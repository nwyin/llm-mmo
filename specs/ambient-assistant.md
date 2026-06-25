# Ambient Startup-Ops Assistant — Hermes Feature Port

Turn the minimal `bot/` agent loop into an ambiently-available Discord assistant for
early-stage startup ops: web research (market/competitor/client), collating customer
feedback, recalling institutional memory, and making operational knowledge explicit over
time. We port a curated subset of [Hermes](../hermes-agent) features and deliberately leave
the rest out.

## Design decisions (from the interview)

These are invariants for every phase:

- **Web research = `web_search` + `web_extract` only.** No headless browser, no computer-use.
  Provider is pluggable; default to a **keyless** backend (DDGS) so the bot runs and tests
  pass with no API key, with Tavily/Exa selectable via env var.
- **Saving stays PR-gated.** Nothing lands in `knowledge/**` without a pull request. The agent
  may *initiate* a save (a tool that fires `repository_dispatch` and opens a PR) — the gate is
  the PR review, not who triggers it. No direct-write-to-`knowledge/` tool.
- **Two memory layers, different autonomy:**
  - *Agent/operational memory* (`MEMORY.md`, `target=agent`) **and the skill library** are
    background-improvable — tool preferences, "use X not Y" corrections, workflow fixes,
    techniques. Writes are direct (this is the agent's private scratch, not the KB).
  - *User profiles* (`USER.md`, `target=user`) are **never** background-built. In a shared
    workspace "whose profile?" is ambiguous and privacy-sensitive. `target=user` writes stay
    explicit/in-turn (admin-gated as today).
- **Conversation recall stays channel-scoped** by default (existing hard invariant). A
  separate, clearly-named, admin-gated `workspace_recall` adds the cross-channel path.
- **Delegate subagent gets web tools** so "research client X" is one multi-step call.
- **Cron is admin-controlled and in-chat**, jobs persisted to a file, results delivered to a
  Discord channel.

## Explicitly out of scope (ported nothing)

Full Hermes gateway, browser suite, computer-use, voice/TTS, image/video gen, MCP, Honcho,
the weekly skill curator, terminal/code-execution tools, multi-platform adapters,
background-built `USER.md` profiles.

## Verification (all phases, run from `bot/`)

- `uv run pytest -q`
- `uvx ruff check`
- `uvx ruff format --check`

All new modules get unit tests; **no test may hit the network** (mock `httpx`). Line length 144.

---

## Spec 1: Web research (search + extract)

### Requirements

- New `bot/web.py`: a provider-abstracted client with two operations:
  - `web_search(query, *, k)` → ranked results (title, url, snippet).
  - `web_extract(url)` → cleaned page text, truncated to a char budget; optional LLM
    summarization is **out of scope** for this phase (return cleaned text only).
- Provider selection via config/env: default `ddgs` (keyless); `tavily`/`exa` used when
  `WEB_SEARCH_PROVIDER` + the matching API key env var are set. Unknown/misconfigured provider
  → clear error string, never a crash.
- New tools in `bot/tools.py`: `build_web_tools()` returning `web_search` and `web_extract`
  `Tool`s, wired into the main loop in `bot/__main__.py`.
- The `delegate` subagent (`build_delegate_tool`) also receives the web tools, so a delegated
  research goal can search + read the web and the KB, then return a brief.
- New system-prompt guidance string (like `KNOWLEDGE_TOOL_GUIDANCE`) telling the model to
  search the web for external/market/competitor/client questions and to cite URLs.

### Edge cases

- No network / provider error / HTTP non-2xx → tool returns a readable `error: ...` string.
- `web_extract` on a huge page → truncated to the char budget with a `…[truncated]` marker.
- Empty/whitespace query → returns "no results" rather than calling the provider.
- `web_extract` rejects non-`http(s)` URLs.

### Success criteria

- All verification commands pass.
- `tests/test_web.py` covers: result parsing, provider routing, truncation, URL rejection,
  error handling — all with a mocked transport (no real requests).
- A persistent runnable snippet `bot/web_smoke.py` performs one live search+extract when run
  manually (documented as network-dependent; not part of `pytest`).
- Asking the bot an external question (manually) makes it call `web_search`/`web_extract`.

### Ralph Command

/ralph-loop:ralph-loop "Read specs/ambient-assistant.md and implement Spec 1 (web search + extract), keeping all interview design decisions" --max-iterations 30 --completion-promise "All verification commands pass"

---

## Spec 2: Persist & recall institutional knowledge

**Prerequisites:** Spec 1 merged.

### Requirements

- **Agent-initiated PR-gated save.** New tool `save_to_kb(path, title, content, reason)` in
  `bot/tools.py` that fires a `repository_dispatch` (reuse `bot/dispatch.py`) carrying
  agent-generated note content. Add a workflow action (e.g. `save_note`) under
  `workflows/agents/` that writes `knowledge/<path>.md` and opens a PR. The tool's description
  states plainly that it opens a PR for review — it does **not** write the KB directly.
  - Use cases this enables: "save this competitor brief", "collate this customer feedback into
    a note".
- **Cross-channel recall.** New admin-gated tool `workspace_recall(query)` wired to
  `Store.search_all_channels` (already exists). `recall` stays channel-scoped and ungated.
  `workspace_recall` is only added to the toolset for admin users (reuse the `memory_admins`
  gating pattern); non-admins never see it.
- Config knob to enable/disable `workspace_recall` and a clear system-prompt note that it
  searches across channels.

### Edge cases

- `save_to_kb` with a path escaping `knowledge/` (`..`, absolute) → rejected before dispatch.
- Dispatch failure → readable error string, no crash.
- `workspace_recall` requested by a non-admin → not present in their toolset (not just a
  runtime "denied" string).
- Empty query → "no matches", no DB error.

### Success criteria

- All verification commands pass.
- `tests/test_tools.py` (or new `tests/test_persist.py`) covers: path traversal rejection,
  dispatch payload shape (mocked), admin gating of `workspace_recall`, channel vs workspace
  scoping.
- The new `save_note` action has a `PROMPT.md` and is registered like existing actions.

### Ralph Command

/ralph-loop:ralph-loop "Read specs/ambient-assistant.md and implement Spec 2 (PR-gated save_to_kb + admin workspace_recall)" --max-iterations 25 --completion-promise "All verification commands pass"

---

## Spec 3: Self-improvement loop (agent memory + skills)

**Prerequisites:** Specs 1–2 merged.

### Requirements

- **Agent-writable skills.** New tool `skill_manage(action=create|edit|patch|remove, ...)`
  that writes skills to a **runtime skills dir** (e.g. `memory/skills/`), separate from the
  repo-tracked, read-only `.agents/skills`. `SkillLibrary` indexes **both** dirs; `skill_view`
  reads from both. Runtime skills dir is git-ignored.
- **Proactive agent memory.** Allow `remember(target=agent, ...)` without the admin gate and
  add system-prompt guidance to save durable operational facts in-turn. `target=user` writes
  remain admin-gated/manual (unchanged).
- **In-prompt nudges.** Track turns-since-last agent-memory write and iterations-since-last
  skill write (per channel/session). Every N turns (configurable, default 10), inject a
  one-turn reminder to persist operational learnings. Counters reset on the relevant write.
- **Background-review fork.** After a turn completes, spawn a background task that replays the
  turn's transcript through `run_agent` with a tool whitelist of **only** `remember(target=agent)`
  + `skill_manage`. Its prompt asks it to capture repeated corrections (e.g. "use X not Y"),
  tool/workflow preferences, and techniques. It must **never** write `target=user` and must not
  touch the live conversation. A short non-conversational notice (e.g. "💾 learned: …") may be
  posted to the channel. Background failures are swallowed and logged, never surfaced as a
  chat error. Make it toggleable via config (default on) and ensure it cannot fire recursively.

### Edge cases

- Background fork raising → logged, no user-visible error, main reply already sent.
- `skill_manage` writing outside the runtime skills dir → rejected.
- Duplicate/near-duplicate memory adds → fork prompt instructs replace-over-add; enforce the
  existing char limit.
- Nudge must fire at most once per turn and not on the very first turn.
- A fork must not itself trigger another fork.

### Success criteria

- All verification commands pass.
- Tests cover: skill_manage create/edit/patch/remove against a temp runtime dir; dual-dir
  indexing; nudge counter logic (fires at N, resets on write); the fork's tool whitelist
  excludes `target=user` and all non-memory/skill tools; fork errors are isolated.
- The background fork is exercised with a mocked `complete`/`run_agent` (no network).

### Ralph Command

/ralph-loop:ralph-loop "Read specs/ambient-assistant.md and implement Spec 3 (agent-writable skills + nudges + background-review fork scoped to agent-memory & skills, never user profiles)" --max-iterations 40 --completion-promise "All verification commands pass"

---

## Spec 4: Scheduled automations (cron)

**Prerequisites:** Specs 1–3 merged.

### Requirements

- New `bot/cron.py`: a job store persisted to a file (JSON or SQLite under the bot state dir),
  each job = `{id, schedule, prompt, channel_id, persona, created_by, enabled}`. Support cron
  expressions and a few natural-language shortcuts (e.g. "daily 9am", "weekly mon 9am").
- A scheduler that ticks (~every 60s) inside the running bot, finds due jobs, runs each as an
  agent turn (`run_agent` with the normal toolset incl. web), and delivers the result to the
  job's Discord channel. Concurrent ticks must not double-fire a job.
- Admin-gated in-chat `cronjob(action=create|list|delete|pause|resume, ...)` tool. Only
  `memory_admins` may manage jobs.
- Jobs run with the same channel-scoped trust model; a job that wants to save research uses the
  Spec-2 PR-gated `save_to_kb` path (still no unreviewed KB writes).

### Edge cases

- Invalid schedule string → tool returns a readable error, job not created.
- Bot restart → jobs reload from the store and resume; a job whose time passed while down does
  not back-fire a storm (run at most once on catch-up).
- Job agent turn raising → logged, optionally a failure notice to the channel, scheduler keeps
  running.
- Deleting/pausing a job mid-tick is safe.

### Success criteria

- All verification commands pass.
- Tests cover: schedule parsing (cron + shortcuts), due-job selection given a fixed "now",
  persistence round-trip, admin gating, no double-fire. Scheduler logic is tested with an
  injected clock and a mocked `run_agent` (no real timers, no network).
- A persistent runnable snippet demonstrates registering a job and computing its next run.

### Ralph Command

/ralph-loop:ralph-loop "Read specs/ambient-assistant.md and implement Spec 4 (admin-controlled cron scheduler with Discord delivery)" --max-iterations 30 --completion-promise "All verification commands pass"
