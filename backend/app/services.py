"""Domain logic shared by routers: serialisation, confidence, expiry, audit."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .geo import haversine_km
from .models import (
    Area, AuditLog, Camera, FloodReport, LEVEL_RANK, LEVEL_TH, ReportSource,
    ReportStatus, STATION_SITUATION_TH, User, WaterStation, utcnow,
)
from .schemas import CameraOut, ReportOut, WaterStationOut


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise before arithmetic."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def report_confidence(report: FloodReport) -> float:
    """0..1 score used for map opacity and chatbot wording.

    Three inputs: who filed it, how many people agreed, and how old it is.
    Official and CCTV-backed reports start high; a user report earns trust from
    confirmations and loses it as the water has time to move.
    """
    base = {
        ReportSource.official.value: 0.9,
        ReportSource.cctv.value: 0.8,
        ReportSource.user.value: 0.45,
    }.get(report.source, 0.45)

    votes = report.confirm_count - report.dispute_count
    # Each net confirmation adds less than the one before it.
    vote_bonus = 0.12 * votes if votes >= 0 else 0.18 * votes
    score = base + max(min(vote_bonus, 0.4), -0.6)

    created = _aware(report.created_at) or utcnow()
    age_h = (utcnow() - created).total_seconds() / 3600
    decay = max(0.0, 1.0 - (age_h / max(settings.report_ttl_hours, 1)) * 0.5)
    return round(max(0.05, min(1.0, score * decay)), 2)


def age_minutes(report: FloodReport) -> int:
    created = _aware(report.created_at) or utcnow()
    return max(0, int((utcnow() - created).total_seconds() // 60))


def report_to_out(report: FloodReport) -> ReportOut:
    out = ReportOut.model_validate(report)
    out.level_label = LEVEL_TH.get(report.level, report.level)
    out.province_name = report.province.name_th if report.province else None
    out.confidence = report_confidence(report)
    out.age_minutes = age_minutes(report)
    return out


def camera_to_out(camera: Camera, origin: tuple[float, float] | None = None,
                  nearby_level: str | None = None) -> CameraOut:
    out = CameraOut.model_validate(camera)
    out.province_name = camera.province.name_th if camera.province else None
    if origin:
        out.distance_km = round(haversine_km(origin[0], origin[1], camera.lat, camera.lng), 2)
    out.nearby_flood_level = nearby_level

    # How old the picture itself is, not how long ago we fetched it. Agency
    # snapshot endpoints happily serve a month-old frame with HTTP 200.
    frame_at = _aware(camera.last_frame_at)
    if frame_at is not None:
        out.frame_age_minutes = max(0, int((utcnow() - frame_at).total_seconds() // 60))
    return out


def station_to_out(station: WaterStation,
                   origin: tuple[float, float] | None = None) -> WaterStationOut:
    """Serialise a gauge reading, flagging how current it is.

    A gauge that stopped reporting is worse than useless if shown as current,
    so staleness is computed here rather than left to each caller.
    """
    from .stations import stale_cutoff

    out = WaterStationOut.model_validate(station)
    out.situation_label = STATION_SITUATION_TH.get(station.situation_level or 0)
    measured = _aware(station.measured_at)
    out.is_stale = measured is None or measured < stale_cutoff()
    if origin:
        out.distance_km = round(haversine_km(origin[0], origin[1], station.lat, station.lng), 2)
    return out


def expire_stale_reports(db: Session) -> int:
    """Flip approved-but-old reports to expired. Cheap, idempotent, safe to spam.

    Called from the report/stats list endpoints so the map never shows a pin the
    data no longer supports, without needing a scheduler process.
    """
    result = db.execute(
        update(FloodReport)
        .where(FloodReport.status.in_([ReportStatus.approved.value, ReportStatus.pending.value]))
        .where(FloodReport.expires_at <= utcnow())
        .values(status=ReportStatus.expired.value, updated_at=utcnow())
    )
    if result.rowcount:
        db.commit()
    return result.rowcount or 0


def recount_votes(db: Session, report: FloodReport) -> None:
    from .models import ReportVote  # local import keeps module import graph flat

    rows = db.execute(
        select(ReportVote.vote).where(ReportVote.report_id == report.id)
    ).scalars().all()
    report.confirm_count = sum(1 for v in rows if v == "confirm")
    report.dispute_count = sum(1 for v in rows if v == "dispute")


def apply_vote_side_effects(report: FloodReport) -> None:
    """Confirmations extend a report's life; disputes can pull it back for review."""
    if report.confirm_count and report.status == ReportStatus.approved.value:
        report.expires_at = FloodReport.default_expiry()

    if (report.dispute_count >= settings.auto_flag_disputes
            and report.dispute_count > report.confirm_count
            and report.status == ReportStatus.approved.value):
        report.status = ReportStatus.pending.value
        report.moderation_note = (
            f"ถูกดึงกลับคิวตรวจอัตโนมัติ: มีผู้แย้ง {report.dispute_count} ราย "
            f"มากกว่าผู้ยืนยัน {report.confirm_count} ราย"
        )
    report.updated_at = utcnow()


def worst_level(levels: list[str]) -> str | None:
    known = [lv for lv in levels if lv in LEVEL_RANK]
    if not known:
        return None
    return max(known, key=lambda lv: LEVEL_RANK[lv])


def resolve_province(db: Session, lat: float, lng: float) -> Area | None:
    """Nearest province centroid.

    An approximation — no polygon data ships with the app — but good enough to
    group reports for stats and chatbot answers, and a moderator can correct it.
    """
    provinces = db.execute(
        select(Area).where(Area.kind == "province", Area.lat.is_not(None))
    ).scalars().all()
    if not provinces:
        return None
    return min(provinces, key=lambda p: haversine_km(lat, lng, p.lat, p.lng))


def nearby_flood_level(db: Session, lat: float, lng: float, radius_km: float = 1.5) -> str | None:
    """Worst active flood level within radius — used to badge camera markers."""
    from .geo import bbox_around

    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    rows = db.execute(
        select(FloodReport.level, FloodReport.lat, FloodReport.lng)
        .where(FloodReport.status == ReportStatus.approved.value)
        .where(FloodReport.lat.between(min_lat, max_lat))
        .where(FloodReport.lng.between(min_lng, max_lng))
    ).all()
    levels = [r.level for r in rows if haversine_km(lat, lng, r.lat, r.lng) <= radius_km]
    return worst_level(levels)


def log_action(db: Session, actor: User | None, action: str, entity: str,
               entity_id: str | None, detail: str | None = None) -> None:
    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=(actor.display_name or actor.username) if actor else "ระบบ/ไม่ระบุตัวตน",
        action=action, entity=entity, entity_id=str(entity_id) if entity_id else None,
        detail=detail,
    ))


def initial_status(source: str, is_trusted_reporter: bool) -> str:
    """New reports go live immediately only when we can vouch for the source."""
    if source in (ReportSource.official.value, ReportSource.cctv.value):
        return ReportStatus.approved.value
    if is_trusted_reporter or not settings.require_moderation:
        return ReportStatus.approved.value
    return ReportStatus.pending.value


def since_cutoff(hours: int) -> datetime:
    return utcnow() - timedelta(hours=max(1, hours))
