from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field


class GameBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Название игры")
    category: str = Field(default="STEAM", description="Категория игры (STEAM, GOTY, SERIES, PRESET, EMULATOR, SANTA_TOP, SANTA_COAL)")
    genre: str = Field(default="Экшен", description="Жанр игры")
    preset_name: str | None = Field(default=None, description="Название пресета / франшизы / платформы")
    hltb_hours: float = Field(default=0.0, ge=0.0, description="Примерное время прохождения (HLTB в часах)")
    reward_points: int = Field(default=100, ge=0, description="Очки за успешное прохождение")
    penalty_points: int = Field(default=50, ge=0, description="Штрафные очки за отказ от прохождения")

    @computed_field
    @property
    def time_range(self) -> str:
        if self.hltb_hours <= 10.0:
            return "5–10 ч"
        elif self.hltb_hours <= 20.0:
            return "10–20 ч"
        elif self.hltb_hours <= 35.0:
            return "20–35 ч"
        else:
            return "35+ ч"


class GameCreate(GameBase):
    pass


class GameRead(GameBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
