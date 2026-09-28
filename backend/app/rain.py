"""Rain radar and short-range forecast, from Longdo Weather.

Everything here answers a question the flood map on its own cannot: not "is
this road under water now" but "is more water on its way while I am driving".
A route that reads clear at the moment someone leaves can be under heavy rain
by the time they are halfway along it, and that is the decision this data
changes.

Rain is never turned into a flood report. The same rule the canal gauges live
under applies here and for the same reason: a downpour is a reason to expect
trouble, not evidence that a particular road is impassable, and roads drain at
wildly different rates. It stays its own layer and its own sentence.

Calls go through this app rather than from the page so the key stays on the
server, which also puts every call behind one cache. The radar refreshes about
every ten minutes, so asking more often than that spends quota to receive the
same picture.
"""
import asyncio
import logging
import math
import time
from dataclasses import dataclass

import httpx

from .config import settings

logger = logging.getLogger("floodwatch.rain")

RADAR_TILE = "/rain/api/v1/layer/latest/{z}/{x}/{y}.png"
POLYGON_URL = "/rain/api/v1/polygon"
FORECAST_AREA_URL = "/rain/api/v1/forecast/area"
CAMERAS_URL = "/rain/api/v1/cameras"

# Upstream's own scale, 0 (dry) to 5 (very heavy). Anything at or above this is
# worth interrupting someone's trip planning for; below it, rain is normal
# weather and saying so on every route would train people to ignore the line.
NOTABLE_INTENSITY = 3

# Coverage below this is a shower clipping the corner of a long route rather
# than weather on the road, whatever its peak intensity.
NOTABLE_COVERAGE_PCT = 15.0


def enabled() -> bool:
    return bool(settings.longdo_api_key)


# Why each kind of call last failed, so an operator can tell a wrong key from
# an endpoint their plan does not include without shell access to the logs.
LAST_FAILURE: dict[str, str] = {}


def _remember_failure(kind: str, exc: BaseException) -> None:
    detail = describe_failure(exc)
    LAST_FAILURE[kind] = detail
    logger.warning("เรียก %s ไม่สำเร็จ: %s", kind, detail)


def _remember_success(kind: str) -> None:
    """Clear the old failure. Without this a fault fixed hours ago still reads
    as the current state, which cost a round of wrong diagnosis already."""
    LAST_FAILURE.pop(kind, None)


PROBES: dict[str, tuple[str, str, dict]] = {
    "cameras": ("GET", CAMERAS_URL, {}),
    "location": ("GET", "/rain/api/v1/location", {"lat": 13.7563, "lon": 100.5018}),
    "area": ("GET", "/rain/api/v1/area",
             {"lat": 13.7563, "lon": 100.5018, "radius_km": 5}),
    "forecast_location": ("GET", "/rain/api/v1/forecast/location",
                          {"lat": 13.7563, "lon": 100.5018}),
    "forecast_area": ("GET", FORECAST_AREA_URL,
                      {"lat": 13.7563, "lon": 100.5018, "radius_km": 10}),
    "layer_list": ("GET", "/rain/api/v1/layer/list", {}),
    "polygon": ("POST", POLYGON_URL, {}),
}

_POLYGON_PROBE = [[[100.50, 13.75], [100.52, 13.75], [100.52, 13.77],
                   [100.50, 13.77], [100.50, 13.75]]]


