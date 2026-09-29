"""Water level history and the trend read off it.

The trend is the part a driver acts on, so the cases that matter most are the
ones where a naive reading of the series would say the opposite of the truth:
null slots at the end that look like "now", and a gauge that sat flat for days
before starting to climb an hour ago.
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/h.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app import history
from app.database import SessionLocal
from app.main import app
from app.models import WaterStation, utcnow
from app.stations import BANGKOK_TZ

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def at(hours_ago: float) -> datetime:
    return datetime.now(BANGKOK_TZ).replace(minute=0, second=0, microsecond=0) \
        - timedelta(hours=hours_ago)


def series(*pairs):
    return [history.Point(at=at(h), value=v) for h, v in sorted(pairs, reverse=True)]


# ---------------------------------------------------------------- the trend
t = history._summarize(series((8, 0.50), (6, 0.52), (3, 0.68), (0, 0.82)))
check("น้ำขึ้น → rising", t and t.direction == "rising", t)
check("บอกเป็น ซม. ในภาษาคน", t and "กำลังขึ้น" in t.label and "ซม." in t.label,
      t.label if t else None)

t = history._summarize(series((8, 0.95), (6, 0.90), (3, 0.86), (0, 0.82)))
check("น้ำลง → falling", t and t.direction == "falling", t)
check("บอกว่ากำลังลง", t and "กำลังลง" in t.label, t.label if t else None)

t = history._summarize(series((6, 0.820), (3, 0.815), (0, 0.822)))
check("ขยับ 0.7 ซม. → ถือว่าทรงตัว ไม่ใช่ขึ้น", t and t.direction == "steady", t)

# The case a fitted line gets wrong: flat for two days, then climbing.
flat = [(h, 0.40) for h in range(48, 6, -1)]
t = history._summarize(series(*flat, (5, 0.42), (2, 0.58), (0, 0.71)))
check("นิ่งมา 2 วันแล้วเพิ่งพุ่ง → ต้องจับได้ว่ากำลังขึ้น",
      t and t.direction == "rising", t)

t = history._summarize(series((1, 0.50), (0, 0.55)))
check("ข้อมูลสั้นกว่าหน้าต่างที่ขอ → ใช้เท่าที่มี ไม่ใช่คืน None",
      t and t.direction == "rising" and t.hours == 1.0, t)

t = history._summarize(series((24, 58.63), (0, 65.79)))
check("ขึ้นเกินหนึ่งเมตร → บอกเป็นเมตร ไม่ใช่ 716 ซม.",
      t and "ม." in t.label and "ซม." not in t.label, t.label if t else None)

check("จุดเดียว → ไม่ตัดสินแนวโน้ม", history._summarize(series((0, 0.5))) is None)
check("ไม่มีข้อมูล → ไม่ตัดสินแนวโน้ม", history._summarize([]) is None)


# ---------------------------------------------------------------- fetching
captured = {}

def upstream(payload, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        captured["url"] = str(request.url)
        return httpx.Response(status_code, json=payload)
    return handler


def run_with(handler, *args, **kwargs):
    """Point history's client at a stub transport for one call."""
    real = httpx.AsyncClient

    class Stub(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    httpx.AsyncClient = Stub
    try:
        return asyncio.run(history.fetch_history(*args, **kwargs))
    finally:
        httpx.AsyncClient = real


GOOD = {"result": "OK", "data": {"graph_data": [
    {"datetime": "2026-09-27 12:00", "value": 0.50},
    {"datetime": "2026-09-27 13:00", "value": None},      # station silent
    {"datetime": "2026-09-27 14:00", "value": 0.62},
    {"datetime": "2026-09-27 15:00", "value": "0.70"},    # arrives as a string
    {"datetime": "2026-09-27 16:00", "value": None},      # not reported yet
]}}

history._cache.clear()
points = run_with(upstream(GOOD), "700590")
check("ทิ้งจุดที่เป็น null", len(points) == 3, [p.value for p in points])
check("แปลงค่าที่มาเป็นข้อความได้", points[-1].value == 0.70, points[-1].value)
check("เรียงเก่า→ใหม่", [p.value for p in points] == [0.50, 0.62, 0.70],
      [p.value for p in points])
check("จุดสุดท้ายคือค่าที่มีจริง ไม่ใช่ช่องว่างล่าสุด", points[-1].value == 0.70)
# "2026-09-27 12:00" upstream is Bangkok time; stored and compared as UTC so a
# database that drops the offset cannot make a reading look newer than it is.
check("12:00 ไทย = 05:00 UTC",
      points[0].at == datetime(2026, 9, 27, 5, 0, tzinfo=timezone.utc), points[0].at)

check("ส่ง station_type ทุกครั้ง (ไม่ส่งแล้วต้นทางตอบ 500)",
      captured["params"].get("station_type") == "tele_waterlevel", captured["params"])
check("ส่ง station_id ที่ขอ", captured["params"].get("station_id") == "700590",
      captured["params"])
check("ส่งช่วงวันที่ครบ",
      "start_date" in captured["params"] and "end_date" in captured["params"],
      captured["params"])

# Second call inside the TTL must not reach the network at all.
def explode(request):
    raise AssertionError("ไม่ควรยิงซ้ำภายใน TTL")

cached = run_with(explode, "700590")
check("ยิงซ้ำภายใน TTL → ใช้ของใน cache ไม่รบกวนต้นทาง",
      [p.value for p in cached] == [0.50, 0.62, 0.70], cached)

history._cache.clear()
empty = run_with(upstream({"result": "OK", "data": {"graph_data": []}}), "1")
check("ต้นทางส่งว่างมา → คืนลิสต์ว่าง ไม่ระเบิด", empty == [], empty)

history._cache.clear()
odd = run_with(upstream({"result": "NO", "data": "422: No station id"}), "2")
check("ต้นทางตอบรูปแบบผิดคาด → คืนลิสต์ว่าง", odd == [], odd)

# ---------------------------------------------------------------- end to end
with TestClient(app) as c:
    db = SessionLocal()
    try:
        db.add(WaterStation(id="tw1", source="thaiwater", external_id="700590",
                            name="สถานีทดสอบ", lat=13.75, lng=100.5,
                            measured_at=utcnow(), synced_at=utcnow()))
        db.add(WaterStation(id="bma1", source="bma", external_id="263",
                            name="คลองทดสอบ กทม.", lat=13.70, lng=100.60,
                            measured_at=utcnow(), synced_at=utcnow()))
        db.commit()
    finally:
        db.close()

    r = c.get("/api/stations/ไม่มีจริง/history")
    check("สถานีที่ไม่มี → 404", r.status_code == 404, r.status_code)

    r = c.get("/api/stations/bma1/history")
    body = r.json()
    check("สถานี กทม. → บอกตรง ๆ ว่ายังไม่มีย้อนหลัง",
          r.status_code == 200 and body["available"] is False and body["reason"],
          body)
    check("และไม่ส่งกราฟเปล่าที่ดูเหมือนน้ำนิ่ง", body["points"] == [] and body["trend"] is None,
          body)

    history._cache.clear()
    real = httpx.AsyncClient

    class Stub(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(upstream(GOOD))
            super().__init__(*a, **kw)

    httpx.AsyncClient = Stub
    try:
        r = c.get("/api/stations/tw1/history")
        body = r.json()
        check("สถานี ThaiWater → ได้ข้อมูลย้อนหลัง",
              r.status_code == 200 and body["available"] and len(body["points"]) == 3,
              body)
        check("แนบชื่อสถานีมาด้วย", body.get("name") == "สถานีทดสอบ", body.get("name"))
        check("มีคำสรุปแนวโน้มพร้อมแสดง",
              body["trend"] and body["trend"]["label"], body.get("trend"))
    finally:
        httpx.AsyncClient = real

    # An upstream that is down must degrade, not take the request with it.
    history._cache.clear()

    def dead(request):
        raise httpx.ConnectError("upstream down")

    class DeadStub(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(dead)
            super().__init__(*a, **kw)

    httpx.AsyncClient = DeadStub
    try:
        r = c.get("/api/stations/tw1/history")
        check("ต้นทางล่ม → ตอบ 200 พร้อมบอกว่าไม่มีข้อมูล ไม่ใช่ 500",
              r.status_code == 200 and r.json()["available"] is False,
              f"{r.status_code} {r.text[:120]}")
    finally:
        httpx.AsyncClient = real

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL HISTORY CHECKS PASSED")
sys.exit(1 if fails else 0)
