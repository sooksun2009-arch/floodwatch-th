"""Areas, stats, and image upload."""
import io
import logging
import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import area_overview, faceblur, floodroads, storage
from ..config import settings
from ..database import get_db
from ..deps import client_ip, enforce_limit, get_current_user_optional
from ..models import (
    Area, Camera, FloodReport, LEVEL_RANK, ReportStatus, User, utcnow,
)
from ..schemas import AreaOut, ProvinceStat, SummaryOut, TimelinePoint, UploadOut
from ..services import expire_stale_reports, since_cutoff, worst_level

logger = logging.getLogger("floodwatch")

router = APIRouter(prefix="/api", tags=["misc"])


# ---------------------------------------------------------------- areas

@router.get("/areas/provinces", response_model=list[AreaOut])
def provinces(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Area).where(Area.kind == "province").order_by(Area.name_th)
    ).scalars().all()
    return [AreaOut.model_validate(a) for a in rows]


@router.get("/areas/districts", response_model=list[AreaOut])
def districts(province_id: int | None = None, db: Session = Depends(get_db)):
    query = select(Area).where(Area.kind == "district")
    if province_id:
        query = query.where(Area.parent_id == province_id)
    rows = db.execute(query.order_by(Area.name_th)).scalars().all()
    return [AreaOut.model_validate(a) for a in rows]


# ---------------------------------------------------------------- stats

@router.get("/stats/summary", response_model=SummaryOut)
def summary(db: Session = Depends(get_db)):
    expire_stale_reports(db)
    approved = FloodReport.status == ReportStatus.approved.value

    by_level_rows = db.execute(
        select(FloodReport.level, func.count(FloodReport.id))
        .where(approved).group_by(FloodReport.level)
    ).all()

    return SummaryOut(
        active_reports=sum(n for _, n in by_level_rows),
        by_level={lv: n for lv, n in by_level_rows},
        pending_moderation=db.execute(
            select(func.count(FloodReport.id))
            .where(FloodReport.status == ReportStatus.pending.value)
        ).scalar() or 0,
        provinces_affected=db.execute(
            select(func.count(func.distinct(FloodReport.province_id))).where(approved)
        ).scalar() or 0,
        cameras_total=db.execute(select(func.count(Camera.id))).scalar() or 0,
        cameras_active=db.execute(
            select(func.count(Camera.id)).where(Camera.is_active.is_(True))
        ).scalar() or 0,
        reports_last_24h=db.execute(
            select(func.count(FloodReport.id)).where(FloodReport.created_at >= since_cutoff(24))
        ).scalar() or 0,
        updated_at=utcnow(),
    )


@router.get("/stats/by-province", response_model=list[ProvinceStat])
def by_province(db: Session = Depends(get_db), limit: int = Query(default=20, ge=1, le=100)):
    expire_stale_reports(db)
    rows = db.execute(
        select(FloodReport.province_id, Area.name_th, FloodReport.level, FloodReport.passable)
        .join(Area, Area.id == FloodReport.province_id, isouter=True)
        .where(FloodReport.status == ReportStatus.approved.value)
    ).all()

    grouped: dict[tuple[int | None, str], dict] = {}
    for province_id, name, level, passable in rows:
        key = (province_id, name or "ไม่ระบุจังหวัด")
        bucket = grouped.setdefault(key, {"levels": [], "impassable": 0})
        bucket["levels"].append(level)
        if level in ("severe", "closed") or passable is False:
            bucket["impassable"] += 1

    stats = [
        ProvinceStat(province_id=key[0], province_name=key[1], total=len(value["levels"]),
                     worst_level=worst_level(value["levels"]), impassable=value["impassable"])
        for key, value in grouped.items()
    ]
    stats.sort(key=lambda s: (-LEVEL_RANK.get(s.worst_level or "normal", 0), -s.total))
    return stats[:limit]


@router.get("/stats/provinces-overview", response_model=dict)
async def provinces_overview(db: Session = Depends(get_db)):
    """Every province's status in one go, centroids included, so the browser
    can pick its own province without sending its position here."""
    return await area_overview.overview(db)


_roads_gz: dict = {"key": None, "body": None}


