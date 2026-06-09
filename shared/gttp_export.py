"""
Build the single GTTP-ready document from Crawlavator's per-episode data.

GTTP (getreceipts.org) extracts claims from the `transcript`. Its extraction
prompt anchors claim timestamps on inline `[H:MM:SS]` / `[M:SS]` markers and
infers speakers from `## Speaker` markdown headers.

Crawlavator's transcripts are ALREADY diarized (`## Speaker` headers) and ALREADY
carry exact timestamps — but as `(HH:MM:SS)` in parentheses, a format GTTP's
prompt does not recognize (so claim timestamps come out empty). The fix is a
pure reformat: `(HH:MM:SS)` -> `[H:MM:SS]`. Nothing is approximated — these are
the source's own exact timestamps, including multiple within a single segment.

(Note: the per-segment `timestamp_start` field is unreliable — it is frequently
`00:00:00` — so we deliberately do NOT use it. The authoritative timestamps are
the `(HH:MM:SS)` markers inside the transcript/segment text.)

The result is ONE lossless JSON per episode, shaped exactly as GTTP's
/api/import/crawlavator-batch endpoint expects per episode:

    { "metadata": {...}, "transcript": "<normalized>", "segments": [...], "audioUrl": ... }

`metadata` and `segments` are preserved verbatim — nothing from the original
three files is dropped. Only the timestamp punctuation in `transcript` changes.

Shared by:
  - scripts/convert_to_gttp.py  (one-time conversion of already-downloaded episodes)
  - the site plugins (future scrapes can emit this doc directly)
"""

from __future__ import annotations

import re

# Matches an inline `(H:MM:SS)`, `(HH:MM:SS)` or `(MM:SS)` timestamp.
_PAREN_TS = re.compile(r"\((\d{1,2}):(\d{2})(?::(\d{2}))?\)")


def _paren_to_bracket(match: re.Match) -> str:
    a, b, c = match.group(1), match.group(2), match.group(3)
    if c is not None:
        h, m, s = int(a), int(b), int(c)
        return f"[{h}:{m:02d}:{s:02d}]" if h > 0 else f"[{m}:{s:02d}]"
    m, s = int(a), int(b)
    return f"[{m}:{s:02d}]"


def normalize_timestamps(text: str) -> str:
    """Reformat inline `(HH:MM:SS)` timestamps to `[H:MM:SS]` / `[M:SS]` so GTTP's
    extraction prompt anchors claim timestamps on them. Leaves `## Speaker`
    headers and all other text untouched."""
    if not text:
        return ""
    return _PAREN_TS.sub(_paren_to_bracket, text)


def _unwrap(seg: object) -> dict:
    """Segments are stored as {'segment': {...}}; tolerate both nested and flat."""
    if isinstance(seg, dict):
        inner = seg.get("segment")
        if isinstance(inner, dict):
            return inner
        return seg
    return {}


def _transcript_from_segments(segments: list) -> str:
    """Fallback when no transcript.txt exists: stitch the segment texts with
    `## Speaker` headers on speaker change, then normalize timestamps. The
    segment text already contains the exact `(HH:MM:SS)` markers."""
    lines: list[str] = []
    last_speaker = None
    for raw in segments or []:
        seg = _unwrap(raw)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = (seg.get("speaker") or "Unknown").strip() or "Unknown"
        if speaker != last_speaker:
            lines.append(f"\n## {speaker}")
            last_speaker = speaker
        lines.append(text)
    return normalize_timestamps("\n".join(lines).strip())


def _audio_url(metadata: dict):
    site = metadata.get("site_metadata") or {}
    return site.get("download_url") or metadata.get("download_url")


def build_gttp_document(metadata: dict, segments: list, transcript_raw: str | None) -> dict:
    """Produce the single GTTP import payload for one episode.

    Lossless: `metadata` and `segments` pass through verbatim. `transcript` is
    the original transcript with its `(HH:MM:SS)` timestamps reformatted to the
    `[H:MM:SS]` markers GTTP reads (preserving `## Speaker` headers). When no
    transcript text exists, it is stitched from the segments instead.
    """
    if transcript_raw and transcript_raw.strip():
        transcript = normalize_timestamps(transcript_raw)
    elif segments:
        transcript = _transcript_from_segments(segments)
    else:
        transcript = ""
    return {
        "metadata": metadata,
        "transcript": transcript or None,
        "segments": segments or None,
        "audioUrl": _audio_url(metadata),
    }
