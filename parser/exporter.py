import csv
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    from parser.config import (
        DEFAULT_JSONL_PATH,
        DEFAULT_JSON_PATH,
        DEFAULT_CSV_PATH,
        OUTPUT_DIR
    )
    from parser.db import Database
except ImportError:
    from config import (
        DEFAULT_JSONL_PATH,
        DEFAULT_JSON_PATH,
        DEFAULT_CSV_PATH,
        OUTPUT_DIR
    )
    from db import Database

logger = logging.getLogger(__name__)

class DataExporter:
    """Exports parsed game datasets into JSONL, JSON, and CSV formats."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def _format_record(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize row dictionary into final export structure."""
        tags = row.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        return {
            "title": row.get("title"),
            "image_url": row.get("image_url"),
            "review_percentage": row.get("review_percentage"),
            "release_date": row.get("release_date") or row.get("release_date_raw"),
            "developer": row.get("developer"),
            "tags": tags,
            "steam_url": row.get("steam_url"),
            "hltb_url": row.get("hltb_url"),
            "hltb_main_story_hours": row.get("hltb_main_story_hours"),
            # Additional helpful metadata
            "steam_appid": row.get("steam_appid"),
            "review_count": row.get("review_count"),
            "review_desc": row.get("review_desc")
        }

    def export_jsonl(self, output_path: Optional[Path] = None, only_released: bool = True) -> int:
        """Export dataset to JSON Lines (.jsonl). Optimal for large datasets."""
        path = Path(output_path or DEFAULT_JSONL_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with open(path, "w", encoding="utf-8") as f:
            for row in self.db.stream_all_games(only_released=only_released):
                record = self._format_record(row)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        logger.info(f"Exported {count:,} games to JSONL: {path}")
        return count

    def export_json(self, output_path: Optional[Path] = None, only_released: bool = True, indent: int = 2) -> int:
        """Export dataset to formatted JSON (.json) array."""
        path = Path(output_path or DEFAULT_JSON_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        records = [
            self._format_record(row)
            for row in self.db.stream_all_games(only_released=only_released)
        ]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=indent)

        logger.info(f"Exported {len(records):,} games to JSON: {path}")
        return len(records)

    def export_csv(self, output_path: Optional[Path] = None, only_released: bool = True) -> int:
        """Export dataset to CSV (.csv) file."""
        path = Path(output_path or DEFAULT_CSV_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        fields = [
            "steam_appid", "title", "image_url", "review_percentage", "review_count",
            "review_desc", "release_date", "developer", "tags",
            "steam_url", "hltb_url", "hltb_main_story_hours"
        ]

        count = 0
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()

            for row in self.db.stream_all_games(only_released=only_released):
                rec = self._format_record(row)
                csv_row = {
                    "steam_appid": rec.get("steam_appid"),
                    "title": rec.get("title"),
                    "image_url": rec.get("image_url"),
                    "review_percentage": rec.get("review_percentage"),
                    "review_count": rec.get("review_count"),
                    "review_desc": rec.get("review_desc"),
                    "release_date": rec.get("release_date"),
                    "developer": rec.get("developer"),
                    "tags": ", ".join(rec.get("tags") or []),
                    "steam_url": rec.get("steam_url"),
                    "hltb_url": rec.get("hltb_url"),
                    "hltb_main_story_hours": rec.get("hltb_main_story_hours")
                }
                writer.writerow(csv_row)
                count += 1

        logger.info(f"Exported {count:,} games to CSV: {path}")
        return count

    def export_all(self, only_released: bool = True) -> Dict[str, Any]:
        """Export to all standard formats."""
        count_jsonl = self.export_jsonl(only_released=only_released)
        self.export_json(only_released=only_released)
        self.export_csv(only_released=only_released)
        return {
            "total_exported": count_jsonl,
            "jsonl_path": str(DEFAULT_JSONL_PATH),
            "json_path": str(DEFAULT_JSON_PATH),
            "csv_path": str(DEFAULT_CSV_PATH)
        }
