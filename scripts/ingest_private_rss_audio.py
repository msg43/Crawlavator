#!/usr/bin/env python3
"""
Ingest Private RSS feed audio files into GTTP via the two-phase GCS upload API.

Flow per file:
  1. Compute MD5 + size (streaming — safe for large files)
  2. GET /api/upload/audio → GTTP returns a signed GCS URL  (Phase 1)
  3. PUT the audio file directly to GCS via the signed URL  (no local creds needed)
  4. POST /api/upload/audio with sidecar JSON  (Phase 2 — creates the job)

Jobs land as status="held" by default; use --auto-process to queue immediately.
A local progress log (~/.gttp_rss_import.jsonl) makes re-runs idempotent.

Usage (from the crawlavator/ directory):
    # Dry-run — show what would be imported:
    venv/bin/python3 scripts/ingest_private_rss_audio.py --dry-run

    # Smoke test — import 5 episodes against local dev:
    venv/bin/python3 scripts/ingest_private_rss_audio.py \\
        --api-url http://localhost:3000 --limit 5

    # One show, prod:
    venv/bin/python3 scripts/ingest_private_rss_audio.py \\
        --api-url https://www.gttp.app --channel "Sam Harris"

    # Full run (1,214 eps, held):
    venv/bin/python3 scripts/ingest_private_rss_audio.py \\
        --api-url https://www.gttp.app

After import, release from the GTTP admin page: /admin → Jobs → filter
source_type=audio → select all → Release.

Rate limit note:
    Prod /api/upload/audio Phase 2 is capped at 20/min.  The default --delay-ms
    3500 keeps the script well under that.  Use --delay-ms 0 against localhost.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_ROOT = "/Volumes/OWC 12TB/PODCASTS/Private RSS Feeds"
DEFAULT_API_URL = "http://localhost:3000"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".mp4"}
PROGRESS_LOG = os.path.expanduser("~/.gttp_rss_import.jsonl")

CONTENT_TYPE_MAP = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp4": "audio/mp4",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_md5(path: str) -> tuple[str, int]:
    """Return (base64_md5, file_size_bytes), streaming to avoid OOM."""
    h = hashlib.md5()
    size = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(65_536):
            h.update(chunk)
            size += len(chunk)
    return base64.b64encode(h.digest()).decode(), size


def load_progress() -> set[str]:
    """Return set of episode IDs already recorded in the progress log."""
    if not os.path.exists(PROGRESS_LOG):
        return set()
    seen: set[str] = set()
    with open(PROGRESS_LOG) as fh:
        for line in fh:
            try:
                seen.add(json.loads(line)["episode_id"])
            except Exception:
                pass
    return seen


def record_progress(episode_id: str, job_id: str, title: str) -> None:
    with open(PROGRESS_LOG, "a") as fh:
        fh.write(json.dumps({"episode_id": episode_id, "job_id": job_id, "title": title}) + "\n")


def find_episodes(root: str, channel_filter: str) -> list[dict]:
    """Walk root for (audio, metadata) pairs, optionally filtered by channel."""
    episodes = []
    for show_name in sorted(os.listdir(root)):
        show_dir = os.path.join(root, show_name)
        if not os.path.isdir(show_dir):
            continue
        if channel_filter and channel_filter.lower() not in show_name.lower():
            continue
        for fname in sorted(os.listdir(show_dir)):
            ext = Path(fname).suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                continue
            audio_path = os.path.join(show_dir, fname)
            stem = fname[: -len(ext)]
            meta_path = os.path.join(show_dir, f"{stem}_metadata.json")
            if not os.path.exists(meta_path):
                continue
            episodes.append({
                "audio_path": audio_path,
                "meta_path": meta_path,
                "show": show_name,
                "filename": fname,
                "ext": ext,
            })
    return episodes


def load_meta(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── Upload phases ─────────────────────────────────────────────────────────────

def gttp_phase1_signed_url(
    api_url: str,
    filename: str,
    content_type: str,
    size: int,
    md5_b64: str,
    session: requests.Session,
) -> dict:
    """GET /api/upload/audio — returns {signedUrl, gcsUri, gcsFilename}."""
    resp = session.get(
        f"{api_url}/api/upload/audio",
        params={
            "filename": filename,
            "contentType": content_type,
            "size": str(size),
            "md5": md5_b64,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def gcs_put_file(
    signed_url: str,
    audio_path: str,
    content_type: str,
    md5_b64: str,
    session: requests.Session,
) -> None:
    """PUT audio file directly to GCS via signed URL (streams, no buffering)."""
    size = os.path.getsize(audio_path)
    with open(audio_path, "rb") as fh:
        resp = session.put(
            signed_url,
            data=fh,
            headers={
                "Content-Type": content_type,
                "Content-MD5": md5_b64,
                "Content-Length": str(size),
            },
            timeout=600,  # 10 min ceiling for very large files
        )
    resp.raise_for_status()


def gttp_phase2_register_job(
    api_url: str,
    gcs_uri: str,
    md5_b64: str,
    size: int,
    meta: dict,
    auto_process: bool,
    session: requests.Session,
) -> dict:
    """
    POST /api/upload/audio (FormData) — creates the processing_jobs row.

    Normalises 'date' → 'episode_date' in the sidecar so GTTP captures it.
    """
    sidecar = {**meta}
    if "date" in sidecar and "episode_date" not in sidecar:
        sidecar["episode_date"] = sidecar["date"]

    resp = session.post(
        f"{api_url}/api/upload/audio",
        data={
            "gcsUri": gcs_uri,
            "md5": md5_b64,
            "size": str(size),
            "channel": meta.get("source", ""),
            "autoProcess": "true" if auto_process else "false",
        },
        files={
            "sidecar": ("metadata.json", json.dumps(sidecar).encode(), "application/json"),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest Private RSS audio into GTTP")
    parser.add_argument("--dir", default=DEFAULT_ROOT)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--channel", default="", help="Filter by show name substring")
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument(
        "--delay-ms", type=int, default=3500,
        help="Pause between Phase-2 calls (ms). 0 = no delay (use with localhost).",
    )
    parser.add_argument(
        "--auto-process", action="store_true",
        help="Create jobs as status=queued (default: held)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    episodes = find_episodes(args.dir, args.channel)
    already_done = load_progress()

    # Filter to not-yet-imported, using the crawlavator id as the stable key
    pending = []
    for ep in episodes:
        meta = load_meta(ep["meta_path"])
        ep["meta"] = meta
        if meta.get("id") not in already_done:
            pending.append(ep)

    print(f"\n=== Private RSS → GTTP Ingest ===")
    print(f"Root:         {args.dir}")
    print(f"API URL:      {args.api_url}")
    print(f"Channel:      {args.channel or '(all)'}")
    print(f"Episodes:     {len(episodes)} total, {len(pending)} not yet imported")
    print(f"Auto-process: {args.auto_process}")
    print(f"Dry run:      {args.dry_run}")
    print()

    if args.dry_run:
        by_show: dict[str, int] = {}
        for ep in pending:
            by_show[ep["show"]] = by_show.get(ep["show"], 0) + 1
        for show, count in sorted(by_show.items()):
            size_mb = sum(
                os.path.getsize(e["audio_path"])
                for e in pending if e["show"] == show
            ) / 1e6
            print(f"  {show}: {count} eps, {size_mb:.0f} MB")
        total_gb = sum(os.path.getsize(e["audio_path"]) for e in pending) / 1e9
        print(f"\nTotal: {len(pending)} episodes, {total_gb:.1f} GB")
        eta_min = len(pending) * (args.delay_ms / 1000 + 5) / 60  # ~5s per upload
        print(f"ETA (rough):  {eta_min:.0f} min at current settings")
        return

    if args.limit:
        pending = pending[: args.limit]

    session = requests.Session()
    session.headers["User-Agent"] = "GTTP-RSS-Ingest/1.0"

    ok = errors = 0
    total = len(pending)

    for i, ep in enumerate(pending, 1):
        meta = ep["meta"]
        episode_id = meta.get("id", "")
        title = meta.get("title", ep["filename"])
        audio_path = ep["audio_path"]
        filename = ep["filename"]
        content_type = CONTENT_TYPE_MAP.get(ep["ext"], "audio/mpeg")

        tag = f"[{i}/{total}]"

        try:
            # Compute MD5 + size (needed for Phase 1 + GCS signed-URL verification)
            md5_b64, size = compute_md5(audio_path)

            # Phase 1: get signed GCS upload URL
            p1 = gttp_phase1_signed_url(
                args.api_url, filename, content_type, size, md5_b64, session
            )

            # Phase 2: upload directly to GCS
            gcs_put_file(p1["signedUrl"], audio_path, content_type, md5_b64, session)

            # Phase 3: register job in GTTP
            result = gttp_phase2_register_job(
                args.api_url, p1["gcsUri"], md5_b64, size, meta,
                auto_process=args.auto_process, session=session,
            )

            job_id = result.get("jobId", "?")
            record_progress(episode_id, job_id, title)
            print(f"{tag} OK   {meta.get('date', '?')} {title[:55]}  → {job_id}")
            ok += 1

        except Exception as exc:
            print(f"{tag} ERR  {title[:55]}: {exc}")
            errors += 1

        if args.delay_ms > 0 and i < total:
            time.sleep(args.delay_ms / 1000)

    print(f"\nDone: {ok} imported, {errors} errors")
    if errors:
        print(f"Re-run to retry failed episodes — progress log: {PROGRESS_LOG}")
    if not args.auto_process and ok > 0:
        print(f"\nJobs created as status=held. Release from admin: /admin → Jobs → source_type=audio")


if __name__ == "__main__":
    main()
