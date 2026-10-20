import json
import sqlite3
from typing import Dict, Any, List, Optional, Set, Generator

try:
    from parser.config import DB_PATH
except ImportError:
    from config import DB_PATH

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DB_PATH)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency and performance
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_db(self) -> None:
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    steam_appid INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    image_url TEXT,
                    has_valid_image INTEGER DEFAULT 1,
                    review_percentage REAL,
                    review_count INTEGER,
                    review_desc TEXT,
                    release_date_raw TEXT,
                    release_date TEXT,
                    developer TEXT,
                    tags TEXT,
                    steam_url TEXT,
                    hltb_game_id INTEGER,
                    hltb_game_name TEXT,
                    hltb_url TEXT,
                    hltb_main_story_hours REAL,
                    hltb_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_games_release_date ON games (release_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_games_hltb_status ON games (hltb_status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_games_title ON games (title);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_games_valid_image ON games (has_valid_image);")
            conn.commit()

    def get_existing_appids(self) -> Set[int]:
        """Returns the set of all steam_appids already present in the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT steam_appid FROM games")
            return {row[0] for row in cursor.fetchall()}

    def get_game_by_appid(self, appid: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM games WHERE steam_appid = ?", (appid,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                if d.get("tags") and isinstance(d["tags"], str):
                    try:
                        d["tags"] = json.loads(d["tags"])
                    except Exception:
                        d["tags"] = []
                return d
            return None

    def upsert_game(self, game: Dict[str, Any]) -> None:
        """Upsert a single game into the database."""
        self.upsert_games_batch([game])

    def upsert_games_batch(self, games: List[Dict[str, Any]]) -> None:
        """Upsert a batch of games in a single transaction."""
        if not games:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for g in games:
                tags_json = g.get("tags")
                if isinstance(tags_json, (list, set, tuple)):
                    tags_json = json.dumps(list(tags_json), ensure_ascii=False)
                elif tags_json is None:
                    tags_json = json.dumps([], ensure_ascii=False)

                cursor.execute("""
                    INSERT INTO games (
                        steam_appid, title, image_url, has_valid_image, review_percentage,
                        review_count, review_desc, release_date_raw, release_date,
                        developer, tags, steam_url, hltb_game_id, hltb_game_name,
                        hltb_url, hltb_main_story_hours, hltb_status, updated_at
                    ) VALUES (
                        :steam_appid, :title, :image_url, :has_valid_image, :review_percentage,
                        :review_count, :review_desc, :release_date_raw, :release_date,
                        :developer, :tags, :steam_url, :hltb_game_id, :hltb_game_name,
                        :hltb_url, :hltb_main_story_hours, :hltb_status, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(steam_appid) DO UPDATE SET
                        title = excluded.title,
                        image_url = CASE 
                            WHEN excluded.image_url IS NOT NULL AND excluded.image_url != '' THEN excluded.image_url 
                            ELSE games.image_url 
                        END,
                        has_valid_image = COALESCE(excluded.has_valid_image, games.has_valid_image),
                        review_percentage = COALESCE(excluded.review_percentage, games.review_percentage),
                        review_count = COALESCE(excluded.review_count, games.review_count),
                        review_desc = COALESCE(excluded.review_desc, games.review_desc),
                        release_date_raw = COALESCE(excluded.release_date_raw, games.release_date_raw),
                        release_date = COALESCE(excluded.release_date, games.release_date),
                        developer = COALESCE(excluded.developer, games.developer),
                        tags = CASE 
                            WHEN excluded.tags IS NOT NULL AND excluded.tags != '[]' THEN excluded.tags 
                            ELSE games.tags 
                        END,
                        steam_url = COALESCE(excluded.steam_url, games.steam_url),
                        hltb_game_id = COALESCE(excluded.hltb_game_id, games.hltb_game_id),
                        hltb_game_name = COALESCE(excluded.hltb_game_name, games.hltb_game_name),
                        hltb_url = COALESCE(excluded.hltb_url, games.hltb_url),
                        hltb_main_story_hours = COALESCE(excluded.hltb_main_story_hours, games.hltb_main_story_hours),
                        hltb_status = CASE 
                            WHEN excluded.hltb_status != 'pending' THEN excluded.hltb_status 
                            ELSE games.hltb_status 
                        END,
                        updated_at = CURRENT_TIMESTAMP
                """, {
                    "steam_appid": g.get("steam_appid"),
                    "title": g.get("title"),
                    "image_url": g.get("image_url"),
                    "has_valid_image": g.get("has_valid_image", 1),
                    "review_percentage": g.get("review_percentage"),
                    "review_count": g.get("review_count"),
                    "review_desc": g.get("review_desc"),
                    "release_date_raw": g.get("release_date_raw"),
                    "release_date": g.get("release_date"),
                    "developer": g.get("developer"),
                    "tags": tags_json,
                    "steam_url": g.get("steam_url"),
                    "hltb_game_id": g.get("hltb_game_id"),
                    "hltb_game_name": g.get("hltb_game_name"),
                    "hltb_url": g.get("hltb_url"),
                    "hltb_main_story_hours": g.get("hltb_main_story_hours"),
                    "hltb_status": g.get("hltb_status", "pending")
                })
            conn.commit()

    def get_pending_hltb_games(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch games that still need HLTB data."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT steam_appid, title FROM games WHERE hltb_status = 'pending'"
            if limit:
                query += f" LIMIT {int(limit)}"
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def update_hltb_info(self, steam_appid: int, hltb_info: Optional[Dict[str, Any]]) -> None:
        """Update HLTB data for a single game."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if hltb_info:
                cursor.execute("""
                    UPDATE games SET
                        hltb_game_id = :hltb_game_id,
                        hltb_game_name = :hltb_game_name,
                        hltb_url = :hltb_url,
                        hltb_main_story_hours = :hltb_main_story_hours,
                        hltb_status = 'found',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE steam_appid = :steam_appid
                """, {
                    "steam_appid": steam_appid,
                    "hltb_game_id": hltb_info.get("hltb_game_id"),
                    "hltb_game_name": hltb_info.get("hltb_game_name"),
                    "hltb_url": hltb_info.get("hltb_url"),
                    "hltb_main_story_hours": hltb_info.get("hltb_main_story_hours")
                })
            else:
                cursor.execute("""
                    UPDATE games SET
                        hltb_status = 'not_found',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE steam_appid = ?
                """, (steam_appid,))
            conn.commit()

    def stream_all_games(self, only_released: bool = True) -> Generator[Dict[str, Any], None, None]:
        """Generator that streams games one by one for export."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM games"
            if only_released:
                query += " WHERE release_date IS NOT NULL AND release_date <= date('now')"
            query += " ORDER BY release_date DESC, steam_appid DESC"
            cursor.execute(query)
            for row in cursor:
                d = dict(row)
                if d.get("tags") and isinstance(d["tags"], str):
                    try:
                        d["tags"] = json.loads(d["tags"])
                    except Exception:
                        d["tags"] = []
                yield d

    def get_stats(self) -> Dict[str, Any]:
        """Return dataset statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM games")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM games WHERE release_date IS NOT NULL AND release_date <= date('now')")
            released = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM games WHERE hltb_status = 'found'")
            hltb_found = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM games WHERE hltb_status = 'not_found'")
            hltb_not_found = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM games WHERE hltb_status = 'pending'")
            hltb_pending = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM games WHERE review_percentage IS NOT NULL")
            with_reviews = cursor.fetchone()[0]

            cursor.execute("SELECT AVG(hltb_main_story_hours) FROM games WHERE hltb_main_story_hours IS NOT NULL")
            avg_hours = cursor.fetchone()[0]

            return {
                "total_games": total,
                "released_games": released,
                "with_reviews": with_reviews,
                "hltb_found": hltb_found,
                "hltb_not_found": hltb_not_found,
                "hltb_pending": hltb_pending,
                "avg_hltb_hours": round(avg_hours, 1) if avg_hours else None
            }
