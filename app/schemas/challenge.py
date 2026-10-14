from pydantic import BaseModel, ConfigDict, Field


class ChallengeBase(BaseModel):
    description: str = Field(..., max_length=300, description="Описание условия испытания")
    multiplier: float = Field(default=1.2, ge=1.0, le=5.0, description="Множитель награды квеста")


class ChallengeCreate(ChallengeBase):
    pass


class ChallengeRead(ChallengeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
