from __future__ import annotations

import json
from pathlib import Path
import random
import sqlite3
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.game import Game, GameCategory
import concurrent.futures
import re
import requests


def get_games_db_connection() -> sqlite3.Connection:
    """Creates a connection to the parser's SQLite games database."""
    db_path = settings.PARSER_DB_PATH
    if not db_path.exists():
        # Fallback to creating parent dir if needed
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def normalize_steam_image_url(url: Optional[str], appid: Optional[int] = None) -> Optional[str]:
    """Sanitizes and normalizes Steam image URLs to ensure HTTP 200 availability."""
    if not url:
        return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else None
    
    # Valid image URLs (including Steam CDN hash paths for header.jpg and capsule) must be preserved as-is
    return url


def _parse_game_row(row: sqlite3.Row) -> dict[str, Any]:
    """Helper to convert sqlite3.Row to game dictionary with parsed tags and valid image URL."""
    d = dict(row)
    tags_raw = d.get("tags")
    if tags_raw and isinstance(tags_raw, str):
        try:
            d["tags"] = json.loads(tags_raw)
        except Exception:
            d["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif not tags_raw:
        d["tags"] = []

    appid = d.get("steam_appid")
    d["image_url"] = normalize_steam_image_url(d.get("image_url"), appid)

    if not d.get("steam_url") and appid:
        d["steam_url"] = f"https://store.steampowered.com/app/{appid}/"

    return d


_IMAGE_CACHE: dict[int, str] = {}


def resolve_single_image_url(appid: Optional[int], current_url: Optional[str] = None) -> Optional[str]:
    """Resolves working Steam cover URL using cache and instant normalization without blocking network calls."""
    if not appid:
        return current_url
    if appid in _IMAGE_CACHE:
        return _IMAGE_CACHE[appid]
    
    normalized = normalize_steam_image_url(current_url, appid)
    if normalized:
        _IMAGE_CACHE[appid] = normalized
        return normalized

    fallback = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
    _IMAGE_CACHE[appid] = fallback
    return fallback


def resolve_game_images(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Instant non-blocking normalization for all game covers in the reel."""
    for g in games:
        appid = g.get("steam_appid")
        g["image_url"] = normalize_steam_image_url(g.get("image_url"), appid)
        if appid and g["image_url"]:
            _IMAGE_CACHE[appid] = g["image_url"]
    return games


def query_games_from_parser_db(
    tag: Optional[str] = None,
    min_hours: Optional[float] = None,
    max_hours: Optional[float] = None,
    min_rating: Optional[float] = None,
    is_santa_top: bool = False,
    is_santa_coal: bool = False,
    exclude_titles: Optional[set[str]] = None,
    exclude_appids: Optional[set[int]] = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """
    Queries games from parser/data/games.db according to card filters:
    - tag: matches anywhere in game tags (e.g. Rogue, Metroidvania, Souls-like, Horror, RPG, etc.)
    - min_hours / max_hours: filters by HowLongToBeat main story hours
    - min_rating: filters by Steam review percentage
    - is_santa_top / is_santa_coal: special Mystery Box categories
    Features automatic fallback cascade if strict query returns fewer than requested games.
    """
    conn = get_games_db_connection()
    exclude_titles = exclude_titles or set()
    exclude_appids = exclude_appids or set()

    try:
        cur = conn.cursor()

        # Step 1: Strict query with all filters
        conditions: list[str] = []
        params: list[Any] = []

        if is_santa_coal:
            conditions.append("(review_percentage <= 50.0 OR tags LIKE ? OR tags LIKE ?)")
            params.extend(["%Trash%", "%Coal%"])
        elif is_santa_top:
            conditions.append("(review_percentage >= 90.0 OR review_percentage IS NULL)")
            if min_hours is not None:
                conditions.append("(hltb_main_story_hours >= ? OR hltb_main_story_hours IS NULL)")
                params.append(min_hours)
        else:
            if tag:
                # Case-insensitive substring search for tag
                conditions.append("LOWER(tags) LIKE LOWER(?)")
                params.append(f"%{tag}%")

            if min_hours is not None:
                conditions.append("hltb_main_story_hours >= ?")
                params.append(min_hours)

            if max_hours is not None:
                conditions.append("hltb_main_story_hours <= ?")
                params.append(max_hours)

            if min_rating is not None:
                conditions.append("review_percentage >= ?")
                params.append(min_rating)

        order_clause = "ORDER BY has_valid_image DESC, (CASE WHEN steam_appid < 3000000 THEN 0 ELSE 1 END), RANDOM()"
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM games{where_clause} {order_clause} LIMIT {limit * 2}"
        cur.execute(query, params)
        raw_rows = cur.fetchall()

        results = [_parse_game_row(r) for r in raw_rows]
        # Filter out excluded titles/appids
        filtered = [
            g for g in results
            if g["title"] not in exclude_titles and g.get("steam_appid") not in exclude_appids
        ]

        if len(filtered) >= limit:
            return resolve_game_images(filtered[:limit])

        # Step 2: Fallback cascade if strict search has fewer games
        # Relax HLTB hours restriction (keep tag)
        if (min_hours is not None or max_hours is not None) and tag:
            fallback_conds = ["LOWER(tags) LIKE LOWER(?)"]
            fb_params = [f"%{tag}%"]
            if min_rating:
                fallback_conds.append("review_percentage >= ?")
                fb_params.append(min_rating)

            fb_query = f"SELECT * FROM games WHERE {' AND '.join(fallback_conds)} {order_clause} LIMIT {limit * 2}"
            cur.execute(fb_query, fb_params)
            fb_rows = [_parse_game_row(r) for r in cur.fetchall()]
            for g in fb_rows:
                if g["title"] not in exclude_titles and g.get("steam_appid") not in exclude_appids:
                    if not any(item["title"] == g["title"] for item in filtered):
                        filtered.append(g)
                if len(filtered) >= limit:
                    return resolve_game_images(filtered[:limit])

        # Step 3: Global fallback from games.db (any games, prioritized by positive reviews and images)
        cur.execute(f"SELECT * FROM games {order_clause} LIMIT ?", (limit * 2,))
        global_rows = [_parse_game_row(r) for r in cur.fetchall()]
        for g in global_rows:
            if not any(item["title"] == g["title"] for item in filtered):
                filtered.append(g)
            if len(filtered) >= limit:
                break

        return resolve_game_images(filtered[:limit])
    finally:
        conn.close()


def calculate_game_points(hltb_hours: Optional[float], review_percentage: Optional[float]) -> tuple[int, int]:
    """Calculates reward and penalty points based on HLTB length and rating."""
    hours = hltb_hours or 10.0
    if hours <= 5.0:
        base_reward = 140
        base_penalty = 40
    elif hours <= 10.0:
        base_reward = 180
        base_penalty = 50
    elif hours <= 20.0:
        base_reward = 220
        base_penalty = 70
    elif hours <= 35.0:
        base_reward = 280
        base_penalty = 90
    else:
        base_reward = 350
        base_penalty = 110

    # Rating bonus for masterpieces (95%+)
    if review_percentage and review_percentage >= 95.0:
        base_reward += 30

    return base_reward, base_penalty


async def sync_game_to_hpg(
    session: AsyncSession,
    game_dict: dict[str, Any],
    category: str = "STEAM",
    preset_name: Optional[str] = None,
    reward_points: Optional[int] = None,
    penalty_points: Optional[int] = None,
) -> Game:
    """
    Synchronizes a game from parser/data/games.db into the main app database (hpg.db).
    Ensures that foreign keys on Quest work seamlessly and all rich metadata is present.
    """
    appid = game_dict.get("steam_appid")
    title = game_dict.get("title", "Безымянная игра")

    # Find existing game in hpg.db by steam_appid or title
    stmt = select(Game)
    if appid:
        stmt = stmt.where((Game.steam_appid == appid) | (Game.title == title))
    else:
        stmt = stmt.where(Game.title == title)

    existing_game = (await session.execute(stmt)).scalars().first()

    hours = game_dict.get("hltb_main_story_hours") or 0.0
    rating = game_dict.get("review_percentage")
    calc_reward, calc_penalty = calculate_game_points(hours, rating)

    final_reward = reward_points or calc_reward
    final_penalty = penalty_points or calc_penalty

    # Genre determination from tags
    tags = game_dict.get("tags") or []
    genre_display = "Экшен"
    if tags:
        # Find primary genre tag
        preferred_genres = [
            "Rogue-like", "Roguelike", "Roguelite", "Metroidvania", "Souls-like",
            "RPG", "Survival Horror", "Horror", "Strategy", "Puzzle", "Platformer",
            "Deckbuilding", "Card Battler", "Action-Adventure", "Indie"
        ]
        for pg in preferred_genres:
            if any(pg.lower() in t.lower() for t in tags):
                genre_display = pg
                break
        if genre_display == "Экшен" and len(tags) > 0:
            genre_display = tags[0]

    raw_img = game_dict.get("image_url")
    resolved_img = resolve_single_image_url(appid, raw_img) or raw_img

    if existing_game:
        # Update existing record with rich metadata
        if appid:
            existing_game.steam_appid = appid
        existing_game.image_url = resolved_img or existing_game.image_url
        existing_game.developer = game_dict.get("developer") or existing_game.developer
        existing_game.tags = tags
        existing_game.review_percentage = rating
        existing_game.review_count = game_dict.get("review_count")
        existing_game.review_desc = game_dict.get("review_desc")
        existing_game.release_date = game_dict.get("release_date")
        existing_game.steam_url = game_dict.get("steam_url")
        existing_game.hltb_game_id = game_dict.get("hltb_game_id")
        existing_game.hltb_game_name = game_dict.get("hltb_game_name")
        existing_game.hltb_url = game_dict.get("hltb_url")
        existing_game.hltb_status = game_dict.get("hltb_status", "found")
        if hours > 0:
            existing_game.hltb_hours = hours
        existing_game.reward_points = final_reward
        existing_game.penalty_points = final_penalty
        if category:
            existing_game.category = category
        if preset_name:
            existing_game.preset_name = preset_name
        await session.flush()
        return existing_game

    # Create new Game
    new_game = Game(
        steam_appid=appid,
        title=title,
        category=category,
        genre=genre_display,
        preset_name=preset_name,
        hltb_hours=hours,
        reward_points=final_reward,
        penalty_points=final_penalty,
        image_url=resolved_img,
        developer=game_dict.get("developer"),
        tags=tags,
        review_percentage=rating,
        review_count=game_dict.get("review_count"),
        review_desc=game_dict.get("review_desc"),
        release_date=game_dict.get("release_date"),
        steam_url=game_dict.get("steam_url"),
        hltb_game_id=game_dict.get("hltb_game_id"),
        hltb_game_name=game_dict.get("hltb_game_name"),
        hltb_url=game_dict.get("hltb_url"),
        hltb_status=game_dict.get("hltb_status", "found"),
    )
    session.add(new_game)
    await session.flush()
    return new_game
