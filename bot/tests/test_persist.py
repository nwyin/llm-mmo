"""Persist + recall tests: PR-gated save_to_kb and admin-gated workspace_recall."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import dispatch
from store import Store
from tools import _validate_kb_path, build_save_to_kb_tool, build_workspace_recall_tool


def _save_tool() -> Any:
    return build_save_to_kb_tool(token="t", repo="o/r", action="save_note", requested_by="u1", channel_id="c1")


def test_validate_kb_path_rejects_traversal_and_absolute() -> None:
    assert _validate_kb_path("../secrets.md").startswith("error:")
    assert _validate_kb_path("/etc/passwd.md").startswith("error:")
    assert _validate_kb_path("~/notes.md").startswith("error:")
    assert _validate_kb_path("a/../../b.md").startswith("error:")
    assert _validate_kb_path("notes\\win.md").startswith("error:")
    assert _validate_kb_path("clients/acme.txt").startswith("error:")
    assert _validate_kb_path("").startswith("error:")
    assert _validate_kb_path("clients/acme.md") is None
    assert _validate_kb_path("brief.md") is None


def test_save_to_kb_rejects_bad_path_before_dispatch(monkeypatch) -> None:
    called = False

    async def fake_dispatch(**kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(dispatch, "dispatch_action", fake_dispatch)
    result = asyncio.run(_save_tool().handler({"path": "../evil.md", "content": "x"}))

    assert result.startswith("error:")
    assert called is False


def test_save_to_kb_requires_content(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "dispatch_action", lambda **k: None)
    result = asyncio.run(_save_tool().handler({"path": "ok.md", "content": "   "}))
    assert result.startswith("error:")


def test_save_to_kb_dispatches_expected_payload(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_dispatch(**kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(dispatch, "dispatch_action", fake_dispatch)
    result = asyncio.run(_save_tool().handler({"path": "clients/acme.md", "title": "Acme", "content": "# Acme\nbody", "reason": "research"}))

    assert result.startswith("ok:")
    assert seen["action"] == "save_note"
    assert seen["repo"] == "o/r"
    payload = seen["payload"]
    assert payload["path"] == "clients/acme.md"
    assert payload["content"] == "# Acme\nbody"
    assert payload["requested_by"] == "u1"
    assert payload["channel_id"] == "c1"


def test_save_to_kb_surfaces_dispatch_failure(monkeypatch) -> None:
    async def boom(**kwargs: Any) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(dispatch, "dispatch_action", boom)
    result = asyncio.run(_save_tool().handler({"path": "ok.md", "content": "body"}))
    assert result.startswith("error:")
    assert "network down" in result


def test_workspace_recall_searches_across_channels(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "The atlas roadmap was decided in channel a.", now=100.0)
        store.log("channel-b", "user", "The atlas budget lives in channel b.", now=101.0)
        tool = build_workspace_recall_tool(store)

        result = tool.handler({"query": "atlas"})

        assert "channel a" in result
        assert "channel b" in result
        assert "[channel-a]" in result
        assert "[channel-b]" in result
    finally:
        store.close()


def test_workspace_recall_empty_query_returns_no_matches(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        tool = build_workspace_recall_tool(store)
        assert tool.handler({"query": ""}) == "no matches across channels"
    finally:
        store.close()
