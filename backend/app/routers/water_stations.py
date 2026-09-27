"""Canal/river gauge readings: public reads, moderator-triggered sync."""
from datetime import timezone

import hmac

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bma_stations import ingest as ingest_bma
from ..config import settings
from ..database import get_db
from ..history import station_history
from ..deps import require_moderator
from ..geo import bbox_around, parse_bbox
from ..models import STATION_SITUATION_TH, User, WaterStation
from ..schemas import WaterStationOut
from ..services import log_action, station_to_out as to_out
from ..stations import stale_cutoff, sync_all

router = APIRouter(prefix="/api/stations", tags=["water-stations"])


@router.get("", response_model=list[WaterStationOut])
def list_stations(
    db: Session = Depends(get_db),
    bbox: str | None = Query(default=None, description="min_lat,min_lng,max_lat,max_lng"),
    near: str | None = Query(default=None, description="lat,lng[,radius_km]"),
    province: str | None = Query(default=None, max_length=128),
    overflowing_only: bool = False,
    min_situation: int | None = Query(
        default=None, ge=1, le=5,
        description="กรองตามระดับสถานการณ์ขั้นต่ำ (4 = เฝ้าระวังขึ้นไป, 5 = วิกฤติ)"),
    include_stale: bool = True,
    limit: int = Query(default=1000, ge=1, le=2000),
):
    query = select(WaterStation)
    origin = None

    if near:
        parts = [p.strip() for p in near.split(",")]
        if len(parts) not in (2, 3):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "near ต้องเป็น lat,lng หรือ lat,lng,radius_km")
        try:
            lat, lng = float(parts[0]), float(parts[1])
            radius = float(parts[2]) if len(parts) == 3 else 15.0
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "near มีค่าที่ไม่ใช่ตัวเลข") from exc
        origin = (lat, lng)
        min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius)
        query = query.where(WaterStation.lat.between(min_lat, max_lat),
                            WaterStation.lng.between(min_lng, max_lng))
    elif bbox:
        try:
            min_lat, min_lng, max_lat, max_lng = parse_bbox(bbox)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        query = query.where(WaterStation.lat.between(min_lat, max_lat),
                            WaterStation.lng.between(min_lng, max_lng))

    if province:
        query = query.where(WaterStation.province_name == province.strip())
    if min_situation is not None:
        # Overflowing counts as worth showing even when the source gave no
        # situation level, which is common outside the กทม. network.
        query = query.where(
            (WaterStation.situation_level >= min_situation)
            | (WaterStation.is_overflowing.is_(True))
        )
    elif overflowing_only:
        query = query.where(WaterStation.is_overflowing.is_(True))
    if not include_stale:
        query = query.where(WaterStation.measured_at >= stale_cutoff())

    rows = db.execute(query.limit(limit)).scalars().all()
    out = [to_out(station, origin) for station in rows]

    if origin:
        radius = float(near.split(",")[2]) if len(near.split(",")) == 3 else 15.0
        out = [s for s in out if (s.distance_km or 0) <= radius]
        out.sort(key=lambda s: s.distance_km or 0)
    else:
        # Worst first: overflowing, then by how far over the bank.
        out.sort(key=lambda s: (not s.is_overflowing, -(s.diff_from_bank or -99)))
    return out


@router.get("/summary", response_model=dict)
def summary(db: Session = Depends(get_db)):
    rows = db.execute(select(WaterStation)).scalars().all()
    cutoff = stale_cutoff()

    def fresh(station: WaterStation) -> bool:
        measured = station.measured_at
        if measured is None:
            return False
        if measured.tzinfo is None:
            measured = measured.replace(tzinfo=timezone.utc)
        return measured >= cutoff

    by_level: dict[str, int] = {}
    for station in rows:
        label = STATION_SITUATION_TH.get(station.situation_level or 0, "ไม่ระบุ")
        by_level[label] = by_level.get(label, 0) + 1

    latest = max((s.synced_at for s in rows), default=None)
    return {
        "total": len(rows),
        "overflowing": sum(1 for s in rows if s.is_overflowing),
        "fresh": sum(1 for s in rows if fresh(s)),
        "stale": sum(1 for s in rows if not fresh(s)),
        "by_situation": by_level,
        "last_synced_at": latest,
    }


@router.get("/{station_id}/history", response_model=dict)
async def history(station_id: str, db: Session = Depends(get_db),
                  days: int = Query(default=2, ge=1, le=4)):
    """Recent readings for one gauge, and which way the water is moving.

    Fetched when someone opens a station rather than kept in sync for all of
    them: 800 gauges polled on a timer would be 800 requests an hour at the
    upstream for readings almost nobody looks at.
    """
    station = db.get(WaterStation, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบสถานีนี้")

    if station.source != "thaiwater":
        # Bangkok's own gauges publish history on a site that refuses
        # connections from outside Thailand, so say so plainly instead of
        # showing an empty chart that looks like the water is not moving.
        return {"station_id": station.id, "name": station.name,
                "source": station.source, "available": False,
                "reason": "แหล่งข้อมูลนี้ยังไม่เปิดให้ดึงข้อมูลย้อนหลัง",
                "points": [], "trend": None}

    result = await station_history(station.external_id, days=days)
    return {"station_id": station.id, "name": station.name,
            "source": station.source, **result}


@router.post("/bma/ingest", response_model=dict)
def ingest_relay(
    payload: dict = Body(...),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Accept Bangkok gauge readings pushed in by a relay.

    The drainage site drops connections from outside Thailand, so this
    deployment cannot fetch them itself — something that can reach it posts
    the page here.

    Closed unless INGEST_TOKEN is set. It writes to the map, so it is not
    something to leave open by default on a deployment that never uses it.
    """
    if not settings.ingest_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "ช่องรับข้อมูลปิดอยู่ (ยังไม่ได้ตั้ง INGEST_TOKEN)")

    supplied = authorization.removeprefix("Bearer ").strip()
    # compare_digest, not ==: string comparison returns early on the first
    # wrong byte, which leaks the token a character at a time to anyone
    # willing to time the responses.
    if not hmac.compare_digest(supplied, settings.ingest_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "โทเคนไม่ถูกต้อง")

    summary_html = payload.get("summary_html")
    if not isinstance(summary_html, str) or not summary_html.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ต้องส่ง summary_html")

    coords = payload.get("coords")
    if coords is not None and not isinstance(coords, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "coords ต้องเป็น object")

    try:
        return ingest_bma(db, summary_html, coords)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/sync", response_model=dict)
async def trigger_sync(db: Session = Depends(get_db), user: User = Depends(require_moderator)):
    """Pull the latest readings now. Also suitable for a cron to hit."""
    results = await sync_all(db)
    detail = " · ".join(
        f"{name}: ใหม่ {r.get('created', 0)} อัปเดต {r.get('updated', 0)}"
        + ("" if r.get("ok") else f" (ล้มเหลว: {r.get('error')})")
        for name, r in results.items()
    )
    log_action(db, user, "sync_stations", "station", None, detail)
    db.commit()

    if not any(r.get("ok") for r in results.values()):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"ซิงก์ข้อมูลไม่สำเร็จทุกแหล่ง: {detail}")
    return results
