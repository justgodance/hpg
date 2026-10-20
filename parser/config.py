from datetime import date
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "games.db"

# Default Export Files
DEFAULT_JSONL_PATH = OUTPUT_DIR / "steam_hltb_games.jsonl"
DEFAULT_JSON_PATH = OUTPUT_DIR / "steam_hltb_games.json"
DEFAULT_CSV_PATH = OUTPUT_DIR / "steam_hltb_games.csv"

# Cutoff Date: Games released up to today
TODAY = date.today()

# Steam Configurations
STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_HOVER_URL = "https://store.steampowered.com/apphoverpublic"
STEAM_IMAGE_BASE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"

# HowLongToBeat Configurations
HLTB_BASE_URL = "https://howlongtobeat.com"
HLTB_INIT_URL = f"{HLTB_BASE_URL}/api/search/site/init"
HLTB_SEARCH_URL = f"{HLTB_BASE_URL}/api/search/site"
HLTB_GAME_URL = f"{HLTB_BASE_URL}/game"

# Network & Politeness Settings
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 20
STEAM_SEARCH_PAGE_SIZE = 100 # Steam allows up to 100 games per search page
STEAM_SEARCH_DELAY = 2.0     # seconds between search pages to avoid rate limits
STEAM_DETAIL_DELAY = 0.8     # seconds between individual game detail calls
HLTB_DELAY = 0.8             # seconds between HLTB searches to avoid 429
MAX_RETRIES = 5
COOLDOWN_429_BASE = 30       # base cooldown seconds on HTTP 429
