# Phase 2 spec — delegation / the research subagent

Goal: add an **isolated research subagent**. A `delegate` tool spins a *fresh* agent loop with
its own message list and a narrow toolset (`search_knowledge`, `read_page`), runs it to
completion, and returns only its distilled brief to the parent. This is hermes-agent's
"isolated subagents with their own conversations" idea, kept minimal.

**Why:** the persona's context stays clean — the child burns tokens exploring the KB; only its
summary reaches the persona. This is exactly the original "research subagent" ask, now sitting
on the Phase 1 loop.

## Reference architecture (hermes-agent, `./hermes-agent/`)
- `tools/delegate_tool.py` — `_build_child_agent()` makes a fresh agent (`skip_memory`,
  `skip_context_files`, narrowed toolset, depth-capped); `_run_single_child()` runs it
  synchronously and returns its `final_response` as the parent's tool result. Read for SHAPE.
  We do **not** need its threading, heartbeat, async/background, or batch machinery — our loop
  is async, so the child is just an awaited `run_agent` call in the same event loop.

## The one enabling change: async tool handlers
Our Phase 1 tool handlers are sync, called directly in the loop. `delegate` must call the async
`run_agent`. Make the loop await awaitable handler results — minimal and idiomatic for our async
loop (also future-proofs web-search later). No threads.

### `bot/agent.py`
- Widen `Tool.handler` type to `Callable[[dict[str, Any]], str | Awaitable[str]]`.
- In `run_agent`'s dispatch, after calling the handler: `if inspect.isawaitable(result): result = await result`. Keep the existing try/except around the whole call+await so a failing child becomes an `"error: …"` tool result (the parent continues).
- Nothing else in the loop changes.

### `bot/tools.py`
- Add `def build_delegate_tool(kb, *, max_files, max_chars, api_key, model, max_iterations) -> Tool`.
  - Its async handler takes `args["goal"]` (a research question/task) and calls:
    `await run_agent(api_key=…, model=…, system_prompt=RESEARCH_SUBAGENT_PROMPT,
      user_message=goal, tools=build_knowledge_tools(kb, …), max_iterations=max_iterations)`
    and returns the child's text.
  - The child gets **only** the knowledge tools (NOT another `delegate`) — this is the depth cap;
    a child cannot spawn further children. Keep it that simple (no depth counter needed).
  - `RESEARCH_SUBAGENT_PROMPT` (module constant in agent.py or tools.py): instruct the child to
    research the knowledge base for the given goal — search, read the most relevant pages, and
    return a concise brief (key findings + the file paths used). No persona voice; it's an
    internal research note for another agent to use.
  - Tool description tells the persona: "Delegate a focused research question to an isolated
    subagent that searches/reads the knowledge base and returns a brief. Use for multi-step or
    broad lookups; for a single quick fact, just use search_knowledge/read_page directly."
  - Params schema: required `goal` string.
- Avoid an import cycle: `tools.py` already imports from `agent`; import `run_agent` there too
  (it's defined in agent.py). Keep it clean.

### Wiring (`bot/__main__.py`)
- In `MMOBot.__init__`, append the delegate tool to `self.tools`:
  `self.tools = build_knowledge_tools(...) + [build_delegate_tool(self.knowledge, max_files=cfg.max_context_files, max_chars=cfg.max_context_chars, api_key=cfg.openrouter_api_key, model=cfg.chat_model, max_iterations=cfg.max_iterations)]`.
- No other handler changes; `_answer`/`/ask` already pass `self.tools`.

### Tests (`bot/tests/test_agent.py`, add cases)
- `delegate` runs a child loop and returns its brief: monkeypatch `agent.complete` with a
  scripted sequence covering BOTH the parent turns and the child turns (the child also calls
  `complete`). Assert the parent's final answer incorporates the child's returned brief, and that
  the child actually invoked a knowledge tool. Fully offline.
- Async-handler dispatch: a trivial async-handler `Tool` returns its value through the loop.

### Acceptance
- `cd bot && uv run pytest -q` green; `uvx ruff check bot && uvx ruff format --check bot` clean.
- `uv --project bot run python -c "import bot.__main__; print('OK')"` prints OK.
- Minimalism preserved: no threads, no depth counter, no new deps.
