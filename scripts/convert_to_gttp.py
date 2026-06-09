#!/usr/bin/env python3
"""
One-time conversion: walk a directory of already-downloaded Crawlavator episodes
(three files each: *_metadata.json, *_transcript.txt, *_segments.json) and write
ONE GTTP-ready *_gttp.json per episode next to the originals.

The single doc is lossless (metadata + segments verbatim) and its `transcript`
is rebuilt with EXACT [H:MM:SS] markers + `## Speaker` headers from the diarized
segments — see shared/gttp_export.py. GTTP imports the *_gttp.json directly.

Usage:
  python3 scripts/convert_to_gttp.py --dir "/Volumes/OWC 12TB/PODCASTS"
  python3 scripts/convert_to_gttp.py --dir "/Volumes/OWC 12TB/PODCASTS" --limit 3 --dry-run
  python3 scripts/convert_to_gttp.py --dir "/Volumes/OWC 12TB/PODCASTS" --overwrite

Flags:
  --dir <path>   (required) root of the downloaded episodes
  --limit <n>    convert at most n episodes (0 = all)
  --dry-run      build + preview, write nothing
  --overwrite    re-write *_gttp.json even if it already exists
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared.gttp_export import build_gttp_document  # noqa: E402


def find_metadata(root: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith("_metadata.json"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_text(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    metas = find_metadata(args.dir)
    print(f"Found {len(metas)} episodes under {args.dir}")

    written = skipped_exists = no_segments = errors = processed = audio_only = 0

    for mp in metas:
        if args.limit and processed >= args.limit:
            break
        prefix = mp[: -len("_metadata.json")]
        out_path = prefix + "_gttp.json"

        if os.path.exists(out_path) and not args.overwrite and not args.dry_run:
            skipped_exists += 1
            continue

        metadata = read_json(mp)
        if not metadata or not metadata.get("id"):
            errors += 1
            continue

        segments = read_json(prefix + "_segments.json")
        transcript = read_text(prefix + "_transcript.txt")
        if not segments:
            no_segments += 1

        doc = build_gttp_document(metadata, segments or [], transcript)

        # Skip transcript-less episodes (e.g. audio-only Eurodollar) — there's
        # nothing to extract; they'd just fail GTTP's empty-transcript gate.
        if not doc.get("transcript"):
            audio_only += 1
            continue

        processed += 1

        if args.dry_run:
            if written < 2:
                preview = (doc.get("transcript") or "")[:500]
                print(f"\n--- {metadata['id']} (segments={len(segments or [])}) ---")
                print(preview)
            written += 1
            continue

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        written += 1

    print(
        f"\n{'DRY RUN — nothing written. ' if args.dry_run else ''}"
        f"Built: {written} | Skipped (exists): {skipped_exists} | "
        f"Audio-only/no-transcript (skipped): {audio_only} | "
        f"No segments (passthrough): {no_segments} | Errors: {errors}"
    )


if __name__ == "__main__":
    main()
