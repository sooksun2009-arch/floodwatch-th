"""Satellite flood extent, from GISTDA's Disaster Platform open API.

This answers a question none of the other sources can. A user report needs
someone to have driven past and stopped to type. A canal gauge measures one
point on one waterway. Radar shows rain, which is not flooding. This is the
water itself, mapped from orbit across the whole country, including every
district where nobody has reported anything — which is most of them, most of
the time, and is exactly where the map is least useful today.

What it is not, and the app must keep saying so:

* It is an **area**, not a road. A polygon covering a sub-district does not
  mean its roads are impassable, and a raised road through flooded fields is
  ordinary in Thailand.
* It is **up to a day old**, and the multi-day products older still. Roads
  drain at wildly different rates, so yesterday's water is a reason to check,
  not a verdict.

So it lives on its own toggleable layer with its own caption, and nothing here
feeds the A-to-B verdict. That is the same rule the canal gauges live under and
it is in the project's working rules as number seven.

The key travels in an ``API-Key`` header — confirmed from the published
Swagger's own authorize dialog rather than guessed — and never leaves this
process: the page asks this app for tiles and this app asks GISTDA.
"""
import asyncio
import io
import logging

import httpx
from PIL import Image

from .config import settings
from .netbudget import Budget, Cache, QuotaExhausted, strip_secret

logger = logging.getLogger("floodwatch.flood_extent")

# The products the platform publishes. "freq" is the recurrent-flooding
# summary: not where water is now, but where it returns year after year.
PRODUCTS = ("1day", "3days", "7days", "30days")
FREQ = "flood-freq"

TILE_PATH = "/maps/flood/{product}/tms/{z}/{x}/{y}"
FREQ_TILE_PATH = "/maps/flood-freq/tms/{z}/{x}/{y}"
FEATURES_PATH = "/features/flood/{product}"


def _blank_png() -> bytes:
    """One transparent pixel, served when a tile is unavailable.

    Built rather than pasted as a base64 blob so it is obvious what it is.
    """
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


BLANK_TILE = _blank_png()

_cache = Cache()
_tile_budget: Budget | None = None
_feature_budget: Budget | None = None


def enabled() -> bool:
    return bool(settings.gistda_api_key)


def budget() -> Budget:
    global _tile_budget
    if _tile_budget is None:
        _tile_budget = Budget(settings.gistda_tiles_per_min,
                              settings.gistda_tiles_per_day)
    return _tile_budget


def feature_budget() -> Budget:
    """Separate from tiles, and small.

    One call downloads the whole country, so this is the expensive one and
    panning the map must not be able to spend it.
    """
    global _feature_budget
    if _feature_budget is None:
        _feature_budget = Budget(4, settings.gistda_features_per_day)
    return _feature_budget


# Why each kind of call last failed, reachable over HTTP. A log line inside a
# container is invisible from outside it, and that invisibility is what made
# guessing at the Bangkok gauges and at the Longdo plan feel reasonable twice.
LAST_FAILURE: dict[str, str] = {}


def describe_failure(exc: BaseException) -> str:
    """What GISTDA actually said, with our key taken back out."""
    if isinstance(exc, httpx.HTTPStatusError):
        body = (exc.response.text or "")[:200]
        detail = f"HTTP {exc.response.status_code}: {body}"
    else:
        detail = f"{type(exc).__name__}: {exc}"[:220]
    return " ".join(strip_secret(detail, settings.gistda_api_key).split())


def _remember_failure(kind: str, exc: BaseException) -> None:
    detail = describe_failure(exc)
    LAST_FAILURE[kind] = detail
    logger.warning("เรียก GISTDA %s ไม่สำเร็จ: %s", kind, detail)


def _remember_success(kind: str) -> None:
    """Clear the old failure, so a fault fixed hours ago stops reading as the
    current state. An uncleared one sent a diagnosis the wrong way already."""
    LAST_FAILURE.pop(kind, None)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.gistda_base_url.rstrip("/"),
        timeout=settings.gistda_timeout_sec,
        headers={"API-Key": settings.gistda_api_key,
                 "User-Agent": "FloodWatchTH/1.0 (+https://floodwatch-th.onrender.com)"},
        follow_redirects=True,
    )


def product_or_default(product: str | None) -> str:
    """Only the published products, so a typo in a URL cannot become a request.

    Anything unrecognised falls back to the configured default rather than
    raising: this feeds a map layer, and a bad tile URL should show no water,
    not break the page.
    """
    return product if product in PRODUCTS else settings.gistda_product


