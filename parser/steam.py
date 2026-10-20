import logging
import re
import time
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Tuple, Set

import requests
from bs4 import BeautifulSoup

try:
    from parser.config import (
        STEAM_SEARCH_URL,
        STEAM_APP_DETAILS_URL,
        STEAM_HOVER_URL,
        STEAM_IMAGE_BASE,
        DEFAULT_USER_AGENT,
        DEFAULT_TIMEOUT,
        STEAM_SEARCH_PAGE_SIZE,
        STEAM_SEARCH_DELAY,
        STEAM_DETAIL_DELAY,
        MAX_RETRIES,
        COOLDOWN_429_BASE,
        TODAY
    )
except ImportError:
    from config import (
        STEAM_SEARCH_URL,
        STEAM_APP_DETAILS_URL,
        STEAM_HOVER_URL,
        STEAM_IMAGE_BASE,
        DEFAULT_USER_AGENT,
        DEFAULT_TIMEOUT,
        STEAM_SEARCH_PAGE_SIZE,
        STEAM_SEARCH_DELAY,
        STEAM_DETAIL_DELAY,
        MAX_RETRIES,
        COOLDOWN_429_BASE,
        TODAY
    )

logger = logging.getLogger(__name__)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

def parse_steam_date(date_str: Optional[str]) -> Optional[date]:
    """Parse various Steam release date formats into a date object."""
    if not date_str:
        return None
    s = date_str.strip().lower()
    if any(unreleased in s for unreleased in ("soon", "tba", "tbd", "announced", "coming")):
        return None

    # Format: "24 Feb, 2017" or "24 Feb 2017"
    m = re.search(r"(\d{1,2})\s+([a-z]{3})[a-z]*,?\s+(\d{4})", s)
    if m:
        try:
            day = int(m.group(1))
            month = MONTHS.get(m.group(2)[:3], 1)
            year = int(m.group(3))
            return date(year, month, day)
        except ValueError:
            pass

    # Format: "Feb 24, 2017"
    m = re.search(r"([a-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        try:
            month = MONTHS.get(m.group(1)[:3], 1)
            day = int(m.group(2))
            year = int(m.group(3))
            return date(year, month, day)
        except ValueError:
            pass

    # Format: "Feb 2017"
    m = re.search(r"([a-z]{3})[a-z]*\s+(\d{4})", s)
    if m:
        month = MONTHS.get(m.group(1)[:3], 1)
        year = int(m.group(2))
        return date(year, month, 1)

    # Format: "2017"
    m = re.search(r"\b(\d{4})\b", s)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1)

    return None

def is_released_by_today(d: Optional[date], cutoff: Optional[date] = None) -> bool:
    """Check if the date is released up to today."""
    if d is None:
        return False
    target = cutoff or TODAY
    return d <= target

def parse_reviews_tooltip(tooltip_html: Optional[str]) -> Tuple[Optional[float], Optional[int], Optional[str]]:
    """
    Extract (percentage, count, description) from Steam search review tooltip.
    Example: 'Very Positive<br>93% of the 1,447 user reviews for this game are positive.'
    """
    if not tooltip_html:
        return None, None, None

    # Parse description (before <br>)
    desc_match = re.search(r"^([^<]+)", tooltip_html)
    desc = desc_match.group(1).strip() if desc_match else None

    # Parse percentage
    pct_match = re.search(r"(\d+)%", tooltip_html)
    percentage = float(pct_match.group(1)) if pct_match else None

    # Parse count
    count_match = re.search(r"of\s+the\s+([\d,]+)\s+user\s+reviews", tooltip_html)
    count = int(count_match.group(1).replace(",", "")) if count_match else None

    return percentage, count, desc

