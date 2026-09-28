"""Satellite flood extent (GISTDA).

Three things here are worth more than the rest, because each one has already
cost this project something on a different provider:

* The key travels in an ``API-Key`` header. Sent as a query parameter it comes
  back 407 and the layer is simply blank, which looks exactly like "no flooding
  today" -- so the header is asserted, not assumed.
* Tiles are budgeted and cached for hours. A cache alone did not save the
  Longdo quota; panning asks for a different tile every time, and when that
  quota went the camera list and the forecast went with it.
* With no key configured the app must behave exactly as it did before: no
  requests, no errors, and a tile endpoint that answers with a transparent
  pixel rather than a status code the map would draw a banner for.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/fe.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"

import asyncio

import httpx
from fastapi.testclient import TestClient

import json as _json

from app import flood_extent as fe
from app import routing
from app.config import settings
from app.main import app

fails = []
calls: list[httpx.Request] = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


A_PNG = fe.BLANK_TILE


def json_dumps(x):
    return _json.dumps(x, ensure_ascii=False)


def serve(handler):
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
    fe._cache.clear()
    fe._tile_budget = None
    fe._feature_budget = None
    fe.LAST_FAILURE.clear()
    calls.clear()
    settings.gistda_api_key = key


def ok_tile(request):
    return httpx.Response(200, content=A_PNG, headers={"content-type": "image/png"})


# ------------------------------------------------------------------ off

reset(key="")
got = with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 228))
check("ไม่ตั้งคีย์ -> ปิดสนิท คืน None", got is None)
check("และไม่ยิงออกไปข้างนอกเลย", calls == [], f"{len(calls)} ครั้ง")

probe = with_upstream(ok_tile, fe.probe_all)
check("ไม่ตั้งคีย์ -> diagnose บอกว่าปิดอยู่", probe == {"enabled": False, "results": {}}, probe)

# ------------------------------------------------------------------ the key

reset()
with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 228))
check("ยิงออกไปหนึ่งครั้ง", len(calls) == 1, f"{len(calls)} ครั้ง")
if calls:
    sent = calls[0]
    check('ส่งคีย์ทาง header "API-Key"',
          sent.headers.get("API-Key") == "test-key", dict(sent.headers))
    # Sent as a query parameter this comes back 407 and the layer goes blank,
    # which is indistinguishable from "no flooding here".
    check("ไม่ได้แอบส่งคีย์ไปใน URL", "test-key" not in str(sent.url), str(sent.url))
    check("ยิงถูก path ของ TMS",
          sent.url.path.endswith("/maps/flood/7days/tms/9/402/228"), str(sent.url))

# ------------------------------------------------------------------ caching

reset()
with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 228))
with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 228))
check("ไทล์เดิม -> ยิงออกครั้งเดียว (แคชทำงาน)", len(calls) == 1, f"{len(calls)} ครั้ง")

check("แคชตั้งไว้เป็นชั่วโมง ไม่ใช่นาที",
      settings.gistda_tile_cache_sec >= 3600, settings.gistda_tile_cache_sec)

reset()
with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 228))
with_upstream(ok_tile, lambda: fe.tile("1day", 9, 402, 228))
check("คนละ product -> แคชคนละช่อง ไม่ปนกัน", len(calls) == 2, f"{len(calls)} ครั้ง")

# ------------------------------------------------------------------ zoom cap

reset()
deep = with_upstream(ok_tile, lambda: fe.tile("7days", settings.gistda_max_zoom + 1, 1, 1))
check("ซูมเกินเพดาน -> ไม่ยิงออกเลย", calls == [], f"{len(calls)} ครั้ง")
check("และคืน None ให้ router เปลี่ยนเป็นภาพใส", deep is None)

# ------------------------------------------------------------------ budget

reset()
fe._tile_budget = None
settings.gistda_tiles_per_min = 2
fe.budget()
for i in range(5):
    with_upstream(ok_tile, lambda i=i: fe.tile("7days", 9, 400 + i, 228))
check("งบต่อนาทีหมด -> หยุดยิงเอง ไม่ไปกวนปลายทาง",
      len(calls) == 2, f"ยิงไป {len(calls)} ครั้ง จากที่ขอ 5")
check("และบอกเหตุผลว่าโควตาหมด",
      "โควตา" in fe.LAST_FAILURE.get("tile", ""), fe.LAST_FAILURE)
settings.gistda_tiles_per_min = 20

# ------------------------------------------------------------------ failure

reset()


def refuse(request):
    # Error bodies quote the request back, key and all.
    return httpx.Response(407, text='{"detail":"Authentication Required for key test-key"}')


got = with_upstream(refuse, lambda: fe.tile("7days", 9, 402, 228))
check("ปลายทางปฏิเสธ -> คืน None (router เปลี่ยนเป็นภาพใส ไม่ใช่ 503)", got is None)
check("บันทึกเหตุผลไว้ให้อ่านได้", "407" in fe.LAST_FAILURE.get("tile", ""), fe.LAST_FAILURE)
check("คีย์ไม่หลุดออกมาในข้อความ error",
      "test-key" not in fe.LAST_FAILURE.get("tile", ""), fe.LAST_FAILURE)

# A fault that was fixed hours ago must stop reading as the current state.
with_upstream(ok_tile, lambda: fe.tile("7days", 9, 402, 229))
check("สำเร็จแล้วล้างความล้มเหลวเก่าทิ้ง", "tile" not in fe.LAST_FAILURE, fe.LAST_FAILURE)

# ------------------------------------------------------------------ products

reset()
check("product แปลกปลอม -> ใช้ค่าตั้งต้นแทน",
      fe.product_or_default("../../etc") == settings.gistda_product,
      fe.product_or_default("../../etc"))
check("product ที่มีจริง -> ใช้ตามที่ขอ", fe.product_or_default("1day") == "1day")

# ------------------------------------------------------------------ over HTTP

reset(key="")
with TestClient(app) as c:
    r = c.get("/api/flood-extent/status")
    check("มีคีย์หรือยัง ดูได้จาก /status", r.status_code == 200 and
          r.json()["enabled"] is False, r.text[:160])

    r = c.get("/api/flood-extent/7days/9/402/228.png")
    check("ไม่มีคีย์ -> ไทล์คืน 200 ภาพใส ไม่ใช่ 503",
          r.status_code == 200 and r.headers["content-type"] == "image/png",
          f"{r.status_code} {r.headers.get('content-type')}")
    check("ภาพใสนั้นเป็น PNG จริง", r.content[:8] == b"\x89PNG\r\n\x1a\n", r.content[:8])

    # Spending a call to be told a tile cannot exist is pure waste.
    r = c.get("/api/flood-extent/7days/2/9/9.png")
    check("พิกัดไทล์เกินระดับซูม -> 404 โดยไม่ยิงออกไป", r.status_code == 404, r.status_code)

    r = c.get("/api/flood-extent/status").json()
    check("/status บอกอายุแคช เพื่อให้หน้าเว็บบอกคนได้ว่าภาพเก่าได้แค่ไหน",
          r.get("cache_sec") == settings.gistda_tile_cache_sec, r)
    check("/status บอกงบที่ใช้ไป", "used_today" in r.get("budget", {}), r)

# ------------------------------------------------- polygons handed to routing

SQUARE = [[100.50, 13.70], [100.70, 13.70], [100.70, 13.85],
          [100.50, 13.85], [100.50, 13.70]]


def features(rings):
    return {"features": [{"geometry": {"type": "Polygon", "coordinates": [r]}}
                         for r in rings]}


def serve_features(payload, size=0):
    def handler(request):
        body = json_dumps(payload)
        if size:
            body = body + " " * size
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "application/geo+json"})
    return handler


reset()
rings = with_upstream(serve_features(features([SQUARE])), fe.all_rings)
check("อ่านรูปหลายเหลี่ยมจาก GeoJSON ได้", len(rings) == 1, rings)

# Rounded as they are read, not later: the full-resolution country does not
# need to exist in memory on a 512MB instance even for a moment longer.
reset()
JAGGED = [[100.5000, 13.7000], [100.50001, 13.7000], [100.50002, 13.7000],
          [100.5200, 13.7000], [100.5200, 13.7200], [100.5000, 13.7200],
          [100.5000, 13.7000]]
tidy = with_upstream(serve_features(features([JAGGED])), fe.all_rings)
check("ย่อจุดตั้งแต่ตอนอ่าน ไม่เก็บความละเอียดเต็มไว้",
      tidy and len(tidy[0]) < len(JAGGED), tidy)

reset()
got = with_upstream(serve_features(features([SQUARE])),
                    lambda: fe.avoid_near((100.55, 13.75, 100.60, 13.80)))
check("พื้นที่ที่ทับเส้นทาง -> ส่งให้ ORS หลบ",
      got and got["type"] == "MultiPolygon" and len(got["coordinates"]) == 1, got)

reset()
far = with_upstream(serve_features(features([SQUARE])),
                    lambda: fe.avoid_near((99.0, 8.0, 99.1, 8.1)))
check("พื้นที่คนละจังหวัด -> ไม่ต้องหลบ (คืน None)", far is None, far)

reset()
many = [[[100.5 + i * 0.01, 13.7], [100.51 + i * 0.01, 13.7],
         [100.51 + i * 0.01, 13.85], [100.5 + i * 0.01, 13.85],
         [100.5 + i * 0.01, 13.7]] for i in range(80)]
capped = with_upstream(serve_features(features(many)),
                       lambda: fe.avoid_near((100.4, 13.6, 101.4, 13.9)))
check("จำกัดจำนวนรูปที่ส่งให้ ORS ไม่ส่งไปทั้งประเทศ",
      capped and len(capped["coordinates"]) <= settings.gistda_avoid_max_polygons,
      len(capped["coordinates"]) if capped else None)

# The ceiling exists because this instance is small and the endpoint takes no
# parameters -- there is no way to ask for less.
reset()
oversize = int((settings.gistda_max_download_mb + 2) * 1024 * 1024)
huge = with_upstream(serve_features(features([SQUARE]), size=oversize),
                     fe.all_rings)
check("ข้อมูลใหญ่เกินเพดาน -> ไม่แตะ ไม่ล่ม คืนว่าง", huge == [], len(huge))
check("และบอกไว้ว่าทำไมถึงไม่มีข้อมูล",
      "ใหญ่เกิน" in fe.LAST_FAILURE.get("features", ""), fe.LAST_FAILURE)

# The outlines are small patches, so "inside" is the wrong question -- this is
# the check that would have caught the layer quietly never firing in production.
reset()
TINY = [[100.6000, 13.7300], [100.6002, 13.7300],
        [100.6002, 13.7302], [100.6000, 13.7302], [100.6000, 13.7300]]
road = [(13.7310, 100.6001), (13.7340, 100.6001)]
check("ถนนเฉียดหย่อมน้ำเล็ก ๆ -> จับได้",
      fe.path_near(road, [TINY], 0.3) is True)
check("แต่ถ้าถามว่าตกอยู่ในหย่อมพอดีไหม -> ไม่เจอ (เหตุผลที่ต้องวัดระยะ)",
      fe.path_enters(road, [TINY]) is False)
check("ถนนไกลออกไป -> ไม่จับ",
      fe.path_near([(13.9000, 100.6001)], [TINY], 0.3) is False)
check("ยังไม่เคยโหลดข้อมูล -> บอกว่า None ไม่ใช่ 0",
      fe.cached_ring_count() is None, fe.cached_ring_count())

# The feed refuses a page size it considers too large and does not say what
# its ceiling is, so the only way to find it is to ask. Production spent a
# deploy answering "HTTP 400: Query param 'limit' is invalid" and loading
# nothing at all.
reset()
seen_limits = []


def picky(request):
    limit = int(dict(request.url.params).get("limit", 0))
    seen_limits.append(limit)
    if limit > 10000:
        return httpx.Response(
            400, text=json_dumps({"code": "400",
                                  "description": "Query param 'limit' is invalid"}))
    return serve_features(features([SQUARE]))(request)


rings = with_upstream(picky, fe.all_rings)
check("ปลายทางปฏิเสธ limit ใหญ่ -> ไล่ลงมาจนได้", len(rings) == 1, rings)
check("และลองค่าที่เล็กลงจริง ไม่ใช่ยอมแพ้",
      len(seen_limits) >= 2 and seen_limits[0] > seen_limits[-1], seen_limits)
check("ไม่มีความล้มเหลวค้างไว้ เพราะสุดท้ายสำเร็จ",
      "features" not in fe.LAST_FAILURE, fe.LAST_FAILURE)

# The real feed is about 25 MB, over the ceiling that protects a 512 MB
# instance. Asking for a smaller page is the answer; refusing outright left
# the layer loading nothing at all for a deploy.
reset()
sizes = []


def bulky(request):
    limit = int(dict(request.url.params).get("limit", 0))
    sizes.append(limit)
    big = limit > 8000
    return serve_features(features([SQUARE]),
                          size=int((settings.gistda_max_download_mb + 2) * 1024 * 1024)
                          if big else 0)(request)


rings = with_upstream(bulky, fe.all_rings)
check("ชุดเต็มใหญ่เกินเพดาน -> ขอชุดเล็กลงแทนที่จะยอมแพ้", len(rings) == 1, rings)
check("และไล่ขนาดลงจริง", len(sizes) >= 2 and sizes[0] > sizes[-1], sizes)

reset()
check("รวมรูปจาก 2 แหล่งเข้าด้วยกันได้",
      len(routing._merge_polygons(
          {"type": "MultiPolygon", "coordinates": [[SQUARE]]},
          {"type": "MultiPolygon", "coordinates": [[SQUARE]]})["coordinates"]) == 2)
check("ไม่มีอะไรต้องหลบ -> ไม่ส่ง avoid ไปเลย",
      routing._merge_polygons(None, None) is None)

# ------------------------------------------- the line that must not be crossed

reset()
with TestClient(app) as c:
    # A route through water the satellite saw, with nobody having reported
    # anything. The satellite may send this app looking for a way round. It may
    # not tell the driver the road is impassable: it is an area seen from
    # orbit, up to a day old, and a raised road through flooded fields is
    # ordinary here. If this check ever fails, an observation has been promoted
    # into a claim it cannot support.
    everywhere = [[[100.0, 13.0], [101.5, 13.0], [101.5, 14.5],
                   [100.0, 14.5], [100.0, 13.0]]]
    body = with_upstream(
        serve_features(features(everywhere)),
        lambda: asyncio.to_thread(
            lambda: c.post("/api/route/check", json={
                "origin": {"lat": 13.7460, "lng": 100.5340},
                "destination": {"lat": 13.7650, "lng": 100.5620},
            })),
    )
    if body.status_code == 200:
        data = body.json()
        check("ดาวเทียมเห็นน้ำ แต่ไม่มีใครแจ้ง -> คำตัดสินยังเป็น 'ไปได้'",
              data["verdict"] == "clear", data["verdict"])
        check("แต่บอกผู้ใช้ว่าเส้นทางผ่านพื้นที่ที่ดาวเทียมเห็นน้ำ",
              "ดาวเทียม" in (data.get("degraded") or ""), data.get("degraded"))
        check("และย้ำว่าไม่ได้แปลว่าถนนผ่านไม่ได้",
              "ไม่ได้แปลว่าถนนผ่านไม่ได้" in (data.get("degraded") or ""),
              data.get("degraded"))
    else:
        check("เรียก route-check ได้", False, f"{body.status_code} {body.text[:160]}")

    # And with the layer off entirely, nothing about routing changes.
    settings.gistda_api_key = ""
    plain = c.post("/api/route/check", json={
        "origin": {"lat": 13.7460, "lng": 100.5340},
        "destination": {"lat": 13.7650, "lng": 100.5620},
    })
    check("ไม่ตั้งคีย์ -> เช็คเส้นทางทำงานเหมือนเดิมทุกอย่าง",
          plain.status_code == 200 and "ดาวเทียม" not in (plain.json().get("degraded") or ""),
          plain.text[:160])

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL FLOOD-EXTENT CHECKS PASSED")
sys.exit(1 if fails else 0)
