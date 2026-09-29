"""Gauge-station sync: parsing, upsert idempotency, and the API surface."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

import asyncio
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import WaterStation
from app.seed import run_seed
from app.stations import normalise, upsert

Base.metadata.create_all(bind=engine)
_s = SessionLocal(); run_seed(_s); _s.close()

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond: fails.append(name)

# Freshness is measured against the clock, so the fixture's timestamp has to
# move with it. A hardcoded date passes on the day it is written and starts
# failing the next morning, which is a test reporting the calendar rather than
# the code — and it did exactly that.
from datetime import datetime, timedelta, timezone

_RECENT = (datetime.now(timezone(timedelta(hours=7))) - timedelta(minutes=20))     .strftime("%Y-%m-%d %H:%M")

# A record shaped exactly like the live API returns.
SAMPLE = {
    "id": 1313736250, "waterlevel_datetime": _RECENT,
    "waterlevel_msl": "2.76", "situation_level": 5,
    "diff_wl_bank": "0.56", "diff_wl_bank_text": "ล้นตลิ่ง (ม.)",
    "agency": {"agency_shortname": {"th": "สสน.", "en": "HII"}},
    "basin": {"basin_name": {"th": "ลุ่มน้ำเจ้าพระยา"}},
    "station": {"id": 1394808, "tele_station_name": {"th": "คลองลาดพร้าว วัดบางบัว", "en": "x"},
                "tele_station_lat": 13.85402, "tele_station_long": 100.58746,
                "left_bank": 2.4, "right_bank": 2.2, "min_bank": 2.2},
    "geocode": {"province_name": {"th": "กรุงเทพมหานคร"}, "amphoe_name": {"th": "บางเขน"}},
}

r = normalise(SAMPLE)
check("normalise returns a record", r is not None)
check("thai name picked", r["name"] == "คลองลาดพร้าว วัดบางบัว", r["name"])
check("coords parsed", abs(r["lat"] - 13.85402) < 1e-5 and abs(r["lng"] - 100.58746) < 1e-5)
check("overflowing detected", r["is_overflowing"] is True, r["is_overflowing"])
check("diff is positive when over bank", r["diff_from_bank"] == 0.56, r["diff_from_bank"])
check("province/amphoe", r["province_name"] == "กรุงเทพมหานคร" and r["amphoe_name"] == "บางเขน")
check("agency for attribution", r["agency"] == "สสน.", r["agency"])
check("min_bank used as bank level", r["bank_level"] == 2.2, r["bank_level"])
# The instant, not the label. Asserting the offset was +07:00 only proved the
# value was tagged Bangkok, which is what let a Bangkok time get stored naive
# and read back as UTC — seven hours in the future.
_fixed = normalise(dict(SAMPLE, waterlevel_datetime="2026-09-27 10:10"))["measured_at"]
check("เวลาที่วัด = ช่วงเวลาที่ถูกต้อง (10:10 ไทย = 03:10 UTC)",
      _fixed == datetime(2026, 9, 27, 3, 10, tzinfo=timezone.utc), _fixed)
check("เก็บเป็น UTC เพื่อให้ฐานข้อมูลที่ตัด timezone ทิ้งยังอ่านถูก",
      _fixed.utcoffset().total_seconds() == 0, _fixed)

# Below-bank readings must come out negative so a single comparison works.
# The reading has to match the claim: bank 2.2, water at 1.17 -> 1.03 m below.
below = dict(SAMPLE, waterlevel_msl="1.17", diff_wl_bank="1.03",
             diff_wl_bank_text="ต่ำกว่าตลิ่ง (ม.)", situation_level=4)
rb = normalise(below)
check("below bank -> negative diff", rb["diff_from_bank"] == -1.03, rb["diff_from_bank"])
check("below bank not flagged overflowing", rb["is_overflowing"] is False)

# Unusable rows are skipped rather than stored with bad coordinates.
check("missing coords -> skipped",
      normalise({"station": {"id": 1}, "geocode": {}}) is None)
check("coords outside Thailand -> skipped",
      normalise({"station": {"id": 2, "tele_station_lat": 48.85, "tele_station_long": 2.35}}) is None)

db = SessionLocal()
created, updated = upsert(db, [normalise(SAMPLE)])
check("first sync inserts", (created, updated) == (1, 0), (created, updated))
created2, updated2 = upsert(db, [normalise(SAMPLE)])
check("second sync updates, no duplicate", (created2, updated2) == (0, 1), (created2, updated2))
check("still one row", db.query(WaterStation).count() == 1, db.query(WaterStation).count())

moved = dict(normalise(SAMPLE))
moved["water_level_msl"] = 3.10
moved["diff_from_bank"] = 0.90
upsert(db, [moved])
row = db.query(WaterStation).first()
check("reading updated in place", row.water_level_msl == 3.10 and row.diff_from_bank == 0.90,
      (row.water_level_msl, row.diff_from_bank))
db.close()

with TestClient(app) as c:
    r = c.get("/api/stations")
    check("list stations", r.status_code == 200 and len(r.json()) == 1, r.text[:200])
    st = r.json()[0]
    check("situation label in thai", st["situation_label"] == "วิกฤต น้ำล้นตลิ่ง", st["situation_label"])
    check("freshness computed", "is_stale" in st and st["is_stale"] is False, st.get("is_stale"))

    # And the other direction, so "not stale" is a result rather than the only
    # answer the code can give.
    _old = dict(SAMPLE, waterlevel_datetime=(
        datetime.now(timezone(timedelta(hours=7))) - timedelta(hours=12)
    ).strftime("%Y-%m-%d %H:%M"))
    _db = SessionLocal()
    upsert(_db, [normalise(_old)])
    _db.close()
    st2 = c.get("/api/stations").json()[0]
    check("ค่าที่เก่าเกินเกณฑ์ -> ถูกทำเครื่องหมายว่าค้าง", st2["is_stale"] is True,
          st2.get("is_stale"))

    r = c.get("/api/stations?overflowing_only=true")
    check("filter overflowing", r.status_code == 200 and len(r.json()) == 1, r.text[:150])

    r = c.get("/api/stations?near=13.85,100.58,5")
    check("near returns distance", r.status_code == 200 and r.json()[0]["distance_km"] is not None,
          r.text[:200])
    r = c.get("/api/stations?near=18.0,99.0,5")
    check("near excludes far stations", r.status_code == 200 and r.json() == [], r.text[:150])

    r = c.get("/api/stations?province=กรุงเทพมหานคร")
    check("filter by province", r.status_code == 200 and len(r.json()) == 1, r.text[:150])

    r = c.get("/api/stations/summary")
    b = r.json()
    check("summary counts", r.status_code == 200 and b["total"] == 1 and b["overflowing"] == 1, r.text[:200])

    r = c.post("/api/stations/sync")
    check("sync needs auth", r.status_code == 401, r.status_code)

# ---------------------------------------------------------------- bad upstream data
# 6 of 805 live stations have every bank field at 0, which upstream turns into
# "over the bank by <height above sea level>". These must never reach the map.
print()
UNSET_BANK = {
    "id": 9, "waterlevel_datetime": _RECENT,
    "waterlevel_msl": "331.70", "situation_level": None,
    "diff_wl_bank": "331.70", "diff_wl_bank_text": "ล้นตลิ่ง (ม.)",
    "station": {"id": 999, "tele_station_name": {"th": "ฝายละแอ"},
                "tele_station_lat": 6.2, "tele_station_long": 101.3,
                "min_bank": 0, "left_bank": 0, "right_bank": 0},
    "geocode": {"province_name": {"th": "ยะลา"}},
}
u = normalise(UNSET_BANK)
check("unset bank -> not overflowing", u["is_overflowing"] is False, u["is_overflowing"])
check("unset bank -> no bank level", u["bank_level"] is None, u["bank_level"])
check("unset bank -> no diff claimed", u["diff_from_bank"] is None, u["diff_from_bank"])
check("unset bank -> says so", u["status_text"] == "ไม่มีข้อมูลระดับตลิ่ง", u["status_text"])
check("unset bank -> reading still kept", u["water_level_msl"] == 331.70, u["water_level_msl"])

# left/right_bank use a different datum than min_bank on real stations and are
# frequently negative. They must never be substituted for a missing min_bank.
DIFFERENT_DATUM = dict(SAMPLE)
DIFFERENT_DATUM["station"] = dict(SAMPLE["station"], min_bank=1.5,
                                  left_bank=-7.586, right_bank=-7.578)
DIFFERENT_DATUM["waterlevel_msl"] = "2.18"
dd = normalise(DIFFERENT_DATUM)
check("negative left/right bank ignored", dd["bank_level"] == 1.5, dd["bank_level"])
check("gap matches upstream when min_bank is sound",
      dd["diff_from_bank"] == 0.68, dd["diff_from_bank"])
check("still flagged overflowing", dd["is_overflowing"] is True, dd["is_overflowing"])

# min_bank unset stays unusable even when left/right carry numbers.
ONLY_SIDES = dict(UNSET_BANK)
ONLY_SIDES["station"] = dict(UNSET_BANK["station"], min_bank=0,
                             left_bank=330.0, right_bank=0)
os_ = normalise(ONLY_SIDES)
check("side banks alone are not a bank level", os_["bank_level"] is None, os_["bank_level"])
check("side banks alone -> not overflowing", os_["is_overflowing"] is False, os_["is_overflowing"])

# An implausible gap on a surveyed station is kept but not asserted as a flood.
ABSURD = dict(SAMPLE, waterlevel_msl="97.2", diff_wl_bank="95.0",
              diff_wl_bank_text="ล้นตลิ่ง (ม.)")
ab = normalise(ABSURD)
check("absurd diff not treated as flooding", ab["is_overflowing"] is False, ab["is_overflowing"])
check("absurd diff is labelled", "ผิดปกติ" in (ab["status_text"] or ""), ab["status_text"])

# The ordinary case must be untouched by all of the above.
ok = normalise(SAMPLE)
check("normal station unaffected",
      ok["is_overflowing"] is True and ok["diff_from_bank"] == 0.56 and ok["bank_level"] == 2.2,
      (ok["is_overflowing"], ok["diff_from_bank"], ok["bank_level"]))

# ---------------------------------------------------------------- sync status
# Bangkok's gauges were missing from production for days and the only record of
# why was a log line unreachable from outside the container.
import asyncio

import app.stations as stations_mod

stations_mod.LAST_SYNC.clear()


async def _fake_sync(db):
    return {"ok": False, "error": "ConnectError <- gaierror(name not resolved)",
            "created": 0, "updated": 0}


real_sync, real_bma = stations_mod.sync, None
import app.bma_stations as bmamod
real_bma = bmamod.sync
stations_mod.sync = _fake_sync
bmamod.sync = _fake_sync
try:
    asyncio.run(stations_mod.sync_all(None))
finally:
    stations_mod.sync, bmamod.sync = real_sync, real_bma

check("บันทึกผลซิงก์ของทุกแหล่ง", set(stations_mod.LAST_SYNC) >= {"thaiwater"}, list(stations_mod.LAST_SYNC))
entry = stations_mod.LAST_SYNC["thaiwater"]
check("แหล่งที่ล้ม -> ok=False", entry["ok"] is False, entry)
check("และเก็บสาเหตุที่อ่านรู้เรื่องไว้ด้วย", "gaierror" in (entry["error"] or ""), entry)
check("มีเวลาที่ซิงก์ล่าสุด", entry.get("at") is not None, entry)
stations_mod.LAST_SYNC.clear()

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL WATER-STATION CHECKS PASSED (incl. bad upstream data)")
