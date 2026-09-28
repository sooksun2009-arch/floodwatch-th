"""Rain radar tiles and wet-camera list, proxied so the key stays server-side."""
from fastapi import APIRouter, HTTPException, Path, Response, status

from .. import rain

router = APIRouter(prefix="/api/rain", tags=["rain"])


@router.get("/status", response_model=dict)
def status_():
    """Whether rain features are configured, and why each one last failed.

    "Configured" is not "working" — a key can be present and still be refused
    for a given endpoint, which is what happened on the first deploy: radar
    tiles served fine while every other call failed, and the only record was a
    log line unreachable from outside the container.
    """
    return {"enabled": rain.enabled(), "last_failure": rain.LAST_FAILURE}


@router.get("/diagnose", response_model=dict)
async def diagnose():
    """What this key can actually reach, endpoint by endpoint.

    Reports status codes and the upstream's own words with the key removed.
    Exists because "the key works" turned out to be true and false at the same
    time: radar tiles and cameras served fine while the polygon and forecast
    calls were refused outright.
    """
    return await rain.probe_all()


@router.get("/cameras", response_model=dict)
async def cameras():
    """Traffic cameras with rain falling on them right now.

    Upstream scans a few hundred and returns only the wet ones, so the scanned
    count comes through too — otherwise an empty list on a clear day is
    indistinguishable from a broken feed.
    """
    return await rain.raining_cameras()


@router.get("/radar/{z}/{x}/{y}.png")
async def radar(
    z: int = Path(ge=0, le=20),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
):
    """One radar tile.

    Proxied rather than letting the page fetch it directly: the key would
    otherwise be readable by anyone who opens the network tab, and going
    through here puts every visitor behind one cache instead of spending a
    request each.
    """
    # A tile index outside its zoom level cannot exist, and forwarding it only
    # spends a call to be told so.
    limit = 1 << z
    if x >= limit or y >= limit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไทล์ไม่ถูกต้อง")

    tile = await rain.radar_tile(z, x, y)
    if tile is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "ยังไม่มีข้อมูลเรดาร์ฝน")

    content, content_type = tile
    return Response(
        content=content,
        media_type=content_type,
        # Matches the cache this app keeps, so a browser does not ask again
        # for a picture that cannot have changed yet.
        headers={"Cache-Control": f"public, max-age={rain.settings.rain_cache_sec}"},
    )
