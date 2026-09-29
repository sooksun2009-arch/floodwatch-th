"""Blur faces in uploaded flood photos before they are saved.

A flood photo is a picture of a street, and streets have people in them:
someone wading, a neighbour on a doorstep. They did not agree to be on a
public map. So every upload is checked here, in the same pass that already
strips EXIF, and faces are blurred before anything is written -- the
original, unblurred image exists only in memory for this request.

Detector: YuNet (OpenCV Zoo, MIT licence), a 230 KB model that finds faces
down to roughly ten pixels across, which is what a person twenty metres down
a flooded soi looks like in a phone photo. Loaded once, on first use, so the
app does not pay for OpenCV until someone uploads.

What this does not do: licence plates. There is no small model that reads
Thai plates reliably, and a detector that misses half of them would suggest
a protection that is not there. Plates are blurred by the reporter, by
tapping on the photo before sending (see ReportModal).
"""
import logging
import os
import threading

from PIL import Image, ImageFilter

logger = logging.getLogger("floodwatch.faceblur")

MODEL = os.path.join(os.path.dirname(__file__), "data", "face_detection_yunet_2023mar.onnx")

# Low enough to catch a small, side-on face; a blurred patch of wall costs
# nothing, a missed face is the whole failure.
SCORE_THRESHOLD = 0.55
# Grow each box: the detector boxes the face, not the hair and ears that
# still identify someone.
PAD = 0.35

_detector = None
_lock = threading.Lock()
_unavailable: str | None = None


def _get_detector(width: int, height: int):
    global _detector, _unavailable
    if _unavailable:
        return None
    if _detector is None:
        try:
            import cv2  # noqa: WPS433 -- deliberately lazy, it is large
            import numpy as np

            # From bytes, not from a path: OpenCV's file reader cannot open a
            # path with non-ASCII characters on Windows, and this project's
            # folder has Thai in it.
            with open(MODEL, "rb") as handle:
                model = np.frombuffer(handle.read(), np.uint8)
            _detector = cv2.FaceDetectorYN.create("onnx", model, np.array([], np.uint8),
                                                  (width, height), SCORE_THRESHOLD, 0.3, 5000)
        except Exception as exc:  # missing wheel, missing model file
            _unavailable = type(exc).__name__
            logger.error("โหลดตัวตรวจจับใบหน้าไม่สำเร็จ: %s", _unavailable)
            return None
    _detector.setInputSize((width, height))
    return _detector


# Small faces. At the stored size (1600 px) YuNet misses faces under about
# 30 px -- a person twenty-odd metres away. Running it on the whole image at
# twice the size finds them, but measured at 480 MB of memory on a 512 MB
# instance. So the image is enlarged in tiles instead, one at a time, which
# costs time (about a second) rather than memory.
TILE = 400       # source pixels per tile side
OVERLAP = 64     # so a face on a tile edge is whole in at least one tile
UPSCALE = 2


def _detect(frame_rgb: Image.Image) -> list[tuple[float, float, float, float]]:
    import numpy as np

    width, height = frame_rgb.size
    # OpenCV wants BGR; Pillow gives RGB.
    frame = np.ascontiguousarray(np.asarray(frame_rgb)[:, :, ::-1])
    detector = _get_detector(width, height)
    if detector is None:
        raise RuntimeError(_unavailable or "detector unavailable")
    _, faces = detector.detect(frame)
    return [tuple(float(v) for v in face[:4]) for face in (faces if faces is not None else [])]


def _raw_faces(image: Image.Image) -> list[tuple[float, float, float, float]]:
    width, height = image.size
    found = []
    with _lock:  # the detector object is not safe to share across threads
        # Whole image: the large, near faces, which a tile would cut in half.
        found += _detect(image)
        # Enlarged tiles: the small, far ones.
        step = TILE - OVERLAP
        for top in range(0, max(height - OVERLAP, 1), step):
            for left in range(0, max(width - OVERLAP, 1), step):
                box = (left, top, min(left + TILE, width), min(top + TILE, height))
                tile = image.crop(box)
                tile = tile.resize((tile.width * UPSCALE, tile.height * UPSCALE), Image.BICUBIC)
                for x, y, w, h in _detect(tile):
                    found.append((left + x / UPSCALE, top + y / UPSCALE, w / UPSCALE, h / UPSCALE))
    return found


def _boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = image.size
    out = []
    for x, y, w, h in _raw_faces(image):
        px, py = w * PAD, h * PAD
        left = max(0, int(x - px))
        top = max(0, int(y - py * 1.3))  # more room above: hair
        right = min(width, int(x + w + px))
        bottom = min(height, int(y + h + py))
        if right - left >= 4 and bottom - top >= 4:
            out.append((left, top, right, bottom))
    return _merge(out)


def _merge(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """The same face is found by the whole-image pass and by one or two
    tiles. Fold overlapping boxes into their union, so each face is one box
    and the count the reporter sees is the number of people."""
    merged: list[list[int]] = []
    for box in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        for m in merged:
            ix = min(m[2], box[2]) - max(m[0], box[0])
            iy = min(m[3], box[3]) - max(m[1], box[1])
            smaller = min((m[2] - m[0]) * (m[3] - m[1]), (box[2] - box[0]) * (box[3] - box[1]))
            if ix > 0 and iy > 0 and ix * iy >= 0.3 * smaller:
                m[:] = [min(m[0], box[0]), min(m[1], box[1]), max(m[2], box[2]), max(m[3], box[3])]
                break
        else:
            merged.append(list(box))
    return [tuple(m) for m in merged]


def _obscure(region: Image.Image) -> Image.Image:
    """Pixelate, then blur. Blur alone can be partly undone; averaging into a
    handful of blocks first throws the detail away for good."""
    w, h = region.size
    blocks = max(3, min(8, w // 6))
    small = region.resize((blocks, max(3, int(blocks * h / max(w, 1)))), Image.BILINEAR)
    coarse = small.resize((w, h), Image.NEAREST)
    return coarse.filter(ImageFilter.GaussianBlur(radius=max(2, w // 10)))


def blur_faces(image: Image.Image) -> tuple[Image.Image, int | None]:
    """Return (image with faces blurred, number blurred).

    The count is None when the check could not run. The caller decides what
    that means; this function never throws the photo away.
    """
    try:
        boxes = _boxes(image)
    except Exception as exc:
        logger.warning("ตรวจใบหน้าไม่สำเร็จ: %s", type(exc).__name__)
        return image, None
    for left, top, right, bottom in boxes:
        region = image.crop((left, top, right, bottom))
        image.paste(_obscure(region), (left, top))
    return image, len(boxes)


def available() -> bool:
    return _unavailable is None and os.path.exists(MODEL)
