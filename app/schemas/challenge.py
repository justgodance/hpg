from pydantic import BaseModel, ConfigDict, Field


class ChallengeBase(BaseModel):
    description: str = Field(..., max_length=300, description="Описание условия испытания")
    multiplier: float = Field(default=1.2, ge=1.0, le=5.0, description="Множитель награды квеста")
    bonus_multiplier: float = Field(default=1.2, ge=1.0, le=5.0, description="Бонусный множитель за успех (+X%)")
    penalty_multiplier: float = Field(default=0.85, ge=0.0, le=1.0, description="Штрафной множитель за провал (-X%)")


class ChallengeCreate(ChallengeBase):
    pass


class ChallengeRead(ChallengeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
