#!/usr/bin/env bash
# deploy-bot-fly.sh — deploy the always-on Discord bot to Fly.io.
#
# WHAT IT TOUCHES: creates/uses a Fly.io app, stores the bot's secrets on Fly,
# and deploys a machine — this is the step that can incur Fly charges (a tiny
# shared-cpu-1x/256MB machine is ~a couple dollars/month). Secret values are
# typed into hidden prompts and piped to `fly secrets import` over stdin, never
# as command-line arguments. Nothing is written to disk.
#
# Run it yourself in your terminal:
#   bash scripts/deploy-bot-fly.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"   # fly.toml lives at the repo root; build context must be the root.

if ! command -v fly >/dev/null 2>&1; then
  echo "error: flyctl (fly) is not installed. Run: bash scripts/check-deps.sh" >&2
  exit 1
fi
if ! fly auth whoami >/dev/null 2>&1; then
  echo "error: not logged in to Fly. Run: fly auth login" >&2
  exit 1
fi
if [ ! -f fly.toml ]; then
  echo "error: no fly.toml at repo root. Are you in the right repo?" >&2
  exit 1
fi

echo
echo "Logged in to Fly as: $(fly auth whoami 2>/dev/null)"
echo

# Ensure the app exists. `fly status` reads the app name from fly.toml.
if fly status >/dev/null 2>&1; then
  echo "Using existing Fly app from fly.toml."
else
  echo "No Fly app yet. Running 'fly launch --no-deploy' — pick a UNIQUE name and a"
  echo "region near you. This rewrites the 'app' line in fly.toml. Do NOT add a public"
  echo "service / HTTP port when prompted — the bot is a worker and opens no port."
  echo
  read -r -p "Proceed with 'fly launch --no-deploy'? [y/N] " ok
  case "$ok" in y|Y) fly launch --no-deploy ;; *) echo "Aborted."; exit 1 ;; esac
fi

echo
echo "Now the bot's secrets. Blank input skips that key (e.g. the optional guild id)."
echo "(values are hidden and piped to Fly over stdin — not echoed, not saved)"
echo

ask() { # ask <PROMPT-LABEL> -> sets REPLY_VALUE
  printf '  %s: ' "$1"
  IFS= read -rs REPLY_VALUE || true
  echo
}

ask "DISCORD_BOT_TOKEN (Developer Portal → Bot → Token)";        BOT_TOKEN="$REPLY_VALUE"
ask "OPENROUTER_API_KEY (sk-or-...)";                            OR_KEY="$REPLY_VALUE"
ask "GITHUB_DISPATCH_TOKEN (PAT with Actions: write)";           GH_TOKEN="$REPLY_VALUE"
printf '  %s: ' "GITHUB_REPO (owner/repo to dispatch to)"; IFS= read -r GH_REPO || true
ask "DISCORD_GUILD_ID (optional, for instant slash sync)";       GUILD_ID="$REPLY_VALUE"
unset REPLY_VALUE

# Build the KEY=VALUE stream in-memory and pipe to `fly secrets import`.
{
  [ -n "$BOT_TOKEN" ] && printf 'DISCORD_BOT_TOKEN=%s\n' "$BOT_TOKEN"
  [ -n "$OR_KEY" ]    && printf 'OPENROUTER_API_KEY=%s\n' "$OR_KEY"
  [ -n "$GH_TOKEN" ]  && printf 'GITHUB_DISPATCH_TOKEN=%s\n' "$GH_TOKEN"
  [ -n "$GH_REPO" ]   && printf 'GITHUB_REPO=%s\n' "$GH_REPO"
  [ -n "$GUILD_ID" ]  && printf 'DISCORD_GUILD_ID=%s\n' "$GUILD_ID"
} | fly secrets import
unset BOT_TOKEN OR_KEY GH_TOKEN GH_REPO GUILD_ID
echo "✓ Secrets stored on Fly."

echo
read -r -p "Deploy now with 'fly deploy'? (builds the image, starts the machine) [y/N] " go
case "$go" in
  y|Y)
    fly deploy
    echo
    echo "✓ Deployed. Watch it connect with:  fly logs"
    echo "  Expect: 'Logged in as <bot>' and 'Synced N slash command(s)'."
    ;;
  *)
    echo "Skipped deploy. When ready, run: fly deploy"
    ;;
esac
