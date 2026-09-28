"""Satellite flood-extent tiles, proxied so the key stays server-side."""
from fastapi import APIRouter, HTTPException, Path, Response, status

from .. import flood_extent

router = APIRouter(prefix="/api/flood-extent", tags=["flood-extent"])


@router.get("/status", response_model=dict)
def status_():
    """Whether the layer is configured, what it last failed at, what it spent.

    "Configured" is not "working": the Longdo key was accepted for tiles and
    refused for two other endpoints on the same plan, and the only record of it
    was a log line unreachable from outside the container. This is that record,
    over HTTP.
    """
    return {
        "enabled": flood_extent.enabled(),
        "product": flood_extent.settings.gistda_product,
        "products": list(flood_extent.PRODUCTS),
        "max_zoom": flood_extent.settings.gistda_max_zoom,
        # So the page can tell people how old what they are looking at can be,
        # instead of leaving them to assume it is live.
        "cache_sec": flood_extent.settings.gistda_tile_cache_sec,
        "last_failure": flood_extent.LAST_FAILURE,
        "budget": flood_extent.budget().state(),
    }


@router.get("/diagnose", response_model=dict)
async def diagnose():
    """What this key can actually reach, endpoint by endpoint, key stripped."""
    return await flood_extent.probe_all()


@router.get("/{product}/{z}/{x}/{y}.png")
async def tile(
    product: str,
    z: int = Path(ge=0, le=20),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
):
    """One flood-extent tile."""
    # A tile index outside its own zoom level cannot exist, and forwarding it
    # only spends a call to be told so.
    limit = 1 << z
    if x >= limit or y >= limit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไทล์ไม่ถูกต้อง")

    chosen = (flood_extent.FREQ if product == flood_extent.FREQ
              else flood_extent.product_or_default(product))
    result = await flood_extent.tile(chosen, z, x, y)

    if result is None:
        # Transparent, not an error. This layer is context someone switched on;
        # the flood map underneath is why the page exists, and a failed tile
        # turning into a red banner across it is the decoration shouting over
        # the point. The reason is still recorded and /status reports it.
        return Response(
            content=flood_extent.BLANK_TILE,
            media_type="image/png",
            # Short, so a tile missing because of a blip comes back on the next
            # pan rather than being remembered as empty for six hours.
            headers={"Cache-Control": "public, max-age=60"},
        )

    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control":
                 f"public, max-age={flood_extent.settings.gistda_tile_cache_sec}"},
    )
