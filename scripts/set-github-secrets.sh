#!/usr/bin/env bash
# set-github-secrets.sh — upload the GitHub *Actions* secrets this repo needs,
# so the review/action agents can run.
#
# WHAT IT TOUCHES: it calls `gh secret set` to store secrets on your GitHub repo.
# It does NOT print secret values, write them to disk, or pass them as command-
# line arguments (which would leak via `ps`/shell history). Each value is typed
# into a hidden prompt and piped straight to `gh` over stdin. Press Enter on a
# blank prompt to skip a secret.
#
# Run it yourself in your terminal (not through an AI agent) so you control where
# the secrets go:
#   bash scripts/set-github-secrets.sh            # uses the repo of the current dir
#   bash scripts/set-github-secrets.sh owner/repo # or target an explicit repo
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "error: GitHub CLI (gh) is not installed. Run: bash scripts/check-deps.sh" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "error: not logged in to GitHub. Run: gh auth login" >&2
  exit 1
fi

REPO="${1:-}"
if [ -z "$REPO" ]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "error: could not determine the repo. Pass it: bash scripts/set-github-secrets.sh owner/repo" >&2
  exit 1
fi

echo
echo "Uploading GitHub Actions secrets to: $REPO"
echo "(blank input skips a secret; values are never echoed or stored locally)"
echo

# set_secret <NAME> <required|optional> <description>
set_secret() {
  name="$1"; level="$2"; desc="$3"
  printf '%s (%s)\n  %s\n' "$name" "$level" "$desc"
  # -s hides input; -r keeps backslashes literal.
  printf '  value: '
  IFS= read -rs value || true
  echo
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
    echo "  ✓ set."
  else
    echo "  ✗ failed to set $name (check your gh permissions on $REPO)."
  fi
  echo
  unset value
}

set_secret OPENROUTER_API_KEY required \
  "Powers the review + action agents. Same key you'll give the bot. Starts sk-or-."
set_secret PR_TOKEN recommended \
  "Fine-grained PAT (Contents+PR+Actions: write). Lets auto-opened PRs trigger the review workflow. Without it, review won't fire on agent PRs."
set_secret DISCORD_WEBHOOK_URL optional \
  "A channel webhook URL so finished actions post the PR link back to Discord."

echo "Done. Verify in: Settings → Secrets and variables → Actions, or run:"
echo "  gh secret list --repo $REPO"
