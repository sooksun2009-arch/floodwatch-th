"""Faces in uploaded photos are blurred before the file is written.

Checked on the stored file itself, not on the count the API reports: a
counter that says "1 face blurred" over an untouched face is the failure
that matters.
"""
import io
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/f.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SYNC_STATIONS_ON_START"] = "false"
os.environ["FLOODROADS_ENABLED"] = "false"

from fastapi.testclient import TestClient
from PIL import Image, ImageStat

from app import faceblur
from app.config import settings
from app.main import app

fails = []
HERE = os.path.dirname(__file__)
# NASA portrait (public domain), via scikit-image's sample data.
PORTRAIT = os.path.join(HERE, "testdata", "astronaut.jpg")
FACE_BOX = (170, 40, 290, 180)  # where the face is in that picture


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"\n      -> {extra}"))
    if not cond:
        fails.append(name)


def jpeg(image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def detail(image, box):
    """Mean edge strength in a region: high for a face, near zero once blurred."""
    from PIL import ImageFilter
    return ImageStat.Stat(image.crop(box).convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]


portrait = Image.open(PORTRAIT).convert("RGB")

with TestClient(app) as c:
    r = c.post("/api/uploads", files={"file": ("p.jpg", jpeg(portrait), "image/jpeg")})
    check("อัปโหลดรูปที่มีหน้าคนได้", r.status_code == 201, r.text[:200])
    body = r.json()
    check("บอกจำนวนหน้าที่เบลอ = 1", body.get("faces_blurred") == 1, body)

    stored = Image.open(os.path.join(settings.upload_dir, body["url"].rsplit("/", 1)[1]))
    before, after = detail(portrait, FACE_BOX), detail(stored, FACE_BOX)
    check("ใบหน้าในไฟล์ที่บันทึกถูกเบลอจริง (รายละเอียดหายไปมาก)", after < before * 0.35,
          f"ก่อน {before:.1f} หลัง {after:.1f}")
    # The rest of the picture is the flood evidence; it must survive.
    rest = (20, 300, 140, 480)
    check("ส่วนอื่นของรูปไม่ถูกเบลอ", detail(stored, rest) > detail(portrait, rest) * 0.6,
          f"{detail(portrait, rest):.1f} -> {detail(stored, rest):.1f}")

    # A small face, as in a street photo: 24 px across in a 1600 px image.
    street = Image.new("RGB", (1600, 1200), (120, 130, 140))
    street.paste(portrait.crop((150, 20, 300, 190)).resize((24, 27)), (800, 600))
    r = c.post("/api/uploads", files={"file": ("s.jpg", jpeg(street), "image/jpeg")})
    check("หน้าเล็ก ๆ ไกล ๆ ในรูปถนนก็เจอ", r.json().get("faces_blurred") == 1, r.json())

    r = c.post("/api/uploads", files={"file": ("n.jpg", jpeg(Image.new("RGB", (1200, 900), (90, 110, 140))), "image/jpeg")})
    check("รูปไม่มีคน -> ไม่เบลออะไร", r.json().get("faces_blurred") == 0, r.json())

    # The detector unavailable: the photo is still accepted, and says so.
    saved_state = faceblur._unavailable
    faceblur._unavailable = "ImportError"
    r = c.post("/api/uploads", files={"file": ("p.jpg", jpeg(portrait), "image/jpeg")},
               headers={"x-forwarded-for": "9.9.9.9"})
    check("ตัวตรวจใช้ไม่ได้ -> ยังรับรูป ไม่ทำให้แจ้งน้ำท่วมไม่ได้", r.status_code == 201, r.text[:200])
    check("และบอกว่าไม่ได้ตรวจ (null ไม่ใช่ 0)", r.json().get("faces_blurred") is None, r.json())
    faceblur._unavailable = saved_state

print()
print("=" * 60)
print(f"{len(fails)} FAILED" if fails else "ALL FACE-BLUR CHECKS PASSED")
sys.exit(1 if fails else 0)
