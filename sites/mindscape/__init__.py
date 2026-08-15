"""
Sean Carroll's Mindscape podcast plugin — transcripts only.

Hosted at preposterousuniverse.com/podcast.

Index strategy: Libsyn RSS feed (rss.libsyn.com/shows/604590/destinations/5288840.xml)
contains all 430 episodes with titles, dates, and episode page URLs embedded in the
description CDATA.

Transcript strategy: Transcripts are inline on each episode page in a collapsible
accordion widget. Two formats depending on era:
  - Format A (ep ~174+, 2022 onward): UABB accordion div with id "uabb-accordion-content-*"
  - Format B (older): unrendered WordPress shortcode [accordion-item...] in raw HTML
Both are fully present in static HTML — no JS rendering needed.
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


RSS_URL = "https://rss.libsyn.com/shows/604590/destinations/5288840.xml"
SITE_BASE = "https://www.preposterousuniverse.com"


@register_site
class MindscapeSite(BaseSite):
    """Sean Carroll's Mindscape podcast plugin — transcripts only."""

    SITE_ID = "mindscape"
    SITE_NAME = "Sean Carroll's Mindscape"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["podcast"]
    IMPORT_SOURCE = "preposterousuniverse.com"

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
        """Fetch all episodes via RSS + archive page URL map.

        The Libsyn RSS pubDate often differs from the WordPress blog post date,
        making date-based URL construction unreliable for pre-2020 episodes. We
        build a normalised-title → URL map by scraping the paginated archive first,
        then merge it with the RSS feed (which carries audio URLs and descriptions).
        """
        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        _cb("Building episode URL map from archive pages...")
        url_map = self._build_archive_url_map(_cb)
        _cb(f"URL map built: {len(url_map)} entries.")

        _cb("Fetching Mindscape RSS feed...")
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
            item = self._entry_to_content_item(entry, url_map)
            if item and item.id not in self.indexed_content:
                self.indexed_content[item.id] = item
                items.append(item)

        _cb(f"Indexed {len(items)} Mindscape episodes.")
        return items

    def _build_archive_url_map(self, progress_callback=None) -> Dict[str, str]:
        """Scrape all archive pages.

        Returns a dict keyed two ways so lookup can try both:
          "title:{normalised_title}" → url
          "ep:{episode_number}"      → url
        """
        url_map: Dict[str, str] = {}
        page = 1
        while True:
            archive_url = (
                f"{SITE_BASE}/podcast/"
                if page == 1
                else f"{SITE_BASE}/podcast/page/{page}/"
            )
            try:
                r = self.session.get(archive_url, timeout=30)
                r.raise_for_status()
            except Exception:
                break

            soup = BeautifulSoup(r.content, "lxml")
            found = 0
            seen_hrefs: set = set()
            for a in soup.find_all("a", href=True):
                href = a["href"].split("#")[0]  # strip anchors
                if not re.search(r"/podcast/\d{4}/\d{2}/\d{2}/[^/]+/?$", href):
                    continue
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                # Key by normalised link title text
                title_text = a.get_text(strip=True)
                if title_text:
                    key = f"title:{self._normalise(title_text)}"
                    url_map.setdefault(key, href)

                # Key by episode number extracted from URL slug
                slug = href.rstrip("/").split("/")[-1]
                ep_m = re.match(r"^(?:episode-)?(\d+)-", slug)
                if ep_m:
                    ep_key = f"ep:{ep_m.group(1)}"
                    url_map.setdefault(ep_key, href)

                found += 1

            if not found:
                break
            page += 1

        return url_map

    def _entry_to_content_item(
        self, entry, url_map: Dict[str, str]
    ) -> Optional[ContentItem]:
        title = entry.get("title", "").strip()
        if not title:
            return None

        # Episode number from title: "356 | Andrea Wulf on ..." or "Episode 21 | ..."
        ep_num = ""
        m = re.match(r"^(\d+)\s*[|–-]", title)
        if m:
            ep_num = m.group(1)
        else:
            m2 = re.match(r"^Episode\s+(\d+)", title, re.IGNORECASE)
            if m2:
                ep_num = m2.group(1)

        # 1. URL embedded in description CDATA (recent episodes)
        description_html = entry.get("summary", "")
        page_url = self._extract_page_url(description_html)

        # 2. Look up by episode number (most reliable) then normalised title
        if not page_url and ep_num:
            page_url = url_map.get(f"ep:{ep_num}", "")
        if not page_url:
            page_url = url_map.get(f"title:{self._normalise(title)}", "")

        # 3. Date-based construction from Libsyn slug (post-2020 reliable)
        if not page_url:
            libsyn_link = entry.get("link", "")
            slug = libsyn_link.rstrip("/").split("/")[-1] if libsyn_link else ""
            if slug and hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    y, mo, d = entry.published_parsed[:3]
                    if y >= 2020:
                        page_url = f"{SITE_BASE}/podcast/{y}/{mo:02d}/{d:02d}/{slug}/"
                except Exception:
                    pass

        if not page_url:
            return None

        description = BeautifulSoup(description_html, "lxml").get_text(
            separator=" ", strip=True
        )

        date_str = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                date_str = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
            except Exception:
                pass

        item_id = f"ms_{ep_num}" if ep_num else f"ms_{self._slugify(title)}"

        return ContentItem(
            id=item_id,
            title=title,
            url=page_url,
            asset_type="transcript",
            category="podcast",
            subcategory="physics-philosophy",
            date=date_str,
            description=description,
        )

    def _extract_page_url(self, description_html: str) -> str:
        """Extract the episode page URL from RSS description CDATA."""
        # Pattern: Blog post with transcript: <a href="URL">
        m = re.search(
            r'href=\s*["\']?(https://www\.preposterousuniverse\.com/podcast/[^"\'>\s]+)',
            description_html,
        )
        return m.group(1) if m else ""

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
        raw_html = r.text

        transcript_text = self._extract_transcript(soup, raw_html)
        if not transcript_text:
            return False, "No transcript found (older episode may lack one)"

        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_filename(item.title)

        txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
        header = (
            f"# {item.title}\n"
            f"Date: {item.date}\n"
            f"Source: Sean Carroll's Mindscape\n"
            f"URL: {item.url}\n\n"
            "---\n\n"
        )
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(header + transcript_text)

        participants = self._extract_participants(item.title)

        raw_meta = {
            "id": item.id,
            "title": item.title,
            "date": item.date,
            "url": item.url,
            "source": "Sean Carroll's Mindscape",
            "source_url": "preposterousuniverse.com",
            "description": item.description,
            "asset_type": "transcript",
        }
        normalized = self.build_normalized_metadata(
            raw_meta,
            has_diarization=True,
            has_segments=False,
            segment_count=0,
            participants=participants,
            tags=["physics", "philosophy", "science", "complexity", "mindscape"],
        )
        meta_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(normalized, fh, indent=2)

        word_count = len(transcript_text.split())
        return True, f"Downloaded transcript ({word_count:,} words)"

    def _extract_transcript(self, soup: BeautifulSoup, raw_html: str) -> str:
        """Two-format transcript extraction:
        - Format A (ep 174+): UABB accordion div id="uabb-accordion-content-*"
        - Format B (older): raw [accordion-item] shortcode in HTML
        """
        # Format A: UABB accordion (rendered HTML)
        uabb_div = soup.find(id=re.compile(r"uabb-accordion-content-"))
        if uabb_div:
            text = uabb_div.get_text(separator="\n", strip=True)
            # Strip the "Click above to close." artifact that sometimes appears
            text = re.sub(r"^Click above to close\.\s*", "", text)
            if len(text) > 200:
                return text

        # Format B: unrendered shortcode in raw HTML
        m = re.search(
            r'\[accordion-item[^\]]+title=["\']Click to Show Episode Transcript["\'][^\]]*\](.*?)\[/accordion-item\]',
            raw_html,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            raw_transcript = m.group(1).strip()
            # Strip leading artifact
            raw_transcript = re.sub(r"^Click above to close\.\s*", "", raw_transcript)
            # Parse any residual HTML tags
            text = BeautifulSoup(raw_transcript, "lxml").get_text(
                separator="\n", strip=True
            )
            if len(text) > 200:
                return text

        return ""

    def _extract_participants(self, title: str) -> List[Dict[str, str]]:
        """Parse guest name from title format '356 | Guest Name on Topic'."""
        participants = [{"name": "Sean Carroll", "role": "host"}]
        # "356 | Andrea Wulf on ..."
        m = re.match(r"^\d+\s*[|–-]\s*(.+?)\s+on\s+", title)
        if m:
            guest = m.group(1).strip()
            if guest.lower() not in ("sean carroll", "ama", ""):
                participants.append({"name": guest, "role": "guest"})
        return participants

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        """Lowercase, strip punctuation — used for title-based URL map lookup."""
        return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()

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
