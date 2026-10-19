import json
from datetime import datetime, timezone
from pathlib import Path
import random
import re
import shutil
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.crud.challenge import get_random_challenges
from app.crud.quest import (
    complete_quest,
    drop_quest,
    get_quest_by_id,
    get_quests,
    get_user_active_quest,
    refill_board,
    reroll_quest,
    set_quest_challenge,
    take_quest,
)
from app.crud.user import is_underdog
from app.database import get_db
from app.models.challenge import Challenge
from app.models.game import Game
from app.models.quest import Quest, QuestStatus
from app.models.user import User
from app.schemas.quest import QuestResponse
from app.services.games_db import query_games_from_parser_db, sync_game_to_hpg, resolve_single_image_url

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
            avatar_url="/static/avatars/artur.svg",
            pin_code="1111",
        )
        u2 = User(
            username="Влад (Игрок)",
            total_score=350,
            free_drops=settings.DEFAULT_FREE_DROPS,
            rerolls_left=settings.DEFAULT_REROLLS_LEFT,
            avatar_url="/static/avatars/vlad.svg",
            pin_code="2222",
        )
        session.add_all([u1, u2])
        await session.commit()
        res = await session.execute(select(User).order_by(User.total_score.desc()))
        users = list(res.scalars().all())
    else:
        # Guarantee avatar_url and pin_code exist for existing users
        updated = False
        for u in users:
            if not u.avatar_url:
                if "Артур" in u.username:
                    u.avatar_url = "/static/avatars/artur.svg"
                elif "Влад" in u.username:
                    u.avatar_url = "/static/avatars/vlad.svg"
                else:
                    u.avatar_url = "/static/avatars/default.svg"
                updated = True
            if not u.pin_code:
                if "Артур" in u.username:
                    u.pin_code = "1111"
                elif "Влад" in u.username:
                    u.pin_code = "2222"
                else:
                    u.pin_code = "1234"
                updated = True
        if updated:
            await session.commit()
    return users


def attach_underdog_flags(users: list[User]) -> None:
    """Computes and attaches underdog status to user objects in memory for templates."""
    if not users:
        return
    max_score = max(u.total_score for u in users)
    for u in users:
        u.is_underdog = (max_score - u.total_score) >= settings.UNDERDOG_SCORE_GAP


async def get_board_context(
    request: Request,
    user_id: Optional[int],
    db: AsyncSession,
) -> dict:
    """Helper that prepares unified context for rendering the Kanban board."""
    users = await get_or_seed_users(db)
    attach_underdog_flags(users)

    # Determine currently active user from session cookie (first priority) or fallback param
    current_user = None
    cookie_uid = request.cookies.get("session_user_id")
    if cookie_uid and cookie_uid.isdigit():
        current_user = next((u for u in users if u.id == int(cookie_uid)), None)
    if not current_user and user_id:
        current_user = next((u for u in users if u.id == user_id), None)
    if not current_user and users:
        current_user = users[0]

    # Fetch available and in-progress quests
    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    db_in_progress = await get_quests(db, status=QuestStatus.IN_PROGRESS)

    # Convert to schema so dynamic inflation current_reward is automatically computed
    available_quests = [QuestResponse.model_validate(q) for q in db_available]
    raw_in_progress = [QuestResponse.model_validate(q) for q in db_in_progress]

    # Сортировка: квесты текущего игрока всегда выводятся выше квестов других игроков
    user_active_quests = [q for q in raw_in_progress if current_user and q.user_id == current_user.id]
    other_active_quests = [q for q in raw_in_progress if not current_user or q.user_id != current_user.id]

    user_active_quests.sort(key=lambda q: q.started_at.timestamp() if q.started_at else q.id, reverse=True)
    other_active_quests.sort(key=lambda q: q.started_at.timestamp() if q.started_at else q.id, reverse=True)

    in_progress_quests = user_active_quests + other_active_quests
    user_active_count = len(user_active_quests)
    user_can_take_quest = user_active_count < settings.MAX_ACTIVE_QUESTS

    return {
        "request": request,
        "current_user": current_user,
        "users": users,
        "leaderboard": users,
        "available_quests": available_quests,
        "in_progress_quests": in_progress_quests,
        "user_active_quests": user_active_quests,
        "other_active_quests": other_active_quests,
        "user_active_count": user_active_count,
        "user_can_take_quest": user_can_take_quest,
        "max_active_quests": settings.MAX_ACTIVE_QUESTS,
        "active_page": "board",
    }


