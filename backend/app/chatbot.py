"""Thai-language flood chatbot.

Design decision: the answer is produced from database facts by deterministic
rules, not by a language model. Reasons:

  * During a flood the app must answer with zero external dependencies and zero
    per-question cost.
  * Water depth is safety information. A retrieval-and-template answer cannot
    invent a road that is not flooded.

An optional LLM pass (CHAT_LLM_ENABLED) only *rephrases* the same retrieved
facts. If it fails or is disabled, the rule answer is what ships.
"""
import difflib
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .geo import bbox_around, haversine_km
from . import chatbot_en as en
from .models import (
    Area, Camera, FloodReport, LEVEL_RANK, LEVEL_TH, ReportStatus,
)
from .schemas import ChatSuggestion
from .services import camera_to_out, nearby_flood_level, report_to_out, worst_level

# คำนำหน้าสถานที่ที่ตัดออกก่อนเทียบชื่อ
PLACE_PREFIXES = (
    "จังหวัด", "จ.", "อำเภอ", "อ.", "ตำบล", "ต.", "เขต", "แขวง", "ถนน", "ถ.",
    "ซอย", "ซ.", "แยก", "สี่แยก", "สามแยก", "หมู่บ้าน", "ม.", "บ้าน", "ตลาด",
    "หน้า", "แถว", "ย่าน", "บริเวณ", "ที่", "ใน", "แถวๆ", "ละแวก", "ละแวกๆ",
)

# คำที่ไม่ใช่ชื่อสถานที่ ตัดทิ้งก่อน fuzzy match
STOPWORDS = {
    "น้ำ", "น้ำท่วม", "ท่วม", "ท่วมไหม", "น้ำท่วมไหม", "ไหม", "มั้ย", "หรือเปล่า",
    "เปล่า", "ครับ", "ค่ะ", "คะ", "ฮะ", "จ้า", "นะ", "หน่อย", "ช่วย", "ขอ", "อยาก",
    "รู้", "ทราบ", "ดู", "เช็ค", "เชค", "ตรวจ", "สอบถาม", "ถาม", "ตอนนี้", "วันนี้",
    "เดี๋ยวนี้", "ปัจจุบัน", "สถานการณ์", "สภาพ", "เป็นไง", "เป็นยังไง", "ยังไง",
    "อย่างไร", "ระดับ", "สูง", "เท่าไหร่", "เท่าไร", "กี่", "อยู่", "มี", "บ้าง",
    "และ", "กับ", "ของ", "จาก", "ไป", "มา", "ที่ไหน", "ไหน", "แล้ว", "ยัง", "จะ",
    "ได้", "ผ่าน", "ผ่านได้", "ขับ", "รถ", "กล้อง", "cctv", "กล้องวงจรปิด",
}

GREETING_PAT = re.compile(r"^(สวัสดี|หวัดดี|hello|hi|ดีครับ|ดีค่ะ|ทัก)")
# English alternatives alongside the Thai. Translating the answers without
# these was half a feature: an English question fell through to the fallback,
# which then replied in Thai, which is the worst of both.
NEAR_ME_PAT = re.compile(
    r"(ใกล้ฉัน|ใกล้ ๆ ฉัน|ใกล้เคียง|ตรงนี้|แถวนี้|รอบตัว|ที่ฉันอยู่|บริเวณนี้"
    r"|near\s*me|around\s*me|nearby|near\s*here|my\s*area|where\s*i\s*am)",
    re.IGNORECASE)
CAMERA_PAT = re.compile(
    r"(กล้อง|cctv|วงจรปิด|ดูภาพ|ดูสด|live|camera|webcam)", re.IGNORECASE)
WORST_PAT = re.compile(
    r"(หนักสุด|หนักที่สุด|ท่วมหนัก|วิกฤต|แย่สุด|ที่ไหนท่วม|ตรงไหนท่วม|จุดไหนท่วม|ที่ไหนบ้าง"
    r"|worst|most\s*flooded|where\s*is\s*it\s*(bad|worst)|badly\s*flooded"
    r"|which\s*areas?|hardest\s*hit)",
    re.IGNORECASE)
HOWTO_PAT = re.compile(
    r"(แจ้ง.*(ยังไง|อย่างไร|ไหน)|วิธีแจ้ง|รายงาน.*(ยังไง|อย่างไร)|จะแจ้ง|อยากแจ้ง|แจ้งเหตุ"
    r"|how\s*(do|can)\s*i\s*report|how\s*to\s*report|report\s*flooding)",
    re.IGNORECASE)
STATS_PAT = re.compile(
    r"(กี่จุด|จำนวน|ทั้งหมดกี่|สถิติ|สรุป|ภาพรวม|มีกี่"
    r"|how\s*many|summary|overview|statistics)", re.IGNORECASE)
SAFETY_PAT = re.compile(
    r"(ขับผ่าน|ผ่านได้|ลุยน้ำ|เอารถ|รถเก๋ง|รถกระบะ|อันตราย|ปลอดภัย|ควรทำ|เตรียมตัว"
    r"|can\s*i\s*drive|safe\s*to\s*drive|drive\s*through|is\s*it\s*safe)",
    re.IGNORECASE)
DEPTH_PAT = re.compile(r"(\d+)\s*(ซม|เซน|เซนติเมตร|cm|เมตร|ม\.)")
HELP_PAT = re.compile(
    r"(ทำอะไรได้|ช่วยอะไร|ใช้ยังไง|คำสั่ง|help|เมนู|what\s*can\s*you\s*do)",
    re.IGNORECASE)

