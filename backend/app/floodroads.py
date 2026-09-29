"""Flooded road segments from Floodboard (floodboard.org), CC BY 4.0.

Floodboard publishes, as open data, the roads it currently believes are under
water around Bangkok -- merged from BMA road sensors, Traffy Fondue, Longdo,
news and crowd reports -- each with a depth, a per-vehicle verdict and a
confidence. It is the road-level evidence this app never had: a route through
a flooded soi used to come back "no reports on this route".

Two uses, deliberately different in how much they are trusted:

  * On the map, every segment we keep is drawn, fainter when less certain.
  * In a route check, a segment has to actually run *along* the route (not
    just cross it) to count, and only a confident one may call a route
    blocked. A low-confidence segment can make the verdict "caution" at most:
    most of this feed is inferred, and an app that cries wolf on every street
    gets ignored on the one that matters.

Fetched at most once per cache period and shared by everyone -- one request
every few minutes, not one per visitor -- and the last good copy is kept when
the feed is down, labelled with its age. The licence asks for attribution;
every response that carries this data carries it.
"""
import asyncio
import logging
import math
import time

import httpx

from .config import settings
from .models import LEVEL_RANK

logger = logging.getLogger("floodwatch.floodroads")

ATTRIBUTION = "ข้อมูลถนนน้ำท่วม: Floodboard (floodboard.org), CC BY 4.0"
ATTRIBUTION_URL = "https://floodboard.org"

# A segment's worst verdict for an ordinary car, mapped onto this app's levels.
SEDAN_TO_LEVEL = {"blocked": "severe", "risky": "deep", "caution": "shallow", "ok": "puddle"}

_state: dict = {"at": 0.0, "segments": None, "error": None, "fetched_at": None}
_lock = asyncio.Lock()


def _band(props: dict) -> str:
    """The colour band used on the map legend."""
    if props.get("closedAll"):
        return "closed"
    depth = props.get("depthCm")
    if depth is None:
        return "unknown"
    if depth >= 30:
        return "30"
    if depth >= 20:
        return "20"
    if depth >= 10:
        return "10"
    return "lt10"


# Roads in the air. The feed marks some of them flooded -- the Uttaraphimuk
# tollway at 15 cm, for one -- which reads as an estimate spilling over from
# the surface road underneath, since an elevated deck does not hold water.
ELEVATED_HW = ("motorway", "motorway_link")
ELEVATED_WORDS = ("ทางยกระดับ", "ทางด่วน", "ทางพิเศษ", "expressway", "tollway", "elevated")


def is_elevated(props: dict) -> bool:
    if props.get("hw") in ELEVATED_HW:
        return True
    names = f"{props.get('name') or ''} {props.get('nameEn') or ''}".lower()
    return any(word in names for word in ELEVATED_WORDS)


def slim(feature: dict) -> dict | None:
    """Keep what the map and the route check need, drop the rest (the raw
    observation list carries full news URLs and is most of the file's size)."""
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    if props.get("cleared") or is_elevated(props):
        return None
    conf = float(props.get("conf") or 0)
    if conf < settings.floodroads_min_conf_show:
        return None
    if geom.get("type") == "LineString":
        lines = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiLineString":
        lines = geom.get("coordinates") or []
    else:
        return None
    lines = [[[round(x, 5), round(y, 5)] for x, y, *_ in line] for line in lines if len(line) >= 2]
    if not lines:
        return None
    verdict = props.get("verdict") or {}
    sedan = verdict.get("sedan") or "caution"
    if props.get("closedAll"):
        sedan = "blocked"
    return {
        "name": props.get("name") or props.get("nameEn") or "",
        "name_en": props.get("nameEn") or "",
        "depth_cm": props.get("depthCm"),
        "closed": bool(props.get("closedAll")),
        "sedan": sedan,
        "motorbike": verdict.get("motorbike") or sedan,
        "conf": round(conf, 2),
        "estimated": bool(props.get("estimated") or props.get("inferred")),
        "sources": list(props.get("sources") or [])[:5],
        "updated": props.get("updated"),
        "band": _band(props),
        "lines": lines,
    }


async def _fetch() -> list[dict]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(settings.floodroads_url,
                                headers={"User-Agent": settings.http_user_agent,
                                         "Accept": "application/geo+json"})
        resp.raise_for_status()
        data = resp.json()
    out = []
    for feature in data.get("features") or []:
        seg = slim(feature)
        if seg is not None:
            out.append(seg)
    return out


async def segments() -> list[dict] | None:
    """Current segments, or the last good copy, or None if never loaded."""
    if not settings.floodroads_enabled:
        return None
    now = time.monotonic()
    if _state["segments"] is not None and now - _state["at"] < settings.floodroads_cache_sec:
        return _state["segments"]
    async with _lock:
        if _state["segments"] is not None and time.monotonic() - _state["at"] < settings.floodroads_cache_sec:
            return _state["segments"]
        try:
            found = await _fetch()
            _state.update(at=time.monotonic(), segments=found, error=None,
                          fetched_at=int(time.time()))
        except Exception as exc:  # keep serving the last good copy
            # Only the exception type and status: an upstream body is not ours
            # to repeat.
            detail = (f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                      else type(exc).__name__)
            _state.update(at=time.monotonic(), error=detail)
            logger.warning("ดึงข้อมูลถนนน้ำท่วมจาก Floodboard ไม่สำเร็จ: %s", detail)
    return _state["segments"]


