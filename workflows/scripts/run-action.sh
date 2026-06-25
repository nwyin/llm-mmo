#!/usr/bin/env bash
# run-action.sh — run an action agent that writes to the knowledge base, then open a PR.
#
# Usage: run-action.sh <action>
#
# The action's input is passed via environment variables (set by agent-action.yml from the
# Discord dispatch payload):
#   LINK, NOTE, REQUESTED_BY, CHANNEL_ID
#
# Required env:
#   OPENROUTER_API_KEY   — LLM calls.
#   GH_TOKEN             — token used by `gh` to push + open the PR (PR_TOKEN preferred so the
#                          review workflow fires; falls back to the Actions GITHUB_TOKEN).
#   GITHUB_REPO          — owner/repo.
# Optional env:
#   AGENT_MODEL          — override the agent model.
#   ACTION_TIMEOUT       — soft timeout seconds (default 600).

set -euo pipefail

ACTION="${1:?Usage: run-action.sh <action>}"
if ! [[ "$ACTION" =~ ^[a-z0-9_]+$ ]]; then
  echo "::error::Invalid action name: $ACTION"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOWS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WORKFLOWS_DIR/.." && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

PROMPT_DIR="$WORKFLOWS_DIR/agents/$ACTION"
if [ ! -f "$PROMPT_DIR/PROMPT.md" ]; then
  echo "::error::No agent prompt at $PROMPT_DIR/PROMPT.md — is '$ACTION' registered in actions.toml?"
  exit 1
fi

# Resolve the agent name, human title, and commit paths from actions.toml.
# Defaults: agent id == action id; add_paths == "knowledge/". Tab-separated so the
# title may contain spaces.
IFS=$'\t' read -r AGENT TITLE ADD_PATHS < <(python3 - "$WORKFLOWS_DIR/actions.toml" "$ACTION" <<'PY'
import sys, tomllib
cfg = tomllib.load(open(sys.argv[1], "rb"))
entry = cfg.get(sys.argv[2], {})
agent = entry.get("agent", sys.argv[2])
title = entry.get("title", sys.argv[2])
# add_paths may be a string or a list; normalize to a space-separated string.
paths = entry.get("add_paths", "knowledge/")
if isinstance(paths, list):
    paths = " ".join(paths)
print("\t".join([agent, title, paths]))
PY
)
ADD_PATHS="${ADD_PATHS:-knowledge/}"

# Apply model override (opencode reads OPENCODE_AGENT_<NAME_UPPER>_MODEL).
if [ -n "${AGENT_MODEL:-}" ]; then
  export "OPENCODE_AGENT_$(echo "$AGENT" | tr '[:lower:]' '[:upper:]')_MODEL=$AGENT_MODEL"
fi

WORK_DIR="$WORKFLOWS_DIR/.work"
mkdir -p "$WORK_DIR"
PROMPT_FILE="$WORK_DIR/action-prompt.md"
OUTPUT_FILE="$WORK_DIR/output.md"
RAW_JSONL="$WORK_DIR/raw.jsonl"
STDERR_LOG="$WORK_DIR/stderr.log"

# ---------------------------------------------------------------------------
# Build the task message piped to the agent.
# ---------------------------------------------------------------------------
cat > "$PROMPT_FILE" <<EOF
# Action: $ACTION

A user in Discord requested this action. Carry out your instructions, writing any new files
into the repository, then output your PR description.

## Input
- **link**: ${LINK:-（none）}
- **note**: ${NOTE:-（none）}
- **requested_by**: ${REQUESTED_BY:-unknown}

Today's date is $(date +%Y-%m-%d).
EOF

# ---------------------------------------------------------------------------
# Run the agent from the repo root so it can read/write knowledge/.
# ---------------------------------------------------------------------------
echo "::group::Running action agent '$AGENT'"
setup_opencode_auth
cd "$REPO_ROOT"
export OPENCODE_CONFIG="$WORKFLOWS_DIR/opencode.json"

ACTION_TIMEOUT="${ACTION_TIMEOUT:-600}"
[[ "$ACTION_TIMEOUT" =~ ^[0-9]+$ ]] || ACTION_TIMEOUT=600

run_opencode "$AGENT" "$PROMPT_FILE" "$OUTPUT_FILE" "$RAW_JSONL" "$STDERR_LOG" "$ACTION_TIMEOUT" || true
echo "::endgroup::"

if [ ! -s "$OUTPUT_FILE" ]; then
  echo "::error::Agent produced no output. See logs."
  exit 1
fi

# ---------------------------------------------------------------------------
# Parse PR title/body from the agent's output (first `PR_TITLE:` line).
# ---------------------------------------------------------------------------
PR_TITLE=$(grep -m1 '^PR_TITLE:' "$OUTPUT_FILE" | sed 's/^PR_TITLE:[[:space:]]*//' || true)
[ -n "$PR_TITLE" ] || PR_TITLE="$TITLE"
PR_BODY=$(grep -v '^PR_TITLE:' "$OUTPUT_FILE")

# ---------------------------------------------------------------------------
# Commit & open a PR — only if the agent actually changed files.
# ---------------------------------------------------------------------------
cd "$REPO_ROOT"
# shellcheck disable=SC2086  # ADD_PATHS is intentionally word-split into multiple paths.
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard $ADD_PATHS)" ]; then
  echo "::warning::Agent made no file changes — nothing to commit. Skipping PR."
  echo "AGENT_SUMMARY<<EOF" >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "No changes were produced for action '$ACTION'. $PR_BODY" >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "EOF" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

BRANCH="action/${ACTION}-${GITHUB_RUN_ID:-$(date +%s)}"
git config user.name "llm-mmo-bot"
git config user.email "llm-mmo-bot@users.noreply.github.com"
git switch -c "$BRANCH"
# shellcheck disable=SC2086  # ADD_PATHS is intentionally word-split into multiple paths.
git add -A $ADD_PATHS
git commit -m "$PR_TITLE

Action: $ACTION (requested by ${REQUESTED_BY:-unknown})"
git push -u origin "$BRANCH"

# `gh` uses $GH_TOKEN. Label the PR with the action so review routing can target it.
PR_URL=$(gh pr create \
  --repo "$GITHUB_REPO" \
  --base "${BASE_BRANCH:-main}" \
  --head "$BRANCH" \
  --title "$PR_TITLE" \
  --body "$PR_BODY" \
  --label "agent-pr" 2>/dev/null || gh pr create \
    --repo "$GITHUB_REPO" --base "${BASE_BRANCH:-main}" --head "$BRANCH" \
    --title "$PR_TITLE" --body "$PR_BODY")

echo "Opened PR: $PR_URL"
# Expose results so the workflow can notify Discord.
{
  echo "PR_URL=$PR_URL"
  echo "PR_TITLE=$PR_TITLE"
} >> "${GITHUB_OUTPUT:-/dev/null}"
