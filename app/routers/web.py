from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.quest import (
    complete_quest,
    drop_quest,
    get_quest_by_id,
    get_quests,
    refill_board,
    reroll_quest,
    take_quest,
)
from app.crud.user import is_underdog
from app.database import get_db
from app.models.quest import QuestStatus
from app.models.user import User
from app.schemas.quest import QuestResponse

router = APIRouter(tags=["Web UI"])
templates = Jinja2Templates(directory="app/templates")


async def get_or_seed_users(session: AsyncSession) -> list[User]:
    """Retrieves all users; if none exist, seeds default participants for local play."""
    res = await session.execute(select(User).order_by(User.total_score.desc()))
    users = list(res.scalars().all())
    if not users:
        u1 = User(
            username="Артур (Капитан)",
            total_score=2400,
            free_drops=settings.DEFAULT_FREE_DROPS,
            rerolls_left=settings.DEFAULT_REROLLS_LEFT,
        )
        u2 = User(
            username="Влад (Игрок)",
            total_score=350,
            free_drops=settings.DEFAULT_FREE_DROPS,
            rerolls_left=settings.DEFAULT_REROLLS_LEFT,
        )
        session.add_all([u1, u2])
        await session.commit()
        res = await session.execute(select(User).order_by(User.total_score.desc()))
        users = list(res.scalars().all())
    return users


def attach_underdog_flags(users: list[User]) -> None:
    """Computes and attaches underdog status to user objects in memory for templates."""
    if not users:
        return
    max_score = max(u.total_score for u in users)
    for u in users:
        u.is_underdog = (max_score - u.total_score) >= settings.UNDERDOG_SCORE_GAP


@router.get("/", response_class=HTMLResponse)
async def index_page(
    request: Request,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Renders the main Kanban board with Guild Dashboard, Quest Exchange, and Active Quests."""
    users = await get_or_seed_users(db)
    attach_underdog_flags(users)

    # Determine currently active user
    current_user = None
    if user_id:
        current_user = next((u for u in users if u.id == user_id), None)
    if not current_user and users:
        current_user = users[0]

    # Fetch available and in-progress quests
    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    db_in_progress = await get_quests(db, status=QuestStatus.IN_PROGRESS)

    # Convert to schema so dynamic inflation current_reward is automatically computed
    available_quests = [QuestResponse.model_validate(q) for q in db_available]
    in_progress_quests = [QuestResponse.model_validate(q) for q in db_in_progress]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "current_user": current_user,
            "users": users,
            "leaderboard": users,
            "available_quests": available_quests,
            "in_progress_quests": in_progress_quests,
        },
    )


@router.post("/quests/{quest_id}/take", response_class=HTMLResponse)
async def web_take_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    form_user_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """User takes a contract. Unpacks Santa gift if present, locks reward, reveals game in active column, refills board."""
    active_uid = user_id or form_user_id
    if not active_uid:
        users = await get_or_seed_users(db)
        active_uid = users[0].id if users else 1

    quest_before = await get_quest_by_id(db, quest_id)
    if not quest_before:
        raise HTTPException(status_code=404, detail="Квест не найден")

    try:
        updated_quest = await take_quest(db, quest_id=quest_id, user_id=active_uid)
        await refill_board(db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch updated available and in-progress quests
    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    db_in_progress = await get_quests(db, status=QuestStatus.IN_PROGRESS)

    available_quests = [QuestResponse.model_validate(q) for q in db_available]
    in_progress_quests = [QuestResponse.model_validate(q) for q in db_in_progress]

    # Render available cards for main #board-container
    board_cards_html = "".join(
        templates.get_template("partials/quest_card.html").render(
            {"request": request, "quest": q}
        )
        for q in available_quests
    )

    # Render active cards with out-of-band swap for #active-quests-container
    active_cards_html = "".join(
        templates.get_template("partials/quest_card.html").render(
            {"request": request, "quest": q}
        )
        for q in in_progress_quests
    )
    if not active_cards_html:
        active_cards_html = """
        <div class="py-8 text-center text-xs text-slate-500 italic bg-black/30 rounded-2xl border border-white/5">
            В данный момент никто не выполняет квесты.<br>Возьмите контракт на бирже слева!
        </div>
        """

    oob_active = f'<div id="active-quests-container" class="space-y-3" hx-swap-oob="innerHTML">{active_cards_html}</div>'

    return HTMLResponse(content=board_cards_html + oob_active)


@router.post("/quests/{quest_id}/drop")
async def web_drop_quest(
    quest_id: int,
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """User drops active quest. Returns 200 empty body so HTMX removes the card from active quests."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        return Response(status_code=200, content="")

    uid = user_id or quest.user_id
    if uid:
        await drop_quest(db, quest_id=quest_id, user_id=uid)

    return Response(status_code=200, content="")


@router.post("/quests/{quest_id}/complete")
async def web_complete_quest(
    quest_id: int,
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """User completes active quest. Awards points and removes card from in-progress list."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        return Response(status_code=200, content="")

    uid = user_id or quest.user_id
    if uid:
        await complete_quest(db, quest_id=quest_id, user_id=uid)

    return Response(status_code=200, content="")


@router.post("/quests/{quest_id}/reroll", response_class=HTMLResponse)
async def web_reroll_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Performs roulette reroll and returns updated card HTML."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    uid = user_id or quest.user_id or 1
    updated_quest = await reroll_quest(db, quest_id=quest_id, user_id=uid)
    quest_resp = QuestResponse.model_validate(updated_quest)

    return templates.TemplateResponse(
        "partials/quest_card.html",
        {"request": request, "quest": quest_resp},
    )


@router.post("/quests/refill-board", response_class=HTMLResponse)
async def web_refill_board(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Refills board to 12 slots and returns updated available quest cards."""
    await refill_board(db)
    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    available_quests = [QuestResponse.model_validate(q) for q in db_available]

    html_parts = [
        templates.get_template("partials/quest_card.html").render(
            {"request": request, "quest": q}
        )
        for q in available_quests
    ]
    return HTMLResponse(content="".join(html_parts))
