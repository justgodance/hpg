from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
import random
from typing import Any, Optional
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.crud.user import is_underdog
from app.models.challenge import Challenge
from app.models.game import Game
from app.models.quest import Quest, QuestStatus
from app.models.user import User
from app.services.games_db import query_games_from_parser_db, sync_game_to_hpg

# Карточки-архетипы для генерации контрактов из базы парсера games.db
CARD_TEMPLATES: list[dict[str, Any]] = [
    {
        "card_type": "ROGUELIKE",
        "card_title": "Rogue-like (6+ ч)",
        "tag_filter": "Rogue",
        "min_hltb_hours": 6.0,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.22,
        "preset_name": "Steam: Rogue-like 6+ ч",
    },
    {
        "card_type": "METROIDVANIA",
        "card_title": "Метроидвания (10+ ч)",
        "tag_filter": "Metroidvania",
        "min_hltb_hours": 10.0,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.16,
        "preset_name": "Steam: Метроидвания 10+ ч",
    },
    {
        "card_type": "SOULSLIKE",
        "card_title": "Souls-like / Хардкор (15+ ч)",
        "tag_filter": "Souls-like",
        "min_hltb_hours": 15.0,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.12,
        "preset_name": "Steam: Souls-like 15+ ч",
    },
    {
        "card_type": "RPG",
        "card_title": "RPG / Приключение (20+ ч)",
        "tag_filter": "RPG",
        "min_hltb_hours": 20.0,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.14,
        "preset_name": "Steam: RPG 20+ ч",
    },
    {
        "card_type": "SHORT_INDIE",
        "card_title": "Короткое Инди (до 5 ч)",
        "tag_filter": "Indie",
        "min_hltb_hours": 0.5,
        "max_hltb_hours": 5.0,
        "min_rating": None,
        "weight": 0.12,
        "preset_name": "Steam: Инди до 5 ч",
    },
    {
        "card_type": "HORROR",
        "card_title": "Хоррор / Выживание (6+ ч)",
        "tag_filter": "Horror",
        "min_hltb_hours": 6.0,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.10,
        "preset_name": "Steam: Хоррор 6+ ч",
    },
    {
        "card_type": "STEAM_TOP",
        "card_title": "Шедевр Steam (95%+ рейтинг)",
        "tag_filter": None,
        "min_hltb_hours": 5.0,
        "max_hltb_hours": None,
        "min_rating": 95.0,
        "weight": 0.08,
        "preset_name": "Steam: Шедевр 95%+",
    },
    {
        "card_type": "SANTA",
        "card_title": "Подарок от Всех (50/50)",
        "tag_filter": None,
        "min_hltb_hours": None,
        "max_hltb_hours": None,
        "min_rating": None,
        "weight": 0.06,
        "preset_name": "Секретный подарок Санты",
    },
]


async def create_quest(
    session: AsyncSession,
    game_id: int | None = None,
    card_type: str = "STEAM",
    is_santa_box: bool = False,
    is_roulette: bool = False,
    game_list_ids: list[int] | None = None,
    is_underdog_only: bool = False,
) -> Quest:
    """Creates a new quest on the board with spawned_at timestamp."""
    if game_id is not None:
        game = await session.get(Game, game_id)
        if not game:
            raise ValueError(f"Игра #{game_id} не найдена в каталоге")
    elif not is_santa_box:
        raise ValueError("game_id обязателен, если квест не является подарком Санты")

    quest = Quest(
        game_id=game_id,
        card_type=card_type,
        is_santa_box=is_santa_box,
        status=QuestStatus.AVAILABLE,
        is_roulette=is_roulette,
        game_list_ids=game_list_ids or [],
        is_underdog_only=is_underdog_only,
        spawned_at=datetime.now(timezone.utc),
    )
    session.add(quest)
    await session.commit()
    return await get_quest_by_id(session, quest.id)  # type: ignore


