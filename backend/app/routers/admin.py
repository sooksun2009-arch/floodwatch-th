"""Moderation queue, user management, audit trail."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin, require_moderator
from ..models import (
    Area, AuditLog, ChatLog, FloodReport, ReportStatus, Role, User, utcnow,
)
from ..schemas import (
    AdminUserUpdateIn, ModerateIn, ReportListOut, ReportOut, UserOut,
)
from ..services import expire_stale_reports, log_action, report_to_out, resolve_province

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/queue", response_model=ReportListOut)
def moderation_queue(db: Session = Depends(get_db), _: User = Depends(require_moderator),
                     limit: int = Query(default=100, ge=1, le=500)):
    """Oldest pending reports first — during a flood, waiting is the whole cost."""
    # Two things need a person: reports never reviewed, and reports on the map
    # that enough people have since disputed. The second used to arrive here by
    # being un-approved, which also took it off the map; it now stays visible
    # and waits here instead.
    waiting = or_(FloodReport.status == ReportStatus.pending.value,
                  FloodReport.needs_review.is_(True))
    rows = db.execute(
        select(FloodReport).options(joinedload(FloodReport.province))
        .where(waiting)
        .order_by(FloodReport.created_at.asc()).limit(limit)
    ).unique().scalars().all()
    total = db.execute(select(func.count(FloodReport.id)).where(waiting)).scalar() or 0
    return ReportListOut(total=total, items=[report_to_out(r) for r in rows])


@router.post("/reports/{report_id}/moderate", response_model=ReportOut)
def moderate(report_id: str, payload: ModerateIn, db: Session = Depends(get_db),
             user: User = Depends(require_moderator)):
    report = db.get(FloodReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบรายงานนี้")

    report.status = payload.status.value
    report.moderated_by = user.id
    report.moderated_at = utcnow()
    report.moderation_note = payload.note
    # A person has now decided, whichever way; it should leave the queue.
    report.needs_review = False
    if payload.level is not None:
        report.level = payload.level.value
    if payload.source is not None:
        report.source = payload.source.value

    if payload.status == ReportStatus.approved:
        # Approving an old queued item should not immediately expire it.
        report.expires_at = FloodReport.default_expiry()
        if report.province_id is None:
            province = resolve_province(db, report.lat, report.lng)
            report.province_id = province.id if province else None

    log_action(db, user, f"moderate_{payload.status.value}", "report", report.id, payload.note)
    db.commit()
    db.refresh(report)
    return report_to_out(report)


@router.post("/reports/bulk-moderate", response_model=list[ReportOut])
def bulk_moderate(report_ids: list[str], payload: ModerateIn, db: Session = Depends(get_db),
                  user: User = Depends(require_moderator)):
    """Clear a backlog in one action — common when a storm generates a burst."""
    if not report_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ต้องระบุรายงานอย่างน้อย 1 รายการ")
    if len(report_ids) > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ทำได้ครั้งละไม่เกิน 200 รายการ")

    rows = db.execute(
        select(FloodReport).options(joinedload(FloodReport.province))
        .where(FloodReport.id.in_(report_ids))
    ).unique().scalars().all()

    for report in rows:
        report.status = payload.status.value
        report.moderated_by = user.id
        report.moderated_at = utcnow()
        report.moderation_note = payload.note
        if payload.status == ReportStatus.approved:
            report.expires_at = FloodReport.default_expiry()

    log_action(db, user, f"bulk_moderate_{payload.status.value}", "report", None,
               f"{len(rows)} รายการ")
    db.commit()
    return [report_to_out(r) for r in rows]


@router.post("/maintenance")
def maintenance(db: Session = Depends(get_db), user: User = Depends(require_moderator)):
    """Expire stale reports now. Safe to call from a cron."""
    expired = expire_stale_reports(db)
    log_action(db, user, "maintenance", "report", None, f"หมดอายุ {expired} รายการ")
    db.commit()
    return {"expired": expired, "ran_at": utcnow()}


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin),
               search: str | None = Query(default=None, max_length=80),
               limit: int = Query(default=100, ge=1, le=500)):
    query = select(User)
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(User.username.ilike(needle) | User.display_name.ilike(needle))
    rows = db.execute(query.order_by(User.created_at.desc()).limit(limit)).scalars().all()
    return [UserOut.model_validate(u) for u in rows]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, payload: AdminUserUpdateIn, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบผู้ใช้นี้")

    data = payload.model_dump(exclude_unset=True)

    # Guard against an admin locking every admin out of the system.
    if target.id == actor.id and (data.get("role") not in (None, Role.admin)
                                  or data.get("is_active") is False):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "ไม่สามารถลดสิทธิ์หรือระงับบัญชีของตัวเองได้")
    if data.get("role") is not None and target.role == Role.admin.value \
            and data["role"] != Role.admin:
        remaining = db.execute(
            select(func.count(User.id))
            .where(User.role == Role.admin.value, User.is_active.is_(True), User.id != target.id)
        ).scalar() or 0
        if remaining == 0:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "ต้องมีผู้ดูแลระบบที่ใช้งานได้เหลืออยู่อย่างน้อย 1 บัญชี")

    if data.get("role") is not None:
        target.role = data["role"].value
    if "is_active" in data:
        target.is_active = data["is_active"]
    if "org" in data:
        target.org = data["org"]

    log_action(db, actor, "update_user", "user", target.id, str(data))
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)


@router.get("/audit", response_model=list[dict])
def audit(db: Session = Depends(get_db), _: User = Depends(require_admin),
          limit: int = Query(default=100, ge=1, le=500)):
    rows = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    ).scalars().all()
    return [{
        "id": r.id, "actor_name": r.actor_name, "action": r.action, "entity": r.entity,
        "entity_id": r.entity_id, "detail": r.detail, "created_at": r.created_at,
    } for r in rows]


@router.get("/chat-logs", response_model=list[dict])
def chat_logs(db: Session = Depends(get_db), _: User = Depends(require_admin),
              limit: int = Query(default=100, ge=1, le=500)):
    """Unanswered questions are the roadmap: fallback intents show what is missing."""
    rows = db.execute(
        select(ChatLog).order_by(ChatLog.created_at.desc()).limit(limit)
    ).scalars().all()
    return [{
        "id": r.id, "question": r.question, "intent": r.intent,
        "matched_place": r.matched_place, "engine": r.engine, "created_at": r.created_at,
    } for r in rows]


@router.post("/areas/districts", response_model=dict, status_code=status.HTTP_201_CREATED)
def add_district(name_th: str, province_id: int, lat: float | None = None,
                 lng: float | None = None, db: Session = Depends(get_db),
                 user: User = Depends(require_moderator)):
    """Teach the gazetteer a new district or locality the chatbot should recognise."""
    province = db.get(Area, province_id)
    if province is None or province.kind != "province":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบจังหวัดนี้")

    existing = db.execute(
        select(Area).where(Area.kind == "district", Area.name_th == name_th.strip(),
                           Area.parent_id == province_id)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "มีพื้นที่ชื่อนี้ในจังหวัดนี้แล้ว")

    area = Area(kind="district", name_th=name_th.strip(), parent_id=province_id,
                lat=lat if lat is not None else province.lat,
                lng=lng if lng is not None else province.lng)
    db.add(area)
    log_action(db, user, "add_district", "area", None, f"{name_th} / {province.name_th}")
    db.commit()
    db.refresh(area)
    return {"id": area.id, "name_th": area.name_th, "parent_id": area.parent_id}
