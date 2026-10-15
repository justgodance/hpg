from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.quest import Quest, QuestStatus
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["Admin"])


class RevertQuestRequest(BaseModel):
    score_adjustment: int = Field(
        ...,
        description="Количество очков для вычета или прибавления пользователю при откате квеста (может быть отрицательным)",
    )


class AdjustScoreRequest(BaseModel):
    amount: int = Field(
        ...,
        description="Количество очков для прямого изменения счета пользователя (может быть отрицательным)",
    )


class AdminQuestRevertResponse(BaseModel):
    message: str
    quest_id: int
    status: str
    challenge_successful: Optional[bool]
    score_adjustment: int
    user_id: Optional[int]
    new_user_score: Optional[int]


class AdminUserScoreResponse(BaseModel):
    message: str
    user_id: int
    username: str
    adjustment: int
    new_total_score: int


@router.post("/quests/{quest_id}/revert", response_model=AdminQuestRevertResponse)
async def revert_quest(
    quest_id: int,
    payload: RevertQuestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Откатывает квест из статусов COMPLETED или DROPPED обратно в IN_PROGRESS.
    Сбрасывает challenge_successful в None и корректирует total_score пользователя
    на значение score_adjustment.
    """
    stmt = (
        select(Quest)
        .where(Quest.id == quest_id)
        .options(selectinload(Quest.user))
    )
    res = await db.execute(stmt)
    quest = res.scalar_one_or_none()

    if not quest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Квест #{quest_id} не найден",
        )

    if quest.status not in (QuestStatus.COMPLETED, QuestStatus.DROPPED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Невозможно откатить квест #{quest_id}: текущий статус '{quest.status.value}'. "
                f"Откат разрешен только для квестов в статусах COMPLETED или DROPPED."
            ),
        )

    # 1. Откатываем статус квеста в IN_PROGRESS
    quest.status = QuestStatus.IN_PROGRESS
    quest.completed_at = None
    quest.challenge_successful = None

    # 2. Корректируем очки пользователя
    new_user_score = None
    if quest.user:
        quest.user.total_score += payload.score_adjustment
        new_user_score = quest.user.total_score
    elif quest.user_id:
        user = await db.get(User, quest.user_id)
        if user:
            user.total_score += payload.score_adjustment
            new_user_score = user.total_score

    await db.commit()
    await db.refresh(quest)

    return AdminQuestRevertResponse(
        message=f"Квест #{quest.id} успешно возвращен в статус IN_PROGRESS",
        quest_id=quest.id,
        status=quest.status.value,
        challenge_successful=quest.challenge_successful,
        score_adjustment=payload.score_adjustment,
        user_id=quest.user_id,
        new_user_score=new_user_score,
    )


@router.post("/users/{user_id}/adjust_score", response_model=AdminUserScoreResponse)
async def adjust_user_score(
    user_id: int,
    payload: AdjustScoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Напрямую прибавляет или вычитает значение amount из total_score пользователя.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь #{user_id} не найден",
        )

    user.total_score += payload.amount
    await db.commit()
    await db.refresh(user)

    sign = "+" if payload.amount >= 0 else ""
    return AdminUserScoreResponse(
        message=f"Счет пользователя {user.username} успешно скорректирован ({sign}{payload.amount})",
        user_id=user.id,
        username=user.username,
        adjustment=payload.amount,
        new_total_score=user.total_score,
    )