async def refill_board(session: AsyncSession, force_flush_oldest: bool = False) -> list[Quest]:
    """Механика 'Конвейер (Тетрис)':
    Поддерживает количество квестов со статусом AVAILABLE равным settings.MAX_BOARD_SIZE (12).
    Защита от дедлока:
    - Автоматически сжигает (DROPPED) квесты, висящие дольше BOARD_AUTO_ROTATE_HOURS (72 ч).
    - При force_flush_oldest=True (нажатие кнопки при полной доске) сжигает 3 самых старых квеста.
    """
    max_size = settings.MAX_BOARD_SIZE
    now = datetime.now(timezone.utc)

    # 1. Авто-ротация: сжигаем невостребованные квесты старше 72 часов (TTL)
    cutoff = now - timedelta(hours=settings.BOARD_AUTO_ROTATE_HOURS)
    stale_stmt = select(Quest).where(Quest.status == QuestStatus.AVAILABLE, Quest.spawned_at < cutoff)
    stale_quests = list((await session.execute(stale_stmt)).scalars().all())
    for sq in stale_quests:
        sq.status = QuestStatus.DROPPED
        sq.completed_at = now

    # 2. Если доска забита и вызван принудительный сброс конвейера: сжигаем 3 самых старых квеста
    count_stmt = select(func.count(Quest.id)).where(Quest.status == QuestStatus.AVAILABLE)
    available_count = (await session.execute(count_stmt)).scalar() or 0

    if force_flush_oldest and available_count >= max_size:
        oldest_stmt = (
            select(Quest)
            .where(Quest.status == QuestStatus.AVAILABLE)
            .order_by(Quest.spawned_at.asc(), Quest.id.asc())
            .limit(3)
        )
        oldest_quests = list((await session.execute(oldest_stmt)).scalars().all())
        for oq in oldest_quests:
            oq.status = QuestStatus.DROPPED
            oq.completed_at = now
        await session.commit()
        available_count = (await session.execute(count_stmt)).scalar() or 0

    if available_count >= max_size:
        if stale_quests:
            await session.commit()
        return []

    needed = max_size - available_count

    active_titles_stmt = select(Game.title).join(Quest, Quest.game_id == Game.id).where(
        Quest.status.in_([QuestStatus.AVAILABLE, QuestStatus.IN_PROGRESS]),
        Quest.game_id.is_not(None),
    )
    active_titles = set((await session.execute(active_titles_stmt)).scalars().all())

    templates_pool = CARD_TEMPLATES
    weights = [t["weight"] for t in templates_pool]
    chosen_templates = random.choices(templates_pool, weights=weights, k=needed)

    new_quests: list[Quest] = []
    now = datetime.now(timezone.utc)

    for tmpl in chosen_templates:
        if tmpl["card_type"] == "SANTA":
            # Спец-квест: коробка Санты без привязки игры до распаковки
            q = Quest(
                game_id=None,
                card_type="SANTA",
                card_title=tmpl["card_title"],
                is_santa_box=True,
                is_roulette=True,
                status=QuestStatus.AVAILABLE,
                spawned_at=now,
            )
            session.add(q)
            new_quests.append(q)
        else:
            # Ищем подходящую игру в games.db парсера по фильтрам карточки
            candidates = query_games_from_parser_db(
                tag=tmpl.get("tag_filter"),
                min_hours=tmpl.get("min_hltb_hours"),
                max_hours=tmpl.get("max_hltb_hours"),
                min_rating=tmpl.get("min_rating"),
                exclude_titles=active_titles,
                limit=5,
            )
            candidate_dict = candidates[0] if candidates else None

            if candidate_dict:
                game = await sync_game_to_hpg(
                    session,
                    candidate_dict,
                    category=tmpl["card_type"],
                    preset_name=tmpl.get("preset_name"),
                )
                active_titles.add(game.title)
                q = Quest(
                    game_id=game.id,
                    card_type=tmpl["card_type"],
                    card_title=tmpl["card_title"],
                    tag_filter=tmpl.get("tag_filter"),
                    min_hltb_hours=tmpl.get("min_hltb_hours"),
                    max_hltb_hours=tmpl.get("max_hltb_hours"),
                    min_rating=tmpl.get("min_rating"),
                    is_santa_box=False,
                    is_roulette=True,
                    status=QuestStatus.AVAILABLE,
                    spawned_at=now,
                )
                session.add(q)
                new_quests.append(q)

    if new_quests:
        await session.commit()

    return new_quests


