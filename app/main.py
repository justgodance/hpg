from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.crud.challenge import seed_challenges_if_empty
from app.crud.game import seed_games_if_empty
from app.crud.quest import refill_board
from app.database import async_session_maker, init_db
# Ensure models are imported so that Base.metadata has them registered
import app.models  # noqa: F401
from app.routers import challenges, games, quests, users, web
from app.routers.web import get_or_seed_users


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on application startup
    await init_db()
    # Seed default data if tables are empty and refill board to 12
    async with async_session_maker() as session:
        await seed_games_if_empty(session)
        await seed_challenges_if_empty(session)
        await get_or_seed_users(session)
        await refill_board(session)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Web UI templates & HTMX endpoints
app.include_router(web.router)

# REST API endpoints
app.include_router(users.router)
app.include_router(games.router)
app.include_router(quests.router)
app.include_router(challenges.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}
