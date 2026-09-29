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
    (403, {"error": {"code": 2099}}, "HTTP 403 code 2099"),
    (429, {"error": {"code": 2004}}, "HTTP 429 code 2004"),
    (400, {}, "HTTP 400"),
]:
    real, Fake = with_response(status, payload)
    httpx.AsyncClient = Fake
    try:
        routing.LAST_ORS_FAILURE = None
        out = asyncio.run(routing._ors_route(A, B, BOX))
    finally:
        httpx.AsyncClient = real
    check(f"ORS ตอบ {status} -> จำสาเหตุไว้ ({want})",
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

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL ORS-DIAGNOSTIC CHECKS PASSED")
sys.exit(1 if fails else 0)
