"""Telling "the source is quiet tonight" apart from "our sync is dead".

Both look identical through a count of fresh stations, and the alert asserted
the second whenever the first happened — waking the owner at 4am about the
national gauge feed going quiet overnight, which nobody can act on. The summary
now carries when the freshest reading was *taken*, and a short history of runs.
"""
import os
import sys
import tempfile
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/s.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
# Off in production too, and without it this test reaches the real Bangkok
# drainage site, which answers 403 and made every run look like a failure.
os.environ["SYNC_BMA_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"

import asyncio

from fastapi.testclient import TestClient

from app import stations
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import WaterStation, utcnow

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def add(db, ref, hours_ago):
    db.add(WaterStation(source="thaiwater", external_id=ref, name=f"สถานี {ref}",
                        lat=13.7, lng=100.5, measured_at=utcnow() - timedelta(hours=hours_ago),
                        synced_at=utcnow()))


with TestClient(app) as c:
    with SessionLocal() as db:
        add(db, "a", 0.5)    # fresh
        add(db, "b", 2)      # fresh
        add(db, "c", 9)      # stale
        db.commit()

    body = c.get("/api/stations/summary").json()
    check("สรุปบอกเวลาที่วัดล่าสุด (ไม่ใช่แค่เวลาที่เราไปดึง)",
          body.get("newest_measured_at") is not None, body.get("newest_measured_at"))
    check("บอกเกณฑ์ที่ใช้ตัดสินว่าค้าง", body.get("stale_after_hours") == settings.station_stale_hours,
          body.get("stale_after_hours"))
    check("นับสด/ค้างถูกต้อง", (body["fresh"], body["stale"]) == (2, 1), body)

    # The overnight case: every reading old, but our sync is working fine.
    with SessionLocal() as db:
        for row in db.query(WaterStation).all():
            row.measured_at = utcnow() - timedelta(hours=8)
        db.commit()
    quiet = c.get("/api/stations/summary").json()
    check("ต้นทางเงียบ -> สด 0 แต่ยังบอกได้ว่าข้อมูลล่าสุดเก่าแค่ไหน",
          quiet["fresh"] == 0 and quiet["newest_measured_at"] is not None, quiet)
    check("และไม่มีแหล่งไหนรายงานว่าล้มเหลว",
          all(v.get("ok") is not False for v in (quiet.get("sources") or {}).values()),
          quiet.get("sources"))

    # ------------------------------------------------- run history
    stations.SYNC_HISTORY.clear()

    async def ok_sync(db):
        return {"ok": True, "created": 0, "updated": 806}

    real = stations.sync
    stations.sync = ok_sync
    with SessionLocal() as db:
        asyncio.run(stations.sync_all(db))
        asyncio.run(stations.sync_all(db))

        async def bad_sync(db_):
            return {"ok": False, "created": 0, "updated": 0, "error": "ConnectTimeout"}

        stations.sync = bad_sync
        asyncio.run(stations.sync_all(db))
    stations.sync = real

    history = c.get("/api/stations/summary").json()["recent_syncs"]
    check("เก็บประวัติการซิงก์หลายรอบ ไม่ใช่แค่รอบล่าสุด", len(history) == 3, len(history))
    check("แต่ละรอบบอกว่าสำเร็จไหม และข้อมูลล่าสุดเก่าแค่ไหนตอนนั้น",
          [h["ok"] for h in history] == [True, True, False]
          and all("newest_measured_at" in h for h in history), history)
    check("รอบที่ล้มเหลวมีสาเหตุให้อ่าน",
          c.get("/api/stations/summary").json()["sources"]["thaiwater"]["error"] == "ConnectTimeout")

    # ------------------------------------------------- the streak, not the last run
    def run(ok):
        stations.SYNC_HISTORY.append({"at": utcnow(), "ok": ok})

    stations.SYNC_HISTORY.clear()
    for ok in (True, True, False):
        run(ok)
    one = c.get("/api/stations/summary").json()
    check("ล้มเหลวรอบเดียว -> นับสตรีค 1", one["consecutive_failures"] == 1, one["consecutive_failures"])

    run(True)
    healed = c.get("/api/stations/summary").json()
    check("สำเร็จแล้ว -> สตรีคกลับเป็น 0 (หายเอง ไม่ต้องปลุกใคร)",
          healed["consecutive_failures"] == 0, healed["consecutive_failures"])

    for _ in range(4):
        run(False)
    down = c.get("/api/stations/summary").json()
    check("ล้มเหลวติดกัน 4 รอบ -> สตรีค 4", down["consecutive_failures"] == 4, down["consecutive_failures"])
    check("และบอกเวลาที่ซิงก์สำเร็จล่าสุด", down["last_success_at"] is not None, down["last_success_at"])

    stations.SYNC_HISTORY.clear()
    empty = c.get("/api/stations/summary").json()
    check("เพิ่งรีสตาร์ท ไม่มีประวัติ -> 0 รอบ ไม่มีเวลาสำเร็จ (ไม่ปลุกมั่ว)",
          empty["consecutive_failures"] == 0 and empty["last_success_at"] is None, empty)

    for _ in range(30):
        stations.SYNC_HISTORY.append({"at": utcnow(), "ok": True})
    check("ประวัติไม่โตไม่สิ้นสุด (กันหน่วยความจำบวม)",
          len(c.get("/api/stations/summary").json()["recent_syncs"]) <= 24)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL STALE-ALERT CHECKS PASSED")
sys.exit(1 if fails else 0)
