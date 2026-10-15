from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="Имя игрока")
    avatar_url: str | None = Field(default=None, description="URL аватарки")


class UserCreate(UserBase):
    pin_code: str | None = Field(default=None, max_length=10, description="4-значный ПИН-код")


class UserRead(UserBase):
    id: int
    total_score: int
    free_drops: int
    rerolls_left: int
    quests_since_reroll: int
    pin_code: str | None = None
    is_underdog: bool = False

    model_config = ConfigDict(from_attributes=True)

