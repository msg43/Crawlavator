"""
EconTalk podcast plugin — transcripts only.

Hosted by Russ Roberts at econtalk.org.

Index strategy: Simplecast RSS feed (feeds.simplecast.com/wgl4xEgL) contains all
1,053 episodes with titles, dates, and episode page URLs. No pagination needed.

Transcript strategy: Transcripts are inline on each episode page inside a
<table class="ts2"> element. Each row is a timestamped exchange. Episodes from
before October 2006 (~20 episodes) predate transcripts and are skipped.
"""

import os
import re
import json
import requests
import feedparser
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
from datetime import datetime

from .. import BaseSite, ContentItem, register_site


RSS_URL = "https://feeds.simplecast.com/wgl4xEgL"
SITE_BASE = "https://www.econtalk.org"


@register_site
class EconTalkSite(BaseSite):
    """EconTalk podcast plugin — transcripts only."""

    SITE_ID = "econtalk"
    SITE_NAME = "EconTalk"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["podcast"]
    IMPORT_SOURCE = "econtalk.org"

    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        })

    def get_config_fields(self) -> List[Dict[str, Any]]:
        return []

    def check_auth(self) -> Tuple[bool, str]:
        return True, "No authentication required"

    def login(self, **credentials) -> Tuple[bool, str]:
        return True, "No authentication required"

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def index_content(self, progress_callback=None) -> List[ContentItem]:
        """Fetch all episodes from the Simplecast RSS feed."""
        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        _cb("Fetching EconTalk RSS feed...")
        try:
            r = self.session.get(RSS_URL, timeout=30)
            r.raise_for_status()
        except Exception as e:
            _cb(f"RSS fetch failed: {e}")
            return []

        feed = feedparser.parse(r.content)
        _cb(f"Found {len(feed.entries)} episodes, parsing...")

        items = []
        for entry in feed.entries:
            item = self._entry_to_content_item(entry)
            if item and item.id not in self.indexed_content:
                self.indexed_content[item.id] = item
                items.append(item)

        _cb(f"Indexed {len(items)} EconTalk episodes.")
        return items

    def _entry_to_content_item(self, entry) -> Optional[ContentItem]:
        title = entry.get("title", "").strip()
        url = entry.get("link", "")
        if not url or not title:
            return None

        description = BeautifulSoup(
            entry.get("summary", ""), "lxml"
        ).get_text(separator=" ", strip=True)

        date_str = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                date_str = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
            except Exception:
                pass

        # Episode number from <itunes:episode> or title heuristic
        ep_num = getattr(entry, "itunes_episode", "") or ""
        if not ep_num:
            m = re.search(r"Ep(?:isode)?\.?\s*(\d+)", title, re.IGNORECASE)
            ep_num = m.group(1) if m else self._slugify(title)[:40]

        item_id = f"et_{ep_num}"

        # Guest name: typically "Firstname Lastname on Topic"
        guest = ""
        m = re.match(r"^([A-Z][^:]+?)\s+on\s+", title)
        if m:
            guest = m.group(1).strip()

        return ContentItem(
            id=item_id,
            title=title,
            url=url,
            asset_type="transcript",
            category="podcast",
            subcategory="economics",
            date=date_str,
            description=description,
        )

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_item(
        self,
        item: ContentItem,
        output_dir: str,
        progress_callback=None,
    ) -> Tuple[bool, str]:
        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        _cb(f"Fetching episode page: {item.title}")
        try:
            r = self.session.get(item.url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            return False, f"Page fetch failed: {e}"

        soup = BeautifulSoup(r.content, "lxml")

        transcript_text = self._extract_transcript(soup)
        if not transcript_text:
            return False, "No transcript found on page (pre-2006 episode or page changed)"

        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_filename(item.title)

        txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
        header = (
            f"# {item.title}\n"
            f"Date: {item.date}\n"
            f"Source: EconTalk\n"
            f"URL: {item.url}\n\n"
            "---\n\n"
        )
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(header + transcript_text)

        raw_meta = {
            "id": item.id,
            "title": item.title,
            "date": item.date,
            "url": item.url,
            "source": "EconTalk",
            "source_url": "econtalk.org",
            "description": item.description,
            "asset_type": "transcript",
        }
        normalized = self.build_normalized_metadata(
            raw_meta,
            has_diarization=True,
            has_segments=False,
            segment_count=0,
            participants=[{"name": "Russ Roberts", "role": "host"}],
            tags=["economics", "markets", "philosophy", "econtalk"],
        )
        meta_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(normalized, fh, indent=2)

        word_count = len(transcript_text.split())
        return True, f"Downloaded transcript ({word_count:,} words)"

    def _extract_transcript(self, soup: BeautifulSoup) -> str:
        """Extract transcript from table.ts2 — each row is timestamp + dialogue."""
        table = soup.find("table", class_="ts2")
        if not table:
            return ""

        lines = []
        for row in table.find_all("tr")[1:]:  # skip header row
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            timestamp = cols[0].get_text(strip=True)
            dialogue = cols[1].get_text(separator="\n", strip=True)
            if dialogue:
                if timestamp:
                    lines.append(f"[{timestamp}]")
                lines.append(dialogue)
                lines.append("")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _slugify(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_-]+", "_", text)
        return text[:50]

    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "", name)
        safe = re.sub(r"\s+", "_", safe).strip("._")
        return safe[:100] or "untitled"

    def close(self):
        self.session.close()
