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


def enabled() -> bool:
    return bool(settings.gistda_api_key)


def budget() -> Budget:
    global _tile_budget
    if _tile_budget is None:
        _tile_budget = Budget(settings.gistda_tiles_per_min,
                              settings.gistda_tiles_per_day)
    return _tile_budget


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
