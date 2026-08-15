#!/usr/bin/env python3
"""
scrape_channel.py - Standalone script to scrape crawlavator plugin channels.

Usage:
    python scrape_channel.py --channel bigthink
    python scrape_channel.py --channel all
    python scrape_channel.py --list

Downloads content to /Volumes/OWC 12TB/PODCASTS/[SITE_NAME]/
"""

import os
import sys
import json
import time
import argparse
import traceback
from datetime import datetime

# Set up sys.path so we can import from crawlavator
CRAWLAVATOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CRAWLAVATOR_DIR)

# Import site plugins (this triggers registration via @register_site decorators)
from sites import list_sites, get_site, ContentItem
from sites.eurodollar import EurodollarSite
from sites.lexfridman import LexFridmanSite
from sites.conversationswithtyler import ConversationsWithTylerSite
from sites.private_rss import PrivateRSSSite
from sites.invest_like_best import InvestLikeBestSite
from sites.macrovoices import MacroVoicesSite
from sites.peter_zeihan import PeterZeihanSite
from sites.ezra_klein import EzraKleinSite
from sites.odd_lots import OddLotsSite
from sites.hidden_forces import HiddenForcesSite
from sites.excess_returns import ExcessReturnsSite
from sites.dwarkesh import DwarkeshSite
from sites.fareed_zakaria import FareedZakariaSite
from sites.bigthink import BigThinkSite

# Output root
OUTPUT_ROOT = "/Volumes/OWC 12TB/PODCASTS"

# Config file for credentials
CONFIG_FILE = os.path.join(CRAWLAVATOR_DIR, "config.json")

# Channels to skip (already have audio + metadata in AUDIO ONLY)
SKIP_CHANNELS = {"peter_zeihan", "invest_like_best", "ezra_klein"}

# Delay between downloads (seconds)
DOWNLOAD_DELAY = 1

# Ordered list of channels to process (fastest first)
CHANNEL_ORDER = [
    "private_rss",  # RSS feeds first — no auth, fast
    "bigthink",
    "conversationswithtyler",
    "lexfridman",
    "excess_returns",
    "hidden_forces",
    "macrovoices",
    "odd_lots",
    "fareed_zakaria",
    "dwarkesh",
    "eurodollar",
]