@router.get("/flood-roads")
async def flood_roads(request: Request):
    """Flooded road segments for the map layer (Floodboard, CC BY 4.0).

    Served from our shared cache rather than letting every browser call
    Floodboard directly: one fetch every few minutes, whatever the traffic.
    About 1.5 MB as JSON, so it is gzipped here -- once per fetch, not per
    request -- rather than turning on compression for the whole server,
    which would spend a small instance's CPU recompressing map tiles.
    """
    import gzip
    import json

    from fastapi.responses import JSONResponse

    segs = await floodroads.segments()
    if segs is None:
        return JSONResponse({"type": "FeatureCollection", "features": [],
                             "attribution": floodroads.ATTRIBUTION, "unavailable": True})
    key = (floodroads.status()["fetched_at"], len(segs))
    if _roads_gz["key"] != key:
        raw = json.dumps(floodroads.as_geojson(segs), ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        _roads_gz.update(key=key, raw=raw, body=gzip.compress(raw, 6))
    headers = {"Cache-Control": "public, max-age=120", "Vary": "Accept-Encoding"}
    if "gzip" in (request.headers.get("accept-encoding") or ""):
        return Response(_roads_gz["body"], media_type="application/json",
                        headers={**headers, "Content-Encoding": "gzip"})
    return Response(_roads_gz["raw"], media_type="application/json", headers=headers)


@router.get("/stats/timeline", response_model=list[TimelinePoint])
def timeline(db: Session = Depends(get_db), hours: int = Query(default=48, ge=6, le=720)):
    """Reports per hour — shows whether a situation is building or receding."""
    rows = db.execute(
        select(FloodReport.created_at)
        .where(FloodReport.created_at >= since_cutoff(hours))
    ).scalars().all()

    buckets: dict[str, int] = {}
    now = utcnow()
    for i in range(hours, -1, -1):
        stamp = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
        buckets[stamp] = 0
    for created in rows:
        stamp = created.strftime("%Y-%m-%dT%H:00")
        if stamp in buckets:
            buckets[stamp] += 1
    return [TimelinePoint(bucket=k, total=v) for k, v in buckets.items()]


# ---------------------------------------------------------------- upload

@router.post("/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload_photo(request: Request, file: UploadFile = File(...),
                       user: User | None = Depends(get_current_user_optional)):
    """Accept a flood photo.

    The bytes are decoded and re-encoded with Pillow rather than stored as
    received. That validates the file really is an image, drops EXIF (which
    carries the photographer's exact GPS and device), and caps the dimensions.
    """
    key = f"upload:user:{user.id}" if user else f"upload:ip:{client_ip(request)}"
    enforce_limit(key, 30 if user else 10)

    limit_bytes = settings.max_upload_mb * 1024 * 1024
    raw = await file.read(limit_bytes + 1)
    if len(raw) > limit_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"ไฟล์ใหญ่เกิน {settings.max_upload_mb} MB")
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ไฟล์ว่าง")

    try:
        image = Image.open(io.BytesIO(raw))
        image.verify()                      # structural check; consumes the stream
        image = Image.open(io.BytesIO(raw))  # reopen for real work
        image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "ไฟล์นี้ไม่ใช่รูปภาพที่อ่านได้") from exc

    image.thumbnail((settings.max_image_px, settings.max_image_px))

    # Faces of passers-by, blurred before anything is written. About a second
    # of CPU, so off the event loop. None means the check could not run: the
    # photo is still accepted -- refusing flood photos during a flood over a
    # missing library would be the wrong trade -- and a moderator sees every
    # photo before it counts for much anyway.
    from starlette.concurrency import run_in_threadpool

    image, faces = await run_in_threadpool(faceblur.blur_faces, image)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82, optimize=True)
    payload = buffer.getvalue()

    name = f"{utcnow():%Y%m%d}-{uuid.uuid4().hex[:12]}.jpg"
    try:
        url = storage.save_jpeg(payload, name)
    except Exception as exc:
        # Deliberately not falling back to local disk: that would look like a
        # success and then lose the photo at the next deploy, which is the exact
        # failure the bucket was added to prevent.
        logger.exception("บันทึกรูปไม่สำเร็จ (%s)", storage.backend_name())
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "บันทึกรูปไม่สำเร็จ ลองใหม่อีกครั้ง "
                            "หรือส่งรายงานโดยไม่แนบรูปก็ได้") from exc

    return UploadOut(url=url, width=image.width, height=image.height,
                     bytes=len(payload), faces_blurred=faces)
