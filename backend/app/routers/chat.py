from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import chatbot
from ..config import settings
from ..database import get_db
from ..deps import client_ip, enforce_limit, get_current_user_optional
from ..geocode import resolve_place
from ..models import ChatLog, User
from ..routing import check_route
from ..schemas import ChatIn, ChatOut, RouteCheckOut
from ..services import expire_stale_reports

router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _try_route_answer(db: Session, message: str, lat: float | None,
                            lng: float | None) -> ChatOut | None:
    """Handle "จาก A ไป B ท่วมไหม" questions.

    Returns None when the question is not a route question, or when the
    endpoints cannot be resolved into coordinates — the caller then falls
    through to the ordinary intent router instead of surfacing an error.
    """
    endpoints = chatbot.extract_route_endpoints(message)
    if endpoints is None:
        return None
    origin_text, dest_text = endpoints

    # "จากตรงนี้ไปรามคำแหง" — the origin is the user's own position.
    origin_is_me = bool(chatbot.NEAR_ME_PAT.search(chatbot.normalize(origin_text)))
    if origin_is_me and lat is not None and lng is not None:
        origin, origin_label = (lat, lng), "ตำแหน่งของคุณ"
    else:
        found = await resolve_place(db, origin_text)
        if found is None:
            return None
        origin, origin_label = (found[0], found[1]), found[2]

    dest_found = await resolve_place(db, dest_text)
    if dest_found is None:
        result = chatbot.answer_route_unresolved([dest_text])
        return ChatOut(answer=result.answer, intent=result.intent, engine="rules",
                       suggestions=result.suggestions)
    dest, dest_label = (dest_found[0], dest_found[1]), dest_found[2]

    try:
        raw = await check_route(db, origin, dest)
    except ValueError as exc:
        return ChatOut(
            answer=f"ตรวจเส้นทางไม่สำเร็จครับ: {exc}",
            intent="route_error", engine="rules",
            suggestions=list(chatbot.DEFAULT_SUGGESTIONS),
        )

    raw["origin_label"] = origin_label
    raw["destination_label"] = dest_label
    route = RouteCheckOut.model_validate(raw)

    header = f"เส้นทาง {origin_label} → {dest_label}\n\n"
    answer = header + route.advice
    if route.recommendation:
        answer += f"\n\n{route.recommendation}"

    primary = route.routes[0]
    return ChatOut(
        answer=answer,
        intent="route_check",
        engine="rules",
        matched_place=f"{origin_label} → {dest_label}",
        reports=[o.report for o in primary.obstacles],
        cameras=[c.camera for c in primary.cameras],
        route=route,
        suggestions=[
            chatbot.ChatSuggestion(label="ดูเส้นทางเลี่ยง",
                                   message=f"มีทางเลี่ยงจาก{origin_label}ไป{dest_label}ไหม"),
            chatbot.ChatSuggestion(label="เช็คขากลับ",
                                   message=f"จาก{dest_label}ไป{origin_label} ท่วมไหม"),
            *chatbot.DEFAULT_SUGGESTIONS[1:3],
        ],
    )


@router.post("", response_model=ChatOut)
async def ask(payload: ChatIn, request: Request, db: Session = Depends(get_db),
              user: User | None = Depends(get_current_user_optional)):
    key = f"chat:user:{user.id}" if user else f"chat:ip:{client_ip(request)}"
    enforce_limit(key, settings.chat_limit_per_hour)

    expire_stale_reports(db)
    message = payload.message.strip()

    response = await _try_route_answer(db, message, payload.lat, payload.lng)
    if response is None:
        result = chatbot.route(db, message, payload.lat, payload.lng)
        answer = result.answer

        polished = await chatbot.polish_with_llm(message, result.answer)
        engine = "rules"
        if polished:
            answer, engine = polished, "llm"

        response = ChatOut(
            answer=answer, intent=result.intent, engine=engine,
            matched_place=result.matched_place, reports=result.reports,
            cameras=result.cameras, suggestions=result.suggestions,
        )

    db.add(ChatLog(
        session_id=payload.session_id, user_id=user.id if user else None,
        question=message, answer=response.answer, intent=response.intent,
        matched_place=response.matched_place, engine=response.engine,
    ))
    db.commit()
    return response


@router.get("/starters", response_model=list[dict])
def starters():
    """Suggestion chips shown before the first message."""
    return [s.model_dump() for s in chatbot.DEFAULT_SUGGESTIONS]
