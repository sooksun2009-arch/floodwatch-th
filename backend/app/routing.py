"""Route flood analysis — the core feature.

Given A and B, answer one question: can I drive this, and what should I look at
before deciding? Three layers of evidence, in the order the user trusts them:

  1. Cameras along the corridor — the user's own eyes, no interpretation needed.
  2. Approved reports within the corridor — crowd evidence, weighted by
     confirmations and age, aggregated into a verdict.
  3. The chatbot, which calls straight into this module.

Routing itself is delegated to an OSRM-compatible HTTP service. When no routing
service answers, we fall back to a straight-line corridor and say so plainly —
a degraded answer labelled as degraded beats no answer during a flood.
"""
import asyncio
import math
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import flood_extent, floodroads
from .config import settings
from .geo import haversine_km, in_thailand
from .models import (
    Camera, FloodReport, LEVEL_RANK, LEVEL_TH, ReportStatus, WaterStation,
)
from .services import (
    camera_to_out, report_confidence, report_to_out, station_to_out,
)

EARTH_KM_PER_DEG = 111.32


# ------------------------------------------------------------------ geometry

def _project(lat: float, lng: float, ref_lat: float) -> tuple[float, float]:
    """Equirectangular projection to kilometres.

    Accurate to well under a metre over the tens of kilometres a city route
    spans, and it turns point-to-segment distance into flat geometry.
    """
    x = lng * EARTH_KM_PER_DEG * math.cos(math.radians(ref_lat))
    y = lat * EARTH_KM_PER_DEG
    return x, y


def point_to_path_km(lat: float, lng: float,
                     path: list[tuple[float, float]]) -> tuple[float, float]:
    """Shortest distance from a point to a polyline, and how far along it that is.

    Returns (distance_km, along_km). `along_km` lets the UI say "กม. ที่ 4.2
    ของเส้นทาง" and order obstacles the way the driver will meet them.
    """
    if not path:
        return float("inf"), 0.0
    if len(path) == 1:
        return haversine_km(lat, lng, path[0][0], path[0][1]), 0.0

    ref_lat = path[len(path) // 2][0]
    px, py = _project(lat, lng, ref_lat)

    best_dist = float("inf")
    best_along = 0.0
    travelled = 0.0

    for i in range(len(path) - 1):
        ax, ay = _project(path[i][0], path[i][1], ref_lat)
        bx, by = _project(path[i + 1][0], path[i + 1][1], ref_lat)
        seg_dx, seg_dy = bx - ax, by - ay
        seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
        seg_len = math.sqrt(seg_len_sq)

        if seg_len_sq == 0:
            t = 0.0
        else:
            t = ((px - ax) * seg_dx + (py - ay) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))

        closest_x, closest_y = ax + t * seg_dx, ay + t * seg_dy
        dist = math.hypot(px - closest_x, py - closest_y)

        if dist < best_dist:
            best_dist = dist
            best_along = travelled + t * seg_len

        travelled += seg_len

    return best_dist, best_along


def path_length_km(path: list[tuple[float, float]]) -> float:
    return sum(haversine_km(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])
               for i in range(len(path) - 1))


def path_bbox(path: list[tuple[float, float]], pad_km: float) -> tuple[float, float, float, float]:
    lats = [p[0] for p in path]
    lngs = [p[1] for p in path]
    mid_lat = (min(lats) + max(lats)) / 2
    d_lat = pad_km / EARTH_KM_PER_DEG
    d_lng = pad_km / max(EARTH_KM_PER_DEG * math.cos(math.radians(mid_lat)), 1e-6)
    return (min(lats) - d_lat, min(lngs) - d_lng, max(lats) + d_lat, max(lngs) + d_lng)


def simplify(path: list[tuple[float, float]], max_points: int = 400) -> list[tuple[float, float]]:
    """Thin a dense OSRM geometry so the corridor scan stays cheap.

    Keeps endpoints; drops evenly in between. Dropping detail can only move the
    polyline by roughly the spacing of the removed points, which is far below
    the corridor width, so verdicts do not change.
    """
    if len(path) <= max_points:
        return path
    step = len(path) / max_points
    thinned = [path[int(i * step)] for i in range(max_points)]
    if thinned[-1] != path[-1]:
        thinned.append(path[-1])
    return thinned


