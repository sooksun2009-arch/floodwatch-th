"""BMA drainage gauge parsing — offline, against captured page shapes."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/up"
os.environ["JWT_SECRET"] = "t"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"  # no network in tests

import app.bma_stations as bma
from app.bma_stations import (
    describe_connection_failure, parse_detail, parse_summary, to_record,
    _parse_thai_datetime,
)

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond: fails.append(name)

SUMMARY = """
<table><tr><th>เขต</th><th>คลอง</th></tr>
<tr><td>บางเขน</td><td>คลองกระเฉด</td><td>ค.กระเฉด(รามอินทรา)</td>
    <td>27/09/2569 15:20</td><td>ปกติ</td><td>-0.16</td><td>-</td><td>-</td>
    <td><a href="/water/StationDetail?id=265">ดู</a></td></tr>
<tr><td>บางกะปิ</td><td>คลองกะจะ</td><td>ค.กะจะ ถ.พระราม 9</td>
    <td>27/09/2569 15:20</td><td>วิกฤติ</td><td>2.40</td><td>-</td><td>-</td>
    <td><a href="/water/StationDetail?id=138">ดู</a></td></tr>
<tr><td>ดินแดง</td><td>คลองสามเสน</td><td>ค.สามเสน</td>
    <td>27/09/2569 15:20</td><td>ขัดข้อง</td><td>-</td><td>-</td><td>-</td>
    <td><a href="/water/StationDetail?id=99">ดู</a></td></tr>
