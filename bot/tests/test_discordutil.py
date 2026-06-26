"""Message chunking for Discord's 2000-char limit."""

from __future__ import annotations

from discordutil import DEFAULT_CHUNK, chunk_message


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_message("hello") == ["hello"]


def test_empty_text_yields_one_empty_chunk() -> None:
    # Callers send chunks[0] unconditionally, so there must always be at least one.
    assert chunk_message("") == [""]


def test_long_text_splits_under_limit() -> None:
    text = "\n\n".join(f"paragraph {i} " + "x" * 200 for i in range(40))
    chunks = chunk_message(text)

    assert len(chunks) > 1
    assert all(len(c) <= DEFAULT_CHUNK for c in chunks)
    # Nothing is dropped: every paragraph marker survives somewhere.
    assert "paragraph 39" in "".join(chunks)


def test_prefers_paragraph_boundaries() -> None:
    first = "A" * 1000
    second = "B" * 1000
    chunks = chunk_message(first + "\n\n" + second, limit=1100)

    assert chunks[0] == first
    assert chunks[1] == second


def test_hard_splits_an_oversized_token() -> None:
    chunks = chunk_message("Z" * 5000, limit=1000)

    assert len(chunks) == 5
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == "Z" * 5000
