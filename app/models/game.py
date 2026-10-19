from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.quest import Quest


class GameCategory(str, enum.Enum):
    STEAM = "STEAM"
    GOTY = "GOTY"
    SERIES = "SERIES"
    PRESET = "PRESET"
    EMULATOR = "EMULATOR"
    SANTA_TOP = "SANTA_TOP"
    SANTA_COAL = "SANTA_COAL"


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    steam_appid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(50),
        default=GameCategory.STEAM.value,
        nullable=False,
        index=True,
    )
    genre: Mapped[str] = mapped_column(String(100), default="Экшен", nullable=False)
    preset_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    hltb_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reward_points: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    penalty_points: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # Rich metadata from Steam / HLTB Parser (parser/data/games.db)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    developer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    review_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    review_desc: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    release_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    steam_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hltb_game_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hltb_game_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hltb_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hltb_status: Mapped[Optional[str]] = mapped_column(String(50), default="found", nullable=True)

    quests: Mapped[list["Quest"]] = relationship(
        foreign_keys="[Quest.game_id]",
        back_populates="game",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

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

    def __repr__(self) -> str:
        return (
            f"<Game id={self.id} title='{self.title}' category='{self.category}' "
            f"genre='{self.genre}' reward={self.reward_points} penalty={self.penalty_points}>"
        )
