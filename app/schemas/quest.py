from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.config import settings
from app.models.quest import QuestStatus
from app.schemas.challenge import ChallengeRead


class QuestCreate(BaseModel):
    game_id: int | None = Field(default=None, description="ID игры (может быть None для ящиков Санты)")
    card_type: str = Field(default="STEAM", description="Тип карточки на доске (STEAM, GOTY, SERIES, PRESET, EMULATOR, SANTA)")
    is_santa_box: bool = Field(default=False, description="Является ли карточка нераспакованным подарком Санты")
    is_roulette: bool = Field(default=False, description="Контракт-рулетка со случайным выбором игры")
    game_list_ids: list[int] = Field(default_factory=list, description="Список ID игр для пула рулетки")
    is_underdog_only: bool = Field(default=False, description="Эксклюзивный контракт только для отстающих")


class QuestTakeRequest(BaseModel):
    user_id: int = Field(..., description="ID пользователя, берущего квест")
    challenge_id: int | None = Field(default=None, description="Опциональный ID выбранного модификатора")


class QuestGameRead(BaseModel):
    id: int
    title: str
    category: str = "STEAM"
    genre: str = "Экшен"
    preset_name: str | None = None
    hltb_hours: float
    reward_points: int
    penalty_points: int

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

    model_config = ConfigDict(from_attributes=True)


class QuestUserRead(BaseModel):
    id: int
    username: str
    total_score: int
    free_drops: int
    rerolls_left: int

    model_config = ConfigDict(from_attributes=True)


class QuestResponse(BaseModel):
    id: int
    game_id: int | None = None
    user_id: int | None = None
    challenge_id: int | None = None
    status: QuestStatus

    # Categories & Visual card types
    card_type: str = "STEAM"
    is_santa_box: bool = False

    # Balance & roulette mechanics
    is_roulette: bool = False
    game_list_ids: list[int] = Field(default_factory=list)
    current_rolled_game_id: int | None = None
    reroll_count: int = 0
    is_underdog_only: bool = False

    # Inflation & conveyor mechanics
    spawned_at: datetime
    locked_reward: int | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    game: QuestGameRead | None = None
    current_rolled_game: QuestGameRead | None = None
    user: QuestUserRead | None = None
    challenge: ChallengeRead | None = None

    @computed_field
    @property
    def is_revealed(self) -> bool:
        """Показывает, раскрыто ли точное название игры (только когда квест в работе или сдан)."""
        return self.status in (QuestStatus.IN_PROGRESS, QuestStatus.COMPLETED)

    @computed_field
    @property
    def display_title(self) -> str:
        """На бирже (AVAILABLE) игра скрыта: показывается название пресета, серии, эмулятора или Steam-контракта.
        В работе (IN_PROGRESS) раскрывается настоящее название игры!
        """
        active_game = self.current_rolled_game or self.game
        if self.is_revealed and active_game:
            return active_game.title

        if self.card_type == "SANTA" or self.is_santa_box:
            return "Таинственный Подарок Санты"

        if not active_game:
            return f"Контракт {self.card_type}"

        if self.card_type == "PRESET":
            return active_game.preset_name or "Тематический Пресет"
        elif self.card_type == "SERIES":
            return active_game.preset_name or "Контракт на серию игр"
        elif self.card_type == "EMULATOR":
            return active_game.preset_name or "Ретро-эмулятор"
        elif self.card_type == "GOTY":
            return active_game.preset_name or "Шедевр года (GOTY)"
        elif self.card_type == "STEAM":
            return f"Steam: {active_game.genre}"
        return f"Контракт {self.card_type}"

    @computed_field
    @property
    def display_condition(self) -> str:
        """Показывает жанр и условия контракта."""
        active_game = self.current_rolled_game or self.game
        if not active_game:
            return "Условия контракта формируются..."

        if self.card_type == "SANTA" or self.is_santa_box:
            return "50% шанс на Топ-хит (+10%) или Уголёк (+50%)"
        elif self.card_type == "PRESET":
            return f"Жанр: {active_game.genre} &bull; Пресет гильдии"
        elif self.card_type == "SERIES":
            return f"Жанр: {active_game.genre} &bull; Связанная франшиза"
        elif self.card_type == "EMULATOR":
            return f"Жанр: {active_game.genre} &bull; Ретро-платформа"
        elif self.card_type == "GOTY":
            return f"Жанр: {active_game.genre} &bull; Высокие ставки"
        elif self.card_type == "STEAM":
            return f"Жанр: {active_game.genre} &bull; Каталог Steam"
        return f"Жанр: {active_game.genre}"

    @computed_field
    @property
    def display_time(self) -> str:
        """На бирже отображается часовой диапазон (например, 10-20 ч). При взятии в работу раскрывается точное время."""
        active_game = self.current_rolled_game or self.game
        if not active_game:
            return "?? ч"

        if self.is_revealed:
            return f"{active_game.hltb_hours} ч"

        return active_game.time_range

    @computed_field
    @property
    def current_reward(self) -> int:
        """Динамический расчет награды:
        Если награда зафиксирована в locked_reward (квест взят/сдан), возвращает её.
        Иначе начисляет +20% к базовой награде за каждые полные 24 часа с момента spawned_at.
        Для нераскрытых коробок Санты возвращает 0 до распаковки.
        """
        if self.locked_reward is not None:
            return self.locked_reward

        active_game = self.current_rolled_game or self.game
        if not active_game:
            return 0

        base = active_game.reward_points

        now = datetime.now(timezone.utc)
        spawned = self.spawned_at if self.spawned_at.tzinfo else self.spawned_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = (now - spawned).total_seconds()
        interval_seconds = settings.INFLATION_INTERVAL_HOURS * 3600
        intervals = max(0, int(elapsed_seconds // interval_seconds))

        return round(base * (1.0 + settings.INFLATION_RATE_PER_INTERVAL * intervals))

    model_config = ConfigDict(from_attributes=True)


QuestRead = QuestResponse