DEFAULT_SUGGESTIONS = [
    ChatSuggestion(label="เช็คเส้นทางบ้าน → ที่ทำงาน",
                   message="จะไปจากบางนาไปรามคำแหง มีน้ำท่วมไหม"),
    ChatSuggestion(label="น้ำท่วมใกล้ฉันไหม", message="น้ำท่วมใกล้ฉันไหม"),
    ChatSuggestion(label="ตอนนี้ท่วมหนักที่ไหน", message="ตอนนี้ท่วมหนักที่ไหน"),
    ChatSuggestion(label="กล้องใกล้ฉัน", message="ขอดูกล้อง CCTV ใกล้ฉัน"),
]

# "จาก X ไป Y", "X ไป Y", "X -> Y", "X ถึง Y"
ROUTE_PATTERNS = (
    re.compile(r"จาก\s*(?P<a>.+?)\s*(?:ไปยัง|ไปที่|ไป|ถึง|->|→|-)\s*(?P<b>.+?)$"),
    re.compile(r"^(?P<a>.+?)\s*(?:->|→)\s*(?P<b>.+?)$"),
    re.compile(r"^(?P<a>.+?)\s+(?:ไปยัง|ไปที่|ไป|ถึง)\s+(?P<b>.+?)$"),
)

ROUTE_HINT_PAT = re.compile(
    r"(เส้นทาง|ทางไป|จะไป|ขับไป|เดินทาง|ไปทำงาน|กลับบ้าน|ไปโรงเรียน|route|"
    r"ผ่านได้ไหม|ไปได้ไหม|ทางไหนดี|เลี่ยง)"
)

# คำท้ายประโยคที่ต้องตัดออกจากชื่อปลายทาง
ROUTE_TAIL_PAT = re.compile(
    r"\s*(มี\s*)?(น้ำ\s*)?(ท่วม)?\s*(ไหม|มั้ย|หรือเปล่า|เปล่า|บ้าง|ยัง|รึเปล่า)?\s*"
    r"(ครับ|ค่ะ|คะ|ฮะ|จ้า|นะ)?\s*$"
)


@dataclass
class ChatResult:
    answer: str
    intent: str
    engine: str = "rules"
    matched_place: str | None = None
    reports: list = field(default_factory=list)
    cameras: list = field(default_factory=list)
    suggestions: list = field(default_factory=lambda: list(DEFAULT_SUGGESTIONS))


# ------------------------------------------------------------------ route question parsing

def _clean_endpoint(text: str) -> str:
    """Strip question tails and leading filler from an extracted endpoint name."""
    cleaned = ROUTE_TAIL_PAT.sub("", text.strip())
    cleaned = re.sub(r"^(ช่วย|ขอ|อยาก|จะ|เช็ค|เชค|ดู|ถาม)\s*", "", cleaned).strip()
    cleaned = re.sub(r"^(เส้นทาง|ทาง|รถ|ขับ|เดินทาง)\s*", "", cleaned).strip()
    for prefix in ("จาก", "ที่"):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return strip_prefix(cleaned)


def extract_route_endpoints(text: str) -> tuple[str, str] | None:
    """Pull (origin, destination) out of a Thai sentence, or None.

    Returns raw names only — resolving them to coordinates needs async I/O and
    happens in the chat router. Callers must treat a non-None result as a
    *candidate*: if either endpoint fails to resolve, fall back to another
    intent rather than reporting an error.
    """
    raw = text.strip()
    if not raw:
        return None

    for pattern in ROUTE_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        a = _clean_endpoint(match.group("a"))
        b = _clean_endpoint(match.group("b"))
        if len(a) >= 2 and len(b) >= 2 and a != b:
            return a, b

    # Thai is written without spaces, so "บางนาไปรามคำแหงท่วมไหม" needs a split
    # on the bare "ไป". Only attempted when the sentence looks like a trip
    # question, since "ไป" also appears inside ordinary sentences.
    if ROUTE_HINT_PAT.search(normalize(raw)) or "ไป" in raw:
        head = ROUTE_TAIL_PAT.sub("", raw)
        parts = head.split("ไป")
        if len(parts) == 2:
            a, b = _clean_endpoint(parts[0]), _clean_endpoint(parts[1])
            if len(a) >= 2 and len(b) >= 2 and a != b:
                return a, b
    return None


def answer_route_needs_endpoints(lang: str = "th") -> ChatResult:
    return ChatResult(intent="route_need_endpoints", answer=(
        "บอกต้นทางกับปลายทางมาได้เลยครับ เช่น\n"
        "• \"จากบางนาไปรามคำแหง ท่วมไหม\"\n"
        "• \"ลาดพร้าว -> สุขุมวิท\"\n\n"
        "หรือกดแท็บ \"เช็คเส้นทาง\" ด้านบน แล้วปักหมุดต้นทาง-ปลายทางบนแผนที่ "
        "ระบบจะบอกจุดน้ำท่วมบนเส้นทาง พร้อมกล้อง CCTV ที่ควรเปิดดูก่อนออกรถ"
    ))


def answer_route_unresolved(missing: list[str], lang: str = "th") -> ChatResult:
    names = " และ ".join(f"\"{m}\"" for m in missing)
    return ChatResult(intent="route_unresolved", answer=(
        f"ผมหาตำแหน่งของ {names} ไม่เจอครับ ลองพิมพ์ให้ละเอียดขึ้น "
        "เช่น ใส่ชื่อเขตหรือจังหวัดต่อท้าย (\"รามคำแหง กรุงเทพ\") "
        "หรือใช้แท็บ \"เช็คเส้นทาง\" ปักหมุดบนแผนที่เองก็ได้ แม่นกว่าครับ"
    ))


