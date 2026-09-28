"""The A-to-B endpoint. This is the feature the app exists for."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, enforce_limit, get_current_user_optional
from ..geocode import resolve_place
from ..models import User
from ..rain import route_rain
from ..routing import check_route
from ..schemas import GeocodeOut, LatLng, RouteCheckIn, RouteCheckOut
from ..services import expire_stale_reports

logger = logging.getLogger("floodwatch")

router = APIRouter(prefix="/api/route", tags=["route"])


async def _resolve_endpoint(db: Session, point: LatLng | None, text: str | None,
                            role: str) -> tuple[tuple[float, float], str | None]:
    """Coordinates win over text; text is geocoded. Raises 400 when neither works."""
    if point is not None:
        return (point.lat, point.lng), None
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ต้องระบุ{role}")

    found = await resolve_place(db, text)
    if found is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"หาตำแหน่งของ{role} \"{text}\" ไม่พบ ลองใส่ชื่อเขตหรือจังหวัดต่อท้าย "
            f"หรือปักหมุดบนแผนที่แทน",
        )
    lat, lng, label, _source = found
    return (lat, lng), label


@router.post("/check", response_model=RouteCheckOut)
async def check(payload: RouteCheckIn, request: Request, db: Session = Depends(get_db),
                user: User | None = Depends(get_current_user_optional)):
    """Check a route for flooding.

    Rate limited because each call may hit an external routing service and,
    for text endpoints, a geocoder.
    """
    key = f"route:user:{user.id}" if user else f"route:ip:{client_ip(request)}"
    enforce_limit(key, 120 if user else 40)

    if not payload.has_origin() or not payload.has_destination():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ต้องระบุทั้งต้นทางและปลายทาง")

    expire_stale_reports(db)

    origin, origin_label = await _resolve_endpoint(
        db, payload.origin, payload.origin_text, "ต้นทาง")
    dest, dest_label = await _resolve_endpoint(
        db, payload.destination, payload.destination_text, "ปลายทาง")

    try:
        result = await check_route(
            db, origin, dest,
            corridor_m=payload.corridor_m,
            camera_corridor_m=payload.camera_corridor_m,
            alternatives=payload.alternatives,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    result["origin_label"] = origin_label or payload.origin_text
    result["destination_label"] = dest_label or payload.destination_text

    # Asked for the route people will actually drive — the first one — not all
    # of them, because each alternative would multiply the upstream calls for
    # weather that is nearly the same across a few kilometres.
    best = (result.get("routes") or [None])[0]
    if best and best.get("path"):
        try:
            result["rain"] = await route_rain(best["path"])
        except Exception:
            logger.exception("ดึงข้อมูลฝนบนเส้นทางไม่สำเร็จ")
            result["rain"] = None

    return RouteCheckOut.model_validate(result)


@router.get("/geocode", response_model=GeocodeOut)
async def geocode(q: str = Query(min_length=2, max_length=200), request: Request = None,
                  db: Session = Depends(get_db),
                  user: User | None = Depends(get_current_user_optional)):
    """Place-name lookup for the origin/destination autocomplete boxes."""
    key = f"geocode:user:{user.id}" if user else f"geocode:ip:{client_ip(request)}"
    enforce_limit(key, 200 if user else 60)

    found = await resolve_place(db, q)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"หาตำแหน่งของ \"{q}\" ไม่พบ")
    lat, lng, label, source = found
    return GeocodeOut(lat=lat, lng=lng, label=label, source=source)
