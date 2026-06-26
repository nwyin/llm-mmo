#!/bin/sh
# Container entrypoint for the bot.
#
#  1. Mark the checkout as a safe git directory (it is root-owned in the image).
#  2. Point `origin` at an authenticated HTTPS URL so the background knowledge pull works on
#     PRIVATE repos — token-in-URL keeps the bot's own `git pull` credential-agnostic. No-op
#     when the vars are unset (public repo) or when pull_interval_seconds = 0.
#  3. Exec the bot (PID 1, so signals/restarts behave).
#
# Runtime state is NOT here — it lives on the mounted volume at $STATE_DIR (/data on Fly).
set -e

git config --global --add safe.directory /app 2>/dev/null || true

if [ -n "$GITHUB_DISPATCH_TOKEN" ] && [ -n "$GITHUB_REPO" ]; then
  git -C /app remote set-url origin \
    "https://x-access-token:${GITHUB_DISPATCH_TOKEN}@github.com/${GITHUB_REPO}.git" 2>/dev/null || true
fi

exec uv --project bot run python -m bot
