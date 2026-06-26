"""Discord output helpers.

Discord caps a message at 2000 characters. The bot's headline outputs — research briefs,
competitor scans, collated feedback — routinely exceed that, so truncating (the old `[:1900]`)
silently dropped the end of exactly the answers people care about. ``chunk_message`` splits a
long reply into sendable pieces, preferring paragraph then line then word boundaries, and only
hard-splitting a single oversized token as a last resort.
"""

from __future__ import annotations

DISCORD_LIMIT = 2000
# Leave headroom for Discord counting and any prefix the caller adds.
DEFAULT_CHUNK = 1900


def chunk_message(text: str, *, limit: int = DEFAULT_CHUNK) -> list[str]:
    """Split ``text`` into chunks no longer than ``limit``, on the nicest boundary available.

    Always returns at least one chunk (an empty string in, an empty string out) so callers can
    unconditionally send ``chunks[0]``.
    """
    text = text or ""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        # Prefer to break at a paragraph, then a line, then a space — whichever is latest and
        # not too early (avoid tiny chunks from a boundary near the start).
        split = _best_split(window)
        chunks.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def _best_split(window: str) -> int:
    floor = int(len(window) * 0.5)  # don't accept a boundary in the first half — keep chunks full
    for sep in ("\n\n", "\n", " "):
        idx = window.rfind(sep)
        if idx >= floor:
            return idx + len(sep)
    return len(window)  # no good boundary: hard cut at the limit
