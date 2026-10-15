from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.challenge import Challenge
    from app.models.game import Game
    from app.models.user import User


class QuestStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    challenge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("challenges.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    challenge_successful: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        default=None,
    )
    status: Mapped[QuestStatus] = mapped_column(
        Enum(QuestStatus, name="quest_status_enum", native_enum=False),
        default=QuestStatus.AVAILABLE,
        nullable=False,
        index=True,
    )

    # Card categories & Santa mystery box
    card_type: Mapped[str] = mapped_column(String(50), default="STEAM", nullable=False, index=True)
    is_santa_box: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Roulette & Underdog mechanics
    is_roulette: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    game_list_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    current_rolled_game_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reroll_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_underdog_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Inflation & Conveyor mechanics
    spawned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    locked_reward: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    game: Mapped[Optional["Game"]] = relationship(
        foreign_keys=[game_id],
        back_populates="quests",
        lazy="selectin",
    )
    current_rolled_game: Mapped[Optional["Game"]] = relationship(
        foreign_keys=[current_rolled_game_id],
        lazy="selectin",
    )
    user: Mapped[Optional["User"]] = relationship(
        back_populates="quests",
        lazy="selectin",
    )
    challenge: Mapped[Optional["Challenge"]] = relationship(
        back_populates="quests",
        lazy="selectin",
    )



    def __repr__(self) -> str:
        return (
            f"<Quest id={self.id} game_id={self.game_id} "
            f"user_id={self.user_id} challenge_id={self.challenge_id} status='{self.status.value}'>"
        )
