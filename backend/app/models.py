"""Database schema.

The level vocabulary is a fixed enum on purpose: a reporter picks a bucket
instead of guessing centimetres, and every consumer (map colour, chatbot,
stats) reads the same value. depth_cm is optional extra precision.
"""
import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .config import settings
from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"


class FloodLevel(str, enum.Enum):
    normal = "normal"      # สัญจรได้ปกติ / น้ำลดแล้ว
    puddle = "puddle"      # น้ำขังผิวถนน ไม่เกิน 10 ซม.
    shallow = "shallow"    # 10-30 ซม. รถเก๋งผ่านได้ ระวัง
    deep = "deep"          # 30-60 ซม. รถเก๋งเสี่ยงเครื่องดับ
    severe = "severe"      # เกิน 60 ซม. ผ่านไม่ได้
    closed = "closed"      # ปิดการจราจร / ทางการสั่งห้ามผ่าน


LEVEL_TH = {
    "normal": "สัญจรได้ปกติ",
    "puddle": "น้ำขังผิวถนน ไม่เกิน 10 ซม.",
    "shallow": "น้ำท่วม 10-30 ซม. รถเก๋งผ่านได้ ระวัง",
    "deep": "น้ำท่วม 30-60 ซม. รถเก๋งเสี่ยงเครื่องดับ",
    "severe": "น้ำท่วมเกิน 60 ซม. ผ่านไม่ได้",
    "closed": "ปิดการจราจร",
}

LEVEL_RANK = {
    "normal": 0, "puddle": 1, "shallow": 2, "deep": 3, "severe": 4, "closed": 5,
}

# ช่วงความลึกที่ใช้เดาระดับจากตัวเลข ซม. ที่ผู้แจ้งกรอก
DEPTH_TO_LEVEL = ((0, "normal"), (10, "puddle"), (30, "shallow"), (60, "deep"), (10_000, "severe"))


def level_from_depth(depth_cm: int) -> str:
    for ceiling, level in DEPTH_TO_LEVEL:
        if depth_cm <= ceiling:
            return level
    return "severe"


class ReportStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ReportSource(str, enum.Enum):
    user = "user"          # แจ้งโดยประชาชน
    official = "official"  # เจ้าหน้าที่ / อบต. / เทศบาล
    cctv = "cctv"          # ยืนยันจากภาพกล้อง


class StreamType(str, enum.Enum):
    hls = "hls"            # .m3u8 เล่นด้วย hls.js
    mjpeg = "mjpeg"        # multipart stream ใส่ใน img ได้เลย
    snapshot = "snapshot"  # ภาพนิ่ง refresh เป็นรอบ (กล้องราชการไทยส่วนใหญ่)
    youtube = "youtube"    # YouTube Live
    iframe = "iframe"      # หน้าเว็บผู้ให้บริการ embed ตรง


class User(Base):
    __tablename__ = "users"
    id = Column(String(32), primary_key=True, default=new_id)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True)
    display_name = Column(String(128))
    phone = Column(String(32))
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False, default="user")
    org = Column(String(128))          # หน่วยงาน สำหรับบัญชีเจ้าหน้าที่
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Area(Base):
    """จังหวัด และเขต/อำเภอ ใช้ทั้งกรองแผนที่และให้แชทบ็อทจับชื่อสถานที่."""

    __tablename__ = "areas"
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False, default="province")  # province | district
    code = Column(String(16), index=True)
    name_th = Column(String(128), nullable=False, index=True)
    name_en = Column(String(128))
    parent_id = Column(Integer, ForeignKey("areas.id"))
    lat = Column(Float)
    lng = Column(Float)

    parent = relationship("Area", remote_side=[id])

    __table_args__ = (UniqueConstraint("kind", "name_th", "parent_id", name="uq_area_name"),)


