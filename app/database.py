from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models.base import Base

engine_kwargs: dict[str, Any] = {
    "echo": settings.DEBUG,
    "future": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30.0,
    }
else:
    engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session per request."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Creates database tables defined in metadata (useful for quick start & dev)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate SQLite database schema if new columns are added
        if settings.DATABASE_URL.startswith("sqlite"):
            def migrate_sqlite(connection: Any) -> None:
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                connection.exec_driver_sql("PRAGMA busy_timeout=30000")
                # 1. Challenges table
                res_chal = connection.exec_driver_sql("PRAGMA table_info(challenges)").fetchall()
                chal_cols = [r[1] for r in res_chal]
                if "bonus_multiplier" not in chal_cols:
                    connection.exec_driver_sql("ALTER TABLE challenges ADD COLUMN bonus_multiplier FLOAT DEFAULT 1.2 NOT NULL")
                if "penalty_multiplier" not in chal_cols:
                    connection.exec_driver_sql("ALTER TABLE challenges ADD COLUMN penalty_multiplier FLOAT DEFAULT 0.85 NOT NULL")
                
                # 2. Quests table
                res_quest = connection.exec_driver_sql("PRAGMA table_info(quests)").fetchall()
                quest_cols = [r[1] for r in res_quest]
                if "challenge_successful" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN challenge_successful BOOLEAN DEFAULT NULL")
                if "card_title" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN card_title VARCHAR(200) DEFAULT NULL")
                if "tag_filter" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN tag_filter VARCHAR(100) DEFAULT NULL")
                if "min_hltb_hours" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN min_hltb_hours FLOAT DEFAULT NULL")
                if "max_hltb_hours" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN max_hltb_hours FLOAT DEFAULT NULL")
                if "min_rating" not in quest_cols:
                    connection.exec_driver_sql("ALTER TABLE quests ADD COLUMN min_rating FLOAT DEFAULT NULL")

                # 3. Users table
                res_user = connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
                user_cols = [r[1] for r in res_user]
                if "avatar_url" not in user_cols:
                    connection.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(255) DEFAULT NULL")
                if "pin_code" not in user_cols:
                    connection.exec_driver_sql("ALTER TABLE users ADD COLUMN pin_code VARCHAR(10) DEFAULT NULL")

                # 4. Games table (Rich metadata from Steam/HLTB Parser)
                res_games = connection.exec_driver_sql("PRAGMA table_info(games)").fetchall()
                game_cols = [r[1] for r in res_games]
                new_game_fields = [
                    ("steam_appid", "INTEGER DEFAULT NULL"),
                    ("image_url", "VARCHAR(500) DEFAULT NULL"),
                    ("developer", "VARCHAR(200) DEFAULT NULL"),
                    ("tags", "JSON DEFAULT NULL"),
                    ("review_percentage", "FLOAT DEFAULT NULL"),
                    ("review_count", "INTEGER DEFAULT NULL"),
                    ("review_desc", "VARCHAR(100) DEFAULT NULL"),
                    ("release_date", "VARCHAR(50) DEFAULT NULL"),
                    ("steam_url", "VARCHAR(500) DEFAULT NULL"),
                    ("hltb_game_id", "INTEGER DEFAULT NULL"),
                    ("hltb_game_name", "VARCHAR(200) DEFAULT NULL"),
                    ("hltb_url", "VARCHAR(500) DEFAULT NULL"),
                    ("hltb_status", "VARCHAR(50) DEFAULT 'found'"),
                ]
                for col_name, col_def in new_game_fields:
                    if col_name not in game_cols:
                        connection.exec_driver_sql(f"ALTER TABLE games ADD COLUMN {col_name} {col_def}")

            await conn.run_sync(migrate_sqlite)

