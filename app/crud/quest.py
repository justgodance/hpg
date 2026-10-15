from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import random
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.crud.user import is_underdog
from app.models.challenge import Challenge
from app.models.game import Game
from app.models.quest import Quest, QuestStatus
from app.models.user import User

# Вероятности категорий при генерации квестов на доске
CATEGORY_WEIGHTS: dict[str, float] = {
    "STEAM": 0.40,
    "PRESET": 0.25,
    "SERIES": 0.15,
    "EMULATOR": 0.10,
    "SANTA": 0.07,
    "GOTY": 0.03,
}


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


async def refill_board(session: AsyncSession) -> list[Quest]:
    """Механика 'Конвейер (Тетрис)':
    Поддерживает количество квестов со статусом AVAILABLE равным settings.MAX_BOARD_SIZE (12).
    Использует взвешенное случайное распределение категорий:
    STEAM (40%), PRESET (25%), SERIES (15%), EMULATOR (10%), SANTA (7%), GOTY (3%).
    """
    max_size = settings.MAX_BOARD_SIZE
    count_stmt = select(func.count(Quest.id)).where(Quest.status == QuestStatus.AVAILABLE)
    available_count = (await session.execute(count_stmt)).scalar() or 0

    if available_count >= max_size:
        return []

    needed = max_size - available_count

    # ID игр, которые уже представлены на доске
    active_games_stmt = select(Quest.game_id).where(
        Quest.status.in_([QuestStatus.AVAILABLE, QuestStatus.IN_PROGRESS]),
        Quest.game_id.is_not(None),
    )
    active_game_ids = set((await session.execute(active_games_stmt)).scalars().all())

    categories = list(CATEGORY_WEIGHTS.keys())
    weights = list(CATEGORY_WEIGHTS.values())
    chosen_categories = random.choices(categories, weights=weights, k=needed)

    new_quests: list[Quest] = []
    now = datetime.now(timezone.utc)

    for cat in chosen_categories:
        if cat == "SANTA":
            # Спец-квест: коробка Санты без привязки игры до распаковки
            q = Quest(
                game_id=None,
                card_type="SANTA",
                is_santa_box=True,
                status=QuestStatus.AVAILABLE,
                spawned_at=now,
            )
            session.add(q)
            new_quests.append(q)
        else:
            # Выбираем случайную игру этой категории, которой нет на доске
            games_query = select(Game).where(Game.category == cat)
            if active_game_ids:
                games_query = games_query.where(Game.id.not_in(active_game_ids))
            games_query = games_query.order_by(func.random()).limit(1)
            game = (await session.execute(games_query)).scalar_one_or_none()

            # Фолбэк: если все игры категории на доске, берем любую игру категории
            if not game:
                fallback_query = select(Game).where(Game.category == cat).order_by(func.random()).limit(1)
                game = (await session.execute(fallback_query)).scalar_one_or_none()

            # Крайний фолбэк: любая игра из базы
            if not game:
                any_query = select(Game).order_by(func.random()).limit(1)
                game = (await session.execute(any_query)).scalar_one_or_none()

            if game:
                active_game_ids.add(game.id)
                q = Quest(
                    game_id=game.id,
                    card_type=cat,
                    is_santa_box=False,
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


async def get_user_active_quest(session: AsyncSession, user_id: int) -> Quest | None:
    """Finds currently active (IN_PROGRESS) quest for a user if any exists."""
    query = (
        select(Quest)
        .where(Quest.user_id == user_id, Quest.status == QuestStatus.IN_PROGRESS)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.challenge),
        )
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_quest_by_id(session: AsyncSession, quest_id: int) -> Quest | None:
    """Fetches quest with all related entities."""
    query = (
        select(Quest)
        .where(Quest.id == quest_id)
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
    """Assigns an AVAILABLE quest to user with Santa box unpacking, inflation locking, and conveyor refill."""
    # 1. Row-level lock via with_for_update()
    quest_stmt = (
        select(Quest)
        .where(Quest.id == quest_id)
        .options(
            selectinload(Quest.game),
            selectinload(Quest.current_rolled_game),
            selectinload(Quest.user),
            selectinload(Quest.challenge),
        )
        .with_for_update()
    )
    quest = (await session.execute(quest_stmt)).scalar_one_or_none()
    if not quest or quest.status != QuestStatus.AVAILABLE:
        raise ValueError("Контракт уже забрал другой игрок!")

    # 2. Check user existence
    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"Пользователь #{user_id} не найден")

    # 3. Check slots limit: user cannot have 1 or more IN_PROGRESS quests
    active_count_stmt = (
        select(func.count(Quest.id))
        .where(Quest.user_id == user_id, Quest.status == QuestStatus.IN_PROGRESS)
    )
    active_count = (await session.execute(active_count_stmt)).scalar() or 0
    if active_count >= 1:
        raise ValueError("Достигнут лимит активных квестов: у вас уже есть один активный квест. Сдайте или сбросьте текущий.")

    # 4. Underdog check
    if quest.is_underdog_only:
        user_is_underdog = await is_underdog(session, user)
        if not user_is_underdog:
            raise PermissionError(
                f"Этот квест доступен только участникам со статусом 'Андердог' "
                f"(отставание от лидера > {settings.UNDERDOG_SCORE_GAP} очков)"
            )

    now = datetime.now(timezone.utc)
    spawned = quest.spawned_at if quest.spawned_at.tzinfo else quest.spawned_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - spawned).total_seconds()
    interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
    intervals = max(0, int(elapsed_seconds // interval_seconds))
    inflation_mult = 1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals

    # 5. Распаковка подарка Санты (50/50 жребий или конкретная выпавшая игра)
    if quest.is_santa_box:
        if specific_game_id:
            santa_game = await session.get(Game, specific_game_id)
            if not santa_game:
                fallback_query = select(Game).order_by(func.random()).limit(1)
                santa_game = (await session.execute(fallback_query)).scalar_one()
            target_category = santa_game.category
            bonus_pct = 0.10 if target_category == "SANTA_TOP" else 0.50
        else:
            is_top_gift = random.choice([True, False])
            target_category = "SANTA_TOP" if is_top_gift else "SANTA_COAL"
            bonus_pct = 0.10 if is_top_gift else 0.50

            # Выбираем случайную игру из соответствующей категории Санты
            santa_query = select(Game).where(Game.category == target_category).order_by(func.random()).limit(1)
            santa_game = (await session.execute(santa_query)).scalar_one_or_none()

            if not santa_game:
                fallback_query = select(Game).order_by(func.random()).limit(1)
                santa_game = (await session.execute(fallback_query)).scalar_one()

        quest.game_id = santa_game.id
        quest.is_santa_box = False
        quest.card_type = target_category

        # Фиксируем награду с бонусом Санты (+10% для топа или +50% для уголька) и инфляцией
        santa_base_reward = round(santa_game.reward_points * (1.0 + bonus_pct))
        quest.locked_reward = round(santa_base_reward * inflation_mult)
    else:
        # Обычный квест или рулетка
        if specific_game_id and quest.is_roulette:
            quest.current_rolled_game_id = specific_game_id
        elif quest.is_roulette and quest.game_list_ids:
            quest.current_rolled_game_id = random.choice(quest.game_list_ids)
        elif quest.is_roulette and not quest.game_list_ids:
            quest.current_rolled_game_id = quest.game_id

        active_game = quest.current_rolled_game if (quest.is_roulette and quest.current_rolled_game) else quest.game
        if not active_game:
            raise ValueError(f"Игра для квеста #{quest.id} не определена")

        base_reward = active_game.reward_points
        quest.locked_reward = round(base_reward * inflation_mult)

    # 6. Привязка опционального челленджа
    if challenge_id is not None:
        challenge = await session.get(Challenge, challenge_id)
        if not challenge:
            raise ValueError(f"Модификатор/челлендж #{challenge_id} не найден")
        quest.challenge_id = challenge_id
    else:
        quest.challenge_id = None

    # 7. Перевод в статус IN_PROGRESS
    quest.user_id = user_id
    quest.status = QuestStatus.IN_PROGRESS
    quest.started_at = now

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

    user = quest.user
    if not user or user.rerolls_left <= 0:
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
    intervals = max(0, int(elapsed_seconds // interval_seconds))
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

    user = quest.user
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
