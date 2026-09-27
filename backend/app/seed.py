"""First-run data: areas, the admin account, and optional demo content.

Idempotent — safe to run on every boot. Province centroids are approximate
(provincial city centre, not a polygon centroid); they are used to group reports
and to anchor chatbot place matches, not to draw boundaries.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Area, AuditLog, Camera, FloodReport, Role, User, utcnow,
)
from .security import hash_password, verify_password

logger = logging.getLogger("floodwatch.seed")

# (province code, ชื่อไทย, English, lat, lng)
PROVINCES: list[tuple[str, str, str, float, float]] = [
    ("10", "กรุงเทพมหานคร", "Bangkok", 13.7563, 100.5018),
    ("11", "สมุทรปราการ", "Samut Prakan", 13.5991, 100.5998),
    ("12", "นนทบุรี", "Nonthaburi", 13.8591, 100.5217),
    ("13", "ปทุมธานี", "Pathum Thani", 14.0208, 100.5250),
    ("14", "พระนครศรีอยุธยา", "Phra Nakhon Si Ayutthaya", 14.3532, 100.5689),
    ("15", "อ่างทอง", "Ang Thong", 14.5896, 100.4550),
    ("16", "ลพบุรี", "Lopburi", 14.7995, 100.6534),
    ("17", "สิงห์บุรี", "Sing Buri", 14.8907, 100.3968),
    ("18", "ชัยนาท", "Chai Nat", 15.1851, 100.1251),
    ("19", "สระบุรี", "Saraburi", 14.5289, 100.9101),
    ("20", "ชลบุรี", "Chon Buri", 13.3611, 100.9847),
    ("21", "ระยอง", "Rayong", 12.6814, 101.2816),
    ("22", "จันทบุรี", "Chanthaburi", 12.6113, 102.1039),
    ("23", "ตราด", "Trat", 12.2428, 102.5175),
    ("24", "ฉะเชิงเทรา", "Chachoengsao", 13.6904, 101.0779),
    ("25", "ปราจีนบุรี", "Prachin Buri", 14.0421, 101.3686),
    ("26", "นครนายก", "Nakhon Nayok", 14.2069, 101.2130),
    ("27", "สระแก้ว", "Sa Kaeo", 13.8240, 102.0645),
    ("30", "นครราชสีมา", "Nakhon Ratchasima", 14.9799, 102.0977),
    ("31", "บุรีรัมย์", "Buri Ram", 14.9930, 103.1029),
    ("32", "สุรินทร์", "Surin", 14.8818, 103.4936),
    ("33", "ศรีสะเกษ", "Si Sa Ket", 15.1186, 104.3220),
    ("34", "อุบลราชธานี", "Ubon Ratchathani", 15.2448, 104.8473),
    ("35", "ยโสธร", "Yasothon", 15.7921, 104.1452),
    ("36", "ชัยภูมิ", "Chaiyaphum", 15.8068, 102.0317),
    ("37", "อำนาจเจริญ", "Amnat Charoen", 15.8657, 104.6257),
    ("38", "บึงกาฬ", "Bueng Kan", 18.3609, 103.6465),
    ("39", "หนองบัวลำภู", "Nong Bua Lam Phu", 17.2042, 102.4260),
    ("40", "ขอนแก่น", "Khon Kaen", 16.4419, 102.8360),
    ("41", "อุดรธานี", "Udon Thani", 17.4138, 102.7870),
    ("42", "เลย", "Loei", 17.4860, 101.7223),
    ("43", "หนองคาย", "Nong Khai", 17.8783, 102.7420),
    ("44", "มหาสารคาม", "Maha Sarakham", 16.1851, 103.3029),
    ("45", "ร้อยเอ็ด", "Roi Et", 16.0538, 103.6520),
    ("46", "กาฬสินธุ์", "Kalasin", 16.4322, 103.5060),
    ("47", "สกลนคร", "Sakon Nakhon", 17.1664, 104.1486),
    ("48", "นครพนม", "Nakhon Phanom", 17.3910, 104.7690),
    ("49", "มุกดาหาร", "Mukdahan", 16.5420, 104.7024),
    ("50", "เชียงใหม่", "Chiang Mai", 18.7883, 98.9853),
    ("51", "ลำพูน", "Lamphun", 18.5744, 99.0087),
    ("52", "ลำปาง", "Lampang", 18.2888, 99.4909),
    ("53", "อุตรดิตถ์", "Uttaradit", 17.6200, 100.0993),
    ("54", "แพร่", "Phrae", 18.1446, 100.1405),
    ("55", "น่าน", "Nan", 18.7756, 100.7730),
    ("56", "พะเยา", "Phayao", 19.1664, 99.9003),
    ("57", "เชียงราย", "Chiang Rai", 19.9105, 99.8406),
    ("58", "แม่ฮ่องสอน", "Mae Hong Son", 19.3020, 97.9654),
    ("60", "นครสวรรค์", "Nakhon Sawan", 15.7047, 100.1372),
    ("61", "อุทัยธานี", "Uthai Thani", 15.3835, 100.0245),
    ("62", "กำแพงเพชร", "Kamphaeng Phet", 16.4828, 99.5221),
    ("63", "ตาก", "Tak", 16.8839, 99.1258),
    ("64", "สุโขทัย", "Sukhothai", 17.0068, 99.8265),
    ("65", "พิษณุโลก", "Phitsanulok", 16.8211, 100.2659),
    ("66", "พิจิตร", "Phichit", 16.4429, 100.3487),
    ("67", "เพชรบูรณ์", "Phetchabun", 16.4190, 101.1591),
    ("70", "ราชบุรี", "Ratchaburi", 13.5282, 99.8134),
    ("71", "กาญจนบุรี", "Kanchanaburi", 14.0227, 99.5328),
    ("72", "สุพรรณบุรี", "Suphan Buri", 14.4745, 100.1177),
    ("73", "นครปฐม", "Nakhon Pathom", 13.8199, 100.0621),
    ("74", "สมุทรสาคร", "Samut Sakhon", 13.5475, 100.2745),
    ("75", "สมุทรสงคราม", "Samut Songkhram", 13.4098, 100.0022),
    ("76", "เพชรบุรี", "Phetchaburi", 13.1119, 99.9399),
    ("77", "ประจวบคีรีขันธ์", "Prachuap Khiri Khan", 11.8126, 99.7957),
    ("80", "นครศรีธรรมราช", "Nakhon Si Thammarat", 8.4304, 99.9631),
    ("81", "กระบี่", "Krabi", 8.0863, 98.9063),
    ("82", "พังงา", "Phang Nga", 8.4501, 98.5255),
    ("83", "ภูเก็ต", "Phuket", 7.8804, 98.3923),
    ("84", "สุราษฎร์ธานี", "Surat Thani", 9.1382, 99.3215),
    ("85", "ระนอง", "Ranong", 9.9529, 98.6085),
    ("86", "ชุมพร", "Chumphon", 10.4930, 99.1800),
    ("90", "สงขลา", "Songkhla", 7.1756, 100.6142),
    ("91", "สตูล", "Satun", 6.6238, 100.0674),
    ("92", "ตรัง", "Trang", 7.5593, 99.6114),
    ("93", "พัทลุง", "Phatthalung", 7.6167, 100.0742),
    ("94", "ปัตตานี", "Pattani", 6.8692, 101.2550),
    ("95", "ยะลา", "Yala", 6.5410, 101.2803),
    ("96", "นราธิวาส", "Narathiwat", 6.4254, 101.8253),
]

# เขตกรุงเทพฯ ทั้ง 50 เขต — พื้นที่ที่มีปริมาณการใช้งานสูงสุด ใส่ไว้ให้แชทบอท
# จับชื่อได้ตั้งแต่วันแรก พิกัดเป็นจุดอ้างอิงกลางเขตโดยประมาณ
BANGKOK_DISTRICTS: list[tuple[str, float, float]] = [
    ("พระนคร", 13.7637, 100.4980), ("ดุสิต", 13.7778, 100.5203),
    ("หนองจอก", 13.8556, 100.8622), ("บางรัก", 13.7248, 100.5232),
    ("บางเขน", 13.8740, 100.5960), ("บางกะปิ", 13.7658, 100.6470),
    ("ปทุมวัน", 13.7448, 100.5220), ("ป้อมปราบศัตรูพ่าย", 13.7539, 100.5130),
    ("พระโขนง", 13.7030, 100.6020), ("มีนบุรี", 13.8140, 100.7480),
    ("ลาดกระบัง", 13.7220, 100.7860), ("ยานนาวา", 13.6970, 100.5430),
    ("สัมพันธวงศ์", 13.7400, 100.5130), ("พญาไท", 13.7800, 100.5420),
    ("ธนบุรี", 13.7250, 100.4870), ("บางกอกใหญ่", 13.7390, 100.4760),
    ("ห้วยขวาง", 13.7770, 100.5790), ("คลองสาน", 13.7300, 100.5100),
    ("ตลิ่งชัน", 13.7770, 100.4460), ("บางกอกน้อย", 13.7620, 100.4700),
    ("บางขุนเทียน", 13.6600, 100.4350), ("ภาษีเจริญ", 13.7150, 100.4370),
    ("หนองแขม", 13.7040, 100.3490), ("ราษฎร์บูรณะ", 13.6820, 100.5050),
    ("บางพลัด", 13.7940, 100.5050), ("ดินแดง", 13.7700, 100.5530),
    ("บึงกุ่ม", 13.7850, 100.6690), ("สาทร", 13.7180, 100.5290),
    ("บางซื่อ", 13.8100, 100.5270), ("จตุจักร", 13.8280, 100.5600),
    ("บางคอแหลม", 13.6930, 100.5020), ("ประเวศ", 13.7170, 100.6940),
    ("คลองเตย", 13.7080, 100.5840), ("สวนหลวง", 13.7300, 100.6470),
    ("จอมทอง", 13.6770, 100.4840), ("ดอนเมือง", 13.9120, 100.5930),
    ("ราชเทวี", 13.7590, 100.5340), ("ลาดพร้าว", 13.8200, 100.6060),
    ("วัฒนา", 13.7370, 100.5840), ("บางแค", 13.7160, 100.3990),
    ("หลักสี่", 13.8870, 100.5710), ("สายไหม", 13.9060, 100.6520),
    ("คันนายาว", 13.8250, 100.6780), ("สะพานสูง", 13.7690, 100.6860),
    ("วังทองหลาง", 13.7790, 100.6080), ("คลองสามวา", 13.8600, 100.7040),
    ("บางนา", 13.6800, 100.5880), ("ทวีวัฒนา", 13.7810, 100.3560),
    ("ทุ่งครุ", 13.6480, 100.5060), ("บางบอน", 13.6580, 100.3840),
]

# ถนนสายหลักและจุดสังเกตในกรุงเทพฯ — คนพิมพ์ชื่อพวกนี้มากกว่าชื่อเขต
# ("จากบางนาไปรามคำแหง" ไม่ใช่ "ไปเขตบางกะปิ") การมีไว้ในฐานข้อมูลทำให้
# ค้นเจอทันทีโดยไม่ต้องเรียก geocoder ภายนอก ซึ่งอาจถูกบล็อกหรือจำกัดโควตา
# พิกัดเป็นจุดอ้างอิงกลางถนนโดยประมาณ ถนนสายยาวจึงเป็นค่าประมาณเท่านั้น
BANGKOK_LANDMARKS: list[tuple[str, float, float]] = [
    ("รามคำแหง", 13.7550, 100.6200), ("สุขุมวิท", 13.7300, 100.5700),
    ("สีลม", 13.7250, 100.5300), ("พหลโยธิน", 13.8400, 100.5600),
    ("วิภาวดีรังสิต", 13.8600, 100.5700), ("รัชดาภิเษก", 13.7800, 100.5700),
    ("เพชรบุรี", 13.7500, 100.5400), ("พระราม 4", 13.7250, 100.5500),
    ("พระราม 9", 13.7580, 100.5650), ("พระราม 2", 13.6600, 100.4400),
    ("พระราม 3", 13.6900, 100.5400), ("บางนา-ตราด", 13.6700, 100.6100),
    ("ศรีนครินทร์", 13.7000, 100.6450), ("อ่อนนุช", 13.7050, 100.6100),
    ("เกษตร-นวมินทร์", 13.8300, 100.6200), ("แจ้งวัฒนะ", 13.8900, 100.5500),
    ("งามวงศ์วาน", 13.8500, 100.5300), ("ราชพฤกษ์", 13.7500, 100.4300),
    ("บรมราชชนนี", 13.7750, 100.4200), ("เพชรเกษม", 13.7100, 100.3800),
    ("กาญจนาภิเษก", 13.7700, 100.3900), ("นวมินทร์", 13.8100, 100.6500),
    ("เสรีไทย", 13.8000, 100.6700), ("รามอินทรา", 13.8500, 100.6400),
    ("ประชาอุทิศ", 13.6400, 100.5100), ("สาธุประดิษฐ์", 13.6900, 100.5300),
    ("เจริญกรุง", 13.7200, 100.5150), ("เยาวราช", 13.7400, 100.5100),
    ("ราชดำเนิน", 13.7600, 100.5000), ("จรัญสนิทวงศ์", 13.7700, 100.4700),
    ("ปิ่นเกล้า", 13.7750, 100.4750), ("ท่าพระ", 13.7300, 100.4750),
    ("ประชาชื่น", 13.8400, 100.5300), ("ติวานนท์", 13.8800, 100.5200),
    ("อนุสาวรีย์ชัยสมรภูมิ", 13.7650, 100.5380), ("สยามสแควร์", 13.7460, 100.5340),
    ("อโศก", 13.7370, 100.5600), ("ทองหล่อ", 13.7300, 100.5820),
    ("เอกมัย", 13.7200, 100.5850), ("พร้อมพงษ์", 13.7300, 100.5690),
    ("หมอชิต", 13.8020, 100.5540), ("สนามบินสุวรรณภูมิ", 13.6900, 100.7501),
    ("สนามบินดอนเมือง", 13.9126, 100.6070), ("ศาลายา", 13.7900, 100.3200),
]

# กล้องสาธิต — ใช้สตรีมทดสอบสาธารณะ ไม่ใช่ภาพจริงจากสถานที่นั้น
# is_demo=True ทำให้ UI ติดป้าย "สตรีมตัวอย่าง" ผู้ดูแลควรแทนที่ด้วย URL กล้องจริง
DEMO_HLS = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"

DEMO_CAMERAS = [
    ("แยกรามคำแหง (สาธิต)", "บางกะปิ", 13.7655, 100.6420, "กรุงเทพมหานคร"),
    ("ถนนลาดพร้าว ช่วงโชคชัย 4 (สาธิต)", "ลาดพร้าว", 13.8080, 100.5990, "กรุงเทพมหานคร"),
    ("ถนนสุขุมวิท ช่วงบางนา (สาธิต)", "บางนา", 13.6810, 100.5900, "กรุงเทพมหานคร"),
    ("ถนนพหลโยธิน ช่วงห้าแยกลาดพร้าว (สาธิต)", "จตุจักร", 13.8170, 100.5610, "กรุงเทพมหานคร"),
    ("ถนนเพชรบุรี ช่วงประตูน้ำ (สาธิต)", "ราชเทวี", 13.7510, 100.5390, "กรุงเทพมหานคร"),
    ("ถนนวิภาวดีรังสิต ขาออก (สาธิต)", "ดอนเมือง", 13.8900, 100.5880, "กรุงเทพมหานคร"),
    ("ถนนนิมมานเหมินท์ (สาธิต)", "เมืองเชียงใหม่", 18.7960, 98.9670, "เชียงใหม่"),
    ("ถนนมิตรภาพ ขาเข้าเมือง (สาธิต)", "เมืองขอนแก่น", 16.4380, 102.8300, "ขอนแก่น"),
]

# รายงานตัวอย่าง วางบนถนนจริงเพื่อให้ฟีเจอร์ตรวจเส้นทางมีอะไรให้เห็น
DEMO_REPORTS = [
    (13.7650, 100.6350, "shallow", 22, "แยกลำสาลี ขาเข้า", "บางกะปิ",
     "น้ำขังเลนซ้าย 2 เลน รถเก๋งผ่านได้แต่ต้องชิดขวา", True),
    (13.8060, 100.5960, "deep", 45, "ถนนลาดพร้าว ซอย 71", "วังทองหลาง",
     "น้ำท่วมหน้าปากซอย รถเก๋ง 2 คันดับคาที่", False),
    (13.7500, 100.5400, "puddle", 8, "ประตูน้ำ ฝั่งพันธุ์ทิพย์", "ราชเทวี",
     "น้ำขังเล็กน้อย ระบายทันแล้ว", True),
    (13.6820, 100.5900, "closed", 70, "ถนนสรรพาวุธ ใต้ทางด่วน", "บางนา",
     "เจ้าหน้าที่ปิดเส้นทาง ให้เลี่ยงไปใช้บางนา-ตราด", False),
]


def seed_areas(db: Session) -> None:
    existing = {
        (row.kind, row.name_th, row.parent_id)
        for row in db.execute(select(Area)).scalars()
    }

    for code, name_th, name_en, lat, lng in PROVINCES:
        if ("province", name_th, None) in existing:
            continue
        db.add(Area(kind="province", code=code, name_th=name_th, name_en=name_en,
                    lat=lat, lng=lng))
    db.commit()

    bangkok = db.execute(
        select(Area).where(Area.kind == "province", Area.name_th == "กรุงเทพมหานคร")
    ).scalar_one_or_none()
    if bangkok is None:
        return

    for name_th, lat, lng in BANGKOK_DISTRICTS:
        if ("district", name_th, bangkok.id) in existing:
            continue
        db.add(Area(kind="district", name_th=name_th, parent_id=bangkok.id, lat=lat, lng=lng))

    for name_th, lat, lng in BANGKOK_LANDMARKS:
        if ("landmark", name_th, bangkok.id) in existing:
            continue
        db.add(Area(kind="landmark", name_th=name_th, parent_id=bangkok.id, lat=lat, lng=lng))
    db.commit()


def _apply_password_reset(db: Session, admin: User) -> None:
    """Reset the admin password when ADMIN_PASSWORD_RESET is set.

    Only runs when the variable holds a value, so a normal restart never
    touches credentials. The operator is expected to clear it afterwards; the
    warning below says so, and the change is written to the audit log so a
    reset is never invisible.
    """
    new_password = (settings.admin_password_reset or "").strip()
    if not new_password:
        return
    if len(new_password) < 8:
        logger.warning("ADMIN_PASSWORD_RESET สั้นเกินไป (ต้อง 8 ตัวขึ้นไป) — ข้ามการรีเซ็ต")
        return
    if verify_password(new_password, admin.hashed_password):
        return  # already set; nothing to do and nothing to log

    admin.hashed_password = hash_password(new_password)
    admin.is_active = True
    db.add(AuditLog(actor_id=admin.id, actor_name=admin.username,
                    action="admin_password_reset", entity="user", entity_id=admin.id,
                    detail="รีเซ็ตผ่านตัวแปร ADMIN_PASSWORD_RESET ตอนบูต"))
    db.commit()
    logger.warning(
        "รีเซ็ตรหัสผ่านบัญชี %s แล้ว — ให้ลบตัวแปร ADMIN_PASSWORD_RESET ออกทันที "
        "ไม่เช่นนั้นรหัสจะค้างอยู่ในค่าตั้งของระบบ", admin.username)


def seed_admin(db: Session) -> User | None:
    admin = db.execute(
        select(User).where(func.lower(User.username) == settings.seed_admin_username.lower())
    ).scalar_one_or_none()
    if admin:
        _apply_password_reset(db, admin)
        return admin

    admin = User(
        username=settings.seed_admin_username,
        display_name="ผู้ดูแลระบบ",
        hashed_password=hash_password(settings.seed_admin_password),
        role=Role.admin.value,
        org="ผู้ดูแลระบบ FloodWatch TH",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _province_by_name(db: Session, name: str) -> Area | None:
    return db.execute(
        select(Area).where(Area.kind == "province", Area.name_th == name)
    ).scalar_one_or_none()


def seed_demo(db: Session, admin: User | None) -> None:
    if not settings.seed_demo_data:
        return

    if (db.execute(select(func.count(Camera.id))).scalar() or 0) == 0:
        for name, district, lat, lng, province_name in DEMO_CAMERAS:
            province = _province_by_name(db, province_name)
            db.add(Camera(
                name=name, district=district, lat=lat, lng=lng,
                province_id=province.id if province else None,
                stream_type="hls", stream_url=DEMO_HLS, refresh_sec=15,
                owner_org="ข้อมูลสาธิต",
                notes=("กล้องสาธิต: ตำแหน่งเป็นจุดจริงแต่ภาพเป็นสตรีมทดสอบสาธารณะ "
                       "ผู้ดูแลระบบควรแก้ stream_url เป็น URL กล้องจริงของหน่วยงาน"),
                is_demo=True, health="unknown",
            ))
        db.commit()

    if (db.execute(select(func.count(FloodReport.id))).scalar() or 0) == 0:
        bangkok = _province_by_name(db, "กรุงเทพมหานคร")
        for lat, lng, level, depth, place, district, note, passable in DEMO_REPORTS:
            db.add(FloodReport(
                lat=lat, lng=lng, level=level, depth_cm=depth, place=place, district=district,
                province_id=bangkok.id if bangkok else None,
                description=f"[ข้อมูลสาธิต] {note}",
                source="official", status="approved", passable=passable,
                reporter_id=admin.id if admin else None,
                reporter_name="ข้อมูลสาธิต",
                confirm_count=3, dispute_count=0,
                created_at=utcnow(), updated_at=utcnow(),
                expires_at=FloodReport.default_expiry(),
            ))
        db.commit()


def run_seed(db: Session) -> None:
    seed_areas(db)
    admin = seed_admin(db)
    seed_demo(db, admin)
