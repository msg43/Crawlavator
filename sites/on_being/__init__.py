"""
On Being podcast plugin — transcripts only.

Hosted by Krista Tippett at onbeing.org.

Index strategy: WordPress REST API at /wp-json/wp/v2/programs returns all 531
episodes (post type "programs") paginated at 100 per page.

Transcript strategy: Transcripts are inline on each episode page inside
div#transcript > div.episode__transcript-body. A homepage request is made first
to establish a session cookie (direct API/page requests can return 403 otherwise).
"""

import os
import re
import json
import requests
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
from datetime import datetime

from .. import BaseSite, ContentItem, register_site


WP_API_BASE = "https://onbeing.org/wp-json/wp/v2/programs"
HOMEPAGE = "https://onbeing.org/"
SITE_BASE = "https://onbeing.org"


@register_site
class OnBeingSite(BaseSite):
    """On Being podcast plugin — transcripts only."""

    SITE_ID = "on_being"
    SITE_NAME = "On Being"
    REQUIRES_AUTH = False
    ASSET_TYPES = ["transcript"]
    CATEGORIES = ["podcast"]
    IMPORT_SOURCE = "onbeing.org"

    def __init__(self):
        self.indexed_content: Dict[str, ContentItem] = {}
        self._session_ready = False
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Encoding": "identity",
        })

    def _ensure_session(self):
        """Hit the homepage once to establish a PHPSESSID cookie."""
        if self._session_ready:
            return
        try:
            self.session.get(HOMEPAGE, timeout=20)
        except Exception:
            pass
        self._session_ready = True

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
        """Enumerate all episodes via the WP REST API."""
        def _cb(msg):
            if progress_callback:
                progress_callback(msg)

        _cb("Establishing session with onbeing.org...")
        self._ensure_session()

        items = []
        page = 1

        while True:
            _cb(f"Fetching episode list page {page}...")
            try:
                r = self.session.get(
                    WP_API_BASE,
                    params={
                        "per_page": 100,
                        "page": page,
                        "_fields": "id,slug,date,title,link,excerpt",
                    },
                    timeout=30,
                )
                r.raise_for_status()
            except Exception as e:
                _cb(f"API error on page {page}: {e}")
                break

            posts = r.json()
            if not posts:
                break

            for post in posts:
                item = self._post_to_content_item(post)
                if item and item.id not in self.indexed_content:
                    self.indexed_content[item.id] = item
                    items.append(item)

            if len(posts) < 100:
                break
            page += 1

        _cb(f"Indexed {len(items)} On Being episodes.")
        return items

    def _post_to_content_item(self, post: Dict[str, Any]) -> Optional[ContentItem]:
        slug = post.get("slug", "")
        if not slug:
            return None

        title_obj = post.get("title", {})
        title = (
            BeautifulSoup(title_obj.get("rendered", slug), "lxml").get_text()
            if isinstance(title_obj, dict)
            else str(title_obj)
        ).strip()

        link = post.get("link", f"{SITE_BASE}/programs/{slug}/")
        date_str = (post.get("date") or "")[:10]

        excerpt_obj = post.get("excerpt", {})
        description = BeautifulSoup(
            excerpt_obj.get("rendered", "") if isinstance(excerpt_obj, dict) else "",
            "lxml",
        ).get_text(separator=" ", strip=True)

        # Guest name often appears before " — " in the title (e.g. "Robin Wall Kimmerer — ...")
        guest = ""
        m = re.match(r"^(.+?)\s+[—–-]{1,2}\s+", title)
        if m:
            guest = m.group(1).strip()

        item_id = f"ob_{slug[:60]}"

        return ContentItem(
            id=item_id,
            title=title,
            url=link,
            asset_type="transcript",
            category="podcast",
            subcategory="spirituality-philosophy",
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

        self._ensure_session()

        _cb(f"Fetching episode page: {item.title}")
        try:
            r = self.session.get(item.url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            return False, f"Page fetch failed: {e}"

        soup = BeautifulSoup(r.content, "lxml")

        transcript_text = self._extract_transcript(soup)
        if not transcript_text:
            return False, "No transcript found on page"

        os.makedirs(output_dir, exist_ok=True)
        safe_title = self._safe_filename(item.title)

        txt_path = os.path.join(output_dir, f"{safe_title}_transcript.txt")
        header = (
            f"# {item.title}\n"
            f"Date: {item.date}\n"
            f"Source: On Being\n"
            f"URL: {item.url}\n\n"
            "---\n\n"
        )
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(header + transcript_text)

        # Enrich participants from page if possible
        participants = self._extract_participants(soup)
        if not participants:
            participants = [{"name": "Krista Tippett", "role": "host"}]

        raw_meta = {
            "id": item.id,
            "title": item.title,
            "date": item.date,
            "url": item.url,
            "source": "On Being",
            "source_url": "onbeing.org",
            "description": item.description,
            "asset_type": "transcript",
        }
        normalized = self.build_normalized_metadata(
            raw_meta,
            has_diarization=True,
            has_segments=False,
            segment_count=0,
            participants=participants,
            tags=["philosophy", "spirituality", "meaning", "on-being"],
        )
        meta_path = os.path.join(output_dir, f"{safe_title}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(normalized, fh, indent=2)

        word_count = len(transcript_text.split())
        return True, f"Downloaded transcript ({word_count:,} words)"

    def _extract_transcript(self, soup: BeautifulSoup) -> str:
        """Extract transcript from div#transcript > div.episode__transcript-body."""
        transcript_div = soup.find(id="transcript")
        if not transcript_div:
            # Fallback: look for the class directly
            transcript_div = soup.find(class_="episode__transcript")
        if not transcript_div:
            return ""

        body = transcript_div.find(class_="episode__transcript-body")
        if not body:
            body = transcript_div

        return body.get_text(separator="\n", strip=True)

    def _extract_participants(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Try to extract guest and host names from the episode page."""
        participants = [{"name": "Krista Tippett", "role": "host"}]

        # Guest name from subheading h2.episode__header-subhead
        subhead = soup.find(class_="episode__header-subhead")
        if subhead:
            guest_name = subhead.get_text(strip=True)
            if guest_name and guest_name.lower() != "krista tippett":
                participants.append({"name": guest_name, "role": "guest"})

        return participants

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_filename(self, name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "", name)
        safe = re.sub(r"\s+", "_", safe).strip("._")
        return safe[:100] or "untitled"

    def close(self):
        self.session.close()
