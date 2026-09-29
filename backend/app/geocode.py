"""Turn a typed place name into coordinates.

Order matters: the local gazetteer first (it knows the roads people actually
report floods on, and costs nothing), then Nominatim for everything else. Every
external result is cached in-process, because during a flood the same handful of
place names get typed over and over.
"""
import logging
import threading
from collections import OrderedDict

import httpx
from sqlalchemy.orm import Session

from .chatbot import match_place, normalize
from .config import settings
from .geo import in_thailand

logger = logging.getLogger("floodwatch.geocode")

# How far from the area someone named a result may sit and still be what they
# meant. Generous, because a province centroid is not its centre of population
# and a landmark can be at the far edge of a large province -- but small enough
# that a Bangkok result for a Rayong query is thrown away.
AREA_RADIUS_KM = 120.0


def _near(lat: float, lng: float, to_lat: float, to_lng: float) -> bool:
    from .geo import haversine_km

    return haversine_km(lat, lng, to_lat, to_lng) <= AREA_RADIUS_KM


class _LRU:
    def __init__(self, capacity: int = 512) -> None:
        self._data: OrderedDict[str, tuple[float, float, str] | None] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            if key not in self._data:
                return False, None
            self._data.move_to_end(key)
            return True, self._data[key]

    def put(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._capacity:
                self._data.popitem(last=False)


_cache = _LRU()


async def _nominatim(query: str) -> tuple[float, float, str] | None:
    """OSM's own geocoder.

    Its usage policy is enforced: a User-Agent that does not identify a real
    operator (anything still pointing at example.com) gets HTTP 403. Set
    HTTP_USER_AGENT to a real contact address, or this provider never answers.
    """
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{settings.nominatim_base_url.rstrip('/')}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "th",
                    "accept-language": "th",
                },
                headers={"User-Agent": settings.http_user_agent,
                         "Accept": "application/json"},
            )
        if resp.status_code == 403:
            logger.warning(
                "Nominatim ปฏิเสธคำขอ (403) — ตรวจ HTTP_USER_AGENT ว่าระบุผู้ดูแลจริง "
                "ไม่ใช่ค่าตัวอย่าง; ระบบจะใช้ผู้ให้บริการสำรองแทน")
            return None
        if resp.status_code != 200:
            return None
        results = resp.json()
        if not results:
            return None
        top = results[0]
        found = (float(top["lat"]), float(top["lon"]), top.get("display_name", query))
        return found if in_thailand(found[0], found[1]) else None
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def _photon(query: str) -> tuple[float, float, str] | None:
    """Komoot's OSM geocoder — no key, no User-Agent policy.

    Used as the fallback so a blocked or rate-limited Nominatim does not leave
    the app unable to resolve place names at all. Results are biased toward
    Bangkok, where most queries originate.
    """
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{settings.photon_base_url.rstrip('/')}/api/",
                params={"q": query, "limit": 5, "lang": "default",
                        "lat": 13.7563, "lon": 100.5018},
                headers={"User-Agent": settings.http_user_agent},
            )
        if resp.status_code != 200:
            return None
        for feature in resp.json().get("features", []):
            lng, lat = feature["geometry"]["coordinates"][:2]
            if not in_thailand(lat, lng):
                continue
            props = feature.get("properties", {})
            label = ", ".join(
                part for part in (props.get("name"), props.get("district"),
                                  props.get("city"), props.get("state"))
                if part
            ) or query
            return float(lat), float(lng), label
        return None
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return None


async def _external(query: str) -> tuple[float, float, str] | None:
    """Try each external provider in turn, caching only definitive answers.

    A miss is cached (the name genuinely is not found); a transport failure is
    not, because the next attempt may well succeed.
    """
    hit, cached = _cache.get(query)
    if hit:
        return cached

    for provider in (_nominatim, _photon):
        found = await provider(query)
        if found:
            _cache.put(query, found)
            return found

    _cache.put(query, None)
    return None


def _covers(match_name: str, query: str) -> float:
    """How much of what someone typed the local match actually accounts for.

    "Central Rayong" matched the province Rayong and returned the middle of the
    province — throwing away the word that said which building. From the far
    end that reads as being sent somewhere else, and a user said so. A province
    centroid is a fine answer to "ระยอง" and a poor one to "เซ็นทรัลระยอง".
    """
    name = normalize(match_name or "")
    text = normalize(query or "")
    if not name or not text:
        return 0.0
    return len(name) / max(len(name), len(text))


# Enough of the query accounted for that the local match is the whole answer.
FULL_MATCH = 0.75


def _split_variants(db: Session, query: str) -> list[str]:
    """Ways to say the same query that an external geocoder may handle better.

    Thai is written without spaces between words, so people type
    "เซ็นทรัลระยอง" as one token and no geocoder finds it. Putting the space
    back before a province name costs nothing and is the difference between an
    answer and "not found".
    """
    from .models import Area  # local import: avoids a cycle at module load

    text = query.strip()
    out: list[str] = []
    rows = db.query(Area).filter(Area.kind == "province").all()
    for area in rows:
        for name in (area.name_th, area.name_en):
            if not name or len(name) < 3:
                continue
            idx = text.lower().find(name.lower())
            if idx > 0 and text[idx - 1] not in " ,-":
                spaced = f"{text[:idx]} {text[idx:]}"
                if spaced not in out:
                    out.append(spaced)
    return out


async def resolve_place(db: Session, query: str) -> tuple[float, float, str, str] | None:
    """Return (lat, lng, display_name, source) or None.

    source is "local" when the app's own data answered, "external" otherwise,
    and "area" when the answer is a whole province or district rather than the
    place that was asked for — the UI shows which, so a user can tell a precise
    match from the middle of a province.
    """
    query = query.strip()
    if not query:
        return None

    local = match_place(db, query)
    has_local = local is not None and local.lat is not None and local.lng is not None

    # A local match that accounts for the whole query is the best answer there
    # is: it is a road or a place people actually report floods on.
    if has_local and _covers(local.name, query) >= FULL_MATCH:
        return local.lat, local.lng, local.name, "local"

    if settings.geocode_enabled:
        # The query says more than the area it mentions, so ask someone who
        # might know the building. Spaced variants first: a glued Thai name is
        # the common way this is typed and the common way it is not found.
        attempts = [*_split_variants(db, query), query]
        attempts += [a if "ประเทศไทย" in a else f"{a} ประเทศไทย" for a in list(attempts)]

        seen: set[str] = set()
        for attempt in attempts:
            if attempt in seen:
                continue
            seen.add(attempt)
            found = await _external(attempt)
            if found is None:
                continue
            # Rule: an answer about the wrong place is worse than no answer.
            # If the query named an area and the result is nowhere near it, it
            # is not what was asked for.
            if has_local and not _near(found[0], found[1], local.lat, local.lng):
                logger.info("ทิ้งผลค้นหาที่อยู่ไกลจากพื้นที่ที่ระบุ: %s", found[2][:60])
                continue
            return found[0], found[1], found[2], "external"

    # Nothing better found. A province centre is still useful — it puts the map
    # in the right part of the country — but it is labelled as the area it is,
    # so nobody reads it as the shop they typed.
    if has_local:
        kind = {"province": "ทั้งจังหวัด", "district": "ทั้งอำเภอ/เขต"}.get(local.kind)
        label = f"{local.name} ({kind})" if kind else local.name
        return local.lat, local.lng, label, "area" if kind else "local"

    return None
