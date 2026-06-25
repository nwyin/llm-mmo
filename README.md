# LLM MMO

> *Multiple **agents** and multiple **people** collaborating in one server.* A markdown
> knowledge base that an **LLM chatbot in Discord** can read and add to.

A template repo: chat happens in Discord; the heavy "go do work and open a PR" jobs run as
**event-driven GitHub Actions** — the same pattern as a CI code-review bot, pointed at your
knowledge base instead of code.

Fork it, drop in your markdown, set three secrets, and you have a bot your friends can
talk to that turns Discord messages into reviewable pull requests.

## What you get

| Piece | Lives in | What it does |
|-------|----------|--------------|
| **Knowledge base** | `knowledge/**.md` | Your notes. The bot reads these to answer questions. |
| **Personas** | `personas/*.md` | Chatbot characters (system prompts). Tag one in Discord to talk to it. |
| **Discord bot** | `bot/` | Listens for `@mentions` and slash commands. Runs a tool-calling chat loop; dispatches actions to GitHub. |
| **Actions** | `workflows/agents/<name>/` | Agents that *do work* (fetch a thumbnail, write a note) and open a PR. |
| **Review workflows** | `workflows/agents/review/`, `.github/workflows/review.yml` | Agents that review PRs to the knowledge base. Routed by PR label. |

Chat also has persistent sessions (`/new`), long-term memory (`memory/MEMORY.md` + `memory/USER.md`), and repo skills from `.agents/skills`.

## The two flows

**1. Chat (instant, in Discord)**

```
@ResearchBot what thumbnail styles are working for cooking accounts?
  → bot starts an OpenRouter tool loop
      → model may call search_knowledge, read_page, delegate, recall, remember, skill_view
  → replies in the channel
```

**2. Action (async, opens a PR)**

```
/save link:https://youtu.be/dQw4w9WgXcQ note:great hook in first 2s
  → bot fires a repository_dispatch to GitHub
  → agent-action.yml runs the `save_link` agent (opencode)
      → fetches the video's title + thumbnail, writes knowledge/thumbnail-ideas/<slug>.md, commits
  → opens a pull request
  → review.yml runs a reviewer agent on the PR and comments
```

Nothing is written to your knowledge base without a PR. You stay in the loop.

## Architecture

```
Discord ──@mention/chat──► bot ──► OpenRouter agent loop ──► reply
                                  │
                                  ├─► search_knowledge / read_page ──► knowledge/*.md
                                  ├─► delegate ──► isolated research subagent
                                  ├─► recall ──► cross-session SQLite FTS
                                  ├─► remember ──► memory/MEMORY.md + USER.md
                                  └─► skill_view ──► .agents/skills
        ──/save, /ask────► bot ──► repository_dispatch ─┐
                                                        ▼
                                  .github/workflows/agent-action.yml
                                      └─► workflows/scripts/run-action.sh
                                            └─► opencode --agent <action>
                                                  (fetch / write md / commit) ──► opens PR
                                                                                    │
PR opened / labeled ────────────────────────────────────────────────────────────┘
                                  .github/workflows/review.yml
                                      └─► workflows/scripts/run-review.sh
                                            └─► opencode --agent <reviewer>  ──► PR comment
```

Both halves share **one** LLM credential (`OPENROUTER_API_KEY`) and the same agent
runtime ([opencode](https://opencode.ai) over [OpenRouter](https://openrouter.ai)).
Agent behavior is defined entirely by editable markdown prompts.

## Quickstart

**Guided (recommended):** open this repo in a coding agent (Claude Code / Codex / opencode) and
ask it to *"help me set this up."* It loads the **`getting-started`** skill and walks you through
dependencies, tokens, secrets, and deployment — driving the reviewable scripts in
[`scripts/`](scripts/). Start anytime with the read-only check: `bash scripts/check-deps.sh`.

**Manual:** follow the steps below and **[SETUP.md](SETUP.md)**.

1. **Use this template** on GitHub (green "Use this template" button) to make your own repo.
2. **Add secrets** (Settings → Secrets and variables → Actions):
   - `OPENROUTER_API_KEY` — for the review/action agents.
   - (optional) `DISCORD_WEBHOOK_URL` — so actions post the PR link back to a channel.
3. **Run the bot** (see [`bot/README.md`](bot/README.md)) on any always-on machine — your
   laptop to start, a $5 VPS / Fly.io / Railway for real use.
4. **Drop markdown** into `knowledge/` and **personas** into `personas/`. Commit. Done.

Full step-by-step (Discord app creation, intents, tokens) is in **[SETUP.md](SETUP.md)**.

## Extending it

- **New persona:** add `personas/my-bot.md`. It's a system prompt. That's the whole step.
- **New action:** copy `workflows/agents/_template/` to `workflows/agents/<name>/`, edit
  `PROMPT.md`, register it in `workflows/actions.toml`. The full spec with copy-paste snippets
  is the `creating-workflows` skill ([`.claude/skills/creating-workflows/SKILL.md`](.claude/skills/creating-workflows/SKILL.md)).
- **New review behavior:** edit `workflows/agents/review/PROMPT.md`, or add a label route in
  `workflows/review-routing.toml` (e.g. PRs labeled `social` get the `thumbnail_reviewer`).
- **Let an agent build the workflow:** dispatch the `new_action` meta-agent with a plain-English
  description and it scaffolds a new action/reviewer and opens a PR for you to review.

The "how to add a workflow" procedure is also packaged as an [Agent Skill](https://agentskills.io)
(`creating-workflows`, mirrored in `.claude/skills/` and `.agents/skills/`) so Claude Code, Codex,
or opencode running locally in this repo can auto-load it. See [`.claude/skills/README.md`](.claude/skills/README.md).

## Not included (on purpose)

This is a starting point, not a platform. There is **no** remote file store, vector DB, or
plugin system yet — knowledge lives as plain markdown in git, retrieval is keyword-based, and
images are committed straight into the repo. Those are natural next steps, flagged as
`EXTENSION:` comments where they'd plug in.
