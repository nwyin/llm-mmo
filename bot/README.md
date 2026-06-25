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
| `config.py` | Loads secrets from `.env` and knobs from `config.toml`; finds the repo root. |
| `knowledge.py` | Loads `knowledge/**.md`, keyword-ranks them for a query. |
| `personas.py` | Loads `personas/*.md` system prompts. |
| `chat.py` | One OpenRouter chat-completions call (the only direct LLM call). |
| `dispatch.py` | Fires `repository_dispatch` to trigger a GitHub action agent. |

## How chat works

1. A message mentions the bot (optionally prefixed `persona-id:`).
2. `knowledge.search()` keyword-ranks the notes and returns the top few within a char budget.
3. The persona prompt + retrieved notes + recent channel history go to OpenRouter.
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

It needs to stay connected, so run it on an always-on host. A `Dockerfile` is provided:

```bash
docker build -t llm-mmo bot/ && docker run --env-file bot/.env llm-mmo
```

Or run `uv run python -m bot` under `systemd`/`pm2`/your platform's process manager.