# ------------------------------------------------------------------ place lookup

def normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[?!.,;:\"'()\[\]]+", " ", text)
    return re.sub(r"\s+", " ", text)


def strip_prefix(token: str) -> str:
    for prefix in sorted(PLACE_PREFIXES, key=len, reverse=True):
        if token.startswith(prefix) and len(token) > len(prefix):
            return token[len(prefix):].strip()
    return token


_STOPWORDS_LONGEST_FIRST = sorted(STOPWORDS, key=len, reverse=True)


def strip_stopword_affixes(text: str) -> str:
    """Peel filler words off the front and back of a chunk, one at a time.

    Crucially this only strips at the edges. Replacing stopwords everywhere in
    the string would corrupt real names, because Thai is written without spaces
    and short filler words occur inside place names — "เชียงใหม่" contains
    "ไหม", "น้ำพอง" starts with "น้ำ". Stripping only at the edges turns
    "เชียงใหม่ท่วมไหม" into "เชียงใหม่" while leaving the name itself intact.
    """
    current = text.strip()
    for _ in range(12):  # bounded: each pass must shorten the string
        for word in _STOPWORDS_LONGEST_FIRST:
            if len(current) <= len(word):
                continue
            if current.endswith(word):
                current = current[: -len(word)].strip()
                break
            if current.startswith(word):
                current = current[len(word):].strip()
                break
        else:
            break
    return current


def candidate_phrases(text: str) -> list[str]:
    """Phrases that might be a place name, longest first.

    Thai has no spaces inside a phrase, so reliable tokenisation is out of
    reach. Instead every whitespace chunk is offered in several forms — as
    typed, with a location prefix removed, and with filler words peeled off the
    edges — and fuzzy matching picks the winner. Unstripped forms are kept so a
    name that legitimately starts with a filler word still matches exactly.
    """
    cleaned = normalize(text)
    words = [w for w in cleaned.split(" ") if w]
    phrases: list[str] = []

    def offer(chunk: str) -> None:
        if not chunk or chunk in STOPWORDS:
            return
        phrases.append(chunk)
        # "แถวรามคำแหง" -> "รามคำแหง", "จังหวัดเชียงใหม่" -> "เชียงใหม่"
        for variant in (strip_prefix(chunk), strip_stopword_affixes(chunk)):
            if variant and variant != chunk:
                phrases.append(variant)
                # "สถานการณ์จังหวัดเชียงใหม่" needs both passes, in this order.
                deeper = strip_prefix(variant)
                if deeper and deeper != variant:
                    phrases.append(deeper)

    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            offer(" ".join(words[i:i + size]))

    # เผื่อผู้ใช้พิมพ์ติดกันทั้งประโยคโดยไม่เว้นวรรค
    offer(cleaned.replace(" ", ""))

    seen: set[str] = set()
    unique = []
    for phrase in sorted(phrases, key=len, reverse=True):
        phrase = phrase.strip()
        if len(phrase) >= 2 and phrase not in seen and phrase not in STOPWORDS:
            seen.add(phrase)
            unique.append(phrase)
    return unique


@dataclass
class PlaceMatch:
    name: str
    kind: str                # province | district | report_place | camera
    lat: float | None = None
    lng: float | None = None
    province_id: int | None = None
    score: float = 0.0


def _gazetteer(db: Session) -> list[PlaceMatch]:
    """Every name the bot can recognise, built from live data.

    Provinces and districts come from the seeded area table; road names and
    camera names come from the data users and admins actually entered, so the
    bot learns new places as the wiki of reports grows.
    """
    places: list[PlaceMatch] = []

    for area in db.execute(select(Area)).scalars():
        places.append(PlaceMatch(
            name=area.name_th, kind=area.kind, lat=area.lat, lng=area.lng,
            province_id=area.id if area.kind == "province" else area.parent_id,
        ))
        if area.name_en:
            places.append(PlaceMatch(
                name=area.name_en.lower(), kind=area.kind, lat=area.lat, lng=area.lng,
                province_id=area.id if area.kind == "province" else area.parent_id,
            ))

    active_places = db.execute(
        select(FloodReport.place, FloodReport.lat, FloodReport.lng, FloodReport.province_id)
        .where(FloodReport.status == ReportStatus.approved.value)
        .where(FloodReport.place.is_not(None))
    ).all()
    for row in active_places:
        places.append(PlaceMatch(name=row.place, kind="report_place", lat=row.lat,
                                 lng=row.lng, province_id=row.province_id))

    for cam in db.execute(select(Camera).where(Camera.is_active.is_(True))).scalars():
        places.append(PlaceMatch(name=cam.name, kind="camera", lat=cam.lat, lng=cam.lng,
                                 province_id=cam.province_id))
    return places


