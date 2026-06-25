# Phase 3 spec — sessions, persistence, cross-session recall

Goal: give the bot **session boundaries** (`/new`), a **persistent transcript** it can search,
and a **`recall` tool** for cross-session lookup. Today the bot is stateless (Discord is the
store) and history is pulled live from the channel. We keep Discord as the live-history source
but add a small SQLite store for persistence + full-text recall + session boundaries.

**Minimalism note — compression is DEFERRED.** Live history is already hard-capped at
`history_turns`, and Discord holds the full transcript, so there is no context-window pressure
to compress yet. We leave a documented seam (a `summarize_older(...)` stub is NOT required) and
add real compression only when a real limit appears. This is a deliberate simplicity choice.

## Reference architecture (hermes-agent, `./hermes-agent/`)
- `hermes_state.py` — SQLite `sessions` + `messages` tables, FTS5 virtual table maintained by
  triggers, `search_messages()` with `snippet(...)`. Read for the schema + FTS trigger SHAPE.
  We take the minimal subset: one db file, two tables, one FTS table, three triggers. SKIP the
  migration chain, multi-process locks, trigram table, in-place compaction, parent-session
  chains.

## DB location & config
- New `[store]` table in `bot/config.toml`: `path = "state.db"` with a comment (relative to the
  bot dir; gitignored; attach a volume in production to persist). Add `store_path: Path` to
  `Config` (resolve relative to `BOT_DIR`). Default `BOT_DIR / "state.db"`.
- Add `bot/state.db*` to the repo `.gitignore`.

---

## Part 3A — `bot/store.py` (SQLite store) + tests. No wiring.

`bot/store.py` — a small, dependency-free (`sqlite3` stdlib) store. Flat-import style.

Schema (created on first open; `PRAGMA journal_mode=WAL`):
```sql
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
-- triggers to keep messages_fts in sync on INSERT/UPDATE/DELETE (standard external-content FTS5 triggers)
```

`class Store`:
- `__init__(self, path: Path)` — connect (`check_same_thread=False`), `row_factory=sqlite3.Row`,
  create schema. The bot is single-process/async; a module-level connection is fine.
- `current_session(self, channel_id) -> int` — return the open (ended_at IS NULL) session id for
  the channel, creating one (started_at=now) if none. **`now` must be injectable**: accept an
  optional `now: float | None` param (default `time.time()`) so tests are deterministic.
- `new_session(self, channel_id, *, now=None) -> int` — set ended_at=now on the channel's open
  session(s), insert a fresh open session, return its id.
- `log(self, channel_id, role, content, *, now=None) -> None` — insert into messages under the
  channel's current session.
- `session_started_at(self, channel_id) -> float | None` — started_at of the current session.
- `search(self, query, *, limit=5) -> list[dict]` — FTS5 `messages_fts MATCH ?` joined to
  messages; return rows `{snippet, role, ts, channel_id}` using
  `snippet(messages_fts, 0, '[', ']', ' … ', 12)`, newest first. On an FTS syntax error from raw
  user input, fall back to a `LIKE` scan (wrap the query, don't crash).
- `close(self)`.

`bot/tests/test_store.py` (offline, `tmp_path` db):
- session lifecycle: `current_session` creates one; `new_session` ends the old + starts new;
  `session_started_at` reflects the new session.
- `log` + `search`: log a few messages, assert `search` finds one by keyword with a snippet, and
  that a nonsense query returns nothing (and a query with FTS metacharacters doesn't raise).
- determinism via injected `now`.

Acceptance 3A: `cd bot && uv run pytest -q` green; `uvx ruff check bot && uvx ruff format --check bot` clean; no new deps.

---

## Part 3B — wire sessions + recall into the bot (after 3A reviewed)

- `bot/config.py` / `config.toml`: add `store_path` as above.
- `bot/__main__.py`:
  - `__init__`: `self.store = Store(cfg.store_path)`.
  - Log to the store: in `_answer` log the user question (role `"user"`) before the call and the
    reply (role `"assistant"`) after; same for `/ask`. Use the channel id. Keep it best-effort —
    wrap store writes so a store failure never breaks a reply (log + continue).
  - **Session-bounded history**: in `_recent_history`, fetch `started = self.store.session_started_at(channel_id)`
    and skip Discord messages with `created_at` timestamp `< started` (so `/new` gives a clean
    context). Still cap at `history_turns`.
  - **`/new` slash command**: `self.store.new_session(channel_id)`, reply "🧵 Started a fresh
    session — earlier messages won't be used as context (still searchable via the bot)."
  - **`recall` tool**: add `build_recall_tool(store)` in `bot/tools.py` — async or sync handler
    taking `args["query"]`, returns `store.search(query)` formatted as lines `role @ time: snippet`;
    "no earlier matches" if empty. Append it to `self.tools`. Tool description: "Search the bot's
    own past conversations (across sessions) for something discussed before." Give the persona
    this tool alongside the knowledge tools and delegate.
  - Note: the research subagent (delegate child) should NOT get `recall` — keep it knowledge-only.
- `bot/tests/test_agent.py` or a new test: a quick check that `build_recall_tool` returns hits
  from a populated store (can reuse the Store over tmp_path). Offline.

Acceptance 3B: pytest + ruff green; `uv --project bot run python -c "import bot.__main__; print('OK')"` prints OK; `/new` + `recall` wired; store writes are best-effort.