async def get_quests(
    session: AsyncSession,
    status: QuestStatus | None = None,
) -> Sequence[Quest]:
    """Retrieves all quests or quests filtered by status with all relationships loaded."""
    query = (
        select(Quest)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.user),
            selectinload(Quest.challenge),
        )
        .order_by(Quest.id.desc())
    )
    if status is not None:
        query = query.where(Quest.status == status)

    result = await session.execute(query)
    return result.scalars().all()


async def get_user_active_quests(session: AsyncSession, user_id: int) -> list[Quest]:
    """Finds all currently active (IN_PROGRESS) quests for a user (up to MAX_ACTIVE_QUESTS)."""
    query = (
        select(Quest)
        .where(Quest.user_id == user_id, Quest.status == QuestStatus.IN_PROGRESS)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.challenge),
        )
        .order_by(Quest.started_at.desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_user_active_quest(session: AsyncSession, user_id: int) -> Quest | None:
    """Finds currently active (IN_PROGRESS) quest for a user if any exists (returns first)."""
    active = await get_user_active_quests(session, user_id)
    return active[0] if active else None


async def get_quest_by_id(session: AsyncSession, quest_id: int) -> Quest | None:
    """Fetches quest with all related entities."""
    query = (
        select(Quest)
        .where(Quest.id == quest_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.user),
            selectinload(Quest.challenge),
        )
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def take_quest(
    session: AsyncSession,
    quest_id: int,
    user_id: int,
    challenge_id: int | None = None,
    specific_game_id: int | None = None,
) -> Quest:
    """Assigns an AVAILABLE quest to user with atomic status claim, inflation cap, and conveyor refill."""
    now = datetime.now(timezone.utc)

    # 1. Check user existence
    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"Пользователь #{user_id} не найден")

    # 2. Check slots limit: user cannot exceed settings.MAX_ACTIVE_QUESTS (2)
    active_count_stmt = (
        select(func.count(Quest.id))
        .where(Quest.user_id == user_id, Quest.status == QuestStatus.IN_PROGRESS)
    )
    active_count = (await session.execute(active_count_stmt)).scalar() or 0
    if active_count >= settings.MAX_ACTIVE_QUESTS:
        raise ValueError(
            f"Достигнут лимит активных квестов ({settings.MAX_ACTIVE_QUESTS}/{settings.MAX_ACTIVE_QUESTS}). "
            f"Сдайте или сбросьте один из текущих квестов перед взятием нового."
        )

    # 3. Preview quest for underdog check
    quest_preview = await session.get(Quest, quest_id)
    if not quest_preview or quest_preview.status != QuestStatus.AVAILABLE:
        raise ValueError("Контракт уже забрал другой игрок!")

    if quest_preview.is_underdog_only:
        user_is_underdog = await is_underdog(session, user)
        if not user_is_underdog:
            raise PermissionError(
                f"Этот квест доступен только участникам со статусом 'Андердог' "
                f"(отставание от лидера > {settings.UNDERDOG_SCORE_GAP} очков)"
            )

    # 4. Atomic row claim via UPDATE to prevent race conditions on both SQLite and PostgreSQL
    claim_values: dict[str, Any] = {
        "status": QuestStatus.IN_PROGRESS,
        "user_id": user_id,
        "started_at": now,
    }
    if specific_game_id:
        claim_values["game_id"] = specific_game_id
        claim_values["current_rolled_game_id"] = specific_game_id

    claim_stmt = (
        update(Quest)
        .where(Quest.id == quest_id, Quest.status == QuestStatus.AVAILABLE)
        .values(**claim_values)
    )
    res = await session.execute(claim_stmt)
    if res.rowcount == 0:
        raise ValueError("Контракт уже забрал другой игрок!")

    quest = await get_quest_by_id(session, quest_id)
    if not quest:
        raise ValueError(f"Квест #{quest_id} не найден")

    # 5. Capped inflation calculation (Hard Cap = MAX_INFLATION_INTERVALS, e.g. +60%)
    spawned = quest.spawned_at if quest.spawned_at.tzinfo else quest.spawned_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - spawned).total_seconds()
    interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
    intervals = min(settings.MAX_INFLATION_INTERVALS, max(0, int(elapsed_seconds // interval_seconds)))
    inflation_mult = 1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals

    # 6. Распаковка подарка Санты (50/50 жребий или конкретная выпавшая игра)
    if quest.is_santa_box:
        if specific_game_id:
            santa_game = await session.get(Game, specific_game_id)
            if not santa_game:
                fallback_query = select(Game).order_by(func.random()).limit(1)
                santa_game = (await session.execute(fallback_query)).scalar_one()
            target_category = santa_game.category
            bonus_pct = 0.10 if target_category == "SANTA_TOP" else 0.50
        elif quest.current_rolled_game_id:
            santa_game = await session.get(Game, quest.current_rolled_game_id)
            if not santa_game:
                fallback_query = select(Game).order_by(func.random()).limit(1)
                santa_game = (await session.execute(fallback_query)).scalar_one()
            target_category = santa_game.category
            bonus_pct = 0.10 if target_category == "SANTA_TOP" else 0.50
        else:
            is_top_gift = random.choice([True, False])
            target_category = "SANTA_TOP" if is_top_gift else "SANTA_COAL"
            bonus_pct = 0.10 if is_top_gift else 0.50

            santa_query = select(Game).where(Game.category == target_category).order_by(func.random()).limit(1)
            santa_game = (await session.execute(santa_query)).scalar_one_or_none()
            if not santa_game:
                fallback_query = select(Game).order_by(func.random()).limit(1)
                santa_game = (await session.execute(fallback_query)).scalar_one()

        quest.game_id = santa_game.id
        quest.current_rolled_game_id = santa_game.id
        quest.is_santa_box = False
        quest.card_type = target_category

        # Фиксируем награду с бонусом Санты (+10% для топа или +50% для уголька) и инфляцией
        santa_base_reward = round(santa_game.reward_points * (1.0 + bonus_pct))
        quest.locked_reward = round(santa_base_reward * inflation_mult)
    else:
        # Обычный квест или рулетка
        if specific_game_id and quest.is_roulette:
            quest.current_rolled_game_id = specific_game_id
            quest.game_id = specific_game_id
        elif quest.is_roulette and quest.game_list_ids:
            quest.current_rolled_game_id = random.choice(quest.game_list_ids)
            quest.game_id = quest.current_rolled_game_id
        elif quest.is_roulette and not quest.game_list_ids:
            quest.current_rolled_game_id = quest.game_id

        active_game = await session.get(Game, quest.game_id)
        if not active_game:
            raise ValueError(f"Игра для квеста #{quest.id} не определена")
        quest.game = active_game

        base_reward = active_game.reward_points
        quest.locked_reward = round(base_reward * inflation_mult)

    # 7. Привязка опционального челленджа
    if challenge_id is not None:
        challenge = await session.get(Challenge, challenge_id)
        if not challenge:
            raise ValueError(f"Модификатор/челлендж #{challenge_id} не найден")
        quest.challenge_id = challenge_id
    else:
        quest.challenge_id = None

    await session.commit()

    # 8. Конвейер: восполняем доску до settings.MAX_BOARD_SIZE (12)
    await refill_board(session)

    return await get_quest_by_id(session, quest.id)  # type: ignore


async def set_quest_challenge(
    session: AsyncSession,
    quest_id: int,
    user_id: int,
    challenge_id: Optional[int] = None,
) -> Quest:
    """Sets optional challenge on quest (or None) and transitions it to IN_PROGRESS."""
    quest = await get_quest_by_id(session, quest_id)
    if not quest:
        raise ValueError(f"Квест #{quest_id} не найден")

    if challenge_id is not None:
        challenge = await session.get(Challenge, challenge_id)
        if not challenge:
            raise ValueError(f"Челлендж #{challenge_id} не найден")
        quest.challenge_id = challenge_id
    else:
        quest.challenge_id = None

    quest.user_id = user_id
    quest.status = QuestStatus.IN_PROGRESS
    quest.started_at = datetime.now(timezone.utc)

    await session.commit()
    await refill_board(session)
    return await get_quest_by_id(session, quest.id)  # type: ignore


async def reroll_quest(
    session: AsyncSession,
    quest_id: int,
    user_id: int,
    specific_game_id: Optional[int] = None,
) -> Quest:
    """Executes reroll: spends 1 user reroll, increments quest reroll count, picks new game from quest's category."""
    quest = await get_quest_by_id(session, quest_id)
    if not quest:
        raise ValueError(f"Квест #{quest_id} не найден")
    if quest.status != QuestStatus.IN_PROGRESS:
        raise ValueError(f"Квест #{quest_id} не находится в процессе прохождения (статус: {quest.status.value})")
    if quest.user_id != user_id:
        raise ValueError(f"Квест #{quest_id} закреплен за другим участником")

    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"Пользователь #{user_id} не найден")
    if user.rerolls_left <= 0:
        raise ValueError("У вас нет доступных попыток реролла (rerolls_left = 0)")

    # Determine category
    category = quest.game.category if quest.game else quest.card_type

    if specific_game_id:
        new_game = await session.get(Game, specific_game_id)
        if not new_game:
            raise ValueError(f"Игра #{specific_game_id} не найдена")
    else:
        # If quest has explicit game_list_ids
        if quest.game_list_ids:
            candidates_ids = [gid for gid in quest.game_list_ids if gid != quest.game_id]
            if not candidates_ids:
                candidates_ids = quest.game_list_ids
            rolled_gid = random.choice(candidates_ids)
            new_game = await session.get(Game, rolled_gid)
        else:
            # Ищем новую игру в games.db по фильтрам квеста
            exclude = {quest.game.title} if quest.game else set()
            candidates_dicts = query_games_from_parser_db(
                tag=quest.tag_filter,
                min_hours=quest.min_hltb_hours,
                max_hours=quest.max_hltb_hours,
                min_rating=quest.min_rating,
                is_santa_top=(quest.card_type == "SANTA_TOP"),
                is_santa_coal=(quest.card_type == "SANTA_COAL"),
                exclude_titles=exclude,
                limit=10,
            )
            if candidates_dicts:
                chosen_dict = random.choice(candidates_dicts)
                new_game = await sync_game_to_hpg(session, chosen_dict, category=category)
            else:
                cat_stmt = select(Game).where(Game.category == category)
                if quest.game_id:
                    diff_stmt = cat_stmt.where(Game.id != quest.game_id)
                    candidates = list((await session.execute(diff_stmt)).scalars().all())
                    if not candidates:
                        candidates = list((await session.execute(cat_stmt)).scalars().all())
                else:
                    candidates = list((await session.execute(cat_stmt)).scalars().all())

                if not candidates:
                    fallback_stmt = select(Game).where(Game.id != quest.game_id) if quest.game_id else select(Game)
                    candidates = list((await session.execute(fallback_stmt)).scalars().all())

                if not candidates:
                    raise ValueError("Не удалось найти подходящую игру для реролла")

                new_game = random.choice(candidates)

    if not new_game:
        raise ValueError("Ошибка выбора новой игры для реролла")

    # Calculate locked_reward preserving inflation and special bonuses
    now = datetime.now(timezone.utc)
    spawned = quest.spawned_at if quest.spawned_at.tzinfo else quest.spawned_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - spawned).total_seconds()
    interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
    intervals = min(settings.MAX_INFLATION_INTERVALS, max(0, int(elapsed_seconds // interval_seconds)))
    inflation_mult = 1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals

    bonus_pct = 0.0
    if quest.card_type == "SANTA_TOP":
        bonus_pct = 0.10
    elif quest.card_type == "SANTA_COAL":
        bonus_pct = 0.50

    base_reward = round(new_game.reward_points * (1.0 + bonus_pct))
    quest.locked_reward = round(base_reward * inflation_mult)

    quest.game_id = new_game.id
    quest.current_rolled_game_id = new_game.id
    quest.reroll_count += 1
    user.rerolls_left -= 1

    await session.commit()
    return await get_quest_by_id(session, quest.id)  # type: ignore



async def complete_quest(
    session: AsyncSession,
    quest_id: int,
    user_id: int,
    challenge_status: Optional[str] = None,
) -> tuple[Quest, int, dict]:
    """Marks quest as COMPLETED, calculates final points based on locked_reward, challenge outcome, reroll penalties, and underdog bonuses."""
    quest = await get_quest_by_id(session, quest_id)
    if not quest:
        raise ValueError(f"Квест #{quest_id} не найден")
    if quest.status != QuestStatus.IN_PROGRESS:
        raise ValueError(f"Квест #{quest_id} не находится в процессе прохождения (статус: {quest.status.value})")
    if quest.user_id != user_id:
        raise ValueError(f"Квест #{quest_id} закреплен за другим участником")

    user = quest.user
    active_game = quest.current_rolled_game if (quest.is_roulette and quest.current_rolled_game) else quest.game

    # 1. Base reward: используем зафиксированную инфляционную награду
    default_base = active_game.reward_points if active_game else 100
    base_points = quest.locked_reward if quest.locked_reward is not None else default_base

    # 2. Challenge multiplier (Success vs Failed)
    challenge_mult = 1.0
    if quest.challenge:
        if challenge_status == "success":
            challenge_mult = quest.challenge.bonus_multiplier
            quest.challenge_successful = True
        elif challenge_status == "failed":
            challenge_mult = quest.challenge.penalty_multiplier
            quest.challenge_successful = False
        else:
            challenge_mult = quest.challenge.bonus_multiplier
            quest.challenge_successful = True
    else:
        quest.challenge_successful = None

    base_reward = base_points * challenge_mult

    # 3. Reroll penalty
    reroll_penalty_rate = min(1.0, settings.REROLL_PENALTY_RATE * quest.reroll_count)
    reward_after_reroll = base_reward * (1.0 - reroll_penalty_rate)

    # 4. Underdog bonus: applied AFTER reroll penalty
    user_is_underdog = await is_underdog(session, user)
    if user_is_underdog:
        final_reward = round(reward_after_reroll * settings.UNDERDOG_BONUS_MULTIPLIER)
    else:
        final_reward = round(reward_after_reroll)

    # 5. Update user score
    user.total_score += final_reward

    # 6. Reroll regeneration (every N completed quests)
    user.quests_since_reroll += 1
    recharged_reroll = False
    if user.quests_since_reroll >= settings.QUESTS_PER_REROLL_RECHARGE:
        user.quests_since_reroll = 0
        user.rerolls_left += 1
        recharged_reroll = True

    # 7. Update quest status
    quest.status = QuestStatus.COMPLETED
    quest.completed_at = datetime.now(timezone.utc)

    details = {
        "base_reward": round(base_reward),
        "locked_reward": quest.locked_reward,
        "challenge_status": challenge_status,
        "challenge_successful": quest.challenge_successful,
        "challenge_multiplier": challenge_mult,
        "reroll_count": quest.reroll_count,
        "reroll_penalty_pct": int(reroll_penalty_rate * 100),
        "is_underdog": user_is_underdog,
        "underdog_bonus_applied": user_is_underdog,
        "final_reward": final_reward,
        "recharged_reroll": recharged_reroll,
        "rerolls_left": user.rerolls_left,
        "quests_since_reroll": user.quests_since_reroll,
    }

    await session.commit()
    refreshed_quest = await get_quest_by_id(session, quest.id)
    return refreshed_quest, final_reward, details  # type: ignore



async def drop_quest(
    session: AsyncSession,
    quest_id: int,
    user_id: int,
) -> tuple[Quest, int, bool]:
    """Drops quest with Free Drops mechanic: uses free drop if available, else deducts penalty. Refills board."""
    quest = await get_quest_by_id(session, quest_id)
    if not quest:
        raise ValueError(f"Квест #{quest_id} не найден")
    if quest.status != QuestStatus.IN_PROGRESS:
        raise ValueError(f"Квест #{quest_id} не находится в процессе прохождения (статус: {quest.status.value})")
    if quest.user_id != user_id:
        raise ValueError(f"Квест #{quest_id} закреплен за другим участником")

    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"Пользователь #{user_id} не найден")
    active_game = quest.current_rolled_game if (quest.is_roulette and quest.current_rolled_game) else quest.game

    # Free drops logic
    if user.free_drops > 0:
        user.free_drops -= 1
        penalty = 0
        used_free_drop = True
    else:
        penalty = active_game.penalty_points if active_game else 50
        user.total_score -= penalty
        used_free_drop = False

    quest.status = QuestStatus.DROPPED
    quest.completed_at = datetime.now(timezone.utc)

    await session.commit()
    refreshed_quest = await get_quest_by_id(session, quest.id)

    # При отказе восполняем доску
    await refill_board(session)

    return refreshed_quest, penalty, used_free_drop  # type: ignore
