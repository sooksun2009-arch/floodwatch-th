"""When the national gauge feed is down, say "unknown" — never "all clear".

For 33 hours from 2026-10-02 the source's own database was out of connection
slots. Our sync failed correctly and kept the last readings, labelled stale.
But the "your area" card dropped stale gauges from its counts, so every one of
the 77 provinces read "nothing reported" — including three that had been on
watch the day before. An absence of data was being shown as an absence of
flooding, which is the one mistake this app cannot afford.
"""
import os
import sys
import tempfile
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/o.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["SYNC_BMA_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["ORS_API_KEY"] = ""
os.environ["LONGDO_API_KEY"] = ""

import asyncio

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import area_overview, stations
from app.database import SessionLocal
from app.main import app
from app.models import Area, WaterStation, utcnow

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def overview(client):
    area_overview._cache.update(at=0.0, value=None)
    body = client.get("/api/stats/provinces-overview").json()
    return body, {p["name_th"]: p for p in body["provinces"]}


with TestClient(app) as c:
    with SessionLocal() as db:
        db.execute(delete(WaterStation))
        names = [a.name_th for a in db.execute(
            select(Area).where(Area.kind == "province", Area.lat.is_not(None))).scalars()]
        ayutthaya, quiet = names[0], names[1]

        def gauge(ref, province, hours_ago, over):
            db.add(WaterStation(source="t", external_id=ref, name=ref, lat=14.3, lng=100.5,
                                province_name=province, is_overflowing=over,
                                measured_at=utcnow() - timedelta(hours=hours_ago),
                                synced_at=utcnow()))

        # Yesterday: two gauges over their banks. Then the feed died.
        gauge("a1", ayutthaya, 33, True)
        gauge("a2", ayutthaya, 33, True)
        gauge("a3", ayutthaya, 33, False)
        # Another province with a gauge that is simply fine and recent.
        gauge("q1", quiet, 0.5, False)
        db.commit()

    body, rows = overview(c)
    a, q = rows[ayutthaya], rows[quiet]

    check("จังหวัดที่เครื่องวัดเงียบไป 33 ชม. -> 'ไม่ทราบ' ไม่ใช่ 'ปกติ'",
          a["status"] == "unknown", a["status"])
    check("และไม่นับค่าเก่าเป็นค่าปัจจุบัน (ล้นตลิ่งตอนนี้ = 0)", a["overflowing"] == 0, a)
    check("แต่ยังบอกได้ว่าครั้งสุดท้ายที่วัดได้ ล้นตลิ่ง 2 สถานี",
          a["overflowing_last_known"] == 2, a)
    check("จังหวัดที่เครื่องวัดยังรายงานสด -> ปกติได้ตามจริง", q["status"] == "normal", q)
    check("จังหวัดที่ไม่มีเครื่องวัดเลย -> ไม่ถูกตีเป็น 'ไม่ทราบ' มั่ว",
          all(p["status"] != "unknown" for p in body["provinces"] if p["stations_total"] == 0))
    check("บอกอายุข้อมูลล่าสุดของทั้งประเทศ (เพื่อเอาไปบอกผู้ใช้)",
          body.get("gauge_age_hours") is not None, body.get("gauge_age_hours"))

    # An unknown province must never be ranked as if it were calm, nor above danger.
    order = [p["status"] for p in body["provinces"]]
    check("เรียง: อันตราย > เฝ้าระวัง > ไม่ทราบ > ปกติ",
          order == sorted(order, key=lambda s: {"danger": 0, "watch": 1, "unknown": 2, "normal": 3}[s]),
          order[:6])

    # A real report still wins over missing gauges.
    with SessionLocal() as db:
        from app.models import FloodReport
        area = db.execute(select(Area).where(Area.name_th == ayutthaya)).scalar_one()
        db.add(FloodReport(lat=area.lat, lng=area.lng, province_id=area.id, place="ทดสอบ",
                           level="severe", status="approved",
                           expires_at=utcnow() + timedelta(hours=6)))
        db.commit()
    _, rows = overview(c)
    check("มีรายงานรถผ่านไม่ได้ -> อันตราย แม้เครื่องวัดจะเงียบ", rows[ayutthaya]["status"] == "danger",
          rows[ayutthaya]["status"])

    # ------------------------------------------------- route check
    from app import routing
    from app.models import FloodReport as FR

    with SessionLocal() as db:
        db.execute(delete(FR))
        db.execute(delete(WaterStation))
        # One stale overflowing gauge sitting right on the route, one fresh.
        for ref, hours in (("old", 33), ("new", 0.5)):
            db.add(WaterStation(source="t", external_id=ref, name=f"สถานี {ref}", lat=13.70,
                                lng=100.60 + (0.0 if ref == "old" else 0.003),
                                province_name=ayutthaya, is_overflowing=True,
                                measured_at=utcnow() - timedelta(hours=hours),
                                synced_at=utcnow()))
        db.commit()
        out = asyncio.run(routing.check_route(db, (13.70, 100.58), (13.70, 100.63)))

    # The route's station entries carry the serialised model, not a plain dict.
    shown = [(s["station"].name if hasattr(s["station"], "name") else s["station"]["name"])
             for s in out["routes"][0]["stations"]]
    check("สถานีสดที่ล้นตลิ่งใกล้เส้นทาง -> แสดง", "สถานี new" in shown, shown)
    check("สถานีที่ข้อมูลเก่า 33 ชม. -> ไม่เอามาบอกว่า 'กำลังล้นตลิ่ง'", "สถานี old" not in shown, shown)
    check("แต่บอกผู้ใช้ว่ามีสถานีที่ข้อมูลเก่าจึงไม่ได้นำมาประกอบ",
          "ไม่ได้นำสถานีวัดน้ำ" in (out["degraded"] or ""), out["degraded"])

    # ------------------------------------------------- the source's own failure
    async def broken_source(*a, **k):
        class Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"waterlevel_data": {"result": "NO", "data": {
                    "Severity": "FATAL", "Code": "53300",
                    "Message": "remaining connection slots are reserved"}}}
        return Resp()

    real_get = httpx.AsyncClient.get
    httpx.AsyncClient.get = broken_source
    try:
        with SessionLocal() as db:
            result = asyncio.run(stations.sync(db))
    finally:
        httpx.AsyncClient.get = real_get
    check("ต้นทางตอบ 200 แต่ฐานข้อมูลเขาล่ม -> นับเป็นล้มเหลว ไม่เอามาทับข้อมูลเดิม",
          result["ok"] is False, result)
    check("ข้อความ error สั้น บอกว่าเป็นปัญหาของต้นทาง และมีรหัส",
          "ต้นทางแจ้งว่า" in result["error"] and "53300" in result["error"], result["error"])

    async def too_many(*a, **k):
        class Resp:
            status_code = 429
            request = httpx.Request("GET", "https://api-v3.thaiwater.net/x?secret=1")

            def raise_for_status(self):
                raise httpx.HTTPStatusError("429", request=self.request, response=self)
        return Resp()

    httpx.AsyncClient.get = too_many
    try:
        with SessionLocal() as db:
            result = asyncio.run(stations.sync(db))
    finally:
        httpx.AsyncClient.get = real_get
    check("429 -> error เป็นบรรทัดเดียว ไม่มี URL หรือลิงก์เอกสารยาว ๆ",
          result["error"] == "ต้นทางตอบ HTTP 429", result["error"])

    with SessionLocal() as db:
        count = db.execute(select(WaterStation)).scalars().all()
    check("ข้อมูลเดิมยังอยู่ครบหลังซิงก์ล้มเหลว", len(count) == 2, len(count))

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL GAUGE-OUTAGE CHECKS PASSED")
sys.exit(1 if fails else 0)