def match_place(db: Session, text: str) -> PlaceMatch | None:
    gazetteer = _gazetteer(db)
    if not gazetteer:
        return None

    best: PlaceMatch | None = None
    for phrase in candidate_phrases(text):
        for place in gazetteer:
            target = normalize(place.name)
            if not target:
                continue
            if phrase == target:
                score = 1.0
            elif phrase in target or target in phrase:
                # ให้คะแนนตามสัดส่วนความยาวที่ตรงกัน กันคำสั้นไปแมตช์ชื่อยาว
                score = 0.9 * (min(len(phrase), len(target)) / max(len(phrase), len(target)))
            else:
                score = difflib.SequenceMatcher(None, phrase, target).ratio() * 0.85

            # ชื่อจังหวัด/อำเภอ น่าเชื่อถือกว่าชื่อจุดที่ผู้ใช้พิมพ์เอง
            if place.kind in ("province", "district", "landmark"):
                score += 0.05

            # A Latin-script question matched against Thai place names can
            # only ever score on fuzzy similarity, and fuzzy similarity is how
            # "bang na" came back as จังหวัดพังงา -- then answered confidently
            # about the wrong province, 700 km away. On a flood map that is
            # not a cosmetic bug. Latin input has to match much harder.
            latin = bool(re.search(r"[a-z]", phrase))
            floor = 0.92 if latin else 0.68
            if score > floor and (best is None or score > best.score):
                best = PlaceMatch(name=place.name, kind=place.kind, lat=place.lat,
                                  lng=place.lng, province_id=place.province_id, score=score)
    return best


# ------------------------------------------------------------------ retrieval

def _active_query():
    return (select(FloodReport)
            .where(FloodReport.status == ReportStatus.approved.value)
            .order_by(FloodReport.created_at.desc()))


def reports_near(db: Session, lat: float, lng: float, radius_km: float = 5.0,
                 limit: int = 8) -> list[FloodReport]:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    rows = db.execute(
        _active_query()
        .where(FloodReport.lat.between(min_lat, max_lat))
        .where(FloodReport.lng.between(min_lng, max_lng))
        .limit(limit * 4)
    ).scalars().all()
    within = [(haversine_km(lat, lng, r.lat, r.lng), r) for r in rows]
    within = [(d, r) for d, r in within if d <= radius_km]
    within.sort(key=lambda pair: (-LEVEL_RANK.get(pair[1].level, 0), pair[0]))
    return [r for _, r in within[:limit]]


def reports_in_province(db: Session, province_id: int, limit: int = 8) -> list[FloodReport]:
    rows = db.execute(
        _active_query().where(FloodReport.province_id == province_id).limit(limit * 3)
    ).scalars().all()
    rows.sort(key=lambda r: -LEVEL_RANK.get(r.level, 0))
    return rows[:limit]


def cameras_near(db: Session, lat: float, lng: float, radius_km: float = 10.0,
                 limit: int = 5) -> list[Camera]:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    rows = db.execute(
        select(Camera)
        .where(Camera.is_active.is_(True))
        .where(Camera.lat.between(min_lat, max_lat))
        .where(Camera.lng.between(min_lng, max_lng))
        .limit(limit * 6)
    ).scalars().all()
    scored = [(haversine_km(lat, lng, c.lat, c.lng), c) for c in rows]
    scored = [(d, c) for d, c in scored if d <= radius_km]
    scored.sort(key=lambda pair: pair[0])
    return [c for _, c in scored[:limit]]


# ------------------------------------------------------------------ phrasing

def _report_lines(reports: list[FloodReport], lang: str = "th") -> str:
    lines = []
    for r in reports:
        if lang == "en":
            where = (r.place or r.district
                     or (r.province.name_th if r.province else en.tr("where.unknown")))
            label = en.level(r.level)
            extra = (en.tr("line.measured", depth=r.depth_cm,
                           inches=round(r.depth_cm / 2.54)) if r.depth_cm else "")
            trust = (en.tr("line.confirmed", count=r.confirm_count)
                     if r.confirm_count else "")
            lines.append(en.tr("line.report", where=where, label=label,
                               extra=extra, trust=trust))
            continue
        where = r.place or r.district or (r.province.name_th if r.province else "ไม่ระบุจุด")
        label = LEVEL_TH.get(r.level, r.level)
        extra = f" วัดได้ {r.depth_cm} ซม." if r.depth_cm else ""
        trust = f" ยืนยันแล้ว {r.confirm_count} ราย" if r.confirm_count else ""
        lines.append(f"• {where} — {label}.{extra}{trust}")
    return "\n".join(lines)


def _safety_note(lang: str) -> str:
    return en.SAFETY_NOTE if lang == "en" else SAFETY_NOTE


SAFETY_NOTE = (
    "\n\nข้อควรระวัง: น้ำสูงเกิน 30 ซม. รถเก๋งมีโอกาสเครื่องดับ และน้ำไหลแรงเพียง "
    "15 ซม. ก็ทำให้คนล้มได้ ถ้าไม่จำเป็นให้เลี่ยงเส้นทาง"
)


