"""Asking the assistant about the route already on screen.

The route panel's "ask about a detour" button used to put the endpoint labels
into a sentence. For a GPS fix or a dropped pin those labels are "ตำแหน่งของฉัน"
and "หมุด 13.6999, 100.7135", which the assistant cannot look up, so it
answered "I am not sure where you mean" about a route it was looking at.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/c.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["ORS_API_KEY"] = ""
os.environ["GISTDA_API_KEY"] = ""
os.environ["LONGDO_API_KEY"] = ""

from fastapi.testclient import TestClient

from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


ROUTE = {"origin": {"lat": 13.5743, "lng": 100.7330}, "destination": {"lat": 13.6999, "lng": 100.7135},
         "origin_label": "ตำแหน่งของฉัน", "destination_label": "หมุด 13.6999, 100.7135"}
SENTENCE = "มีทางเลี่ยงจากตำแหน่งของฉันไปหมุด 13.6999, 100.7135ไหม"

with TestClient(app) as c:
    # The failure being fixed: the same sentence, without the coordinates.
    before = c.post("/api/chat", json={"message": SENTENCE}).json()
    check("(ก่อนแก้) ประโยคอย่างเดียว -> แชทไม่เข้าใจว่าที่ไหน", before["intent"] != "route_check",
          before["intent"])

    r = c.post("/api/chat", json={"message": SENTENCE, "route": ROUTE})
    check("ส่งพิกัดของเส้นทางมาด้วย -> ตอบได้", r.status_code == 200, r.text[:200])
    d = r.json()
    check("ตอบเป็นการเช็คเส้นทาง ไม่ใช่ 'ไม่แน่ใจว่าที่ไหน'", d["intent"] == "route_check", d["intent"])
    check("เรียกชื่อต้นทางปลายทางตามที่ผู้ใช้เห็น",
          "ตำแหน่งของฉัน" in d["answer"] and "หมุด 13.6999" in d["answer"], d["answer"][:200])
    check("ส่งข้อมูลเส้นทางกลับไปให้แผนที่", d.get("route") is not None)

    bad = {**ROUTE, "destination": {"lat": 35.0, "lng": 139.0}}
    r = c.post("/api/chat", json={"message": SENTENCE, "route": bad})
    check("พิกัดนอกประเทศไทย -> บอกว่าตรวจไม่สำเร็จ ไม่พัง",
          r.status_code == 200 and r.json()["intent"] == "route_error", r.text[:200])

    r = c.post("/api/chat", json={"message": "จากบางนาไปรามคำแหง ท่วมไหม"})
    check("ถามแบบเดิม (ไม่มีพิกัด) ยังใช้ได้", r.status_code == 200, r.text[:200])

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL CHAT-ROUTE CHECKS PASSED")
sys.exit(1 if fails else 0)
