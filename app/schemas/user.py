from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="Имя игрока")


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    total_score: int
    free_drops: int
    rerolls_left: int
    quests_since_reroll: int
    is_underdog: bool = False

    model_config = ConfigDict(from_attributes=True)

