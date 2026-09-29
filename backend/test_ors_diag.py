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

# ------------------------------------------------- what gets avoided
# Steering around only the water already matched to a route sends the detour
# down the next street, which may be flooded too.
def seg(name, sedan, conf, w, s_, e, n):
    return {"name": name, "sedan": sedan, "conf": conf,
            "lines": [[[w, s_], [e, n]]]}


# A route running north-east; "near" means near this line, not near a box
# around it — the corridor is what a detour will actually use.
NEAR = [(13.70 + i * 0.01, 100.70 + i * 0.01) for i in range(9)]
SEGS = [
    seg("ท่วมหนัก บนเส้นทาง", "blocked", 0.9, 100.70, 13.70, 100.705, 13.705),
    seg("เสี่ยง บนเส้นทาง", "risky", 0.8, 100.72, 13.72, 100.725, 13.725),
    seg("ไม่มั่นใจ", "blocked", 0.2, 100.74, 13.74, 100.745, 13.745),
    seg("ผ่านได้", "caution", 0.9, 100.76, 13.76, 100.765, 13.765),
    seg("ไกลออกไป", "blocked", 0.9, 101.50, 14.50, 101.51, 14.51),
]

poly = routing.nearby_road_polygons(SEGS, NEAR)
check("เอาทุกจุดน้ำท่วมใกล้เส้นทาง ไม่ใช่แค่ที่อยู่บนเส้นทาง",
      poly is not None and len(poly["coordinates"]) == 2, poly and len(poly["coordinates"]))
check("ข้ามจุดที่ความมั่นใจต่ำ และจุดที่รถผ่านได้",
      poly is not None and len(poly["coordinates"]) == 2)
check("ข้ามจุดที่อยู่ไกลจากเส้นทาง",
      all(abs(c[0]) < 101 for rings in poly["coordinates"] for c in rings[0]))

# The bug this ranking exists for: a real 27 km corridor had 282 candidates,
# 197 of them impassable, so ranking by severity sent sixty areas from all
# over the box and left out the flooded road actually on the route.
far_blocked = [seg(f"ไกล {i}", "blocked", 0.99, 100.70 + 0.02, 13.70 + i * 0.0005,
                   100.705 + 0.02, 13.705 + i * 0.0005) for i in range(80)]
on_route = seg("อยู่บนเส้นทางเอง", "risky", 0.6, 100.70, 13.70, 100.7005, 13.7005)
ranked = routing.nearby_road_polygons(far_blocked + [on_route], NEAR, limit=20)
covered = any(routing._point_in_ring(13.70025, 100.70025, rings[0])
              for rings in ranked["coordinates"])
check("จุดที่อยู่บนเส้นทางต้องถูกกันก่อน แม้จะรุนแรงน้อยกว่าจุดที่อยู่ไกล", covered)

only_blocked = routing.nearby_road_polygons(SEGS, NEAR, blocked_only=True)
check("โหมดสำรอง: เอาเฉพาะจุดที่รถเก๋งผ่านไม่ได้",
      only_blocked is not None and len(only_blocked["coordinates"]) == 1, only_blocked)

capped = routing.nearby_road_polygons(SEGS * 40, NEAR, limit=3)
check("จำกัดจำนวนไม่ให้คำขอใหญ่เกิน", len(capped["coordinates"]) == 3,
      len(capped["coordinates"]))
check("ไม่มีถนนน้ำท่วมเลย -> None", routing.nearby_road_polygons([], NEAR) is None
      and routing.nearby_road_polygons(None, NEAR) is None)

# Each area hugs its road: a strip, not a block the size of the road's length.
# A straight 1 km road east-west, so "thin" is measurable across it.
straight = routing.nearby_road_polygons(
    [seg("ถนนตรงยาว 1 กม.", "blocked", 0.9, 100.70, 13.70, 100.7093, 13.70)], NEAR)
ring = straight["coordinates"][0][0]
along_m = (max(c[0] for c in ring) - min(c[0] for c in ring)) * 111.32 * 0.97 * 1000
across_m = (max(c[1] for c in ring) - min(c[1] for c in ring)) * 110.57 * 1000
check("พื้นที่ห้ามผ่านเป็นแถบแคบทาบตามถนน ไม่ใช่กล่องเท่าความยาวถนน",
      across_m < 150 and along_m > 900, f"ยาว {along_m:.0f} m กว้าง {across_m:.0f} m")

