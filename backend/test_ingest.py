"""Relayed Bangkok gauge readings.

The drainage site drops connections from outside Thailand, so the deployment
cannot fetch these itself and something that can reach it posts them instead.
That makes this an endpoint which writes to a public safety map on the strength
of a shared secret, so most of what is checked here is what it refuses.
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/i.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import WaterStation

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


SUMMARY = """
<table><tr><th>เขต</th><th>คลอง</th></tr>
<tr><td>บางเขน</td><td>คลองกระเฉด</td><td>ค.กระเฉด(รามอินทรา)</td>
    <td>27/09/2569 15:20</td><td>ปกติ</td><td>-0.16</td><td>-</td><td>-</td>
    <td><a href="/water/StationDetail?id=265">ดู</a></td></tr>
<tr><td>บางกะปิ</td><td>คลองกะจะ</td><td>ค.กะจะ ถ.พระราม 9</td>
    <td>27/09/2569 15:20</td><td>วิกฤติ</td><td>2.40</td><td>-</td><td>-</td>
    <td><a href="/water/StationDetail?id=138">ดู</a></td></tr>
</table>
"""

TOKEN = "relay-secret-token"
URL = "/api/stations/bma/ingest"


def count_bma():
    db = SessionLocal()
    try:
        return db.query(WaterStation).filter(WaterStation.source == "bma").count()
    finally:
        db.close()


with TestClient(app) as c:
    # ------------------------------------------------ closed by default
    settings.ingest_token = ""
    r = c.post(URL, json={"summary_html": SUMMARY})
    check("ยังไม่ตั้งโทเคน → ปิดสนิท (403)", r.status_code == 403, r.status_code)
    check("และไม่มีอะไรถูกบันทึก", count_bma() == 0, count_bma())

    settings.ingest_token = TOKEN

    # ------------------------------------------------ authentication
    r = c.post(URL, json={"summary_html": SUMMARY})
    check("ไม่ส่งโทเคน → 401", r.status_code == 401, r.status_code)

    r = c.post(URL, json={"summary_html": SUMMARY},
               headers={"Authorization": "Bearer wrong-token"})
    check("โทเคนผิด → 401", r.status_code == 401, r.status_code)

    r = c.post(URL, json={"summary_html": SUMMARY},
               headers={"Authorization": f"Bearer {TOKEN} "})
    check("โทเคนมีช่องว่างต่อท้าย → ยังผ่าน (คนก๊อปวางมักติดมา)",
          r.status_code == 200, f"{r.status_code} {r.text[:120]}")

    check("ยังไม่มีพิกัด → ยังไม่บันทึกสถานี", count_bma() == 0, count_bma())

    auth = {"Authorization": f"Bearer {TOKEN}"}

    # ------------------------------------------------ input validation
    r = c.post(URL, json={}, headers=auth)
    check("ไม่ส่ง summary_html → 400", r.status_code == 400, r.status_code)

    r = c.post(URL, json={"summary_html": "   "}, headers=auth)
    check("summary_html ว่าง → 400", r.status_code == 400, r.status_code)

    r = c.post(URL, json={"summary_html": "<html>ไม่ใช่หน้าที่ต้องการ</html>"}, headers=auth)
    check("ส่งหน้าผิดมา → 400 พร้อมบอกเหตุผล",
          r.status_code == 400 and "Summary" in r.text, f"{r.status_code} {r.text[:150]}")

    r = c.post(URL, json={"summary_html": SUMMARY, "coords": "ไม่ใช่ object"}, headers=auth)
    check("coords ผิดชนิด → 400", r.status_code == 400, r.status_code)

    # ------------------------------------------------ the happy path
    r = c.post(URL, json={
        "summary_html": SUMMARY,
        "coords": {
            "265": {"lat": 13.8512, "lng": 100.6231, "bank_level": 0.9},
            "138": {"lat": 13.7550, "lng": 100.5900},
        },
    }, headers=auth)
    body = r.json()
    check("ส่งครบ → บันทึกสำเร็จ", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    check("รับพิกัดครบ 2 สถานี", body.get("coords_accepted") == 2, body)
    check("สร้างสถานีจริงในฐานข้อมูล", count_bma() == 2, count_bma())

    r = c.get("/api/stations")
    names = [s["name"] for s in r.json()]
    check("สถานี กทม. ขึ้นบน API สาธารณะแล้ว",
          any("กะจะ" in n for n in names), names[:4])
    agencies = {s.get("agency") for s in r.json()}
    check("ติดป้ายหน่วยงานว่าเป็นของ กทม. (สนน. = สำนักการระบายน้ำ)",
          any(a and "กทม." in a for a in agencies), agencies)

    # ------------------------------------------------ repeat runs
    r = c.post(URL, json={"summary_html": SUMMARY}, headers=auth)
    body = r.json()
    check("ส่งซ้ำ → อัปเดต ไม่สร้างซ้ำ",
          count_bma() == 2 and body.get("updated") == 2, f"{count_bma()} {body}")
    check("พิกัดที่เคยส่งแล้ว ไม่ต้องส่งซ้ำทุกรอบ", body.get("coords_accepted") == 0, body)
    check("ไม่มีสถานีไหนค้างรอพิกัดแล้ว", body.get("need_coords") == [], body)

    # ------------------------------------------------ bad coordinates
    r = c.post(URL, json={
        "summary_html": SUMMARY,
        "coords": {"999": {"lat": 48.8584, "lng": 2.2945}},   # Paris
    }, headers=auth)
    check("พิกัดนอกประเทศไทย → ไม่รับ", r.json().get("coords_accepted") == 0, r.json())

    r = c.post(URL, json={
        "summary_html": SUMMARY,
        "coords": {"998": {"lat": "ไม่ใช่ตัวเลข", "lng": 100.5}},
    }, headers=auth)
    check("พิกัดที่ไม่ใช่ตัวเลข → ข้ามไป ไม่ระเบิด",
          r.status_code == 200 and r.json().get("coords_accepted") == 0, r.text[:150])

    # ------------------------------------------------ what to fetch next
    db = SessionLocal()
    try:
        db.query(WaterStation).filter(WaterStation.external_id == "138").delete()
        db.commit()
    finally:
        db.close()
    r = c.post(URL, json={"summary_html": SUMMARY}, headers=auth)
    check("บอกรีเลย์ว่าสถานีไหนยังขาดพิกัด",
          r.json().get("need_coords") == ["138"], r.json().get("need_coords"))

    settings.ingest_token = ""

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL INGEST CHECKS PASSED")
sys.exit(1 if fails else 0)
