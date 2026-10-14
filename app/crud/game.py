from __future__ import annotations

from collections.abc import Sequence
import json
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.game import Game
from app.schemas.game import GameCreate


async def create_game(session: AsyncSession, data: GameCreate) -> Game:
    """Creates a new game in catalog."""
    game = Game(
        title=data.title,
        hltb_hours=data.hltb_hours,
        reward_points=data.reward_points,
        penalty_points=data.penalty_points,
    )
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game


async def get_games(session: AsyncSession) -> Sequence[Game]:
    """Retrieves all games from catalog."""
    query = select(Game).order_by(Game.title.asc())
    result = await session.execute(query)
    return result.scalars().all()


async def get_game_by_id(session: AsyncSession, game_id: int) -> Game | None:
    """Retrieves game by ID."""
    return await session.get(Game, game_id)


async def seed_games_if_empty(session: AsyncSession) -> None:
    """Pre-populates catalog from external games.json file if database is empty."""
    query = select(func.count(Game.id))
    result = await session.execute(query)
    count = result.scalar() or 0
    if count == 0:
        if settings.GAMES_DATA_PATH.exists():
            with open(settings.GAMES_DATA_PATH, "r", encoding="utf-8") as f:
                games_data = json.load(f)
            for item in games_data:
                session.add(Game(**item))
            await session.commit()
