"""A restart must not ask the gauge source again if we asked it minutes ago.

During a deploy the old and the new container overlap, so syncing on boot was
a second request within minutes of the first. On 2026-10-03, a day of several
deploys, those were exactly the requests the source answered with 429 — and
each one set off an alert.
"""
import os
import sys
import tempfile
import time
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/b.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "true"
os.environ["SYNC_BMA_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"
os.environ["STATION_SYNC_INTERVAL_MIN"] = "15"

from fastapi.testclient import TestClient

from app import stations
from app.database import Base, SessionLocal, engine
from app.models import WaterStation, utcnow

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


calls = []


async def counting_sync(db):
    calls.append(time.monotonic())
    return {"thaiwater": {"ok": True}}


stations.sync_all = counting_sync

Base.metadata.create_all(engine)


def boot_and_count(synced_minutes_ago):
    calls.clear()
    with SessionLocal() as db:
        db.query(WaterStation).delete()
        if synced_minutes_ago is not None:
            db.add(WaterStation(source="t", external_id="x", name="x", lat=13.7, lng=100.5,
                                measured_at=utcnow(),
                                synced_at=utcnow() - timedelta(minutes=synced_minutes_ago)))
        db.commit()
    from app.main import app

    with TestClient(app):
        time.sleep(3)
    return len(calls)


check("เพิ่งซิงก์ไป 2 นาทีก่อน -> เริ่มเครื่องแล้วไม่ยิงต้นทางซ้ำทันที",
      boot_and_count(2) == 0, calls)
check("ซิงก์ล่าสุด 40 นาทีก่อน -> เริ่มเครื่องแล้วซิงก์ทันที",
      boot_and_count(40) == 1, calls)
check("ฐานข้อมูลว่าง (deploy ครั้งแรก) -> ซิงก์ทันที", boot_and_count(None) == 1, calls)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL BOOT-SYNC CHECKS PASSED")
sys.exit(1 if fails else 0)