# ------------------------------------------------------------------ route fetching

@dataclass
class RouteGeometry:
    path: list[tuple[float, float]]
    distance_km: float
    duration_min: float
    label: str
    is_straight_line: bool = False
    summary: str = ""


async def _osrm_routes(origin: tuple[float, float], dest: tuple[float, float],
                       alternatives: bool) -> list[RouteGeometry]:
    coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
    url = f"{settings.osrm_base_url.rstrip('/')}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "alternatives": "true" if alternatives else "false",
        "steps": "false",
    }
    async with httpx.AsyncClient(timeout=settings.routing_timeout_sec) as client:
        resp = await client.get(url, params=params,
                                headers={"User-Agent": settings.http_user_agent})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(data.get("message") or "routing service ตอบว่าหาเส้นทางไม่ได้")

    routes: list[RouteGeometry] = []
    for idx, route in enumerate(data["routes"]):
        coordinates = route.get("geometry", {}).get("coordinates") or []
        path = [(c[1], c[0]) for c in coordinates]  # GeoJSON is lng,lat
        if len(path) < 2:
            continue
        routes.append(RouteGeometry(
            path=simplify(path),
            distance_km=round(route.get("distance", 0) / 1000, 2),
            duration_min=round(route.get("duration", 0) / 60, 1),
            label="เส้นทางหลัก" if idx == 0 else f"เส้นทางเลือก {idx}",
        ))
    if not routes:
        raise ValueError("routing service ไม่ส่งเส้นทางที่ใช้ได้กลับมา")
    return routes


def avoid_polygons(db: Session, bbox: tuple[float, float, float, float]) -> dict | None:
    """A MultiPolygon covering the flood points a driver should be routed around.

    Only reports at or above `avoid_min_level` are included, and only those
    inside the search bbox, so the payload stays small enough for the routing
    API to accept. Each point becomes an octagon approximating a circle of
    `avoid_radius_m` — a polygon, because that is what the API takes.
    """
    min_rank = LEVEL_RANK.get(settings.avoid_min_level, 3)
    min_lat, min_lng, max_lat, max_lng = bbox

    rows = db.execute(
        select(FloodReport.lat, FloodReport.lng, FloodReport.level)
        .where(FloodReport.status == ReportStatus.approved.value)
        .where(FloodReport.lat.between(min_lat, max_lat))
        .where(FloodReport.lng.between(min_lng, max_lng))
    ).all()

    blocking = [r for r in rows if LEVEL_RANK.get(r.level, 0) >= min_rank]
    if not blocking:
        return None

    radius_km = settings.avoid_radius_m / 1000
    polygons = []
    for row in blocking[:80]:  # keep the request payload bounded
        d_lat = radius_km / EARTH_KM_PER_DEG
        d_lng = radius_km / max(EARTH_KM_PER_DEG * math.cos(math.radians(row.lat)), 1e-6)
        ring = []
        for i in range(8):
            angle = 2 * math.pi * i / 8
            ring.append([row.lng + d_lng * math.cos(angle), row.lat + d_lat * math.sin(angle)])
        ring.append(ring[0])  # GeoJSON rings must close
        polygons.append([ring])

    return {"type": "MultiPolygon", "coordinates": polygons}


def road_avoid_polygons(analyses: list) -> dict | None:
    """Small boxes around the confident, bad flooded stretches on the routes
    found so far, so a detour is steered off them rather than back onto them.

    Boxes that would swallow an endpoint are dropped later, by
    `drop_polygons_containing` -- see the note there.
    """
    polygons = []
    seen = set()
    pad = 0.00045  # about 50 m either side of the road
    for analysis in analyses:
        for road in analysis.roads:
            if not road["confident"] or road["sedan"] not in ("blocked", "risky"):
                continue
            key = (road["name"], road["along_km"])
            if key in seen:
                continue
            seen.add(key)
            # The road's own extent, padded. It used to be a square as wide as
            # the road was long -- 1.3 km across for a 1.3 km road -- which
            # walled off every side street beside it, and ORS then reported no
            # route at all rather than a detour.
            box = road.get("bbox")
            if box:
                west, south, east, north = box
            else:  # a report pin rather than a stretch
                lat, lng = _point_at_km(analysis.geometry.path, road["along_km"])
                west = east = lng
                south = north = lat
            ring = [[west - pad, south - pad], [east + pad, south - pad],
                    [east + pad, north + pad], [west - pad, north + pad]]
            ring.append(ring[0])
            polygons.append([ring])
            if len(polygons) >= 40:
                break
    return {"type": "MultiPolygon", "coordinates": polygons} if polygons else None