def status() -> dict:
    return {"fetched_at": _state["fetched_at"], "error": _state["error"],
            "count": len(_state["segments"] or [])}


def as_geojson(segs: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "attribution_url": ATTRIBUTION_URL,
        "fetched_at": _state["fetched_at"],
        "stale_error": _state["error"],
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": s["lines"]},
                "properties": {k: v for k, v in s.items() if k not in ("lines", "sources")}
                | {"sources": ",".join(s["sources"])},
            } for s in segs
        ],
    }


# ------------------------------------------------------------ route matching

class _PathIndex:
    """The route as projected segments, bucketed on a grid, so each road point
    is compared with the few route segments near it instead of all of them."""

    CELL_M = 200.0

    def __init__(self, path: list[tuple[float, float]]):
        self.ref_lat = sum(p[0] for p in path) / len(path)
        self.kx = 111_320.0 * math.cos(math.radians(self.ref_lat))
        self.ky = 110_540.0
        pts = [self.xy(lat, lng) for lat, lng in path]
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.segs = list(zip(pts, pts[1:]))
        self.grid: dict[tuple[int, int], list[int]] = {}
        for i, (a, b) in enumerate(self.segs):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // self.CELL_M), int(x1 // self.CELL_M) + 1):
                for gy in range(int(y0 // self.CELL_M), int(y1 // self.CELL_M) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)

    def xy(self, lat: float, lng: float) -> tuple[float, float]:
        return (lng * self.kx, lat * self.ky)

    def nearest(self, lat: float, lng: float) -> tuple[float, float]:
        """(distance m, along km) to the route, or (inf, 0) when far away."""
        px, py = self.xy(lat, lng)
        gx, gy = int(px // self.CELL_M), int(py // self.CELL_M)
        best = (math.inf, 0.0)
        seen: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.grid.get((gx + dx, gy + dy), ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    (ax, ay), (bx, by) = self.segs[i]
                    vx, vy = bx - ax, by - ay
                    length2 = vx * vx + vy * vy
                    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length2))
                    d = math.hypot(px - (ax + t * vx), py - (ay + t * vy))
                    if d < best[0]:
                        best = (d, (self.cum[i] + t * math.sqrt(length2)) / 1000)
        return best


def along_route(segs: list[dict], path: list[tuple[float, float]]) -> list[dict]:
    """Segments that run along this route, with where on it they are.

    "Along", not "near": a flooded side street that merely crosses the route
    touches it at one point and says nothing about the route itself. So at
    least half of a segment's points (and two of them) must lie within the
    corridor.
    """
    if not segs or len(path) < 2:
        return []
    near_m = settings.floodroads_near_m
    lats = [p[0] for p in path]
    lngs = [p[1] for p in path]
    pad = 0.01
    min_lat, max_lat = min(lats) - pad, max(lats) + pad
    min_lng, max_lng = min(lngs) - pad, max(lngs) + pad
    index = None
    found = []
    for seg in segs:
        points = [pt for line in seg["lines"] for pt in line]
        if not any(min_lng <= x <= max_lng and min_lat <= y <= max_lat for x, y in points):
            continue
        if index is None:
            index = _PathIndex(path)
        hits = [index.nearest(y, x) for x, y in points]
        close = [h for h in hits if h[0] <= near_m]
        if len(close) < 2 or len(close) < len(points) / 2:
            continue
        level = SEDAN_TO_LEVEL.get(seg["sedan"], "shallow")
        confident = seg["conf"] >= settings.floodroads_min_conf_block
        # An unsure segment may ask for care; it may not close a road.
        counted = level if confident else ("shallow" if level in ("severe", "deep") else level)
        found.append({
            "name": seg["name"], "name_en": seg["name_en"],
            "depth_cm": seg["depth_cm"], "closed": seg["closed"],
            "sedan": seg["sedan"], "motorbike": seg["motorbike"],
            "conf": seg["conf"], "confident": confident, "estimated": seg["estimated"],
            "sources": seg["sources"], "updated": seg["updated"],
            "level": counted,
            # The stretch's own extent, so a detour can be steered around the
            # road itself rather than a square the size of its length.
            "bbox": [min(x for x, _ in points), min(y for _, y in points),
                     max(x for x, _ in points), max(y for _, y in points)],
            "along_km": round(min(h[1] for h in close), 2),
            "length_m": int(round(sum(
                math.dist(index.xy(a[1], a[0]), index.xy(b[1], b[0]))
                for line in seg["lines"] for a, b in zip(line, line[1:])))),
        })
    # One road is often several touching segments; keep the worst per name
    # and stretch, so the list reads as places, not fragments.
    found.sort(key=lambda s: s["along_km"])
    merged: list[dict] = []
    for seg in found:
        prev = merged[-1] if merged else None
        if prev and prev["name"] == seg["name"] and seg["along_km"] - prev["along_km"] < 0.5:
            total = prev["length_m"] + seg["length_m"]
            if LEVEL_RANK.get(seg["level"], 0) > LEVEL_RANK.get(prev["level"], 0):
                seg["along_km"] = prev["along_km"]
                merged[-1] = seg
            merged[-1]["length_m"] = total
            continue
        merged.append(seg)
    return merged
