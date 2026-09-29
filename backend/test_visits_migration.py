"""The one-time fix for the day the visitor counter switched clocks.

This feature launched 2026-09-28 22:12 Bangkok time, counting by whatever clock
the server happened to run on (UTC, on Render). The fix that made it count by
Thailand's clock instead landed 2026-09-29 09:02:55 — so on that one day, and
only that day, rows written before 09:02:55 carry a UTC hour (0, 1, 2) filed
under a Bangkok date. That reads as a spike of visits at "00:00" that never
happened; the real traffic was at 07:00–09:02.

The scenario has to be built in this order to mean anything: the stale rows
must exist *before* the app starts, because that is what actually happened in
production — the bad data was already sitting in the table when the fixed code
was deployed. Testing it the other way round (start the app, then insert the
stale rows) proves nothing, since the migration's own marker would already be
set from the empty database it saw at that earlier startup.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/mig.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

from sqlalchemy import text

from app.database import Base, engine
# The model is only registered on Base.metadata once this module has been
# imported — exactly the reason main.py imports it for its side effect before
# calling create_all(). Skipping this line is a silent no-op table create.
from app import visits as _register_visit_stat  # noqa: F401,E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------- the world before

# Tables exist, and the stale rows are already there — before the app, or the
# migration, has ever run. This is the state a real deploy would have found.
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text(
        "INSERT INTO visit_stats (day, hour, page, views, visitors) VALUES "
        "('2026-09-29', 0, 'map', 210, 50), "
        "('2026-09-29', 1, 'map', 263, 60), "
        "('2026-09-29', 2, 'cameras', 7, 2), "
        "('2026-09-29', 9, 'map', 95, 30), "
        "('2026-09-28', 1, 'map', 999, 1)"
    ))

# ----------------------------------------------------------- the app starts

from fastapi.testclient import TestClient  # noqa: E402

from app import visits  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    # The fix runs automatically at startup (see main.py's lifespan) — nothing
    # here calls it directly, because a manual call proves the function works
    # and not that anyone remembered to wire it in.
    login = c.post("/api/auth/register", json={"username": "admin2", "password": "pass12345"})
    tok = c.post("/api/auth/login",
                 json={"username": "admin", "password": "admin1234"}).json()["access_token"]
    auth = {"Authorization": f"Bearer {tok}"}

    data = c.get("/api/visits/summary", headers=auth).json()
    hours = {h["hour"]: h["views"] for h in data["hours"]}

    check("ชั่วโมง 0 (UTC) ไม่มีข้อมูลค้างแล้ว", hours.get(0, 0) == 0, hours)
    check("ย้ายไปชั่วโมง 7 (07:00 น. ไทย) ถูกต้อง", hours.get(7) == 210, hours)
    check("ย้ายไปชั่วโมง 8 ถูกต้อง", hours.get(8) == 263, hours)
    check("ชั่วโมง 9 รวมของเดิม 95 กับที่ย้ายมา 7 (คนละหน้ากัน) = 102",
          hours.get(9) == 102, hours)

    days = {d["day"]: d for d in data["days"]}
    check("วันที่ 28 ไม่ถูกแตะต้องเลย",
          days.get("2026-09-28", {}).get("views") == 999, days.get("2026-09-28"))
    check("ยอดรวมวันนี้ไม่เปลี่ยน แค่ย้ายที่ (210+263+102=575)",
          days.get("2026-09-29", {}).get("views") == 575, days.get("2026-09-29"))

    # The bug this exists to catch: a bookkeeping row leaking into the public
    # summary and quietly becoming "today" because its day string sorts last.
    check("แถว marker ไม่โผล่มาปนในรายการวัน",
          "_meta" not in days, list(days.keys()))
    check("\"today\" ในคำตอบยังเป็นวันที่จริง ไม่ใช่ค่า marker",
          data["today"] != "_meta" and len(data["today"]) == 10, data["today"])

    # Running it again, now that the app is up, must be a no-op — this can
    # happen on every ordinary restart from here on.
    session = SessionLocal()
    again = visits.migrate_stale_utc_hours(session)
    session.close()
    check("เรียกซ้ำหลัง deploy ครั้งต่อไป -> ไม่ทำอะไรอีก", "ไปแล้ว" in again, again)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL VISIT-MIGRATION CHECKS PASSED")
sys.exit(1 if fails else 0)