def _point_at_km(path: list[tuple[float, float]], km: float) -> tuple[float, float]:
    done = 0.0
    for a, b in zip(path, path[1:]):
        step = path_length_km([a, b])
        if done + step >= km and step > 0:
            t = (km - done) / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        done += step
    return path[-1]


def _point_in_ring(lat: float, lng: float, ring: list) -> bool:
    """Ray casting. `ring` is GeoJSON order: [lng, lat] pairs."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lng < x_at:
                inside = not inside
    return inside


def drop_polygons_containing(polygons: dict | None,
                             points: list[tuple[float, float]]) -> dict | None:
    """Remove any avoid-area that contains the start or the finish.

    OpenRouteService answers 404 code 2010 -- no routable point found -- when
    an endpoint sits inside an avoided area, and that failure costs the whole
    detour, not just that one area. It happened on the first real route tried:
    the water began 50 m from the origin, so the box around it covered the
    origin. You cannot be routed around the road you are standing on; the
    honest answer there is the verdict, which already says not to go.
    """
    if not polygons:
        return None
    kept = [rings for rings in polygons["coordinates"]
            if not any(_point_in_ring(lat, lng, rings[0]) for lat, lng in points)]
    return {"type": "MultiPolygon", "coordinates": kept} if kept else None


def _merge_polygons(*sources: dict | None) -> dict | None:
    """One MultiPolygon from several, because ORS takes a single avoid shape.

    Reported points and satellite outlines are different kinds of evidence and
    are kept apart everywhere else in this app. They are merged only here, at
    the last step before the request, because the routing engine has one slot
    and "steer around all of this" is the only thing being asked of it. Nothing
    downstream reads which polygon came from where, and nothing about the
    verdict depends on this.
    """
    rings = []
    for source in sources:
        if source and source.get("coordinates"):
            rings.extend(source["coordinates"])
    return {"type": "MultiPolygon", "coordinates": rings} if rings else None


# Why the last detour attempt produced nothing. None once one succeeds.
LAST_ORS_FAILURE: str | None = None

# OpenRouteService error codes worth saying in plain words. A reader looking at
# a flooded route is owed "no way round the water" rather than "code 2009".
ORS_CODE_TH = {
    2009: "ไม่พบเส้นทางที่เลี่ยงจุดน้ำท่วมได้ — น้ำกระจายจนไม่เหลือทางอ้อม",
    2010: "จุดต้นทางหรือปลายทางอยู่ในพื้นที่น้ำท่วมเอง",
    2004: "เกินโควตาการใช้งานของวันนี้",
    2003: "คีย์ไม่มีสิทธิ์ใช้บริการนี้",
    2099: "คีย์ไม่ถูกต้องหรือถูกปฏิเสธ",
}


async def _ors_route(origin: tuple[float, float], dest: tuple[float, float],
                     avoid: dict | None) -> RouteGeometry | None:
    """One route from OpenRouteService, optionally avoiding flooded areas.

    Returns None (rather than raising) on any failure, because this is always
    an *extra* option layered on top of the OSRM result — a missing key, an
    exhausted quota or an unroutable request must not break the main answer.

    Why it failed is recorded in LAST_ORS_FAILURE. Swallowing the reason
    entirely meant a key could be set, the warning about it gone, and still no
    detour appear, with nothing to look at from outside the container.
    """
    global LAST_ORS_FAILURE
    if not settings.ors_api_key:
        LAST_ORS_FAILURE = "ยังไม่ได้ตั้งค่าคีย์"
        return None

    body: dict = {
        "coordinates": [[origin[1], origin[0]], [dest[1], dest[0]]],
        "instructions": False,
    }
    if avoid:
        body["options"] = {"avoid_polygons": avoid}

    try:
        async with httpx.AsyncClient(timeout=settings.routing_timeout_sec) as client:
            resp = await client.post(
                f"{settings.ors_base_url.rstrip('/')}/v2/directions/driving-car/geojson",
                json=body,
                headers={
                    "Authorization": settings.ors_api_key,
                    "Content-Type": "application/json",
                    "User-Agent": settings.http_user_agent,
                },
            )
        if resp.status_code != 200:
            # The status and the upstream's own error code, never its body:
            # ORS echoes the request, which would put the route into the log.
            code = ""
            try:
                code = str(((resp.json() or {}).get("error") or {}).get("code") or "")
            except ValueError:
                pass
            plain = ORS_CODE_TH.get(int(code)) if code.isdigit() else None
            LAST_ORS_FAILURE = plain or f"HTTP {resp.status_code}{f' code {code}' if code else ''}"
            return None
        data = resp.json()
        feature = (data.get("features") or [None])[0]
        if not feature:
            return None
        coordinates = feature.get("geometry", {}).get("coordinates") or []
        path = [(c[1], c[0]) for c in coordinates]
        if len(path) < 2:
            LAST_ORS_FAILURE = "ตอบกลับมาไม่มีเส้นทาง"
            return None
        summary = feature.get("properties", {}).get("summary", {})
        LAST_ORS_FAILURE = None
        return RouteGeometry(
            path=simplify(path),
            distance_km=round(summary.get("distance", 0) / 1000, 2),
            duration_min=round(summary.get("duration", 0) / 60, 1),
            label="เส้นทางเลี่ยงน้ำท่วม" if avoid else "เส้นทางจาก ORS",
        )
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        LAST_ORS_FAILURE = type(exc).__name__
        return None


def _straight_line(origin: tuple[float, float], dest: tuple[float, float]) -> RouteGeometry:
    """Interpolated straight line, used only when no routing service answers."""
    steps = 60
    path = [(origin[0] + (dest[0] - origin[0]) * i / steps,
             origin[1] + (dest[1] - origin[1]) * i / steps) for i in range(steps + 1)]
    dist = haversine_km(*origin, *dest)
    return RouteGeometry(
        path=path, distance_km=round(dist, 2), duration_min=round(dist / 30 * 60, 1),
        label="แนวเส้นตรง (ประมาณการ)", is_straight_line=True,
        summary="ไม่สามารถติดต่อระบบคำนวณเส้นทางได้ จึงใช้แนวเส้นตรงระหว่างต้นทางกับปลายทางแทน",
    )


async def fetch_routes(origin: tuple[float, float], dest: tuple[float, float],
                       alternatives: bool = True) -> tuple[list[RouteGeometry], str | None]:
    """Routes plus a warning string when the result is degraded."""
    try:
        return await _osrm_routes(origin, dest, alternatives), None
    except (httpx.HTTPError, ValueError, KeyError, asyncio.TimeoutError) as exc:
        return ([_straight_line(origin, dest)],
                f"ใช้แนวเส้นตรงประมาณการ เพราะเรียกระบบเส้นทางไม่สำเร็จ ({type(exc).__name__})")


# ------------------------------------------------------------------ corridor analysis

@dataclass
class Obstacle:
    report: FloodReport
    distance_from_route_m: int
    along_km: float


@dataclass
class RouteAnalysis:
    geometry: RouteGeometry
    obstacles: list[Obstacle] = field(default_factory=list)
    cameras: list[tuple[Camera, int, float]] = field(default_factory=list)
    # Gauges near the route that are currently over their bank.
    stations: list[tuple[WaterStation, int, float]] = field(default_factory=list)
    # Flooded stretches along the route, from Floodboard.
    roads: list[dict] = field(default_factory=list)
    verdict: str = "clear"
    worst_level: str | None = None
    score: float = 0.0


VERDICT_ORDER = {"clear": 0, "caution": 1, "risky": 2, "blocked": 3}

VERDICT_TH = {
    "clear": "ไม่พบรายงานน้ำท่วมบนเส้นทาง",
    "caution": "ผ่านได้ แต่มีน้ำขังบางจุด",
    "risky": "เสี่ยง มีจุดน้ำลึกที่รถเก๋งอาจไม่รอด",
    "blocked": "ไม่ควรใช้เส้นทางนี้ มีจุดที่ผ่านไม่ได้",
}


def _verdict_for(levels: list[str]) -> tuple[str, str | None]:
    if not levels:
        return "clear", None
    worst = max(levels, key=lambda lv: LEVEL_RANK.get(lv, 0))
    rank = LEVEL_RANK.get(worst, 0)
    if rank >= LEVEL_RANK["severe"]:
        return "blocked", worst
    if rank == LEVEL_RANK["deep"]:
        return "risky", worst
    if rank >= LEVEL_RANK["puddle"]:
        return "caution", worst
    return "clear", worst


def analyse_route(db: Session, geometry: RouteGeometry, corridor_m: int,
                  camera_corridor_m: int, min_confidence: float,
                  road_segments: list[dict] | None = None) -> RouteAnalysis:
    """Find flood reports and cameras inside the corridor around one route."""
    corridor_km = corridor_m / 1000
    camera_km = camera_corridor_m / 1000
    pad = max(corridor_km, camera_km)
    min_lat, min_lng, max_lat, max_lng = path_bbox(geometry.path, pad)

    reports = db.execute(
        select(FloodReport).options(joinedload(FloodReport.province))
        .where(FloodReport.status == ReportStatus.approved.value)
        .where(FloodReport.lat.between(min_lat, max_lat))
        .where(FloodReport.lng.between(min_lng, max_lng))
    ).unique().scalars().all()

    obstacles: list[Obstacle] = []
    for report in reports:
        # A low-confidence pin (single unverified report, nearly expired) should
        # not by itself turn a route red.
        if report_confidence(report) < min_confidence:
            continue
        dist_km, along_km = point_to_path_km(report.lat, report.lng, geometry.path)
        if dist_km <= corridor_km:
            obstacles.append(Obstacle(report=report,
                                      distance_from_route_m=int(round(dist_km * 1000)),
                                      along_km=round(along_km, 2)))
    obstacles.sort(key=lambda o: o.along_km)

    cameras = db.execute(
        select(Camera).options(joinedload(Camera.province))
        .where(Camera.is_active.is_(True))
        .where(Camera.lat.between(min_lat, max_lat))
        .where(Camera.lng.between(min_lng, max_lng))
    ).unique().scalars().all()

    on_route_cams: list[tuple[Camera, int, float]] = []
    for cam in cameras:
        dist_km, along_km = point_to_path_km(cam.lat, cam.lng, geometry.path)
        if dist_km <= camera_km:
            on_route_cams.append((cam, int(round(dist_km * 1000)), round(along_km, 2)))
    on_route_cams.sort(key=lambda item: item[2])

    # Canal gauges within a wider corridor: a canal overtopping 1 km away is
    # about to put water on this road, even though it is not on it yet.
    station_km = max(corridor_km, 1.0)
    st_min_lat, st_min_lng, st_max_lat, st_max_lng = path_bbox(geometry.path, station_km)
    gauges = db.execute(
        select(WaterStation)
        .where(WaterStation.is_overflowing.is_(True))
        .where(WaterStation.lat.between(st_min_lat, st_max_lat))
        .where(WaterStation.lng.between(st_min_lng, st_max_lng))
    ).scalars().all()

    near_stations: list[tuple[WaterStation, int, float]] = []
    for gauge in gauges:
        dist_km, along_km = point_to_path_km(gauge.lat, gauge.lng, geometry.path)
        if dist_km <= station_km:
            near_stations.append((gauge, int(round(dist_km * 1000)), round(along_km, 2)))
    near_stations.sort(key=lambda item: item[2])

    roads = floodroads.along_route(road_segments or [], geometry.path)

    verdict, worst = _verdict_for([o.report.level for o in obstacles]
                                  + [r["level"] for r in roads])

    # Ranking score for picking a recommended route: penalise blocking severity
    # heavily, then obstacle count, then travel distance.
    score = (VERDICT_ORDER[verdict] * 1000
             + len(obstacles) * 10
             + len(roads) * 5
             + geometry.distance_km)

    return RouteAnalysis(geometry=geometry, obstacles=obstacles, cameras=on_route_cams,
                         stations=near_stations, roads=roads, verdict=verdict,
                         worst_level=worst, score=score)


def build_advice(analysis: RouteAnalysis, degraded: str | None) -> str:
    """Plain-Thai verdict paragraph, the text the chatbot reuses verbatim."""
    geo = analysis.geometry
    lines = [f"{VERDICT_TH[analysis.verdict]} "
             f"(ระยะทาง {geo.distance_km} กม. ใช้เวลาประมาณ {int(geo.duration_min)} นาที)"]

    if analysis.obstacles:
        lines.append("")
        lines.append(f"จุดที่ต้องระวังบนเส้นทาง {len(analysis.obstacles)} จุด:")
        for obs in analysis.obstacles[:8]:
            r = obs.report
            where = r.place or r.district or (r.province.name_th if r.province else "ไม่ระบุจุด")
            depth = f" ลึก {r.depth_cm} ซม." if r.depth_cm else ""
            confirms = f" ยืนยัน {r.confirm_count} ราย" if r.confirm_count else " ยังไม่มีผู้ยืนยัน"
            lines.append(f"• กม. {obs.along_km:.1f} — {where}: "
                         f"{LEVEL_TH.get(r.level, r.level)}.{depth}{confirms}")
        if len(analysis.obstacles) > 8:
            lines.append(f"• และอีก {len(analysis.obstacles) - 8} จุด")

    if analysis.roads:
        sedan_th = {"blocked": "รถเก๋งผ่านไม่ได้", "risky": "รถเก๋งเสี่ยง",
                    "caution": "รถเก๋งผ่านได้ ระวัง", "ok": "ผ่านได้"}
        lines.append("")
        lines.append(f"ถนนน้ำท่วมตามเส้นทาง {len(analysis.roads)} ช่วง (จาก Floodboard):")
        for road in analysis.roads[:8]:
            depth = f" ลึกราว {road['depth_cm']} ซม." if road.get("depth_cm") else ""
            unsure = "" if road["confident"] else " (ความมั่นใจต่ำ)"
            closed = " ปิดการจราจร" if road["closed"] else ""
            lines.append(f"• กม. {road['along_km']:.1f} — {road['name'] or 'ไม่ทราบชื่อถนน'}: "
                         f"{sedan_th.get(road['sedan'], road['sedan'])}{closed}.{depth}{unsure}")
        if len(analysis.roads) > 8:
            lines.append(f"• และอีก {len(analysis.roads) - 8} ช่วง")

    if analysis.cameras:
        lines.append("")
        lines.append(f"กล้อง CCTV ตามเส้นทาง {len(analysis.cameras)} ตัว "
                     "แนะนำให้เปิดดูก่อนออกรถ:")
        for cam, dist_m, along_km in analysis.cameras[:6]:
            demo = " [สตรีมตัวอย่าง]" if cam.is_demo else ""
            lines.append(f"• กม. {along_km:.1f} — {cam.name} "
                         f"(ห่างจากเส้นทาง {dist_m} ม.){demo}")
    else:
        lines.append("")
        lines.append("ยังไม่มีกล้อง CCTV ที่ลงทะเบียนไว้ตามเส้นทางนี้")

    if analysis.stations:
        lines.append("")
        lines.append(f"คลอง/แม่น้ำใกล้เส้นทางที่กำลังล้นตลิ่ง {len(analysis.stations)} จุด:")
        for gauge, dist_m, along_km in analysis.stations[:5]:
            over = f"+{gauge.diff_from_bank:.2f} ม." if gauge.diff_from_bank else ""
            lines.append(f"• กม. {along_km:.1f} — {gauge.name}: สูงกว่าตลิ่ง {over} "
                         f"(ห่างเส้นทาง {dist_m} ม., ข้อมูล {gauge.agency or 'ไม่ระบุหน่วยงาน'})")
        lines.append("ระดับน้ำในคลองที่ล้นตลิ่งมักทำให้ถนนใกล้เคียงท่วมตามในเวลาไม่นาน")

    if analysis.verdict == "clear":
        lines.append("")
        lines.append("ข้อควรทราบ: \"ไม่พบรายงาน\" หมายถึงยังไม่มีใครแจ้งเข้ามา "
                     "ไม่ใช่การยืนยันว่าเส้นทางแห้ง ถ้าคุณขับผ่านแล้วเจอน้ำท่วม "
                     "ช่วยกดแจ้งเพื่อเตือนคนอื่นด้วยครับ")

    if degraded:
        lines.append("")
        lines.append(f"หมายเหตุ: {degraded} ผลที่ได้จึงเป็นการประมาณ ควรตรวจกล้องประกอบ")

    return "\n".join(lines)


async def check_route(db: Session, origin: tuple[float, float], dest: tuple[float, float],
                      corridor_m: int | None = None, camera_corridor_m: int | None = None,
                      min_confidence: float | None = None,
                      alternatives: bool = True) -> dict:
    """Full A-to-B check. Returns a dict ready for the API response model."""
    if not in_thailand(*origin) or not in_thailand(*dest):
        raise ValueError("ต้นทางหรือปลายทางอยู่นอกประเทศไทย")

    corridor_m = corridor_m or settings.route_corridor_m
    camera_corridor_m = camera_corridor_m or settings.route_camera_corridor_m
    min_confidence = settings.route_min_confidence if min_confidence is None else min_confidence

    geometries, degraded = await fetch_routes(origin, dest, alternatives)
    # Loaded once per check and shared by every candidate route. None when the
    # feed is off or has never loaded; the check goes on without it.
    road_segments = await floodroads.segments()
    analyses = [analyse_route(db, geo, corridor_m, camera_corridor_m, min_confidence,
                              road_segments)
                for geo in geometries]

    # If the best route so far still runs through water, ask a routing engine
    # that can steer around it. This only adds an option; the plain routes stay.
    reported_risk = any(
        VERDICT_ORDER[a.verdict] >= VERDICT_ORDER["risky"] for a in analyses)

    # Does the route run through water a satellite actually saw? Asked
    # separately from the reports and kept separate: this is an observation
    # about an area, up to a day old, and a raised road through flooded fields
    # is ordinary here. It is allowed to make this app go and look for a way
    # round; it is never allowed to tell anyone a road is impassable.
    # Read from the tiles, which cover the whole country, rather than from the
    # GeoJSON, whose truncated page covered only the north -- so a route
    # through the worst flooding around Ayutthaya saw nothing at all. None
    # means the question could not be asked and is not treated as a no.
    through_satellite = await flood_extent.route_touches_water(
        analyses[0].geometry.path) is True

    if reported_risk or through_satellite:
        search_bbox = path_bbox(analyses[0].geometry.path, 5.0)
        # Reported points always; satellite outlines only where the feed
        # actually reached, which today is the north and northeast. Absent
        # there, the reported points still steer the detour.
        polygons = drop_polygons_containing(
            _merge_polygons(
                avoid_polygons(db, search_bbox),
                road_avoid_polygons(analyses),
                await flood_extent.avoid_near(search_bbox),
            ),
            [origin, dest],
        )
        if polygons and settings.ors_api_key:
            detour = await _ors_route(origin, dest, polygons)
            if detour:
                detour_analysis = analyse_route(db, detour, corridor_m, camera_corridor_m,
                                                min_confidence, road_segments)
                # Reject a "safe" detour that is absurdly long — past some point
                # waiting the water out beats driving an extra hour.
                if detour_analysis.geometry.distance_km <= analyses[0].geometry.distance_km * 2.5:
                    analyses.append(detour_analysis)
                else:
                    detour_note = (f"มีเส้นทางเลี่ยงแต่ไกลเกินไป ({detour.distance_km} กม. "
                                   f"เทียบกับ {analyses[0].geometry.distance_km} กม.) จึงไม่เสนอ")
                    degraded = f"{degraded} {detour_note}" if degraded else detour_note
            elif LAST_ORS_FAILURE:
                note = f"เรื่องทางเลี่ยง: {LAST_ORS_FAILURE}"
                degraded = f"{degraded} {note}" if degraded else note
        elif settings.ors_api_key and not polygons:
            # Nothing to steer around: the blocking evidence is a road segment
            # too unsure to box, or an area the satellite feed did not cover.
            note = "ยังไม่มีพื้นที่ที่ชัดพอจะใช้คำนวณทางเลี่ยง"
            degraded = f"{degraded} {note}" if degraded else note
        elif polygons:
            note = ("ยังไม่ได้ตั้งค่า OpenRouteService จึงเปรียบเทียบได้เฉพาะเส้นทางสำรองที่มีอยู่ "
                    "ไม่สามารถคำนวณเส้นทางเลี่ยงจุดน้ำท่วมโดยตรง")
            degraded = f"{degraded} {note}" if degraded else note

    # The primary route stays first in the response; the recommendation is
    # whichever route scores best, which may be an alternative.
    best = min(analyses, key=lambda a: a.score)
    primary = analyses[0]

    # Said plainly, because an unexplained detour looks like the app being
    # fussy, and because the honest version of this sentence is the whole
    # point: water was seen from orbit, not on this road, and not today.
    if through_satellite:
        seen = ("เส้นทางนี้ผ่านใกล้พื้นที่ที่ดาวเทียมเห็นน้ำในช่วงหลายวันที่ผ่านมา "
                "ไม่ได้แปลว่าถนนผ่านไม่ได้ และไม่ใช่ภาพสด — "
                "ถ้ามีเส้นเลี่ยงให้เลือก ระบบจะเสนอไว้ด้านล่าง")
        degraded = f"{degraded} {seen}" if degraded else seen

    recommendation = None
    if best is not primary and VERDICT_ORDER[best.verdict] < VERDICT_ORDER[primary.verdict]:
        extra = round(best.geometry.distance_km - primary.geometry.distance_km, 1)
        detour = f"ไกลขึ้น {extra} กม." if extra > 0 else f"สั้นกว่า {abs(extra)} กม."
        recommendation = (f"แนะนำเลี่ยงไปใช้ \"{best.geometry.label}\" แทน "
                          f"({VERDICT_TH[best.verdict]}, {detour})")

    return {
        "origin": {"lat": origin[0], "lng": origin[1]},
        "destination": {"lat": dest[0], "lng": dest[1]},
        "verdict": primary.verdict,
        "verdict_label": VERDICT_TH[primary.verdict],
        "worst_level": primary.worst_level,
        "advice": build_advice(primary, degraded),
        "recommendation": recommendation,
        "degraded": degraded,
        "corridor_m": corridor_m,
        "routes": [
            {
                "label": a.geometry.label,
                "distance_km": a.geometry.distance_km,
                "duration_min": a.geometry.duration_min,
                "is_straight_line": a.geometry.is_straight_line,
                "verdict": a.verdict,
                "verdict_label": VERDICT_TH[a.verdict],
                "worst_level": a.worst_level,
                "is_recommended": a is best,
                "path": [[lat, lng] for lat, lng in a.geometry.path],
                "obstacles": [
                    {
                        "along_km": o.along_km,
                        "distance_from_route_m": o.distance_from_route_m,
                        "report": report_to_out(o.report),
                    } for o in a.obstacles
                ],
                "cameras": [
                    {
                        "along_km": along_km,
                        "distance_from_route_m": dist_m,
                        "camera": camera_to_out(cam),
                    } for cam, dist_m, along_km in a.cameras
                ],
                "stations": [
                    {
                        "along_km": along_km,
                        "distance_from_route_m": dist_m,
                        "station": station_to_out(gauge),
                    } for gauge, dist_m, along_km in a.stations
                ],
                "roads": a.roads,
            } for a in analyses
        ],
        "roads_attribution": (floodroads.ATTRIBUTION
                              if any(a.roads for a in analyses) else None),
    }
