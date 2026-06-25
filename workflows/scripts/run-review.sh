#!/usr/bin/env bash
# run-review.sh — review a PR to the knowledge base with label-routed agent(s).
#
# Usage: run-review.sh <pr_number> <repo> <base_branch>
#
# Required env: OPENROUTER_API_KEY, GITHUB_TOKEN
# Optional env: PR_LABELS (comma-separated), AGENT_MODEL, MAX_REVIEW_TURNS (default 2),
#               REVIEW_TIMEOUT (default 600)

set -euo pipefail

PR_NUMBER="${1:?Usage: run-review.sh <pr_number> <repo> <base_branch>}"
REPO="${2:?Usage: run-review.sh <pr_number> <repo> <base_branch>}"
BASE_BRANCH="${3:-main}"

[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "::error::Invalid repo: $REPO"; exit 1; }
[[ "$PR_NUMBER" =~ ^[0-9]+$ ]] || { echo "::error::Invalid PR number: $PR_NUMBER"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOWS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WORKFLOWS_DIR/.." && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

WORK_DIR="$WORKFLOWS_DIR/.work"
mkdir -p "$WORK_DIR"

# ---------------------------------------------------------------------------
# 1. Resolve reviewer agents from PR labels via review-routing.toml.
# ---------------------------------------------------------------------------
mapfile -t AGENTS < <(python3 - "$WORKFLOWS_DIR/review-routing.toml" "${PR_LABELS:-}" <<'PY'
import sys, tomllib
cfg = tomllib.load(open(sys.argv[1], "rb"))
labels = [s.strip() for s in sys.argv[2].split(",") if s.strip()]
routes = cfg.get("labels", {})
agents = [routes[l]["agent"] for l in labels if l in routes and "agent" in routes[l]]
if not agents:
    agents = [cfg.get("default", {}).get("agent", "reviewer")]
# de-dupe, preserve order
seen, out = set(), []
for a in agents:
    if a not in seen:
        seen.add(a); out.append(a)
print("\n".join(out))
PY
)
echo "Reviewer agent(s): ${AGENTS[*]}"

# ---------------------------------------------------------------------------
# 2. Turn cap — don't re-review the same PR forever.
# ---------------------------------------------------------------------------
MAX_REVIEW_TURNS="${MAX_REVIEW_TURNS:-2}"
[[ "$MAX_REVIEW_TURNS" =~ ^[0-9]+$ ]] || MAX_REVIEW_TURNS=2
REVIEW_COUNT=$(python3 "$SCRIPT_DIR/post-comment.py" --repo "$REPO" --pr "$PR_NUMBER" --token "$GITHUB_TOKEN" --count 2>/dev/null || echo 0)
REVIEW_COUNT=$(printf '%s' "$REVIEW_COUNT" | grep -oE '^[0-9]+' || echo 0)
if [ "$REVIEW_COUNT" -ge "$MAX_REVIEW_TURNS" ]; then
  echo "Review count ($REVIEW_COUNT) >= max turns ($MAX_REVIEW_TURNS) — skipping."
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Build the diff.
# ---------------------------------------------------------------------------
echo "::group::Extracting diff"
MERGE_BASE=$(git -C "$REPO_ROOT" merge-base "origin/$BASE_BRANCH" HEAD)
DIFF_FILE="$WORK_DIR/full.diff"
git -C "$REPO_ROOT" diff "$MERGE_BASE" HEAD > "$DIFF_FILE"
CHANGED_FILES=$(git -C "$REPO_ROOT" diff "$MERGE_BASE" HEAD --name-only)
FILE_COUNT=$(echo "$CHANGED_FILES" | grep -c . || echo 0)
echo "Changed files: $FILE_COUNT"
echo "::endgroup::"

# ---------------------------------------------------------------------------
# 4. PR metadata.
# ---------------------------------------------------------------------------
PR_DATA=$(curl -sf -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/$REPO/pulls/$PR_NUMBER")
PR_TITLE=$(echo "$PR_DATA" | jq -r '.title // "Untitled"')
PR_BODY=$(echo "$PR_DATA" | jq -r '.body // "No description"')

# ---------------------------------------------------------------------------
# 5. Run each reviewer agent and collect comments.
# ---------------------------------------------------------------------------
setup_opencode_auth
cd "$REPO_ROOT"
export OPENCODE_CONFIG="$WORKFLOWS_DIR/opencode.json"
REVIEW_TIMEOUT="${REVIEW_TIMEOUT:-600}"
[[ "$REVIEW_TIMEOUT" =~ ^[0-9]+$ ]] || REVIEW_TIMEOUT=600

COMBINED="$WORK_DIR/combined-review.md"
: > "$COMBINED"

for AGENT in "${AGENTS[@]}"; do
  if [ -n "${AGENT_MODEL:-}" ]; then
    export "OPENCODE_AGENT_$(echo "$AGENT" | tr '[:lower:]' '[:upper:]')_MODEL=$AGENT_MODEL"
  fi
  PROMPT_FILE="$WORK_DIR/review-prompt-$AGENT.md"
  cat > "$PROMPT_FILE" <<EOF
# Knowledge Base PR Review

## PR
- **#$PR_NUMBER**: $PR_TITLE
- **Files changed**: $FILE_COUNT

## Description
$PR_BODY

## Changed files
\`\`\`
$CHANGED_FILES
\`\`\`

## Diff
The full diff is at \`$DIFF_FILE\`. Read it, then read any changed files you need from the
working tree to judge them. Produce your review comment per your output format.
EOF

  echo "::group::Running reviewer '$AGENT'"
  OUT="$WORK_DIR/review-$AGENT.md"
  run_opencode "$AGENT" "$PROMPT_FILE" "$OUT" "$WORK_DIR/raw-$AGENT.jsonl" "$WORK_DIR/stderr-$AGENT.log" "$REVIEW_TIMEOUT" || true
  echo "::endgroup::"

  if [ -s "$OUT" ] && grep -qF '## Knowledge Review' "$OUT"; then
    [ "${#AGENTS[@]}" -gt 1 ] && printf '> _from agent: %s_\n\n' "$AGENT" >> "$COMBINED"
    cat "$OUT" >> "$COMBINED"
    printf '\n\n' >> "$COMBINED"
  else
    echo "::warning::Reviewer '$AGENT' did not produce a complete review."
  fi
done

# ---------------------------------------------------------------------------
# 6. Post the combined review.
# ---------------------------------------------------------------------------
if [ ! -s "$COMBINED" ]; then
  BODY=$(printf '## Knowledge Review — Error\n\nThe reviewer(s) did not produce a verdict. Check the [Actions logs](https://github.com/%s/actions).' "$REPO")
  python3 "$SCRIPT_DIR/post-comment.py" --repo "$REPO" --pr "$PR_NUMBER" --body "$BODY" --token "$GITHUB_TOKEN"
  exit 1
fi

python3 "$SCRIPT_DIR/post-comment.py" --repo "$REPO" --pr "$PR_NUMBER" --body-file "$COMBINED" --token "$GITHUB_TOKEN"
echo "Review posted to PR #$PR_NUMBER"
