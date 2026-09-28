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

from app import flood_extent as fe
from app.config import settings
from app.main import app

fails = []
calls: list[httpx.Request] = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


A_PNG = fe.BLANK_TILE


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

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL FLOOD-EXTENT CHECKS PASSED")
sys.exit(1 if fails else 0)
