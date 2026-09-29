"""Where visitors come from, which provinces they check, the optional survey,
and the CSV backups -- and, first, that none of it stores anything about a
person.
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import visits
from app.config import settings
from app.database import SessionLocal, engine
from app.main import app

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def counts(data, kind):
    return {row["key"]: row["count"] for row in data["tallies"][kind]}


with TestClient(app) as c:
    columns = {col["name"] for col in inspect(engine).get_columns("tallies")}
    check("ตาราง tallies มีแค่ วัน/ประเภท/ค่า/จำนวน",
          columns == {"id", "day", "kind", "key", "count"}, columns)

    login = c.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    summary = lambda: c.get("/api/visits/summary", headers=auth).json()

    # ------------------------------------------------- source
    c.post("/api/visits", json={"page": "map", "first_today": True, "source": "facebook"})
    c.post("/api/visits", json={"page": "map", "first_today": True, "source": "facebook"})
    c.post("/api/visits", json={"page": "map", "first_today": False, "source": "facebook"})
    c.post("/api/visits", json={"page": "map", "first_today": True, "source": "line"})
    c.post("/api/visits", json={"page": "map", "first_today": True,
                                "source": "https://x.co/a"})
    src = counts(summary(), "source")
    check("นับแหล่งที่มาเฉพาะครั้งแรกของวัน", src.get("facebook") == 2, src)
    check("แยก LINE ได้", src.get("line") == 1, src)
    check("ค่าแปลก ๆ (URL) -> เก็บเป็น other ไม่ใช่ตัว URL",
          src.get("other") == 1 and not any("http" in k for k in src), src)

    # ------------------------------------------------- survey
    r = c.post("/api/visits/survey", json={"use": "delivery", "age": "25_34"})
    check("ตอบแบบสอบถามได้", r.status_code == 204, r.status_code)
    c.post("/api/visits/survey", json={"use": "delivery"})
    c.post("/api/visits/survey", json={"use": "ข้อความอะไรก็ได้", "age": "99"})
    data = summary()
    check("นับคำตอบการใช้งาน", counts(data, "use") == {"delivery": 2}, counts(data, "use"))
    check("ตอบข้อเดียวก็ได้ อีกข้อไม่ถูกนับ", counts(data, "age") == {"25_34": 1},
          counts(data, "age"))
    check("คำตอบนอกตัวเลือก -> ไม่ถูกเก็บ",
          all(k in visits.SURVEY["use"] + visits.SURVEY["age"]
              for k in {**counts(data, "use"), **counts(data, "age")}))

    statuses = [c.post("/api/visits/survey", json={"use": "home"}).status_code
                for _ in range(6)]
    check("ส่งแบบสอบถามรัว ๆ จากที่เดียว -> ถูกจำกัด", 429 in statuses, statuses)

    # ------------------------------------------------- provinces
    with SessionLocal() as db:
        bkk = visits.province_of(db, 13.7563, 100.5018)
        check("หาจังหวัดจากพิกัดได้", bool(bkk), bkk)
        check("นอกประเทศไทย -> ไม่นับ", visits.province_of(db, 35.68, 139.69) is None)
        visits.count_route(db, [(13.7563, 100.5018), (13.76, 100.51)])
    prov = counts(summary(), "province")
    check("ต้นทาง-ปลายทางจังหวัดเดียวกัน -> นับครั้งเดียว", prov.get(bkk) == 1, prov)

    # ------------------------------------------------- CSV export
    r = c.get("/api/admin/export/reports.csv")
    check("ไม่ล็อกอิน -> ดาวน์โหลดไม่ได้", r.status_code == 401, r.status_code)

    r = c.get("/api/admin/export/reports.csv", headers=auth)
    check("ผู้ดูแลดาวน์โหลดรายงานได้", r.status_code == 200, r.status_code)
    check("ไฟล์ขึ้นต้นด้วย BOM (Excel อ่านภาษาไทยถูก)",
          r.content.startswith(b"\xef\xbb\xbf"), r.content[:10])
    header = r.content.decode("utf-8-sig").splitlines()[0]
    check("ไม่มี IP หรือชื่อผู้แจ้งในไฟล์",
          "ip" not in header.lower() and "reporter" not in header.lower(), header)

    for name in ("visits", "tallies"):
        r = c.get(f"/api/admin/export/{name}.csv", headers=auth)
        check(f"ดาวน์โหลด {name}.csv ได้", r.status_code == 200 and len(r.content) > 10,
              r.status_code)

    settings.backup_token = ""
    r = c.get("/api/admin/export/reports.csv", headers={"Authorization": "Bearer "})
    check("ยังไม่ตั้ง BACKUP_TOKEN -> โทเคนว่างเข้าไม่ได้", r.status_code == 401, r.status_code)

    settings.backup_token = "nightly-secret"
    r = c.get("/api/admin/export/reports.csv",
              headers={"Authorization": "Bearer nightly-secret"})
    check("BACKUP_TOKEN ถูก -> ดาวน์โหลดได้ (ให้ Apps Script ใช้)", r.status_code == 200,
          r.status_code)
    r = c.get("/api/admin/export/reports.csv", headers={"Authorization": "Bearer wrong"})
    check("BACKUP_TOKEN ผิด -> เข้าไม่ได้", r.status_code == 401, r.status_code)
    r = c.get("/api/visits/summary", headers={"Authorization": "Bearer nightly-secret"})
    check("BACKUP_TOKEN ใช้ได้แค่ดาวน์โหลด ไม่ได้เปิดหน้าแอดมินอื่น",
          r.status_code in (401, 403), r.status_code)
    settings.backup_token = ""

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL TALLY + EXPORT CHECKS PASSED")
sys.exit(1 if fails else 0)
