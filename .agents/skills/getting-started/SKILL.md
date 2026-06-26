---
name: getting-started
description: >-
  Walk a new user end-to-end through setting up and deploying this repo: checking/installing CLI
  dependencies (git, uv, gh, fly), creating accounts and tokens (Discord, OpenRouter, GitHub),
  uploading secrets safely, inviting the bot to a server, and deploying it always-on. Use when
  someone is setting this up for the first time or asks how to install, configure, or deploy it.
license: MIT
---

# Getting started — guided setup & deployment

You are helping a user stand up this project from scratch: a Discord bot (chat) plus
event-driven GitHub Action agents (that open PRs). Budget ~20–30 minutes. Walk them through the
steps below **in order**, one at a time, confirming each works before moving on.

## Safety contract (read this first — it governs how you run every step)

Secrets (API keys, bot tokens, PATs) must never pass through you.

- **Never ask the user to paste a secret into the chat, and never type a secret into a command
  yourself.** You don't need to see any secret value to complete this setup.
- The secret-handling scripts (`set-github-secrets.sh`, `deploy-bot-fly.sh`, `make-bot-env.sh`)
  read values from hidden prompts and pipe them straight to `gh`/`fly`. **The user runs those
  themselves** in their own terminal. In Claude Code they can run a command in-session by
  prefixing it with `!` (e.g. `!bash scripts/set-github-secrets.sh`); otherwise they run it in a
  normal terminal.
- **You may** run the read-only `check-deps.sh`, read files, open documentation URLs, and run
  install commands for missing tools (with the user's OK). You may run `gh`/`fly` for
  *non-secret* reads (`gh repo view`, `fly auth whoami`).
- Before the user runs any script, show them its path and offer to display it so they can review
  it first. These scripts are short and commented for exactly this reason.

## What it costs (tell the user up front)

| Service | Cost | Notes |
|---------|------|-------|
| Discord | Free | The bot platform. |
| OpenRouter | **Pay-as-you-go per token** | Powers chat + agents. Have them **set a spend limit** when creating the key. Sonnet-class usage for a small group is typically cents-to-a-few-dollars/month. |
| GitHub Actions | Free tier | Generous free minutes (unlimited on public repos; a monthly allotment on private). The agents run here. |
| Exa (web search) | **Free tier, then pay-as-you-go** | Recommended search backend for the bot's research. Optional — without a key it falls back to keyless DuckDuckGo. |
| Fly.io (if used to host) | **~a couple $/month** | One tiny `shared-cpu-1x`/256MB machine + a small persistent volume, running 24/7. Other hosts (home box, Pi, VPS) can be free/cheaper. |

## Step 0 — Dependencies

Run the read-only checker and read its output together:

```
bash scripts/check-deps.sh
```

For anything marked missing, explain what the tool is (the script prints a one-line purpose and
the install command) and offer to run the install command for them. Re-run until all **required**
tools pass. Only the host you'll actually use needs its optional tool (`fly` for Fly, `docker`
for containers).

## Step 1 — Log in to GitHub

