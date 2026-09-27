"""Remove seeded demo content so only real data remains.

Run this once before opening the app to the public, and set SEED_DEMO_DATA=false
so the seeder does not put it back on the next boot.

Demo content is dangerous in a live flood app for one specific reason: a sample
camera sits on a real junction and a sample report names a real road, so a
person checking whether to drive can act on something that was never measured.

    python purge_demo.py            # show what would be removed
    python purge_demo.py --apply    # remove it

Gauge stations are never touched — they are synced from the agencies and are
always real.
"""
import sys

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import Camera, FloodReport, ReportStatus, WaterStation, utcnow

# Everything the seeder writes carries one of these markers.
DEMO_REPORTER = "ข้อมูลสาธิต"
DEMO_MARKER = "[ข้อมูลสาธิต]"


def find_demo(db):
    cameras = db.execute(select(Camera).where(Camera.is_demo.is_(True))).scalars().all()
    reports = db.execute(
        select(FloodReport).where(
            or_(
                FloodReport.reporter_name == DEMO_REPORTER,
                FloodReport.description.like(f"%{DEMO_MARKER}%"),
            )
        )
    ).scalars().all()
    return cameras, reports


def main() -> int:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        cameras, reports = find_demo(db)
        stations = db.execute(select(WaterStation)).scalars().all()

        print(f"กล้องสาธิต   : {len(cameras)}")
        for camera in cameras:
            print(f"   - {camera.name}")
        print(f"รายงานสาธิต  : {len(reports)}")
        for report in reports:
            print(f"   - {report.place or '(ไม่ระบุจุด)'}")
        print(f"สถานีวัดน้ำ   : {len(stations)} (ข้อมูลจริง — ไม่แตะต้อง)")

        if not cameras and not reports:
            print("\nไม่มีข้อมูลสาธิตเหลืออยู่แล้ว")
            return 0

        if not apply:
            print("\nนี่เป็นการแสดงผลอย่างเดียว — รันซ้ำด้วย --apply เพื่อลบจริง")
            return 0

        for camera in cameras:
            db.delete(camera)
        # Reports are withdrawn rather than deleted so any votes and audit
        # entries that reference them survive, matching how the app treats a
        # report a moderator rejects.
        for report in reports:
            report.status = ReportStatus.rejected.value
            report.moderation_note = "ลบข้อมูลสาธิตก่อนเปิดใช้งานจริง"
            report.moderated_at = utcnow()
        db.commit()

        print(f"\nลบกล้องสาธิต {len(cameras)} ตัว และถอนรายงานสาธิต {len(reports)} รายการแล้ว")
        print("อย่าลืมตั้ง SEED_DEMO_DATA=false เพื่อไม่ให้ระบบสร้างกลับมาตอนรีสตาร์ต")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
