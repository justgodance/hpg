from collections.abc import Sequence
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.challenge import get_random_challenges
from app.database import get_db
from app.schemas.challenge import ChallengeRead

router = APIRouter(prefix="/api/challenges", tags=["Challenges"])


@router.get("/roll", response_model=list[ChallengeRead])
async def roll_challenges(
    limit: int = Query(default=settings.CHALLENGE_ROLL_COUNT, ge=1, le=10, description="Количество случайных челленджей"),
    db: AsyncSession = Depends(get_db),
) -> Sequence[ChallengeRead]:

    """Возвращает случайные модификаторы для выбора перед стартом квеста."""
    challenges = await get_random_challenges(db, limit=limit)
    return challenges
