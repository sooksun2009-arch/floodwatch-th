"""Additive schema sync: the case that broke a live database."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
DB = f"{tmp}/m.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"

import sqlite3
from sqlalchemy import inspect
import app.models  # noqa: F401 — registers every table on Base.metadata
from app.database import Base, engine
from app.migrate import report_drift, sync_schema

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond: fails.append(name)

Base.metadata.create_all(bind=engine)
check("tables created", "cameras" in inspect(engine).get_table_names(),
      inspect(engine).get_table_names())

# Simulate an older deployment: drop two columns that were added later, and
# put a row in the table so the "existing data" case is covered.
raw = sqlite3.connect(DB)
raw.execute("""CREATE TABLE cameras_old AS
               SELECT id, name, lat, lng, stream_type, stream_url, refresh_sec,
                      is_active, is_demo, health, created_at, updated_at
               FROM cameras""")
raw.execute("DROP TABLE cameras")
raw.execute("ALTER TABLE cameras_old RENAME TO cameras")
raw.execute("""INSERT INTO cameras (id, name, lat, lng, stream_type, stream_url,
                                    refresh_sec, is_active, is_demo, health,
                                    created_at, updated_at)
               VALUES ('abc','กล้องเก่า',13.7,100.5,'snapshot','https://x/a.jpg',
                       15,1,0,'unknown','2026-01-01','2026-01-01')""")
raw.commit()
cols_before = {r[1] for r in raw.execute("PRAGMA table_info(cameras)")}
raw.close()

check("column really missing before sync", "last_frame_at" not in cols_before, sorted(cols_before))

applied = sync_schema(engine)
check("sync reports what it added", any("last_frame_at" in a for a in applied), applied)

raw = sqlite3.connect(DB)
cols_after = {r[1] for r in raw.execute("PRAGMA table_info(cameras)")}
check("missing column added", "last_frame_at" in cols_after)
check("other missing columns added too",
      {"last_checked", "owner_org", "source_page", "notes"} <= cols_after,
      sorted(cols_after))
row = raw.execute("SELECT id, name, last_frame_at FROM cameras").fetchone()
check("existing row preserved", row[0] == "abc" and row[1] == "กล้องเก่า", row)
check("new column is null on the old row", row[2] is None, row)
raw.close()

check("second run is a no-op", sync_schema(engine) == [], "should already be in sync")

# A column the models no longer declare is reported, never dropped.
raw = sqlite3.connect(DB)
raw.execute("ALTER TABLE cameras ADD COLUMN legacy_field TEXT")
raw.commit(); raw.close()
drift = report_drift(engine)
check("extra db column reported as drift",
      "legacy_field" in drift.get("cameras", []), drift)
sync_schema(engine)
raw = sqlite3.connect(DB)
still = {r[1] for r in raw.execute("PRAGMA table_info(cameras)")}
raw.close()
check("drifted column is never dropped", "legacy_field" in still)

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL SCHEMA-SYNC CHECKS PASSED")