def answer_flood_at_place(db: Session, place: PlaceMatch, lang: str = "th") -> ChatResult:
    if place.kind == "province" and place.province_id:
        reports = reports_in_province(db, place.province_id)
        scope = f"จังหวัด{place.name}" if place.name != "กรุงเทพมหานคร" else place.name
    elif place.lat is not None and place.lng is not None:
        radius = 3.0 if place.kind in ("report_place", "camera", "landmark") else 8.0
        reports = reports_near(db, place.lat, place.lng, radius_km=radius)
        scope = place.name
    else:
        reports = []
        scope = place.name

    if not reports:
        cameras = (cameras_near(db, place.lat, place.lng)
                   if place.lat is not None and place.lng is not None else [])
        if lang == "en":
            answer = en.tr("place.none", scope=scope)
            if cameras:
                answer += en.tr("place.cameras", count=len(cameras))
        else:
            answer = (f"ตอนนี้ยังไม่มีรายงานน้ำท่วมที่ยืนยันแล้วในพื้นที่ {scope} ครับ\n\n"
                      "หมายเหตุ: หมายถึง \"ยังไม่มีใครแจ้ง\" ไม่ใช่ \"ยืนยันว่าไม่ท่วม\" "
                      "ถ้าคุณเห็นน้ำท่วมอยู่ ช่วยกดปุ่มแจ้งเหตุเพื่อเตือนคนอื่นด้วยครับ")
            if cameras:
                answer += f"\n\nมีกล้อง CCTV ใกล้พื้นที่นี้ {len(cameras)} ตัว กดดูภาพสดได้เลย"
        return ChatResult(answer=answer, intent="flood_at_place", matched_place=place.name,
                          cameras=[camera_to_out(c, (place.lat, place.lng)) for c in cameras])

    worst = worst_level([r.level for r in reports])
    impassable = [r for r in reports if r.level in ("severe", "closed") or r.passable is False]
    if lang == "en":
        headline = en.tr("place.headline", scope=scope, count=len(reports),
                         worst=en.level(worst))
    else:
        headline = (f"พื้นที่ {scope} มีรายงานน้ำท่วมที่ยืนยันแล้ว {len(reports)} จุด "
                    f"ระดับหนักสุดคือ {LEVEL_TH.get(worst, worst)}")
    answer = f"{headline}\n\n{_report_lines(reports, lang)}"
    if impassable:
        answer += (en.tr("place.impassable", count=len(impassable)) if lang == "en"
                   else f"\n\nมี {len(impassable)} จุดที่รถผ่านไม่ได้หรือปิดการจราจร ควรเลี่ยงเส้นทาง")
    answer += _safety_note(lang)

    cameras = (cameras_near(db, place.lat, place.lng, radius_km=8.0, limit=3)
               if place.lat is not None and place.lng is not None else [])
    return ChatResult(
        answer=answer, intent="flood_at_place", matched_place=place.name,
        reports=[report_to_out(r) for r in reports],
        cameras=[camera_to_out(c, (place.lat, place.lng)) for c in cameras],
    )


def answer_near_me(db: Session, lat: float | None, lng: float | None,
                   lang: str = "th") -> ChatResult:
    if lat is None or lng is None:
        return ChatResult(
            answer=(en.tr("near.noLocation") if lang == "en" else
                    "ผมยังไม่ทราบตำแหน่งของคุณครับ กดปุ่ม \"ใช้ตำแหน่งของฉัน\" "
                    "ที่มุมแผนที่เพื่ออนุญาตการเข้าถึงตำแหน่ง หรือพิมพ์ชื่อถนน/เขต/จังหวัด "
                    "มาก็ได้ เช่น \"น้ำท่วมแถวรามคำแหงไหม\""),
            intent="need_location",
        )

    reports = reports_near(db, lat, lng, radius_km=5.0)
    cameras = cameras_near(db, lat, lng, radius_km=10.0, limit=4)

    if not reports:
        if lang == "en":
            answer = en.tr("near.none")
            if cameras:
                answer += en.tr("near.cameras", count=len(cameras))
        else:
            answer = ("รอบตัวคุณในรัศมี 5 กม. ยังไม่มีรายงานน้ำท่วมที่ยืนยันแล้วครับ\n\n"
                      "ถ้าคุณเห็นน้ำท่วมตรงหน้า ช่วยกดแจ้งเหตุให้คนอื่นรู้ด้วยนะครับ")
            if cameras:
                answer += f"\n\nมีกล้อง CCTV ใกล้คุณ {len(cameras)} ตัว ดูภาพสดได้จากรายการด้านล่าง"
    else:
        worst = worst_level([r.level for r in reports])
        if lang == "en":
            answer = (en.tr("near.some", count=len(reports), worst=en.level(worst))
                      + _report_lines(reports, lang) + _safety_note(lang))
        else:
            answer = (f"ในรัศมี 5 กม. จากตำแหน่งคุณ มีน้ำท่วม {len(reports)} จุด "
                      f"หนักสุด {LEVEL_TH.get(worst, worst)}\n\n"
                      f"{_report_lines(reports)}{SAFETY_NOTE}")

    return ChatResult(
        answer=answer, intent="flood_near_me",
        reports=[report_to_out(r) for r in reports],
        cameras=[camera_to_out(c, (lat, lng), nearby_flood_level(db, c.lat, c.lng))
                 for c in cameras],
    )


def answer_worst(db: Session, lang: str = "th") -> ChatResult:
    rows = db.execute(_active_query().limit(200)).scalars().all()
    if not rows:
        return ChatResult(
            answer=(en.tr("worst.none") if lang == "en" else
                    "ตอนนี้ไม่มีรายงานน้ำท่วมที่ยืนยันแล้วในระบบเลยครับ — "
                    "ถือเป็นข่าวดี แต่ถ้าคุณเจอจุดน้ำท่วม ช่วยแจ้งเข้ามาได้เลย"),
            intent="worst_areas",
        )
    rows.sort(key=lambda r: (-LEVEL_RANK.get(r.level, 0), -r.confirm_count))
    top = rows[:8]
    by_province: dict[str, int] = {}
    for r in rows:
        key = r.province.name_th if r.province else "ไม่ระบุจังหวัด"
        by_province[key] = by_province.get(key, 0) + 1
    ranked = sorted(by_province.items(), key=lambda kv: -kv[1])[:5]
    if lang == "en":
        province_line = ", ".join(en.tr("line.province", name=name, count=count)
                                  for name, count in ranked)
        answer = en.tr("worst.body", count=len(rows),
                       lines=_report_lines(top, lang),
                       provinces=province_line) + _safety_note(lang)
    else:
        province_line = ", ".join(f"{name} {count} จุด" for name, count in ranked)
        answer = (f"ตอนนี้มีน้ำท่วมที่ยืนยันแล้วรวม {len(rows)} จุด\n\n"
                  f"จุดที่หนักที่สุด:\n{_report_lines(top)}\n\n"
                  f"จังหวัดที่มีรายงานมากที่สุด: {province_line}{SAFETY_NOTE}")
    return ChatResult(answer=answer, intent="worst_areas",
                      reports=[report_to_out(r) for r in top])


