"""Geo helpers.

Deliberately no PostGIS: every query here is either a bounding box (which a
plain b-tree index on lat/lng serves) or a distance sort over a bbox-reduced
candidate set. That keeps the app deployable on any stock Postgres.
"""
import math

EARTH_RADIUS_KM = 6371.0

# กรอบคร่าว ๆ ของประเทศไทย ใช้ตรวจว่าพิกัดที่ส่งมาเป็นไปได้จริง
THAILAND_BBOX = (5.4, 97.2, 20.6, 105.7)  # min_lat, min_lng, max_lat, max_lng


def in_thailand(lat: float, lng: float) -> bool:
    min_lat, min_lng, max_lat, max_lng = THAILAND_BBOX
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bbox_around(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Bounding box that fully contains the circle, for cheap SQL pre-filtering."""
    d_lat = radius_km / 111.32
    # Longitude degrees shrink toward the poles; clamp cos to avoid blowing up.
    d_lng = radius_km / max(111.32 * math.cos(math.radians(lat)), 1e-6)
    return (lat - d_lat, lng - d_lng, lat + d_lat, lng + d_lng)


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    """Parse "min_lat,min_lng,max_lat,max_lng". Raises ValueError when malformed."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox ต้องมี 4 ค่า: min_lat,min_lng,max_lat,max_lng")
    min_lat, min_lng, max_lat, max_lng = (float(p) for p in parts)
    if min_lat > max_lat or min_lng > max_lng:
        raise ValueError("bbox กลับด้าน: ค่า min ต้องน้อยกว่า max")
    return min_lat, min_lng, max_lat, max_lng