def load_config():
    """Load crawlavator config.json"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def log(msg, level="INFO"):
    """Print timestamped log message"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def scrape_channel(channel_id, skip_videos=False, item_id=None):
    """Scrape a single channel. Returns a summary dict."""
    site_class = get_site(channel_id)
    if not site_class:
        log(f"Unknown channel: {channel_id}", "ERROR")
        return {"channel": channel_id, "error": "Unknown channel ID"}

    site = site_class()
    site_name = site.SITE_NAME
    output_dir = os.path.join(OUTPUT_ROOT, site_name)

    log(f"=" * 60)
    log(f"STARTING: {site_name} ({channel_id})")
    log(f"Output: {output_dir}")
    log(f"Asset types: {site.ASSET_TYPES}")
    log(f"=" * 60)

    summary = {
        "channel": channel_id,
        "site_name": site_name,
        "output_dir": output_dir,
        "indexed": 0,
        "downloaded": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": [],
        "start_time": datetime.now().isoformat(),
    }

    # --- Auth for Eurodollar ---
    if site.REQUIRES_AUTH:
        log("Checking authentication...")
        is_auth, auth_msg = site.check_auth()
        if is_auth:
            log(f"Auth OK: {auth_msg}")
        else:
            log(f"Auth check failed: {auth_msg}", "WARN")
            # Try automated login
            cfg = load_config()
            site_cfg = cfg.get("sites", {}).get(channel_id, {})
            email = site_cfg.get("email", cfg.get("email", ""))
            password = site_cfg.get("password", cfg.get("password", ""))

            if email and password:
                log("Attempting automated login (headless)...")
                try:
                    # For eurodollar, the login method calls self.auth.login()
                    # We need to access auth directly for headless control
                    if hasattr(site, "auth"):
                        success, msg = site.auth.login(email, password, headless=True)
                    else:
                        success, msg = site.login(email=email, password=password)

                    if success:
                        log(f"Login successful: {msg}")
                    else:
                        log(f"Headless login failed: {msg}", "WARN")
                        log("Attempting visible browser login...")
                        if hasattr(site, "auth"):
                            success, msg = site.auth.login(email, password, headless=False)
                        else:
                            success, msg = site.login(email=email, password=password)

                        if success:
                            log(f"Visible login successful: {msg}")
                        else:
                            log(f"All login attempts failed: {msg}", "ERROR")
                            summary["error"] = f"Auth failed: {msg}"
                            summary["end_time"] = datetime.now().isoformat()
                            return summary
                except Exception as e:
                    log(f"Login error: {e}", "ERROR")
                    summary["error"] = f"Auth exception: {e}"
                    summary["end_time"] = datetime.now().isoformat()
                    return summary
            else:
                log("No credentials found in config.json", "ERROR")
                summary["error"] = "No credentials"
                summary["end_time"] = datetime.now().isoformat()
                return summary

    # --- Index content ---
    log("Indexing content...")
    try:
        items = site.index_content(
            progress_callback=lambda msg: log(f"  {msg}")
        )
        summary["indexed"] = len(items)
        log(f"Indexed {len(items)} items")
    except Exception as e:
        log(f"Indexing failed: {e}", "ERROR")
        traceback.print_exc()
        summary["error"] = f"Index failed: {e}"
        summary["end_time"] = datetime.now().isoformat()
        return summary

    if not items:
        log("No items found to download")
        summary["end_time"] = datetime.now().isoformat()
        return summary

    # --- Filter items ---
    if skip_videos:
        before_count = len(items)
        items = [item for item in items if item.asset_type != "video"]
        skipped_count = before_count - len(items)
        if skipped_count:
            log(f"Skipped {skipped_count} video items (--skip-videos)")
            summary["skipped"] += skipped_count

    if item_id:
        before_count = len(items)
        items = [i for i in items if i.id == item_id or item_id in i.id or item_id in (i.url or "")]
        if not items:
            log(f"No item matching --item-id '{item_id}' found", "ERROR")
            summary["error"] = f"Item not found: {item_id}"
            summary["end_time"] = datetime.now().isoformat()
            return summary
        log(f"Filtered to 1 item: {items[0].title[:60]}")

    # --- Download items ---
    os.makedirs(output_dir, exist_ok=True)
    log(f"Downloading {len(items)} items to {output_dir}...")

    for i, item in enumerate(items, 1):
        try:
            log(f"  [{i}/{len(items)}] {item.title[:60]}...")
            success, message = site.download_item(item, output_dir)

            if success:
                summary["downloaded"] += 1
                log(f"    OK: {message[:80] if message else 'Success'}")
            else:
                # Check if it's a "not found" type skip vs real error
                if "already" in (message or "").lower():
                    summary["skipped"] += 1
                    log(f"    SKIP: {message[:80]}")
                else:
                    summary["errors"] += 1
                    summary["error_details"].append(
                        {"title": item.title[:50], "error": message[:100] if message else "Unknown"}
                    )
                    log(f"    FAIL: {message[:80] if message else 'Unknown error'}", "WARN")

        except Exception as e:
            summary["errors"] += 1
            summary["error_details"].append(
                {"title": item.title[:50], "error": str(e)[:100]}
            )
            log(f"    EXCEPTION: {e}", "ERROR")

        # Rate limiting
        if i < len(items):
            time.sleep(DOWNLOAD_DELAY)

    # --- Cleanup ---
    try:
        site.close()
    except Exception:
        pass

    summary["end_time"] = datetime.now().isoformat()

    # --- Summary ---
    log(f"")
    log(f"COMPLETED: {site_name}")
    log(f"  Indexed:    {summary['indexed']}")
    log(f"  Downloaded: {summary['downloaded']}")
    log(f"  Skipped:    {summary['skipped']}")
    log(f"  Errors:     {summary['errors']}")
    if summary["error_details"]:
        log(f"  Error details:")
        for err in summary["error_details"][:10]:
            log(f"    - {err['title']}: {err['error']}")
        if len(summary["error_details"]) > 10:
            log(f"    ... and {len(summary['error_details']) - 10} more")
    log(f"")

    return summary


