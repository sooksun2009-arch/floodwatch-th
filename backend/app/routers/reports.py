from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import storage
from ..config import settings
from ..database import get_db
from ..deps import client_ip, get_current_user, get_current_user_optional, rate_limit_reports
from ..geo import parse_bbox
from ..models import (
    FloodReport, LEVEL_RANK, ReportSource, ReportStatus, ReportVote, Role, User,
    level_from_depth, utcnow,
)
from ..schemas import (
    ReportIn, ReportListOut, ReportOut, ReportUpdateIn, VoteIn,
)
from ..services import (
    apply_vote_side_effects, auto_approval, expire_stale_reports, initial_status,
    log_action, promote_report, recount_votes, report_to_out, resolve_province,
    since_cutoff,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _base_query():
    return select(FloodReport).options(joinedload(FloodReport.province))


def _can_moderate(user: User | None) -> bool:
    return user is not None and user.role in (Role.moderator.value, Role.admin.value)


@router.get("", response_model=ReportListOut)
def list_reports(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    bbox: str | None = Query(default=None, description="min_lat,min_lng,max_lat,max_lng"),
    province_id: int | None = None,
    level: list[str] | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    since_hours: int = Query(default=0, ge=0, le=720),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=300, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Reports for the map. Defaults to currently-active, approved reports.

    Only moderators may request pending/rejected rows; an anonymous visitor
    asking for them silently gets the approved set instead of an error, so the
    map keeps working.
    """
    expire_stale_reports(db)

    query = _base_query()

    if status_filter and _can_moderate(user):
        wanted = [s.strip() for s in status_filter.split(",") if s.strip()]
        invalid = [s for s in wanted if s not in ReportStatus.__members__]
        if invalid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"สถานะไม่ถูกต้อง: {', '.join(invalid)}")
        query = query.where(FloodReport.status.in_(wanted))
    else:
        query = query.where(FloodReport.status == ReportStatus.approved.value)

    if bbox:
        try:
            min_lat, min_lng, max_lat, max_lng = parse_bbox(bbox)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        query = query.where(FloodReport.lat.between(min_lat, max_lat),
                            FloodReport.lng.between(min_lng, max_lng))

    if province_id:
        query = query.where(FloodReport.province_id == province_id)

    if level:
        levels = [lv for chunk in level for lv in chunk.split(",") if lv.strip()]
        unknown = [lv for lv in levels if lv not in LEVEL_RANK]
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"ระดับน้ำไม่ถูกต้อง: {', '.join(unknown)}")
        query = query.where(FloodReport.level.in_(levels))

    if since_hours:
        query = query.where(FloodReport.created_at >= since_cutoff(since_hours))

    if search:
        needle = f"%{search.strip()}%"
        query = query.where(or_(FloodReport.place.ilike(needle),
                                FloodReport.district.ilike(needle),
                                FloodReport.description.ilike(needle)))

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(
        query.order_by(FloodReport.created_at.desc()).limit(limit).offset(offset)
    ).unique().scalars().all()

    return ReportListOut(total=total, items=[report_to_out(r) for r in rows])


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db),
               user: User | None = Depends(get_current_user_optional)):
    report = db.execute(
        _base_query().where(FloodReport.id == report_id)
    ).unique().scalar_one_or_none()
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")
    if report.status != ReportStatus.approved.value and not _can_moderate(user):
        is_owner = user is not None and report.reporter_id == user.id
        if not is_owner:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")
    return report_to_out(report)


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(payload: ReportIn, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(rate_limit_reports)):
    try:
        payload.check_thailand()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if payload.level is None and payload.depth_cm is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ต้องระบุระดับน้ำ หรือความลึกเป็น ซม.")

    # photo_url is just a string on the payload, and it ends up in an <img> on
    # the moderation screen. Only a URL our own upload endpoint minted may go in.
    if payload.photo_url and not storage.is_managed_url(payload.photo_url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "รูปต้องอัปโหลดผ่านระบบนี้เท่านั้น")

    level = payload.level.value if payload.level else level_from_depth(payload.depth_cm)

    # เจ้าหน้าที่/ผู้ดูแล แจ้งเข้ามาถือเป็นข้อมูลทางการ ขึ้นแผนที่ทันที
    is_official = user is not None and user.role in (Role.moderator.value, Role.admin.value)
    source = ReportSource.official.value if is_official else ReportSource.user.value

    # Placed after is_official is known, not before it exists.
    if settings.require_photo and not is_official and not payload.photo_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ต้องแนบรูปถ่ายจุดที่น้ำท่วมด้วย — รูปช่วยให้คนอื่นตัดสินใจได้จริง "
            "และทำให้รายงานขึ้นแผนที่ทันทีโดยไม่ต้องรอตรวจ")

    province_id = payload.province_id
    if province_id is None:
        province = resolve_province(db, payload.lat, payload.lng)
        province_id = province.id if province else None

    ip = client_ip(request)
    report_status = initial_status(source, is_official)
    auto_note: str | None = None
    also_promote: list[FloodReport] = []

    if report_status == ReportStatus.pending.value:
        # Would have waited for a moderator. See whether the evidence clears it
        # on its own — a photo, or a second witness at the same spot.
        approved, auto_note, also_promote = auto_approval(
            db, payload.lat, payload.lng,
            photo_url=payload.photo_url,
            reporter_id=user.id if user else None,
            reporter_ip=ip,
        )
        if approved:
            report_status = ReportStatus.approved.value

    report = FloodReport(
        lat=payload.lat, lng=payload.lng,
        province_id=province_id,
        district=payload.district,
        place=payload.place,
        level=level,
        depth_cm=payload.depth_cm,
        passable=payload.passable,
        description=payload.description,
        photo_url=payload.photo_url,
        source=source,
        status=report_status,
        moderation_note=auto_note,
        reporter_id=user.id if user else None,
        reporter_name=(user.display_name or user.username) if user else payload.reporter_name,
        reporter_ip=ip,
        expires_at=FloodReport.default_expiry(),
    )
    db.add(report)
    log_action(db, user, "create_report", "report", report.id,
               f"{level} @ {payload.place or ''} ({payload.lat:.5f},{payload.lng:.5f})")
    if auto_note:
        log_action(db, None, "auto_approve_report", "report", report.id, auto_note)

    # The new witness corroborates the earlier reports as much as they clear it,
    # so anything still queued at the same spot goes up with it.
    for other in also_promote:
        promote_report(other, "ขึ้นแผนที่อัตโนมัติ: มีผู้แจ้งจุดเดียวกันเพิ่มอีกราย")
        log_action(db, None, "auto_approve_report", "report", other.id,
                   "ได้รับการยืนยันจากรายงานใหม่ในจุดเดียวกัน")

    db.commit()
    db.refresh(report)
    return report_to_out(report)


@router.patch("/{report_id}", response_model=ReportOut)
def update_report(report_id: str, payload: ReportUpdateIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Edit a report. The reporter may correct their own; moderators may edit any."""
    report = db.get(FloodReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")
    if not _can_moderate(user) and report.reporter_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "แก้ไขได้เฉพาะรายงานของตนเอง")

    data = payload.model_dump(exclude_unset=True)
    if data.get("photo_url") and not storage.is_managed_url(data["photo_url"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "รูปต้องอัปโหลดผ่านระบบนี้เท่านั้น")
    if "level" in data and data["level"] is not None:
        data["level"] = data["level"].value
    elif data.get("depth_cm") is not None:
        data["level"] = level_from_depth(data["depth_cm"])

    for key, value in data.items():
        setattr(report, key, value)
    report.updated_at = utcnow()

    log_action(db, user, "update_report", "report", report.id, str(data))
    db.commit()
    db.refresh(report)
    return report_to_out(report)


@router.post("/{report_id}/vote", response_model=ReportOut)
def vote(report_id: str, payload: VoteIn, request: Request, db: Session = Depends(get_db),
         user: User | None = Depends(get_current_user_optional)):
    """Confirm or dispute a report. One vote per identity, changeable."""
    report = db.get(FloodReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")
    if report.status == ReportStatus.rejected.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "รายงานนี้ถูกปฏิเสธแล้ว")

    voter_key = f"user:{user.id}" if user else f"ip:{client_ip(request)}"
    if user is None:
        from ..deps import enforce_limit
        enforce_limit(f"vote:{client_ip(request)}", 40)

    if report.reporter_id and user and report.reporter_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "ไม่สามารถยืนยันรายงานของตัวเองได้")

    existing = db.execute(
        select(ReportVote).where(ReportVote.report_id == report_id,
                                 ReportVote.voter_key == voter_key)
    ).scalar_one_or_none()

    if existing:
        existing.vote = payload.vote
        existing.level = payload.level.value if payload.level else None
        existing.created_at = utcnow()
    else:
        db.add(ReportVote(report_id=report_id, voter_key=voter_key, vote=payload.vote,
                          level=payload.level.value if payload.level else None))

    # The session runs with autoflush off, so the insert/update above has to be
    # flushed before the recount SELECT can see it.
    db.flush()
    recount_votes(db, report)
    apply_vote_side_effects(report)
    db.commit()
    db.refresh(report)
    return report_to_out(report)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_report(report_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Withdraw a report.

    Nothing is hard-deleted: the row flips to rejected so the audit trail and
    any votes attached to it survive.
    """
    report = db.get(FloodReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")
    if not _can_moderate(user) and report.reporter_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ถอนได้เฉพาะรายงานของตนเอง")

    report.status = ReportStatus.rejected.value
    report.moderation_note = "ผู้แจ้งถอนรายงานเอง" if report.reporter_id == user.id else "ถอนโดยผู้ดูแล"
    report.moderated_by = user.id
    report.moderated_at = utcnow()
    log_action(db, user, "withdraw_report", "report", report.id)
    db.commit()
    return None


@router.get("/mine/list", response_model=ReportListOut)
def my_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user),
               limit: int = Query(default=100, ge=1, le=500)):
    rows = db.execute(
        _base_query().where(FloodReport.reporter_id == user.id)
        .order_by(FloodReport.created_at.desc()).limit(limit)
    ).unique().scalars().all()
    return ReportListOut(total=len(rows), items=[report_to_out(r) for r in rows])
