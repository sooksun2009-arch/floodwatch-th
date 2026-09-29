"""Why a detour did not appear must be visible from outside the container.

A key can be set, the "not configured" warning gone, and still no detour
offered. The reason used to be swallowed by a bare `return None`.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/o.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["GISTDA_API_KEY"] = ""
os.environ["LONGDO_API_KEY"] = ""

import asyncio

import httpx

from app import routing
from app.config import settings

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


A, B = (13.72, 100.75), (13.668, 100.604)
BOX = {"type": "MultiPolygon", "coordinates": [[[[100.70, 13.70], [100.71, 13.70],
                                                 [100.71, 13.71], [100.70, 13.71],
                                                 [100.70, 13.70]]]]}


def with_response(status, payload):
    """Swap in a transport that answers without a network."""
    def handler(request):
        return httpx.Response(status, json=payload)
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)
    return real, Fake


settings.ors_api_key = ""
routing.LAST_ORS_FAILURE = None
asyncio.run(routing._ors_route(A, B, BOX))
check("ไม่มีคีย์ -> บอกว่ายังไม่ได้ตั้งค่า", routing.LAST_ORS_FAILURE == "ยังไม่ได้ตั้งค่าคีย์",
      routing.LAST_ORS_FAILURE)

settings.ors_api_key = "test-key"
for status, payload, want in [
    # Codes a reader can act on are said in plain words; the rest keep the
    # status, which is all there is to go on.
    (403, {"error": {"code": 2099}}, "คีย์ไม่ถูกต้องหรือถูกปฏิเสธ"),
    (429, {"error": {"code": 2004}}, "เกินโควตาการใช้งานของวันนี้"),
    (404, {"error": {"code": 2009}}, "ไม่พบเส้นทางที่เลี่ยงจุดน้ำท่วมได้ — น้ำกระจายจนไม่เหลือทางอ้อม"),
    (404, {"error": {"code": 2010}}, "จุดต้นทางหรือปลายทางอยู่ในพื้นที่น้ำท่วมเอง"),
    (400, {}, "HTTP 400"),
    (500, {"error": {"code": 9999}}, "HTTP 500 code 9999"),
]:
    real, Fake = with_response(status, payload)
    httpx.AsyncClient = Fake
    try:
        routing.LAST_ORS_FAILURE = None
        out = asyncio.run(routing._ors_route(A, B, BOX))
    finally:
        httpx.AsyncClient = real
    check(f"ORS ตอบ {status} -> บอกสาเหตุ ({want[:40]})",
          out is None and routing.LAST_ORS_FAILURE == want, routing.LAST_ORS_FAILURE)

ok_payload = {"features": [{"geometry": {"coordinates": [[100.75, 13.72], [100.70, 13.69],
                                                          [100.604, 13.668]]},
                            "properties": {"summary": {"distance": 21000, "duration": 1800}}}]}
real, Fake = with_response(200, ok_payload)
httpx.AsyncClient = Fake
try:
    routing.LAST_ORS_FAILURE = "ของเก่า"
    out = asyncio.run(routing._ors_route(A, B, BOX))
finally:
    httpx.AsyncClient = real
check("สำเร็จ -> ได้เส้นทาง และล้างสาเหตุเดิม",
      out is not None and out.distance_km == 21.0 and routing.LAST_ORS_FAILURE is None,
      (out, routing.LAST_ORS_FAILURE))

# The key must never appear in what we record.
check("สาเหตุที่บันทึกไม่มีคีย์ปนอยู่", "test-key" not in str(routing.LAST_ORS_FAILURE))
settings.ors_api_key = ""

# ------------------------------------------------- avoid areas over an endpoint
# ORS refuses the whole request (404 code 2010) when the start or finish sits
# inside an avoided area, so those areas are dropped before asking.
def ring(w, s, e, n):
    return [[[w, s], [e, s], [e, n], [w, n], [w, s]]]


OVER_ORIGIN = ring(100.74, 13.71, 100.76, 13.73)   # contains (13.72, 100.75)
OVER_DEST = ring(100.59, 13.66, 100.62, 13.68)     # contains (13.668, 100.604)
MIDWAY = ring(100.68, 13.69, 100.70, 13.71)        # contains neither

both = {"type": "MultiPolygon", "coordinates": [OVER_ORIGIN, MIDWAY, OVER_DEST]}
kept = routing.drop_polygons_containing(both, [A, B])
check("ทิ้งพื้นที่ที่คลุมต้นทางและปลายทาง เหลือแต่ที่อยู่ระหว่างทาง",
      kept is not None and kept["coordinates"] == [MIDWAY], kept)

only_origin = {"type": "MultiPolygon", "coordinates": [OVER_ORIGIN]}
check("ถ้าเหลือศูนย์พื้นที่ -> คืน None (ไม่ส่งลิสต์ว่างไปให้ ORS)",
      routing.drop_polygons_containing(only_origin, [A, B]) is None)
check("ไม่มีพื้นที่มาตั้งแต่ต้น -> None", routing.drop_polygons_containing(None, [A, B]) is None)
check("จุดนอกพื้นที่ -> ไม่ถูกทิ้ง",
      routing.drop_polygons_containing({"type": "MultiPolygon", "coordinates": [MIDWAY]},
                                       [A, B])["coordinates"] == [MIDWAY])
check("จุดในพื้นที่จริง ๆ ตรวจเจอ (ray casting ไม่ใช่แค่กรอบสี่เหลี่ยม)",
      routing._point_in_ring(13.72, 100.75, OVER_ORIGIN[0])
      and not routing._point_in_ring(13.72, 100.75, MIDWAY[0]))

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL ORS-DIAGNOSTIC CHECKS PASSED")
sys.exit(1 if fails else 0)
