from collections.abc import Sequence
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.game import create_game, get_game_by_id, get_games
from app.database import get_db
from app.schemas.game import GameCreate, GameRead

router = APIRouter(prefix="/api/games", tags=["Games"])


@router.post("/", response_model=GameRead, status_code=status.HTTP_201_CREATED)
async def add_game(payload: GameCreate, db: AsyncSession = Depends(get_db)):
    """Добавляет игру в общий каталог марафона."""
    return await create_game(db, payload)


@router.get("/", response_model=list[GameRead])
async def list_games(db: AsyncSession = Depends(get_db)) -> Sequence[GameRead]:
    """Возвращает список всех игр в каталоге."""
    return await get_games(db)


@router.get("/{game_id}", response_model=GameRead)
async def get_game(game_id: int, db: AsyncSession = Depends(get_db)):
    """Возвращает информацию о конкретной игре."""
    game = await get_game_by_id(db, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игра не найдена")
    return game
