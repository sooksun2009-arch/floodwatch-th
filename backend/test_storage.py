"""Photo storage: local disk, the R2 bucket, and which URLs we will accept.

Two separate jobs are covered here. One is durability — on a host with no
persistent disk the bucket is the only reason a photo outlives a deploy. The
other is that `photo_url` arrives as a plain string from whoever is filing the
report and is rendered in an <img> on the moderation screen, so the server has
to be the thing that decides whether a URL is ours.
"""
import io as _io
import os, sys, tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/s.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["ANON_REPORT_LIMIT"] = "200"

from fastapi.testclient import TestClient
from PIL import Image

from app import storage
from app.config import settings
from app.main import app

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def a_jpeg(size=(40, 30)):
    buf = _io.BytesIO()
    Image.new("RGB", size, (10, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


class FakeR2:
    """Stands in for the boto3 client so no network or account is needed."""
    def __init__(self, explode=False):
        self.explode = explode
        self.calls = []

    def put_object(self, **kwargs):
        if self.explode:
            raise RuntimeError("bucket unreachable")
        self.calls.append(kwargs)
        return {}


R2_ENV = {
    "r2_endpoint_url": "https://acct.r2.cloudflarestorage.com",
    "r2_access_key_id": "key",
    "r2_secret_access_key": "secret",
    "r2_bucket": "floodwatch-photos",
    "r2_public_base_url": "https://pics.floodwatch.example",
}


def use_r2(explode=False):
    for field, value in R2_ENV.items():
        setattr(settings, field, value)
    storage._client = FakeR2(explode=explode)
    return storage._client


def use_local():
    for field in R2_ENV:
        setattr(settings, field, "")
    storage._client = None


# ---------------------------------------------------------------- URL rules
check("ค่าเริ่มต้นคือดิสก์ในเครื่อง", storage.backend_name() == "local",
      storage.backend_name())

GOOD = "/uploads/20260927-abc123def456.jpg"
for url, want, label in [
    (GOOD, True, "ชื่อไฟล์ที่ระบบสร้างเอง → รับ"),
    ("/uploads/../../etc/passwd", False, "path traversal → ปฏิเสธ"),
    ("/uploads/evil.jpg", False, "ชื่อไฟล์ผิดรูปแบบ → ปฏิเสธ"),
    ("/uploads/20260927-abc123def456.jpg.html", False, "นามสกุลแปลกปลอม → ปฏิเสธ"),
    ("https://evil.example/pixel.gif", False, "URL ภายนอก → ปฏิเสธ"),
    ("javascript:alert(1)", False, "javascript: → ปฏิเสธ"),
    ("//evil.example/x.jpg", False, "protocol-relative → ปฏิเสธ"),
    (None, False, "ค่าว่าง → ปฏิเสธ"),
]:
    check(label, storage.is_managed_url(url) is want, f"{url!r}")

# R2 on: its public URLs become valid, and the local ones stay valid so photos
# uploaded before the switch do not turn into broken images.
use_r2()
check("เปิด R2 แล้ว backend เปลี่ยน", storage.backend_name() == "r2", storage.backend_name())
check("URL ของ R2 → รับ",
      storage.is_managed_url("https://pics.floodwatch.example/20260927-abc123def456.jpg"))
check("รูปเก่าที่อยู่ในเครื่อง ยังใช้ได้หลังเปิด R2", storage.is_managed_url(GOOD))
check("โดเมนอื่นที่ขึ้นต้นคล้ายกัน → ปฏิเสธ",
      not storage.is_managed_url("https://pics.floodwatch.example.evil.com/20260927-abc123def456.jpg"))

# ---------------------------------------------------------------- writing
fake = use_r2()
url = storage.save_jpeg(a_jpeg(), "20260927-0123456789ab.jpg")
check("เขียนขึ้น R2 แล้วคืน URL สาธารณะ",
      url == "https://pics.floodwatch.example/20260927-0123456789ab.jpg", url)
check("ส่ง ContentType ถูกต้อง", fake.calls[0]["ContentType"] == "image/jpeg", fake.calls[0])
check("ตั้ง cache ยาว เพราะรูปไม่เคยเปลี่ยน",
      "immutable" in fake.calls[0]["CacheControl"], fake.calls[0].get("CacheControl"))
check("ไม่ได้เขียนลงดิสก์ในเครื่องด้วย",
      not os.path.exists(os.path.join(settings.upload_dir, "20260927-0123456789ab.jpg")))

try:
    storage.save_jpeg(b"x", "../../escape.jpg")
    check("ชื่อไฟล์แปลกปลอม → ปฏิเสธก่อนเขียน", False, "ไม่ raise")
except ValueError:
    check("ชื่อไฟล์แปลกปลอม → ปฏิเสธก่อนเขียน", True)

use_local()
url = storage.save_jpeg(a_jpeg(), "20260927-0123456789ab.jpg")
check("โหมดเครื่อง เขียนลงดิสก์และคืน /uploads/",
      url == "/uploads/20260927-0123456789ab.jpg"
      and os.path.exists(os.path.join(settings.upload_dir, "20260927-0123456789ab.jpg")), url)

# ---------------------------------------------------------------- end to end
with TestClient(app) as c:
    use_local()
    r = c.post("/api/uploads", files={"file": ("f.jpg", a_jpeg((2000, 1500)), "image/jpeg")})
    check("อัปโหลดผ่าน API สำเร็จ", r.status_code == 201, r.text[:200])
    uploaded = r.json()["url"]
    check("ย่อรูปตามขนาดสูงสุด", r.json()["width"] <= settings.max_image_px,
          str(r.json()))
    check("URL ที่ได้ผ่านการตรวจของเราเอง", storage.is_managed_url(uploaded), uploaded)

    body = {"lat": 13.7460, "lng": 100.5340, "level": "shallow"}
    r = c.post("/api/reports", json={**body, "photo_url": uploaded},
               headers={"x-forwarded-for": "1.1.1.1"})
    check("แจ้งพร้อมรูปที่อัปโหลดเอง → ผ่าน", r.status_code == 201, r.text[:200])

    r = c.post("/api/reports", json={**body, "photo_url": "https://evil.example/pixel.gif"},
               headers={"x-forwarded-for": "1.1.1.2"})
    check("แจ้งพร้อม URL ภายนอก → ถูกปฏิเสธ (กันหน้าแอดมินโหลดของนอก)",
          r.status_code == 400, f"{r.status_code} {r.text[:150]}")

    r = c.post("/api/reports", json={**body, "photo_url": "/uploads/../../etc/passwd"},
               headers={"x-forwarded-for": "1.1.1.3"})
    check("แจ้งพร้อม path traversal → ถูกปฏิเสธ", r.status_code == 400,
          f"{r.status_code} {r.text[:150]}")

    # Editing has to be guarded too, or the check above is trivially bypassed.
    c.post("/api/auth/register", json={"username": "editor", "password": "pass12345"})
    login = c.post("/api/auth/login", json={"username": "editor", "password": "pass12345"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    made = c.post("/api/reports", json=body, headers={**auth, "x-forwarded-for": "1.1.1.4"})
    rid = made.json()["id"]
    r = c.patch(f"/api/reports/{rid}", json={"photo_url": "https://evil.example/p.gif"},
                headers=auth)
    check("แก้รายงานให้ชี้รูปภายนอก → ถูกปฏิเสธ", r.status_code == 400,
          f"{r.status_code} {r.text[:150]}")

    # A broken bucket must fail loudly. Falling back to local disk would look
    # like success and then lose the photo at the next deploy.
    use_r2(explode=True)
    r = c.post("/api/uploads", files={"file": ("f.jpg", a_jpeg(), "image/jpeg")})
    check("ถังเก็บรูปล่ม → ตอบ 503 ไม่แอบเขียนลงเครื่อง", r.status_code == 503,
          f"{r.status_code} {r.text[:150]}")
    use_local()

    r = c.post("/api/uploads", files={"file": ("x.txt", b"not an image", "text/plain")})
    check("ไฟล์ที่ไม่ใช่รูป → ปฏิเสธ", r.status_code == 400, r.status_code)

# ---------------------------------------------------------------- real client
# Everything above swaps in a fake, so nothing has yet proved the actual boto3
# call would even construct. Build the real one — no network, no account.
for field, value in R2_ENV.items():
    setattr(settings, field, value)
storage._client = None
try:
    import boto3  # noqa: F401
except ImportError:
    print("SKIP  ไม่ได้ติดตั้ง boto3 ในเครื่องนี้ (Docker ติดตั้งจาก requirements.txt)")
else:
    try:
        client = storage._get_client()
        check("สร้าง boto3 client ของจริงได้ (ไม่ต่อเน็ต)",
              client.meta.endpoint_url == R2_ENV["r2_endpoint_url"],
              client.meta.endpoint_url)
        check("เซ็นแบบ SigV4 ตามที่ R2 ต้องการ",
              client.meta.config.signature_version == "s3v4",
              client.meta.config.signature_version)
    except Exception as exc:
        check("สร้าง boto3 client ของจริงได้ (ไม่ต่อเน็ต)", False, repr(exc))
storage._client = None
use_local()

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL STORAGE CHECKS PASSED")
sys.exit(1 if fails else 0)