@router.get("/")
async def index_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Renders the main Witcher Notice Board or redirects to login."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid:
        return RedirectResponse("/login", status_code=303)
    ctx = await get_board_context(request, None, db)
    return templates.TemplateResponse("index.html", ctx)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Login and registration page for hunters."""
    users = await get_or_seed_users(db)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "users": users,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    pin_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Authenticates user with username & 4-digit PIN/password, setting HTTP-only session cookie."""
    stmt = select(User).where(User.username == username.strip())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        return HTMLResponse(
            content='<div class="p-3 rounded-xl bg-red-950/90 border border-red-500 text-red-200 text-xs font-semibold shake-anim shadow text-center">Неверный логин или пароль!</div>',
            status_code=200,
        )

    # Check PIN if user configured one
    if user.pin_code:
        clean_pin = (pin_code or "").strip()
        if clean_pin != user.pin_code:
            return HTMLResponse(
                content='<div class="p-3 rounded-xl bg-red-950/90 border border-red-500 text-red-200 text-xs font-semibold shake-anim shadow text-center">Неверный логин или пароль!</div>',
                status_code=200,
            )

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        resp = Response(status_code=200, headers={"HX-Redirect": "/board"})
    else:
        resp = RedirectResponse("/board", status_code=303)

    resp.set_cookie(
        key="session_user_id",
        value=str(user.id),
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
        path="/",
    )
    return resp


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    pin_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Registers a new hunter profile and logs them in."""
    clean_name = username.strip()
    if not clean_name or len(clean_name) < 2:
        return HTMLResponse(
            content='<div class="p-2 rounded-lg bg-red-950/90 border border-red-500 text-red-200 text-xs font-semibold shake-anim text-center">Имя должно содержать от 2 символов!</div>',
            status_code=200,
        )

    stmt = select(User).where(User.username == clean_name)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return HTMLResponse(
            content='<div class="p-2 rounded-lg bg-red-950/90 border border-red-500 text-red-200 text-xs font-semibold shake-anim text-center">Игрок с таким именем уже зарегистрирован!</div>',
            status_code=200,
        )

    clean_pin = pin_code.strip() if pin_code else None
    if clean_pin and (not clean_pin.isdigit() or len(clean_pin) != 4):
        return HTMLResponse(
            content='<div class="p-2 rounded-lg bg-red-950/90 border border-red-500 text-red-200 text-xs font-semibold shake-anim text-center">ПИН должен состоять из 4 цифр!</div>',
            status_code=200,
        )

    new_user = User(
        username=clean_name,
        pin_code=clean_pin,
        avatar_url="/static/avatars/default.svg",
        total_score=0,
        free_drops=settings.DEFAULT_FREE_DROPS,
        rerolls_left=settings.DEFAULT_REROLLS_LEFT,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        resp = Response(status_code=200, headers={"HX-Redirect": "/board"})
    else:
        resp = RedirectResponse("/board", status_code=303)

    resp.set_cookie(
        key="session_user_id",
        value=str(new_user.id),
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
        path="/",
    )
    return resp


@router.get("/logout")
async def logout_user():
    """Logs out hunter by clearing session cookie and redirecting to /login."""
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(key="session_user_id", path="/")
    return resp


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Renders the logged-in hunter's Personal Cabinet (Личный кабинет)."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid or not cookie_uid.isdigit():
        return RedirectResponse("/login", status_code=303)

    users = await get_or_seed_users(db)
    attach_underdog_flags(users)

    current_user = next((u for u in users if u.id == int(cookie_uid)), None)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    active_quest = await get_user_active_quest(db, current_user.id)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": current_user,
            "current_user": current_user,
            "active_quest": active_quest,
            "leaderboard": users,
            "active_page": "profile",
        },
    )


@router.post("/profile/avatar", response_class=HTMLResponse)
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Processes uploaded avatar file for the authenticated user, saving uniquely to static/avatars."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid or not cookie_uid.isdigit():
        raise HTTPException(status_code=401, detail="Не авторизован")

    user = await db.get(User, int(cookie_uid))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # 1. Проверить расширение файла (jpg, png, webp)
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        return HTMLResponse(
            content='<div class="text-xs text-red-400 font-bold p-2 bg-red-950/80 rounded border border-red-600">Поддерживаются только форматы: JPG, PNG, WEBP!</div>',
            status_code=400,
        )

    # 2. Сгенерировать уникальное имя
    clean_username = re.sub(r"[^a-zA-Z0-9_\-а-яА-ЯёЁ]", "_", user.username)
    unique_id = uuid.uuid4().hex[:8]
    unique_filename = f"{clean_username}_{unique_id}.{ext}"

    # 3. Сохранить файл в папку static/avatars/ с помощью shutil.copyfileobj
    avatars_dir = Path("static/avatars")
    avatars_dir.mkdir(parents=True, exist_ok=True)
    file_path = avatars_dir / unique_filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 4. Обновить поле avatar_url у пользователя в базе
    avatar_url = f"/static/avatars/{unique_filename}"
    user.avatar_url = avatar_url
    await db.commit()
    await db.refresh(user)

    # 5. Вернуть HTML-фрагмент с новой картинкой для HTMX-обновления
    return HTMLResponse(
        content=f'<img id="avatar-preview-img" src="{avatar_url}" alt="{user.username}" class="w-full h-full object-cover">'
                f'<span class="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500 text-[11px] font-bold text-emerald-200 shadow">✓ Сохранено</span>'
    )


@router.post("/profile/pin", response_class=HTMLResponse)
async def update_pin(
    request: Request,
    pin_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Updates the authenticated user's 4-digit PIN code without echoing it back."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid or not cookie_uid.isdigit():
        raise HTTPException(status_code=401, detail="Не авторизован")

    user = await db.get(User, int(cookie_uid))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    clean_pin = pin_code.strip() if pin_code else None
    if clean_pin and (not clean_pin.isdigit() or len(clean_pin) != 4):
        return HTMLResponse(
            content='<span class="text-xs text-red-400 font-bold shake-anim">ПИН должен состоять ровно из 4 цифр!</span>',
            status_code=200,
        )

    user.pin_code = clean_pin
    await db.commit()
    msg = "ПИН-код успешно сохранен!" if clean_pin else "ПИН-код удален!"
    return HTMLResponse(
        content=f'<span class="text-xs text-emerald-400 font-bold">✓ {msg}</span>'
    )


@router.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Renders the dedicated tournament leaderboard and podium page."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid:
        return RedirectResponse("/login", status_code=303)

    users = await get_or_seed_users(db)
    attach_underdog_flags(users)

    current_user = None
    if cookie_uid and cookie_uid.isdigit():
        current_user = next((u for u in users if u.id == int(cookie_uid)), None)
    if not current_user and users:
        current_user = users[0]

    # Query quest stats per user (COMPLETED, IN_PROGRESS, DROPPED)
    stats_stmt = (
        select(Quest.user_id, Quest.status, func.count(Quest.id))
        .where(Quest.user_id.is_not(None))
        .group_by(Quest.user_id, Quest.status)
    )
    quest_stats = (await db.execute(stats_stmt)).all()
    user_counts = {}
    for uid, q_status, count in quest_stats:
        if uid not in user_counts:
            user_counts[uid] = {}
        s_val = q_status.value if hasattr(q_status, "value") else str(q_status)
        user_counts[uid][s_val] = count

    max_score = users[0].total_score if users else 0
    total_completed_all = 0
    total_score_all = 0
    for u in users:
        c = user_counts.get(u.id, {})
        u.completed_quests_count = c.get("COMPLETED", 0)
        u.in_progress_quests_count = c.get("IN_PROGRESS", 0)
        u.dropped_quests_count = c.get("DROPPED", 0)
        u.score_gap = max(0, max_score - u.total_score)
        total_completed_all += u.completed_quests_count
        total_score_all += u.total_score

    top_1 = users[0] if len(users) > 0 else None
    top_2 = users[1] if len(users) > 1 else None
    top_3 = users[2] if len(users) > 2 else None

    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "current_user": current_user,
            "leaderboard": users,
            "top_1": top_1,
            "top_2": top_2,
            "top_3": top_3,
            "total_players": len(users),
            "total_completed_all": total_completed_all,
            "total_score_all": total_score_all,
            "active_page": "leaderboard",
        },
    )


@router.get("/board", response_class=HTMLResponse)
async def web_get_board(
    request: Request,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Renders full index.html for direct browser navigation/redirects, or updated #main-board partial with OOB modal clearing for HTMX swaps."""
    cookie_uid = request.cookies.get("session_user_id")
    if not cookie_uid:
        is_htmx = request.headers.get("hx-request") == "true"
        if is_htmx:
            return Response(status_code=200, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=303)

    ctx = await get_board_context(request, None, db)
    is_htmx = request.headers.get("hx-request") == "true"
    hx_target = request.headers.get("hx-target", "")

    # If this is an HTMX partial request (e.g. from closing modals or updating the board)
    if is_htmx and hx_target != "body":
        board_html = templates.get_template("partials/board_content.html").render(ctx)
        clear_modal = (
            '<div id="roulette-modal-container" hx-swap-oob="innerHTML"></div>'
            '<div id="completion-modal-container" hx-swap-oob="innerHTML"></div>'
            '<div id="challenges-modal" hx-swap-oob="delete"></div>'
        )
        stats_bar_html = templates.get_template("partials/user_stats_bar.html").render(
            {
                "current_user": ctx["current_user"],
                "user_active_count": ctx["user_active_count"],
                "max_active_quests": ctx["max_active_quests"],
                "is_oob": True,
            }
        )
        return HTMLResponse(content=board_html + clear_modal + stats_bar_html)

    # For full page loads (browser navigation, redirects, link clicks <a href="/board">)
    return templates.TemplateResponse("index.html", ctx)


