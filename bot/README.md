# The Discord bot

A thin front-end: it answers chat from the knowledge base and dispatches actions to GitHub.
It deliberately does **no** repo writes itself — that all happens in GitHub Actions.

## Run it

```bash
cd bot
cp .env.example .env     # fill in DISCORD_BOT_TOKEN, OPENROUTER_API_KEY, GITHUB_DISPATCH_TOKEN, GITHUB_REPO
uv sync                  # create venv + install deps
uv run python -m bot     # start
```

Test it works without Discord:

```bash
uv run pytest            # unit tests for retrieval + persona loading
```

## What each file does

| File | Role |
|------|------|
| `__main__.py` | Discord client: `on_message` (@mentions) + `/ask` and `/save` slash commands. |
| `agent.py` | Minimal OpenRouter tool-calling loop used for chat replies. |
| `tools.py` | Knowledge-base tools: `search_knowledge` and `read_page`. |
| `config.py` | Loads secrets from `.env` and knobs from `config.toml`; finds the repo root. |
| `knowledge.py` | Loads `knowledge/**.md`, keyword-ranks them for a query. |
| `personas.py` | Loads `personas/*.md` system prompts. |
| `dispatch.py` | Fires `repository_dispatch` to trigger a GitHub action agent. |

## How chat works

1. A message mentions the bot (optionally prefixed `persona-id:`).
2. The persona prompt + recent channel history go to the tool-calling agent loop.
3. The model uses `search_knowledge` and `read_page` to find and inspect relevant pages.
4. The reply is posted back in-channel.

## How `/save` works

`/save` (and other entries in `[actions]` of `config.toml`) calls `dispatch.dispatch_action`,
which fires a `repository_dispatch` event. From there it's all GitHub — see
[`../workflows/README.md`](../workflows/README.md). The bot just reports "PR incoming."

## Keeping knowledge fresh

The bot reads `knowledge/` from its local checkout. After PRs merge, pull to update:
set `[knowledge] pull_interval_seconds` in `config.toml` (EXTENSION: wire a `git pull` +
`knowledge.reload()` background task — the reload method already exists), or just `git pull` and
restart.

## Deploy

It needs to stay connected, so run it on an always-on host. It's outbound-only (a gateway
WebSocket — no inbound ports), so it works behind NAT and needs no public URL.

**Fly.io** (easiest always-on) — a ready-to-edit [`fly.toml`](../fly.toml) is at the repo root.
See [SETUP.md §6](../SETUP.md). In short: `fly launch --no-deploy`, `fly secrets set …`, `fly deploy`.

**Docker** — build from the **repo root** (not `bot/`) so `knowledge/` and `personas/` are
included:

```bash
docker build -f bot/Dockerfile -t llm-mmo . && docker run --restart=always --env-file bot/.env llm-mmo
```

**systemd / pm2** — run `uv run python -m bot` under your process manager so it restarts on
crash/reboot.
