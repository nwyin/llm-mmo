# Setup

Three things to wire up: a **Discord application** (the bot), **GitHub secrets** (so the
agents can call the LLM), and a **dispatch token** (so the bot can trigger GitHub Actions).
Budget ~20 minutes.

> **Prefer to be walked through it?** Open this repo in a coding agent (Claude Code / Codex /
> opencode) and ask it to *"help me set this up"* — it loads the **`getting-started`** skill and
> drives the reviewable helper scripts in [`scripts/`](scripts/) (dependency check, secret
> upload, Fly deploy). This page is the manual reference for the same steps. Start with the
> read-only `bash scripts/check-deps.sh`.

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

The bot holds a persistent gateway connection, so it needs an always-on host. Good news: it's
**outbound-only** (it dials Discord's gateway over a WebSocket and receives @mentions and
slash-command events on that connection — it does *not* use Discord's "Interactions Endpoint
URL"). So it needs **no public URL, no open ports, and no reverse proxy**, works behind NAT, and
fits in **256 MB RAM** since the heavy work runs in GitHub Actions.

### Easiest: Fly.io

A worker-shaped [`fly.toml`](fly.toml) is included at the repo root (no `[http_service]` — that's
deliberate; the bot opens no port). Install [`flyctl`](https://fly.io/docs/flyctl/install/), then
from the repo root:

```bash
fly launch --no-deploy        # pick a globally-unique app name + a region (rewrites `app` in fly.toml)
fly secrets set \
    DISCORD_BOT_TOKEN=...      \
    OPENROUTER_API_KEY=sk-or-... \
    GITHUB_DISPATCH_TOKEN=...  \
    GITHUB_REPO=youruser/yourfork \
    DISCORD_GUILD_ID=...       # optional
fly deploy                     # builds bot/Dockerfile from the repo root, starts one machine
fly logs                       # expect: "Logged in as <bot>" + "Synced N slash command(s)"
```

A single `shared-cpu-1x` / 256 MB machine running 24/7 costs roughly a couple dollars a month.

> **The one gotcha** on any PaaS (Fly, Railway, Render…): deploy this as a **worker / background
> service**, never a "web service." A web service expects the app to bind an HTTP port and will
> fail health checks and kill it — the bot never opens one. The bundled `fly.toml` already does
> the right thing.

### Alternatives

- **Docker on any host** (VPS, home box, Raspberry Pi) — build from the **repo root**:
  `docker build -f bot/Dockerfile -t llm-mmo . && docker run --restart=always --env-file bot/.env llm-mmo`
- **systemd / pm2** — run `uv run python -m bot` under a process manager so it restarts on
  crash/reboot.
- **Your laptop**, for testing — it just has to stay awake and online.

The bot serves the `knowledge/` and `personas/` baked into its image/checkout. To refresh them
after merges, redeploy (`fly deploy`) — or, on a long-lived checkout, `git pull` periodically (a
cron entry, or the `pull_interval_seconds` knob in `bot/config.toml`).

---

Stuck? The bot logs to stdout; GitHub Action runs are under the repo's **Actions** tab with
full (key-redacted) logs uploaded as artifacts.
