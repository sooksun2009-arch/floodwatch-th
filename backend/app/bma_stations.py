"""Canal gauges published by the Bangkok drainage department.

Why a second source: ThaiWater covers the whole country but has only three
stations inside Bangkok. สำนักการระบายน้ำ กทม. runs ~300 gauges on the canals
that actually flood the city's roads, each with its own warning and critical
thresholds. For a Bangkok driver this is the dense network that matters.

There is no JSON API, so this reads the department's own pages:

  /water/Summary                -> every station's current reading, one request
  /water/StationDetail?id=<id>  -> that station's coordinates and thresholds

Readings come from the summary on every sync. Detail pages are fetched only for
stations whose coordinates we do not have yet, a bounded number per run, because
coordinates and thresholds change almost never and 300 page loads per cycle
would be rude.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .geo import in_thailand
from .models import WaterStation, utcnow

logger = logging.getLogger("floodwatch.bma")

BANGKOK_TZ = timezone(timedelta(hours=7))
SOURCE = "bma"

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
STATION_ID_RE = re.compile(r"StationDetail\?id=(\d+)")
COORD_RE = re.compile(r"(1[2-5]\.\d{4,})\s*,\s*(9\d\.\d{4,}|10\d\.\d{4,})")

# สถานะที่หน้าเว็บรายงาน -> ระดับสถานการณ์ที่เราใช้ทั้งระบบ (เทียบเคียง thaiwater)
STATUS_TO_SITUATION = {
    "ปกติ": 3,
    "เฝ้าระวัง": 4,
    "เตือนภัย": 4,
    "วิกฤติ": 5,
    "วิกฤต": 5,
    "ล้นตลิ่ง": 5,
}
# A gauge reporting "ขัดข้อง" is broken, not calm. It must never read as normal.
BROKEN_STATUSES = {"ขัดข้อง", "ไม่มีข้อมูล", "-"}


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


def _as_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_thai_datetime(text: str) -> datetime | None:
    """"27/09/2569 15:20" -> aware datetime. The year is Buddhist Era."""
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})", text or "")
    if not match:
        return None
    day, month, year, hour, minute = (int(g) for g in match.groups())
    if year > 2400:
        year -= 543  # พ.ศ. -> ค.ศ.
    try:
        return datetime(year, month, day, hour, minute, tzinfo=BANGKOK_TZ)
    except ValueError:
        return None


def parse_summary(html: str) -> list[dict]:
    """Rows of the summary table -> one dict per station."""
    stations = []
    for row in ROW_RE.findall(html):
        station_id = STATION_ID_RE.search(row)
        if not station_id:
            continue
        cells = [_text(c) for c in CELL_RE.findall(row)]
        if len(cells) < 6:
            continue

        district, canal, name, when, status, inner = cells[:6]
        stations.append({
            "external_id": station_id.group(1),
            "district": district or None,
            "canal": canal or None,
            "name": name or f"สถานี {station_id.group(1)}",
            "measured_at": _parse_thai_datetime(when),
            "status": status or None,
            "water_level_msl": _as_float(inner),
        })
    return stations


def parse_detail(html: str) -> dict:
    """Coordinates and bank/alarm levels from one station's page."""
    out: dict = {}

    coord = COORD_RE.search(html)
    if coord:
        lat, lng = float(coord.group(1)), float(coord.group(2))
        if in_thailand(lat, lng):
            out["lat"], out["lng"] = lat, lng

    def labelled(label: str) -> float | None:
        # The page renders each threshold as an input whose title/name carries
        # the Thai label; the value attribute may sit on either side of it.
        for pattern in (
            rf'{label}"[^>]*?value="(-?[\d.]+)"',
            rf'value="(-?[\d.]+)"[^>]*?{label}"',
        ):
            match = re.search(pattern, html)
            if match:
                return _as_float(match.group(1))
        return None

    banks = [labelled("ตลิ่งซ้าย"), labelled("ตลิ่งขวา")]
    banks = [b for b in banks if b is not None]
    if banks:
        # The lower bank is where water leaves the channel first.
        out["bank_level"] = min(banks)

    for key, label in (("warn_level", "เตือนภัย"), ("critical_level", "วิกฤติ")):
        value = labelled(label)
        if value is not None:
            out[key] = value

    return out


