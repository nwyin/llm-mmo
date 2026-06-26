# Setup scripts

Small, single-purpose helpers for first-time setup. **Read each one before you run it** — they're
short and commented on purpose. The guided walkthrough that ties them together is the
`getting-started` skill (your coding agent loads it when you ask how to set up); this folder is
what that skill drives.

| Script | What it does | Safe to run? |
|--------|--------------|--------------|
| `check-deps.sh` | Reports which CLIs (`git`, `uv`, `gh`, `fly`, …) are installed + authenticated, with install commands for any that aren't. | **Read-only.** Installs/changes nothing. Run anytime. |
| `set-github-secrets.sh` | Uploads the GitHub **Actions** secrets (`OPENROUTER_API_KEY`, `PR_TOKEN`, …) via `gh secret set`. | Writes secrets to *your* GitHub repo. No charges. |
| `deploy-bot-fly.sh` | Creates/uses a Fly.io app, **creates the persistent state volume**, stores the bot's secrets on Fly, and deploys the always-on bot. | **Can incur Fly charges** (~a couple $/mo for one tiny machine + a small volume). |
| `make-bot-env.sh` | Writes `bot/.env` from prompts, for running the bot **locally** instead of on a host. | Writes a gitignored plaintext secrets file to your disk. |

## How secrets are handled

These scripts are deliberately careful, because secret hygiene is easy to get wrong:

- **Never passed as command-line arguments.** Values typed as args show up in `ps` output and
  your shell history. Instead, every secret is read from a **hidden prompt** (`read -rs`) and
  piped to `gh`/`fly` over **stdin**.
- **Never echoed or logged**, and (except the intentional local `bot/.env`) **never written to
  disk**.
- **Run them yourself**, in your own terminal — not through an AI agent — so the values only ever
  pass through tools you can see. (In Claude Code you can run a command in-session by prefixing it
  with `!`.)

## Tokens you'll generate (all created in a browser, then pasted into a prompt)

| Token | Where | Used as |
|-------|-------|---------|
| Discord bot token | Developer Portal → your app → Bot | `DISCORD_BOT_TOKEN` (bot host) |
| OpenRouter API key | <https://openrouter.ai> → Keys (set a spend limit!) | `OPENROUTER_API_KEY` (GitHub secret **and** bot host) |
| GitHub fine-grained PAT | <https://github.com/settings/tokens?type=beta> (Contents + Pull requests + Actions: **write**) | `PR_TOKEN` (GitHub secret) **and** `GITHUB_DISPATCH_TOKEN` (bot host) — one PAT covers both |
| Exa API key (recommended) | <https://exa.ai> → API key | `EXA_API_KEY` (**bot host only** — not a GitHub secret) for web research; falls back to keyless DuckDuckGo if unset |

See `SETUP.md` for the full account/intent walkthrough and `fly.toml` for the deploy config.
