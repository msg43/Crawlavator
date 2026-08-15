#!/usr/bin/env python3
"""
Harvest Eurodollar University YouTube transcript PDFs → _gttp.json files.

Uses the Crawlavator's saved browser session (or re-authenticates) to fetch
the transcripts index page, then downloads each YouTube-section PDF and
converts it to a _gttp.json file importable by GTTP's import-crawlavator.ts.

Usage (from the crawlavator/ directory):
    venv/bin/python3 scripts/harvest_eurodollar_transcripts.py --dry-run
    venv/bin/python3 scripts/harvest_eurodollar_transcripts.py --limit 5
    venv/bin/python3 scripts/harvest_eurodollar_transcripts.py

After running, import with:
    npx tsx scripts/import-crawlavator.ts \\
        --dir "/Volumes/OWC 12TB/PODCASTS" \\
        --api-url "https://www.gttp.app" \\
        --channel "Eurodollar"
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

# Add parent directory to path for Crawlavator imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF not found. Install with: pip install pymupdf")

try:
    from edu_auth import EDUAuth
    from bs4 import BeautifulSoup
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nRun from the crawlavator/ directory with its venv.")

TRANSCRIPTS_URL = "https://www.eurodollar.university/transcripts"
SCRAPE_DATE = "2026-06-08"
DEFAULT_OUT_DIR = "/Volumes/OWC 12TB/PODCASTS/Eurodollar University"

YOUTUBE_MONTH_RE = re.compile(
    r"^(2022|2023|2024|2025)\s+"
    r"(January|February|March|April|May|June|"
    r"July|August|September|October|November|December)$"
)


# ── URL discovery ─────────────────────────────────────────────────────────────

def get_youtube_pdf_urls(email: str, password: str) -> list[dict]:
    """
    Authenticate and scrape the transcripts page.
    Returns list of {section, href} dicts for YouTube-section PDFs only.
    """
    auth = EDUAuth()

    # Try saved session first
    ok, msg = auth.check_auth_status()
    print(f"Auth: {msg}")
    if not ok:
        print(f"Re-authenticating as {email}...")
        ok, msg = auth.login(email, password, headless=True)
        if not ok:
            auth.close()
            sys.exit(f"Login failed: {msg}")
        print(f"Login: {msg}")

    try:
        page = auth.get_page()
        print(f"Fetching: {TRANSCRIPTS_URL}")
        page.goto(TRANSCRIPTS_URL, wait_until="networkidle", timeout=30000)
        html = page.content()
        page.close()
    finally:
        auth.close()

    soup = BeautifulSoup(html, "html.parser")

    links = []
    seen_hrefs: set[str] = set()
    current_heading = ""
    in_youtube_section = False

    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "a"]):
        if el.name in ("h1", "h2", "h3", "h4", "h5"):
            text = el.get_text(strip=True)
            if text == "YouTube Videos":
                in_youtube_section = True
            current_heading = text
        elif el.name == "a" and in_youtube_section:
            href = el.get("href", "")
            # Absolutify
            if href.startswith("/s/"):
                href = f"https://www.eurodollar.university{href}"
            if (
                "/s/" in href
                and href.endswith(".pdf")
                and re.search(r"/s/\d{8}-", href)  # must be a dated YouTube transcript
                and href not in seen_hrefs
            ):
                seen_hrefs.add(href)
                links.append({"section": current_heading, "href": href})

    return links


# ── Text processing ───────────────────────────────────────────────────────────

def parse_date(url: str) -> str:
    m = re.search(r"/s/(\d{4})(\d{2})(\d{2})-", url)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def title_from_url(url: str) -> str:
    stem = url.split("/s/")[-1].replace(".pdf", "")
    stem = re.sub(r"^\d{8}-", "", stem)
    return re.sub(r"\s+", " ", stem.replace("-", " ")).strip()


def slug_from_url(url: str) -> str:
    stem = url.split("/s/")[-1].replace(".pdf", "")
    parts = stem.split("-")
    return "-".join([parts[0]] + [p.lower()[:20] for p in parts[1:5]])


def extract_pdf_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages)


def clean_transcript(raw_text: str, title: str) -> str:
    """
    Strip PDF header boilerplate and wrap in GTTP single-speaker format.

    Two observed PDF layouts:

    Newer (2023+):
      eurodollar.UNIVERSITY
      YouTube Transcript
      [Title]
      [Month DD, YYYY]
      [optional intro paragraph]
      <blank line>
      [auto-transcribed body — often lowercase]

    Older (2022):
      Eurodollar University YouTube
      [Title]
      [Month DD, YYYY]
      <single blank>
      JEFF
      [body]
    """
    # Lines that are ONLY boilerplate (anchored ^ … $)
    SKIP_RE = [
        re.compile(r"^eurodollar[\s\.]*university(\s+youtube)?$", re.I),
        re.compile(r"^youtube\s+transcript$", re.I),
        re.compile(
            r"^(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+\d{1,2},\s+\d{4}$",
            re.I,
        ),
        re.compile(r"^\d{4}-\d{2}-\d{2}$"),
        # Older format bare speaker label
        re.compile(r"^JEFF\s*$"),
    ]
    title_prefix = re.sub(r"\W+", " ", title[:25]).strip().lower()

    body_lines: list[str] = []
    in_header = True
    blank_streak = 0
    saw_header_content = False  # don't exit on blanks until we've seen a real header line

    for line in raw_text.split("\n"):
        stripped = line.strip()
        low = stripped.lower()

        if in_header:
            if not stripped:
                blank_streak += 1
                # Only exit header on 2+ blanks if we've already seen some header content
                if blank_streak >= 2 and saw_header_content:
                    in_header = False
                continue
            blank_streak = 0
            if any(rx.match(stripped) or rx.match(low) for rx in SKIP_RE):
                saw_header_content = True
                continue
            if title_prefix and low.startswith(title_prefix[:18]):
                saw_header_content = True
                continue
            # Check for "Date:" label lines (some PDFs use this format)
            if re.match(r"^(date|transcript)\s*:", stripped, re.I):
                saw_header_content = True
                continue
            in_header = False  # first real content line

        body_lines.append(line)

    body = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines).strip())
    return f"# Jeff Snider\n\n## Jeff Snider\n{body}"


def build_doc(url: str, transcript: str, date: str, title: str) -> dict:
    return {
        "metadata": {
            "id": f"eurodollar_{slug_from_url(url)}",
            "title": title,
            "date": date,
            "url": TRANSCRIPTS_URL,
            "source": "Eurodollar University",
            "source_url": "eurodollar.university",
            "description": "",
            "participants": [{"name": "Jeff Snider", "role": "host"}],
            "tags": [],
            "asset_type": "transcript",
            "has_diarization": False,
            "has_segments": False,
            "segment_count": 0,
            "youtube_video_id": None,
            "provenance": {
                "producer_app": "crawlavator",
                "version": "1.1.0",
                "import_source": "eurodollaruniversity.com",
                "scrape_date": SCRAPE_DATE,
            },
            "site_metadata": {"pdf_url": url},
        },
        "transcript": transcript,
        "segments": [],
        "audioUrl": None,
    }


def out_filename(url: str) -> str:
    stem = url.split("/s/")[-1].replace(".pdf", "")
    safe = re.sub(r"[^\w\-]", "_", stem)
    return f"Eurodollar_{safe}_gttp.json"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Harvest Eurodollar YouTube transcripts → _gttp.json"
    )
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay-ms", type=int, default=300)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--email", default="matt@rainfall.llc")
    parser.add_argument("--password", default="qdlQ9E1tSAh3w*8B")
    args = parser.parse_args()

    links = get_youtube_pdf_urls(args.email, args.password)
    print(f"Found {len(links)} YouTube transcript PDFs")

    if args.limit:
        links = links[: args.limit]

    print(f"Processing {len(links)} | out: {args.out_dir} | dry-run: {args.dry_run}\n")

    ok = skipped = errors = 0

    for i, link in enumerate(links, 1):
        url = link["href"]
        date = parse_date(url)
        title = title_from_url(url)
        out_path = os.path.join(args.out_dir, out_filename(url))

        if not args.overwrite and os.path.exists(out_path):
            print(f"[{i}/{len(links)}] SKIP {date} {title[:50]}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"[{i}/{len(links)}] DRY  {date} {title[:50]}")
            ok += 1
            continue

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()

            raw = extract_pdf_text(pdf_bytes)
            transcript = clean_transcript(raw, title)
            doc = build_doc(url, transcript, date, title)

            os.makedirs(args.out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)

            print(f"[{i}/{len(links)}] OK   {date} {title[:50]}")
            ok += 1

        except Exception as exc:
            print(f"[{i}/{len(links)}] ERR  {date} {title[:50]}: {exc}")
            errors += 1

        if args.delay_ms > 0:
            time.sleep(args.delay_ms / 1000)

    print(f"\nDone: {ok} written, {skipped} skipped, {errors} errors")
    if errors:
        print("Re-run to retry (skips existing unless --overwrite).")


if __name__ == "__main__":
    main()
