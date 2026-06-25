# Porting the essentials of hermes-agent into our harness

A plan, distilled from a read of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(2,551 Python files). We are **not** porting hermes. We are porting the small load-bearing
kernel and leaving behind everything that exists to support many platforms, many providers,
many execution backends, and a training-data pipeline.

## The one realization that drives everything

Our bot (`bot/chat.py`) does **single-shot, pre-stuffed retrieval**: keyword `search()` runs
once *before* the model wakes up, and the model is handed whatever fell out. It cannot say
"that's not enough, read the actual page" or "save that for next time" or "what did we decide
last week?" — because it has no turns and no tools.

Every capability you asked for — *on-demand memory, reasoning, context management, new
sessions, the research subagent* — is the same single change underneath:

> **Turn the one chat completion into a tool-calling agent loop.**

Once the model runs a loop and can call tools, each capability is just a tool it decides to
use. OpenRouter's chat-completions endpoint supports tool calling, so **we need neither the
Responses API nor the opencode binary in the bot.** It stays lightweight and in-process.

```
single shot  →   messages = [...]
                 while budget:
                     resp = openrouter(messages, tools)     # the model reasons
                     if resp.tool_calls:
                         run each tool, append results       # search / read / remember / recall / delegate
                         continue
                     return resp.content                     # final Discord reply
```

That loop is ~30 lines. It is the whole port. Everything below hangs off it.

---

## The six layers, in dependency order

Each layer cites where it lives in hermes and what we actually take.

### 1. The agent loop + iteration budget  ← the foundation
- **hermes:** `agent/conversation_loop.py` (the `while` at :589), `agent/iteration_budget.py`
  (a 63-line thread-safe counter), `agent/tool_executor.py` (dispatch).
- **us:** a ~30-line loop in `bot/agent.py`, a tool-name→callable dict, a max-iterations guard.
  Response normalize is `resp.choices[0].message` (OpenRouter). Replaces the body of `chat.py`.
- **Gives us:** reasoning in steps; the substrate for all other tools. **Unlocks the original
  "agentic research" ask by itself** — with just two tools (`search_knowledge`, `read_page`)
  the model researches the KB agentically instead of being spoon-fed keyword hits.

### 2. Tools as the only interface
- The model's entire surface area is a set of tools. Start with:
  `search_knowledge(query)` → ranked page list + snippets, `read_page(path)` → full markdown.
  Later layers add `remember`, `session_search`, `delegate`.
- `knowledge.py`'s existing `search()` becomes the body of the `search_knowledge` tool —
  almost no new code, just exposed to the model instead of run once up front.

### 3. Delegation / subagents  ← this is the "research subagent"
- **hermes:** `tools/delegate_tool.py` — a `delegate_task` tool builds a **fresh agent** with
  its own message list (`skip_memory`, `skip_context_files`), runs it synchronously on a
  thread, returns its `final_response` as the parent's tool result. Depth-capped.
- **us:** one `delegate(goal)` tool that spins a child loop (layer 1) with a narrow toolset and
  an isolated message list, returns a distilled brief. **The research subagent is just a child
  whose tools are `search_knowledge`/`read_page`** — it burns tokens exploring, only its brief
  reaches the persona. Exactly the "isolated subagents with their own conversations" idea, in
  ~40 lines instead of hermes's threaded/async/heartbeat machinery.

### 4. Sessions + context management  ← "manage context, start new sessions"
- **hermes:** `hermes_state.py` — SQLite (`sessions`, `messages`) + FTS5 virtual table with
  auto-maintaining triggers; `session_search` tool for agent-driven cross-session recall
  (not auto-injected); `agent/context_compressor.py` compresses at ~75% of context by
  protecting head+tail and summarizing the middle with one aux-LLM call.
- **us:** one SQLite file. `sessions(id, channel_id, started_at, ended_at, title)` +
  `messages(session_id, role, content, ts, active)` + `messages_fts`. **`channel_id` is the
  session key** (Discord gives us this free — no gateway router needed). `/new` rotates the
  session; resume = newest open session for the channel. A `recall(query)` tool runs FTS5 over
  past messages. Compression: when reported `prompt_tokens` exceeds a threshold, summarize the
  middle, keep head+tail. ~80 lines of SQL+slicing.

### 5. Memory  ← "on-demand manipulate its memories"
- **hermes:** `tools/memory_tool.py` — two flat markdown files, `MEMORY.md` (agent notes) and
  `USER.md` (user profile), entries joined by `§`. One `memory` tool with
  `action ∈ {add, replace, remove}`, substring matching, and an atomic `operations[]` batch.
  Loaded as a **frozen snapshot** into the system prompt at session start (stable for prefix
  caching); mid-session writes hit disk and are picked up next session. A "nudge" every N turns
  prompts the agent to save anything notable.
