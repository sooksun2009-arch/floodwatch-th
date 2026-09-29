"""CSV downloads: the owner's copy of what the site has collected.

The database lives on Neon, whose free plan only keeps a short restore window.
These files are the longer memory -- downloaded by hand from the admin page,
or every night by keepalive.gs into Google Drive.

What is left out is deliberate: no reporter IP, no reporter name, no user
accounts. A backup gets copied, forwarded and forgotten in a Drive folder, so
it holds what the public map already shows plus the counts, and nothing that
could identify the person who filed a report.
"""
import csv
import hmac
import io
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import get_current_user_optional
from ..models import FloodReport, Role, User
from ..visits import META_DAY, Tally, VisitStat

router = APIRouter(prefix="/api/admin/export", tags=["export"])

BANGKOK = timezone(timedelta(hours=7))


def _allowed(authorization: str | None = Header(default=None),
             user: User | None = Depends(get_current_user_optional)) -> None:
    """A signed-in moderator, or the scheduled backup job holding BACKUP_TOKEN."""
    if user is not None and user.role in (Role.moderator.value, Role.admin.value):
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    # compare_digest, not ==, so the token cannot be guessed by timing.
    if settings.backup_token and supplied and hmac.compare_digest(
            supplied.encode(), settings.backup_token.encode()):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ต้องเข้าสู่ระบบเป็นผู้ตรวจสอบ หรือใช้ BACKUP_TOKEN")


def _thai_time(value) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:  # SQLite hands back naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M")


def _csv(name: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    # BOM first: without it Excel reads the file as the local codepage and
    # every Thai character turns to mojibake.
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="floodwatch-{name}.csv"'},
    )


@router.get("/reports.csv", dependencies=[Depends(_allowed)])
def reports_csv(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(
        select(FloodReport).options(joinedload(FloodReport.province))
        .order_by(FloodReport.created_at.asc())
    ).unique().scalars().all()
    return _csv("reports", [
        "id", "แจ้งเมื่อ", "สถานะ", "ระดับน้ำ", "ลึก(ซม.)", "รถเก๋งผ่านได้", "จังหวัด", "เขต/อำเภอ",
        "จุดสังเกต", "lat", "lng", "รายละเอียด", "รูป", "แหล่งที่มา", "ยืนยัน", "แย้ง(น้ำลด)",
        "หมดอายุ", "ตรวจเมื่อ", "หมายเหตุผู้ตรวจ",
    ], ([
        r.id, _thai_time(r.created_at), r.status, r.level, r.depth_cm or "",
        "" if r.passable is None else ("ใช่" if r.passable else "ไม่"),
        r.province.name_th if r.province else "", r.district or "", r.place or "",
        r.lat, r.lng, r.description or "", r.photo_url or "", r.source,
        r.confirm_count, r.dispute_count, _thai_time(r.expires_at),
        _thai_time(r.moderated_at), r.moderation_note or "",
    ] for r in rows))


@router.get("/visits.csv", dependencies=[Depends(_allowed)])
def visits_csv(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(
        select(VisitStat).where(VisitStat.day != META_DAY)
        .order_by(VisitStat.day, VisitStat.hour, VisitStat.page)
    ).scalars().all()
    return _csv("visits", ["วันที่", "ชั่วโมง", "หน้า", "เปิดดู", "ผู้ใช้"],
                ([v.day, v.hour, v.page, v.views, v.visitors] for v in rows))


@router.get("/tallies.csv", dependencies=[Depends(_allowed)])
def tallies_csv(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(select(Tally).order_by(Tally.day, Tally.kind, Tally.key)).scalars().all()
    return _csv("tallies", ["วันที่", "ประเภท", "ค่า", "จำนวน"],
                ([t.day, t.kind, t.key, t.count] for t in rows))
