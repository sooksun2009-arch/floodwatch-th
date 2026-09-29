"""Floodboard road segments: what is kept, what counts as "on the route", and
how much a low-confidence segment is allowed to say."""
import asyncio
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/r.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["OSRM_BASE_URL"] = "http://127.0.0.1:9"  # refused: straight-line route
os.environ["ORS_API_KEY"] = ""
os.environ["GISTDA_API_KEY"] = ""
os.environ["LONGDO_API_KEY"] = ""

import time

from fastapi.testclient import TestClient

from app import floodroads
from app.config import settings
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def feature(coords, sedan="blocked", conf=0.8, cleared=False, name="ถนนทดสอบ", depth=40,
            closed=False):
    return {"type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": [coords]},
            "properties": {"name": name, "nameEn": "Test Rd", "depthCm": depth,
                           "closedAll": closed, "cleared": cleared, "conf": conf,
                           "updated": 1790666310000, "verdict": {"sedan": sedan,
                                                                "motorbike": sedan},
                           "sources": ["traffy"], "obs": ["news:https://x.example/" + "a" * 500]}}


# ------------------------------------------------------------ what is kept
check("น้ำลดแล้ว (cleared) -> ไม่แสดง",
      floodroads.slim(feature([[100.5, 13.7], [100.51, 13.7]], cleared=True)) is None)
check("ความมั่นใจต่ำกว่าเกณฑ์ -> ไม่แสดง",
      floodroads.slim(feature([[100.5, 13.7], [100.51, 13.7]], conf=0.1)) is None)
kept = floodroads.slim(feature([[100.5, 13.7], [100.51, 13.7]]))
check("ตัดรายการลิงก์ข่าวดิบทิ้ง (ไฟล์เล็กลง)", kept and "obs" not in kept, kept)
check("ปิดการจราจร -> ถือว่ารถเก๋งผ่านไม่ได้",
      floodroads.slim(feature([[100.5, 13.7], [100.51, 13.7]], sedan="caution",
                              closed=True))["sedan"] == "blocked")
elevated = feature([[100.5, 13.7], [100.51, 13.7]], name="ทางยกระดับอุตราภิมุข")
check("ทางยกระดับ/ทางด่วน -> ไม่นับ (พื้นลอยน้ำไม่ขัง)", floodroads.slim(elevated) is None)
motorway = feature([[100.5, 13.7], [100.51, 13.7]], name="ไม่มีคำบอก")
motorway["properties"]["hw"] = "motorway"
check("ประเภทถนน motorway -> ไม่นับ", floodroads.slim(motorway) is None)
check("แถบสีตามความลึก", floodroads.slim(feature([[100.5, 13.7], [100.51, 13.7]], depth=25))["band"] == "20")

# ------------------------------------------------------------ route matching
# A straight east-west route along latitude 13.700.
LAT = 13.700
along = floodroads.slim(feature([[100.520 + i * 0.002, LAT + 0.0001] for i in range(6)],
                                name="ถนนตามเส้นทาง"))
crossing = floodroads.slim(feature([[100.540, LAT - 0.01 + i * 0.004] for i in range(6)],
                                   name="ซอยที่ตัดผ่าน", conf=0.9))
unsure = floodroads.slim(feature([[100.546 + i * 0.001, LAT] for i in range(5)],
                                 name="ถนนไม่แน่ใจ", conf=0.35))
far = floodroads.slim(feature([[100.53, 13.75], [100.54, 13.75]], name="ถนนไกล"))

path = [(LAT, 100.50 + i * 0.005) for i in range(13)]
found = {r["name"]: r for r in floodroads.along_route([along, crossing, unsure, far], path)}
check("ช่วงถนนที่วิ่งตามเส้นทาง -> นับ", "ถนนตามเส้นทาง" in found, list(found))
check("ซอยที่แค่ตัดผ่านเส้นทาง -> ไม่นับ", "ซอยที่ตัดผ่าน" not in found, list(found))
check("ถนนที่อยู่ไกล -> ไม่นับ", "ถนนไกล" not in found, list(found))
check("มั่นใจ + ผ่านไม่ได้ -> ระดับ severe", found.get("ถนนตามเส้นทาง", {}).get("level") == "severe",
      found.get("ถนนตามเส้นทาง"))
check("ไม่มั่นใจ -> เตือนได้แค่ระวัง (shallow) ไม่ปิดถนน",
      found.get("ถนนไม่แน่ใจ", {}).get("level") == "shallow", found.get("ถนนไม่แน่ใจ"))
check("บอกตำแหน่งบนเส้นทาง (กม.)",
      2.0 < found.get("ถนนตามเส้นทาง", {}).get("along_km", 0) < 2.4,
      found.get("ถนนตามเส้นทาง", {}).get("along_km"))


# ------------------------------------------------------------ in a route check
def load(segs):
    floodroads._state.update(at=time.monotonic(), segments=segs, error=None,
                             fetched_at=int(time.time()))


settings.floodroads_enabled = True
with TestClient(app) as c:
    body = {"origin": {"lat": LAT, "lng": 100.50}, "destination": {"lat": LAT, "lng": 100.56}}

    load([])
    r = c.post("/api/route/check", json=body)
    check("ไม่มีถนนน้ำท่วม -> ไม่พบ", r.status_code == 200 and r.json()["verdict"] == "clear",
          r.text[:200])
    check("ไม่มีข้อมูล Floodboard ในคำตอบ -> ไม่ใส่เครดิต",
          r.json().get("roads_attribution") is None)

    load([unsure])
    r = c.post("/api/route/check", json=body).json()
    check("มีแต่ช่วงไม่มั่นใจ -> ระวัง ไม่ใช่ห้ามผ่าน", r["verdict"] == "caution", r["verdict"])

    load([along, crossing, unsure])
    r = c.post("/api/route/check", json=body).json()
    check("มีช่วงที่ผ่านไม่ได้บนเส้นทาง -> ไม่ควรใช้เส้นทางนี้", r["verdict"] == "blocked",
          r["verdict"])
    check("ส่งรายการถนนน้ำท่วมกลับไปด้วย",
          [x["name"] for x in r["routes"][0]["roads"]] == ["ถนนตามเส้นทาง", "ถนนไม่แน่ใจ"],
          r["routes"][0]["roads"])
    check("คำแนะนำภาษาไทยพูดถึงถนนและที่มา",
          "ถนนตามเส้นทาง" in r["advice"] and "Floodboard" in r["advice"], r["advice"][:300])
    check("ใส่เครดิต CC BY", "CC BY 4.0" in (r.get("roads_attribution") or ""),
          r.get("roads_attribution"))

    # ---------------------------------------------------------- map layer
    load([along, unsure])
    g = c.get("/api/flood-roads").json()
    check("ชั้นแผนที่ส่ง GeoJSON พร้อมเครดิต",
          len(g["features"]) == 2 and "Floodboard" in g["attribution"], {k: g[k] for k in g if k != "features"})

    # ---------------------------------------------------------- feed down
    async def boom():
        raise RuntimeError("down")

    real = floodroads._fetch
    floodroads._fetch = boom
    floodroads._state["at"] = 0.0  # expired
    kept = asyncio.run(floodroads.segments())
    check("ต้นทางล่ม -> ใช้ข้อมูลชุดล่าสุดที่ดึงได้ต่อ", kept is not None and len(kept) == 2,
          kept and len(kept))
    check("และจำว่าล่มไว้บอก", floodroads.status()["error"] == "RuntimeError",
          floodroads.status())
    floodroads._fetch = real

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL FLOOD-ROAD CHECKS PASSED")
sys.exit(1 if fails else 0)
