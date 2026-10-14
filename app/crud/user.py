from __future__ import annotations

from collections.abc import Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.schemas.user import UserCreate



async def create_user(session: AsyncSession, data: UserCreate) -> User:
    """Creates a new user if username is unique."""
    existing = await get_user_by_username(session, data.username)
    if existing:
        raise ValueError(f"Пользователь с именем '{data.username}' уже существует")

    user = User(username=data.username, total_score=0)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    """Retrieves user by primary key ID."""
    return await session.get(User, user_id)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    """Retrieves user by unique username."""
    query = select(User).where(User.username == username)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_users_leaderboard(session: AsyncSession) -> Sequence[User]:
    """Retrieves all users sorted by total_score descending (Leaderboard)."""
    query = select(User).order_by(User.total_score.desc(), User.id.asc())
    result = await session.execute(query)
    return result.scalars().all()


async def is_underdog(session: AsyncSession, user: User) -> bool:
    """Определяет, является ли игрок Андердогом (отставание от лидера > UNDERDOG_SCORE_GAP)."""
    query = select(func.max(User.total_score))
    result = await session.execute(query)
    leader_score = result.scalar()
    if leader_score is None:
        return False
    return (leader_score - user.total_score) > settings.UNDERDOG_SCORE_GAP


