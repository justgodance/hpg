from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.quest import (
    complete_quest,
    create_quest,
    drop_quest,
    get_quest_by_id,
    get_quests,
    refill_board,
    reroll_quest,
    take_quest,
)
from app.database import get_db
from app.models.quest import QuestStatus
from app.schemas.quest import QuestCreate, QuestRead, QuestResponse, QuestTakeRequest

router = APIRouter(prefix="/api/quests", tags=["Quests"])



class QuestActionResult(BaseModel):
    message: str
    quest_id: int
    points_delta: int
    new_user_score: int
    details: dict[str, Any] | None = None


class QuestDropResult(BaseModel):
    message: str
    quest_id: int
    penalty: int
    used_free_drop: bool
    free_drops_remaining: int
    new_user_score: int


@router.get("/", response_model=list[QuestRead])
async def list_quests_endpoint(
    status: QuestStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Возвращает квесты для доски, с опциональной фильтрацией по статусу."""
    return await get_quests(db, status=status)


@router.post("/", response_model=QuestResponse, status_code=status.HTTP_201_CREATED)
async def create_quest_endpoint(
    payload: QuestCreate,
    db: AsyncSession = Depends(get_db),
):
    """Создает новый квест на доске (обычный, подарок Санты, рулетка или эксклюзивный для Андердогов)."""
    try:
        return await create_quest(
            session=db,
            game_id=payload.game_id,
            card_type=payload.card_type,
            is_santa_box=payload.is_santa_box,
            is_roulette=payload.is_roulette,
            game_list_ids=payload.game_list_ids,
            is_underdog_only=payload.is_underdog_only,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))



@router.post("/refill-board", response_model=list[QuestResponse])
async def refill_board_endpoint(db: AsyncSession = Depends(get_db)):
    """Принудительно пополняет Канбан-доску до 12 доступных квестов ('Конвейер')."""
    return await refill_board(db)


@router.get("/{quest_id}", response_model=QuestResponse)
async def get_quest(quest_id: int, db: AsyncSession = Depends(get_db)):

    """Возвращает детальную информацию о квесте."""
    quest = await get_quest_by_id(db, quest_id)
    if not quest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Квест не найден")
    return quest


@router.post("/{quest_id}/take", response_model=QuestResponse)
async def take_quest_endpoint(
    quest_id: int,
    payload: QuestTakeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Пользователь берет квест: распаковывает подарок Санты (при наличии), фиксирует награду и восполняет доску ('Конвейер')."""
    try:

        quest = await take_quest(
            session=db,
            quest_id=quest_id,
            user_id=payload.user_id,
            challenge_id=payload.challenge_id,
        )
        return quest
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{quest_id}/reroll", response_model=QuestRead)
async def reroll_quest_endpoint(
    quest_id: int,
    user_id: int = Query(..., description="ID пользователя, совершающего реролл"),
    db: AsyncSession = Depends(get_db),
):
    """Выполняет реролл рулетки: списывает 1 попытку реролла, выбирает новую игру и увеличивает счетчик рероллов."""
    try:
        quest = await reroll_quest(db, quest_id=quest_id, user_id=user_id)
        return quest
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{quest_id}/complete", response_model=QuestActionResult)
async def complete_quest_endpoint(
    quest_id: int,
    user_id: int = Query(..., description="ID пользователя, сдающего квест"),
    challenge_status: str | None = Query(None, description="Статус выполнения челленджа: 'success' или 'failed'"),
    db: AsyncSession = Depends(get_db),
):
    """Завершение квеста: рассчитывает бонус/штраф за челлендж, штраф за рероллы (-10%/реролл) и бонус Андердога (+20%)."""
    try:
        quest, points_earned, details = await complete_quest(
            db, quest_id=quest_id, user_id=user_id, challenge_status=challenge_status
        )
        msg_parts = [f"Квест успешно сдан! Начислено: +{points_earned} очков."]
        if details.get("challenge_status"):
            if details["challenge_status"] == "success":
                msg_parts.append(f"Челлендж выполнен (множитель x{details['challenge_multiplier']})!")
            else:
                msg_parts.append(f"Челлендж провален (штрафной множитель x{details['challenge_multiplier']}).")
        if details["reroll_penalty_pct"] > 0:
            msg_parts.append(f"Штраф за {details['reroll_count']} реролла(ов): -{details['reroll_penalty_pct']}%.")
        if details["underdog_bonus_applied"]:
            msg_parts.append("Применен бонус Андердога: +20%!")
        if details["recharged_reroll"]:
            msg_parts.append("Получен +1 реролл за 3 выполненных квеста!")

        return QuestActionResult(
            message=" ".join(msg_parts),
            quest_id=quest.id,
            points_delta=points_earned,
            new_user_score=quest.user.total_score,
            details=details,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{quest_id}/drop", response_model=QuestDropResult)
async def drop_quest_endpoint(
    quest_id: int,
    user_id: int = Query(..., description="ID пользователя, отказывающегося от квеста"),
    db: AsyncSession = Depends(get_db),
):
    """Отказ от квеста: использует бесплатный дроп при наличии, иначе списывает штрафные очки."""
    try:
        quest, penalty, used_free_drop = await drop_quest(db, quest_id=quest_id, user_id=user_id)
        if used_free_drop:
            msg = f"Использован бесплатный дроп! Штраф не списан. Осталось бесплатных дропов: {quest.user.free_drops}."
        else:
            msg = f"Бесплатных дропов не осталось. Списан штраф: -{penalty} очков."

        return QuestDropResult(
            message=msg,
            quest_id=quest.id,
            penalty=penalty,
            used_free_drop=used_free_drop,
            free_drops_remaining=quest.user.free_drops,
            new_user_score=quest.user.total_score,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
