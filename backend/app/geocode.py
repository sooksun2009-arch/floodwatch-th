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

from .chatbot import match_place
from .config import settings
from .geo import in_thailand

logger = logging.getLogger("floodwatch.geocode")


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


async def resolve_place(db: Session, query: str) -> tuple[float, float, str, str] | None:
    """Return (lat, lng, display_name, source) or None.

    source is "local" when the app's own data answered, "nominatim" otherwise —
    the UI shows which, so a user can tell a precise match from a guess.
    """
    query = query.strip()
    if not query:
        return None

    local = match_place(db, query)
    if local is not None and local.lat is not None and local.lng is not None:
        return local.lat, local.lng, local.name, "local"

    if not settings.geocode_enabled:
        return None

    # Bias the lookup toward Thailand even for a bare road name, then retry
    # with the raw query in case the added words hurt the match.
    found = await _external(query if "ประเทศไทย" in query else f"{query} ประเทศไทย")
    if found is None:
        found = await _external(query)
    if found is None:
        return None
    return found[0], found[1], found[2], "external"
