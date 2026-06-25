"""Small SQLite transcript store with session boundaries and FTS recall."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  title TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  channel_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def _now(value: float | None) -> float:
    return time.time() if value is None else value


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def current_session(self, channel_id: str, *, now: float | None = None) -> int:
        row = self.conn.execute(
            """
            SELECT id
            FROM sessions
            WHERE channel_id = ? AND ended_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()
        if row is not None:
            return int(row["id"])

        cursor = self.conn.execute(
            "INSERT INTO sessions(channel_id, started_at) VALUES (?, ?)",
            (channel_id, _now(now)),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def new_session(self, channel_id: str, *, now: float | None = None) -> int:
        ts = _now(now)
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE channel_id = ? AND ended_at IS NULL",
                (ts, channel_id),
            )
            cursor = self.conn.execute(
                "INSERT INTO sessions(channel_id, started_at) VALUES (?, ?)",
                (channel_id, ts),
            )
        return int(cursor.lastrowid)

    def log(self, channel_id: str, role: str, content: str, *, now: float | None = None) -> None:
        session_id = self.current_session(channel_id, now=now)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO messages(session_id, channel_id, role, content, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, channel_id, role, content, _now(now)),
            )

    def session_started_at(self, channel_id: str) -> float | None:
        row = self.conn.execute(
            """
            SELECT started_at
            FROM sessions
            WHERE channel_id = ? AND ended_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()
        return None if row is None else float(row["started_at"])

    # The Discord channel is the recall trust boundary: user-facing search is always scoped.
    def search(self, query: str, *, channel_id: str, limit: int = 5) -> list[dict[str, Any]]:
        if channel_id is None:
            raise TypeError("channel_id is required")
        return self._search(query, channel_id=channel_id, limit=limit)

    def search_all_channels(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Cross-channel recall.

        Reserved for privileged/admin use and tests; NEVER wire this to user-facing chat tools — the Discord channel is the
        recall trust boundary.
        """
        return self._search(query, channel_id=None, limit=limit)

    def close(self) -> None:
        self.conn.close()

    def _search(self, query: str, *, channel_id: str | None, limit: int) -> list[dict[str, Any]]:
        if not query.strip() or limit <= 0:
            return []

        try:
            channel_clause = "" if channel_id is None else "AND m.channel_id = ?"
            params: tuple[Any, ...] = (query, limit) if channel_id is None else (query, channel_id, limit)
            rows = self.conn.execute(
                f"""
                SELECT
                  snippet(messages_fts, 0, '[', ']', ' … ', 12) AS snippet,
                  m.role,
                  m.ts,
                  m.channel_id
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?
                  {channel_clause}
                ORDER BY m.ts DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if not _is_fts_query_error(exc):
                raise
            if channel_id is None:
                rows = self._search_like_all_channels(query, limit=limit)
            else:
                rows = self._search_like(query, channel_id=channel_id, limit=limit)

        return [dict(row) for row in rows]

    def _search_like(self, query: str, *, channel_id: str, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
              content AS snippet,
              role,
              ts,
              channel_id
            FROM messages
            WHERE content LIKE ? ESCAPE '\\'
              AND channel_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (f"%{_escape_like(query)}%", channel_id, limit),
        ).fetchall()

    def _search_like_all_channels(self, query: str, *, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
              content AS snippet,
              role,
              ts,
              channel_id
            FROM messages
            WHERE content LIKE ? ESCAPE '\\'
            ORDER BY ts DESC
            LIMIT ?
            """,
            (f"%{_escape_like(query)}%", limit),
        ).fetchall()


def _is_fts_query_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "fts5" in message or "match" in message or "syntax" in message or "unterminated string" in message or "no such column" in message
