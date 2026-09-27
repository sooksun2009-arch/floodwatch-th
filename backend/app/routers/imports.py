"""Bring in flood points published by an outside body.

No endpoint here scrapes a third-party site. Each one takes data the operator
already has the right to use — a pasted list, an uploaded spreadsheet, or a feed
whose URL the operator configures — and normalises it into reports.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_moderator
from ..importers import (
    ImportResult, parse_coords, parse_csv, parse_pasted_block, parse_table, parse_xlsx, persist,
)
from ..models import User
from ..services import log_action

router = APIRouter(prefix="/api/import", tags=["import"])

MAX_IMPORT_MB = 10


class PasteIn(BaseModel):
    text: str = Field(min_length=10, max_length=200_000)
    source_name: str = Field(default="รายงานหน่วยงาน", max_length=128)
    auto_approve: bool = True
    dry_run: bool = False


class ImportReportOut(BaseModel):
    created: int
    updated: int
    skipped: int
    parsed: int
    errors: list[str]
    preview: list[dict]
    dry_run: bool


def _to_out(result: ImportResult, dry_run: bool) -> ImportReportOut:
    return ImportReportOut(
        created=result.created, updated=result.updated, skipped=result.skipped,
        parsed=len(result.records), errors=result.errors[:50], dry_run=dry_run,
        preview=[{
            "place": r.place, "lat": r.lat, "lng": r.lng, "level": r.level,
            "depth_cm": r.depth_cm, "district": r.district,
        } for r in result.records[:25]],
    )


@router.post("/paste", response_model=ImportReportOut)
def import_paste(payload: PasteIn, db: Session = Depends(get_db),
                 user: User = Depends(require_moderator)):
    """Import records pasted as text — the fastest path when a list is published
    as a web page or a chat message rather than a file.

    Set dry_run to preview what would be created without writing anything.
    """
    result = parse_pasted_block(payload.text)
    if not result.records:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "อ่านรายการไม่ได้เลย: " + ("; ".join(result.errors[:5]) or
                                       "ไม่พบพิกัดในข้อความ แต่ละรายการต้องมีพิกัดหรือลิงก์ Google Maps"),
        )

    if payload.dry_run:
        return _to_out(result, dry_run=True)

    persist(db, result, payload.source_name, user.id, payload.auto_approve)
    log_action(db, user, "import_paste", "report", None,
               f"{payload.source_name}: เพิ่ม {result.created} แก้ไข {result.updated}")
    db.commit()
    return _to_out(result, dry_run=False)


@router.post("/file", response_model=ImportReportOut)
async def import_file(file: UploadFile = File(...),
                      source_name: str = Form(default="รายงานหน่วยงาน"),
                      auto_approve: bool = Form(default=True),
                      dry_run: bool = Form(default=False),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_moderator)):
    """Import a .csv or .xlsx export, such as a district office's daily list."""
    limit = MAX_IMPORT_MB * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"ไฟล์ใหญ่เกิน {MAX_IMPORT_MB} MB")

    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        result = parse_xlsx(content)
    elif name.endswith((".csv", ".txt", ".tsv")):
        result = parse_csv(content)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "รองรับเฉพาะไฟล์ .csv และ .xlsx")

    if not result.records:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "อ่านข้อมูลจากไฟล์ไม่ได้: " + ("; ".join(result.errors[:5]) or "ไม่พบแถวที่ใช้ได้"),
        )

    if dry_run:
        return _to_out(result, dry_run=True)

    persist(db, result, source_name, user.id, auto_approve)
    log_action(db, user, "import_file", "report", None,
               f"{file.filename}: เพิ่ม {result.created} แก้ไข {result.updated}")
    db.commit()
    return _to_out(result, dry_run=False)


class FeedIn(BaseModel):
    """Pull from a JSON feed the operator is entitled to use.

    field_map points at the keys in each item, so a new feed is a configuration
    change rather than a code change. Example:
        {"place": "road_name", "coords": "gmaps_url", "depth": "water_level_cm"}
    """

    url: str = Field(pattern=r"^https?://", max_length=1024)
    items_key: str | None = Field(default=None, max_length=64,
                                  description="คีย์ที่เก็บ array เช่น data หรือ results")
    field_map: dict[str, str] = Field(default_factory=dict)
    source_name: str = Field(default="ฟีดภายนอก", max_length=128)
    auto_approve: bool = False
    dry_run: bool = True
    verify_tls: bool = True


@router.post("/feed", response_model=ImportReportOut)
async def import_feed(payload: FeedIn, db: Session = Depends(get_db),
                      user: User = Depends(require_moderator)):
    """Fetch and import a JSON feed.

    TLS verification stays on by default. It can be turned off per call for a
    feed on a private network with an internal certificate authority — never do
    that for a feed on the public internet, since without verification the
    response could come from anyone.
    """
    import httpx

    from ..config import settings

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=payload.verify_tls,
                                     follow_redirects=True) as client:
            resp = await client.get(payload.url,
                                    headers={"User-Agent": settings.http_user_agent})
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"เรียกฟีดไม่สำเร็จ: {type(exc).__name__} — {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"ฟีดตอบกลับรหัส {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "ฟีดไม่ได้ส่ง JSON กลับมา") from exc

    items = data
    if payload.items_key:
        items = data.get(payload.items_key) if isinstance(data, dict) else None
    elif isinstance(data, dict):
        # Common wrapper keys, in the order feeds tend to use them.
        for key in ("data", "items", "results", "records", "features"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    if not isinstance(items, list) or not items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "ไม่พบรายการ (array) ในฟีด — ระบุ items_key ให้ถูกต้อง")

    # Flatten each item into a row and reuse the table parser, so a feed and a
    # spreadsheet go through exactly the same normalisation.
    mapped_fields = list(payload.field_map) or ["place", "district", "depth", "coords",
                                                "lat", "lng", "status"]
    header = mapped_fields
    rows: list[list[str]] = [header]
    for item in items[:2000]:
        if not isinstance(item, dict):
            continue
        row = []
        for field_name in mapped_fields:
            source_key = payload.field_map.get(field_name, field_name)
            value = item.get(source_key, "")
            row.append("" if value is None else str(value))
        rows.append(row)

    result = parse_table(rows)
    if not result.records:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "แปลงข้อมูลจากฟีดไม่ได้: " + ("; ".join(result.errors[:5]) or "ไม่พบพิกัด"),
        )

    if payload.dry_run:
        return _to_out(result, dry_run=True)

    persist(db, result, payload.source_name, user.id, payload.auto_approve)
    log_action(db, user, "import_feed", "report", None,
               f"{payload.url}: เพิ่ม {result.created} แก้ไข {result.updated}")
    db.commit()
    return _to_out(result, dry_run=False)


@router.post("/parse-coords", response_model=dict)
def parse_coords_endpoint(text: str = Form(...), _: User = Depends(require_moderator)):
    """Utility for the admin UI: turn a pasted Google Maps link into lat/lng."""
    coords = parse_coords(text)
    if coords is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "ไม่พบพิกัดในข้อความนี้")
    return {"lat": coords[0], "lng": coords[1]}