</table>
"""

rows = parse_summary(SUMMARY)
check("แกะตารางสรุปได้ 3 สถานี", len(rows) == 3, len(rows))
check("ดึง id จากลิงก์", [r["external_id"] for r in rows] == ["265", "138", "99"],
      [r["external_id"] for r in rows])
check("ชื่อเขต", rows[0]["district"] == "บางเขน", rows[0]["district"])
check("ระดับน้ำติดลบอ่านได้", rows[0]["water_level_msl"] == -0.16, rows[0]["water_level_msl"])
check("สถานะ", rows[1]["status"] == "วิกฤติ", rows[1]["status"])
check("สถานีขัดข้องไม่มีตัวเลข", rows[2]["water_level_msl"] is None, rows[2]["water_level_msl"])

# พ.ศ. 2569 must become ค.ศ. 2026, read as Thai local time and stored as UTC.
from datetime import datetime as _dt, timezone as _tz

dt = _parse_thai_datetime("27/09/2569 15:20")
check("แปลง พ.ศ. เป็น ค.ศ.", dt is not None and dt.year == 2026 and dt.month == 9, dt)
# The instant, not the label: a value merely tagged +07:00 becomes seven hours
# in the future once a database drops the offset, which showed a twelve-hour-old
# gauge reading as current.
check("15:20 ไทย = 08:20 UTC", dt == _dt(2026, 9, 27, 8, 20, tzinfo=_tz.utc), dt)
check("วันที่ผิดรูปแบบคืน None", _parse_thai_datetime("ไม่มีข้อมูล") is None)

DETAIL = """
<div>พิกัด 13.85826, 100.62848</div>
<input title="ตลิ่งซ้าย" class="form-control" value="0.45" />
<input title="ตลิ่งขวา" class="form-control" value="0.60" />
<input title="เตือนภัย" class="form-control" value="0.20" />
<input title="วิกฤติ" class="form-control" value="0.30" />
"""
d = parse_detail(DETAIL)
check("อ่านพิกัด", (round(d["lat"], 5), round(d["lng"], 5)) == (13.85826, 100.62848), d)
check("ใช้ตลิ่งด้านต่ำกว่า", d["bank_level"] == 0.45, d.get("bank_level"))
check("อ่านเกณฑ์เตือนภัย", d.get("warn_level") == 0.20, d.get("warn_level"))
check("อ่านเกณฑ์วิกฤติ", d.get("critical_level") == 0.30, d.get("critical_level"))
check("หน้าไม่มีพิกัดคืน dict ว่าง", "lat" not in parse_detail("<div>ไม่มีอะไร</div>"))

# พิกัดนอกประเทศต้องไม่ถูกรับ
check("พิกัดนอกไทยถูกปฏิเสธ",
      "lat" not in parse_detail("<div>48.85834, 102.29448</div>"))

DET = {"lat": 13.85826, "lng": 100.62848, "bank_level": 0.45}

r0 = to_record(rows[0], DET)   # ปกติ, ระดับ -0.16 ต่ำกว่าตลิ่ง 0.45
check("ปกติ -> ไม่ล้นตลิ่ง", r0["is_overflowing"] is False, r0["is_overflowing"])
check("คำนวณต่างจากตลิ่ง", r0["diff_from_bank"] == -0.61, r0["diff_from_bank"])
check("จังหวัดเป็น กทม.", r0["province_name"] == "กรุงเทพมหานคร", r0["province_name"])
check("ให้เครดิตหน่วยงาน", r0["agency"] == "สนน. กทม.", r0["agency"])
check("ชื่อรวมชื่อคลอง", "คลองกระเฉด" in r0["name"], r0["name"])
check("สถานะปกติ = ระดับ 3", r0["situation_level"] == 3, r0["situation_level"])

r1 = to_record(rows[1], DET)   # วิกฤติ, ระดับ 2.40 สูงกว่าตลิ่ง
check("วิกฤติ -> ล้นตลิ่ง", r1["is_overflowing"] is True, r1["is_overflowing"])
check("วิกฤติ = ระดับ 5", r1["situation_level"] == 5, r1["situation_level"])
check("ต่างจากตลิ่งเป็นบวก", r1["diff_from_bank"] == 1.95, r1["diff_from_bank"])

# 25 of ~300 real stations read as over-the-bank by subtraction while กทม.
# itself reports ปกติ. The department's status has to win, or the map shows
# red pins where the operator says there is no problem.
HIGH_BUT_NORMAL = dict(rows[0], status="ปกติ", water_level_msl=1.54)
hb = to_record(HIGH_BUT_NORMAL, {"lat": 13.8, "lng": 100.6, "bank_level": 1.25})
check("ระดับสูงกว่าตลิ่งแต่ กทม. ว่าปกติ -> ไม่ล้นตลิ่ง",
      hb["is_overflowing"] is False, hb["is_overflowing"])
check("แต่ยังแสดงตัวเลขส่วนต่างไว้", hb["diff_from_bank"] == 0.29, hb["diff_from_bank"])
check("ระดับสถานการณ์ยังเป็นปกติ", hb["situation_level"] == 3, hb["situation_level"])

# ตลิ่ง 0.0 = ยังไม่ได้สำรวจ ไม่ใช่ระดับน้ำทะเล
unset = to_record(dict(rows[0], water_level_msl=0.83),
                  {"lat": 13.8, "lng": 100.6, "bank_level": 0.0})
check("ตลิ่ง 0 ถือว่าไม่มีข้อมูล", unset["bank_level"] is None, unset["bank_level"])
check("ตลิ่ง 0 -> ไม่คำนวณส่วนต่าง", unset["diff_from_bank"] is None, unset["diff_from_bank"])

r2 = to_record(rows[2], DET)   # ขัดข้อง — ต้องไม่ถูกอ่านว่าปกติ
check("ขัดข้อง -> ไม่มีระดับสถานการณ์", r2["situation_level"] is None, r2["situation_level"])
check("ขัดข้อง -> ไม่ล้นตลิ่ง", r2["is_overflowing"] is False, r2["is_overflowing"])
check("ขัดข้อง -> ไม่แสดงค่าระดับน้ำ", r2["water_level_msl"] is None, r2["water_level_msl"])
check("ขัดข้อง -> บอกผู้ใช้ตรง ๆ", r2["status_text"] == "สถานีขัดข้อง", r2["status_text"])

check("ไม่มีพิกัด -> ข้ามสถานี", to_record(rows[0], {"bank_level": 0.45}) is None)
check("ตารางว่าง -> ไม่พัง", parse_summary("<table></table>") == [])

# ---------------------------------------------------------------- diagnostics
# "ConnectError: " with an empty message was the entire error text for the
# failure that kept Bangkok off the live map, and it cannot tell a name that
# would not resolve from a connection that was refused.
import socket
import httpx

try:
    try:
        raise socket.gaierror(-2, "Name or service not known")
    except Exception as inner:
        raise httpx.ConnectError("") from inner
except Exception as exc:
    text = describe_connection_failure(exc)
check("ข้อความแสดงสาเหตุจริง ไม่ใช่แค่ชื่อประเภท", "gaierror" in text, text)
check("บอกรายละเอียดที่แปลงชื่อโดเมนไม่ได้", "Name or service" in text, text)
check("ยังบอกประเภทชั้นนอกไว้ด้วย", text.startswith("ConnectError"), text)

try:
    raise httpx.ConnectTimeout("timed out")
except Exception as exc:
    text = describe_connection_failure(exc)
check("หมดเวลาเชื่อมต่อ -> แยกออกจากกรณี DNS ได้",
      "ConnectTimeout" in text and "timed out" in text, text)


# ---------------------------------------------------------------- retrying
import asyncio

bma.RETRY_DELAYS = (0.0, 0.0)          # no real waiting inside the test


def _run(handler):
    calls = {"n": 0}

    def wrapped(request):
        calls["n"] += 1
        return handler(request, calls["n"])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
            return await bma._fetch(client, "https://example.test/Summary")

    try:
        return asyncio.run(go()), calls["n"], None
    except Exception as exc:
        return None, calls["n"], exc


text, n, err = _run(lambda r, i: httpx.Response(200, text="ok")
                    if i > 1 else (_ for _ in ()).throw(httpx.ConnectError("")))
check("ล้มครั้งแรกแล้วลองใหม่สำเร็จ", text == "ok" and n == 2, f"{text!r} calls={n} {err}")

text, n, err = _run(lambda r, i: (_ for _ in ()).throw(httpx.ConnectError("")))
check("ล้มทุกครั้ง -> หยุดที่ 3 ครั้ง ไม่วนไม่สิ้นสุด", n == 3, f"calls={n}")
check("และโยน error ออกมาให้เห็น", isinstance(err, httpx.ConnectError), repr(err))

text, n, err = _run(lambda r, i: httpx.Response(403, text="forbidden"))
check("โดนปฏิเสธ 403 -> ไม่ยิงซ้ำ (ยิงซ้ำมีแต่จะโดนหนักขึ้น)", n == 1, f"calls={n}")
check("และรายงานว่าเป็นเรื่องสถานะ ไม่ใช่เรื่องเชื่อมต่อ",
      isinstance(err, httpx.HTTPStatusError), repr(err))


class _Loop(Exception):
    pass

a, b = _Loop("a"), _Loop("b")
a.__cause__ = b
b.__cause__ = a
check("สาเหตุวนกันเอง -> ไม่ค้างลูป", describe_connection_failure(a).count("<-") == 1,
      describe_connection_failure(a))

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL BMA-STATION CHECKS PASSED")