- **us:** the same — flat files under `memory/` (git-committable → free history/rollback), one
  `remember` tool (add/replace/remove + batch), snapshot-at-session-start injection. Optionally
  point it at our `knowledge/*.md` instead of a separate `MEMORY.md`. Nudge = a periodic system
  line, not a second agent.

### 6. Skills + system-prompt assembly  ← we already have the substrate
- **hermes:** three-tier system prompt — **stable** (identity + skills index, built once,
  cached) / **context** (project files) / **volatile** (memory + timestamp). Skills are
  discovered by walking `SKILL.md` files; a compact name:description **index** goes in the
  stable tier; the model loads a full skill on demand via a `skill_view` tool;
  `skill_manage`/`/learn` lets it author new ones (`agent/learn_prompt.py` has the authoring
  standards verbatim).
- **us:** we **already ship agentskills.io skills** in `.agents/skills/` + `.claude/skills/`.
  So this is mostly free: build the index from those `SKILL.md` files into the stable tier,
  add a `skill_view` tool, reuse the three-tier structure. `/learn` (skill authoring) is a
  nice-to-have that fits our existing convention.

---

## What we deliberately SKIP (and why it's safe to)

| Skipped | Why it exists in hermes / why we don't need it |
|---|---|
| `gateway/` + `BasePlatformAdapter` multi-platform router (5k+ lines) | Telegram/Slack/WhatsApp/Signal/Email. We are Discord-only; `discord.py` directly + `channel_id` as the session key replaces all of it. |
| Provider adapters (`anthropic_`, `bedrock_`, `codex_responses_`, ACP) | One API surface per provider. We use OpenRouter chat-completions only. |
| Voice (`VoiceReceiver`/`VoiceMixer`, RTP/DAVE/Opus, ~600 lines) | Push-to-talk. Out of scope. |
| Honcho / Mem0 / holographic memory plugins | Cloud vector DBs + dialectic user modeling. Flat markdown + our KB lookup is enough. |
| `curator.py` (~1.9k lines) + `curator_backup.py` | Autonomous skill-library reorg + tar backups. Git is our rollback; we won't have hundreds of agent-authored skills. |
| `background_review.py` second-agent fork | Replays the transcript in a forked agent for the nudge. A periodic system line is enough. |
| Context-engine / memory-provider **plugin protocols** | Frameworks for swapping backends. We have one backend each. |
| Prompt-caching adapters, billing/usage, plugin/middleware hooks | Anthropic cache-control, cost tracking, extensibility. None needed internally. |
| `trajectory*.py`, `batch_runner.py`, mini-swe | Training-data generation. Not a runtime feature. |
| SQLite migration chain, multi-process locks, trigram FTS | Production hardening for many writers + CJK. Single-process bot starts fresh. |

---

## What the bot keeps from hermes's Discord adapter (cheap, battle-tested)

From `plugins/platforms/discord/adapter.py`, worth lifting as patterns (not code):
- **Dedup on `message.id`** — Discord RESUME replays events after reconnects; without this you
  double-reply.
- **1900-char chunking** at word boundaries (headroom under the 2000 limit).
- **`AllowedMentions(everyone=False, roles=False)`** — never let an LLM reply ping `@everyone`.
- **Reaction feedback** 👀 → ✅/❌ for in-progress signal.
- **Per-channel agent/session cache** so history + (eventual) prompt cache survive across turns.
- **Background `asyncio.create_task`** so the bot stays responsive during an LLM call.

---

## Proposed build order

1. **[x] Phase 1 — the loop.** `bot/agent.py`: tool-calling loop + iteration budget + tool dict;
   tools `search_knowledge`, `read_page`. Rewire `__main__.py`'s `_answer`/`/ask` to use it.
   *This alone delivers the agentic-research upgrade you originally asked for.*
2. **[x] Phase 2 — delegation.** `delegate` tool → the research subagent as an isolated child.
3. **[x] Phase 3 — sessions + context.** SQLite sessions/messages + FTS5 + `recall` tool + `/new` +
   compression.
   Context compression was intentionally deferred because recent history is already capped.
4. **[x] Phase 4 — memory.** Flat `memory/` files + `remember` tool + nudge.
5. **[x] Phase 5 — skills.** Index our existing `.agents/skills/` into the system prompt +
   `skill_view` (+ optional `/learn`).

Each phase is independently shippable and leaves the bot working. Phase 1 is the foundation and
the highest-leverage single change.

> Note: the hermes clone lives at `./hermes-agent/` for reference and is gitignored — it is not
> part of the template.
