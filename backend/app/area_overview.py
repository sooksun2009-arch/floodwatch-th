"""One line per province: is anything happening there right now?

Feeds the "your area" card. The whole country is sent in one response on
purpose: the browser works out which province it is in by itself, from the
centroids included here, so the reader's position never has to reach the
server -- the same promise the rest of the app makes about routes.

Status is deliberately coarse. Three words someone can act on beat a score
they have to interpret:

  danger  -- a report says a car cannot get through (severe / closed /
             impassable). Only people on the road can say that: a river over
             its bank is a warning, not a closed road, and the first version
             called twelve provinces "danger" on gauges alone -- most of them
             without a single report.
  watch   -- any flood report, any gauge over its bank, or rain falling on a
             traffic camera right now
  normal  -- none of the above, from the sources we have
"""
import logging
import time

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import rain
from .models import Area, Camera, FloodReport, LEVEL_RANK, ReportStatus, WaterStation
from .services import expire_stale_reports, worst_level
from .stations import stale_cutoff

logger = logging.getLogger("floodwatch")

CACHE_SEC = 90
_cache: dict = {"at": 0.0, "value": None}

DANGER_LEVELS = ("severe", "closed")


def norm(name: str | None) -> str:
    """Province names arrive as "จังหวัดระยอง", "จ.ระยอง", "ระยอง " or "กทม."."""
    text = (name or "").strip().replace(" ", "")
    for prefix in ("จังหวัด", "จ."):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return {"กทม.": "กรุงเทพมหานคร", "กทม": "กรุงเทพมหานคร",
            "กรุงเทพฯ": "กรุงเทพมหานคร", "กรุงเทพ": "กรุงเทพมหานคร"}.get(text, text)


def status_of(row: dict) -> str:
    if row["worst_level"] in DANGER_LEVELS or row["impassable"] > 0:
        return "danger"
    if row["reports"] > 0 or row["overflowing"] > 0 or (row["raining"] or 0) > 0:
        return "watch"
    return "normal"


async def build(db: Session) -> dict:
    expire_stale_reports(db)
    provinces = db.execute(select(Area).where(Area.kind == "province")).scalars().all()
    rows = {
        norm(a.name_th): {
            "id": a.id, "name_th": a.name_th, "name_en": a.name_en,
            "lat": a.lat, "lng": a.lng,
            "reports": 0, "worst_level": None, "impassable": 0,
            "overflowing": 0, "stations": 0, "cameras": 0, "raining": None,
        }
        for a in provinces if a.lat is not None and a.lng is not None
    }
    by_id = {row["id"]: row for row in rows.values()}

    # Reports: "normal" means someone said the water has gone, so it is not a
    # flood to count.
    levels: dict[int, list[str]] = {}
    for province_id, level, passable in db.execute(
        select(FloodReport.province_id, FloodReport.level, FloodReport.passable)
        .where(FloodReport.status == ReportStatus.approved.value,
               FloodReport.level != "normal")
    ).all():
        row = by_id.get(province_id)
        if row is None:
            continue
        row["reports"] += 1
        levels.setdefault(province_id, []).append(level)
        if level in DANGER_LEVELS or passable is False:
            row["impassable"] += 1
    for province_id, found in levels.items():
        by_id[province_id]["worst_level"] = worst_level(found)

    # Gauges: only readings recent enough to be believed.
    for name, total, over in db.execute(
        select(WaterStation.province_name, func.count(WaterStation.id),
               func.sum(case((WaterStation.is_overflowing.is_(True), 1), else_=0)))
        .where(WaterStation.measured_at >= stale_cutoff())
        .group_by(WaterStation.province_name)
    ).all():
        row = rows.get(norm(name))
        if row is not None:
            row["stations"] += int(total or 0)
            row["overflowing"] += int(over or 0)

    for province_id, total in db.execute(
        select(Camera.province_id, func.count(Camera.id))
        .where(Camera.is_active.is_(True)).group_by(Camera.province_id)
    ).all():
        if province_id in by_id:
            by_id[province_id]["cameras"] = int(total or 0)

    # Rain on traffic cameras, when the Longdo key is set. Unknown stays None
    # rather than 0: "no rain" and "we cannot see" are different answers.
    rain_known = False
    try:
        wet = await rain.raining_cameras()
        if wet.get("available"):
            rain_known = True
            for row in rows.values():
                row["raining"] = 0
            for cam in wet.get("cameras") or []:
                row = rows.get(norm(cam.get("province")))
                if row is not None:
                    row["raining"] += 1
    except Exception:
        logger.exception("ดึงข้อมูลฝนรายจังหวัดไม่สำเร็จ")

    out = []
    for row in rows.values():
        row["status"] = status_of(row)
        out.append(row)
    rank = {"danger": 2, "watch": 1, "normal": 0}
    out.sort(key=lambda r: (-rank[r["status"]], -LEVEL_RANK.get(r["worst_level"] or "normal", 0),
                            -r["overflowing"], -r["reports"], r["name_th"]))
    return {"provinces": out, "rain_known": rain_known, "generated_at": int(time.time())}


async def overview(db: Session) -> dict:
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_SEC:
        return _cache["value"]
    value = await build(db)
    _cache.update(at=now, value=value)
    return value