The user runs (it's an interactive browser login):

```
gh auth login
```

Confirm with `gh auth status`.

## Step 2 — Create accounts & generate tokens

Have the user open each link and create the credential. Explain what each is for; do **not**
collect the values — they'll enter them into the scripts later.

1. **Discord application & bot** — <https://discord.com/developers/applications> → New
   Application → **Bot** tab → copy the **Token**. Then:
   - **Bot tab → turn OFF "Public Bot"** (so only they can invite it).
   - **Bot tab → enable "Message Content Intent", then click "Save Changes"** (required to read
     `@mention` text). At their scale this is a free toggle — Discord only requires an
     *application* for privileged intents once an app can reach 10,000+ users (changed June 2026;
     it used to be 100 servers). **If this toggle is off (or Save was skipped), the bot logs in,
     syncs slash commands, then crashes with `discord.errors.PrivilegedIntentsRequired`** — the
     #1 first-run gotcha. If you see that traceback in Step 6, this is the fix.
2. **OpenRouter API key** — <https://openrouter.ai> → Keys → create one (starts `sk-or-`).
   Tell them to **set a spend limit** on the key now. This single key is used in two places
   (GitHub secret + bot host).
3. **GitHub fine-grained PAT** — <https://github.com/settings/tokens?type=beta> → repo access =
   their fork → permissions **Contents: R/W**, **Pull requests: R/W**, **Actions: R/W**. One PAT
   serves as both `PR_TOKEN` (GitHub secret) and `GITHUB_DISPATCH_TOKEN` (bot host).
4. **Exa API key (recommended)** — <https://exa.ai> → sign up → API key. Powers the bot's web
   research (market/competitor/client). This one goes on the **bot host only** (Fly secret or
   local `.env`), *not* in the GitHub Actions secrets. Optional: without it the bot falls back to
   keyless DuckDuckGo, which is rate-limited and lower quality — fine for a quick try, worth the
   key for a real test.

## Step 3 — Upload the GitHub Actions secrets

The user runs (offer to show them the script first):

```
bash scripts/set-github-secrets.sh
```

It uploads `OPENROUTER_API_KEY` (required), `PR_TOKEN` (recommended; reuses the same fine-grained
PAT stored as `GITHUB_DISPATCH_TOKEN`), and `DISCORD_WEBHOOK_URL` (optional) to their repo via
`gh`. **It sources values from `bot/.env`** when that file exists (so secrets are entered only
once), and falls back to a hidden prompt for anything missing. Verify with `gh secret list`.

> **Order tip for the local-host path:** since `set-github-secrets.sh` reads from `bot/.env`, run
> **Step 5's `make-bot-env.sh` first** — then this step needs no typing at all. On the Fly path
> there's no local `.env`, so this script just prompts (hidden) for each value, as before.

## Step 4 — Invite the bot to their server

In the Developer Portal → **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`;
bot permissions `Send Messages`, `Read Message History`, `Use Slash Commands`. They open the
generated URL, pick their server (they need **Manage Server** there — owners have it), and
authorize. The bot appears offline until it's running. No Discord approval/verification is
needed at personal scale.

## Step 5 — Deploy the always-on bot

The bot must stay connected. It's **outbound-only** (no public port), so any always-on host works.

**Fly.io (recommended)** — the user runs (offer to show the script and `fly.toml` first):

```
fly auth login          # if check-deps showed "not logged in"
bash scripts/deploy-bot-fly.sh
```

It runs `fly launch --no-deploy` (if no app yet — remind them **not** to add a public/HTTP
service; the bot is a worker), **creates the `llm_mmo_data` persistent volume** (the bot stores
recall, memory, cron jobs, and skills there — without it every restart wipes them), prompts for
the bot's secrets (including the optional `EXA_API_KEY`) over stdin, and deploys. Keep it to one
machine — `fly scale count 1` — since the bot is single-instance.

**Local (just testing)** — instead of a host: `bash scripts/make-bot-env.sh` writes a gitignored
`bot/.env` (it also asks for the optional `EXA_API_KEY` and `DISCORD_WEBHOOK_URL`), then
`cd bot && uv sync && uv run python -m bot`. Running this **before** Step 3 means
`set-github-secrets.sh` picks up `OPENROUTER_API_KEY`/`PR_TOKEN`/`DISCORD_WEBHOOK_URL` straight
from `bot/.env` with no re-typing.

**One config edit worth doing before the test:** set `[admins].ids` in `bot/config.toml` to their
own Discord user id. Privileged features (scheduled cron jobs, cross-channel recall, editing the
bot's skills, per-user profile memory) are **off** until an admin is listed — this is fail-closed
by design.

## Step 6 — Verify

- `fly logs` (or local console) should show **`Logged in as <bot>`** and
  **`Synced N slash command(s)`**.
- In Discord: `@TheBot hello` (chat reply), `/ask question: ...`, and `/save link: <url>` —
  watch a pull request appear in their repo, then the review workflow comment on it.

**Most common first-run failure:** the bot logs in, prints `Synced N slash command(s)`, then
crashes with `discord.errors.PrivilegedIntentsRequired`. That means the **Message Content Intent**
is off — send them to the **Bot** tab, toggle it on, **click Save Changes**, and restart. (It's
*not* a bad token: a token error fails earlier, before the sync line.)

If something else fails, point them at `SETUP.md` (full reference), `scripts/README.md` (what each
script touches), and `workflows/README.md` (the Actions side).
