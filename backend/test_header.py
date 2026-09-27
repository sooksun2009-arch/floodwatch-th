"""HTTP_USER_AGENT must never be able to break outbound requests.

A Thai character in this one setting made h11 raise LocalProtocolError on
every outbound call in production: routing fell back to straight lines,
geocoding stopped resolving, and the gauge sync silently stored nothing.
"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/t.db"
os.environ["JWT_SECRET"] = "t"

import h11
from app.config import DEFAULT_USER_AGENT, _safe_header

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond: fails.append(name)

def sendable(value):
    """True when h11 would accept this as a header value."""
    try:
        h11.Request(method="GET", target="/",
                    headers=[("Host", "x"), ("User-Agent", value)])
        return True
    except Exception:
        return False

CASES = [
    ("ค่าปกติ", "FloodWatchTH/1.0 (https://floodwatch-th.onrender.com)"),
    ("มีภาษาไทย", "FloodWatchTH/1.0 (แอปเตือนน้ำท่วม)"),
    ("ไทยล้วน", "แอปน้ำท่วม"),
    ("มีตัวขึ้นบรรทัด", "FloodWatchTH/1.0\nX-Injected: evil"),
    ("มีแท็บ", "FloodWatch\tTH"),
    ("ช่องว่างหัวท้าย", "   FloodWatchTH/1.0   "),
    ("ค่าว่าง", ""),
    ("อีโมจิ", "FloodWatch 🌊"),
]

for name, raw in CASES:
    safe = _safe_header(raw, DEFAULT_USER_AGENT)
    check(f"ส่งเป็น header ได้: {name}", sendable(safe), f"{raw!r} -> {safe!r}")
    check(f"ไม่ว่างเปล่า: {name}", bool(safe.strip()), repr(safe))

check("ค่าปกติไม่ถูกแก้",
      _safe_header("FloodWatchTH/1.0 (https://x.com)", DEFAULT_USER_AGENT)
      == "FloodWatchTH/1.0 (https://x.com)")
check("ค่าที่มีแต่อักขระไทยถอยไปใช้ค่าสำรอง",
      _safe_header("แอปน้ำท่วม", DEFAULT_USER_AGENT) == DEFAULT_USER_AGENT,
      _safe_header("แอปน้ำท่วม", DEFAULT_USER_AGENT))
check("ตัดการแทรก header ด้วยตัวขึ้นบรรทัด",
      "\n" not in _safe_header("a\nX-Evil: 1", DEFAULT_USER_AGENT))

# The real setting, as the app will actually use it.
from app.config import settings
check("ค่าที่แอปใช้จริงส่งได้", sendable(settings.http_user_agent), settings.http_user_agent)

print()
print("=" * 60)
if fails:
    print(f"{len(fails)} FAILED: {fails}"); sys.exit(1)
print("ALL USER-AGENT SAFETY CHECKS PASSED")
