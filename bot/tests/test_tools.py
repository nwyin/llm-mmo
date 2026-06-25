"""Tool security tests. Run with `uv run pytest`."""

from __future__ import annotations

from pathlib import Path

from memory import MemoryStore
from store import Store
from tools import build_recall_tool, build_remember_tool


def test_recall_tool_is_scoped_to_bound_channel(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "The atlas keyword is safe to recall here.", now=100.0)
        store.log("channel-b", "user", "The atlas keyword from channel b is private.", now=101.0)
        recall = build_recall_tool(store, channel_id="channel-a")

        result = recall.handler({"query": "atlas"})

        assert "safe to recall here" in result
        assert "channel b is private" not in result
    finally:
        store.close()


def test_remember_tool_restricts_non_admins_before_mutation(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="999", admins=("123",))

    result = tool.handler({"action": "add", "target": "agent", "content": "Only admins can write this."})

    assert result == "error: memory writes are restricted to admins for this server."
    assert "Only admins can write this." not in memory.snapshot()


def test_remember_tool_allows_admins(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="123", admins=("123",))

    result = tool.handler({"action": "add", "target": "agent", "content": "Admin-approved memory."})

    assert result.startswith("ok:")
    assert "Admin-approved memory." in memory.snapshot()


def test_remember_tool_empty_admins_allows_any_user(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="999", admins=())

    result = tool.handler({"action": "add", "target": "agent", "content": "Open write memory."})

    assert result.startswith("ok:")
    assert "Open write memory." in memory.snapshot()