def to_record(summary: dict, detail: dict) -> dict | None:
    """Combine a summary row with its cached detail into a WaterStation row."""
    lat, lng = detail.get("lat"), detail.get("lng")
    if lat is None or lng is None:
        return None  # without a position it cannot go on a map

    status = (summary.get("status") or "").strip()
    broken = status in BROKEN_STATUSES
    level = summary.get("water_level_msl")

    # A bank level of 0 means the survey value was never filled in, not that the
    # bank sits at sea level — the same trap as the national feed.
    bank = detail.get("bank_level")
    if bank == 0:
        bank = None

    # The published status decides whether this is a flood, not our arithmetic.
    # The department sets each gauge's thresholds from survey data we cannot
    # see, and 25 of ~300 stations read as "over the bank" by subtraction while
    # the department itself reports ปกติ. Trusting our own subtraction there
    # would put false red pins on a safety map.
    situation = None if broken else STATUS_TO_SITUATION.get(status)
    overflowing = (not broken) and status in ("วิกฤติ", "วิกฤต", "ล้นตลิ่ง")

    # The gap is still worth showing as supporting detail where both numbers
    # are real, but it never drives the verdict.
    diff = None
    if not broken and level is not None and bank is not None:
        diff = round(level - bank, 3)

    status_text = "สถานีขัดข้อง" if broken else (status or None)

    name = summary["name"]
    canal = summary.get("canal")
    if canal and canal not in name:
        name = f"{canal} — {name}"

    return {
        "external_id": summary["external_id"],
        "name": name[:255],
        "lat": lat,
        "lng": lng,
        "province_name": "กรุงเทพมหานคร",
        "amphoe_name": summary.get("district"),
        "agency": "สนน. กทม.",
        "basin_name": summary.get("canal"),
        "water_level_msl": None if broken else level,
        "bank_level": bank,
        "diff_from_bank": diff,
        "is_overflowing": bool(overflowing),
        "situation_level": situation,
        "status_text": status_text,
        "measured_at": summary.get("measured_at"),
    }


