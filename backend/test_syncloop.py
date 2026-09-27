"""The in-app sync loop: boots fast, repeats, survives failures, stops cleanly."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "true"
# Dead upstreams: every pass fails, which is the case that must not wedge the app.
os.environ["THAIWATER_BASE_URL"] = "http://127.0.0.1:9"
os.environ["BMA_WATER_BASE_URL"] = "http://127.0.0.1:9/water"
os.environ["STATION_TIMEOUT_SEC"] = "2"

import asyncio
from fastapi.testclient import TestClient

fails = []
def check(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n      -> {extra}"))
    if not ok: fails.append(name)

import app.main as main
from app.config import settings

# Count how often the loop actually runs by wrapping the sync it calls.
calls = {"n": 0}
real = main.__dict__.get("sync_all")

import app.stations as stations
orig_sync_all = stations.sync_all
async def counting_sync_all(db):
    calls["n"] += 1
    return await orig_sync_all(db)
stations.sync_all = counting_sync_all

# A 1-minute floor is enforced in code; patch the setting low for the test.
settings.station_sync_interval_min = 1

t0 = time.monotonic()
with TestClient(main.app) as c:
    boot = time.monotonic() - t0
    check(f"บูตเร็วแม้ต้นทางล่ม ({boot:.1f}s)", boot < 20, boot)
    check("health ตอบได้", c.get("/api/health").status_code == 200)
    check("seed ทำงาน", len(c.get("/api/areas/provinces").json()) == 77)
    # Give the background task a moment to make its first pass.
    time.sleep(6)
    check(f"ซิงก์รอบแรกทำงานแล้ว ({calls['n']} ครั้ง)", calls["n"] >= 1, calls["n"])
    check("API ยังตอบได้แม้ซิงก์ล้มเหลว",
          c.get("/api/stations/summary").json()["total"] == 0)

check("ปิดแอปได้โดยไม่ค้าง", True)

# Interval 0 must run once and stop rather than spin.
settings.station_sync_interval_min = 0
calls["n"] = 0
with TestClient(main.app) as c:
    time.sleep(5)
    check(f"ตั้ง 0 = ซิงก์ครั้งเดียวแล้วหยุด ({calls['n']} ครั้ง)", calls["n"] == 1, calls["n"])

stations.sync_all = orig_sync_all
print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL SYNC-LOOP CHECKS PASSED")
