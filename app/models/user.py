from typing import TYPE_CHECKING
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.quest import Quest


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Balance mechanics from config
    free_drops: Mapped[int] = mapped_column(Integer, default=settings.DEFAULT_FREE_DROPS, nullable=False)
    rerolls_left: Mapped[int] = mapped_column(Integer, default=settings.DEFAULT_REROLLS_LEFT, nullable=False)
    quests_since_reroll: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


    quests: Mapped[list["Quest"]] = relationship(
        back_populates="user",
        lazy="selectin",
    )


    def __repr__(self) -> str:
        return f"<User id={self.id} username='{self.username}' score={self.total_score}>"
