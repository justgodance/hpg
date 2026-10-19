import argparse
import logging
import signal
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional, Set

# Ensure parser directory is in sys.path
PARSER_DIR = Path(__file__).resolve().parent
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from tqdm import tqdm

try:
    from parser.config import TODAY
    from parser.db import Database
    from parser.exporter import DataExporter
    from parser.hltb import HLTBClient
    from parser.steam import SteamClient
except ImportError:
    from config import TODAY
    from db import Database
    from exporter import DataExporter
    from hltb import HLTBClient
    from steam import SteamClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("parser")

class ParserApplication:
    """Master controller for Steam & HLTB game parser."""

    def __init__(self):
        self.db = Database()
        self.steam = SteamClient()
        self.hltb = HLTBClient()
        self.exporter = DataExporter(self.db)
        self.stop_requested = False

        # Register signal handlers for clean exit on Ctrl+C
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)

    def _handle_interrupt(self, signum, frame):
        logger.warning("\nStop requested by user (Ctrl+C). Finishing current item and exiting...")
        self.stop_requested = True

    def process_game_details(
        self,
        game: dict,
        query_hltb: bool = True
    ) -> dict:
        """Enrich basic game dict with developer, tags, and HLTB stats."""
        appid = game["steam_appid"]
        title = game["title"]

        # 1. Fetch Steam Details (developer & tags)
        details = self.steam.fetch_game_details(appid)
        game["developer"] = details.get("developer")
        game["tags"] = details.get("tags") or []

        # 2. Fetch HLTB (if requested)
        if query_hltb:
            hltb_data = self.hltb.search_game(title)
            if hltb_data:
                game["hltb_game_id"] = hltb_data.get("hltb_game_id")
                game["hltb_game_name"] = hltb_data.get("hltb_game_name")
                game["hltb_url"] = hltb_data.get("hltb_url")
                game["hltb_main_story_hours"] = hltb_data.get("hltb_main_story_hours")
                game["hltb_status"] = "found"
            else:
                game["hltb_status"] = "not_found"
        else:
            game["hltb_status"] = "pending"

        return game

    def run_incremental(
        self,
        limit: Optional[int] = None,
        query_hltb: bool = True,
        max_existing_streak: int = 40
    ) -> None:
        """
        Incremental Parser:
        Parses games sorted from newest released (Released_DESC) down to older ones.
        Skips already parsed games and stops once a streak of already-existing games is found.
        Allows instant updates for games released since the last parse!
        """
        existing_appids = self.db.get_existing_appids()
        logger.info(f"Starting INCREMENTAL parse. Existing games in DB: {len(existing_appids):,}")

        start = 0
        batch_size = 50
        added_count = 0
        consecutive_existing = 0

        pbar = tqdm(desc="New Games Found", unit=" games")

        while not self.stop_requested:
            games_batch, total_search = self.steam.fetch_search_batch(
                start=start,
                count=batch_size,
                sort_by="Released_DESC"
            )

            if not games_batch:
                logger.info("No more games found from Steam search.")
                break

            for game in games_batch:
                if self.stop_requested:
                    break

                # Filter: Game must be released by today
                if not game.get("is_released"):
                    continue

                appid = game["steam_appid"]
                if appid in existing_appids:
                    consecutive_existing += 1
                    if consecutive_existing >= max_existing_streak:
                        logger.info(
                            f"Reached {consecutive_existing} previously parsed games in a row. "
                            f"All new releases up to date!"
                        )
                        self.stop_requested = True
                        break
                    continue

                # Reset streak when a new game is discovered
                consecutive_existing = 0

                # Enrich with developer, tags, and HLTB
                enriched = self.process_game_details(game, query_hltb=query_hltb)
                self.db.upsert_game(enriched)
                existing_appids.add(appid)

                added_count += 1
                pbar.update(1)
                pbar.set_postfix_str(f"Latest: {enriched['title'][:25]}")

                if limit and added_count >= limit:
                    logger.info(f"Target limit of {limit} new games reached.")
                    self.stop_requested = True
                    break

            start += batch_size

        pbar.close()
        logger.info(f"Incremental parse completed. Added {added_count:,} new games.")
        self.export_data()

    def run_full(
        self,
        limit: Optional[int] = None,
        query_hltb: bool = True,
        sort_by: str = "Released_DESC"
    ) -> None:
        """
        Full Parser:
        Walks the Steam catalog up to the specified limit or entire catalog.
        """
        existing_appids = self.db.get_existing_appids()
        logger.info(f"Starting FULL parse (sort: {sort_by}). Existing games: {len(existing_appids):,}")

        start = 0
        batch_size = 50
        processed_count = 0

        pbar = tqdm(desc="Parsing Games", unit=" games")

        while not self.stop_requested:
            games_batch, total_search = self.steam.fetch_search_batch(
                start=start,
                count=batch_size,
                sort_by=sort_by
            )

            if not games_batch:
                break

            for game in games_batch:
                if self.stop_requested:
                    break

                # Filter: Must be released by today
                if not game.get("is_released"):
                    continue

                appid = game["steam_appid"]
                if appid in existing_appids:
                    continue

                enriched = self.process_game_details(game, query_hltb=query_hltb)
                self.db.upsert_game(enriched)
                existing_appids.add(appid)

                processed_count += 1
                pbar.update(1)
                pbar.set_postfix_str(f"Added: {enriched['title'][:25]}")

                if limit and processed_count >= limit:
                    self.stop_requested = True
                    break

            start += batch_size

        pbar.close()
        logger.info(f"Catalog walk finished. Processed {processed_count:,} games.")
        self.export_data()

    def run_hltb_backfill(self, limit: Optional[int] = None) -> None:
        """Query HLTB for games currently marked as pending in DB."""
        pending = self.db.get_pending_hltb_games(limit=limit)
        if not pending:
            logger.info("No games pending HLTB data.")
            return

        logger.info(f"Backfilling HLTB data for {len(pending):,} games...")
        pbar = tqdm(pending, desc="HLTB Matching", unit=" games")

        for item in pbar:
            if self.stop_requested:
                break

            appid = item["steam_appid"]
            title = item["title"]

            hltb_data = self.hltb.search_game(title)
            self.db.update_hltb_info(appid, hltb_data)

            status = f"{hltb_data['hltb_main_story_hours']}h" if hltb_data and hltb_data.get('hltb_main_story_hours') else "N/A"
            pbar.set_postfix_str(f"{title[:20]} -> {status}")

        pbar.close()
        logger.info("HLTB backfill completed.")
        self.export_data()

    def print_stats(self) -> None:
        """Print database statistics."""
        stats = self.db.get_stats()
        print("\n" + "="*50)
        print("          STEAM & HLTB PARSER STATS          ")
        print("="*50)
        print(f" Total games in DB:         {stats['total_games']:,}")
        print(f" Released up to today:      {stats['released_games']:,}")
        print(f" Games with review scores:  {stats['with_reviews']:,}")
        print(f" HLTB matched:              {stats['hltb_found']:,}")
        print(f" HLTB not found / no story: {stats['hltb_not_found']:,}")
        print(f" HLTB pending:              {stats['hltb_pending']:,}")
        print(f" Average Main Story Hours:  {stats['avg_hltb_hours'] or 0} hrs")
        print("="*50 + "\n")

    def export_data(self, output_format: str = "all") -> None:
        """Export database to files."""
        logger.info(f"Exporting database (format: {output_format})...")
        if output_format in ("jsonl", "all"):
            self.exporter.export_jsonl()
        if output_format in ("json", "all"):
            self.exporter.export_json()
        if output_format in ("csv", "all"):
            self.exporter.export_csv()
        logger.info("Export completed successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="Steam & HowLongToBeat Comprehensive Game Parser"
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full", "hltb", "export", "stats"],
        default="incremental",
        help=(
            "Operating mode: "
            "'incremental' (default) parses only newly released games; "
            "'full' parses games across Steam; "
            "'hltb' fills missing HLTB data; "
            "'export' generates JSONL/JSON/CSV; "
            "'stats' displays database counts."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of games to parse in this run."
    )
    parser.add_argument(
        "--skip-hltb",
        action="store_true",
        help="Skip HowLongToBeat lookup during Steam scraping (faster initial download)."
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "json", "csv", "all"],
        default="all",
        help="Output export format (default: all)."
    )
    parser.add_argument(
        "--sort",
        default="Released_DESC",
        help="Steam catalog sort order (e.g. Released_DESC, Reviews_DESC, etc.)."
    )

    args = parser.parse_args()
    app = ParserApplication()

    if args.mode == "incremental":
        app.run_incremental(limit=args.limit, query_hltb=not args.skip_hltb)
    elif args.mode == "full":
        app.run_full(limit=args.limit, query_hltb=not args.skip_hltb, sort_by=args.sort)
    elif args.mode == "hltb":
        app.run_hltb_backfill(limit=args.limit)
    elif args.mode == "export":
        app.export_data(output_format=args.format)
    elif args.mode == "stats":
        app.print_stats()


if __name__ == "__main__":
    main()
