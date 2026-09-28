"""Visit counting. Public to write, moderators only to read."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import visits
from ..database import get_db
from ..deps import require_moderator

router = APIRouter(prefix="/api/visits", tags=["visits"])


class VisitIn(BaseModel):
    # A short label, not a path: a URL can carry what someone searched for.
    page: str = Field(default="map", max_length=16)
    # The browser's own answer, because it is the only party that knows and the
    # only arrangement where the server keeps nothing about it.
    first_today: bool = False
    # Made up by the tab for this session. Held in memory for ninety seconds to
    # answer "how many are here now" and never written down.
    token: str = Field(default="", max_length=64)


@router.post("", status_code=204)
def record(payload: VisitIn, db: Session = Depends(get_db)) -> None:
    if payload.token:
        visits.mark_online(payload.token)
    visits.record(db, payload.page, payload.first_today)


class PingIn(BaseModel):
    token: str = Field(default="", max_length=64)


@router.post("/ping", status_code=204)
def ping(payload: PingIn) -> None:
    """Still here. Touches memory only — no database write, no counting."""
    if payload.token:
        visits.mark_online(payload.token)


@router.get("/summary", response_model=dict)
def summary(db: Session = Depends(get_db), _=Depends(require_moderator)) -> dict:
    """Behind the moderator login.

    Not because the numbers are sensitive -- they are counts of counts -- but
    because a public figure invites making it go up, and this one is meant to
    answer whether the map reached anyone.
    """
    return visits.summary(db)
