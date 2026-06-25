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


def test_remember_tool_user_writes_restricted_to_admins(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="999", admins=("123",))

    result = tool.handler({"action": "add", "target": "user", "content": "Only admins can write this profile."})

    assert result.startswith("error:")
    assert "Only admins can write this profile." not in memory.snapshot()


def test_remember_tool_agent_writes_are_ungated(tmp_path: Path) -> None:
    # Operational (agent) memory is proactive and open to anyone — that's the whole point.
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="999", admins=("123",))

    result = tool.handler({"action": "add", "target": "agent", "content": "The team prefers terse answers."})

    assert result.startswith("ok:")
    assert "The team prefers terse answers." in memory.snapshot()


def test_remember_tool_allows_admin_user_writes(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="123", admins=("123",))

    result = tool.handler({"action": "add", "target": "user", "content": "Admin-approved profile fact."})

    assert result.startswith("ok:")
    assert "Admin-approved profile fact." in memory.snapshot()


def test_remember_tool_user_writes_disabled_blocks_even_admin(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    tool = build_remember_tool(memory, user_id="123", admins=("123",), allow_user_writes=False)

    result = tool.handler({"action": "add", "target": "user", "content": "Should be blocked."})

    assert result.startswith("error:")
    assert "Should be blocked." not in memory.snapshot()


def test_remember_tool_fires_agent_write_callback(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory", max_chars=2000)
    fired = []
    tool = build_remember_tool(memory, user_id="1", admins=(), on_agent_write=lambda: fired.append(True))

    tool.handler({"action": "add", "target": "agent", "content": "Durable fact."})

    assert fired == [True]
