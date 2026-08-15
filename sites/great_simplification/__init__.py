"""
The Great Simplification - Frankly Original podcast plugin.

Nate Hagens' solo commentary episodes at thegreatsimplification.com/frankly-original/.

Index strategy: WordPress REST API (/wp-json/wp/v2/frankly-original) returns all
146 episodes with titles, dates, slugs, and HTML show notes.

Audio URL strategy: Libsyn RSS feed (feeds.libsyn.com/thegreatsimplification/rss)
contains enclosures for ~128 Frankly episodes. We build a date→audio_url lookup
during indexing and match by publication date (YYYY-MM-DD). Episodes whose dates
fall outside the RSS window (oldest archived episodes) are indexed without an
audio URL and logged.
"""

import os
import re
import json
import requests
import feedparser
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime, date as _date, timedelta

from .. import BaseSite, ContentItem, register_site


WP_API_BASE = "https://www.thegreatsimplification.com/wp-json/wp/v2/frankly-original"
LIBSYN_RSS_URL = "https://feeds.libsyn.com/thegreatsimplification/rss"
SITE_BASE_URL = "https://www.thegreatsimplification.com"


@register_site
class GreatSimplificationFranklySite(BaseSite):
    """The Great Simplification - Frankly Original podcast plugin."""

    SITE_ID = "great_simplification_frankly"
    SITE_NAME = "The Great Simplification - Frankly"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["audio"]
    CATEGORIES = ["podcast"]
    IMPORT_SOURCE = "thegreatsimplification.com"

    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self._all_rss_entries: List[Tuple[str, str]] = []  # [(title, audio_url)]
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
        """Discover all Frankly episodes via the WP REST API and match audio URLs
        from the Libsyn RSS feed by publication date."""

        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        _cb("Fetching Libsyn RSS feed for audio URLs...")
        audio_by_date = self._build_audio_lookup()
        _cb(f"RSS feed parsed: {len(audio_by_date)} Frankly entries with audio.")

        items = []
        page = 1
        per_page = 100

        while True:
            _cb(f"Fetching WP API page {page}...")
            try:
                r = self.session.get(
                    WP_API_BASE,
                    params={"per_page": per_page, "page": page, "orderby": "date", "order": "desc"},
                    timeout=30,
                )
                r.raise_for_status()
            except Exception as e:
                _cb(f"WP API error on page {page}: {e}")
                break

            posts = r.json()
            if not posts:
                break

            for post in posts:
                item = self._post_to_content_item(post, audio_by_date)
                if item and item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)

            total_pages = int(r.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1

        no_audio = sum(1 for i in items if not i.download_url)
        _cb(
            f"Indexed {len(items)} Frankly episodes "
            f"({no_audio} without a matched audio URL)."
        )
        return items

    def _build_audio_lookup(self) -> Dict[str, List[Tuple[str, str]]]:
        """Return date (YYYY-MM-DD) → [(title, mp3_url), ...] for ALL RSS entries.

        We index every entry (not just those with "frankly" in the title) because
        many Frankly episodes are published under their content title alone in the
        feed. Matching is done by title similarity in _post_to_content_item.
        """
        try:
            r = self.session.get(LIBSYN_RSS_URL, timeout=30)
            r.raise_for_status()
        except Exception:
            return {}

        feed = feedparser.parse(r.content)
        lookup: Dict[str, List[Tuple[str, str]]] = {}

        for entry in feed.entries:
            audio_url = ""
            if hasattr(entry, "enclosures") and entry.enclosures:
                audio_url = entry.enclosures[0].get("href", "")
            if not audio_url:
                continue

            audio_url = audio_url.split("?")[0]  # strip tracking params

            date_str = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    date_str = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if not date_str:
                continue

            title = entry.get("title", "")
            lookup.setdefault(date_str, []).append((title, audio_url))
            self._all_rss_entries.append((title, audio_url))

        return lookup

    def _post_to_content_item(
        self,
        post: Dict[str, Any],
        audio_by_date: Dict[str, List[Tuple[str, str]]],
    ) -> Optional[ContentItem]:
        """Convert a WP REST API post dict to a ContentItem."""
        slug = post.get("slug", "")
        if not slug:
            return None

        title_obj = post.get("title", {})
        title = (
            BeautifulSoup(title_obj.get("rendered", slug), "lxml").get_text()
            if isinstance(title_obj, dict)
            else str(title_obj)
        )

        # date: "2026-06-05T06:00:00" → "2026-06-05"
        date_str = (post.get("date") or "")[:10]

        link = post.get("link", f"{SITE_BASE_URL}/frankly-original/{slug}")

        content_obj = post.get("content", {})
        content_html = content_obj.get("rendered", "") if isinstance(content_obj, dict) else ""
        description = BeautifulSoup(content_html, "lxml").get_text(separator="\n", strip=True)

        # Episode number from slug prefix (e.g. "145-how-to-think-about-...")
        ep_num_match = re.match(r"^(\d+)-", slug)
        ep_num = ep_num_match.group(1) if ep_num_match else slug

        item_id = f"gsfr_{ep_num}"

        # Match audio URL: check same date and ±1 day (timezone offset between WP local and RSS UTC)
        audio_url = self._match_audio_url(title, date_str, audio_by_date)

        return ContentItem(
            id=item_id,
            title=title,
            url=link,
            asset_type="audio",
            category="podcast",
            subcategory="frankly-original",
            date=date_str,
            description=description,
            download_url=audio_url or None,
        )

    def _match_audio_url(
        self,
        wp_title: str,
        date_str: str,
        audio_by_date: Dict[str, List[Tuple[str, str]]],
    ) -> str:
        """Return the best-matching audio URL for a WP episode title on a given date.

        Checks the exact date and ±1 day to handle timezone offset between the WP
        site's local publish time and the RSS feed's UTC timestamp. When multiple
        RSS entries share the same date (regular TGS interview + Frankly episode
        published the same day), we rank by Jaccard word-overlap with the WP title.
        """
        try:
            base = _date.fromisoformat(date_str)
            check_dates = [
                date_str,
                (base + timedelta(days=1)).isoformat(),
                (base - timedelta(days=1)).isoformat(),
            ]
        except Exception:
            check_dates = [date_str]

        all_candidates: List[Tuple[str, str]] = []
        for d in check_dates:
            all_candidates.extend(audio_by_date.get(d, []))

        wp_words = set(re.sub(r"[^a-z0-9\s]", "", wp_title.lower()).split())

        # Score date-window candidates
        best_url = ""
        best_score = -1.0
        for rss_title, rss_url in all_candidates:
            rss_words = set(re.sub(r"[^a-z0-9\s]", "", rss_title.lower()).split())
            union = wp_words | rss_words
            score = len(wp_words & rss_words) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_url = rss_url

        # Accept date-window match if overlap is strong enough
        if best_score >= 0.25:
            return best_url

        # Date-window miss (empty window or low score): global title search.
        # Higher threshold (0.4) guards against false positives on short titles.
        if not wp_words:
            return ""
        global_best_url = ""
        global_best_score = -1.0
        for rss_title, rss_url in self._all_rss_entries:
            rss_words = set(re.sub(r"[^a-z0-9\s]", "", rss_title.lower()).split())
            union = wp_words | rss_words
            score = len(wp_words & rss_words) / len(union) if union else 0.0
            if score > global_best_score:
                global_best_score = score
                global_best_url = rss_url

        return global_best_url if global_best_score >= 0.4 else ""

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_item(
        self,
        item: ContentItem,
        output_dir: str,
        progress_callback=None,
    ) -> Tuple[bool, str]:
        """Download the episode audio and write a metadata + description sidecar."""

        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_filename(item.title)

        # If we have no audio URL, try to resolve it from the episode page
        audio_url = item.download_url
        if not audio_url:
            _cb(f"No cached audio URL; fetching episode page: {item.url}")
            audio_url = self._resolve_audio_url_from_page(item.url)
        if not audio_url:
            return False, f"No audio URL found for: {item.title}"

        _cb(f"Downloading audio: {item.title}")
        try:
            r = self.session.get(audio_url, stream=True, timeout=120)
            r.raise_for_status()
        except Exception as e:
            return False, f"Audio download failed: {e}"

        ext = ".mp3"
        for suffix in (".m4a", ".ogg", ".wav"):
            if suffix in audio_url.lower():
                ext = suffix
                break

        audio_path = os.path.join(output_dir, f"{safe_title}{ext}")
        total_bytes = 0
        with open(audio_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    total_bytes += len(chunk)

        # Write show-notes / description as a text file
        if item.description:
            notes_path = os.path.join(output_dir, f"{safe_title}_shownotes.txt")
            header = (
                f"# {item.title}\n"
                f"Date: {item.date}\n"
                f"Source: The Great Simplification — Frankly\n"
                f"URL: {item.url}\n\n"
                "---\n\n"
            )
            with open(notes_path, "w", encoding="utf-8") as fh:
                fh.write(header + item.description)

        # Write normalized metadata
        raw_meta = {
            "id": item.id,
            "title": item.title,
            "date": item.date,
            "url": item.url,
            "audio_url": audio_url,
            "source": "The Great Simplification — Frankly",
            "source_url": "thegreatsimplification.com",
            "description": item.description,
            "asset_type": "audio",
        }
        normalized = self.build_normalized_metadata(
            raw_meta,
            has_diarization=False,
            has_segments=False,
            segment_count=0,
            participants=[{"name": "Nate Hagens", "role": "host"}],
            tags=["metacrisis", "energy", "ecology", "economics", "frankly"],
        )
        meta_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(normalized, fh, indent=2)

        mb = total_bytes / (1024 * 1024)
        return True, f"Downloaded audio ({mb:.1f} MB)"

    def _resolve_audio_url_from_page(self, episode_url: str) -> Optional[str]:
        """Last-resort: fetch the episode page, extract the Libsyn embed ID, then
        search the RSS feed for a matching entry by trying the embed ID in the URL."""
        try:
            r = self.session.get(episode_url, timeout=30)
            r.raise_for_status()
        except Exception:
            return None

        match = re.search(r"play\.libsyn\.com/embed/episode/id/(\d+)", r.text)
        if not match:
            return None
        libsyn_id = match.group(1)

        # The Libsyn embed player page sometimes embeds the direct MP3 URL
        try:
            embed_r = self.session.get(
                f"https://html5-player.libsyn.com/embed/episode/id/{libsyn_id}",
                timeout=15,
            )
            mp3_match = re.search(
                r"(https://traffic\.libsyn\.com/[^\s\"'<>]+\.mp3)", embed_r.text
            )
            if mp3_match:
                return mp3_match.group(1).split("?")[0]
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "", name)
        safe = re.sub(r"\s+", "_", safe).strip("._")
        return safe[:100] or "untitled"

    def close(self):
        self.session.close()
