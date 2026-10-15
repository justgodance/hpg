from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # System settings
    PROJECT_NAME: str = "Guild Quest Board"
    DEBUG: bool = True
    DATABASE_URL: str = "sqlite+aiosqlite:///./hpg.db"

    # Game balance & rules configuration
    MAX_BOARD_SIZE: int = Field(default=12, description="Целевое количество доступных квестов на доске")
    DEFAULT_FREE_DROPS: int = Field(default=2, description="Начальное количество бесплатных сбросов квестов без штрафа")
    DEFAULT_REROLLS_LEFT: int = Field(default=1, description="Начальное количество попыток реролла рулетки")
    QUESTS_PER_REROLL_RECHARGE: int = Field(default=3, description="Количество сданных квестов для перезарядки 1 реролла")

    # Dynamic inflation
    INFLATION_INTERVAL_HOURS: int = Field(default=24, description="Интервал инфляции в часах (каждые N часов)")
    INFLATION_RATE_PER_INTERVAL: float = Field(default=0.2, description="Множитель инфляции за интервал (+20%)")

    # Modifiers & Penalties
    REROLL_PENALTY_RATE: float = Field(default=0.1, description="Штраф к награде за каждый реролл (-10%)")
    UNDERDOG_SCORE_GAP: int = Field(default=2000, description="Разница очков с лидером для получения статуса Андердога")
    UNDERDOG_BONUS_MULTIPLIER: float = Field(default=1.2, description="Бонус к награде за квест для Андердога (+20%)")
    CHALLENGE_ROLL_COUNT: int = Field(default=3, description="Количество предлагаемых модификаторов при ролле")

    # Roulette / Wheel of Fortune animation settings
    ROULETTE_OPTIONS_COUNT: int = Field(default=15, description="Сколько всего элементов мелькает в анимации рулетки")
    ROULETTE_DURATION_SEC: int = Field(default=4, description="Длительность вращения рулетки в секундах")

    # External data file paths
    GAMES_DATA_PATH: Path = Field(
        default=BASE_DIR / "data" / "games.json",
        description="Путь к JSON-файлу с каталогом игр",
    )
    CHALLENGES_DATA_PATH: Path = Field(
        default=BASE_DIR / "data" / "challenges.json",
        description="Путь к JSON-файлу с пулом челленджей",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