def answer_cameras(db: Session, place: PlaceMatch | None, lat: float | None,
                   lng: float | None, lang: str = "th") -> ChatResult:
    origin = None
    scope = en.tr("scope.country") if lang == "en" else "ทั่วประเทศ"
    if place and place.lat is not None:
        origin, scope = (place.lat, place.lng), place.name
    elif lat is not None and lng is not None:
        origin, scope = (lat, lng), (en.tr("scope.you") if lang == "en"
                                     else "ตำแหน่งของคุณ")

    if origin:
        cams = cameras_near(db, origin[0], origin[1], radius_km=25.0, limit=6)
    else:
        cams = db.execute(
            select(Camera).where(Camera.is_active.is_(True)).limit(6)
        ).scalars().all()

    if not cams:
        total = db.execute(
            select(func.count(Camera.id)).where(Camera.is_active.is_(True))
        ).scalar() or 0
        answer = (en.tr("cams.none", scope=scope, total=total) if lang == "en" else
                  f"ยังไม่มีกล้อง CCTV ที่ลงทะเบียนไว้ใกล้ {scope} ครับ "
                  f"(ทั้งระบบมี {total} ตัว)\n\n"
                  "ถ้าคุณทราบ URL กล้องในพื้นที่ แจ้งผู้ดูแลระบบให้เพิ่มเข้ามาได้")
        return ChatResult(answer=answer, intent="cameras", matched_place=scope)

    lines = []
    for c in cams:
        dist = f" ({haversine_km(origin[0], origin[1], c.lat, c.lng):.1f} กม.)" if origin else ""
        demo = ((en.tr("line.demo") if lang == "en" else " [สตรีมตัวอย่าง]")
                if c.is_demo else "")
        org = f" — {c.owner_org}" if c.owner_org else ""
        lines.append(f"• {c.name}{dist}{org}{demo}")

    if lang == "en":
        answer = en.tr("cams.body", count=len(cams), scope=scope,
                       lines="\n".join(lines))
    else:
        answer = (f"กล้อง CCTV ใกล้ {scope} ที่ดูได้ตอนนี้ {len(cams)} ตัว:\n"
                  + "\n".join(lines)
                  + "\n\nกดที่ชื่อกล้องด้านล่างเพื่อเปิดภาพสดครับ")
    return ChatResult(
        answer=answer, intent="cameras", matched_place=scope,
        cameras=[camera_to_out(c, origin, nearby_flood_level(db, c.lat, c.lng)) for c in cams],
    )


def answer_howto() -> ChatResult:
    return ChatResult(intent="how_to_report", answer=(
        "วิธีแจ้งน้ำท่วม:\n"
        "1. กดปุ่มสีส้ม \"แจ้งน้ำท่วม\" ที่มุมล่างขวาของแผนที่\n"
        "2. ระบบจะดึงตำแหน่ง GPS ให้ หรือคุณลากหมุดบนแผนที่เองก็ได้\n"
        "3. เลือกระดับน้ำ (มีรูปเทียบให้ดู) ใส่ความลึกเป็นเซนติเมตรถ้าพอประมาณได้\n"
        "4. แนบรูปถ่าย (ช่วยให้ผู้ตรวจอนุมัติเร็วขึ้นมาก)\n"
        "5. กดส่ง\n\n"
        "รายงานจะขึ้นแผนที่หลังผู้ตรวจอนุมัติ ปกติไม่เกิน 15 นาที "
        "ถ้าคุณเป็นเจ้าหน้าที่ อบต./เทศบาล ขอบัญชีเจ้าหน้าที่ได้ "
        "รายงานจะขึ้นทันทีไม่ต้องรออนุมัติ"
    ))


