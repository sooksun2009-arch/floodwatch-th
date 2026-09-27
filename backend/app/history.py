"""Recent water level history for one gauge, and what direction it is moving.

A single reading answers "how high is it", which is not the question a driver
has. "+0.82 m, critical" reads like a warning to turn around, and is the same
number whether the water has been falling all afternoon or rose 20 cm in the
last hour. The direction is the part that decides a trip.

Source is the national gauge API's graph endpoint, which serves hourly readings
for the last few days. Two of its quirks are load-bearing here:

  * Omitting station_type makes the upstream panic with a 500, so it is always
    sent, never inferred.
  * Roughly a third of the points come back null, including the most recent
    hours, because a station that has not reported yet still occupies its slot.
    Every calculation below skips them; averaging over them, or taking the last
    slot as "now", produces a confident and wrong answer.

Bangkok's own canal gauges are not available here. Their site refuses
connections from outside Thailand, so the container cannot reach it at all.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from .config import settings
from .stations import BANGKOK_TZ, _parse_dt

logger = logging.getLogger("floodwatch.history")

GRAPH_URL = "/api/v1/thaiwater30/public/waterlevel_graph"

# Below this, an apparent move is gauge noise rather than water going anywhere.
STEADY_THRESHOLD_M = 0.03

# How far back to look when deciding the direction. Long enough that one odd
# reading cannot flip the verdict, short enough to describe now rather than
# yesterday.
TREND_WINDOW_HOURS = 6


@dataclass(frozen=True)
class Point:
    at: datetime
    value: float


@dataclass(frozen=True)
class Trend:
    direction: str           # rising | falling | steady
    change_m: float          # over the window actually measured
    hours: float             # the window actually measured, not the one asked for
    label: str               # ready to show, in Thai


_TREND_TH = {
    "rising": "กำลังขึ้น",
    "falling": "กำลังลง",
    "steady": "ทรงตัว",
}


def _summarize(points: list[Point]) -> Trend | None:
    """Compare the newest reading with the closest one about a window ago.

    Deliberately not a fit over every point: a gauge that was flat for two days
    and started climbing an hour ago is rising, and a line fitted through the
    flat part would call that steady.
    """
    if len(points) < 2:
        return None

    newest = points[-1]
    target = newest.at - timedelta(hours=TREND_WINDOW_HOURS)
    # The newest reading that is at least a full window old, falling back to the
    # oldest we have when the series is shorter than that.
    #
    # Not "whichever reading sits closest to the target": these series have
    # hours-long gaps where the gauge reported nothing, and with a gap straddling
    # the target, nearest flips between a one-hour window and a twelve-hour one
    # on a margin of minutes. The window would then change meaning between two
    # refreshes of the same station while the water did nothing unusual.
    older = [p for p in points[:-1] if p.at <= target]
    earlier = older[-1] if older else points[0]

    hours = (newest.at - earlier.at).total_seconds() / 3600
    if hours <= 0:
        return None

    change = newest.value - earlier.value
    if abs(change) < STEADY_THRESHOLD_M:
        direction = "steady"
    else:
        direction = "rising" if change > 0 else "falling"

    if direction == "steady":
        label = f"ทรงตัวในช่วง {hours:.0f} ชม. ที่ผ่านมา"
    else:
        # Centimetres up to a metre, then metres. A gauge that jumped seven
        # metres while it was offline reads as "621 ซม." otherwise, which is a
        # number people have to stop and convert before it means anything.
        size = (f"{abs(change):.2f} ม." if abs(change) >= 1
                else f"{abs(change) * 100:.0f} ซม.")
        label = f"{_TREND_TH[direction]} {size} ใน {hours:.0f} ชม."

    return Trend(direction=direction, change_m=round(change, 3),
                 hours=round(hours, 1), label=label)


# Readings arrive hourly, so re-fetching more often than that only costs the
# upstream. Keyed by (external_id, days); holds the parsed points and when they
# were fetched.
_cache: dict[tuple[str, int], tuple[float, list[Point]]] = {}
_cache_lock = asyncio.Lock()
CACHE_TTL_SEC = 600


async def fetch_history(external_id: str, days: int = 2) -> list[Point]:
    """Hourly readings for one gauge, newest last, nulls dropped."""
    key = (str(external_id), days)
    now = time.monotonic()

    async with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SEC:
            return hit[1]

    end = datetime.now(BANGKOK_TZ).date()
    start = end - timedelta(days=days)
    params = {
        "station_id": str(external_id),
        # Required. Leaving it out returns a 500 from inside their handler.
        "station_type": "tele_waterlevel",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    async with httpx.AsyncClient(
        timeout=settings.station_timeout_sec,
        headers={"User-Agent": settings.http_user_agent},
    ) as client:
        response = await client.get(
            settings.thaiwater_base_url.rstrip("/") + GRAPH_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    # On a rejected request the upstream keeps HTTP 200 and puts the error
    # message in `data` as a plain string — {"result":"NO","data":"422: ..."} —
    # so the shape has to be checked, not assumed.
    data = (payload or {}).get("data")
    rows = data.get("graph_data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        logger.info("ต้นทางไม่ได้ส่งข้อมูลย้อนหลังมา (station %s): %.120s",
                    external_id, payload)
        rows = []
    points: list[Point] = []
    for row in rows:
        value = row.get("value")
        at = _parse_dt(row.get("datetime"))
        if value is None or at is None:
            continue
        try:
            points.append(Point(at=at, value=float(value)))
        except (TypeError, ValueError):
            continue

    points.sort(key=lambda p: p.at)

    async with _cache_lock:
        _cache[key] = (now, points)
    return points


async def station_history(external_id: str, days: int = 2) -> dict:
    """History plus its trend, shaped for the API. Never raises for the caller."""
    try:
        points = await fetch_history(external_id, days=days)
    except Exception:
        logger.exception("ดึงข้อมูลย้อนหลังไม่สำเร็จ (station %s)", external_id)
        return {"available": False,
                "reason": "ดึงข้อมูลย้อนหลังจากต้นทางไม่สำเร็จ",
                "points": [], "trend": None}

    if not points:
        return {"available": False,
                "reason": "ต้นทางยังไม่มีข้อมูลย้อนหลังของสถานีนี้",
                "points": [], "trend": None}

    trend = _summarize(points)
    return {
        "available": True,
        "reason": None,
        "points": [{"at": p.at.isoformat(), "value": p.value} for p in points],
        "trend": None if trend is None else {
            "direction": trend.direction,
            "change_m": trend.change_m,
            "hours": trend.hours,
            "label": trend.label,
        },
    }