async def tile(product: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
    """One flood-extent tile, or None if it could not be had.

    None is not an error to pass on — see the router. The caller turns it into
    a transparent pixel, because this layer is context someone switched on and
    the flood map underneath is why the page exists.
    """
    if not enabled():
        return None
    if z > settings.gistda_max_zoom:
        # Refused here rather than upstream. Beyond this the picture does not
        # get sharper, and each level asks for four times as many tiles.
        return None

    path = (FREQ_TILE_PATH if product == FREQ else TILE_PATH).format(
        product=product, z=z, x=x, y=y)

    async def fetch():
        budget().spend("ไทล์ภาพน้ำท่วม")
        async with _client() as client:
            response = await client.get(path)
            response.raise_for_status()
            return (response.content,
                    response.headers.get("content-type", "image/png"))

    try:
        result = await _cache.get(
            f"tile:{product}:{z}/{x}/{y}", settings.gistda_tile_cache_sec, fetch)
        _remember_success("tile")
        return result
    except QuotaExhausted as exc:
        _remember_failure("tile", exc)
        return None
    except Exception as exc:
        _remember_failure("tile", exc)
        return None


# Probing every endpoint once, because a key can be accepted by one and refused
# by another on the same account. Assuming otherwise cost a round of wrong
# diagnosis on the Longdo key, where tiles and cameras worked while the polygon
# and forecast calls returned a flat 403.
PROBES: dict[str, str] = {
    "tile_7days": TILE_PATH.format(product="7days", z=9, x=402, y=228),
    "tile_1day": TILE_PATH.format(product="1day", z=9, x=402, y=228),
    "tile_freq": FREQ_TILE_PATH.format(z=9, x=402, y=228),
    "features_7days": FEATURES_PATH.format(product="7days"),
    "features_freq": "/features/flood-freq",
}


async def probe_all() -> dict:
    """Ask each endpoint once and report what it said, key stripped.

    Reachable at /api/flood-extent/diagnose so a wrong key can be told apart
    from an account without this dataset without shell access to the container.
    """
    if not enabled():
        return {"enabled": False, "results": {}}

    async def one(name: str) -> tuple[str, dict]:
        path = PROBES[name]
        try:
            async with _client() as client:
                response = await client.get(path, params={"limit": 1})
            body = strip_secret((response.text or "")[:120],
                                settings.gistda_api_key)
            return name, {
                "status": response.status_code,
                "ok": response.status_code == 200,
                "type": response.headers.get("content-type", ""),
                "bytes": len(response.content),
                # Binary bodies are noise in a diagnostic; a tile's size and
                # type already say whether it arrived.
                "body": "" if response.headers.get(
                    "content-type", "").startswith("image/") else body,
            }
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            return name, {"status": None, "ok": False,
                          "error": describe_failure(exc)}

    # Sequential on purpose. Five parallel requests against an unpublished
    # quota is how the last quota got emptied, and a diagnostic that damages
    # what it is diagnosing is worse than a slow one.
    results = {}
    for name in PROBES:
        key, value = await one(name)
        results[key] = value
        await asyncio.sleep(0.2)
    return {"enabled": True, "results": results}


# ------------------------------------------------------- polygons for routing

def _rings(geometry: dict) -> list[list]:
    """Outer rings only, from either a Polygon or a MultiPolygon.

    Holes are dropped on purpose: a dry island inside a flooded area is not
    worth the vertices when the whole outline is about to be rounded to a
    200-metre grid anyway.
    """
    kind = (geometry or {}).get("type")
    coords = (geometry or {}).get("coordinates") or []
    if kind == "Polygon":
        return [coords[0]] if coords else []
    if kind == "MultiPolygon":
        return [poly[0] for poly in coords if poly]
    return []


def _bounds(ring) -> tuple:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _overlaps(ring, bbox) -> bool:
    minx, miny, maxx, maxy = _bounds(ring)
    return not (maxx < bbox[0] or minx > bbox[2] or maxy < bbox[1] or miny > bbox[3])


def _coarsen(ring, grid: float) -> list:
    """Round an outline to a grid and drop points that collapse together.

    ORS refuses avoid_polygons it considers too intricate, and it refuses the
    whole request rather than the offending shape, which turns "steer around
    the water" into "no route at all". These outlines are coarse observations
    to begin with, and the corridor check downstream is what decides anything.
    """
    out = []
    for point in ring:
        snapped = [round(point[0] / grid) * grid, round(point[1] / grid) * grid]
        if not out or snapped != out[-1]:
            out.append(snapped)
    if len(out) < 3:
        return []
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else []


def point_in_ring(lng: float, lat: float, ring) -> bool:
    """Ray casting.

    Used to ask whether a route actually enters observed water rather than
    merely passing near its bounding box, which in the delta would be almost
    everywhere.
    """
    inside = False
    count = len(ring)
    for i in range(count):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % count][0], ring[(i + 1) % count][1]
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1
            if lng < crossing:
                inside = not inside
    return inside


