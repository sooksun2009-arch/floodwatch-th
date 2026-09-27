import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import require_admin, require_moderator
from ..geo import bbox_around, haversine_km, parse_bbox
from ..models import Camera, User, utcnow
from ..schemas import CameraIn, CameraOut, CameraUpdateIn
from ..services import camera_to_out, log_action, nearby_flood_level

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("", response_model=list[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    bbox: str | None = Query(default=None),
    province_id: int | None = None,
    near: str | None = Query(default=None, description="lat,lng[,radius_km]"),
    search: str | None = Query(default=None, max_length=120),
    include_inactive: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
):
    query = select(Camera).options(joinedload(Camera.province))
    if not include_inactive:
        query = query.where(Camera.is_active.is_(True))
    if province_id:
        query = query.where(Camera.province_id == province_id)
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(or_(Camera.name.ilike(needle), Camera.district.ilike(needle),
                                Camera.owner_org.ilike(needle)))

    origin = None
    if near:
        parts = [p.strip() for p in near.split(",")]
        if len(parts) not in (2, 3):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "near ต้องเป็น lat,lng หรือ lat,lng,radius_km")
        try:
            lat, lng = float(parts[0]), float(parts[1])
            radius = float(parts[2]) if len(parts) == 3 else 10.0
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "near มีค่าที่ไม่ใช่ตัวเลข") from exc
        origin = (lat, lng)
        min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius)
        query = query.where(Camera.lat.between(min_lat, max_lat),
                            Camera.lng.between(min_lng, max_lng))
    elif bbox:
        try:
            min_lat, min_lng, max_lat, max_lng = parse_bbox(bbox)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        query = query.where(Camera.lat.between(min_lat, max_lat),
                            Camera.lng.between(min_lng, max_lng))

    rows = db.execute(query.limit(limit)).unique().scalars().all()

    out = [camera_to_out(c, origin, nearby_flood_level(db, c.lat, c.lng)) for c in rows]
    if origin:
        radius = float(near.split(",")[2]) if len(near.split(",")) == 3 else 10.0
        out = [c for c in out if (c.distance_km or 0) <= radius]
        out.sort(key=lambda c: c.distance_km or 0)
    return out


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.execute(
        select(Camera).options(joinedload(Camera.province)).where(Camera.id == camera_id)
    ).unique().scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    return camera_to_out(camera, None, nearby_flood_level(db, camera.lat, camera.lng))


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(payload: CameraIn, db: Session = Depends(get_db),
                  user: User = Depends(require_moderator)):
    camera = Camera(**payload.model_dump())
    camera.stream_type = payload.stream_type.value
    db.add(camera)
    log_action(db, user, "create_camera", "camera", camera.id, payload.name)
    db.commit()
    db.refresh(camera)
    return camera_to_out(camera)


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: str, payload: CameraUpdateIn, db: Session = Depends(get_db),
                  user: User = Depends(require_moderator)):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")

    data = payload.model_dump(exclude_unset=True)
    if data.get("stream_type") is not None:
        data["stream_type"] = data["stream_type"].value
    for key, value in data.items():
        setattr(camera, key, value)
    camera.updated_at = utcnow()

    log_action(db, user, "update_camera", "camera", camera.id, str(list(data)))
    db.commit()
    db.refresh(camera)
    return camera_to_out(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    log_action(db, user, "delete_camera", "camera", camera.id, camera.name)
    db.delete(camera)
    db.commit()
    return None


def _health_from_frame(frame_at) -> str:
    """online only when the picture is recent; otherwise stale."""
    if frame_at is None:
        return "online"  # endpoint answered but gave no timestamp to judge by
    age_min = (utcnow() - frame_at).total_seconds() / 60
    return "online" if age_min <= settings.camera_stale_minutes else "stale"


_SNAPSHOT_CACHE: dict[str, tuple[float, bytes, str]] = {}
_ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")


@router.get("/{camera_id}/snapshot")
async def snapshot(camera_id: str, db: Session = Depends(get_db)):
    """Server-side proxy for a camera still frame.

    Thai agency CCTV endpoints commonly send no CORS headers and check Referer,
    so a browser cannot load them directly from our origin. Fetching server-side
    fixes both, and a short cache keeps one popular camera from turning N viewers
    into N upstream requests.
    """
    import time

    from fastapi import Response

    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบกล้องนี้")
    if camera.stream_type not in ("snapshot", "mjpeg"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "กล้องนี้ไม่ใช่ประเภทภาพนิ่ง ให้เล่นสตรีมที่ฝั่งเบราว์เซอร์")

    # Cache for a fraction of the camera's own refresh interval.
    ttl = max(2.0, camera.refresh_sec * 0.6)
    cached = _SNAPSHOT_CACHE.get(camera.id)
    now = time.monotonic()
    if cached and now - cached[0] < ttl:
        return Response(content=cached[1], media_type=cached[2],
                        headers={"Cache-Control": f"public, max-age={int(ttl)}"})

    headers = {"User-Agent": settings.http_user_agent}
    if camera.source_page:
        # Many endpoints serve the image only when the Referer looks like their
        # own viewer page; source_page is exactly that page.
        headers["Referer"] = camera.source_page

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(camera.stream_url, headers=headers)
    except httpx.HTTPError as exc:
        camera.health, camera.last_checked = "offline", utcnow()
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"ดึงภาพจากกล้องไม่สำเร็จ: {type(exc).__name__}") from exc

    if resp.status_code >= 400:
        camera.health, camera.last_checked = "offline", utcnow()
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"กล้องตอบกลับรหัส {resp.status_code}")

    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"ปลายทางไม่ได้ส่งรูปภาพกลับมา (content-type: {content_type or 'ไม่ระบุ'})")
    if content_type not in _ALLOWED_IMAGE_TYPES:
        content_type = "image/jpeg"

    body = resp.content
    if len(body) > 12 * 1024 * 1024:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ภาพจากกล้องมีขนาดใหญ่เกินไป")

    _SNAPSHOT_CACHE[camera.id] = (now, body, content_type)
    if len(_SNAPSHOT_CACHE) > 500:
        for key in sorted(_SNAPSHOT_CACHE, key=lambda k: _SNAPSHOT_CACHE[k][0])[:100]:
            _SNAPSHOT_CACHE.pop(key, None)

    # Last-Modified tells us when the frame was actually taken. Many Thai
    # agency endpoints keep serving a frozen image with HTTP 200, so trusting
    # the status code alone would show a month-old picture as "live".
    frame_at = None
    last_modified = resp.headers.get("last-modified")
    if last_modified:
        try:
            frame_at = parsedate_to_datetime(last_modified)
            if frame_at.tzinfo is None:
                frame_at = frame_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            frame_at = None

    camera.last_frame_at = frame_at
    camera.last_checked = utcnow()
    camera.health = _health_from_frame(frame_at)
    db.commit()

    headers = {"Cache-Control": f"public, max-age={int(ttl)}"}
    if frame_at is not None:
        age_min = int((utcnow() - frame_at).total_seconds() // 60)
        headers["X-Frame-Age-Minutes"] = str(max(0, age_min))
    return Response(content=body, media_type=content_type, headers=headers)


async def _probe(camera: Camera) -> str:
    """Is this stream reachable?

    A HEAD request is tried first because snapshot endpoints are often large
    JPEGs; some servers reject HEAD, so fall back to a ranged GET. An iframe or
    YouTube camera is not probed — those are third-party pages whose status says
    nothing about the camera.
    """
    if camera.stream_type in ("iframe", "youtube"):
        return "unknown"
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.head(camera.stream_url,
                                     headers={"User-Agent": settings.http_user_agent})
            if resp.status_code >= 400 or resp.status_code == 405:
                resp = await client.get(camera.stream_url,
                                        headers={"User-Agent": settings.http_user_agent,
                                                 "Range": "bytes=0-2047"})
        if resp.status_code >= 400:
            return "offline"
        last_modified = resp.headers.get("last-modified")
        if last_modified:
            try:
                frame_at = parsedate_to_datetime(last_modified)
                if frame_at.tzinfo is None:
                    frame_at = frame_at.replace(tzinfo=timezone.utc)
                return _health_from_frame(frame_at)
            except (TypeError, ValueError):
                pass
        return "online"
    except httpx.HTTPError:
        return "offline"


@router.post("/health-check", response_model=list[CameraOut])
async def health_check(db: Session = Depends(get_db), user: User = Depends(require_moderator),
                       limit: int = Query(default=50, ge=1, le=200)):
    """Probe registered streams and record the result.

    Run from the admin screen, or on a schedule with a cron hitting this route.
    """
    cameras = db.execute(
        select(Camera).where(Camera.is_active.is_(True))
        .order_by(Camera.last_checked.is_(None).desc(), Camera.last_checked.asc())
        .limit(limit)
    ).scalars().all()

    results = await asyncio.gather(*(_probe(c) for c in cameras), return_exceptions=True)
    for camera, result in zip(cameras, results):
        camera.health = result if isinstance(result, str) else "offline"
        camera.last_checked = utcnow()

    offline = sum(1 for c in cameras if c.health == "offline")
    stale = sum(1 for c in cameras if c.health == "stale")
    log_action(db, user, "camera_health_check", "camera", None,
               f"ตรวจ {len(cameras)} ตัว ใช้ไม่ได้ {offline} ตัว ภาพค้าง {stale} ตัว")
    db.commit()
    return [camera_to_out(c) for c in cameras]
