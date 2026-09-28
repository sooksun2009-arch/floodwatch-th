"""How many people opened the app, counted without keeping anything about them.

The site tells visitors it does not store the routes they search or keep a
travel history. A visitor counter must not quietly make that untrue, so this
one holds no row per person and no address of any kind. What is stored is two
integers per hour: how many page opens, and how many of those were a browser's
first open that day.

"First open today" is decided by the browser itself, which remembers only its
own last counted date. Nothing identifies it to the server, and nothing here
can be turned back into a person. The cost is that a cleared browser or a
private window counts again, so the unique figure is a floor rather than a
measurement -- which is the right way round for a number nobody is billed on.

Who is here *now* is held in memory and never written down: an id the browser
made up for this tab, dropped as soon as it stops checking in. A restart of the
instance forgets it, and that is fine, because it is a number about right now.
"""
import time
from datetime import date, datetime, timezone

from sqlalchemy import Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import Base

# How long a tab counts as "here" after its last check-in. Long enough to
# survive a slow connection, short enough that the number means now.
ONLINE_TTL_SEC = 90

# A page name is a short label chosen from this list, never a path or a query
# string: a URL can carry what someone searched for, and this file exists on
# the promise that it does not learn that.
PAGES = ("map", "cameras", "stats", "admin", "login", "other")


class VisitStat(Base):
    """One row per hour. Counts only."""

    __tablename__ = "visit_stats"
    __table_args__ = (UniqueConstraint("day", "hour", "page", name="uq_visit_hour"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    hour: Mapped[int] = mapped_column(Integer)
    page: Mapped[str] = mapped_column(String(16))
    views: Mapped[int] = mapped_column(Integer, default=0)
    visitors: Mapped[int] = mapped_column(Integer, default=0)


_online: dict[str, float] = {}


def mark_online(token: str) -> None:
    """Remember that a tab checked in, and forget the ones that stopped."""
    now = time.monotonic()
    _online[token[:64]] = now
    if len(_online) > 5000:  # a burst, or something looping; keep it bounded
        for key, seen in list(_online.items()):
            if now - seen > ONLINE_TTL_SEC:
                _online.pop(key, None)


def online_now() -> int:
    now = time.monotonic()
    return sum(1 for seen in _online.values() if now - seen <= ONLINE_TTL_SEC)


def record(db: Session, page: str, first_today: bool) -> None:
    """Add one view, and one visitor if the browser says it is new today."""
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    page = page if page in PAGES else "other"

    row = db.execute(
        select(VisitStat).where(
            VisitStat.day == day, VisitStat.hour == now.hour, VisitStat.page == page)
    ).scalar_one_or_none()

    if row is None:
        row = VisitStat(day=day, hour=now.hour, page=page, views=0, visitors=0)
        db.add(row)

    row.views += 1
    if first_today:
        row.visitors += 1
    db.commit()


def summary(db: Session, days: int = 14) -> dict:
    """Totals by day and by hour for today, plus who is here now."""
    today = date.today().strftime("%Y-%m-%d")

    by_day = db.execute(
        select(VisitStat.day,
               func.sum(VisitStat.views),
               func.sum(VisitStat.visitors))
        .group_by(VisitStat.day)
        .order_by(VisitStat.day.desc())
        .limit(days)
    ).all()

    by_hour = db.execute(
        select(VisitStat.hour, func.sum(VisitStat.views))
        .where(VisitStat.day == today)
        .group_by(VisitStat.hour)
        .order_by(VisitStat.hour)
    ).all()

    by_page = db.execute(
        select(VisitStat.page, func.sum(VisitStat.views))
        .where(VisitStat.day == today)
        .group_by(VisitStat.page)
        .order_by(func.sum(VisitStat.views).desc())
    ).all()

    return {
        "online_now": online_now(),
        "today": today,
        "days": [{"day": d, "views": int(v or 0), "visitors": int(u or 0)}
                 for d, v, u in reversed(by_day)],
        "hours": [{"hour": int(h), "views": int(v or 0)} for h, v in by_hour],
        "pages": [{"page": p, "views": int(v or 0)} for p, v in by_page],
    }
