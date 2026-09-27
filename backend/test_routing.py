"""Route engine and chatbot tests.

OSRM is pointed at an unreachable host so the straight-line fallback path is the
one under test — that is the path that must work when the routing service is
down during a storm.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["GEOCODE_ENABLED"] = "false"          # gazetteer only, no network
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"  # discard port: always refused
os.environ["SEED_DEMO_DATA"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.chatbot import extract_route_endpoints, match_place, route  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.routing import path_length_km, point_to_path_km  # noqa: E402
from app.seed import run_seed  # noqa: E402

# The direct-session tests below run before any request, so the schema and seed
# data have to exist before the app's own lifespan hook would create them.
Base.metadata.create_all(bind=engine)
_setup = SessionLocal()
try:
    run_seed(_setup)
finally:
    _setup.close()

fails: list[str] = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- geometry

# A 1-degree-of-latitude leg is ~111.3 km.
leg = [(13.0, 100.0), (14.0, 100.0)]
check("path length ~111km", 110.0 < path_length_km(leg) < 112.5, path_length_km(leg))

# A point due east of the midpoint: 0.01 deg lng at lat 13.5 is ~1.08 km.
dist, along = point_to_path_km(13.5, 100.01, leg)
check("perpendicular distance ~1.08km", 1.0 < dist < 1.15, dist)
check("along-track is halfway", 54 < along < 57, along)

# A point beyond the far end clamps to the endpoint rather than extrapolating.
dist_end, along_end = point_to_path_km(14.5, 100.0, leg)
check("clamps past endpoint", 54 < dist_end < 57 and along_end > 110,
      f"dist={dist_end} along={along_end}")

# A point exactly on the line has ~zero offset.
dist_on, _ = point_to_path_km(13.5, 100.0, leg)
check("on-line distance ~0", dist_on < 0.01, dist_on)

# ---------------------------------------------------------------- route parsing

cases = [
    ("จากบางนาไปรามคำแหง มีน้ำท่วมไหม", "บางนา", "รามคำแหง"),
    ("จาก ลาดพร้าว ไป สุขุมวิท", "ลาดพร้าว", "สุขุมวิท"),
    ("ลาดพร้าว -> ดอนเมือง", "ลาดพร้าว", "ดอนเมือง"),
    ("บางกะปิไปจตุจักรท่วมไหม", "บางกะปิ", "จตุจักร"),
    ("จะไปจากดินแดงถึงบางซื่อ ท่วมมั้ยครับ", "ดินแดง", "บางซื่อ"),
]
for text, want_a, want_b in cases:
    got = extract_route_endpoints(text)
    check(f"parse: {text[:34]}", got is not None and got[0] == want_a and got[1] == want_b,
          f"got={got} want=({want_a}, {want_b})")

check("non-route sentence is not parsed as a route",
      extract_route_endpoints("น้ำท่วมใกล้ฉันไหม") is None,
      str(extract_route_endpoints("น้ำท่วมใกล้ฉันไหม")))

# ---------------------------------------------------------------- gazetteer

db = SessionLocal()
try:
    m = match_place(db, "น้ำท่วมแถวลาดพร้าวไหม")
    check("match district inside a sentence", m is not None and m.name == "ลาดพร้าว",
          str(m))
    m2 = match_place(db, "สถานการณ์จังหวัดเชียงใหม่")
    check("match province with จังหวัด prefix", m2 is not None and m2.name == "เชียงใหม่", str(m2))
    m3 = match_place(db, "เชียงไหม่ท่วมไหม")   # misspelled on purpose
    check("fuzzy match tolerates a typo", m3 is not None and m3.name == "เชียงใหม่", str(m3))
    check("nonsense matches nothing", match_place(db, "xyzqwerty") is None,
          str(match_place(db, "xyzqwerty")))

    r = route(db, "น้ำ 45 ซม ขับผ่านได้ไหม", None, None)
    check("safety intent with depth", r.intent == "safety_advice" and "45" in r.answer,
          f"{r.intent}: {r.answer[:90]}")
    r = route(db, "แจ้งน้ำท่วมยังไง", None, None)
    check("how-to intent", r.intent == "how_to_report", r.intent)
    r = route(db, "ตอนนี้ท่วมหนักที่ไหน", None, None)
    check("worst-areas intent lists demo points",
          r.intent == "worst_areas" and len(r.reports) > 0, f"{r.intent} n={len(r.reports)}")
    r = route(db, "ขอดูกล้อง CCTV แถวบางกะปิ", None, None)
    check("camera intent returns cameras", r.intent == "cameras" and len(r.cameras) > 0,
          f"{r.intent} n={len(r.cameras)}")
    r = route(db, "น้ำท่วมใกล้ฉันไหม", None, None)
    check("near-me without coords asks for location", r.intent == "need_location", r.intent)
    r = route(db, "น้ำท่วมใกล้ฉันไหม", 13.7655, 100.6350)
    check("near-me with coords finds the demo pin",
          r.intent == "flood_near_me" and len(r.reports) > 0, f"{r.intent} n={len(r.reports)}")
finally:
    db.close()

# ---------------------------------------------------------------- API: route check

with TestClient(app) as c:
    # Coordinates spanning two demo flood points (ลำสาลี shallow, ลาดพร้าว deep).
    r = c.post("/api/route/check", json={
        "origin": {"lat": 13.7650, "lng": 100.6360},
        "destination": {"lat": 13.8060, "lng": 100.5950},
    })
    check("route check responds", r.status_code == 200, r.text[:300])
    if r.status_code == 200:
        body = r.json()
        check("fallback is flagged as degraded", bool(body["degraded"]), str(body["degraded"]))
        check("straight-line flag set", body["routes"][0]["is_straight_line"] is True)
        obstacles = body["routes"][0]["obstacles"]
        check("obstacles found on corridor", len(obstacles) >= 1,
              f"n={len(obstacles)} verdict={body['verdict']}")
        check("verdict reflects worst level", body["verdict"] in ("risky", "blocked", "caution"),
              f"{body['verdict']} worst={body['worst_level']}")
        check("obstacles ordered by distance along route",
              [o["along_km"] for o in obstacles] == sorted(o["along_km"] for o in obstacles))
        check("advice mentions kilometre markers", "กม." in body["advice"], body["advice"][:150])
        check("cameras listed along route", len(body["routes"][0]["cameras"]) >= 1,
              f"n={len(body['routes'][0]['cameras'])}")

    # A route far from every demo pin must come back clear.
    r = c.post("/api/route/check", json={
        "origin": {"lat": 18.7880, "lng": 98.9850},
        "destination": {"lat": 18.8000, "lng": 99.0000},
    })
    check("clear route verdict", r.status_code == 200 and r.json()["verdict"] == "clear",
          r.text[:200])
    if r.status_code == 200:
        check("clear advice warns absence is not proof",
              "ไม่ใช่การยืนยัน" in r.json()["advice"], r.json()["advice"][-200:])

    r = c.post("/api/route/check", json={"origin": {"lat": 13.75, "lng": 100.5}})
    check("missing destination rejected", r.status_code == 400, r.text[:150])

    r = c.post("/api/route/check", json={
        "origin": {"lat": 48.85, "lng": 2.35},
        "destination": {"lat": 13.75, "lng": 100.5}})
    check("out-of-country route rejected", r.status_code == 400, r.text[:150])

    # Place names resolved from the gazetteer only (geocoder disabled).
    r = c.post("/api/route/check", json={"origin_text": "บางกะปิ",
                                         "destination_text": "ลาดพร้าว"})
    check("route by place name", r.status_code == 200, r.text[:250])
    if r.status_code == 200:
        check("labels echoed back", r.json()["origin_label"] == "บางกะปิ", r.json().get("origin_label"))

    r = c.post("/api/route/check", json={"origin_text": "zzzz ไม่มีที่นี่",
                                         "destination_text": "ลาดพร้าว"})
    check("unresolvable origin returns 422", r.status_code == 422, r.text[:200])

    # ---------------------------------------------------------------- API: chat
    r = c.post("/api/chat", json={"message": "จากบางกะปิไปลาดพร้าว ท่วมไหม"})
    check("chat handles a route question", r.status_code == 200, r.text[:250])
    if r.status_code == 200:
        body = r.json()
        check("chat route intent", body["intent"] == "route_check", body["intent"])
        check("chat returns route payload", body.get("route") is not None)
        check("chat answer names both endpoints",
              "บางกะปิ" in body["answer"] and "ลาดพร้าว" in body["answer"],
              body["answer"][:150])
        check("chat suggests the return trip",
              any("ขากลับ" in s["label"] for s in body["suggestions"]),
              str(body["suggestions"]))

    r = c.post("/api/chat", json={"message": "สวัสดีครับ"})
    check("greeting falls back to help", r.status_code == 200 and r.json()["intent"] == "help",
          r.text[:150])

    r = c.post("/api/chat", json={"message": "จะไปทำงาน ท่วมไหม"})
    check("trip question without endpoints asks for them",
          r.status_code == 200 and r.json()["intent"] in ("route_need_endpoints", "worst_areas"),
          r.json().get("intent"))

    r = c.post("/api/chat", json={"message": "เช็คเส้นทางแถวลาดพร้าว", "lat": 13.8, "lng": 100.6})
    check("chat always answers something", r.status_code == 200 and len(r.json()["answer"]) > 10,
          r.text[:200])

    r = c.get("/api/chat/starters")
    check("chat starters", r.status_code == 200 and len(r.json()) == 4, r.text[:150])

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL ROUTE + CHATBOT CHECKS PASSED")
