"""Visit counting, and the promise it must not break.

The site tells people it does not store the routes they search or keep a travel
history. A counter is the easiest place to make that quietly untrue — one path
logged, one address kept — so the first checks here are about what is *not*
stored, and only then about whether the arithmetic works.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/v.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app import visits
from app.database import engine
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


with TestClient(app) as c:
    # ------------------------------------------------- what is not stored
    columns = {col["name"] for col in inspect(engine).get_columns("visit_stats")}
    check("ตารางไม่มีช่องเก็บ IP หรือตัวระบุตัวตน",
          not (columns & {"ip", "ip_address", "visitor", "visitor_id", "token",
                          "user_agent", "session"}),
          columns)
    check("เก็บแค่ วัน/ชั่วโมง/หน้า/จำนวน",
          columns == {"id", "day", "hour", "page", "views", "visitors"}, columns)

    # A path can carry where somebody was trying to get to. The field is short
    # enough that one cannot fit, and it is refused rather than truncated --
    # a truncated path is still part of a path.
    r = c.post("/api/visits", json={"page": "/?origin=บางนา&destination=รามคำแหง",
                                    "first_today": True, "token": "a"})
    check("ส่ง path มาแทนชื่อหน้า -> ปฏิเสธ ไม่ตัดให้สั้นแล้วเก็บ",
          r.status_code == 422, r.status_code)
    pages = [x[0] for x in engine.connect().execute(text("SELECT page FROM visit_stats"))]
    check("ไม่มีคำค้นหาหลุดลงฐานข้อมูล",
          not any("บางนา" in p for p in pages), pages)

    # A label we do not publish still counts, as "other" -- an unknown page is
    # a page, and losing it would make the totals wrong.
    c.post("/api/visits", json={"page": "weird", "first_today": True, "token": "a"})
    check("ชื่อหน้าที่ไม่รู้จัก -> เก็บเป็น other",
          "other" in [x[0] for x in
                      engine.connect().execute(text("SELECT page FROM visit_stats"))])

    # ------------------------------------------------- the arithmetic
    for _ in range(4):
        c.post("/api/visits", json={"page": "map", "first_today": False, "token": "b"})
    c.post("/api/visits", json={"page": "map", "first_today": True, "token": "c"})

    login = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    data = c.get("/api/visits/summary", headers=auth).json()
    today = data["days"][-1]

    check("นับยอดเปิดดูครบทุกครั้ง", today["views"] == 6, today)
    check("นับผู้ใช้เฉพาะครั้งแรกของวัน", today["visitors"] == 2, today)
    check("แยกตามหน้าได้", {p["page"] for p in data["pages"]} == {"map", "other"},
          data["pages"])

    # ------------------------------------------------- who is here now
    check("นับคนที่กำลังเปิดอยู่", data["online_now"] == 3, data["online_now"])
    c.post("/api/visits/ping", json={"token": "d"})
    check("ping นับว่ายังอยู่ โดยไม่เพิ่มยอดเปิดดู",
          c.get("/api/visits/summary", headers=auth).json()["days"][-1]["views"] == 6)

    # Nothing about who is here survives anywhere but memory.
    visits._online.clear()
    check("ล้างหน่วยความจำ -> ไม่เหลือใครอยู่ (ไม่ได้เขียนลงดิสก์)",
          c.get("/api/visits/summary", headers=auth).json()["online_now"] == 0)

    # ------------------------------------------------- whose clock
    # Render runs in UTC. Counting by its date filed every visit between
    # midnight and 7am under the day before, and pushed the hourly chart seven
    # hours away from the clock the reader is holding.
    from datetime import datetime, timezone as _tz

    from app.visits import BANGKOK, _now

    thai = _now()
    utc = datetime.now(_tz.utc)
    check("นับวันตามเวลาไทย ไม่ใช่เวลาเครื่อง",
          thai.utcoffset().total_seconds() == 7 * 3600, thai.utcoffset())
    check("ชั่วโมงที่บันทึกตรงกับนาฬิกาบ้านเรา",
          thai.hour == (utc.hour + 7) % 24, (thai.hour, utc.hour))
    # The stored day and the day the summary asks for must be the same clock,
    # or "today" quietly reads a row nothing is written to.
    row_day = data["days"][-1]["day"]
    check("วันที่ในแถวข้อมูล = วันที่ที่หน้าสรุปถาม", row_day == thai.strftime("%Y-%m-%d"),
          (row_day, thai.strftime("%Y-%m-%d")))

    # ------------------------------------------------- who may read it
    check("ไม่ล็อกอิน -> อ่านสรุปไม่ได้",
          c.get("/api/visits/summary").status_code in (401, 403),
          c.get("/api/visits/summary").status_code)

    c.post("/api/auth/register", json={"username": "someone", "password": "pass12345"})
    plain = c.post("/api/auth/login",
                   json={"username": "someone", "password": "pass12345"})
    if plain.status_code == 200:
        head = {"Authorization": f"Bearer {plain.json()['access_token']}"}
        check("ผู้ใช้ทั่วไป -> อ่านสรุปไม่ได้",
              c.get("/api/visits/summary", headers=head).status_code in (401, 403),
              c.get("/api/visits/summary", headers=head).status_code)

    # ------------------------------------------------- never in the way
    # Counting is the least important thing here. A broken count must not be
    # able to fail a page load, so the write path accepts nonsense quietly.
    r = c.post("/api/visits", json={})
    check("ส่งมาไม่ครบ -> ยังรับ ไม่พังหน้าเว็บ", r.status_code == 204, r.status_code)

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL VISIT-COUNTING CHECKS PASSED")
sys.exit(1 if fails else 0)
