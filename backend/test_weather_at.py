"""Rain at a camera: now (observed) and the next three hours (modelled)."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/w.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"

from fastapi.testclient import TestClient

from app import rain, weather_at
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


now = datetime.now(timezone(timedelta(hours=7))).replace(minute=0, second=0, microsecond=0)
hours = [(now + timedelta(hours=h - 1)).strftime("%Y-%m-%dT%H:%M") for h in range(6)]
calls = {"meteo": 0}


async def fake_meteo(lat, lng):
    calls["meteo"] += 1
    return {"hourly": {"time": hours, "precipitation_probability": [90, 30, 60, 80, 10, 5],
                       "precipitation": [5.0, 0.1, 1.2, 3.4, 0.0, 0.0]}}


async def wet_nearby():
    return {"available": True, "cameras": [
        {"lat": 13.7205, "lng": 100.7505, "rain_level": "ฝนปานกลาง"},  # ~70 m away
        {"lat": 14.5, "lng": 100.5, "rain_level": "ฝนหนัก"},           # far away
    ]}


async def dry():
    return {"available": True, "cameras": []}


async def no_key():
    return {"available": False, "cameras": []}


weather_at._open_meteo = fake_meteo

with TestClient(app) as c:
    rain.raining_cameras = wet_nearby
    r = c.get("/api/rain/at", params={"lat": 13.72, "lng": 100.75})
    check("เรียกได้โดยไม่ต้องล็อกอิน", r.status_code == 200, r.text[:200])
    d = r.json()
    check("ได้ 3 ชั่วโมงข้างหน้า เริ่มจากชั่วโมงปัจจุบัน",
          [h["time"] for h in d["hours"]] == [(now + timedelta(hours=i)).strftime("%H:%M") for i in range(3)],
          d["hours"])
    check("ข้ามชั่วโมงที่ผ่านไปแล้ว", d["hours"][0]["probability"] == 30, d["hours"])
    check("กล้อง Longdo ใกล้ ๆ เห็นฝน -> ฝนตกตอนนี้",
          d["now"] == {"raining": True, "level": "ฝนปานกลาง", "distance_m": d["now"]["distance_m"]}
          and d["now"]["distance_m"] < 200, d["now"])
    check("ให้เครดิต Open-Meteo", "Open-Meteo" in (d["attribution"] or ""))

    before = calls["meteo"]
    c.get("/api/rain/at", params={"lat": 13.7201, "lng": 100.7502})
    check("จุดใกล้กันใช้แคชร่วมกัน (ไม่ยิงซ้ำ)", calls["meteo"] == before, calls)

    weather_at._cache.clear()
    rain.raining_cameras = dry
    d = c.get("/api/rain/at", params={"lat": 13.72, "lng": 100.75}).json()
    check("ไม่มีกล้องไหนเห็นฝน -> ไม่มีฝน (false)", d["now"] == {"raining": False}, d["now"])

    weather_at._cache.clear()
    rain.raining_cameras = no_key
    d = c.get("/api/rain/at", params={"lat": 13.72, "lng": 100.75}).json()
    check("ไม่ได้ตั้งคีย์ Longdo -> ไม่รู้ (null) ไม่ใช่ 'ไม่มีฝน'", d["now"] is None, d["now"])

    async def boom(lat, lng):
        raise RuntimeError("down")

    utc_now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    async def fake_met(lat, lng):
        return {"properties": {"timeseries": [
            {"time": (utc_now + timedelta(hours=h - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "data": {"next_1_hours": {"details": {"precipitation_amount": float(h)}}}}
            for h in range(6)]}}

    weather_at._open_meteo = boom
    weather_at._met_no = fake_met
    weather_at._cache.clear()
    d = c.get("/api/rain/at", params={"lat": 13.72, "lng": 100.75}).json()
    check("Open-Meteo ล่ม -> ใช้ MET Norway แทน", [h["mm"] for h in d["hours"]] == [1.0, 2.0, 3.0], d)
    check("MET Norway ไม่มีโอกาสฝน -> ส่ง null ไม่เดา", all(h["probability"] is None for h in d["hours"]), d)
    check("เครดิตเปลี่ยนเป็น MET Norway", "MET Norway" in (d["attribution"] or ""), d["attribution"])

    weather_at._met_no = boom
    weather_at._cache.clear()
    r = c.get("/api/rain/at", params={"lat": 13.72, "lng": 100.75})
    check("ล่มทั้งสองแหล่ง -> ยังตอบได้ ไม่มีพยากรณ์ และบอกเหตุผล",
          r.status_code == 200 and r.json()["hours"] == [] and "met.no" in (r.json()["forecast_error"] or ""),
          r.text[:200])

    r = c.get("/api/rain/at", params={"lat": 35.0, "lng": 139.0})
    check("นอกประเทศไทย -> ปฏิเสธ", r.status_code in (400, 422), r.status_code)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL RAIN-AT CHECKS PASSED")
sys.exit(1 if fails else 0)