# ------------------------------------------------- water at the doorstep
# No detour can route around the road you are standing on, so a route that
# still says "do not go" there is right, and should say why.
class FakeGeo:
    def __init__(self, km):
        self.distance_km = km


class FakeAnalysis:
    def __init__(self, km, roads):
        self.geometry = FakeGeo(km)
        self.obstacles = []
        self.roads = roads


def road_at(km, sedan="blocked", confident=True):
    return {"along_km": km, "sedan": sedan, "confident": confident}


check("ผ่านไม่ได้ตั้งแต่ต้นทาง -> บอกว่าต้นทาง",
      routing._blocked_at_an_end(FakeAnalysis(20, [road_at(0.04)])) == "ต้นทาง")
check("ผ่านไม่ได้ตรงปลายทาง -> บอกว่าปลายทาง",
      routing._blocked_at_an_end(FakeAnalysis(20, [road_at(19.9)])) == "ปลายทาง")
check("ผ่านไม่ได้กลางทาง -> ไม่ใช่กรณีนี้ (เลี่ยงได้)",
      routing._blocked_at_an_end(FakeAnalysis(20, [road_at(10)])) is None)
check("จุดที่ความมั่นใจต่ำ ไม่นับว่าผ่านไม่ได้",
      routing._blocked_at_an_end(FakeAnalysis(20, [road_at(0.04, confident=False)])) is None)
check("จุดที่แค่เสี่ยง ไม่นับว่าผ่านไม่ได้",
      routing._blocked_at_an_end(FakeAnalysis(20, [road_at(0.04, sedan="risky")])) is None)

# ------------------------------------------------- one fact, one explanation
# With water at the doorstep, "no way round the flooding" is true but is not
# the reason, and stacking both reads as the app arguing with itself.
from datetime import timedelta

from app.database import SessionLocal, engine
from app.models import Base, FloodReport, utcnow

Base.metadata.create_all(engine)
settings.ors_api_key = "test-key"

with SessionLocal() as db:
    db.add(FloodReport(lat=13.70, lng=100.60, place="ตรงต้นทาง", level="closed", depth_cm=70,
                       status="approved", expires_at=utcnow() + timedelta(hours=6)))
    # Exactly half way along the straight line below, so it lands inside the
    # corridor rather than merely near it.
    db.add(FloodReport(lat=13.69, lng=100.605, place="กลางทาง", level="closed", depth_cm=70,
                       status="approved", expires_at=utcnow() + timedelta(hours=6)))
    db.commit()

    async def no_route(origin, dest, avoid):
        routing.LAST_ORS_FAILURE = routing.ORS_CODE_TH[2009]
        return None

    real_ors = routing._ors_route
    routing._ors_route = no_route
    at_door = asyncio.run(routing.check_route(db, (13.70, 100.60), (13.78, 100.66)))
    mid_way = asyncio.run(routing.check_route(db, (13.60, 100.55), (13.78, 100.66)))
    routing._ors_route = real_ors

door_text = at_door["degraded"] or ""
mid_text = mid_way["degraded"] or ""
check("ติดที่ต้นทาง -> บอกว่าติดตรงต้นทาง", "อยู่ตรงต้นทาง" in door_text, door_text)
check("ติดที่ต้นทาง -> ไม่พ่วงเหตุผลเรื่องทางเลี่ยงซ้ำ",
      "ไม่พบเส้นทางที่เลี่ยง" not in door_text and "ยังไม่มีพื้นที่ที่ชัดพอ" not in door_text,
      door_text)
check("ติดกลางทาง -> ยังบอกเหตุผลว่าหาทางเลี่ยงไม่ได้",
      "อยู่ตรงต้นทาง" not in mid_text and ("ไม่พบเส้นทางที่เลี่ยง" in mid_text
                                            or "ยังไม่มีพื้นที่ที่ชัดพอ" in mid_text), mid_text)
settings.ors_api_key = ""

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL ORS-DIAGNOSTIC CHECKS PASSED")
sys.exit(1 if fails else 0)