class FloodReport(Base):
    __tablename__ = "flood_reports"
    id = Column(String(32), primary_key=True, default=new_id)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    province_id = Column(Integer, ForeignKey("areas.id"), index=True)
    district = Column(String(128))
    place = Column(String(255))          # ถนน / แยก / จุดสังเกต
    level = Column(String(16), nullable=False, default="shallow")
    depth_cm = Column(Integer)
    passable = Column(Boolean)           # รถเก๋งผ่านได้หรือไม่ ตามที่ผู้แจ้งตอบ
    description = Column(Text)
    photo_url = Column(String(512))
    source = Column(String(16), nullable=False, default="user")
    status = Column(String(16), nullable=False, default="pending", index=True)

    reporter_id = Column(String(32), ForeignKey("users.id"))
    reporter_name = Column(String(128))  # ชื่อที่ผู้แจ้งกรอกเอง กรณีไม่ล็อกอิน
    reporter_ip = Column(String(64))     # สำหรับ rate limit และสืบกรณีสแปม

    confirm_count = Column(Integer, nullable=False, default=0)
    dispute_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

    moderated_by = Column(String(32), ForeignKey("users.id"))
    moderated_at = Column(DateTime(timezone=True))
    moderation_note = Column(Text)
    camera_id = Column(String(32), ForeignKey("cameras.id"))  # ถ้ายืนยันจากกล้อง

    reporter = relationship("User", foreign_keys=[reporter_id])
    moderator = relationship("User", foreign_keys=[moderated_by])
    province = relationship("Area")
    camera = relationship("Camera")
    votes = relationship("ReportVote", back_populates="report", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_reports_status_created", "status", "created_at"),)

    @staticmethod
    def default_expiry(from_time: datetime | None = None) -> datetime:
        return (from_time or utcnow()) + timedelta(hours=settings.report_ttl_hours)


class ReportVote(Base):
    """ยืนยัน/แย้ง หนึ่งเสียงต่อหนึ่งผู้ใช้ (หรือหนึ่ง IP) ต่อหนึ่งรายงาน."""

    __tablename__ = "report_votes"
    id = Column(String(32), primary_key=True, default=new_id)
    report_id = Column(String(32), ForeignKey("flood_reports.id", ondelete="CASCADE"),
                       nullable=False)
    voter_key = Column(String(80), nullable=False)   # user id หรือ ip:<addr>
    vote = Column(String(12), nullable=False)        # confirm | dispute
    level = Column(String(16))                       # ระดับที่ผู้ยืนยันเห็น ถ้าระบุ
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    report = relationship("FloodReport", back_populates="votes")

    __table_args__ = (UniqueConstraint("report_id", "voter_key", name="uq_vote_once"),)


class Camera(Base):
    __tablename__ = "cameras"
    id = Column(String(32), primary_key=True, default=new_id)
    name = Column(String(255), nullable=False)
    province_id = Column(Integer, ForeignKey("areas.id"), index=True)
    district = Column(String(128))
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    stream_type = Column(String(16), nullable=False, default="snapshot")
    stream_url = Column(String(1024), nullable=False)
    refresh_sec = Column(Integer, nullable=False, default=15)   # ใช้กับ snapshot
    owner_org = Column(String(128))     # กทม. / กรมทางหลวง / อบต. ...
    source_page = Column(String(1024))  # หน้าเว็บต้นทาง สำหรับให้เครดิต
    notes = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    is_demo = Column(Boolean, nullable=False, default=False)  # สตรีมตัวอย่าง ไม่ใช่ภาพจริง
    health = Column(String(16), nullable=False, default="unknown")  # online|offline|stale|unknown
    last_checked = Column(DateTime(timezone=True))
    # เวลาของ "ภาพ" ล่าสุดที่ปลายทางบอกมา (Last-Modified) ไม่ใช่เวลาที่เราไปดึง
    # กล้องราชการหลายตัวยังตอบ HTTP 200 ทั้งที่ภาพค้างมาเป็นเดือน
    last_frame_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    province = relationship("Area")


class ChatLog(Base):
    __tablename__ = "chat_logs"
    id = Column(String(32), primary_key=True, default=new_id)
    session_id = Column(String(64), index=True)
    user_id = Column(String(32), ForeignKey("users.id"))
    question = Column(Text, nullable=False)
    answer = Column(Text)
    intent = Column(String(48))
    matched_place = Column(String(128))
    engine = Column(String(16), default="rules")   # rules | llm
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String(32), primary_key=True, default=new_id)
    actor_id = Column(String(32), ForeignKey("users.id"))
    actor_name = Column(String(128))
    action = Column(String(48), nullable=False)
    entity = Column(String(32))
    entity_id = Column(String(48))
    detail = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

# ระดับสถานการณ์ของสถานีโทรมาตร ตามที่ thaiwater กำหนด (1 = น้ำน้อยวิกฤต ... 5 = ล้นตลิ่ง)
STATION_SITUATION_TH = {
    1: "น้ำน้อยวิกฤต",
    2: "น้ำน้อย",
    3: "ปกติ",
    4: "เฝ้าระวัง น้ำมาก",
    5: "วิกฤต น้ำล้นตลิ่ง",
}


class WaterStation(Base):
    """สถานีวัดระดับน้ำในคลอง/แม่น้ำ ซิงก์มาจากคลังข้อมูลน้ำแห่งชาติ.

    แยกจาก FloodReport โดยตั้งใจ: คลองล้นตลิ่งไม่ได้แปลว่าถนนท่วมทันที
    แต่เป็นสัญญาณเตือนล่วงหน้าที่วัดด้วยเครื่องมือ ไม่ใช่ความเห็นของคน
    จึงแสดงเป็นชั้นข้อมูลของตัวเอง และใช้ประกอบคำตัดสินเส้นทาง
    """

    __tablename__ = "water_stations"
    id = Column(String(32), primary_key=True, default=new_id)
    # รหัสสถานีจากต้นทาง ใช้ upsert ไม่ให้ซ้ำเวลาซิงก์รอบถัดไป
    source = Column(String(32), nullable=False, default="thaiwater")
    external_id = Column(String(64), nullable=False)

    name = Column(String(255), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    province_name = Column(String(128), index=True)
    amphoe_name = Column(String(128))
    agency = Column(String(128))
    basin_name = Column(String(128))

    water_level_msl = Column(Float)      # ระดับน้ำ (ม.รทก.)
    bank_level = Column(Float)           # ระดับตลิ่งต่ำสุด
    diff_from_bank = Column(Float)       # ต่างจากตลิ่ง บวก = ล้น
    is_overflowing = Column(Boolean, nullable=False, default=False)
    situation_level = Column(Integer)    # 1-5
    status_text = Column(String(128))

    measured_at = Column(DateTime(timezone=True), index=True)
    synced_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_station_source_ref"),
        Index("ix_station_bbox", "lat", "lng"),
    )