@router.get("/board/items", response_class=HTMLResponse)
async def get_board_items(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Возвращает актуальный HTML-фрагмент сетки доступных квестов (AVAILABLE) для тихого HTMX-поллинга."""
    cookie_uid = request.cookies.get("session_user_id")
    current_user = await db.get(User, int(cookie_uid)) if cookie_uid and cookie_uid.isdigit() else None

    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    available_quests = [QuestResponse.model_validate(q) for q in db_available]

    active_count = 0
    if current_user:
        active_stmt = select(func.count(Quest.id)).where(
            Quest.user_id == current_user.id, Quest.status == QuestStatus.IN_PROGRESS
        )
        active_count = (await db.execute(active_stmt)).scalar() or 0

    return templates.TemplateResponse(
        "partials/board_grid.html",
        {
            "request": request,
            "available_quests": available_quests,
            "current_user": current_user,
            "user_active_count": active_count,
            "user_can_take_quest": active_count < settings.MAX_ACTIVE_QUESTS,
            "max_active_quests": settings.MAX_ACTIVE_QUESTS,
        },
    )


@router.post("/quests/{id}/take")
@router.post("/quests/{id}/take/")
async def take_quest_endpoint(
    id: int,
    request: Request,
    user_id: Optional[int] = Query(None),
    form_user_id: Optional[int] = Form(None),
    direct: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Взятие квеста. По умолчанию возвращает модальное окно рулетки (roulette_modal.html)
    для выбора случайной игры с анимацией барабана. При direct=True производит прямое взятие.
    Строго ограничивает лимит до максимум 1 активного квеста на игрока.
    """
    quest_id = id
    cookie_uid = request.cookies.get("session_user_id")
    if cookie_uid and cookie_uid.isdigit():
        active_uid = int(cookie_uid)
    else:
        active_uid = user_id or form_user_id
        if not active_uid:
            try:
                body = await request.json()
                if isinstance(body, dict) and "user_id" in body:
                    active_uid = int(body["user_id"])
            except Exception:
                pass
    if not active_uid:
        users = await get_or_seed_users(db)
        active_uid = users[0].id if users else 1

    user = await db.get(User, active_uid)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # 1. Проверка лимита: разрешено максимум settings.MAX_ACTIVE_QUESTS активных квестов!
    active_count_stmt = select(func.count(Quest.id)).where(
        Quest.user_id == active_uid, Quest.status == QuestStatus.IN_PROGRESS
    )
    active_count = (await db.execute(active_count_stmt)).scalar() or 0
    if active_count >= settings.MAX_ACTIVE_QUESTS:
        is_htmx = request.headers.get("hx-request") == "true"
        if is_htmx:
            toast_hdr = json.dumps({"showToast": {"type": "warning", "message": f"Достигнут лимит активных квестов ({settings.MAX_ACTIVE_QUESTS}/{settings.MAX_ACTIVE_QUESTS})!"}})
            return HTMLResponse(
                content=f'<div id="roulette-modal" class="modal-open fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4 overflow-y-auto transition-all duration-300">'
                        f'<div class="relative w-full max-w-md my-auto max-h-[92vh] overflow-y-auto bg-[#180e08] border-4 border-amber-600 rounded-2xl p-6 sm:p-8 text-center shadow-2xl space-y-4">'
                        f'<div class="w-14 h-14 rounded-full bg-amber-950 border-2 border-amber-500 text-amber-300 flex items-center justify-center text-3xl mx-auto shadow-inner">⚠️</div>'
                        f'<h3 class="text-xl sm:text-2xl font-heading font-black text-amber-300 tracking-wide uppercase">Лимит квестов</h3>'
                        f'<p class="text-base sm:text-lg text-[#edd6bd] font-serif leading-relaxed">'
                        f'У вас уже максимум активных квестов: <strong class="text-amber-300">({settings.MAX_ACTIVE_QUESTS}/{settings.MAX_ACTIVE_QUESTS})</strong>.<br><br>'
                        f'В турнире разрешено выполнять <strong class="text-amber-300">не более {settings.MAX_ACTIVE_QUESTS} активного квеста</strong> одновременно.<br><br>'
                        f'Сначала завершите или сбросьте текущий контракт.'
                        f'</p>'
                        f'<div class="pt-2">'
                        f'<button onclick="document.getElementById(\'roulette-modal\').remove()" class="w-full py-3 px-4 rounded-xl bg-gradient-to-b from-stone-800 to-stone-900 hover:from-stone-700 hover:to-stone-800 text-amber-200 border-2 border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer active:scale-95 transition-all shadow-md">'
                        f'Понятно'
                        f'</button>'
                        f'</div></div></div>',
                headers={"HX-Trigger": toast_hdr},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Достигнут лимит активных квестов. У вас уже {settings.MAX_ACTIVE_QUESTS} активных квеста. Сдайте или сбросьте один перед тем, как брать новый.",
        )

    # 2. Проверка доступности квеста
    stmt = (
        select(Quest)
        .where(Quest.id == quest_id)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.user),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.challenge),
        )
    )
    if direct:
        stmt = stmt.with_for_update()

    result = await db.execute(stmt)
    quest = result.scalar_one_or_none()

    if not quest or quest.status != QuestStatus.AVAILABLE:
        is_htmx = request.headers.get("hx-request") == "true"
        if is_htmx:
            toast_hdr = json.dumps({"showToast": {"type": "error", "message": "Контракт уже забран другим игроком!"}})
            return HTMLResponse(
                content='<div id="roulette-modal" class="modal-open fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4 overflow-y-auto transition-all duration-300">'
                        '<div class="relative w-full max-w-md my-auto bg-[#180e08] border-4 border-red-800 rounded-2xl p-6 text-center shadow-2xl space-y-4">'
                        '<h3 class="text-xl font-heading font-black text-red-400">⚠️ Контракт недоступен</h3>'
                        '<p class="text-base text-[#edd6bd] font-serif">Этот квест уже взял другой игрок или он был завершен!</p>'
                        '<button hx-get="/board" hx-target="#main-board" hx-swap="outerHTML" onclick="document.getElementById(\'roulette-modal\').remove()" class="w-full py-3 px-4 rounded-xl bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">Обновить Доску</button>'
                        '</div></div>',
                headers={"HX-Trigger": toast_hdr},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Контракт уже забрал другой ведьмак!",
        )

    # 3. Проверка статуса Андердога
    if quest.is_underdog_only:
        user_is_underdog = await is_underdog(db, user)
        if not user_is_underdog:
            is_htmx = request.headers.get("hx-request") == "true"
            if is_htmx:
                return HTMLResponse(
                    content='<div id="roulette-modal" class="modal-open fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4 overflow-y-auto">'
                            '<div class="relative w-full max-w-md my-auto bg-[#180e08] border-4 border-amber-600 rounded-2xl p-6 text-center shadow-2xl space-y-4">'
                            '<h3 class="text-xl font-heading font-black text-amber-400">⚠️ Только для Андердога</h3>'
                            '<p class="text-base text-[#edd6bd] font-serif">Этот квест доступен только участникам со статусом Андердог!</p>'
                            '<button onclick="document.getElementById(\'roulette-modal\').remove()" class="w-full py-3 px-4 rounded-xl bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">Закрыть</button>'
                            '</div></div>'
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Этот контракт доступен только Андердогам (отставание > {settings.UNDERDOG_SCORE_GAP} очков)",
            )

    # Прямое взятие без рулетки (если direct=True)
    if direct:
        try:
            quest = await take_quest(db, quest_id=quest_id, user_id=active_uid)
            await refill_board(db)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        is_htmx = request.headers.get("hx-request") == "true"
        if is_htmx:
            ctx = await get_board_context(request, active_uid, db)
            board_html = templates.get_template("partials/board_content.html").render(ctx)
            clear_modal = (
                '<div id="roulette-modal-container" hx-swap-oob="innerHTML"></div>'
                '<div id="completion-modal-container" hx-swap-oob="innerHTML"></div>'
            )
            return HTMLResponse(content=board_html + clear_modal)
        await db.refresh(quest)
        return QuestResponse.model_validate(quest)

    # 4. Формирование барабана рулетки из games.db парсера
    winning_game: Optional[Game] = None
    bonus_pct = 0.0

    if quest.is_santa_box:
        # Если игра для этой коробки Санты уже была определена ранее — сохраняем её (защита от F5)
        if quest.current_rolled_game_id:
            winning_game = await db.get(Game, quest.current_rolled_game_id)
        if not winning_game:
            is_top = random.choice([True, False])
            target_cat = "SANTA_TOP" if is_top else "SANTA_COAL"
            bonus_pct = 0.10 if is_top else 0.50
            santa_candidates = query_games_from_parser_db(
                is_santa_top=is_top,
                is_santa_coal=(not is_top),
                limit=10,
            )
            if santa_candidates:
                chosen_dict = random.choice(santa_candidates)
                winning_game = await sync_game_to_hpg(db, chosen_dict, category=target_cat)
            else:
                santa_stmt = select(Game).where(Game.category == target_cat).order_by(func.random()).limit(1)
                winning_game = (await db.execute(santa_stmt)).scalar_one_or_none()
                if not winning_game:
                    winning_game = (await db.execute(select(Game).order_by(func.random()).limit(1))).scalar_one()
            quest.current_rolled_game_id = winning_game.id
            await db.commit()
        else:
            bonus_pct = 0.10 if winning_game.category == "SANTA_TOP" else 0.50
    else:
        # Обычный квест или квест по фильтрам (Rogue-like 6+ ч, Metroidvania, etc.)
        if quest.current_rolled_game_id:
            winning_game = await db.get(Game, quest.current_rolled_game_id)
        if not winning_game:
            candidates = query_games_from_parser_db(
                tag=quest.tag_filter,
                min_hours=quest.min_hltb_hours,
                max_hours=quest.max_hltb_hours,
                min_rating=quest.min_rating,
                limit=15,
            )
            if candidates:
                chosen_dict = candidates[0]
                winning_game = await sync_game_to_hpg(db, chosen_dict, category=quest.card_type)
            else:
                winning_game = quest.game

    if not winning_game:
        winning_game = (await db.execute(select(Game).order_by(func.random()).limit(1))).scalar_one()

    if winning_game and winning_game.steam_appid:
        resolved_img = resolve_single_image_url(winning_game.steam_appid, winning_game.image_url)
        if resolved_img and resolved_img != winning_game.image_url:
            winning_game.image_url = resolved_img
            await db.flush()

    winning_title = winning_game.title

    # Расчет ожидаемой награды с учетом текущей инфляции (Hard Cap)
    now = datetime.now(timezone.utc)
    spawned = quest.spawned_at if quest.spawned_at.tzinfo else quest.spawned_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - spawned).total_seconds()
    interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
    intervals = min(settings.MAX_INFLATION_INTERVALS, max(0, int(elapsed_seconds // interval_seconds)))
    inflation_mult = 1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals

    base_reward = round(winning_game.reward_points * (1.0 + bonus_pct))
    candidate_reward = round(base_reward * inflation_mult)

    # 5. Генерация списка игр с картинками для барабана рулетки
    fake_needed = settings.ROULETTE_OPTIONS_COUNT - 1
    reel_candidates = query_games_from_parser_db(
        tag=quest.tag_filter,
        min_hours=quest.min_hltb_hours,
        max_hours=quest.max_hltb_hours,
        min_rating=quest.min_rating,
        exclude_titles={winning_title},
        limit=fake_needed,
    )

    fake_games: list[dict[str, Any]] = []
    for cand in reel_candidates:
        cand_img = cand.get("image_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{cand.get('steam_appid')}/header.jpg" if cand.get("steam_appid") else None)
        fake_games.append({
            "title": cand["title"],
            "image_url": cand_img,
            "genre": cand.get("tags", ["Игра"])[0] if cand.get("tags") else "Экшен",
            "hltb_hours": cand.get("hltb_main_story_hours") or 0.0,
            "developer": cand.get("developer"),
            "review_percentage": cand.get("review_percentage"),
        })

    # Дополняем из parser/data/games.db если нужно
    if len(fake_games) < fake_needed:
        remaining = fake_needed - len(fake_games)
        more_candidates = query_games_from_parser_db(
            exclude_titles={winning_title}.union({g["title"] for g in fake_games}),
            limit=remaining,
        )
        for cand in more_candidates:
            cand_img = cand.get("image_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{cand.get('steam_appid')}/header.jpg" if cand.get("steam_appid") else None)
            if cand_img:
                fake_games.append({
                    "title": cand["title"],
                    "image_url": cand_img,
                    "genre": cand.get("tags", ["Игра"])[0] if cand.get("tags") else "Экшен",
                    "hltb_hours": cand.get("hltb_main_story_hours") or 0.0,
                    "developer": cand.get("developer"),
                    "review_percentage": cand.get("review_percentage"),
                })

    # Дополняем из hpg.db с гарантированной картинкой
    if len(fake_games) < fake_needed:
        remaining = fake_needed - len(fake_games)
        fallback_stmt = (
            select(Game)
            .where(
                Game.title != winning_title,
                Game.title.not_in([g["title"] for g in fake_games]),
                Game.image_url.is_not(None),
                Game.image_url != "",
            )
            .order_by(func.random())
            .limit(remaining)
        )
        fb_games = list((await db.execute(fallback_stmt)).scalars().all())
        for fbg in fb_games:
            fake_games.append({
                "title": fbg.title,
                "image_url": fbg.image_url,
                "genre": fbg.genre,
                "hltb_hours": fbg.hltb_hours,
                "developer": fbg.developer,
                "review_percentage": fbg.review_percentage,
            })

    random.shuffle(fake_games)

    winning_dict = {
        "title": winning_game.title,
        "image_url": winning_game.image_url,
        "genre": winning_game.genre,
        "hltb_hours": winning_game.hltb_hours,
        "developer": winning_game.developer,
        "review_percentage": winning_game.review_percentage,
    }

    penultimate_idx = max(0, settings.ROULETTE_OPTIONS_COUNT - 2)
    roulette_games = fake_games[:penultimate_idx] + [winning_dict] + fake_games[penultimate_idx:fake_needed]
    roulette_games = roulette_games[: settings.ROULETTE_OPTIONS_COUNT]
    winning_index = penultimate_idx
    roulette_titles = [g["title"] for g in roulette_games]

    # 6. МГНОВЕННО ФИКСИРУЕМ ВЗЯТИЕ КВЕСТА В БАЗЕ ДАННЫХ!
    # Игрок НЕ МОЖЕТ отменить выпавшую игру обновлением страницы (F5) или закрытием вкладки.
    # Квест переходит в статус IN_PROGRESS и привязывается к пользователю.
    # Для отказа от игры игрок ОБЯЗАН использовать реролл или сброс со штрафом.
    quest = await take_quest(db, quest_id=quest_id, user_id=active_uid, specific_game_id=winning_game.id)
    quest.game_id = winning_game.id
    quest.current_rolled_game_id = winning_game.id
    quest.game = winning_game
    await db.commit()
    await refill_board(db)
    await db.refresh(user)

    all_users = list((await db.execute(select(User))).scalars().all())
    attach_underdog_flags(all_users)

    stats_bar_html = templates.get_template("partials/user_stats_bar.html").render(
        {
            "current_user": user,
            "user_active_count": 1,
            "max_active_quests": settings.MAX_ACTIVE_QUESTS,
            "is_oob": True,
        }
    )

    modal_html = templates.get_template("partials/roulette_modal.html").render(
        {
            "request": request,
            "quest": quest,
            "current_user": user,
            "user_id": active_uid,
            "winning_game": winning_game,
            "winning_title": winning_title,
            "candidate_reward": quest.locked_reward,
            "penalty_points": winning_game.penalty_points,
            "roulette_games": roulette_games,
            "roulette_titles": roulette_titles,
            "winning_index": winning_index,
            "options_count": len(roulette_games),
            "duration_sec": settings.ROULETTE_DURATION_SEC,
            "is_reroll": False,
        }
    )
    return HTMLResponse(content=modal_html + stats_bar_html)


@router.post("/quests/{quest_id}/confirm-take", response_class=HTMLResponse)
async def web_confirm_take_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[str] = Query(None),
    form_user_id: Optional[str] = Form(None),
    game_id: Optional[str] = Query(None),
    form_game_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly accepts the contract after roulette and opens the challenge selection modal."""
    cookie_uid = request.cookies.get("session_user_id")
    if cookie_uid and cookie_uid.isdigit():
        uid = int(cookie_uid)
    elif user_id and str(user_id).isdigit():
        uid = int(user_id)
    elif form_user_id and str(form_user_id).isdigit():
        uid = int(form_user_id)
    else:
        users = await get_or_seed_users(db)
        uid = users[0].id if users else 1

    raw_gid = game_id or form_game_id
    gid = int(raw_gid) if raw_gid and str(raw_gid).isdigit() else None

    # Проверка лимита: у пользователя не должно быть больше settings.MAX_ACTIVE_QUESTS активных квестов (исключая текущий)
    active_count_stmt = select(func.count(Quest.id)).where(
        Quest.user_id == uid, Quest.status == QuestStatus.IN_PROGRESS, Quest.id != quest_id
    )
    active_count = (await db.execute(active_count_stmt)).scalar() or 0
    if active_count >= settings.MAX_ACTIVE_QUESTS:
        return HTMLResponse(
            content=f'<div id="challenges-modal" class="modal-open fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4 overflow-y-auto">'
                    f'<div class="relative w-full max-w-md my-auto max-h-[92vh] overflow-y-auto bg-[#180e08] border-4 border-amber-600 rounded-2xl p-6 text-center shadow-2xl space-y-4">'
                    f'<div class="w-14 h-14 rounded-full bg-amber-950 border-2 border-amber-500 text-amber-300 flex items-center justify-center text-3xl mx-auto shadow-inner">⚠️</div>'
                    f'<h3 class="text-xl font-heading font-black text-amber-300 mb-2">⚠️ Лимит квестов</h3>'
                    f'<p class="text-base text-[#edd6bd] font-serif mb-5">У вас уже максимум активных контрактов: ({settings.MAX_ACTIVE_QUESTS} из {settings.MAX_ACTIVE_QUESTS}). В турнире разрешено не более {settings.MAX_ACTIVE_QUESTS} активного квеста одновременно.</p>'
                    f'<button hx-get="/board" hx-target="#main-board" hx-swap="outerHTML" class="px-6 py-2.5 rounded-lg bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">Вернуться к Доске</button></div></div>'
        )

    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        return HTMLResponse(
            content='<div id="challenges-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4">'
                    '<div class="relative w-full max-w-md bg-[#180e08] border-4 border-red-800 rounded-2xl p-6 text-center shadow-2xl">'
                    '<h3 class="text-xl font-heading font-black text-red-400 mb-2">⚠️ Ошибка Квеста</h3>'
                    '<p class="text-base text-[#edd6bd] font-serif mb-5">Квест не найден.</p>'
                    '<button hx-get="/board" hx-target="#main-board" hx-swap="outerHTML" class="px-6 py-2.5 rounded-lg bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">Вернуться к Доске</button></div></div>'
        )

    # Проверка: если квест уже закреплен за другим игроком
    if quest.user_id and quest.user_id != uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    try:
        if quest.status == QuestStatus.AVAILABLE:
            quest = await take_quest(db, quest_id=quest_id, user_id=uid, specific_game_id=gid)
            await refill_board(db)
        elif gid and quest.game_id != gid:
            quest.game_id = gid
            quest.current_rolled_game_id = gid
            g = await db.get(Game, gid)
            if g:
                now = datetime.now(timezone.utc)
                spawned = quest.spawned_at if quest.spawned_at.tzinfo else quest.spawned_at.replace(tzinfo=timezone.utc)
                elapsed_seconds = (now - spawned).total_seconds()
                interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
                intervals = min(settings.MAX_INFLATION_INTERVALS, max(0, int(elapsed_seconds // interval_seconds)))
                inflation_mult = 1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals
                quest.locked_reward = round(g.reward_points * inflation_mult)
            await db.commit()
    except Exception as e:
        error_msg = str(e)
        return HTMLResponse(
            content=f'<div id="challenges-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4">'
                    f'<div class="relative w-full max-w-md bg-[#180e08] border-4 border-red-800 rounded-2xl p-6 text-center shadow-2xl">'
                    f'<h3 class="text-xl font-heading font-black text-red-400 mb-2">⚠️ Ошибка Квеста</h3>'
                    f'<p class="text-base text-[#edd6bd] font-serif mb-5">{error_msg}</p>'
                    f'<button hx-get="/board" hx-target="#main-board" hx-swap="outerHTML" class="px-6 py-2.5 rounded-lg bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">'
                    f'Вернуться к Доске</button></div></div>'
        )

    # Fetch 3 random challenges for optional oath taking
    challenges = await get_random_challenges(db, limit=3)
    return templates.TemplateResponse(
        "partials/challenges_selection.html",
        {
            "request": request,
            "quest": quest,
            "challenges": challenges,
            "user_id": uid,
            "current_user": await db.get(User, uid),
        },
    )


@router.get("/quests/{quest_id}/challenges_selection", response_class=HTMLResponse)
async def web_get_challenges_selection(
    request: Request,
    quest_id: int,
    user_id: Optional[str] = Query(None),
    form_user_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Renders the challenge selection modal for a taken quest."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    cookie_uid = request.cookies.get("session_user_id")
    if cookie_uid and cookie_uid.isdigit():
        uid = int(cookie_uid)
    elif user_id and str(user_id).isdigit():
        uid = int(user_id)
    elif form_user_id and str(form_user_id).isdigit():
        uid = int(form_user_id)
    else:
        users = await get_or_seed_users(db)
        uid = users[0].id if users else 1

    # Запретить доступ к выбору челленджа для чужого квеста
    if quest.user_id and quest.user_id != uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    challenges = await get_random_challenges(db, limit=3)
    return templates.TemplateResponse(
        "partials/challenges_selection.html",
        {
            "request": request,
            "quest": quest,
            "challenges": challenges,
            "user_id": uid,
            "current_user": await db.get(User, uid),
        },
    )


@router.post("/quests/{quest_id}/accept_challenge/{challenge_choice}")
async def web_accept_challenge(
    request: Request,
    quest_id: int,
    challenge_choice: str,
    user_id: Optional[str] = Query(None),
    form_user_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Binds chosen challenge (or None for standard contract decline) and transitions quest to IN_PROGRESS."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    cookie_uid = request.cookies.get("session_user_id")
    if cookie_uid and cookie_uid.isdigit():
        uid = int(cookie_uid)
    elif user_id and str(user_id).isdigit():
        uid = int(user_id)
    elif form_user_id and str(form_user_id).isdigit():
        uid = int(form_user_id)
    else:
        users = await get_or_seed_users(db)
        uid = users[0].id if users else 1

    # Запретить принятие/отклонение челленджа чужого квеста
    if quest.user_id and quest.user_id != uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    # Parse challenge_choice: 'none', 'null', or integer ID
    ch_id: Optional[int] = None
    if challenge_choice.lower() not in ("none", "null", "0", "false"):
        try:
            ch_id = int(challenge_choice)
        except ValueError:
            ch_id = None

    try:
        if quest.status == QuestStatus.AVAILABLE:
            await take_quest(db, quest_id=quest_id, user_id=uid, challenge_id=ch_id)
        else:
            await set_quest_challenge(db, quest_id=quest_id, user_id=uid, challenge_id=ch_id)
        await refill_board(db)
    except Exception as e:
        error_msg = str(e)
        return HTMLResponse(
            content=f'<div id="challenges-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4">'
                    f'<div class="relative w-full max-w-md bg-[#180e08] border-4 border-red-800 rounded-2xl p-6 text-center shadow-2xl">'
                    f'<h3 class="text-xl font-heading font-black text-red-400 mb-2">⚠️ Ошибка Квеста</h3>'
                    f'<p class="text-base text-[#edd6bd] font-serif mb-5">{error_msg}</p>'
                    f'<button hx-get="/board" hx-target="#main-board" hx-swap="outerHTML" class="px-6 py-2.5 rounded-lg bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">'
                    f'Вернуться к Доске</button></div></div>'
        )

    is_htmx = request.headers.get("hx-request") == "true"
    accept_hdr = request.headers.get("accept", "")
    content_type_hdr = request.headers.get("content-type", "")
    if not is_htmx and ("application/json" in accept_hdr or "application/json" in content_type_hdr):
        return {
            "status": "ok",
            "quest_id": quest_id,
            "challenge_id": ch_id,
            "quest_status": "IN_PROGRESS",
        }

    ctx = await get_board_context(request, uid, db)
    board_html = templates.get_template("partials/board_content.html").render(ctx)
    clear_modal = (
        '<div id="challenges-modal" hx-swap-oob="delete"></div>'
        '<div id="roulette-modal-container" hx-swap-oob="innerHTML"></div>'
        '<div id="completion-modal-container" hx-swap-oob="innerHTML"></div>'
    )
    stats_bar_html = templates.get_template("partials/user_stats_bar.html").render(
        {
            "current_user": ctx["current_user"],
            "user_active_count": ctx["user_active_count"],
            "max_active_quests": ctx["max_active_quests"],
            "is_oob": True,
        }
    )
    return HTMLResponse(content=board_html + clear_modal + stats_bar_html)


@router.get("/quests/{quest_id}/completion_modal", response_class=HTMLResponse)
async def web_get_completion_modal(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Renders the completion modal for reporting quest and challenge outcome."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    cookie_uid = request.cookies.get("session_user_id")
    caller_uid = int(cookie_uid) if cookie_uid and cookie_uid.isdigit() else user_id
    if not caller_uid:
        raise HTTPException(status_code=401, detail="Необходимо авторизоваться")

    if quest.user_id != caller_uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    challenge = quest.challenge
    if not challenge and quest.challenge_id:
        challenge = await db.get(Challenge, quest.challenge_id)

    if not challenge:
        challenge = Challenge(
            id=0,
            description="Базовый квест без усложнений",
            multiplier=1.0,
            bonus_multiplier=1.0,
            penalty_multiplier=1.0,
        )

    current_user = await db.get(User, caller_uid)
    return templates.TemplateResponse(
        "partials/completion_modal.html",
        {
            "request": request,
            "quest": quest,
            "challenge": challenge,
            "current_user": current_user,
        },
    )


@router.post("/quests/{quest_id}/drop")
async def web_drop_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """User drops active quest. Returns updated board HTML so only user's active quest is removed."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        return Response(status_code=200, content="")

    cookie_uid = request.cookies.get("session_user_id")
    caller_uid = int(cookie_uid) if cookie_uid and cookie_uid.isdigit() else user_id
    if not caller_uid:
        raise HTTPException(status_code=401, detail="Необходимо авторизоваться")

    if quest.user_id != caller_uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    refreshed_quest, penalty, used_free_drop = await drop_quest(db, quest_id=quest_id, user_id=caller_uid)

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        ctx = await get_board_context(request, caller_uid, db)
        board_html = templates.get_template("partials/board_content.html").render(ctx)
        clear_modal = (
            '<div id="roulette-modal-container" hx-swap-oob="innerHTML"></div>'
            '<div id="completion-modal-container" hx-swap-oob="innerHTML"></div>'
            '<div id="challenges-modal" hx-swap-oob="delete"></div>'
        )
        stats_bar_html = templates.get_template("partials/user_stats_bar.html").render(
            {
                "current_user": ctx["current_user"],
                "user_active_count": ctx["user_active_count"],
                "max_active_quests": ctx["max_active_quests"],
                "is_oob": True,
            }
        )
        if used_free_drop:
            toast_msg = f"Квест сброшен! Использован 1 бесплатный сброс (осталось: {ctx['current_user'].free_drops})."
            toast_type = "info"
        else:
            toast_msg = f"Квест сброшен! Бесплатных сбросов нет — списан штраф -{penalty} очков."
            toast_type = "warning"

        toast_hdr = json.dumps({"showToast": {"type": toast_type, "message": toast_msg}})
        resp = HTMLResponse(content=board_html + clear_modal + stats_bar_html)
        resp.headers["HX-Trigger"] = toast_hdr
        return resp

    return Response(status_code=200, content="")


@router.post("/quests/{quest_id}/complete")
async def web_complete_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    form_user_id: Optional[int] = Form(None),
    challenge_status: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Completes active quest: computes challenge bonus/penalty, updates score and board."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    cookie_uid = request.cookies.get("session_user_id")
    caller_uid = int(cookie_uid) if cookie_uid and cookie_uid.isdigit() else (user_id or form_user_id)
    if not caller_uid:
        raise HTTPException(status_code=401, detail="Необходимо авторизоваться")

    if quest.user_id != caller_uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    # 1. Resolve challenge_status from Form, Query, or JSON body
    status_choice = challenge_status or request.query_params.get("challenge_status")
    if not status_choice:
        try:
            body = await request.json()
            if isinstance(body, dict):
                status_choice = body.get("challenge_status")
        except Exception:
            pass

    try:
        quest, points_earned, details = await complete_quest(
            db, quest_id=quest_id, user_id=caller_uid, challenge_status=status_choice
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check if REST client requested JSON
    is_htmx = request.headers.get("hx-request") == "true"
    accept_hdr = request.headers.get("accept", "")
    content_type_hdr = request.headers.get("content-type", "")
    if not is_htmx and ("application/json" in accept_hdr or "application/json" in content_type_hdr):
        return {
            "message": f"Квест успешно сдан! Начислено: +{points_earned} очков.",
            "quest_id": quest.id,
            "points_delta": points_earned,
            "new_user_score": quest.user.total_score,
            "challenge_successful": quest.challenge_successful,
            "details": details,
        }

    ctx = await get_board_context(request, caller_uid, db)
    board_html = templates.get_template("partials/board_content.html").render(ctx)
    clear_modal = (
        '<div id="completion-modal-container" hx-swap-oob="innerHTML"></div>'
        '<div id="roulette-modal-container" hx-swap-oob="innerHTML"></div>'
        '<div id="challenges-modal" hx-swap-oob="delete"></div>'
    )
    stats_bar_html = templates.get_template("partials/user_stats_bar.html").render(
        {
            "current_user": ctx["current_user"],
            "user_active_count": ctx["user_active_count"],
            "max_active_quests": ctx["max_active_quests"],
            "is_oob": True,
        }
    )
    toast_hdr = json.dumps({"showToast": {"type": "success", "message": f"Контракт успешно сдан! Начислено +{points_earned} очков."}})
    resp = HTMLResponse(content=board_html + clear_modal + stats_bar_html)
    resp.headers["HX-Trigger"] = toast_hdr
    return resp


@router.post("/quests/{quest_id}/reroll", response_class=HTMLResponse)
async def web_reroll_quest(
    request: Request,
    quest_id: int,
    user_id: Optional[int] = Query(None),
    direct: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Выполняет реролл игры внутри активного квеста.
    Выбирает случайную игру из категории квеста, списывает 1 реролл и возвращает
    анимированное модальное окно рулетки (roulette_modal.html с is_reroll=True).
    """
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Квест не найден")

    cookie_uid = request.cookies.get("session_user_id")
    caller_uid = int(cookie_uid) if cookie_uid and cookie_uid.isdigit() else user_id
    if not caller_uid:
        raise HTTPException(status_code=401, detail="Необходимо авторизоваться")

    if quest.user_id != caller_uid:
        raise HTTPException(status_code=403, detail="Вы не можете взаимодействовать с чужим квестом!")

    if quest.status != QuestStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Реролл доступен только для активных квестов в процессе выполнения!")

    user = await db.get(User, caller_uid)
    if not user or user.rerolls_left <= 0:
        is_htmx = request.headers.get("hx-request") == "true"
        if is_htmx:
            return HTMLResponse(
                content='<div id="roulette-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4">'
                        '<div class="relative w-full max-w-md bg-[#180e08] border-4 border-amber-600 rounded-2xl p-6 text-center shadow-2xl space-y-4">'
                        '<div class="w-14 h-14 rounded-full bg-amber-950 border-2 border-amber-500 text-amber-300 flex items-center justify-center text-3xl mx-auto shadow-inner">⚠️</div>'
                        '<h3 class="text-xl font-heading font-black text-amber-300">Нет доступных рероллов</h3>'
                        '<p class="text-base text-[#edd6bd] font-serif">У вас закончились попытки реролла.<br>Выполните еще 3 квеста, чтобы восполнить +1 реролл!</p>'
                        '<button onclick="document.getElementById(\'roulette-modal\').remove()" class="w-full py-3 px-4 rounded-xl bg-stone-800 hover:bg-stone-700 text-amber-200 border border-stone-600 font-heading font-black uppercase tracking-wider cursor-pointer">Понятно</button>'
                        '</div></div>'
            )
        raise HTTPException(status_code=400, detail="У вас нет доступных попыток реролла")

    # 1. Определяем категорию квеста
    category = quest.game.category if quest.game else quest.card_type
    category_display_map = {
        "STEAM": "Steam",
        "GOTY": "GOTY",
        "PRESET": "Пресет",
        "SERIES": "Серия игр",
        "EMULATOR": "Ретро / Эмулятор",
        "SANTA": "Подарок Санты",
        "SANTA_TOP": "Топ-хит Санты",
        "SANTA_COAL": "Уголёк",
    }
    category_display = category_display_map.get(category, category)

    # 2. Выполняем реролл через CRUD (списывает 1 реролл, начисляет штраф -10%, ставит новую игру из той же категории)
    updated_quest = await reroll_quest(db, quest_id=quest_id, user_id=caller_uid)
    await db.refresh(user)

    winning_game = updated_quest.game
    if winning_game and winning_game.steam_appid:
        resolved_img = resolve_single_image_url(winning_game.steam_appid, winning_game.image_url)
        if resolved_img and resolved_img != winning_game.image_url:
            winning_game.image_url = resolved_img
            await db.flush()
    winning_title = winning_game.title if winning_game else "Новая игра"

    # Если direct=True (например, прямой вызов из тестов без модального окна)
    if direct:
        ctx = await get_board_context(request, caller_uid, db)
        board_html = templates.get_template("partials/board_content.html").render(ctx)
        return HTMLResponse(content=board_html)

    # 3. Формируем барабан рулетки из games.db парсера для красивой анимации вращения
    fake_needed = settings.ROULETTE_OPTIONS_COUNT - 1
    exclude_set = {winning_title}
    reel_candidates = query_games_from_parser_db(
        tag=updated_quest.tag_filter,
        min_hours=updated_quest.min_hltb_hours,
        max_hours=updated_quest.max_hltb_hours,
        min_rating=updated_quest.min_rating,
        exclude_titles=exclude_set,
        limit=fake_needed,
    )

    fake_games: list[dict[str, Any]] = []
    for cand in reel_candidates:
        cand_img = cand.get("image_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{cand.get('steam_appid')}/header.jpg" if cand.get("steam_appid") else None)
        fake_games.append({
            "title": cand["title"],
            "image_url": cand_img,
            "genre": cand.get("tags", ["Игра"])[0] if cand.get("tags") else "Экшен",
            "hltb_hours": cand.get("hltb_main_story_hours") or 0.0,
            "developer": cand.get("developer"),
            "review_percentage": cand.get("review_percentage"),
        })

    # Дополняем из parser/data/games.db если нужно
    if len(fake_games) < fake_needed:
        remaining = fake_needed - len(fake_games)
        more_candidates = query_games_from_parser_db(
            exclude_titles={winning_title}.union({g["title"] for g in fake_games}),
            limit=remaining,
        )
        for cand in more_candidates:
            cand_img = cand.get("image_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{cand.get('steam_appid')}/header.jpg" if cand.get("steam_appid") else None)
            if cand_img:
                fake_games.append({
                    "title": cand["title"],
                    "image_url": cand_img,
                    "genre": cand.get("tags", ["Игра"])[0] if cand.get("tags") else "Экшен",
                    "hltb_hours": cand.get("hltb_main_story_hours") or 0.0,
                    "developer": cand.get("developer"),
                    "review_percentage": cand.get("review_percentage"),
                })

    # Дополняем из hpg.db с гарантированной картинкой
    if len(fake_games) < fake_needed:
        remaining = fake_needed - len(fake_games)
        fallback_stmt = (
            select(Game)
            .where(
                Game.title != winning_title,
                Game.title.not_in([g["title"] for g in fake_games]),
                Game.image_url.is_not(None),
                Game.image_url != "",
            )
            .order_by(func.random())
            .limit(remaining)
        )
        fb_games = list((await db.execute(fallback_stmt)).scalars().all())
        for fbg in fb_games:
            fake_games.append({
                "title": fbg.title,
                "image_url": fbg.image_url,
                "genre": fbg.genre,
                "hltb_hours": fbg.hltb_hours,
                "developer": fbg.developer,
                "review_percentage": fbg.review_percentage,
            })

    random.shuffle(fake_games)

    winning_dict = {
        "title": winning_game.title,
        "image_url": winning_game.image_url,
        "genre": winning_game.genre,
        "hltb_hours": winning_game.hltb_hours,
        "developer": winning_game.developer,
        "review_percentage": winning_game.review_percentage,
    }

    penultimate_idx = max(0, settings.ROULETTE_OPTIONS_COUNT - 2)
    roulette_games = fake_games[:penultimate_idx] + [winning_dict] + fake_games[penultimate_idx:fake_needed]
    roulette_games = roulette_games[: settings.ROULETTE_OPTIONS_COUNT]
    winning_index = penultimate_idx
    roulette_titles = [g["title"] for g in roulette_games]

    reroll_penalty_pct = int(settings.REROLL_PENALTY_RATE * updated_quest.reroll_count * 100)

    # 4. Рендерим модальное окно рулетки
    modal_html = templates.get_template("partials/roulette_modal.html").render(
        {
            "request": request,
            "is_reroll": True,
            "quest": updated_quest,
            "user_id": caller_uid,
            "current_user": user,
            "winning_game": winning_game,
            "winning_title": winning_title,
            "candidate_reward": updated_quest.locked_reward,
            "penalty_points": winning_game.penalty_points if winning_game else 50,
            "category_display": category_display,
            "reroll_penalty_pct": reroll_penalty_pct,
            "roulette_games": roulette_games,
            "roulette_titles": roulette_titles,
            "winning_index": winning_index,
            "options_count": len(roulette_games),
            "duration_sec": 3.5,
        }
    )

    all_users = list((await db.execute(select(User))).scalars().all())
    attach_underdog_flags(all_users)

    # OOB обновление полосы ресурсов в шапке сайта, чтобы рероллы сразу уменьшились (напр. 🎲 0)
    stats_oob = templates.get_template("partials/user_stats_bar.html").render(
        {
            "current_user": user,
            "user_active_count": 1,
            "max_active_quests": settings.MAX_ACTIVE_QUESTS,
            "is_oob": True,
        }
    )

    toast_hdr = json.dumps({"showToast": {"type": "info", "message": f"Реролл выполнен! Списан 1 реролл (осталось: {user.rerolls_left})."}})
    resp = HTMLResponse(content=modal_html + stats_oob)
    resp.headers["HX-Trigger"] = toast_hdr
    return resp



@router.post("/quests/refill-board", response_class=HTMLResponse)
async def web_refill_board(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Refills board to 12 slots and returns updated available quest cards grid."""
    await refill_board(db, force_flush_oldest=True)
    db_available = await get_quests(db, status=QuestStatus.AVAILABLE)
    available_quests = [QuestResponse.model_validate(q) for q in db_available]

    cookie_uid = request.cookies.get("session_user_id")
    current_user = None
    if cookie_uid and cookie_uid.isdigit():
        current_user = await db.get(User, int(cookie_uid))
    if not current_user:
        users = await get_or_seed_users(db)
        current_user = users[0] if users else None

    active_count = 0
    if current_user:
        active_stmt = select(func.count(Quest.id)).where(
            Quest.user_id == current_user.id, Quest.status == QuestStatus.IN_PROGRESS
        )
        active_count = (await db.execute(active_stmt)).scalar() or 0

    toast_hdr = json.dumps({"showToast": {"type": "info", "message": "Конвейер квестов пополнен и обновлен!"}})
    resp = templates.TemplateResponse(
        "partials/board_grid.html",
        {
            "request": request,
            "available_quests": available_quests,
            "current_user": current_user,
            "user_active_count": active_count,
            "user_can_take_quest": active_count < settings.MAX_ACTIVE_QUESTS,
            "max_active_quests": settings.MAX_ACTIVE_QUESTS,
        },
    )
    resp.headers["HX-Trigger"] = toast_hdr
    return resp