async def probe_all() -> dict:
    """Ask each endpoint once and report what it said.

    A key can be accepted by one endpoint and refused by another on the same
    plan — which is exactly what happened here, with cameras and radar tiles
    working while the polygon and forecast calls returned a flat 403. Guessing
    at which is which wasted a round already.
    """
    if not enabled():
        return {"enabled": False, "results": {}}

    async def one(name):
        method, path, params = PROBES[name]
        try:
            async with _client() as client:
                if method == "POST":
                    response = await client.post(
                        path, params={"key": settings.longdo_api_key},
                        json={"type": "Polygon", "coordinates": _POLYGON_PROBE})
                else:
                    response = await client.get(
                        path, params={"key": settings.longdo_api_key, **params})
            body = (response.text or "")[:120]
            key = settings.longdo_api_key
            if key:
                body = body.replace(key, "<คีย์>")
            return {"status": response.status_code,
                    "ok": response.status_code == 200,
                    "body": " ".join(body.split())}
        except Exception as exc:
            return {"status": None, "ok": False, "body": describe_failure(exc)}

    names = list(PROBES)
    # Sequential on purpose: their gateway limits requests per minute, and a
    # burst would produce rate-limit errors that look like the fault being
    # investigated.
    results = {}
    for name in names:
        results[name] = await one(name)
        await asyncio.sleep(0.4)
    return {"enabled": True, "results": results}


# ---------------------------------------------------------------- caching

@dataclass
class _Entry:
    at: float
    value: object


_cache: dict[str, _Entry] = {}
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _cached(key: str, ttl: float, produce):
    """One in-flight fetch per key, and one answer shared by everyone waiting.

    Without the per-key lock a burst of route checks during a storm — exactly
    when this is busiest — would each miss the cache and each spend a call.
    """
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit.at < ttl:
        return hit.value

    async with _locks_guard:
        lock = _locks.setdefault(key, asyncio.Lock())

    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit.at < ttl:
            return hit.value
        value = await produce()
        _cache[key] = _Entry(at=time.monotonic(), value=value)
        return value