def ingest(db: Session, summary_html: str,
           coords: dict[str, dict] | None = None) -> dict:
    """Take readings a relay fetched on our behalf and store them.

    The Bangkok drainage site drops connections from outside Thailand, so the
    container cannot reach it at all — not refused, unreachable. Something that
    can reach it posts the page here instead.

    The relay stays a pipe: it sends the summary page exactly as it received
    it and this parses it, so the parsing stays in one place that is tested,
    and a change to the page never means editing a script in someone's Google
    account. Coordinates are the one exception. They live on a 876 KB page per
    station, which is not worth relaying three hundred times for two numbers
    that never change, so the relay extracts those itself and sends them once.
    """
    rows = parse_summary(summary_html)
    if not rows:
        raise ValueError("อ่านตารางสรุปของ กทม. ไม่ได้ — หน้าที่ส่งมาอาจไม่ใช่หน้า Summary")

    details: dict[str, dict] = {
        station.external_id: {"lat": station.lat, "lng": station.lng,
                              "bank_level": station.bank_level}
        for station in db.execute(
            select(WaterStation).where(WaterStation.source == SOURCE)
        ).scalars()
    }

    accepted = 0
    for station_id, value in (coords or {}).items():
        try:
            lat, lng = float(value["lat"]), float(value["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        # Same gate as our own fetch path: a station outside Thailand is a
        # parsing accident, not a station.
        if not in_thailand(lat, lng):
            continue
        entry = dict(details.get(str(station_id)) or {})
        entry["lat"], entry["lng"] = lat, lng
        for key in ("bank_level", "warn_level", "critical_level"):
            if value.get(key) is not None:
                entry[key] = _as_float(str(value[key]))
        details[str(station_id)] = entry
        accepted += 1

    result = persist(db, rows, details)
    result["coords_accepted"] = accepted
    # Which stations still have no position, so the relay knows what to fetch
    # next instead of walking all three hundred pages every run.
    result["need_coords"] = [
        r["external_id"] for r in rows if r["external_id"] not in details
    ][:50]
    logger.info("รับข้อมูล กทม. จากรีเลย์: %s แถว · พิกัดใหม่ %s · ยังขาดพิกัด %s",
                len(rows), accepted, len(result["need_coords"]))
    return result


def describe_connection_failure(exc: BaseException) -> str:
    """A failure string that names the cause instead of its category.

    httpx wraps the underlying socket error and often carries no message of its
    own, so the chain has to be walked to find the one that knows what actually
    happened.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        parts.append(f"{type(current).__name__}({text})" if text else type(current).__name__)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


# Waits between attempts, in seconds. Short, and only a few: this is someone
# else's public web page and it rate-limits, so a burst of retries is more
# likely to earn a block than to get an answer.
RETRY_DELAYS = (2.0, 5.0)


async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    """Fetch one page, retrying only failures that a retry could plausibly fix.

    The fetch has been failing from the deployed container while the same URL
    answers fine elsewhere, and the cause is not yet known. Retrying covers
    every transient version of that — a nameserver that did not answer in
    time, a connection dropped mid-handshake — without needing to know which
    one it is. An HTTP status is not retried: a 403 is a decision, and asking
    again immediately is how a decision becomes a longer one.
    """
    last: Exception | None = None
    for attempt, delay in enumerate((0.0,) + RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(url, headers={"User-Agent": settings.http_user_agent})
            resp.raise_for_status()
            if attempt:
                logger.info("ดึง %s สำเร็จในครั้งที่ %s", url, attempt + 1)
            return resp.text
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as exc:
            last = exc
            logger.info("ดึง %s ไม่สำเร็จ (ครั้งที่ %s): %s",
                        url, attempt + 1, describe_connection_failure(exc))
    raise last  # type: ignore[misc]


async def sync(db: Session) -> dict:
    """Refresh readings, filling in coordinates for stations we have not seen."""
    base = settings.bma_water_base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=settings.station_timeout_sec,
                                     follow_redirects=True) as client:
            summary_html = await _fetch(client, f"{base}/Summary")
            rows = parse_summary(summary_html)
            if not rows:
                raise ValueError("อ่านตารางสรุปของ กทม. ไม่ได้ — โครงสร้างหน้าเว็บอาจเปลี่ยน")

            existing = {
                station.external_id: station
                for station in db.execute(
                    select(WaterStation).where(WaterStation.source == SOURCE)
                ).scalars()
            }
            # Coordinates and thresholds are static, so keep what we already have.
            details: dict[str, dict] = {
                sid: {"lat": s.lat, "lng": s.lng, "bank_level": s.bank_level}
                for sid, s in existing.items()
            }

            missing = [r["external_id"] for r in rows if r["external_id"] not in details]
            budget = missing[: settings.bma_detail_per_sync]
            for station_id in budget:
                try:
                    detail_html = await _fetch(client, f"{base}/StationDetail?id={station_id}")
                    details[station_id] = parse_detail(detail_html)
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("ดึงรายละเอียดสถานี %s ไม่สำเร็จ: %s", station_id, exc)
                # Deliberate pacing: this is someone else's public web page.
                await asyncio.sleep(settings.bma_detail_delay_sec)

    except (httpx.HTTPError, ValueError) as exc:
        # Spell the failure out. The first version logged "ConnectError: " with
        # an empty message, which says only that something went wrong before
        # any HTTP happened — it cannot distinguish a name that would not
        # resolve from a refused connection from a handshake that timed out,
        # and those have completely different fixes. The site itself is
        # reachable from outside Thailand, so whatever stops this container is
        # worth naming precisely rather than guessing at.
        detail = describe_connection_failure(exc)
        logger.warning("ซิงก์สถานี กทม. ไม่สำเร็จ: %s", detail)
        return {"ok": False, "error": detail,
                "created": 0, "updated": 0, "pending_detail": 0}

    return persist(db, rows, details, missing=missing, fetched=budget)


def persist(db: Session, rows: list[dict], details: dict[str, dict], *,
            missing: list[str] | None = None,
            fetched: list[str] | None = None) -> dict:
    """Upsert parsed rows. Separate from fetching so the same, tested code
    handles readings we pulled ourselves and readings a relay handed us."""
    existing = {
        station.external_id: station
        for station in db.execute(
            select(WaterStation).where(WaterStation.source == SOURCE)
        ).scalars()
    }
    missing = missing if missing is not None else [
        r["external_id"] for r in rows if r["external_id"] not in details
    ]
    fetched = fetched or []

    created = updated = skipped = 0
    now = utcnow()
    for row in rows:
        detail = details.get(row["external_id"])
        if not detail:
            skipped += 1
            continue
        record = to_record(row, detail)
        if record is None:
            skipped += 1
            continue

        station = existing.get(record["external_id"])
        if station is None:
            db.add(WaterStation(source=SOURCE, **record, synced_at=now))
            created += 1
        else:
            for key, value in record.items():
                setattr(station, key, value)
            station.synced_at = now
            updated += 1

    db.commit()
    still_missing = max(0, len(missing) - len(fetched))
    logger.info("ซิงก์ กทม.: ใหม่ %s อัปเดต %s ยังไม่มีพิกัด %s", created, updated, still_missing)
    return {"ok": True, "created": created, "updated": updated, "skipped": skipped,
            "total": len(rows), "pending_detail": still_missing, "synced_at": now}