def answer_safety(text: str) -> ChatResult:
    match = DEPTH_PAT.search(text)
    depth = None
    if match:
        depth = int(match.group(1))
        if match.group(2) in ("เมตร", "ม."):
            depth *= 100

    if depth is None:
        body = ("เกณฑ์ตัดสินใจเรื่องขับรถลุยน้ำ:\n"
                "• ไม่เกิน 10 ซม. — ผ่านได้ ขับช้า ๆ\n"
                "• 10-30 ซม. — รถเก๋งผ่านได้ ใช้เกียร์ต่ำ รอบเครื่องคงที่ ห้ามเหยียบคันเร่งกระชาก\n"
                "• 30-60 ซม. — น้ำถึงระดับท่อไอเสียและกรองอากาศ รถเก๋งเสี่ยงเครื่องดับ "
                "ซ่อมหลักหมื่นถึงหลักแสน ไม่ควรเสี่ยง\n"
                "• เกิน 60 ซม. — ห้ามผ่านทุกกรณี แม้กระบะยกสูง\n\n"
                "ถ้าน้ำไหลเชี่ยว ให้ลดตัวเลขทั้งหมดลงครึ่งหนึ่ง น้ำไหลแรงแค่ 15 ซม. "
                "ก็พัดคนล้มและดันรถเบา ๆ ให้ลอยได้")
    elif depth <= 10:
        body = f"น้ำ {depth} ซม. ผ่านได้ครับ ขับช้า ๆ ระวังฝาท่อหลุดและหลุมที่มองไม่เห็น"
    elif depth <= 30:
        body = (f"น้ำ {depth} ซม. รถเก๋งยังผ่านได้ แต่ให้ใช้เกียร์ต่ำ (L หรือ 1-2) "
                "เลี้ยงรอบเครื่องให้คงที่ ห้ามหยุดกลางน้ำ และเว้นระยะจากรถคันหน้าเพื่อไม่ให้คลื่นน้ำซัดเข้าห้องเครื่อง")
    elif depth <= 60:
        body = (f"น้ำ {depth} ซม. เสี่ยงสูงครับ ระดับนี้น้ำถึงกรองอากาศของรถเก๋งทั่วไป "
                "ถ้าน้ำเข้าห้องเครื่องขณะเครื่องทำงานจะเกิด water hammer ก้านสูบงอ "
                "ค่าซ่อมหลักหมื่นถึงหลักแสน แนะนำให้เลี่ยงเส้นทาง")
    else:
        body = (f"น้ำ {depth} ซม. ห้ามผ่านครับ ระดับนี้เกินความสามารถของรถทุกประเภทที่ไม่ใช่รถทหาร "
                "และรถเก๋งจะเริ่มลอยเมื่อน้ำสูงประมาณ 60-70 ซม. ให้หาทางเลี่ยงหรือรอน้ำลด")

    return ChatResult(answer=body, intent="safety_advice")


def answer_stats(db: Session) -> ChatResult:
    active = db.execute(
        select(func.count(FloodReport.id))
        .where(FloodReport.status == ReportStatus.approved.value)
    ).scalar() or 0
    provinces = db.execute(
        select(func.count(func.distinct(FloodReport.province_id)))
        .where(FloodReport.status == ReportStatus.approved.value)
    ).scalar() or 0
    cams = db.execute(
        select(func.count(Camera.id)).where(Camera.is_active.is_(True))
    ).scalar() or 0
    by_level = db.execute(
        select(FloodReport.level, func.count(FloodReport.id))
        .where(FloodReport.status == ReportStatus.approved.value)
        .group_by(FloodReport.level)
    ).all()
    level_line = ", ".join(f"{LEVEL_TH.get(lv, lv)}: {n} จุด" for lv, n in
                           sorted(by_level, key=lambda kv: -LEVEL_RANK.get(kv[0], 0))) or "ไม่มี"
    return ChatResult(intent="stats", answer=(
        f"สรุปสถานการณ์ตอนนี้:\n"
        f"• จุดน้ำท่วมที่ยืนยันแล้ว: {active} จุด\n"
        f"• จังหวัดที่ได้รับผลกระทบ: {provinces} จังหวัด\n"
        f"• กล้อง CCTV ที่ดูได้: {cams} ตัว\n"
        f"• แยกตามระดับ — {level_line}"
    ))


def answer_help() -> ChatResult:
    return ChatResult(intent="help", answer=(
        "ผมช่วยเรื่องน้ำท่วมได้ 6 อย่างครับ:\n"
        "1. เช็คเส้นทาง (ที่คนใช้มากที่สุด) — \"จากบางนาไปรามคำแหง ท่วมไหม\" "
        "ผมจะไล่ดูทั้งเส้นทางว่ามีจุดน้ำท่วมกี่จุด อยู่กิโลเมตรที่เท่าไหร่ "
        "รถเก๋งผ่านได้หรือไม่ และมีกล้อง CCTV ตัวไหนให้เปิดดูก่อนออกรถ\n"
        "2. เช็คจุดเดียว — พิมพ์ชื่อถนน เขต หรือจังหวัด เช่น \"น้ำท่วมแถวรามคำแหงไหม\"\n"
        "3. เช็คใกล้ตัว — \"น้ำท่วมใกล้ฉันไหม\" (ต้องอนุญาตตำแหน่ง)\n"
        "4. หากล้อง CCTV — \"ขอดูกล้องแถวลาดพร้าว\"\n"
        "5. ดูภาพรวม — \"ตอนนี้ท่วมหนักที่ไหน\" หรือ \"สรุปสถิติ\"\n"
        "6. ถามเรื่องความปลอดภัย — \"น้ำ 40 ซม. ขับผ่านได้ไหม\"\n\n"
        "และถ้าคุณเจอน้ำท่วมเอง ถามผมว่า \"แจ้งน้ำท่วมยังไง\" ได้เลย"
    ))


def answer_fallback(db: Session) -> ChatResult:
    total = db.execute(
        select(func.count(FloodReport.id))
        .where(FloodReport.status == ReportStatus.approved.value)
    ).scalar() or 0
    return ChatResult(intent="fallback", answer=(
        "ผมไม่แน่ใจว่าคุณหมายถึงพื้นที่ไหนครับ ลองพิมพ์ชื่อถนน เขต หรือจังหวัด "
        "ให้ชัดขึ้น เช่น \"น้ำท่วมลาดพร้าวไหม\" หรือ \"สถานการณ์จังหวัดอยุธยา\"\n\n"
        f"ตอนนี้ระบบมีจุดน้ำท่วมที่ยืนยันแล้ว {total} จุด "
        "พิมพ์ \"ท่วมหนักที่ไหน\" เพื่อดูจุดที่หนักที่สุดได้"
    ))


