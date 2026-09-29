"""Break-glass admin password reset.

Without this a forgotten password locks the operator out of their own
deployment permanently, because the seeder deliberately never overwrites an
existing account.
"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
DB = f"{tmp}/t.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests
os.environ["SEED_ADMIN_PASSWORD"] = "original-pass-123"

from sqlalchemy import select
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import AuditLog, User
from app.seed import run_seed
from app.security import verify_password

fails = []
def check(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n      -> {extra}"))
    if not ok: fails.append(name)

def admin(db):
    return db.execute(select(User).where(User.username == "admin")).scalar_one()

Base.metadata.create_all(bind=engine)
db = SessionLocal(); run_seed(db)
check("สร้างบัญชี admin ตอน seed", verify_password("original-pass-123", admin(db).hashed_password))

# Changing SEED_ADMIN_PASSWORD must not touch an existing account.
settings.seed_admin_password = "changed-in-dashboard"
run_seed(db)
check("แก้ SEED_ADMIN_PASSWORD ไม่เปลี่ยนรหัสเดิม",
      verify_password("original-pass-123", admin(db).hashed_password))

# Too-short reset values are refused rather than silently weakening the account.
settings.admin_password_reset = "short"
run_seed(db)
check("รหัสรีเซ็ตสั้นเกินไปถูกปฏิเสธ",
      verify_password("original-pass-123", admin(db).hashed_password))

# The real reset.
settings.admin_password_reset = "brand-new-password-456"
run_seed(db)
a = admin(db)
check("รีเซ็ตรหัสสำเร็จ", verify_password("brand-new-password-456", a.hashed_password))
check("รหัสเดิมใช้ไม่ได้แล้ว", not verify_password("original-pass-123", a.hashed_password))
check("บัญชีถูกเปิดใช้งาน", a.is_active is True)

logs = db.execute(select(AuditLog).where(AuditLog.action == "admin_password_reset")).scalars().all()
check("บันทึกลง audit log", len(logs) == 1, len(logs))

# Re-running with the same value must not spam the audit log.
run_seed(db)
logs = db.execute(select(AuditLog).where(AuditLog.action == "admin_password_reset")).scalars().all()
check("บูตซ้ำด้วยค่าเดิมไม่บันทึกซ้ำ", len(logs) == 1, len(logs))

# Clearing the variable leaves the new password in place.
settings.admin_password_reset = ""
run_seed(db)
check("ลบตัวแปรแล้วรหัสใหม่ยังใช้ได้",
      verify_password("brand-new-password-456", admin(db).hashed_password))
db.close()

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL ADMIN-RESET CHECKS PASSED")
