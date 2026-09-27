"""Flood-avoidance routing: polygon construction and the no-key fallback."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["ORS_API_KEY"] = ""          # not configured on purpose

from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.routing import avoid_polygons
from app.seed import run_seed

Base.metadata.create_all(bind=engine)
s = SessionLocal(); run_seed(s)

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond: fails.append(name)

# Demo data has one 45cm (deep) and one 70cm (closed) report, plus a 22cm and an
# 8cm one that must NOT generate no-go zones.
poly = avoid_polygons(s, (13.0, 100.0, 14.5, 101.0))
check("polygons built for blocking reports", poly is not None and len(poly["coordinates"]) == 2,
      f"n={len(poly['coordinates']) if poly else None}")
check("polygon is a closed ring of 9 points",
      poly and len(poly["coordinates"][0][0]) == 9 and
      poly["coordinates"][0][0][0] == poly["coordinates"][0][0][-1],
      str(poly["coordinates"][0][0][:2]) if poly else "")
# Ring points are [lng, lat]. Point 0 sits due east, point 4 due west, so the
# half-span between them is the radius in degrees of longitude (~0.0011 at this
# latitude for 120 m). Points 2 and 6 give the same in latitude (~0.00108).
ring = poly["coordinates"][0][0] if poly else []
half_lng = abs(ring[0][0] - ring[4][0]) / 2 if ring else 0
half_lat = abs(ring[2][1] - ring[6][1]) / 2 if ring else 0
check("polygon half-width is about 120 m east-west", 0.0009 < half_lng < 0.0014, half_lng)
check("polygon half-height is about 120 m north-south", 0.0009 < half_lat < 0.0013, half_lat)
check("empty area yields no polygons",
      avoid_polygons(s, (18.0, 98.0, 19.0, 99.0)) is None)
s.close()

with TestClient(app) as c:
    r = c.post("/api/route/check", json={
        "origin": {"lat": 13.7650, "lng": 100.6360},
        "destination": {"lat": 13.8060, "lng": 100.5950}})
    check("route check still succeeds without an ORS key", r.status_code == 200, r.text[:200])
    body = r.json()
    check("verdict is risky or worse", body["verdict"] in ("risky", "blocked"), body["verdict"])
    check("missing ORS key is explained to the user",
          "OpenRouteService" in (body["degraded"] or ""), body["degraded"])
    check("no phantom avoidance route was added",
          all("เลี่ยงน้ำท่วม" not in r["label"] for r in body["routes"]),
          [r["label"] for r in body["routes"]])

    # A clear route must not trigger avoidance logic or its warning at all.
    r2 = c.post("/api/route/check", json={
        "origin": {"lat": 18.7880, "lng": 98.9850},
        "destination": {"lat": 18.8000, "lng": 99.0000}})
    body2 = r2.json()
    check("clear route mentions no ORS warning",
          "OpenRouteService" not in (body2["degraded"] or ""), body2["degraded"])

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL AVOIDANCE-ROUTING CHECKS PASSED")
