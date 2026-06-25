# Setup

Three things to wire up: a **Discord application** (the bot), **GitHub secrets** (so the
agents can call the LLM), and a **dispatch token** (so the bot can trigger GitHub Actions).
Budget ~20 minutes.

---

## 1. Create the Discord application & bot

1. Go to <https://discord.com/developers/applications> → **New Application**. Name it.
2. **Bot** tab → **Add Bot**. Copy the **Token** (you'll set it as `DISCORD_BOT_TOKEN`).
3. Under **Privileged Gateway Intents**, enable **Message Content Intent** — required so the
   bot can read `@mention` messages (not just slash commands).
4. **Installation** (or **OAuth2 → URL Generator**) tab:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Read Message History`, `Use Slash Commands`
   - Open the generated URL and invite the bot to **your** server.
5. Copy your server's **Guild ID** (enable Developer Mode in Discord → right-click server →
   Copy Server ID). Used to register slash commands instantly during development.

## 2. Get an OpenRouter API key

1. Sign up at <https://openrouter.ai> and create a key (Keys tab). It starts with `sk-or-`.
2. This single key powers **both** the Discord chat replies and the GitHub Action agents.

## 3. Create a GitHub dispatch token

The bot triggers GitHub Actions via `repository_dispatch`, which needs a token with write
access to Actions.

- **Fine-grained PAT** (recommended): <https://github.com/settings/tokens?type=beta> →
  repo access = your fork → permissions: **Contents: Read and write**, **Pull requests: Read
  and write**, **Actions: Read and write**.
- Save it as `GITHUB_DISPATCH_TOKEN` in the bot's `.env`.

> **Why a PAT and not the built-in token?** Two reasons. (1) The bot runs outside GitHub, so
> it has no built-in token. (2) A PR opened using the *Actions* built-in `GITHUB_TOKEN` does
> **not** trigger other workflows — so the review job wouldn't fire on auto-created PRs. Having
> the action open the PR with `PR_TOKEN` (a PAT) fixes that. See `workflows/README.md`.

## 4. Set GitHub repository secrets

Settings → Secrets and variables → **Actions** → New repository secret:

| Secret | Required | Purpose |
|--------|----------|---------|
| `OPENROUTER_API_KEY` | ✅ | LLM calls for review + action agents. |
| `PR_TOKEN` | recommended | PAT used to open PRs so the review workflow fires on them. Falls back to `GITHUB_TOKEN` (no downstream review) if unset. |
| `DISCORD_WEBHOOK_URL` | optional | A channel webhook so finished actions post the PR link back to Discord. Create via Discord → channel → Edit → Integrations → Webhooks. |

Optional **Variables** (Settings → Variables → Actions) tune models without code changes:

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_MODEL` | `anthropic/claude-sonnet-4.6` | Model for action + review agents. |
| `MAX_REVIEW_TURNS` | `2` | Cap on review comments per PR. |
| `REVIEW_TIMEOUT` | `600` | Soft timeout (s) for an agent run. |

## 5. Configure & run the bot

```bash
cd bot
cp .env.example .env        # fill in the four values below
uv sync                     # create the venv and install deps
uv run python -m bot        # start the bot
```

`.env` needs:

```
DISCORD_BOT_TOKEN=...        # step 1
DISCORD_GUILD_ID=...         # step 1 (optional; speeds up slash-command registration)
OPENROUTER_API_KEY=sk-or-... # step 2
GITHUB_DISPATCH_TOKEN=...    # step 3
GITHUB_REPO=youruser/yourfork
```

You should see `Logged in as <bot>` and `Synced N slash command(s)`. In your server, try:

- `@YourBot hello` — a chat reply.
- `/ask question: what's in the knowledge base?`
- `/save link: https://youtu.be/dQw4w9WgXcQ note: testing` — watch a PR appear.

## 6. (Production) keep the bot running

The bot holds a persistent gateway connection, so it needs an always-on host. Cheapest paths:

- **A VPS / Fly.io / Railway:** run `uv run python -m bot` under a process manager
  (`systemd`, `pm2`, or the platform's own). A `Dockerfile` stub is in `bot/`.
- **Your laptop**, for testing — it just has to stay awake and online.

The bot reads `knowledge/` from its local checkout. To keep answers fresh after merges, run
`git pull` periodically (a cron entry, or the built-in `pull_interval_seconds` setting in
`bot/config.toml`).

---

Stuck? The bot logs to stdout; GitHub Action runs are under the repo's **Actions** tab with
full (key-redacted) logs uploaded as artifacts.
