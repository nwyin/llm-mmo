"""MemoryStore tests. Run with `uv run pytest`."""

from __future__ import annotations

from pathlib import Path

from memory import MemoryStore
from tools import build_remember_tool


def _store(tmp_path: Path, *, max_chars: int = 2000) -> MemoryStore:
    return MemoryStore(tmp_path, max_chars=max_chars)


def test_add_then_snapshot_contains_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = store.add("agent", "Deploys use Fly volumes for durable runtime edits.")

    assert result.startswith("ok:")
    assert "Deploys use Fly volumes" in store.snapshot()
    assert "USER (profile):\n(empty)" in store.snapshot()


def test_remove_by_substring(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("agent", "Keep launch notes brief.")
    store.add("agent", "DNS still needs verification.")

    result = store.remove("agent", "launch notes")

    assert result.startswith("ok:")
    snapshot = store.snapshot()
    assert "Keep launch notes brief." not in snapshot
    assert "DNS still needs verification." in snapshot


def test_replace_by_substring(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("user", "User prefers verbose updates.")

    result = store.replace("user", "verbose", "User prefers concise updates.")

    assert result.startswith("ok:")
    snapshot = store.snapshot()
    assert "User prefers concise updates." in snapshot
    assert "User prefers verbose updates." not in snapshot


def test_ambiguous_replace_returns_candidates_and_does_not_mutate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("agent", "Alpha note mentions shared token.")
    store.add("agent", "Beta note mentions shared token.")
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    result = store.replace("agent", "shared token", "Replacement")

    assert "multiple entries match" in result
    assert "Alpha note mentions shared token." in result
    assert "Beta note mentions shared token." in result
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == before


def test_ambiguous_remove_returns_candidates_and_does_not_mutate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("user", "Prefers status before edits.")
    store.add("user", "Prefers status after verification.")
    before = (tmp_path / "USER.md").read_text(encoding="utf-8")

    result = store.remove("user", "Prefers status")

    assert "multiple entries match" in result
    assert "Prefers status before edits." in result
    assert "Prefers status after verification." in result
    assert (tmp_path / "USER.md").read_text(encoding="utf-8") == before


def test_char_limit_rejection_does_not_write(tmp_path: Path) -> None:
    store = _store(tmp_path, max_chars=10)

    result = store.add("agent", "this is too long")

    assert "exceed 10 chars" in result
    assert not (tmp_path / "MEMORY.md").exists()


def test_batch_apply_atomicity_on_mid_batch_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("agent", "Original entry.")
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    result = store.apply(
        [
            {"action": "add", "target": "agent", "content": "First staged entry."},
            {"action": "replace", "target": "agent", "old_text": "missing", "content": "Never written."},
            {"action": "add", "target": "agent", "content": "Also never written."},
        ]
    )

    assert "no entry matches" in result
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == before


def test_preserves_leading_html_comment_header_on_write(tmp_path: Path) -> None:
    path = tmp_path / "MEMORY.md"
    path.write_text("<!--\nSeed header.\n-->\n\nOld entry.", encoding="utf-8")
    store = _store(tmp_path)

    store.add("agent", "New entry.")

    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!--\nSeed header.\n-->")
    assert "Old entry." in text
    assert "New entry." in text


def test_remember_tool_add_updates_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tool = build_remember_tool(store, user_id="123", admins=())

    result = tool.handler({"action": "add", "target": "agent", "content": "Remember deploy volumes for memory persistence."})

    assert result.startswith("ok:")
    assert "Remember deploy volumes for memory persistence." in store.snapshot()
