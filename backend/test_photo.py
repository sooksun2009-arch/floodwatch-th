"""The photo requirement.

Added after a report reached the live map carrying no place, no reporter name
and no picture — the kind that teaches people the map is not worth checking. A
photo is the difference between a claim and evidence, and it is the one thing
a passer-by can judge for themselves.

It also removes the moderation queue for public reports, because a report with
a photo goes live on its own. That is a consequence worth being deliberate
about, so it is asserted here rather than left to be discovered.
"""
import io, os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/p.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["ANON_REPORT_LIMIT"] = "200"

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def a_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (20, 90, 150)).save(buf, format="JPEG")
    return buf.getvalue()


SPOT = {"lat": 13.7460, "lng": 100.5340, "level": "shallow"}

with TestClient(app) as c:
    settings.require_photo = True

    r = c.post("/api/reports", json=SPOT, headers={"x-forwarded-for": "1.1.1.1"})
    check("ไม่แนบรูป → ถูกปฏิเสธ", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    check("และบอกเหตุผลเป็นภาษาคน ไม่ใช่รหัสข้อผิดพลาด",
          "รูปถ่าย" in r.json().get("detail", ""), r.json().get("detail"))

    r = c.post("/api/reports", json={**SPOT, "photo_url": ""},
               headers={"x-forwarded-for": "1.1.1.2"})
    check("ส่งช่องรูปมาว่าง ๆ → ยังถูกปฏิเสธ", r.status_code == 400, r.status_code)

    # A URL we did not mint was already rejected; the photo gate must not have
    # opened a way around that check.
    r = c.post("/api/reports", json={**SPOT, "photo_url": "https://evil.example/x.jpg"},
               headers={"x-forwarded-for": "1.1.1.3"})
    check("แนบรูปจากที่อื่น → ยังถูกปฏิเสธเหมือนเดิม", r.status_code == 400, r.status_code)

    # The whole path someone actually takes.
    up = c.post("/api/uploads", files={"file": ("f.jpg", a_jpeg(), "image/jpeg")})
    check("อัปโหลดรูปได้", up.status_code == 201, up.text[:120])
    url = up.json()["url"]

    r = c.post("/api/reports", json={**SPOT, "photo_url": url},
               headers={"x-forwarded-for": "1.1.1.4"})
    check("แนบรูปที่อัปโหลดเอง → ผ่าน", r.status_code == 201, r.text[:150])
    check("และขึ้นแผนที่ทันที ไม่เข้าคิวรอคน",
          r.json().get("status") == "approved", r.json().get("status"))

    # The consequence, stated out loud: with the gate up there is nothing left
    # for a moderator to approve.
    stats = c.get("/api/stats/summary").json()
    check("คิวรออนุมัติว่าง เพราะทุกรายงานมีรูปและขึ้นเอง",
          stats["pending_moderation"] == 0, stats)

    # Officials file from desks as well as roadsides, and their word is already
    # vouched for.
    c.post("/api/auth/register", json={"username": "boss", "password": "pass12345"})
    login = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    if login.status_code == 200:
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = c.post("/api/reports", json={**SPOT, "lat": 13.75},
                   headers={**auth, "x-forwarded-for": "1.1.1.5"})
        check("ผู้ดูแลแจ้งโดยไม่มีรูป → ยังได้ (ข้อมูลทางการ)",
              r.status_code == 201, f"{r.status_code} {r.text[:120]}")

    # And the switch back, for a deployment that wants reports without one.
    settings.require_photo = False
    r = c.post("/api/reports", json={**SPOT, "lat": 13.76},
               headers={"x-forwarded-for": "1.1.1.6"})
    check("ปิดสวิตช์ → แจ้งโดยไม่มีรูปได้เหมือนเดิม", r.status_code == 201,
          f"{r.status_code} {r.text[:120]}")
    settings.require_photo = True

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL PHOTO-REQUIREMENT CHECKS PASSED")
sys.exit(1 if fails else 0)