class SteamClient:
    """Steam client for searching catalog and querying store details."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://store.steampowered.com/search/?category1=998",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin"
        })

    def fetch_search_batch(
        self,
        start: int = 0,
        count: int = STEAM_SEARCH_PAGE_SIZE,
        sort_by: str = "Released_DESC"
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Fetch a page of games from Steam Search.
        Returns (list_of_parsed_games, total_count).
        """
        params = {
            "query": "",
            "start": start,
            "count": count,
            "category1": "998",  # Games only (filters out software, videos, DLCs)
            "sort_by": sort_by
        }

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(STEAM_SEARCH_URL, params=params, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = int(retry_after) + 2
                    else:
                        sleep_time = COOLDOWN_429_BASE * (attempt + 1)
                    logger.warning(
                        f"Steam rate limit (429). Server requested cooldown. "
                        f"Pausing {sleep_time}s (attempt {attempt + 1}/{MAX_RETRIES})..."
                    )
                    time.sleep(sleep_time)
                    continue

                if resp.status_code != 200:
                    logger.warning(f"Steam search error {resp.status_code} at start={start}")
                    time.sleep(1)
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Parse total count
                total_count = 0
                count_match = re.search(r"([\d,]+)\s+results\s+match", resp.text)
                if count_match:
                    total_count = int(count_match.group(1).replace(",", ""))

                rows = soup.select("a.search_result_row")
                games = []

                for row in rows:
                    appid_str = row.get("data-ds-appid")
                    if not appid_str or not appid_str.isdigit():
                        continue
                    appid = int(appid_str)

                    title_el = row.select_one(".title")
                    title = title_el.text.strip() if title_el else ""

                    date_el = row.select_one(".search_released")
                    release_date_raw = date_el.text.strip() if date_el else ""
                    parsed_date = parse_steam_date(release_date_raw)

                    # Image URL: preserve Steam hash directory if present in search_capsule
                    img_el = row.select_one(".search_capsule img")
                    capsule_img = img_el.get("src") if img_el else None
                    if capsule_img:
                        # Steam hash CDN is specific to capsule image filename; keeping it guarantees HTTP 200
                        image_url = capsule_img
                    else:
                        image_url = f"{STEAM_IMAGE_BASE}/{appid}/header.jpg"

                    # Review Summary
                    review_summary = row.select_one(".search_review_summary")
                    tooltip = review_summary.get("data-tooltip-html") if review_summary else None
                    pct, review_cnt, desc = parse_reviews_tooltip(tooltip)

                    games.append({
                        "steam_appid": appid,
                        "title": title,
                        "release_date_raw": release_date_raw,
                        "release_date": parsed_date.isoformat() if parsed_date else None,
                        "parsed_date_obj": parsed_date,
                        "is_released": is_released_by_today(parsed_date),
                        "image_url": image_url,
                        "review_percentage": pct,
                        "review_count": review_cnt,
                        "review_desc": desc,
                        "steam_url": f"https://store.steampowered.com/app/{appid}/"
                    })

                time.sleep(STEAM_SEARCH_DELAY)
                return games, total_count

            except Exception as e:
                logger.warning(f"Error fetching Steam search batch start={start} (attempt {attempt + 1}): {e}")
                time.sleep(2)

        return [], 0

    def fetch_game_details(self, appid: int) -> Dict[str, Any]:
        """
        Fetch developer and user tags for a specific game.
        Combines lightweight apphoverpublic (for user tags) and appdetails (for developers).
        """
        developer = None
        tags = []

        # 1. Fetch tags from apphoverpublic (very fast and comprehensive user tags)
        try:
            hover_url = f"{STEAM_HOVER_URL}/{appid}?l=english"
            resp = self.session.get(hover_url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                tag_elements = soup.select(".app_tag")
                tags = [t.text.strip() for t in tag_elements if t.text.strip()]
        except Exception as e:
            logger.debug(f"Hover tags failed for appid {appid}: {e}")

        # 2. Fetch developer from appdetails
        try:
            params = {
                "appids": str(appid),
                "filters": "developers,genres,release_date",
                "l": "english"
            }
            resp = self.session.get(STEAM_APP_DETAILS_URL, params=params, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json().get(str(appid), {})
                if data.get("success"):
                    app_data = data.get("data", {})
                    devs = app_data.get("developers", [])
                    if devs:
                        developer = ", ".join(devs)
                    # Fallback tags to genres if hover tags were empty
                    if not tags:
                        genres = app_data.get("genres", [])
                        tags = [g.get("description") for g in genres if g.get("description")]
            elif resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_time = int(retry_after) + 2 if retry_after and retry_after.isdigit() else COOLDOWN_429_BASE
                logger.warning(f"Steam appdetails 429 rate limit on appid {appid}. Cooling down for {sleep_time}s...")
                time.sleep(sleep_time)
        except Exception as e:
            logger.debug(f"Appdetails failed for appid {appid}: {e}")

        time.sleep(STEAM_DETAIL_DELAY)
        return {
            "developer": developer,
            "tags": tags
        }
