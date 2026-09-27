"""Importer tests, built around the record shape กทม. district lists publish."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.importers import parse_coords, parse_csv, parse_depth_cm, parse_pasted_block  # noqa: E402
from app.main import app  # noqa: E402

fails: list[str] = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- coordinates

# The exact string Google Maps shows for the pin in the reference screenshot.
c = parse_coords('13°41\'11.3"N 100°38\'06.7"E')
check("DMS parsed", c is not None and abs(c[0] - 13.68647) < 1e-4 and abs(c[1] - 100.63519) < 1e-4, c)

c = parse_coords("13.686460, 100.635200")
check("decimal pair parsed", c == (13.68646, 100.6352), c)

c = parse_coords("https://maps.google.com/?q=13.686460,100.635200")
check("google q= link", c == (13.68646, 100.6352), c)

c = parse_coords("https://www.google.com/maps/@13.686460,100.635200,17z")
check("google @ link", c == (13.68646, 100.6352), c)

c = parse_coords("https://www.google.com/maps/place/x/data=!3d13.686460!4d100.635200")
check("google !3d!4d link", c == (13.68646, 100.6352), c)

check("coords outside Thailand rejected", parse_coords("48.858370, 2.294481") is None,
      parse_coords("48.858370, 2.294481"))
check("no coords -> None", parse_coords("ถนนวชิรธรรมสาธิต เขตพระโขนง") is None)

# ---------------------------------------------------------------- depth

check("depth ซม.", parse_depth_cm("ท่วมสูง 20 ซม. หรือมากกว่า") == 20,
      parse_depth_cm("ท่วมสูง 20 ซม. หรือมากกว่า"))
check("depth range takes upper bound", parse_depth_cm("ระดับน้ำ 15-20 ซม.") == 20,
      parse_depth_cm("ระดับน้ำ 15-20 ซม."))
check("depth in metres converted", parse_depth_cm("น้ำสูง 0.5 เมตร") == 50,
      parse_depth_cm("น้ำสูง 0.5 เมตร"))
check("no depth -> None", parse_depth_cm("น้ำขังรอระบาย") is None,
      parse_depth_cm("น้ำขังรอระบาย"))

# ---------------------------------------------------------------- pasted block

PASTED = """21. ถ.วชิรธรรมสาธิต
ช่วงน้ำท่วม: บริเวณใกล้ ซ.วัดทุ่ง
จุดวัด 1 จุด
ช่วง 3 แยกซอยวัดทุ่ง ท่วมสูง 20 ซม. หรือมากกว่า
เขตพระโขนง
https://maps.google.com/?q=13.686460,100.635200

22. ถ.สุขุมวิท 101/1
ช่วงน้ำท่วม: ปากซอยถึงกลางซอย
น้ำขังรอระบาย
เขตบางนา
13.6800, 100.5880

