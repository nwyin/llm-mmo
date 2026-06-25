# Phase 4 spec — agent-manipulable memory

Goal: let the agent **save and edit durable facts on demand** — "on-demand manipulate its
memories." Two flat markdown files the agent owns; one `remember` tool; a frozen snapshot
injected into the system prompt.

## Reference architecture (hermes-agent, `./hermes-agent/`)
- `tools/memory_tool.py` — two flat files (`MEMORY.md` agent notes, `USER.md` user profile),
  entries joined by `\n§\n`; a single `memory` tool with `action ∈ {add, replace, remove}`,
  substring matching for replace/remove, an atomic `operations[]` batch, per-file char limits,
  and a **frozen snapshot** loaded at session start + injected into the system prompt (writes hit
  disk immediately; the running snapshot is stable for prefix caching; reload next session).
  Take this shape. SKIP: threat-pattern scanner, write-approval gate, drift/file-locking,
  background-review fork, external providers (Honcho/Mem0).

## Storage & config
- Memory lives in a `memory/` dir (configurable). Two files: `MEMORY.md`, `USER.md`. They are
  git-committed content (free history), but **runtime edits on an ephemeral host won't persist
  across redeploys without a volume** — document this in the dir's seed comment, same caveat as
  state.db.
- `bot/config.py` + `config.toml`: add `[memory] dir = "../memory"` → `Config.memory_dir: Path`
  (resolve relative to BOT_DIR; default `REPO_ROOT / "memory"`) and
  `[memory] max_chars = 2000` → `Config.memory_max_chars: int` (per file).
- Create seed files `memory/MEMORY.md` and `memory/USER.md`, each with a short HTML-comment
  header explaining what it is and that the bot edits it via the `remember` tool. These ARE
  committed (not gitignored).

---

## Part 4A — `bot/memory.py` (MemoryStore) + tests. No wiring.

`bot/memory.py`, flat-import style, `from __future__ import annotations`, line-length 144,
stdlib only.

- `TARGETS = {"agent": "MEMORY.md", "user": "USER.md"}`.
- `class MemoryStore`:
  - `__init__(self, dir: Path, *, max_chars: int)` — store dir + limit; `dir.mkdir(parents=True, exist_ok=True)`.
  - `_path(target) -> Path`; raise `ValueError` for an unknown target.
  - `_entries(target) -> list[str]` — read file, split on a `§`-on-its-own-line delimiter, strip,
    drop empties, ignoring any leading HTML-comment header block.
  - `_write(target, entries)` — join entries with `\n\n§\n\n`, preserve the header comment if
    present, atomic write (temp file + os.replace).
  - `add(target, content)` — append an entry; after the op, if total chars > max_chars return an
    error string (do not write); else write and return an ok string.
  - `replace(target, old_text, content)` — find entries containing `old_text` (substring). If
    zero → error "no entry matches …"; if >1 → error listing the matching entries so the caller
    can disambiguate; if exactly 1 → replace it, enforce limit, write.
  - `remove(target, old_text)` — same matching rules; remove the single match.
  - `apply(operations: list[dict])` — atomic batch: apply add/replace/remove in order to an
    in-memory copy, enforce the char limit only against the FINAL state, then write once. Any
    op error aborts the whole batch (return the error, write nothing).
  - `snapshot() -> str` — render both files for the system prompt, e.g.:
    `MEMORY (agent notes):\n<entries or "(empty)">\n\nUSER (profile):\n<entries or "(empty)">`.
    Keep it compact; this is injected verbatim.
- All public mutators return a short human-readable result string (for use as a tool result).

`bot/tests/test_memory.py` (offline, tmp_path):
- add then snapshot contains it; remove by substring; replace by substring; ambiguous
  replace/remove (2 matches) returns the disambiguation error and does not mutate; char-limit
  rejection; batch `apply` is atomic (a failing op in the middle leaves the file unchanged).

Acceptance 4A: pytest + ruff green; no new deps.

---

## Part 4B — `remember` tool + wiring (after 4A reviewed)

- `bot/tools.py`: `build_remember_tool(memory: MemoryStore) -> Tool`. One tool `remember` with
  params: `action` (enum add|replace|remove), `target` (enum agent|user), `content` (string,
  for add/replace), `old_text` (string, for replace/remove), and optional `operations` (array of
  `{action, target?, content?, old_text?}` for atomic batch). Handler: if `operations` given,
  call `memory.apply(...)`; else dispatch on `action`. Return the store's result string. Required:
  at least `action`+`target` (or `operations`). Clear description telling the model to save
  durable facts about the team/project (agent) or the user's preferences (user), and to prefer
  the batch form when consolidating.
- `bot/agent.py`: add `MEMORY_GUIDANCE` constant (concise, hermes prompt_builder tone): you have
  a long-term memory; proactively save durable facts with `remember`; don't save secrets or
  transient chatter.
- `bot/__main__.py`:
  - `__init__`: `self.memory = MemoryStore(cfg.memory_dir, max_chars=cfg.memory_max_chars)`;
    append `build_remember_tool(self.memory)` to `self.tools` (top-level only — delegate child
    stays knowledge-only).
  - Inject the snapshot into the system prompt for replies: where `_answer`/`/ask` build the
    system prompt, append `"\n\n" + agent.MEMORY_GUIDANCE + "\n\n" + self.memory.snapshot()`
    (alongside the existing KNOWLEDGE_TOOL_GUIDANCE). Keep it readable — consider a small helper
    `self._system_prompt(persona_prompt)` that assembles persona + guidance + memory snapshot, and
    use it in both handlers.
  - **Frozen-snapshot semantics**: the snapshot is read fresh each reply via `self.memory.snapshot()`
    (cheap file read) — acceptable and simpler than caching. (We are not optimizing prefix cache
    yet; note this is where you'd freeze it later.)
- Tests: a quick check that `build_remember_tool` add → the snapshot reflects it (tmp dir). Offline.

Acceptance 4B: pytest + ruff green; `uv --project bot run python -c "import bot.__main__; print('OK')"` prints OK; remember tool wired, snapshot in the prompt, delegate child unchanged.