def verify_channel(channel_id, site_name, output_dir):
    """Verify downloaded content for a channel."""
    if not os.path.exists(output_dir):
        return {"channel": channel_id, "exists": False, "files": 0, "metadata": 0}

    content_files = 0
    metadata_files = 0
    orphan_content = []  # Content files without metadata

    for f in os.listdir(output_dir):
        if f.endswith("_metadata.json"):
            metadata_files += 1
        elif f.endswith((".txt", ".mp3", ".m4a", ".mp4", ".pdf", ".wav")):
            content_files += 1
            # Check for matching metadata
            stem = os.path.splitext(f)[0]
            # Remove known suffixes
            for suffix in ["_transcript"]:
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            meta_file = f"{stem}_metadata.json"
            if not os.path.exists(os.path.join(output_dir, meta_file)):
                orphan_content.append(f)

    return {
        "channel": channel_id,
        "site_name": site_name,
        "exists": True,
        "content_files": content_files,
        "metadata_files": metadata_files,
        "orphan_content": orphan_content[:5],  # First 5 only
        "orphan_count": len(orphan_content),
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape crawlavator channels")
    parser.add_argument(
        "--channel",
        type=str,
        help='Channel ID to scrape (e.g. "bigthink") or "all" for all 10 channels',
    )
    parser.add_argument(
        "--list", action="store_true", help="List available channels"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify downloaded content"
    )
    parser.add_argument(
        "--skip-videos", action="store_true",
        help="Skip video asset types (useful for Eurodollar when ffmpeg fails)"
    )
    parser.add_argument(
        "--item-id",
        type=str,
        help="Download only the item with this ID (e.g. lex_sean-carroll-3)",
    )
    args = parser.parse_args()

    if args.list:
        print("\nAvailable channels to scrape:")
        print("-" * 50)
        for cid in CHANNEL_ORDER:
            site_class = get_site(cid)
            if site_class:
                s = site_class()
                auth = " [AUTH REQUIRED]" if s.REQUIRES_AUTH else ""
                print(f"  {cid:30s} {s.SITE_NAME}{auth}")
        print(f"\nSkipped (already done): {', '.join(SKIP_CHANNELS)}")
        return

    if args.verify:
        log("Verifying all channel downloads...")
        results = []
        for cid in CHANNEL_ORDER:
            site_class = get_site(cid)
            if site_class:
                s = site_class()
                out_dir = os.path.join(OUTPUT_ROOT, s.SITE_NAME)
                result = verify_channel(cid, s.SITE_NAME, out_dir)
                results.append(result)
                status = "OK" if result.get("exists") else "MISSING"
                log(
                    f"  {s.SITE_NAME:35s} {status:8s} "
                    f"content={result.get('content_files', 0):4d}  "
                    f"metadata={result.get('metadata_files', 0):4d}  "
                    f"orphans={result.get('orphan_count', 0):3d}"
                )
        return

    if not args.channel:
        parser.print_help()
        return

    # Determine which channels to scrape
    if args.channel == "all":
        channels = CHANNEL_ORDER
    else:
        channels = [args.channel]

    # Validate
    for cid in channels:
        if cid in SKIP_CHANNELS:
            log(f"Skipping {cid} (already done in AUDIO ONLY)", "WARN")
            channels = [c for c in channels if c != cid]
        elif not get_site(cid):
            log(f"Unknown channel: {cid}", "ERROR")
            sys.exit(1)

    if not channels:
        log("No channels to scrape")
        return

    # Run scrapes
    all_summaries = []
    log(f"Will scrape {len(channels)} channel(s): {', '.join(channels)}")
    log(f"Output root: {OUTPUT_ROOT}")
    log("")

    for cid in channels:
        try:
            summary = scrape_channel(
                cid,
                skip_videos=args.skip_videos,
                item_id=args.item_id,
            )
            all_summaries.append(summary)
        except Exception as e:
            log(f"FATAL error scraping {cid}: {e}", "ERROR")
            traceback.print_exc()
            all_summaries.append({"channel": cid, "error": str(e)})

    # Final summary
    log("=" * 60)
    log("FINAL SUMMARY")
    log("=" * 60)
    total_downloaded = 0
    total_errors = 0
    for s in all_summaries:
        cid = s.get("channel", "?")
        name = s.get("site_name", cid)
        if "error" in s and s.get("indexed", 0) == 0:
            log(f"  {name:35s}  ERROR: {s['error'][:50]}")
        else:
            dl = s.get("downloaded", 0)
            err = s.get("errors", 0)
            idx = s.get("indexed", 0)
            total_downloaded += dl
            total_errors += err
            log(f"  {name:35s}  indexed={idx:4d}  downloaded={dl:4d}  errors={err:3d}")

    log(f"")
    log(f"Total downloaded: {total_downloaded}")
    log(f"Total errors: {total_errors}")
    log(f"Done.")


if __name__ == "__main__":
    main()
