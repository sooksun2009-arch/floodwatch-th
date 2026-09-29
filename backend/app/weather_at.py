"""Rain at one camera: is it raining there now, and the next three hours.

Deliberately small. A camera popup needs one answer before someone drives
towards it -- is more water coming in the time it takes to get there -- not
a week's outlook. Two sources, kept apart because they are different kinds
of evidence:

  now    -- observed: a Longdo traffic camera within a short distance that
            currently has rain on it (the one Longdo endpoint this key can
            reach). None when that feed is not configured or not answering,
            which is not the same as "dry".
  hours  -- modelled: Open-Meteo's hourly chance and amount (free, no key,
            CC BY 4.0), for the next three hours.

Cached per ~5 km cell, so a hundred people opening the same camera cost one
upstream call.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import rain
from .config import settings
from .geo import haversine_km, in_thailand

logger = logging.getLogger("floodwatch.weather_at")

BANGKOK = timezone(timedelta(hours=7))
ATTRIBUTION = "พยากรณ์: Open-Meteo.com (CC BY 4.0)"
# A wet Longdo camera this close counts as rain "at" this one.
NEAR_KM = 1.5
HOURS = 3

_cache: dict[str, tuple[float, dict]] = {}


async def _open_meteo(lat: float, lng: float) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.open_meteo_url, params={
            "latitude": round(lat, 3), "longitude": round(lng, 3),
            "hourly": "precipitation_probability,precipitation",
            "forecast_hours": HOURS + 1,
            "timezone": "Asia/Bangkok",
        }, headers={"User-Agent": settings.http_user_agent})
        resp.raise_for_status()
        return resp.json()


def _hours(payload: dict, now: datetime) -> list[dict]:
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    mm = hourly.get("precipitation") or []
    this_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    out = []
    for i, stamp in enumerate(times):
        try:
            at = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        # The hours still ahead, starting with the one we are in.
        if at < this_hour:
            continue
        out.append({"time": at.strftime("%H:%M"),
                    "probability": probs[i] if i < len(probs) else None,
                    "mm": mm[i] if i < len(mm) else None})
        if len(out) == HOURS:
            break
    return out


async def _observed(lat: float, lng: float) -> dict | None:
    wet = await rain.raining_cameras()
    if not wet.get("available"):
        return None
    nearest = None
    for cam in wet.get("cameras") or []:
        dist = haversine_km(lat, lng, cam["lat"], cam["lng"])
        if dist <= NEAR_KM and (nearest is None or dist < nearest[0]):
            nearest = (dist, cam)
    if nearest is None:
        return {"raining": False}
    return {"raining": True, "level": nearest[1].get("rain_level"),
            "distance_m": int(nearest[0] * 1000)}


async def at(lat: float, lng: float) -> dict:
    if not in_thailand(lat, lng):
        raise ValueError("อยู่นอกประเทศไทย")
    key = f"{lat:.2f}/{lng:.2f}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < settings.weather_at_cache_sec:
        return hit[1]

    now = datetime.now(BANGKOK)
    hours: list[dict] = []
    forecast_error = None
    try:
        hours = _hours(await _open_meteo(lat, lng), now)
    except Exception as exc:
        # Status or exception type only -- enough to diagnose from outside the
        # container, nothing from the upstream body.
        forecast_error = (f"HTTP {exc.response.status_code}"
                          if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__)
        logger.warning("ดึงพยากรณ์ฝนจาก Open-Meteo ไม่สำเร็จ: %s", forecast_error)
    observed = None
    try:
        observed = await _observed(lat, lng)
    except Exception as exc:
        logger.warning("อ่านฝนจากกล้องไม่สำเร็จ: %s", type(exc).__name__)

    value = {"now": observed, "hours": hours,
             "attribution": ATTRIBUTION if hours else None,
             "forecast_error": forecast_error}
    # A failed fetch is not cached for long: the next person should retry.
    if hours:
        _cache[key] = (time.monotonic(), value)
        if len(_cache) > 2000:
            _cache.clear()
    return value
