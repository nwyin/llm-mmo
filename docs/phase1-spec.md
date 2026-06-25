# Phase 1 spec — the tool-calling agent loop

Goal: replace the bot's **single-shot, pre-stuffed** chat (`bot/chat.py`) with a minimal
**tool-calling agent loop**. After this, the model decides what to read instead of being handed
keyword hits. This is the foundation every later phase (delegation, sessions, memory, skills)
hangs off.

**Design principle: minimalism.** This is a small base we will hack on later. No abstraction we
don't need yet. No new dependencies (`httpx` is already present). Mirror the *shape* of
hermes-agent's loop, not its machinery.

## Reference architecture (hermes-agent, cloned at `./hermes-agent/`)

Read these for the *shape*, then write our own ~30-line version. Do not copy code.
- `agent/conversation_loop.py` (~line 589): the core `while` — call LLM → if `tool_calls`,
  append assistant msg + execute tools + append results + continue; else return content.
- `agent/iteration_budget.py`: a tiny counter that caps iterations and prevents runaway loops.
  We need only an `int` max + a final "grace" call with tools disabled to force an answer.
- `agent/tool_executor.py`: dispatch = parse JSON args → call handler → append
  `{"role":"tool","tool_call_id":…,"content":…}`. We need the simple sequential form only.
- Response normalize for OpenRouter chat-completions = `resp["choices"][0]["message"]`.

OpenRouter tool-calling wire format (same as OpenAI):
- request: `tools=[{"type":"function","function":{"name","description","parameters":<JSONSchema>}}]`
- assistant tool call: `message.tool_calls = [{"id","type":"function","function":{"name","arguments":<JSON string>}}]`
- tool result message: `{"role":"tool","tool_call_id":<id>,"content":<string>}`

---

## Part 1A — core loop + knowledge tools (no Discord wiring yet)

Self-contained; must not break the currently-running bot (leave `chat.py` and `__main__.py`
untouched in 1A). New files only + a test.

### `bot/agent.py`
- `OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"`.
- A `Tool` dataclass: `name: str`, `description: str`, `parameters: dict` (JSON Schema for the
  args), `handler: Callable[[dict], str]` (takes parsed args, returns a result string).
- `async def complete(*, api_key, model, messages, tools=None, timeout=60) -> dict` — POSTs to
  OpenRouter (httpx.AsyncClient, headers like `chat.py` incl. `X-Title: llm-mmo`), passing
  `tools` when given, returns `data["choices"][0]["message"]` (the raw assistant message dict,
  which may contain `tool_calls`). Raises `httpx.HTTPError` on transport/HTTP failure.
- `async def run_agent(*, api_key, model, system_prompt, user_message, tools, history=None, max_iterations=6) -> str`:
  - Build `messages = [{"role":"system","content":system_prompt}] + (history or []) + [{"role":"user","content":user_message}]`.
  - Build `tool_specs` from `tools`; build `tool_map = {t.name: t}`.
  - Loop up to `max_iterations`:
    - `msg = await complete(..., tools=tool_specs)`
    - if no `msg.get("tool_calls")`: return `(msg.get("content") or "").strip()`.
    - else append `msg`, then for each tool call: parse `json.loads(arguments or "{}")`,
      look up handler (unknown name → `"error: unknown tool <name>"`), call it inside
      try/except (exception → `f"error: {exc}"`), append the tool-result message. Continue.
  - **Grace call** (budget exhausted, mirrors hermes): one final `complete(..., tools=None)` to
    force a text answer; return its content or a friendly fallback string.
- Keep handlers **synchronous** (search/read are fast, in-process) — call them directly in the
  loop. Do not add async tool support yet.

### `bot/tools.py`
- `def build_knowledge_tools(kb: KnowledgeBase, *, max_files: int, max_chars: int, snippet_chars: int = 400) -> list[Tool]`:
  - `search_knowledge(args)` — `query = args["query"]`; `notes = kb.search(query, k=max_files, max_chars=max_chars)`; return a compact listing, one line per note: `"- <path>\n    <first snippet_chars chars, whitespace-collapsed>"`; if none, return a clear "no matches" string. Params schema: `{"type":"object","properties":{"query":{"type":"string","description":...}},"required":["query"]}`.
  - `read_page(args)` — `path = args["path"]`; **path-safety** (mirror `agent/file_safety.py`):
    `target = (kb.root / path).resolve()`; if not `target.is_relative_to(kb.root.resolve())`
    return `"error: path is outside the knowledge base"`; if not a file return
    `"error: page not found: <path>"`; else return the file text. Params schema: single required
    `path` string described as "repo-relative path under knowledge/, e.g. as returned by search_knowledge".
  - Descriptions must tell the model: search first, then read the most relevant pages in full,
    cite paths.

### `bot/tests/test_agent.py`
- Build a real `KnowledgeBase` over a `tmp_path` with 2–3 `.md` files.
- **Test the happy path** by monkeypatching `agent.complete` with an async stub that returns a
  scripted sequence: (1) a `tool_calls` message calling `search_knowledge`, (2) a `tool_calls`
  message calling `read_page` on a known file, (3) a plain content message. Assert `run_agent`
  returns the final content and that the stub saw `role:"tool"` messages appended.
- **Test budget exhaustion**: stub always returns a `tool_calls` message; assert `run_agent`
  still returns the grace-call content and made exactly `max_iterations + 1` completion calls.
- **Test path safety**: `read_page` with `"../../etc/passwd"` returns the outside-KB error.
- No network, no secrets. Must pass under `uv run pytest` from `bot/`.

### Acceptance for 1A
- `cd bot && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` all pass.
- `chat.py` and `__main__.py` unchanged; the bot still imports/runs as before.

---

## Part 1B — wire into Discord, config, cleanup (done after 1A is reviewed)

- `bot/config.py` + `config.toml`: add `[chat] max_iterations = 6` → `Config.max_iterations: int`.
- `bot/agent.py`: add a `KNOWLEDGE_TOOL_GUIDANCE` constant (short, in the spirit of hermes
  `prompt_builder.py` SKILLS_GUIDANCE): instructs the model to search the knowledge base before
  answering, read the most relevant pages, cite paths, and say so plainly when nothing matches.
- `bot/__main__.py`:
  - Build tools once in `__init__` (`build_knowledge_tools(self.knowledge, …)`).
  - `_answer` and `/ask`: drop the pre-call `self.knowledge.search(...)`/`format_context(...)`;
    instead call `agent.run_agent(system_prompt=persona_prompt + "\n\n" + KNOWLEDGE_TOOL_GUIDANCE,
    user_message=question, tools=self.tools, history=…, max_iterations=cfg.max_iterations)`.
  - Keep the existing error handling (log + friendly message) and the 1900-char reply cap.
- Delete `bot/chat.py` (its OpenRouter call now lives in `agent.complete`); fix imports.
  `format_context` in `knowledge.py` may become unused — leave it (it's harmless and smoke.py
  uses it) or remove its import where dead.
- `smoke.py` still valid (tests retrieval). Optionally add `bot/agent_smoke.py`: runs one
  `run_agent` turn against the real KB, using a stubbed `complete` when `OPENROUTER_API_KEY` is
  unset so it's runnable offline.
- Update `bot/README.md` if it references `chat.py`.

### Acceptance for 1B
- ruff + pytest pass; `uv run python -m bot` still boots (import-level), tools registered.
- A short manual note in the PR: example of the model searching then reading before replying.