23. ถ.ไม่มีพิกัด
เขตดินแดง
"""

result = parse_pasted_block(PASTED)
check("two records parsed, one skipped",
      len(result.records) == 2 and result.skipped == 1,
      f"parsed={len(result.records)} skipped={result.skipped} errors={result.errors}")

if len(result.records) >= 1:
    r0 = result.records[0]
    check("record place keeps road + section",
          "วชิรธรรมสาธิต" in r0.place and "วัดทุ่ง" in r0.place, r0.place)
    check("record depth", r0.depth_cm == 20, r0.depth_cm)
    check("record district", r0.district == "พระโขนง", r0.district)
    check("record coords", abs(r0.lat - 13.68646) < 1e-4, (r0.lat, r0.lng))
    # "น้ำท่วมสูง" is not in this block, but 20cm lands in the shallow band.
    check("record level from depth", r0.level == "shallow", r0.level)

if len(result.records) >= 2:
    r1 = result.records[1]
    check("second record level from keyword", r1.level == "puddle", r1.level)
    check("second record has no depth", r1.depth_cm is None, r1.depth_cm)

check("skipped row is explained",
      any("ไม่พบพิกัด" in e for e in result.errors), result.errors)

# A stated depth overrides a milder keyword.
override = parse_pasted_block("1. ถ.ทดสอบ\nน้ำขัง 45 ซม.\nเขตบางรัก\n13.7248, 100.5232")
check("depth beats a milder keyword",
      override.records and override.records[0].level == "deep",
      override.records[0].level if override.records else None)

# ---------------------------------------------------------------- CSV

CSV_BOM = "﻿" + """ถนน,ช่วง,เขต,ระดับน้ำ,พิกัด,สถานะ
ถ.รามคำแหง,แยกลำสาลี,บางกะปิ,25 ซม.,"13.765000, 100.635000",กำลังเร่งระบาย
ถ.ลาดพร้าว,ซอย 71,วังทองหลาง,ท่วมสูง 50 ซม.,https://maps.google.com/?q=13.806000%2C100.596000,ปิดการจราจร
ถ.ไม่มีพิกัด,,ดินแดง,10 ซม.,,
"""
res = parse_csv(CSV_BOM.encode("utf-8"))
check("CSV with UTF-8 BOM parsed", len(res.records) == 2 and res.skipped == 1,
      f"parsed={len(res.records)} skipped={res.skipped} errors={res.errors}")
if len(res.records) == 2:
    check("CSV depth", res.records[0].depth_cm == 25, res.records[0].depth_cm)
    check("CSV url-encoded google link", abs(res.records[1].lng - 100.596) < 1e-4,
          res.records[1].lng)
    check("CSV status keyword -> closed", res.records[1].level == "closed",
          res.records[1].level)

check("CSV in cp874 also decodes",
      len(parse_csv(CSV_BOM.replace("﻿", "").encode("cp874")).records) == 2)

csv_no_coords = "ถนน,เขต\nถ.ก,บางรัก\n"
res2 = parse_csv(csv_no_coords.encode("utf-8"))
check("CSV without coordinate column is refused with a reason",
      not res2.records and any("พิกัด" in e for e in res2.errors), res2.errors)

# ---------------------------------------------------------------- API

with TestClient(app) as c2:
    login = c2.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = c2.post("/api/import/paste", json={"text": PASTED, "dry_run": True,
                                           "source_name": "กทม. (ทดสอบ)"})
    check("import requires auth", r.status_code == 401, r.status_code)

    r = c2.post("/api/import/paste", headers=auth,
                json={"text": PASTED, "dry_run": True, "source_name": "กทม. (ทดสอบ)"})
    check("dry run parses without writing",
          r.status_code == 200 and r.json()["parsed"] == 2 and r.json()["created"] == 0,
          r.text[:250])
    check("dry run returns a preview",
          r.status_code == 200 and len(r.json()["preview"]) == 2, r.text[:200])

    r = c2.get("/api/reports")
    check("dry run wrote nothing", r.json()["total"] == 0, r.json()["total"])

    r = c2.post("/api/import/paste", headers=auth,
                json={"text": PASTED, "dry_run": False, "source_name": "กทม. (ทดสอบ)",
                      "auto_approve": True})
    check("real import creates reports",
          r.status_code == 200 and r.json()["created"] == 2, r.text[:250])

    r = c2.get("/api/reports")
    check("imported reports are live on the map", r.json()["total"] == 2, r.json()["total"])
    items = r.json()["items"]
    check("imported reports marked official",
          all(i["source"] == "official" for i in items), [i["source"] for i in items])

    # Re-importing the same list must update, not duplicate.
    r = c2.post("/api/import/paste", headers=auth,
                json={"text": PASTED, "dry_run": False, "source_name": "กทม. (ทดสอบ)"})
    check("re-import updates instead of duplicating",
          r.json()["updated"] == 2 and r.json()["created"] == 0, r.text[:250])
    r = c2.get("/api/reports")
    check("still two reports after re-import", r.json()["total"] == 2, r.json()["total"])

    r = c2.post("/api/import/paste", headers=auth,
                json={"text": "ไม่มีอะไรเลย ไม่มีพิกัด", "dry_run": True})
    check("unparseable paste returns 422", r.status_code == 422, r.status_code)

    files = {"file": ("report.csv", CSV_BOM.encode("utf-8"), "text/csv")}
    r = c2.post("/api/import/file", headers=auth, files=files,
                data={"source_name": "เขตทดสอบ", "dry_run": "true"})
    check("CSV upload dry run", r.status_code == 200 and r.json()["parsed"] == 2, r.text[:250])

    files = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    r = c2.post("/api/import/file", headers=auth, files=files)
    check("unsupported file type refused", r.status_code == 400, r.status_code)

    r = c2.post("/api/import/parse-coords", headers=auth,
                data={"text": "https://maps.google.com/?q=13.686460,100.635200"})
    check("coord helper endpoint", r.status_code == 200
          and abs(r.json()["lat"] - 13.68646) < 1e-4, r.text[:150])

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL IMPORTER CHECKS PASSED")
