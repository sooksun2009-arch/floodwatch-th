"""Automatic approval: when a report may go on the map with no moderator.

The queue exists to keep wrong pins off a safety map. These rules let a report
past it, so the tests that matter most are the ones proving it still cannot be
walked past by a single person filing twice.
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/aa.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["REQUIRE_MODERATION"] = "true"
# Reports per IP per hour — raised so the rate limiter does not mask a result.
os.environ["ANON_REPORT_LIMIT"] = "200"

from datetime import timedelta

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.models import FloodReport, ReportStatus, utcnow
from app.main import app

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


# Two distinct spots, far enough apart that neither can corroborate the other.
SIAM = (13.7460, 100.5340)
BANGNA = (13.6680, 100.6040)


def file(c, lat, lng, *, ip, photo=None, level="shallow", place=None):
    body = {"lat": lat, "lng": lng, "level": level}
    if photo:
        body["photo_url"] = photo
    if place:
        body["place"] = place
    return c.post("/api/reports", json=body, headers={"x-forwarded-for": ip})


def status_of(report_id):
    db = SessionLocal()
    try:
        row = db.get(FloodReport, report_id)
        return (row.status, row.moderation_note) if row else (None, None)
    finally:
        db.close()


with TestClient(app) as c:
    # -------------------------------------------------- the default: hold it
    r = file(c, *SIAM, ip="1.1.1.1")
    check("รายงานเดี่ยว ไม่มีรูป → เข้าคิว", r.status_code == 201
          and r.json()["status"] == "pending", r.text[:200])
    lone_id = r.json()["id"]

    # -------------------------------------------------- photo clears it
    r = file(c, *BANGNA, ip="2.2.2.2", photo="/uploads/x.jpg")
    check("แจ้งพร้อมรูป → ขึ้นแผนที่เอง", r.status_code == 201
          and r.json()["status"] == "approved", r.text[:200])
    check("บันทึกเหตุผลว่าขึ้นเพราะรูป", "รูปถ่าย" in (status_of(r.json()["id"])[1] or ""),
          status_of(r.json()["id"])[1])

    # -------------------------------------------------- the abuse case
    # Same anonymous origin, same spot, twice. This must NOT self-approve.
    r = file(c, 13.7461, 100.5341, ip="1.1.1.1")
    check("คนเดิม IP เดิม แจ้งซ้ำจุดเดิม → ยังเข้าคิว (กันอนุมัติตัวเอง)",
          r.json()["status"] == "pending", r.text[:200])
    check("รายงานแรกยังไม่ถูกดันขึ้นโดยคนเดิม",
          status_of(lone_id)[0] == ReportStatus.pending.value, status_of(lone_id))

    # -------------------------------------------------- a second witness
    r = file(c, 13.7462, 100.5342, ip="3.3.3.3")
    check("คนที่สอง แจ้งจุดเดียวกัน → ขึ้นแผนที่เอง",
          r.json()["status"] == "approved", r.text[:200])
    check("รายงานแรกที่ค้างคิวถูกดันขึ้นด้วย",
          status_of(lone_id)[0] == ReportStatus.approved.value, status_of(lone_id))
    check("รายงานแรกบันทึกเหตุผลที่ถูกดันขึ้น",
          "มีผู้แจ้งจุดเดียวกันเพิ่ม" in (status_of(lone_id)[1] or ""), status_of(lone_id)[1])

    # -------------------------------------------------- distance matters
    # ~1.5 km north of Siam: a different road, so not the same flood.
    r = file(c, 13.7595, 100.5340, ip="4.4.4.4")
    check("ไกลเกินรัศมี → ไม่นับว่ายืนยันกัน", r.json()["status"] == "pending",
          r.text[:200])
    far_id = r.json()["id"]

    # -------------------------------------------------- time matters
    # Age that report past the window, then file beside it from a new IP.
    db = SessionLocal()
    try:
        row = db.get(FloodReport, far_id)
        row.created_at = utcnow() - timedelta(hours=settings.auto_approve_window_hours + 1)
        db.commit()
    finally:
        db.close()

    r = file(c, 13.7596, 100.5341, ip="5.5.5.5")
    check("รายงานเก่าเกินกรอบเวลา → ไม่นับว่ายืนยันกัน",
          r.json()["status"] == "pending", r.text[:200])

    # -------------------------------------------------- rejected rows are inert
    # On its own patch of map: anything still pending nearby would corroborate
    # the new report for real and hide what this is testing.
    r = file(c, 13.5470, 100.2740, ip="10.10.10.10")
    rejected_id = r.json()["id"]
    db = SessionLocal()
    try:
        row = db.get(FloodReport, rejected_id)
        row.status = ReportStatus.rejected.value
        db.commit()
    finally:
        db.close()

    r = file(c, 13.5471, 100.2741, ip="11.11.11.11")
    check("รายงานที่ถูกปฏิเสธแล้ว ไม่นำมายืนยัน", r.json()["status"] == "pending",
          r.text[:200])

    # -------------------------------------------------- a logged-in duplicate
    c.post("/api/auth/register", json={"username": "dup", "password": "pass12345",
                                       "display_name": "ผู้ใช้ทดสอบ"})
    login = c.post("/api/auth/login", json={"username": "dup", "password": "pass12345"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    spot = (13.8200, 100.4400)
    a = c.post("/api/reports", json={"lat": spot[0], "lng": spot[1], "level": "shallow"},
               headers={**auth, "x-forwarded-for": "7.7.7.7"})
    b = c.post("/api/reports", json={"lat": spot[0] + 0.0001, "lng": spot[1], "level": "shallow"},
               headers={**auth, "x-forwarded-for": "8.8.8.8"})
    check("ผู้ใช้เดิมล็อกอิน แจ้งซ้ำคนละ IP → ยังเข้าคิว",
          a.json()["status"] == "pending" and b.json()["status"] == "pending",
          f"{a.json().get('status')} / {b.json().get('status')}")

    # -------------------------------------------------- the map only shows live rows
    r = c.get("/api/reports")
    ids = {item["id"] for item in r.json()["items"]}
    check("แผนที่แสดงเฉพาะที่อนุมัติแล้ว", lone_id in ids and far_id not in ids,
          f"n={len(ids)}")

    # -------------------------------------------------- flagged for review
    r = c.get("/api/reports")
    auto = [i for i in r.json()["items"] if i.get("auto_approved")]
    check("รายงานที่ขึ้นเองถูกติดธงว่ายังไม่มีคนตรวจ", len(auto) >= 2,
          f"n={len(auto)}")

    # -------------------------------------------------- the off switch
    settings.auto_approve_with_photo = False
    settings.auto_approve_corroborated = False
    r = file(c, 13.9000, 100.3000, ip="9.9.9.9", photo="/uploads/y.jpg")
    check("ปิดสวิตช์แล้ว → กลับไปเข้าคิวทุกกรณี", r.json()["status"] == "pending",
          r.text[:200])
    settings.auto_approve_with_photo = True
    settings.auto_approve_corroborated = True

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL AUTO-APPROVAL CHECKS PASSED")
sys.exit(1 if fails else 0)