def describe_failure(exc: BaseException) -> str:
    """What the upstream actually said, with our key taken back out.

    Swallowing this into a log was a mistake already made once with the
    Bangkok gauges: "it failed" cannot distinguish a wrong key from a product
    that does not include the endpoint from a request that timed out, and
    those have nothing in common but the symptom. The key is stripped because
    error text often quotes the request URL back.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        body = (exc.response.text or "")[:200]
        detail = f"HTTP {exc.response.status_code}: {body}"
    else:
        detail = f"{type(exc).__name__}: {exc}"[:220]
    key = settings.longdo_api_key
    if key:
        detail = detail.replace(key, "<คีย์>")
    return " ".join(detail.split())


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.longdo_weather_base_url.rstrip("/"),
        timeout=settings.rain_timeout_sec,
        headers={"User-Agent": settings.http_user_agent},
    )


# ---------------------------------------------------------------- geometry

def corridor_polygon(path: list[list[float]], width_km: float) -> list[list[float]]:
    """A closed ring roughly enclosing a route, as GeoJSON [lon, lat].

    Not a true buffer — a bounding box around the whole path would drag in
    weather nowhere near the road on any route that bends, and a real buffer
    needs a geometry library this app deliberately does not carry. This walks
    the path and offsets each point perpendicular to its own direction, which
    follows the route closely enough for a rain statistic.
    """
    points = [(p[0], p[1]) for p in path if len(p) >= 2]
    if len(points) < 2:
        return []

    # Thin the path: radar pixels are kilometres wide, so hundreds of vertices
    # metres apart buy nothing and make the request large.
    step = max(1, len(points) // 60)
    points = points[::step] + [points[-1]]

    half = width_km / 2
    left: list[list[float]] = []
    right: list[list[float]] = []
    for index, (lat, lng) in enumerate(points):
        nxt = points[min(index + 1, len(points) - 1)]
        prv = points[max(index - 1, 0)]
        dlat = nxt[0] - prv[0]
        dlng = (nxt[1] - prv[1]) * math.cos(math.radians(lat))
        length = math.hypot(dlat, dlng) or 1e-9
        # Perpendicular, converted from kilometres to degrees.
        off_lat = (-dlng / length) * (half / 111.0)
        off_lng = (dlat / length) * (half / (111.0 * max(0.2, math.cos(math.radians(lat)))))
        left.append([lng + off_lng, lat + off_lat])
        right.append([lng - off_lng, lat - off_lat])

    ring = left + list(reversed(right))
    ring.append(ring[0])
    return ring


def sample_points(path: list[list[float]], count: int) -> list[tuple[float, float]]:
    """A few points spread along the route, for the per-area forecast calls."""
    points = [(p[0], p[1]) for p in path if len(p) >= 2]
    if not points:
        return []
    if len(points) <= count:
        return points
    step = (len(points) - 1) / (count - 1) if count > 1 else 0
    return [points[round(i * step)] for i in range(count)]


# ---------------------------------------------------------------- upstream

async def rain_now(path: list[list[float]]) -> dict | None:
    """Rain over the route corridor right now."""
    ring = corridor_polygon(path, settings.rain_corridor_km)
    if not enabled() or len(ring) < 4:
        return None

    # Key on a coarse shape, not every vertex: two route checks along the same
    # road should share an answer.
    key = "now:" + ",".join(f"{c[0]:.2f}/{c[1]:.2f}" for c in ring[::5])

    async def fetch():
        async with _client() as client:
            response = await client.post(
                POLYGON_URL,
                params={"key": settings.longdo_api_key},
                json={"type": "Polygon", "coordinates": [ring]},
            )
            response.raise_for_status()
            return response.json()

    try:
        payload = await _cached(key, settings.rain_cache_sec, fetch)
    except Exception as exc:
        _remember_failure("polygon", exc)
        return None

    _remember_success("polygon")
    stats = (payload or {}).get("stats") or {}
    if not stats:
        return None
    return {
        "coverage_pct": stats.get("rain_coverage_pct"),
        "max_intensity": stats.get("max_intensity"),
        "avg_intensity": stats.get("avg_intensity"),
        "level": (stats.get("dominant_level") or {}).get("description"),
        "last_updated": (payload or {}).get("last_updated"),
    }


async def forecast_at(lat: float, lng: float) -> list[dict]:
    """Short-range forecast for one stretch of the route."""
    if not enabled():
        return []

    # Round the key: a radar cell is kilometres across, so two nearby points
    # have the same weather and should not cost two calls.
    key = f"fc:{lat:.2f}/{lng:.2f}"

    async def fetch():
        async with _client() as client:
            response = await client.get(FORECAST_AREA_URL, params={
                "key": settings.longdo_api_key,
                "lat": lat, "lon": lng,
                "radius_km": settings.rain_forecast_radius_km,
            })
            response.raise_for_status()
            return response.json()

    try:
        payload = await _cached(key, settings.rain_cache_sec, fetch)
    except Exception as exc:
        _remember_failure("forecast", exc)
        return []

    _remember_success("forecast")
    out: list[dict] = []
    for slot, lead in zip((payload or {}).get("forecast") or [],
                          (payload or {}).get("lead_minutes") or []):
        # A slot the upstream could not compute is not a forecast of no rain.
        if not slot.get("available"):
            continue
        stats = slot.get("stats") or {}
        out.append({
            "lead_minutes": lead,
            "max_intensity": stats.get("max_intensity"),
            "coverage_pct": stats.get("rain_coverage_pct"),
            "level": (stats.get("dominant_level") or {}).get("description"),
        })
    return out


async def route_rain(path: list[list[float]]) -> dict | None:
    """Rain over a route now, and what is heading for it.

    Returns None when the key is unset, so the rest of the answer is unchanged
    on a deployment that has not configured this.
    """
    if not enabled() or len(path) < 2:
        return None

    samples = sample_points(path, settings.rain_forecast_samples)
    results = await asyncio.gather(
        rain_now(path),
        *[forecast_at(lat, lng) for lat, lng in samples],
        return_exceptions=True,
    )
    now = results[0] if not isinstance(results[0], BaseException) else None

    # Worst case across the route per lead time: someone needs to know about
    # the one stretch that is about to get hit, not the average of the trip.
    worst: dict[int, dict] = {}
    for result in results[1:]:
        if isinstance(result, BaseException):
            continue
        for slot in result:
            lead = slot.get("lead_minutes")
            if lead is None:
                continue
            current = worst.get(lead)
            if current is None or (slot.get("max_intensity") or 0) > (current.get("max_intensity") or 0):
                worst[lead] = slot

    soon = [worst[lead] for lead in sorted(worst)]
    if now is None and not soon:
        return None

    return {"now": now, "soon": soon, "summary": summarise(now, soon)}


def summarise(now: dict | None, soon: list[dict]) -> str | None:
    """One sentence, or nothing. Ordinary weather does not get a sentence."""
    def notable(entry: dict | None) -> bool:
        if not entry:
            return False
        return ((entry.get("max_intensity") or 0) >= NOTABLE_INTENSITY
                and (entry.get("coverage_pct") or 0) >= NOTABLE_COVERAGE_PCT)

    if notable(now):
        return f"ขณะนี้มี{now.get('level') or 'ฝนตก'}บนเส้นทาง"

    upcoming = next((s for s in soon if notable(s)), None)
    if upcoming:
        return (f"อีก {upcoming['lead_minutes']} นาที "
                f"คาดว่าจะมี{upcoming.get('level') or 'ฝนตกหนัก'}บนเส้นทาง")
    return None


async def raining_cameras() -> dict:
    """Traffic cameras that currently have rain falling on them.

    Upstream scans a few hundred and returns only the wet ones, so a short list
    means clear weather rather than a broken feed — which is why the scanned
    count is passed through instead of only the cameras.
    """
    if not enabled():
        return {"available": False, "reason": "ยังไม่ได้ตั้งค่า LONGDO_API_KEY",
                "cameras": [], "scanned": 0}

    async def fetch():
        async with _client() as client:
            response = await client.get(CAMERAS_URL,
                                        params={"key": settings.longdo_api_key})
            response.raise_for_status()
            return response.json()

    try:
        payload = await _cached("cameras", settings.rain_cache_sec, fetch)
    except Exception as exc:
        detail = describe_failure(exc)
        logger.warning("ดึงรายการกล้องที่ฝนตกไม่สำเร็จ: %s", detail)
        return {"available": False,
                "reason": f"ดึงข้อมูลกล้องไม่สำเร็จ — {detail}",
                "cameras": [], "scanned": 0}

    cameras = []
    for entry in (payload or {}).get("cameras") or []:
        lat, lng = entry.get("lat"), entry.get("lon")
        if lat is None or lng is None:
            continue
        cameras.append({
            "id": entry.get("camid"),
            "name": entry.get("title"),
            "lat": lat, "lng": lng,
            "province": entry.get("province"),
            "agency": entry.get("organization"),
            "stream_url": entry.get("hls_url"),
            "rain_level": (entry.get("rain") or {}).get("description"),
            "rain_intensity": (entry.get("rain") or {}).get("intensity"),
        })

    return {
        "available": True,
        "reason": None,
        "cameras": cameras,
        "scanned": (payload or {}).get("scanned") or 0,
        "last_updated": (payload or {}).get("last_updated"),
        "stale": bool((payload or {}).get("stale")),
    }


async def radar_tile(z: int, x: int, y: int) -> tuple[bytes, str] | None:
    """One radar tile, fetched with our key so the page never sees it."""
    if not enabled():
        return None

    async def fetch():
        async with _client() as client:
            response = await client.get(
                RADAR_TILE.format(z=z, x=x, y=y),
                params={"key": settings.longdo_api_key},
            )
            response.raise_for_status()
            return (response.content,
                    response.headers.get("content-type", "image/png"))

    try:
        return await _cached(f"tile:{z}/{x}/{y}", settings.rain_cache_sec, fetch)
    except Exception:
        logger.info("ดึงไทล์เรดาร์ %s/%s/%s ไม่สำเร็จ", z, x, y)
        return None
