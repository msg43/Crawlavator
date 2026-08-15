#!/usr/bin/env python3
"""
One-time backfill script: generate metadata.json sidecars for orphan mp3 files
in Invest Like the Best and The Ezra Klein Show directories.

Reads data from the RSS feeds and matches to existing files by safe-filename.
"""

import os
import re
import json
import sys
import feedparser
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────

FEEDS = [
    {
        "name": "Invest Like the Best",
        "rss_url": "https://investlikethebest.libsyn.com/rss",
        "dir": "/Volumes/OWC 12TB/PODCASTS/AUDIO ONLY/Invest Like the Best",
        "id_prefix": "ilb",
        "source": "Invest Like the Best",
        "source_url": "joincolossus.com",
        "import_source": "joincolossus.com",
    },
    {
        "name": "The Ezra Klein Show",
        "rss_url": "https://feeds.simplecast.com/82FI35Px",
        "dir": "/Volumes/OWC 12TB/PODCASTS/AUDIO ONLY/The Ezra Klein Show",
        "id_prefix": "ezra",
        "source": "The Ezra Klein Show",
        "source_url": "",
        "import_source": "nytimes.com/ezra-klein-show",
    },
]

CRAWLAVATOR_VERSION = "1.1.0"


# ── Helpers (match the plugin logic exactly) ────────────────────────────────

def safe_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', '_', safe)
    safe = safe.strip('._')
    return safe[:100] if safe else 'untitled'


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text[:50]


def build_metadata(raw: dict, import_source: str) -> dict:
    """Build the normalized crawlavator metadata schema."""
    CANONICAL_KEYS = {
        "id", "title", "date", "url", "source", "source_url",
        "description", "asset_type", "segment_count",
    }
    canonical = {
        "id": raw.get("id", ""),
        "title": raw.get("title", ""),
        "date": raw.get("date", ""),
        "url": raw.get("url", ""),
        "source": raw.get("source", ""),
        "source_url": raw.get("source_url", ""),
        "description": raw.get("description", ""),
        "participants": [],
        "tags": [],
        "asset_type": raw.get("asset_type", "audio"),
        "has_diarization": False,
        "has_segments": False,
        "segment_count": 0,
        "youtube_video_id": None,
        "provenance": {
            "producer_app": "crawlavator",
            "version": CRAWLAVATOR_VERSION,
            "import_source": import_source,
            "scrape_date": datetime.utcnow().strftime("%Y-%m-%d"),
        },
    }
    site_metadata = {}
    for key, value in raw.items():
        if key not in CANONICAL_KEYS and key != "provenance":
            site_metadata[key] = value
    canonical["site_metadata"] = site_metadata
    return canonical


# ── Main ────────────────────────────────────────────────────────────────────

def backfill_feed(feed_cfg: dict) -> dict:
    name = feed_cfg["name"]
    audio_dir = feed_cfg["dir"]

    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")

    if not os.path.isdir(audio_dir):
        print(f"  ERROR: directory not found: {audio_dir}")
        return {"feed": name, "created": 0, "skipped": 0, "unmatched": 0, "errors": []}

    # 1. Discover orphan mp3s (mp3 with no matching _metadata.json)
    all_files = set(os.listdir(audio_dir))
    mp3_files = sorted(f for f in all_files if f.endswith('.mp3'))
    orphans = {}
    already_have = 0
    for mp3 in mp3_files:
        stem = mp3[:-4]  # strip .mp3
        meta_name = f"{stem}_metadata.json"
        if meta_name in all_files:
            already_have += 1
        else:
            orphans[stem] = mp3

    print(f"  Total mp3 files:        {len(mp3_files)}")
    print(f"  Already have metadata:  {already_have}")
    print(f"  Orphans needing fill:   {len(orphans)}")

    if not orphans:
        print("  Nothing to do!")
        return {"feed": name, "created": 0, "skipped": already_have, "unmatched": 0, "errors": []}

    # 2. Fetch RSS feed and build a lookup from safe_filename → entry data
    print(f"  Fetching RSS feed...")
    feed = feedparser.parse(feed_cfg["rss_url"])
    print(f"  RSS entries: {len(feed.entries)}")

    rss_lookup = {}  # safe_filename stem → entry dict
    for entry in feed.entries:
        title = entry.get('title', 'Untitled Episode')
        url = entry.get('link', '')
        description = entry.get('summary', '')
        date_str = ''
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
            except:
                pass

        audio_url = None
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enc in entry.enclosures:
                if 'audio' in enc.get('type', ''):
                    audio_url = enc.get('href', '')
                    break

        stem = safe_filename(title)
        rss_lookup[stem] = {
            "title": title,
            "url": url,
            "description": description,
            "date": date_str,
            "audio_url": audio_url,
        }

    # 3. Match orphans to RSS entries
    created = 0
    unmatched_list = []
    errors = []
    created_files = []

    for stem, mp3_name in sorted(orphans.items()):
        rss_entry = rss_lookup.get(stem)
        if not rss_entry:
            unmatched_list.append(stem)
            continue

        # Build the ID
        slug = slugify(rss_entry["title"])
        item_id = f"{feed_cfg['id_prefix']}_{slug}"

        raw_metadata = {
            "id": item_id,
            "title": rss_entry["title"],
            "url": rss_entry["url"],
            "date": rss_entry["date"],
            "description": rss_entry["description"],
            "source": feed_cfg["source"],
            "source_url": feed_cfg["source_url"],
            "asset_type": "audio",
        }
        normalized = build_metadata(raw_metadata, feed_cfg["import_source"])

        meta_path = os.path.join(audio_dir, f"{stem}_metadata.json")
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(normalized, f, indent=2)
            created += 1
            created_files.append(f"{stem}_metadata.json")
            print(f"  ✓ {stem}_metadata.json")
        except Exception as e:
            errors.append(f"{stem}: {e}")
            print(f"  ✗ {stem}: {e}")

    if unmatched_list:
        print(f"\n  Unmatched orphans ({len(unmatched_list)}):")
        for u in unmatched_list:
            print(f"    - {u}")

    print(f"\n  Summary: {created} created, {len(unmatched_list)} unmatched, {len(errors)} errors")
    return {
        "feed": name,
        "created": created,
        "skipped": already_have,
        "unmatched": len(unmatched_list),
        "unmatched_files": unmatched_list,
        "errors": errors,
        "created_files": created_files,
    }


if __name__ == "__main__":
    print("Backfill Metadata Sidecars")
    print("=" * 70)

    results = []
    for feed_cfg in FEEDS:
        result = backfill_feed(feed_cfg)
        results.append(result)

    print(f"\n\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    total_created = 0
    total_unmatched = 0
    for r in results:
        print(f"  {r['feed']}: {r['created']} created, {r['unmatched']} unmatched, {len(r['errors'])} errors")
        total_created += r['created']
        total_unmatched += r['unmatched']
    print(f"  TOTAL: {total_created} metadata files created, {total_unmatched} unmatched")
