"""Store tests. Run with `uv run pytest`."""

from __future__ import annotations

from pathlib import Path

from store import Store


def test_session_lifecycle_creates_rotates_and_reports_started_at(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        first_id = store.current_session("channel-a", now=10.0)

        assert store.current_session("channel-a", now=20.0) == first_id
        assert store.session_started_at("channel-a") == 10.0

        second_id = store.new_session("channel-a", now=30.0)

        assert second_id != first_id
        assert store.current_session("channel-a", now=40.0) == second_id
        assert store.session_started_at("channel-a") == 30.0

        rows = store.conn.execute("SELECT id, started_at, ended_at FROM sessions ORDER BY id").fetchall()
        assert [row["started_at"] for row in rows] == [10.0, 30.0]
        assert rows[0]["ended_at"] == 30.0
        assert rows[1]["ended_at"] is None
    finally:
        store.close()


def test_log_and_search_finds_keyword_with_snippet(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "Where did we leave the launch checklist?", now=100.0)
        store.log("channel-a", "assistant", "The launch checklist still needs DNS and smoke tests.", now=101.0)
        store.log("channel-b", "user", "Unrelated note about pricing.", now=102.0)

        results = store.search("launch", limit=5)

        assert len(results) == 2
        assert results[0]["role"] == "assistant"
        assert results[0]["ts"] == 101.0
        assert "[launch]" in results[0]["snippet"].lower()
        assert results[0]["channel_id"] == "channel-a"
    finally:
        store.close()


def test_search_channel_scope_isolates_results(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "The orbit keyword belongs in channel a.", now=100.0)
        store.log("channel-b", "user", "The orbit keyword belongs in channel b.", now=101.0)

        scoped = store.search("orbit", channel_id="channel-a", limit=5)
        unscoped = store.search("orbit", limit=5)

        assert [row["channel_id"] for row in scoped] == ["channel-a"]
        assert {row["channel_id"] for row in unscoped} == {"channel-a", "channel-b"}
    finally:
        store.close()


def test_search_nonsense_returns_nothing_and_fts_metacharacters_do_not_raise(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "Remember the deployment checklist.", now=200.0)

        assert store.search("no-such-token-for-this-db") == []
        assert store.search('"unterminated AND OR (') == []
    finally:
        store.close()


def test_injected_now_makes_sessions_and_messages_deterministic(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        session_id = store.current_session("channel-a", now=123.5)
        store.log("channel-a", "user", "Deterministic timestamp message.", now=456.5)

        session = store.conn.execute("SELECT id, started_at FROM sessions").fetchone()
        message = store.conn.execute("SELECT session_id, ts FROM messages").fetchone()

        assert session["id"] == session_id
        assert session["started_at"] == 123.5
        assert message["session_id"] == session_id
        assert message["ts"] == 456.5
    finally:
        store.close()
