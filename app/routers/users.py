from __future__ import annotations

from collections.abc import Sequence
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.quest import get_user_active_quest
from app.crud.user import create_user, get_user_by_id, get_users_leaderboard, is_underdog
from app.database import get_db
from app.schemas.quest import QuestRead
from app.schemas.user import UserCreate, UserRead


router = APIRouter(prefix="/api/users", tags=["Users"])


class UserProfileRead(UserRead):
    active_quest: QuestRead | None = None


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """Регистрирует нового участника марафона."""
    try:
        user = await create_user(db, payload)
        return UserRead.model_validate(user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=list[UserRead])
async def list_leaderboard(db: AsyncSession = Depends(get_db)) -> list[UserRead]:
    """Возвращает таблицу лидеров с флагом статуса Андердога."""
    users = await get_users_leaderboard(db)
    leader_score = users[0].total_score if users else 0
    results: list[UserRead] = []
    for u in users:
        item = UserRead.model_validate(u)
        item.is_underdog = (leader_score - u.total_score) > settings.UNDERDOG_SCORE_GAP
        results.append(item)

    return results


@router.get("/{user_id}", response_model=UserProfileRead)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    """Возвращает профиль участника с активным квестом и статусом Андердога."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    active_quest = await get_user_active_quest(db, user_id)
    user_is_underdog = await is_underdog(db, user)
    return UserProfileRead(
        id=user.id,
        username=user.username,
        total_score=user.total_score,
        free_drops=user.free_drops,
        rerolls_left=user.rerolls_left,
        quests_since_reroll=user.quests_since_reroll,
        is_underdog=user_is_underdog,
        active_quest=active_quest,  # type: ignore
    )

