from __future__ import annotations

from collections.abc import Sequence
import json
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.challenge import Challenge


async def get_random_challenges(
    session: AsyncSession,
    limit: int = settings.CHALLENGE_ROLL_COUNT,
) -> Sequence[Challenge]:
    """Returns N random challenges from the database."""
    query = select(Challenge).order_by(func.random()).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


async def get_challenge_by_id(session: AsyncSession, challenge_id: int) -> Challenge | None:
    """Retrieves a challenge by its primary key ID."""
    query = select(Challenge).where(Challenge.id == challenge_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def seed_challenges_if_empty(session: AsyncSession) -> None:
    """Pre-populates challenges from external challenges.json file if database is empty."""
    query = select(func.count(Challenge.id))
    result = await session.execute(query)
    count = result.scalar() or 0
    if count == 0:
        if settings.CHALLENGES_DATA_PATH.exists():
            with open(settings.CHALLENGES_DATA_PATH, "r", encoding="utf-8") as f:
                challenges_data = json.load(f)
            for item in challenges_data:
                session.add(Challenge(**item))
            await session.commit()
