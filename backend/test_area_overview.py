"""The "your area" overview: one status per province, built from reports,
gauges and cameras, and never needing the reader's position."""
import os
import sys
import tempfile
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/a.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["LONGDO_API_KEY"] = ""

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import area_overview
from app.database import SessionLocal
from app.main import app
from app.models import Area, FloodReport, WaterStation, utcnow

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def fresh(client):
    area_overview._cache.update(at=0.0, value=None)
    r = client.get("/api/stats/provinces-overview")
    return r, {p["name_th"]: p for p in r.json()["provinces"]}


check("ตัดคำนำหน้าชื่อจังหวัด", area_overview.norm("จังหวัดระยอง") == "ระยอง"
      and area_overview.norm("จ.ระยอง") == "ระยอง"
      and area_overview.norm("กทม.") == "กรุงเทพมหานคร")

with TestClient(app) as c:
    with SessionLocal() as db:
        # Start from a known-empty state, not whatever the demo seed filed.
        db.execute(delete(FloodReport))
        db.commit()
        names = [a.name_th for a in db.execute(
            select(Area).where(Area.kind == "province", Area.lat.is_not(None))).scalars()]
        check("มีจังหวัดพร้อมพิกัดให้ทดสอบ", len(names) >= 3, names)
        quiet, watched, flooded = names[0], names[1], names[2]
        by_name = {a.name_th: a for a in db.execute(select(Area)).scalars()}

        def report(province, level, passable=None):
            a = by_name[province]
            db.add(FloodReport(lat=a.lat, lng=a.lng, province_id=a.id, place="ทดสอบ",
                               level=level, passable=passable, status="approved",
                               expires_at=utcnow() + timedelta(hours=6)))

        report(watched, "shallow")
        report(watched, "normal")   # "water gone" must not count as a flood
        report(flooded, "severe")
        a = by_name[watched]
        for i, over in enumerate((True, False)):
            db.add(WaterStation(source="t", external_id=f"w{i}", name="s", lat=a.lat, lng=a.lng,
                                province_name=f"จังหวัด{watched}", is_overflowing=over,
                                measured_at=utcnow()))
        # A stale overflowing gauge is not current evidence.
        db.add(WaterStation(source="t", external_id="old", name="s", lat=a.lat, lng=a.lng,
                            province_name=quiet, is_overflowing=True,
                            measured_at=utcnow() - timedelta(days=30)))
        db.commit()

    r, rows = fresh(c)
    check("เปิดได้โดยไม่ต้องล็อกอิน", r.status_code == 200, r.status_code)
    check("ส่งพิกัดกลางจังหวัดมาด้วย (ให้เบราว์เซอร์หาจังหวัดเอง)",
          all(p["lat"] and p["lng"] for p in rows.values()))
    check("จังหวัดที่ไม่มีอะไร -> ปกติ (สถานีเก่าไม่นับ)", rows[quiet]["status"] == "normal",
          rows[quiet])
    check("มีรายงาน + ล้นตลิ่ง -> เฝ้าระวัง", rows[watched]["status"] == "watch", rows[watched])
    check("รายงาน 'น้ำลดแล้ว' ไม่ถูกนับเป็นน้ำท่วม", rows[watched]["reports"] == 1,
          rows[watched])
    check("จับชื่อจังหวัดของสถานีที่มีคำว่า 'จังหวัด' นำหน้าได้",
          rows[watched]["overflowing"] == 1 and rows[watched]["stations"] == 2, rows[watched])
    check("น้ำเกิน 60 ซม. -> อันตราย", rows[flooded]["status"] == "danger", rows[flooded])
    check("อันตรายขึ้นก่อนในรายการ", r.json()["provinces"][0]["name_th"] == flooded)
    check("ไม่มีคีย์ฝน -> ไม่รู้ (null) ไม่ใช่ 0",
          r.json()["rain_known"] is False and rows[quiet]["raining"] is None, rows[quiet])
    check("ไม่มีข้อมูลรายคน (ชื่อ/IP ผู้แจ้ง)",
          "reporter" not in r.text and "ip" not in {k for p in rows.values() for k in p})

    with SessionLocal() as db:
        a = db.execute(select(Area).where(Area.name_th == quiet)).scalar_one()
        for i in range(3):
            db.add(WaterStation(source="t", external_id=f"q{i}", name="s", lat=a.lat,
                                lng=a.lng, province_name=quiet, is_overflowing=True,
                                measured_at=utcnow()))
        db.commit()
    _, rows = fresh(c)
    check("ล้นตลิ่งหลายจุดแต่ไม่มีใครแจ้งว่าผ่านไม่ได้ -> เฝ้าระวัง ไม่ใช่อันตราย",
          rows[quiet]["status"] == "watch", rows[quiet])

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL AREA-OVERVIEW CHECKS PASSED")
sys.exit(1 if fails else 0)
