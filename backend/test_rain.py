"""Rain radar and forecast.

The rules worth protecting here are the ones that keep rain from being read as
flooding: it never becomes a report, it only earns a sentence when it is heavy
enough to change a decision, and a deployment with no key behaves exactly as
it did before.
"""
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/r.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"

import asyncio
import json as _json

import httpx


def json_dumps(x):
    return _json.dumps(x, ensure_ascii=False)
from fastapi.testclient import TestClient

from app import rain
from app.config import settings
from app.main import app

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


PATH = [[13.70, 100.50], [13.75, 100.55], [13.80, 100.60]]

CAMS_OK = {"scanned": 256, "count": 0, "cameras": []}

calls: list[httpx.Request] = []


def serve(handler):
    """Point rain's client at a stub, and remember every request it made."""
    real = httpx.AsyncClient

    def wrapped(request):
        calls.append(request)
        return handler(request)

    class Stub(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(wrapped)
            super().__init__(*a, **kw)

    return real, Stub


def with_upstream(handler, coro):
    real, Stub = serve(handler)
    httpx.AsyncClient = Stub
    try:
        return asyncio.run(coro())
    finally:
        httpx.AsyncClient = real


def reset(key="test-key"):
    rain._cache.clear()
    rain._locks.clear()
    calls.clear()
    settings.longdo_api_key = key


# ---------------------------------------------------------------- geometry
ring = rain.corridor_polygon(PATH, 4.0)
check("วงแหวนรอบเส้นทางปิดสนิท", ring[0] == ring[-1], (ring[0], ring[-1]))
check("มีจุดสองฝั่งของเส้นทาง", len(ring) >= 7, len(ring))
lons = [c[0] for c in ring]
lats = [c[1] for c in ring]
check("วงแหวนกว้างกว่าเส้นทางจริง",
      max(lats) > 13.80 and min(lats) < 13.70, (min(lats), max(lats)))
check("พิกัดเรียงแบบ GeoJSON คือ [lon, lat]",
      99 < min(lons) < 102 and 13 < min(lats) < 15, (ring[0],))

long_path = [[13.0 + i * 0.001, 100.0 + i * 0.001] for i in range(900)]
check("เส้นทางยาวถูกลดจำนวนจุด ไม่ส่งไปเป็นพัน",
      len(rain.corridor_polygon(long_path, 4.0)) < 200,
      len(rain.corridor_polygon(long_path, 4.0)))
check("เส้นทางสั้นเกินไป -> ไม่มีวงแหวน", rain.corridor_polygon([[13.7, 100.5]], 4.0) == [])
check("สุ่มจุดได้ตามจำนวนที่ขอ", len(rain.sample_points(long_path, 3)) == 3)
# Tolerance, not equality: these come out of floating point arithmetic and
# 13.899000000000001 is the same place as 13.899.
_samples = rain.sample_points(long_path, 3)
check("สุ่มจุดรวมทั้งต้นและปลายทาง",
      abs(_samples[0][0] - 13.0) < 1e-9 and abs(_samples[-1][0] - 13.899) < 1e-9,
      _samples)


# ---------------------------------------------------------------- the sentence
heavy_now = {"max_intensity": 4, "coverage_pct": 40, "level": "ฝนตกหนัก"}
check("ฝนหนักครอบคลุมกว้าง -> บอกผู้ใช้",
      "ขณะนี้" in (rain.summarise(heavy_now, []) or ""), rain.summarise(heavy_now, []))
check("ฝนปรอยทั่วเส้นทาง -> เงียบไว้ (ไม่งั้นคนจะเลิกอ่าน)",
      rain.summarise({"max_intensity": 1, "coverage_pct": 90, "level": "ฝนปรอย"}, []) is None)
check("ฝนหนักแต่แค่มุมเดียวของเส้นทาง -> เงียบไว้",
      rain.summarise({"max_intensity": 5, "coverage_pct": 3, "level": "ฝนตกหนักมาก"}, []) is None)
soon = [{"lead_minutes": 30, "max_intensity": 5, "coverage_pct": 50, "level": "ฝนตกหนักมาก"}]
check("ตอนนี้ยังแห้ง แต่ฝนกำลังมา -> เตือนล่วงหน้า",
      "อีก 30 นาที" in (rain.summarise(None, soon) or ""), rain.summarise(None, soon))
check("ไม่มีอะไรน่าบอก -> คืน None", rain.summarise(None, []) is None)


# ---------------------------------------------------------------- off switch
reset(key="")
check("ไม่มีคีย์ -> ปิดการทำงาน", rain.enabled() is False)
check("ไม่มีคีย์ -> ไม่คืนข้อมูลฝนบนเส้นทาง",
      asyncio.run(rain.route_rain(PATH)) is None)
check("ไม่มีคีย์ -> ไม่ยิงออกนอกเลย", calls == [], calls)


# ---------------------------------------------------------------- upstream
POLYGON = {"unix_time": "1", "last_updated": "2026-09-28T01:00:00Z",
           "stats": {"rain_coverage_pct": 42.0, "max_intensity": 4,
                     "avg_intensity": 1.2,
                     "dominant_level": {"description": "ฝนตกหนัก", "intensity": 4}}}
FORECAST = {"lat": 13.7, "lon": 100.5, "lead_minutes": [15, 30, 60],
            "forecast": [
                {"available": True, "stats": {"max_intensity": 1, "rain_coverage_pct": 5,
                                              "dominant_level": {"description": "ฝนปรอย"}}},
                {"available": False, "stats": {}},
                {"available": True, "stats": {"max_intensity": 5, "rain_coverage_pct": 60,
                                              "dominant_level": {"description": "ฝนตกหนักมาก"}}},
            ]}


def route_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/polygon"):
        return httpx.Response(200, json=POLYGON)
    return httpx.Response(200, json=FORECAST)


reset()
result = with_upstream(route_handler, lambda: rain.route_rain(PATH))
check("ได้ทั้งฝนตอนนี้และพยากรณ์", result and result["now"] and result["soon"], result)
check("อ่านค่าฝนปัจจุบันถูก", result["now"]["max_intensity"] == 4, result["now"])
check("ข้ามช่วงเวลาที่ต้นทางคำนวณไม่ได้ (available=false)",
      [s["lead_minutes"] for s in result["soon"]] == [15, 60],
      [s["lead_minutes"] for s in result["soon"]])
check("สรุปเป็นประโยคเดียวให้ผู้ใช้", bool(result["summary"]), result["summary"])

sent = [str(c.url) for c in calls]
check("คีย์ถูกส่งไปกับทุกคำขอ", all("key=test-key" in u for u in sent), sent[:2])
check("ยิงพยากรณ์ตามจำนวนจุดที่ตั้งไว้ ไม่ใช่ทุกจุดบนเส้นทาง",
      sum(1 for u in sent if "forecast" in u) <= settings.rain_forecast_samples,
      sent)

# The same route asked twice must not cost twice.
before = len(calls)
with_upstream(route_handler, lambda: rain.route_rain(PATH))
check("ถามเส้นทางเดิมซ้ำ -> ใช้ cache ไม่เสียโควตาเพิ่ม", len(calls) == before,
      f"{before} -> {len(calls)}")


# ---------------------------------------------------------------- failures
reset()
rain.LAST_FAILURE.clear()
result = with_upstream(lambda r: httpx.Response(500, text="boom"),
                       lambda: rain.route_rain(PATH))
check("ต้นทางล่ม -> คืน None ไม่โยน error ใส่คำตอบเส้นทาง", result is None, result)
check("และจำไว้ว่าล้มเพราะอะไร ไม่ใช่แค่ว่าล้ม",
      "500" in (rain.LAST_FAILURE.get("polygon") or ""), rain.LAST_FAILURE)

# Error text often quotes the request back, key and all.
reset(key="super-secret-key")
rain.LAST_FAILURE.clear()
with_upstream(lambda r: httpx.Response(403, text=f"denied for key super-secret-key"),
              lambda: rain.route_rain(PATH))
check("สาเหตุที่รายงานออกมา ต้องไม่มีคีย์ติดไปด้วย",
      "super-secret-key" not in str(rain.LAST_FAILURE), rain.LAST_FAILURE)
check("แต่ยังบอกรหัสสถานะให้วินิจฉัยได้",
      "403" in (rain.LAST_FAILURE.get("polygon") or ""), rain.LAST_FAILURE)
rain.LAST_FAILURE.clear()

reset()
result = with_upstream(lambda r: httpx.Response(200, json={"unexpected": True}),
                       lambda: rain.route_rain(PATH))
check("ต้นทางส่งรูปแบบแปลก -> ไม่ระเบิด", result is None or result.get("now") is None, result)


# ---------------------------------------------------------------- endpoints
with TestClient(app) as c:
    reset(key="")
    r = c.get("/api/rain/status")
    check("status บอกว่ายังไม่ได้ตั้งค่า", r.json().get("enabled") is False, r.json())
    check("status บอกสาเหตุที่ล้มล่าสุดด้วย (คีย์มีอยู่ ไม่ได้แปลว่าใช้ได้)",
          "last_failure" in r.json(), r.json())
    r = c.get("/api/rain/cameras")
    check("ไม่มีคีย์ -> cameras ตอบ 200 พร้อมบอกเหตุผล",
          r.status_code == 200 and r.json()["available"] is False, r.text[:150])
    r = c.get("/api/rain/radar/10/800/470.png")
    check("ไม่มีคีย์ -> ไทล์ตอบ 503 ไม่ใช่ 500", r.status_code == 503, r.status_code)

    reset()
    r = c.get("/api/rain/radar/3/99/1.png")
    check("ไทล์นอกช่วงของ zoom -> 404 โดยไม่ยิงออกนอก",
          r.status_code == 404 and calls == [], f"{r.status_code} {len(calls)}")

    reset()
    real, Stub = serve(lambda rq: httpx.Response(200, content=b"\x89PNG\r\n\x1a\n",
                                                 headers={"content-type": "image/png"}))
    httpx.AsyncClient = Stub
    try:
        r = c.get("/api/rain/radar/10/800/470.png")
        check("ไทล์เรดาร์ส่งภาพกลับมาได้", r.status_code == 200 and r.content.startswith(b"\x89PNG"),
              f"{r.status_code} {r.content[:12]}")
        check("ตั้ง cache ให้เบราว์เซอร์ไม่ถามซ้ำถี่เกินจำเป็น",
              "max-age" in r.headers.get("cache-control", ""), r.headers.get("cache-control"))
        check("คีย์ไม่รั่วออกไปในคำตอบ", b"test-key" not in r.content, r.content[:40])
    finally:
        httpx.AsyncClient = real

    reset()
    CAMS = {"scanned": 280, "count": 1, "stale": False,
            "last_updated": "2026-09-28T01:00:00Z",
            "cameras": [{"camid": "DOH-1", "title": "ถนนทดสอบ", "lat": 13.7, "lon": 100.5,
                         "province": "กรุงเทพมหานคร", "organization": "กรมทางหลวง",
                         "hls_url": "https://example.test/x.m3u8",
                         "rain": {"description": "ฝนตกหนัก", "intensity": 4}},
                        {"camid": "BAD", "title": "ไม่มีพิกัด", "lat": None, "lon": None}]}
    real, Stub = serve(lambda rq: httpx.Response(200, json=CAMS))
    httpx.AsyncClient = Stub
    try:
        body = c.get("/api/rain/cameras").json()
        check("คืนกล้องที่ฝนตก", body["available"] and len(body["cameras"]) == 1, body)
        check("ทิ้งกล้องที่ไม่มีพิกัด", all(x["lat"] for x in body["cameras"]), body["cameras"])
        check("บอกด้วยว่าสแกนไปทั้งหมดกี่ตัว (รายการสั้นไม่ได้แปลว่าระบบพัง)",
              body["scanned"] == 280, body.get("scanned"))
        check("แนบลิงก์สตรีมสดมาด้วย",
              body["cameras"][0]["stream_url"].endswith(".m3u8"), body["cameras"][0])
    finally:
        httpx.AsyncClient = real

    settings.longdo_api_key = ""

# ---------------------------------------------------------------- budget
# The radar tile proxy emptied the whole key's daily allowance in one session
# and every other rain call started returning 403 with it. A cache per tile is
# not a limit: it stops the same tile being fetched twice, and a map being
# panned asks for a different tile every time.
b = rain._Budget(per_min=3, per_day=5)
check("ถึงเพดานต่อนาทีแล้วหยุด", [b.take() for _ in range(5)] == [True, True, True, False, False])
b = rain._Budget(per_min=100, per_day=2)
check("ถึงเพดานต่อวันแล้วหยุด", [b.take() for _ in range(4)] == [True, True, False, False])

reset()
rain._tile_budget = rain._Budget(per_min=2, per_day=99)
rain._service_budget = rain._Budget(per_min=99, per_day=99)
rain.LAST_FAILURE.clear()

png = lambda r: httpx.Response(200, content=bytes([0x89]) + b"PNG",
                               headers={"content-type": "image/png"})
got = []
for i in range(4):
    rain._cache.clear()          # different tiles: the cache cannot help
    got.append(with_upstream(png, lambda i=i: rain.radar_tile(9, 400 + i, 250)) is not None)
check("ไทล์เกินเพดาน -> หยุดยิง ไม่ใช่ยิงต่อจนโดนแบน", got == [True, True, False, False], got)
check("และคำขอที่ถูกปฏิเสธ ไม่ได้ถูกส่งออกไปจริง", len(calls) == 2, len(calls))
check("บันทึกไว้ว่าหยุดเพราะโควตา", "โควตา" in (rain.LAST_FAILURE.get("tile") or ""),
      rain.LAST_FAILURE)

# The point of separate budgets: tiles must not be able to starve the calls a
# person is actually waiting on.
reset()
rain._tile_budget = rain._Budget(per_min=0, per_day=0)
rain._service_budget = rain._Budget(per_min=50, per_day=50)
rain._cache.clear()
check("ไทล์หมดโควตา -> แต่บริการอื่นยังทำงานได้",
      with_upstream(lambda r: httpx.Response(200, json=CAMS_OK),
                    lambda: rain.raining_cameras())["available"] is True)
rain._tile_budget = None
rain._service_budget = None
rain.LAST_FAILURE.clear()


# ---------------------------------------------------------------- prober
reset()
rain.LAST_FAILURE.clear()


def mixed(request: httpx.Request) -> httpx.Response:
    # Shaped like what production actually returned: some endpoints fine, some
    # refused by the gateway with a message that blames the key.
    if "/polygon" in request.url.path or "forecast" in request.url.path:
        return httpx.Response(403, json={"detail": "API key is invalid or rate limit exceeded"})
    return httpx.Response(200, json={"ok": True})


report = with_upstream(mixed, lambda: rain.probe_all())
results = report["results"]
check("ตรวจครบทุก endpoint", len(results) == len(rain.PROBES), list(results))
check("แยกได้ว่าอันไหนผ่าน", results["cameras"]["ok"] is True, results["cameras"])
check("แยกได้ว่าอันไหนถูกปฏิเสธ",
      results["polygon"]["ok"] is False and results["polygon"]["status"] == 403,
      results["polygon"])
check("แนบข้อความจากต้นทางมาให้อ่าน",
      "rate limit" in results["forecast_area"]["body"], results["forecast_area"])

reset(key="secret-probe-key")
report = with_upstream(
    lambda r: httpx.Response(403, text="denied key=secret-probe-key"),
    lambda: rain.probe_all())
check("ผลตรวจไม่มีคีย์ปนออกมา",
      "secret-probe-key" not in json_dumps(report), report)

# A success must clear an old failure, or a fault fixed hours ago still reads
# as the current state.
reset()
rain.LAST_FAILURE["polygon"] = "HTTP 403: เก่า"
with_upstream(lambda r: httpx.Response(200, json=POLYGON) if "/polygon" in str(r.url)
              else httpx.Response(200, json=FORECAST),
              lambda: rain.route_rain(PATH))
check("สำเร็จแล้วต้องล้างความล้มเหลวเก่าทิ้ง",
      "polygon" not in rain.LAST_FAILURE, rain.LAST_FAILURE)
rain.LAST_FAILURE.clear()
settings.longdo_api_key = ""

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL RAIN CHECKS PASSED")
sys.exit(1 if fails else 0)
