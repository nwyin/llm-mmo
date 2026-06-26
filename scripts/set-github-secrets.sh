#!/usr/bin/env bash
# set-github-secrets.sh — upload the GitHub *Actions* secrets this repo needs,
# so the review/action agents can run.
#
# WHERE VALUES COME FROM: if bot/.env exists (created by scripts/make-bot-env.sh),
# each value is read from it so you only enter your secrets ONCE. For anything not
# found in bot/.env (or if there's no .env at all — e.g. you host on Fly), it falls
# back to a hidden prompt. Press Enter on a prompt to skip that secret.
#
# WHAT IT TOUCHES: it calls `gh secret set` to store secrets on your GitHub repo.
# It does NOT print secret values, write them to disk, or pass them as command-
# line arguments to external programs (which would leak via `ps`). Each value is
# read from bot/.env or a hidden prompt and piped straight to `gh` over stdin.
#
# Run it yourself in your terminal (not through an AI agent) so you control where
# the secrets go:
#   bash scripts/set-github-secrets.sh            # uses the repo of the current dir
#   bash scripts/set-github-secrets.sh owner/repo # or target an explicit repo
# Override the env file with: ENV_FILE=/path/to/.env bash scripts/set-github-secrets.sh
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "error: GitHub CLI (gh) is not installed. Run: bash scripts/check-deps.sh" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "error: not logged in to GitHub. Run: gh auth login" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/bot/.env}"

REPO="${1:-}"
if [ -z "$REPO" ]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "error: could not determine the repo. Pass it: bash scripts/set-github-secrets.sh owner/repo" >&2
  exit 1
fi

# read_env KEY — print KEY's value from $ENV_FILE (empty if file/key absent).
# Handles optional surrounding quotes. The value is returned via stdout into a
# shell variable; it is never echoed to the terminal or passed as an external
# program's argument.
read_env() {
  local key="$1" line val
  [ -f "$ENV_FILE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key="*)
        val="${line#"$key"=}"
        case "$val" in
          \"*\") val="${val#\"}"; val="${val%\"}" ;;
          \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        printf '%s' "$val"
        return 0
        ;;
    esac
  done < "$ENV_FILE"
  return 0
}

echo
echo "Uploading GitHub Actions secrets to: $REPO"
if [ -f "$ENV_FILE" ]; then
  echo "(reading from $ENV_FILE; missing values fall back to a hidden prompt)"
else
  echo "(no $ENV_FILE found — values come from hidden prompts; blank input skips)"
fi
echo

# set_secret <SECRET_NAME> <env_key> <required|recommended|optional> <description>
# Looks up <env_key> in bot/.env; if empty, asks via a hidden prompt.
set_secret() {
  local name="$1" env_key="$2" level="$3" desc="$4" value src
  printf '%s (%s)\n  %s\n' "$name" "$level" "$desc"
  value="$(read_env "$env_key")"
  if [ -n "$value" ]; then
    src="from ${ENV_FILE##*/} (${env_key})"
  else
    printf '  value: '
    IFS= read -rs value || true   # -s hides input
    echo
    src="from prompt"
  fi
  if [ -z "$value" ]; then
    if [ "$level" = required ]; then
      echo "  ! skipped a REQUIRED secret — agents won't run without it."
    else
      echo "  – skipped."
    fi
    echo
    unset value
    return 0
  fi
  # Pipe via stdin so the value never appears in argv / process list.
  if printf '%s' "$value" | gh secret set "$name" --repo "$REPO" >/dev/null 2>&1; then
    echo "  ✓ set ($src)."
  else
    echo "  ✗ failed to set $name (check your gh permissions on $REPO)."
  fi
  echo
  unset value
}

# PR_TOKEN reuses the same fine-grained PAT stored as GITHUB_DISPATCH_TOKEN in .env.
set_secret OPENROUTER_API_KEY  OPENROUTER_API_KEY    required \
  "Powers the review + action agents. Same key the bot uses. Starts sk-or-."
set_secret PR_TOKEN            GITHUB_DISPATCH_TOKEN  recommended \
  "Fine-grained PAT (Contents+PR+Actions: write). Lets auto-opened PRs trigger the review workflow. Without it, review won't fire on agent PRs."
set_secret DISCORD_WEBHOOK_URL DISCORD_WEBHOOK_URL    optional \
  "Fixed-channel webhook: finished actions post the PR link to this one channel. Used only if DISCORD_BOT_TOKEN is not set."
set_secret DISCORD_BOT_TOKEN   DISCORD_BOT_TOKEN      optional \
  "Lets finished actions post back to the ORIGINATING channel (wherever the command was invoked) instead of a fixed webhook channel. NOTE: this puts full bot access in CI — skip if you prefer the narrower webhook."

echo "Done. Verify in: Settings → Secrets and variables → Actions, or run:"
echo "  gh secret list --repo $REPO"
