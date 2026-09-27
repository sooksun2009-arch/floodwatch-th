"""Sync canal/river gauge readings from the National Hydroinformatics Data Center.

Why this layer exists at all: user reports and agency lists are people telling
us what they saw, and both go stale. These are instruments, they report every
ten minutes, and they cover the whole country. A canal at 0.5 m over its bank is
not the same fact as "water on the road" — so gauges get their own layer rather
than being turned into flood reports — but it is the earliest hard signal that
an area is about to be in trouble.

Source: https://api-v3.thaiwater.net (คลังข้อมูลน้ำแห่งชาติ / สสน.)
Attribution is stored per station in `agency` and shown in the UI.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .geo import in_thailand
from .models import WaterStation, utcnow

logger = logging.getLogger("floodwatch.stations")

WATERLEVEL_URL = "/api/v1/thaiwater30/public/waterlevel_load"

# The upstream reports Thai local time (UTC+7) without a timezone marker.
BANGKOK_TZ = timezone(timedelta(hours=7))

# Largest believable height above/below a bank, in metres. Real channels that
# matter for road flooding sit well inside this; anything beyond it is a
# mis-configured station rather than a catastrophe.
MAX_CREDIBLE_BANK_DIFF_M = 20.0


def _th(value) -> str | None:
    """Upstream text fields are {"th": ..., "en": ...} or a plain string."""
    if isinstance(value, dict):
        return value.get("th") or value.get("en")
    return value if isinstance(value, str) else None


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=BANGKOK_TZ)
        except ValueError:
            continue
    return None


async def fetch_waterlevel() -> list[dict]:
    url = settings.thaiwater_base_url.rstrip("/") + WATERLEVEL_URL
    async with httpx.AsyncClient(timeout=settings.station_timeout_sec) as client:
        resp = await client.get(url, headers={"User-Agent": settings.http_user_agent,
                                              "Accept": "application/json"})
    resp.raise_for_status()
    payload = resp.json()
    block = payload.get("waterlevel_data") or {}
    if block.get("result") not in (None, "OK"):
        raise ValueError(f"ต้นทางตอบ result={block.get('result')}")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError("รูปแบบข้อมูลจากต้นทางไม่ตรงกับที่คาดไว้")
    return rows


def normalise(row: dict) -> dict | None:
    """One upstream record -> the fields we store, or None if unusable."""
    station = row.get("station") or {}
    geocode = row.get("geocode") or {}

    lat = _as_float(station.get("tele_station_lat"))
    lng = _as_float(station.get("tele_station_long"))
    if lat is None or lng is None or not in_thailand(lat, lng):
        return None

    external_id = station.get("id") or station.get("tele_station_oldcode") or row.get("id")
    if external_id is None:
        return None

    name = _th(station.get("tele_station_name")) or f"สถานี {external_id}"

    level = _as_float(row.get("waterlevel_msl"))

    # min_bank is the only bank figure comparable with waterlevel_msl. Do not
    # be tempted to fall back to left_bank/right_bank: on real stations those
    # are expressed in a different datum and are often negative — at
    # ที่ว่าการอ.นครชัยศรี, min_bank is 1.5 while left_bank is -7.59, so mixing
    # them turns a 0.68 m overflow into 9.75 m.
    #
    # A min_bank of 0 means the bank was never surveyed, not "at sea level".
    # Upstream does not make that distinction and computes level - 0, which is
    # how a reservoir 331 m above sea level arrives labelled "ล้นตลิ่ง 331.70 ม.".
    bank = _as_float(station.get("min_bank"))
    if bank == 0:
        bank = None

    status_text = row.get("diff_wl_bank_text") or ""
    diff = _as_float(row.get("diff_wl_bank"))

    situation = row.get("situation_level")
    try:
        situation = int(situation) if situation is not None else None
    except (TypeError, ValueError):
        situation = None

    if bank is None:
        # No bank to compare against, so there is no honest "over by X" figure.
        # Every such station upstream also arrives with situation_level unset,
        # i.e. upstream has not classified it either.
        diff = None
        overflowing = False
        status_text = "ไม่มีข้อมูลระดับตลิ่ง"
    elif level is not None:
        # Compute the gap ourselves against the bank we accepted. Upstream's
        # own diff is derived from its bank value, so when that value is the
        # unset 0 the number is wrong by the station's entire elevation — and
        # on a partially surveyed station it is wrong while still looking
        # plausible. Where upstream's bank is sound, this agrees with it.
        diff = round(level - bank, 3)
        overflowing = diff > 0
    else:
        # No reading, only upstream's summary. Its sign lives in the text.
        overflowing = "ล้นตลิ่ง" in status_text
        if diff is not None and not overflowing:
            diff = -diff

    # Defence in depth, applied however the gap was arrived at: a channel does
    # not run tens of metres over its bank and remain a road-flooding story.
    # Keep the reading, stop asserting it is a flood.
    if diff is not None and abs(diff) > MAX_CREDIBLE_BANK_DIFF_M:
        overflowing = False
        status_text = f"{status_text} (ค่าผิดปกติ ไม่นำมาประเมิน)".strip()

    return {
        "external_id": str(external_id),
        "name": name,
        "lat": lat,
        "lng": lng,
        "province_name": _th(geocode.get("province_name")),
        "amphoe_name": _th(geocode.get("amphoe_name")),
        "agency": _th((row.get("agency") or {}).get("agency_shortname")),
        "basin_name": _th((row.get("basin") or {}).get("basin_name")),
        "water_level_msl": level,
        "bank_level": bank,
        "diff_from_bank": diff,
        "is_overflowing": bool(overflowing),
        "situation_level": situation,
        "status_text": (status_text or None),
        "measured_at": _parse_dt(row.get("waterlevel_datetime")),
    }


def upsert(db: Session, records: list[dict]) -> tuple[int, int]:
    """Insert new stations, update existing ones. Returns (created, updated)."""
    existing = {
        station.external_id: station
        for station in db.execute(
            select(WaterStation).where(WaterStation.source == "thaiwater")
        ).scalars()
    }

    created = updated = 0
    now = utcnow()
    for record in records:
        station = existing.get(record["external_id"])
        if station is None:
            station = WaterStation(source="thaiwater", **record, synced_at=now)
            db.add(station)
            created += 1
        else:
            for key, value in record.items():
                setattr(station, key, value)
            station.synced_at = now
            updated += 1

    db.commit()
    return created, updated


async def sync(db: Session) -> dict:
    """Fetch and store. Safe to run on a schedule; never raises to the caller."""
    try:
        rows = await fetch_waterlevel()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ซิงก์สถานีวัดระดับน้ำไม่สำเร็จ: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "created": 0, "updated": 0, "skipped": 0}

    records, skipped = [], 0
    for row in rows:
        record = normalise(row)
        if record is None:
            skipped += 1
        else:
            records.append(record)

    created, updated = upsert(db, records)
    logger.info("ซิงก์สถานี: ใหม่ %s อัปเดต %s ข้าม %s", created, updated, skipped)
    return {"ok": True, "created": created, "updated": updated, "skipped": skipped,
            "total": len(records), "synced_at": utcnow()}


async def sync_all(db: Session) -> dict:
    """Refresh every gauge source. One failing source must not stop the others."""
    from . import bma_stations

    results = {"thaiwater": await sync(db)}
    if settings.sync_bma_on_start:
        results["bma"] = await bma_stations.sync(db)
    return results


def stale_cutoff() -> datetime:
    """Readings older than this are shown greyed out rather than as current."""
    return utcnow() - timedelta(hours=settings.station_stale_hours)