# ------------------------------------------------------------------ dispatch

# The intents that have English wording. Anything else answers in Thai, and
# says so rather than leaving an English reader to guess whether the assistant
# broke or simply switched languages.
TRANSLATED_INTENTS = frozenset({
    "flood_at_place", "flood_near_me", "worst_areas", "cameras",
    "need_location", "route_need_endpoints", "route_unresolved", "route",
})


def mark_untranslated(result: ChatResult, lang: str) -> ChatResult:
    if lang == "en" and result.intent not in TRANSLATED_INTENTS:
        result.answer = result.answer + en.NOT_TRANSLATED
    return result


def route(db: Session, text: str, lat: float | None, lng: float | None,
          lang: str = "th") -> ChatResult:
    """Pick an intent. Order matters — the most specific pattern wins.

    `lang` reaches only the four answers that have been translated. Everything
    else replies in Thai and is marked, by `_mark_untranslated` below, so an
    English reader is told rather than left to wonder why the assistant
    switched languages mid-conversation.
    """
    raw = text.strip()
    cleaned = normalize(raw)

    if HELP_PAT.search(cleaned):
        return mark_untranslated(answer_help(), lang)
    if HOWTO_PAT.search(cleaned):
        return mark_untranslated(answer_howto(), lang)
    # Safety is checked before the route hint: "ผ่านได้ไหม" appears in both, and
    # a question carrying a depth in centimetres is asking about the water, not
    # about a trip.
    if SAFETY_PAT.search(cleaned) or (DEPTH_PAT.search(cleaned) and "ท่วม" not in cleaned):
        return mark_untranslated(answer_safety(cleaned), lang)
    # Route questions are resolved by the caller (they need async geocoding), so
    # reaching here with a trip-shaped sentence means the endpoints were missing
    # or unresolvable.
    if ROUTE_HINT_PAT.search(cleaned) and extract_route_endpoints(raw) is None:
        return answer_route_needs_endpoints(lang)

    # A romanised place name never matches a Thai gazetteer on similarity, so
    # it is translated to Thai before the lookup rather than left to fuzzy
    # scoring -- which is what produced จังหวัดพังงา for "bang na".
    place = match_place(db, raw)
    if place is None:
        thai_name = en.to_thai_place(raw)
        if thai_name:
            place = match_place(db, thai_name)

    if CAMERA_PAT.search(cleaned):
        return answer_cameras(db, place, lat, lng, lang)
    if NEAR_ME_PAT.search(cleaned):
        return answer_near_me(db, lat, lng, lang)
    if WORST_PAT.search(cleaned) and place is None:
        return answer_worst(db, lang)
    if STATS_PAT.search(cleaned) and place is None:
        return mark_untranslated(answer_stats(db), lang)
    if place is not None:
        return answer_flood_at_place(db, place, lang)
    if GREETING_PAT.search(cleaned):
        return mark_untranslated(answer_help(), lang)
    if "ท่วม" in cleaned or "น้ำ" in cleaned:
        # ถามเรื่องน้ำท่วมแต่ไม่ระบุที่ — ถ้ารู้ตำแหน่งก็ตอบรอบตัว ไม่รู้ก็สรุปภาพรวม
        if lat is not None and lng is not None:
            return answer_near_me(db, lat, lng, lang)
        return answer_worst(db, lang)
    return mark_untranslated(answer_fallback(db), lang)


# ------------------------------------------------------------------ optional LLM polish

LLM_SYSTEM = (
    "คุณคือผู้ช่วยแจ้งเตือนน้ำท่วมของเว็บ FloodWatch TH ตอบเป็นภาษาไทย สุภาพ กระชับ "
    "สำคัญที่สุด: ใช้ได้เฉพาะข้อเท็จจริงใน DATA ที่ให้มาเท่านั้น "
    "ห้ามเพิ่มชื่อถนน ตัวเลขความลึก หรือสถานะน้ำท่วมที่ไม่มีใน DATA "
    "ถ้า DATA บอกว่าไม่มีรายงาน ให้ย้ำว่าหมายถึงยังไม่มีคนแจ้ง ไม่ใช่ยืนยันว่าไม่ท่วม "
    "ห้ามละข้อความเตือนความปลอดภัยที่มีอยู่แล้ว"
)


async def polish_with_llm(question: str, rule_answer: str) -> str | None:
    """Rephrase the rule answer. Never a source of new facts.

    Any failure returns None and the caller keeps the deterministic answer, so a
    dead API key or an empty credit balance cannot take the chatbot down.
    """
    if not settings.chat_llm_enabled or not settings.anthropic_api_key:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.chat_llm_model,
                    "max_tokens": 700,
                    "system": LLM_SYSTEM,
                    "messages": [{
                        "role": "user",
                        "content": (f"คำถามผู้ใช้: {question}\n\n"
                                    f"DATA (คำตอบที่ระบบสร้างจากฐานข้อมูล):\n{rule_answer}\n\n"
                                    "เรียบเรียงคำตอบนี้ให้อ่านง่ายและเป็นธรรมชาติขึ้น "
                                    "โดยคงข้อเท็จจริงและคำเตือนไว้ทุกข้อ"),
                    }],
                },
            )
        if resp.status_code != 200:
            return None
        blocks = resp.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        return text or None
    except Exception:
        return None
