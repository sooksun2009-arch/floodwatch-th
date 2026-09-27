"""Import flood points published by an outside body (e.g. a กทม. district report).

Why this exists: agencies publish flood lists as a page, a spreadsheet or a PDF,
each row carrying a road name, a depth and a Google Maps link. There is no open
API to poll. So instead of guessing at endpoints, the app accepts the published
records directly — pasted text, CSV/XLSX rows, or a JSON feed once one is made
available — and normalises them into ordinary reports.

Imported rows are upserted on (external_source, external_ref), so re-importing
an updated list moves existing pins rather than duplicating them.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .geo import in_thailand
from .models import Area, FloodReport, ReportSource, ReportStatus, level_from_depth, utcnow

# ---------------------------------------------------------------- coordinates

# 13°41'11.3"N 100°38'06.7"E
DMS_PAT = re.compile(
    r"(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*[\"″]?\s*([NSns])"
    r"[,\s]+(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*[\"″]?\s*([EWew])"
)
# 13.686460, 100.635200
DECIMAL_PAT = re.compile(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{2,3}\.\d{3,})")
# Google Maps URL shapes
GMAPS_AT_PAT = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
GMAPS_Q_PAT = re.compile(r"[?&](?:q|query|ll|destination)=(-?\d+\.\d+)%2C(-?\d+\.\d+)",
                         re.IGNORECASE)
GMAPS_Q_PLAIN_PAT = re.compile(r"[?&](?:q|query|ll|destination)=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
                               re.IGNORECASE)
GMAPS_3D4D_PAT = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")


def _dms_to_decimal(deg: str, minute: str, second: str, hemisphere: str) -> float:
    value = int(deg) + int(minute) / 60 + float(second) / 3600
    return -value if hemisphere.upper() in ("S", "W") else value


def parse_coords(text: str) -> tuple[float, float] | None:
    """Pull a coordinate pair out of free text or a Google Maps link.

    Handles every shape the published reports use: a decimal pair, a
    degrees/minutes/seconds pair as Google Maps displays it, and the several
    URL forms Google produces when you copy a pin.
    """
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)

    match = DMS_PAT.search(text)
    if match:
        lat = _dms_to_decimal(*match.group(1, 2, 3, 4))
        lng = _dms_to_decimal(*match.group(5, 6, 7, 8))
        return (lat, lng) if in_thailand(lat, lng) else None

    for pattern in (GMAPS_3D4D_PAT, GMAPS_AT_PAT, GMAPS_Q_PAT, GMAPS_Q_PLAIN_PAT, DECIMAL_PAT):
        match = pattern.search(text)
        if match:
            lat, lng = float(match.group(1)), float(match.group(2))
            if in_thailand(lat, lng):
                return lat, lng
    return None


# ---------------------------------------------------------------- depth & level

# "ท่วมสูง 20 ซม. หรือมากกว่า", "ระดับน้ำ 15-20 ซม.", "สูง 0.5 เมตร"
DEPTH_PAT = re.compile(
    r"(?:ท่วมสูง|สูง|ลึก|ระดับ(?:น้ำ)?)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:-|–|ถึง)?\s*(\d+(?:\.\d+)?)?\s*"
    r"(ซม\.?|เซนติเมตร|เซน|cm|ม\.?|เมตร|m)\b"
)

LEVEL_KEYWORDS = (
    ("closed", ("ปิดการจราจร", "ปิดถนน", "ห้ามผ่าน", "สัญจรไม่ได้", "ผ่านไม่ได้", "รถเล็กผ่านไม่ได้")),
    ("severe", ("น้ำท่วมสูง", "ท่วมหนัก", "วิกฤต", "ท่วมขังสูง")),
    ("deep", ("รถเล็กควรเลี่ยง", "ท่วมขังรอระบาย")),
    ("puddle", ("น้ำขัง", "ผิวจราจรเปียก", "ฝนตกน้ำขัง", "รอระบาย")),
    ("normal", ("ระบายแล้ว", "เข้าสู่ปกติ", "น้ำลดแล้ว", "คลี่คลาย")),
)


def parse_depth_cm(text: str) -> int | None:
    """Depth in centimetres. A range like "15-20 ซม." takes the upper bound.

    The upper bound is deliberate: under-reporting depth is the failure that
    strands a driver, so a range resolves to its worse end.
    """
    if not text:
        return None
    match = DEPTH_PAT.search(unicodedata.normalize("NFKC", text))
    if not match:
        return None
    low, high, unit = match.group(1), match.group(2), match.group(3)
    value = float(high if high else low)
    # Compare against an explicit set: a prefix test does not work here, because
    # "เมตร" begins with "เ", not "ม".
    if unit.rstrip(".") in ("ม", "เมตร", "m"):
        value *= 100
    return int(round(value)) if 0 <= value <= 1000 else None


def parse_level(text: str, depth_cm: int | None) -> str:
    """Prefer an explicit status phrase; fall back to the measured depth."""
    haystack = text or ""
    for level, keywords in LEVEL_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            # A stated depth that is worse than the phrase wins — "น้ำขัง 45 ซม."
            # is not a puddle.
            if depth_cm is not None:
                from .models import LEVEL_RANK
                by_depth = level_from_depth(depth_cm)
                if LEVEL_RANK.get(by_depth, 0) > LEVEL_RANK.get(level, 0):
                    return by_depth
            return level
    if depth_cm is not None:
        return level_from_depth(depth_cm)
    return "shallow"


DISTRICT_PAT = re.compile(r"เขต([ก-๙]+)")
ROAD_PAT = re.compile(r"(?:ถนน|ถ\.)\s*([ก-๙A-Za-z0-9\s.\-]{2,60})")


# ---------------------------------------------------------------- record model

@dataclass
class ImportedRecord:
    place: str
    lat: float
    lng: float
    depth_cm: int | None = None
    level: str = "shallow"
    district: str | None = None
    description: str | None = None
    external_ref: str | None = None


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    records: list[ImportedRecord] = field(default_factory=list)


# ---------------------------------------------------------------- parsers

def parse_pasted_block(text: str) -> ImportResult:
    """Parse records pasted as text, one record per blank-line-separated block.

    Built for the shape the กทม. district lists use, e.g.

        21. ถ.วชิรธรรมสาธิต
        ช่วงน้ำท่วม: บริเวณใกล้ ซ.วัดทุ่ง
        ช่วง 3 แยกซอยวัดทุ่ง ท่วมสูง 20 ซม. หรือมากกว่า
        เขตพระโขนง
        https://maps.google.com/?q=13.686460,100.635200

    Anything without a usable coordinate is reported as an error rather than
    guessed at, because a flood pin in the wrong place is worse than a missing
    one.
    """
    result = ImportResult()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]

    for index, block in enumerate(blocks, start=1):
        coords = parse_coords(block)
        if coords is None:
            first_line = block.splitlines()[0][:60]
            result.errors.append(f"บล็อกที่ {index} ({first_line}) ไม่พบพิกัด — ข้าม")
            result.skipped += 1
            continue

        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        # Title line: drop a leading list number.
        title = re.sub(r"^\s*\d{1,3}[.)]\s*", "", lines[0]) if lines else ""
        title = re.sub(r"https?://\S+", "", title).strip()

        body = " ".join(lines[1:])
        depth = parse_depth_cm(block)
        district_match = DISTRICT_PAT.search(block)

        # Prefer the explicit "ช่วงน้ำท่วม" segment as the place label.
        segment = ""
        seg_match = re.search(r"ช่วง(?:น้ำท่วม)?[:：]?\s*([^\n]{3,80})", block)
        if seg_match:
            segment = re.sub(r"https?://\S+", "", seg_match.group(1)).strip()

        place = " ".join(p for p in (title, segment) if p)[:255] or title[:255] or "ไม่ระบุจุด"

        result.records.append(ImportedRecord(
            place=place,
            lat=coords[0], lng=coords[1],
            depth_cm=depth,
            level=parse_level(block, depth),
            district=district_match.group(1) if district_match else None,
            description=re.sub(r"https?://\S+", "", body).strip()[:2000] or None,
            # Stable across re-imports of the same list: the road plus the pin.
            external_ref=f"{title}|{coords[0]:.5f},{coords[1]:.5f}"[:128],
        ))
    return result


# ชื่อคอลัมน์ที่พบในไฟล์รายงานของหน่วยงาน — เทียบแบบไม่สนตัวพิมพ์/ช่องว่าง
COLUMN_ALIASES = {
    "place": ("ถนน", "ชื่อถนน", "สถานที่", "จุด", "บริเวณ", "ตำแหน่ง", "road", "location", "place"),
    "section": ("ช่วง", "ช่วงน้ำท่วม", "บริเวณน้ำท่วม", "section"),
    "district": ("เขต", "เขตพื้นที่", "สำนักงานเขต", "district", "อำเภอ"),
    "depth": ("ระดับน้ำ", "ความลึก", "ท่วมสูง", "ระดับ", "depth", "depth_cm", "ซม"),
    "lat": ("lat", "latitude", "ละติจูด", "พิกัดละติจูด"),
    "lng": ("lng", "lon", "long", "longitude", "ลองจิจูด", "พิกัดลองจิจูด"),
    "coords": ("พิกัด", "ตำแหน่ง gps", "google maps", "ลิงก์", "link", "url", "maps", "coordinates"),
    "status": ("สถานะ", "หมายเหตุ", "ผลการดำเนินการ", "status", "note", "remark"),
}


def _normalise_header(name: str) -> str:
    return re.sub(r"[\s_.\-]+", "", (name or "").strip().lower())


def _map_columns(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalised = [_normalise_header(h) for h in headers]
    for field_name, aliases in COLUMN_ALIASES.items():
        for idx, header in enumerate(normalised):
            if not header:
                continue
            if any(_normalise_header(alias) in header for alias in aliases):
                mapping.setdefault(field_name, idx)
                break
    return mapping


def parse_table(rows: list[list[str]]) -> ImportResult:
    """Parse CSV/XLSX rows whose header names the columns (Thai or English)."""
    result = ImportResult()
    if not rows:
        result.errors.append("ไฟล์ว่าง")
        return result

    header, *data_rows = rows
    mapping = _map_columns([str(h) for h in header])

    has_coords = "coords" in mapping or ("lat" in mapping and "lng" in mapping)
    if not has_coords:
        result.errors.append(
            "ไม่พบคอลัมน์พิกัด — ต้องมีคอลัมน์ lat และ lng หรือคอลัมน์ลิงก์ Google Maps/พิกัด")
        return result

    def cell(row: list, key: str) -> str:
        idx = mapping.get(key)
        if idx is None or idx >= len(row) or row[idx] is None:
            return ""
        return str(row[idx]).strip()

    for line_no, row in enumerate(data_rows, start=2):
        if not any(str(c).strip() for c in row if c is not None):
            continue

        coords = None
        if "lat" in mapping and "lng" in mapping:
            try:
                lat, lng = float(cell(row, "lat")), float(cell(row, "lng"))
                coords = (lat, lng) if in_thailand(lat, lng) else None
            except ValueError:
                coords = None
        if coords is None:
            coords = parse_coords(cell(row, "coords"))
        if coords is None:
            result.errors.append(f"แถวที่ {line_no}: ไม่พบพิกัดที่ใช้ได้ — ข้าม")
            result.skipped += 1
            continue

        place = cell(row, "place") or "ไม่ระบุจุด"
        section = cell(row, "section")
        status = cell(row, "status")
        depth_text = cell(row, "depth")

        blob = " ".join(x for x in (place, section, depth_text, status) if x)
        depth = parse_depth_cm(depth_text) or parse_depth_cm(blob)

        result.records.append(ImportedRecord(
            place=(f"{place} {section}".strip() if section else place)[:255],
            lat=coords[0], lng=coords[1],
            depth_cm=depth,
            level=parse_level(blob, depth),
            district=cell(row, "district").replace("เขต", "").strip() or None,
            description=status[:2000] or None,
            external_ref=f"{place}|{coords[0]:.5f},{coords[1]:.5f}"[:128],
        ))
    return result


def parse_csv(content: bytes) -> ImportResult:
    """Decode a CSV. Excel in Thailand writes UTF-8 BOM or cp874, so try both."""
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp874", "tis-620"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        result = ImportResult()
        result.errors.append("อ่านไฟล์ไม่ได้ — ไม่รู้จักการเข้ารหัสอักขระ (ลองบันทึกเป็น UTF-8)")
        return result

    dialect_sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(dialect_sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return parse_table([row for row in csv.reader(io.StringIO(text), dialect)])


def parse_xlsx(content: bytes) -> ImportResult:
    """Parse the first worksheet of an .xlsx file, if openpyxl is installed."""
    result = ImportResult()
    try:
        from openpyxl import load_workbook
    except ImportError:
        result.errors.append(
            "รองรับ .xlsx ต้องติดตั้ง openpyxl ก่อน (pip install openpyxl) "
            "หรือบันทึกไฟล์เป็น CSV แล้วอัปโหลดใหม่")
        return result

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a family of format errors
        result.errors.append(f"เปิดไฟล์ .xlsx ไม่ได้: {exc}")
        return result

    sheet = workbook[workbook.sheetnames[0]]
    rows = [["" if c is None else c for c in row] for row in sheet.iter_rows(values_only=True)]
    workbook.close()
    return parse_table(rows)


# ---------------------------------------------------------------- persistence

def _district_area(db: Session, name: str | None) -> Area | None:
    if not name:
        return None
    return db.execute(
        select(Area).where(Area.kind == "district", Area.name_th == name.strip())
    ).scalars().first()


def persist(db: Session, result: ImportResult, source_name: str,
            actor_id: str | None, auto_approve: bool) -> ImportResult:
    """Upsert parsed records. Existing rows from the same source are updated."""
    from .services import resolve_province

    for record in result.records:
        existing = None
        if record.external_ref:
            existing = db.execute(
                select(FloodReport)
                .where(FloodReport.reporter_name == source_name)
                .where(FloodReport.place == record.place)
                .where(FloodReport.lat.between(record.lat - 1e-5, record.lat + 1e-5))
                .where(FloodReport.lng.between(record.lng - 1e-5, record.lng + 1e-5))
            ).scalars().first()

        province = resolve_province(db, record.lat, record.lng)
        district_area = _district_area(db, record.district)
        status = ReportStatus.approved.value if auto_approve else ReportStatus.pending.value

        if existing:
            existing.level = record.level
            existing.depth_cm = record.depth_cm
            existing.description = record.description
            existing.district = record.district or existing.district
            existing.status = status
            existing.updated_at = utcnow()
            existing.expires_at = FloodReport.default_expiry()
            result.updated += 1
        else:
            db.add(FloodReport(
                lat=record.lat, lng=record.lng,
                place=record.place,
                district=record.district,
                province_id=(district_area.parent_id if district_area
                             else (province.id if province else None)),
                level=record.level,
                depth_cm=record.depth_cm,
                description=record.description,
                source=ReportSource.official.value,
                status=status,
                reporter_id=actor_id,
                reporter_name=source_name,
                confirm_count=0, dispute_count=0,
                expires_at=FloodReport.default_expiry(),
            ))
            result.created += 1

    db.commit()
    return result
