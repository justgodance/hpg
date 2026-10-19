import logging
import re
import time
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

import requests

try:
    from parser.config import (
        HLTB_INIT_URL,
        HLTB_SEARCH_URL,
        HLTB_GAME_URL,
        DEFAULT_USER_AGENT,
        DEFAULT_TIMEOUT,
        HLTB_DELAY,
        MAX_RETRIES
    )
except ImportError:
    from config import (
        HLTB_INIT_URL,
        HLTB_SEARCH_URL,
        HLTB_GAME_URL,
        DEFAULT_USER_AGENT,
        DEFAULT_TIMEOUT,
        HLTB_DELAY,
        MAX_RETRIES
    )

logger = logging.getLogger(__name__)

class HLTBClient:
    """Client for querying HowLongToBeat using their modern API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://howlongtobeat.com/",
            "Origin": "https://howlongtobeat.com"
        })
        self.token: Optional[str] = None
        self.token_timestamp: float = 0
        self.min_similarity: float = 0.55

    def _get_valid_token(self, force_refresh: bool = False) -> Optional[str]:
        """Fetch or return cached auth token from HLTB."""
        now = time.time()
        # Refresh if no token or token is older than 20 minutes (1200s)
        if not force_refresh and self.token and (now - self.token_timestamp < 1200):
            return self.token

        for attempt in range(MAX_RETRIES):
            try:
                init_url = f"{HLTB_INIT_URL}?t={int(now * 1000)}"
                resp = self.session.get(init_url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    self.token = data.get("token")
                    self.token_timestamp = now
                    logger.debug("HLTB security token obtained successfully")
                    return self.token
                elif resp.status_code == 429:
                    sleep_time = (attempt + 1) * 3
                    logger.warning(f"HLTB rate limit (429) on init. Sleeping {sleep_time}s...")
                    time.sleep(sleep_time)
            except Exception as e:
                logger.warning(f"HLTB token request failed (attempt {attempt + 1}): {e}")
                time.sleep(1)

        return None

    @staticmethod
    def clean_title(title: str) -> str:
        """Strip trademarks, edition tags, and noisy affixes."""
        if not title:
            return ""
        s = re.sub(r"[\u2122\u00ae\u00a9]", "", title)
        # Strip common game editions at the end
        s = re.sub(
            r"(?i)\s*[-:]?\s*(Deluxe|Collector's|Game of the Year|GOTY|Definitive|"
            r"Enhanced|Remastered|Special|Standard|Anniversary|Complete|Gold|Ultimate)\s+Edition.*$",
            "",
            s
        )
        # Strip trailing release tags like (2020), [VR], etc.
        s = re.sub(r"\s*[\(\[][^\)\]]*(?:20\d\d|19\d\d|VR|Demo|Soundtrack)[^\)\]]*[\)\]]", "", s)
        return s.strip()

    def search_game(self, title: str) -> Optional[Dict[str, Any]]:
        """
        Search for a game on HowLongToBeat.
        Returns dictionary with hltb_game_id, hltb_game_name, hltb_url, hltb_main_story_hours,
        or None if not found or no main story hours.
        """
        clean_name = self.clean_title(title)
        if not clean_name:
            return None

        for attempt in range(MAX_RETRIES):
            token = self._get_valid_token()
            if not token:
                logger.warning("Could not obtain HLTB token.")
                return None

            headers = {
                "Content-Type": "application/json",
                "x-auth-token": token
            }
            payload = {
                "searchType": "games",
                "searchTerms": clean_name.strip().split(" "),
                "searchPage": 1,
                "size": 10,
                "searchOptions": {
                    "games": {
                        "userId": 0, "platform": "", "sortCategory": "popular",
                        "rangeCategory": "main", "rangeTime": {"min": None, "max": None},
                        "gameplay": {"perspective": "", "flow": "", "genre": ""},
                        "year": "", "modifier": ""
                    },
                    "users": {"sortCategory": "postcount"},
                    "lists": {"sortCategory": "follows"},
                    "filter": "", "sort": 0, "randomizer": 0
                },
                "useCache": True
            }

            try:
                resp = self.session.post(
                    HLTB_SEARCH_URL,
                    headers=headers,
                    json=payload,
                    timeout=DEFAULT_TIMEOUT
                )

                if resp.status_code == 403:
                    logger.debug("HLTB token expired (403), refreshing...")
                    self._get_valid_token(force_refresh=True)
                    continue

                if resp.status_code == 429:
                    sleep_time = (attempt + 1) * 3
                    logger.warning(f"HLTB rate limit (429), pausing for {sleep_time}s...")
                    time.sleep(sleep_time)
                    continue

                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    result = self._find_best_match(clean_name, data)
                    time.sleep(HLTB_DELAY)
                    return result

            except Exception as e:
                logger.warning(f"Error querying HLTB for '{title}': {e}")
                time.sleep(1)

        return None

    def _find_best_match(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select the best matching candidate using SequenceMatcher."""
        if not candidates:
            return None

        best_cand = None
        best_ratio = 0.0
        query_lower = query.lower()

        for cand in candidates:
            c_name = cand.get("game_name", "")
            ratio = SequenceMatcher(None, query_lower, c_name.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_cand = cand

        if best_cand and best_ratio >= self.min_similarity:
            comp_main = best_cand.get("comp_main", 0)
            hours = round(comp_main / 3600.0, 1) if comp_main and comp_main > 0 else None
            game_id = best_cand.get("game_id")

            return {
                "hltb_game_id": game_id,
                "hltb_game_name": best_cand.get("game_name"),
                "hltb_url": f"{HLTB_GAME_URL}/{game_id}",
                "hltb_main_story_hours": hours,
                "similarity": round(best_ratio, 2)
            }

        return None
