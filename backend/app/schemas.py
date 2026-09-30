"""Request/response models. Validation lives here so routers stay thin."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .geo import in_thailand
from .models import FloodLevel, ReportSource, ReportStatus, Role, StreamType


# Output-side level/status values come straight from a DB string column.
# Declaring them as plain str (documented here) keeps FastAPI's dump-then-
# revalidate cycle from handing the serializer a str where it expects an Enum.
# Allowed levels: normal | puddle | shallow | deep | severe | closed
LevelStr = str


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth

class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    role: str
    org: str | None
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminUserUpdateIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    org: str | None = Field(default=None, max_length=128)


# ---------------------------------------------------------------- areas

class AreaOut(ORMModel):
    id: int
    kind: str
    code: str | None
    name_th: str
    name_en: str | None
    parent_id: int | None
    lat: float | None
    lng: float | None


# ---------------------------------------------------------------- reports

class ReportIn(BaseModel):
    lat: float
    lng: float
    level: FloodLevel | None = None
    depth_cm: int | None = Field(default=None, ge=0, le=1000)
    passable: bool | None = None
    place: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=128)
    province_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)
    photo_url: str | None = Field(default=None, max_length=512)
    reporter_name: str | None = Field(default=None, max_length=128)

    @field_validator("lat")
    @classmethod
    def _lat_range(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("lat ต้องอยู่ระหว่าง -90 ถึง 90")
        return v

    @field_validator("lng")
    @classmethod
    def _lng_range(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("lng ต้องอยู่ระหว่าง -180 ถึง 180")
        return v

    def check_thailand(self) -> None:
        if not in_thailand(self.lat, self.lng):
            raise ValueError("พิกัดอยู่นอกประเทศไทย")


class ReportUpdateIn(BaseModel):
    level: FloodLevel | None = None
    depth_cm: int | None = Field(default=None, ge=0, le=1000)
    passable: bool | None = None
    place: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    photo_url: str | None = Field(default=None, max_length=512)


class ModerateIn(BaseModel):
    status: ReportStatus
    note: str | None = Field(default=None, max_length=1000)
    level: FloodLevel | None = None     # ให้ผู้ตรวจแก้ระดับตอนอนุมัติได้
    source: ReportSource | None = None  # ยกระดับเป็น official ได้


class VoteIn(BaseModel):
    vote: str = Field(pattern="^(confirm|dispute)$")
    level: FloodLevel | None = None


class ReportOut(ORMModel):
    id: str
    lat: float
    lng: float
    level: LevelStr
    level_label: str | None = None
    depth_cm: int | None
    passable: bool | None
    place: str | None
    district: str | None
    province_id: int | None
    province_name: str | None = None
    description: str | None
    photo_url: str | None
    source: str
    status: str
    reporter_name: str | None
    confirm_count: int
    dispute_count: int
    confidence: float | None = None
    age_minutes: int | None = None
    # On the map but never seen by a person. A flag rather than the moderation
    # note itself, because that field holds whatever a moderator typed and this
    # schema is what the public map endpoint returns.
    auto_approved: bool = False
    # On the map, but enough people have said the water has gone that a
    # moderator should look. Shown to readers as a caveat rather than hidden:
    # they are entitled to know the warning is contested.
    needs_review: bool = False
    camera_id: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class ReportListOut(BaseModel):
    total: int
    items: list[ReportOut]


# ---------------------------------------------------------------- cameras

class CameraIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    lat: float
    lng: float
    stream_type: StreamType = StreamType.snapshot
    stream_url: str = Field(min_length=8, max_length=1024)
    refresh_sec: int = Field(default=15, ge=3, le=600)
    province_id: int | None = None
    district: str | None = Field(default=None, max_length=128)
    owner_org: str | None = Field(default=None, max_length=128)
    source_page: str | None = Field(default=None, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    is_demo: bool = False

    @field_validator("stream_url", "source_page")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("URL ต้องเริ่มด้วย http:// หรือ https://")
        return v


class CameraUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    lat: float | None = None
    lng: float | None = None
    stream_type: StreamType | None = None
    stream_url: str | None = Field(default=None, min_length=8, max_length=1024)
    refresh_sec: int | None = Field(default=None, ge=3, le=600)
    province_id: int | None = None
    district: str | None = Field(default=None, max_length=128)
    owner_org: str | None = Field(default=None, max_length=128)
    source_page: str | None = Field(default=None, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    is_demo: bool | None = None


class CameraOut(ORMModel):
    id: str
    name: str
    lat: float
    lng: float
    stream_type: str
    stream_url: str
    refresh_sec: int
    province_id: int | None
    province_name: str | None = None
    district: str | None
    owner_org: str | None
    source_page: str | None
    notes: str | None
    is_active: bool
    is_demo: bool
    health: str
    last_checked: datetime | None
    last_frame_at: datetime | None = None
    frame_age_minutes: int | None = None
    distance_km: float | None = None
    nearby_flood_level: LevelStr | None = None


class WaterStationOut(ORMModel):
    id: str
    name: str
    lat: float
    lng: float
    province_name: str | None
    amphoe_name: str | None
    agency: str | None
    basin_name: str | None
    water_level_msl: float | None
    bank_level: float | None
    diff_from_bank: float | None
    is_overflowing: bool
    situation_level: int | None
    situation_label: str | None = None
    status_text: str | None
    measured_at: datetime | None
    is_stale: bool = False
    distance_km: float | None = None


# ---------------------------------------------------------------- route check

class LatLng(BaseModel):
    lat: float
    lng: float


class RouteCheckIn(BaseModel):
    """Either coordinates or a place name, per endpoint. Coordinates win."""

    origin: LatLng | None = None
    destination: LatLng | None = None
    origin_text: str | None = Field(default=None, max_length=200)
    destination_text: str | None = Field(default=None, max_length=200)
    corridor_m: int | None = Field(default=None, ge=30, le=2000)
    camera_corridor_m: int | None = Field(default=None, ge=50, le=5000)
    alternatives: bool = True

    def has_origin(self) -> bool:
        return self.origin is not None or bool(self.origin_text)

    def has_destination(self) -> bool:
        return self.destination is not None or bool(self.destination_text)


class ObstacleOut(BaseModel):
    along_km: float
    distance_from_route_m: int
    report: ReportOut


class RouteCameraOut(BaseModel):
    along_km: float
    distance_from_route_m: int
    camera: CameraOut


class RouteStationOut(BaseModel):
    along_km: float
    distance_from_route_m: int
    station: WaterStationOut


class RouteRoadOut(BaseModel):
    """A flooded stretch of road along the route, from Floodboard."""
    along_km: float
    name: str
    name_en: str = ""
    depth_cm: int | None = None
    closed: bool = False
    sedan: str
    motorbike: str
    conf: float
    confident: bool
    estimated: bool = False
    sources: list[str] = []
    updated: int | None = None
    level: str
    length_m: int = 0


class RouteLegOut(BaseModel):
    label: str
    distance_km: float
    duration_min: float
    is_straight_line: bool
    verdict: str
    verdict_label: str
    worst_level: LevelStr | None
    is_recommended: bool
    path: list[list[float]]
    obstacles: list[ObstacleOut]
    cameras: list[RouteCameraOut]
    stations: list[RouteStationOut] = []
    roads: list[RouteRoadOut] = []


class RouteCheckOut(BaseModel):
    origin: LatLng
    destination: LatLng
    origin_label: str | None = None
    destination_label: str | None = None
    verdict: str
    verdict_label: str
    worst_level: LevelStr | None
    advice: str
    recommendation: str | None
    degraded: str | None
    corridor_m: int
    routes: list[RouteLegOut]
    # Set whenever Floodboard road data is part of this answer (CC BY 4.0).
    roads_attribution: str | None = None
    # Weather heading for the route. Deliberately beside the verdict rather
    # than folded into it: rain is a reason to expect trouble, not evidence
    # that any particular road is under water, and roads drain at wildly
    # different rates. None when no key is configured.
    rain: dict | None = None


class GeocodeOut(BaseModel):
    lat: float
    lng: float
    label: str
    source: str


# ---------------------------------------------------------------- chat

class ChatRouteContext(BaseModel):
    """The route the reader is already looking at, as coordinates.

    Sent by the route panel's "ask about a detour" button. Labels such as
    "ตำแหน่งของฉัน" or "หมุด 13.69, 100.71" are what the reader sees for a GPS
    fix or a dropped pin; they are not place names, and putting them into a
    sentence for the assistant to re-parse is what made it answer "I am not
    sure where you mean". The coordinates are already known, so they are sent.
    """
    origin: LatLng
    destination: LatLng
    origin_label: str | None = Field(default=None, max_length=120)
    destination_label: str | None = Field(default=None, max_length=120)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    route: ChatRouteContext | None = None
    # Which language to answer in. Only the common questions have English
    # wording; the rest reply in Thai and say so.
    lang: str = Field(default="th", pattern="^(th|en)$")
    session_id: str | None = Field(default=None, max_length=64)
    lat: float | None = None
    lng: float | None = None


class ChatSuggestion(BaseModel):
    label: str
    message: str


class ChatOut(BaseModel):
    answer: str
    intent: str
    engine: str
    matched_place: str | None = None
    reports: list[ReportOut] = []
    cameras: list[CameraOut] = []
    suggestions: list[ChatSuggestion] = []
    # Populated when the question was a route question, so the UI can draw the
    # route straight from the chat answer.
    route: RouteCheckOut | None = None


# ---------------------------------------------------------------- stats

class ProvinceStat(BaseModel):
    province_id: int | None
    province_name: str
    total: int
    worst_level: LevelStr | None
    impassable: int


class SummaryOut(BaseModel):
    active_reports: int
    by_level: dict[str, int]
    pending_moderation: int
    provinces_affected: int
    cameras_total: int
    cameras_active: int
    reports_last_24h: int
    updated_at: datetime


class TimelinePoint(BaseModel):
    bucket: str
    total: int


class UploadOut(BaseModel):
    url: str
    width: int
    height: int
    bytes: int
    # Faces blurred automatically; None when the check could not run.
    faces_blurred: int | None = None