async def all_rings(product: str | None = None) -> list:
    """Every observed flood outline in the country, cached for hours.

    The endpoint takes no parameters, so there is no narrower question to ask
    it: the whole set is fetched once and filtered here.
    """
    if not enabled():
        return []
    chosen = product_or_default(product)

    async def fetch():
        feature_budget().spend("ข้อมูลพื้นที่น้ำท่วม")
        # Try the largest page the feed will accept. It refuses without saying
        # what its ceiling is, so the only way to find it is to ask.
        wanted = [settings.gistda_features_limit] + [
            int(x) for x in settings.gistda_features_limit_fallbacks.split(",") if x.strip()
        ]
        async with _client() as client:
            response = None
            for limit in wanted:
                response = await client.get(
                    FEATURES_PATH.format(product=chosen), params={"limit": limit})
                if response.status_code != 400 or "limit" not in (response.text or ""):
                    break
                logger.info("GISTDA ปฏิเสธ limit=%s ลองค่าที่เล็กลง", limit)
            response.raise_for_status()
            size_mb = len(response.content) / 1_048_576
            if size_mb > settings.gistda_max_download_mb:
                # Refused rather than parsed. This runs on a small instance and
                # an unbounded download is the kind of improvement that takes
                # the flood map down.
                raise ValueError(
                    f"ข้อมูลใหญ่เกินเพดาน ({size_mb:.1f} MB เกิน "
                    f"{settings.gistda_max_download_mb} MB)")
            payload = response.json()
        # Coarsened here, as each outline is read, rather than kept at full
        # resolution and simplified later. These are thousands of shapes on a
        # small instance, and everything downstream -- the proximity check and
        # the avoid list -- works off the rounded version anyway.
        rings = []
        for feature in (payload or {}).get("features") or []:
            for ring in _rings(feature.get("geometry")):
                simple = _coarsen(ring, settings.gistda_avoid_grid_deg)
                if simple:
                    rings.append(simple)
        logger.info("โหลดพื้นที่น้ำท่วมจากดาวเทียม %.1f MB %d รูป", size_mb, len(rings))
        # A count that lands exactly on the limit means the feed stopped there,
        # not that the country did. Recorded rather than guessed at, because
        # the first version of this read ten outlines for all of Thailand and
        # looked exactly like a quiet week.
        features = len((payload or {}).get("features") or [])
        asked = int(str(response.request.url).split("limit=")[-1].split("&")[0] or 0) \
            if "limit=" in str(response.request.url) else settings.gistda_features_limit
        if features >= asked:
            LAST_FAILURE["features_truncated"] = (
                f"ได้มา {features} รายการ ซึ่งชนเพดานที่ขอไว้พอดี "
                f"— แปลว่าน่าจะมีมากกว่านี้ที่ยังไม่ได้ดึง")
        else:
            LAST_FAILURE.pop("features_truncated", None)
        return rings

    try:
        rings = await _cache.get(f"features:{chosen}",
                                 settings.gistda_features_cache_sec, fetch)
        _remember_success("features")
        return rings
    except Exception as exc:  # noqa: BLE001 - recorded, never raised at a map
        _remember_failure("features", exc)
        return []


async def avoid_near(bbox) -> dict | None:
    """Flood outlines overlapping bbox, coarsened, as a MultiPolygon for ORS.

    None means "nothing observed here", which is not the same as "this is
    fine": the satellite sees what it sees, and in the wet season a good deal
    of the country is under cloud.
    """
    rings = await all_rings()
    near = [r for r in rings if _overlaps(r, bbox)]
    if not near:
        return None

    def area(ring) -> float:
        minx, miny, maxx, maxy = _bounds(ring)
        return (maxx - minx) * (maxy - miny)

    # Biggest first, so that if the cap bites, the areas most likely to matter
    # are the ones that survive it.
    near.sort(key=area, reverse=True)

    # Already coarsened on the way in, so this only has to pick.
    out = [[ring] for ring in near[:settings.gistda_avoid_max_polygons]]
    return {"type": "MultiPolygon", "coordinates": out} if out else None


def cached_ring_count(product: str | None = None) -> int | None:
    """How many outlines are in hand, or None if none have been fetched yet.

    Reported by /status so that "no flooding on your route" can be told from
    "this never loaded". Reads the cache only -- asking it must never trigger
    a country-sized download.
    """
    entry = _cache._entries.get(f"features:{product_or_default(product)}")
    return len(entry.value) if entry else None


def path_near(path, rings, corridor_km: float | None = None) -> bool:
    """Whether a route runs within corridor_km of observed water.

    Not point-in-polygon. The published outlines are many small patches --
    tens of metres across -- and a route path is sampled far more coarsely
    than that, so asking whether a path point lands inside one answers "no"
    almost regardless of the truth. Distance to the patch is the question the
    data can actually answer.
    """
    if not rings or not path:
        return False
    km = settings.gistda_route_corridor_km if corridor_km is None else corridor_km
    # Degrees, at Thailand's latitudes. Longitude is narrower than latitude
    # here; using the latitude figure for both would search a wider east-west
    # band than intended, so each gets its own.
    pad_lat = km / 111.0
    pad_lng = km / 105.0

    boxes = [_bounds(r) for r in rings]
    for lat, lng in path:
        for minx, miny, maxx, maxy in boxes:
            if (minx - pad_lng <= lng <= maxx + pad_lng
                    and miny - pad_lat <= lat <= maxy + pad_lat):
                return True
    return False


def path_enters(path, rings) -> bool:
    """Strictly inside an outline. Kept for callers that want the narrow test;
    routing uses path_near, for the reasons written there."""
    for lat, lng in path:
        for ring in rings:
            if point_in_ring(lng, lat, ring):
                return True
    return False
