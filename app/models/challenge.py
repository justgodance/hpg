from typing import TYPE_CHECKING
from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.quest import Quest


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, default=1.2, nullable=False)
    bonus_multiplier: Mapped[float] = mapped_column(Float, default=1.2, nullable=False)
    penalty_multiplier: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)

    quests: Mapped[list["Quest"]] = relationship(
        back_populates="challenge",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Challenge id={self.id} desc='{self.description[:30]}...' bonus={self.bonus_multiplier} penalty={self.penalty_multiplier}>"
