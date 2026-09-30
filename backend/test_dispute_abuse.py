"""Three strangers must not be able to delete a flood warning.

A report used to be taken off the public map once three people disputed it,
with no person involved. That is cheap to do — three addresses — and the cost
of it working is a reader who sees clear road where there is water. Filing a
warning should be cheap; withdrawing one should need a moderator.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/d.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["SYNC_BMA_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"
os.environ["REQUIRE_MODERATION"] = "false"
os.environ["REQUIRE_PHOTO"] = "false"
os.environ["ANON_REPORT_LIMIT"] = "50"

from fastapi.testclient import TestClient

from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def on_map(client, report_id):
    """Is this pin among what the public map hands out?"""
    return any(r["id"] == report_id for r in client.get("/api/reports?limit=500").json()["items"])


with TestClient(app) as c:
    made = c.post("/api/reports",
                  json={"lat": 13.7460, "lng": 100.5340, "level": "severe", "depth_cm": 70,
                        "place": "ถนนทดสอบ น้ำลึก ปากซอย 9"},
                  headers={"x-forwarded-for": "1.2.3.4"})
    check("แจ้งน้ำท่วมได้", made.status_code == 201, made.text[:200])
    rid = made.json()["id"]
    check("ขึ้นแผนที่แล้ว", on_map(c, rid))

    # The attack: three addresses, three taps on "the water has gone".
    for i in range(3):
        r = c.post(f"/api/reports/{rid}/vote", json={"vote": "dispute"},
                   headers={"x-forwarded-for": f"9.9.9.{i}"})
        check(f"โหวตแย้งจาก IP ที่ {i + 1} ผ่าน", r.status_code == 200, r.text[:150])

    after = c.get(f"/api/reports/{rid}").json()
    check("แย้งครบ 3 ราย -> หมุดยังอยู่บนแผนที่ (ไม่ถูกลบอัตโนมัติ)", on_map(c, rid), after["status"])
    check("สถานะยังเป็น approved ไม่ถูกดึงกลับเงียบ ๆ", after["status"] == "approved", after["status"])
    check("แต่ติดธงว่ารอตรวจสอบ", after["needs_review"] is True, after)
    # Read from the table: moderation_note holds whatever a moderator typed,
    # so it is deliberately not in the public schema.
    from app.database import SessionLocal
    from app.models import FloodReport

    with SessionLocal() as db:
        note = db.get(FloodReport, rid).moderation_note or ""
    check("บอกเหตุผลไว้ให้ผู้ดูแลอ่าน", "แย้ง" in note, note)

    # And a person has to be told, through the count the alert already watches.
    login = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    check("เข้าคิวให้ผู้ดูแลตัดสิน",
          any(r["id"] == rid for r in c.get("/api/admin/queue", headers=auth).json()["items"]))
    check("นับรวมในตัวเลขที่ Telegram เฝ้าอยู่ (ไม่ต้องแก้ Apps Script)",
          c.get("/api/stats/summary").json()["pending_moderation"] >= 1)

    # One person cannot stack votes by voting again from the same address.
    before = c.get(f"/api/reports/{rid}").json()["dispute_count"]
    c.post(f"/api/reports/{rid}/vote", json={"vote": "dispute"},
           headers={"x-forwarded-for": "9.9.9.0"})
    check("โหวตซ้ำจาก IP เดิม -> ไม่เพิ่มยอด",
          c.get(f"/api/reports/{rid}").json()["dispute_count"] == before, before)

    # The moderator decides, either way, and it leaves the queue.
    c.post(f"/api/admin/reports/{rid}/moderate", json={"status": "approved", "note": "ตรวจแล้วยังท่วม"},
           headers=auth)
    settled = c.get(f"/api/reports/{rid}").json()
    check("ผู้ดูแลยืนยันว่ายังท่วม -> ธงถูกปลด", settled["needs_review"] is False, settled)
    check("และยังอยู่บนแผนที่", on_map(c, rid))
    check("ออกจากคิวแล้ว",
          not any(r["id"] == rid for r in c.get("/api/admin/queue", headers=auth).json()["items"]))

    c.post(f"/api/admin/reports/{rid}/moderate", json={"status": "rejected", "note": "น้ำลดแล้วจริง"},
           headers=auth)
    check("ถ้าน้ำลดจริง ผู้ดูแลลบได้ -> หายจากแผนที่", not on_map(c, rid))

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL DISPUTE-ABUSE CHECKS PASSED")
sys.exit(1 if fails else 0)
