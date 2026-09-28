"""Spend limits and response caching for calls to metered third parties.

Lifted out of ``rain.py`` when a second provider arrived. The rules here were
paid for once already: the radar tile proxy had a per-tile cache and no budget,
a few minutes of panning emptied the whole key's daily allowance, and the
camera list and the forecast — two features nobody was panning — went down with
it. Copying that code to the next provider would have meant copying the fix and
then maintaining two of them.

Two ideas, deliberately separate:

* A **cache** stops the *same* thing being fetched twice. It does nothing about
  volume, because a map being panned asks for a different tile every time.
* A **budget** caps how many calls leave at all. It is refused locally, because
  a request refused here costs nothing and cannot deepen the limit that caused
  the refusal.

Every caller keeps its own budgets. Sharing one across providers would let a
quiet provider's ceiling be set by a noisy one's traffic.
"""
import asyncio
import time
from dataclasses import dataclass


class QuotaExhausted(Exception):
    """Refused before the request left. Carries the numbers, because "quota
    exhausted" without them cannot be told from a wrong key."""


class Budget:
    """A spend limit for outbound calls, per minute and per day.

    Keep separate instances for cheap high-volume calls (tiles) and for the
    ones someone is actually waiting on (a lookup, a forecast). Sharing one
    lets the first starve the second, which is the failure this exists to
    prevent.
    """

    def __init__(self, per_min: int, per_day: int):
        self.per_min = per_min
        self.per_day = per_day
        self.minute = 0.0
        self.minute_used = 0
        self.day = 0.0
        self.day_used = 0

    def take(self) -> bool:
        now = time.time()
        if now - self.minute >= 60:
            self.minute, self.minute_used = now, 0
        if now - self.day >= 86400:
            self.day, self.day_used = now, 0
        if self.minute_used >= self.per_min or self.day_used >= self.per_day:
            return False
        self.minute_used += 1
        self.day_used += 1
        return True

    def state(self) -> dict:
        return {"per_min": self.per_min, "used_this_min": self.minute_used,
                "per_day": self.per_day, "used_today": self.day_used}

    def spend(self, what: str) -> None:
        """Take one, or raise saying how much is gone and over which window."""
        if not self.take():
            raise QuotaExhausted(
                f"ใช้โควตา{what}ครบแล้ว "
                f"({self.minute_used}/{self.per_min} ต่อนาที, "
                f"{self.day_used}/{self.per_day} ต่อวัน)")


@dataclass
class _Entry:
    at: float
    value: object


class Cache:
    """Time-limited responses, with one in-flight fetch per key.

    The per-key lock is the part that matters: without it a burst of route
    checks during a storm — exactly when this is busiest — would each miss the
    cache and each spend a call, which is the moment the budget can least
    afford it.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def get(self, key: str, ttl: float, produce):
        now = time.monotonic()
        hit = self._entries.get(key)
        if hit and now - hit.at < ttl:
            return hit.value

        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            hit = self._entries.get(key)
            if hit and time.monotonic() - hit.at < ttl:
                return hit.value
            value = await produce()
            self._entries[key] = _Entry(at=time.monotonic(), value=value)
            return value

    def clear(self) -> None:
        """Drop everything, entries and locks alike.

        The locks go too: leaving them behind keeps one asyncio.Lock per key
        that was ever fetched, bound to the loop it was created on, which in
        tests means a lock from a closed loop guarding the next test's fetch.
        """
        self._entries.clear()
        self._locks.clear()


def strip_secret(text: str, secret: str) -> str:
    """Take our key back out of upstream's words before anyone else reads them.

    Error bodies quote the request back, so a 403's text can carry the key that
    was refused. This runs on every path that returns upstream text to a client
    or writes it where a client can read it.
    """
    return text.replace(secret, "<คีย์>") if secret else text
