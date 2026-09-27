"""Shared FastAPI dependencies: auth, client identity, rate limiting."""
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Role, User
from .security import decode_access_token


def client_ip(request: Request) -> str:
    """Real client IP behind Railway/Vercel proxies.

    X-Forwarded-For is appended to by each hop, so the left-most entry is the
    original client. It is spoofable by the client, but the proxy in front of us
    rewrites the chain, so the value is good enough for rate limiting.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def get_current_user_optional(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        return None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ต้องเข้าสู่ระบบก่อน",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_moderator(user: User = Depends(get_current_user)) -> User:
    if user.role not in (Role.moderator.value, Role.admin.value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ต้องเป็นผู้ตรวจสอบหรือผู้ดูแลระบบ")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ต้องเป็นผู้ดูแลระบบ")
    return user


class SlidingWindowLimiter:
    """In-process sliding window.

    The app deploys as a single service, so per-process counters are the whole
    picture. Behind multiple replicas this becomes per-replica — move to Redis
    at that point.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_sec: int = 3600) -> bool:
        now = time.monotonic()
        cutoff = now - window_sec
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            # Keep the dict from growing without bound on a long-lived process.
            if len(self._hits) > 20_000:
                for stale_key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale_key]
            return True

    def retry_after(self, key: str, window_sec: int = 3600) -> int:
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(window_sec - (time.monotonic() - hits[0])))


limiter = SlidingWindowLimiter()


def enforce_limit(key: str, limit: int, window_sec: int = 3600) -> None:
    if not limiter.check(key, limit, window_sec):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "ส่งคำขอถี่เกินไป กรุณารอสักครู่",
            headers={"Retry-After": str(limiter.retry_after(key, window_sec))},
        )


def rate_limit_reports(request: Request, user: User | None = Depends(get_current_user_optional)):
    """Anonymous reporters share a per-IP budget; signed-in users get a looser one."""
    if user is None:
        if not settings.allow_anonymous_reports:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "ระบบนี้ต้องเข้าสู่ระบบก่อนแจ้งเหตุ")
        enforce_limit(f"report:ip:{client_ip(request)}", settings.anon_report_limit)
    else:
        enforce_limit(f"report:user:{user.id}", max(settings.anon_report_limit * 4, 20))
    return user
