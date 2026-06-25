#!/usr/bin/env bash
# lib.sh — shared helpers for the action/review runners. Source it; don't execute.
#
# Provides: opencode auth setup, a resilient `timeout` wrapper, and a single
# `run_opencode` entry point that streams events to a raw log and extracts the
# final text via extract-output.py.

# Redaction applied to any log content before it could leave the runner.
REDACT='s/(sk-or-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]+)/[redacted]/g'

# Write OpenRouter credentials where opencode expects them (covers local runs;
# CI also writes this, harmlessly idempotent).
setup_opencode_auth() {
  local auth_dir="${HOME}/.local/share/opencode"
  if [ ! -f "$auth_dir/auth.json" ] && [ -n "${OPENROUTER_API_KEY:-}" ]; then
    mkdir -p "$auth_dir"
    printf '{"openrouter":{"type":"api","key":"%s"}}' "$OPENROUTER_API_KEY" > "$auth_dir/auth.json"
    chmod 600 "$auth_dir/auth.json"
  fi
}

# Echo a timeout command prefix into the named array, or nothing if unavailable.
# Usage: resolve_timeout_prefix TIMEOUT_PREFIX 600
resolve_timeout_prefix() {
  local -n _out="$1"
  local seconds="$2"
  _out=()
  if command -v timeout >/dev/null 2>&1; then
    _out=(timeout --kill-after=30s "$seconds")
  elif command -v gtimeout >/dev/null 2>&1; then
    _out=(gtimeout --kill-after=30s "$seconds")
  else
    echo "::warning::no 'timeout' binary found — running without a soft timeout (local run?)." >&2
  fi
}

# run_opencode <agent> <prompt_file> <out_file> <raw_jsonl> <stderr_log> <timeout_seconds>
# Returns opencode's exit code. Writes the extracted final text to <out_file>.
run_opencode() {
  local agent="$1" prompt_file="$2" out_file="$3" raw_jsonl="$4" stderr_log="$5" tmo="$6"
  local script_dir; script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  local tprefix
  resolve_timeout_prefix tprefix "$tmo"

  : > "$raw_jsonl"
  set +e
  ${tprefix[@]+"${tprefix[@]}"} \
    opencode run \
    --agent "$agent" \
    --dangerously-skip-permissions \
    --format json \
    < "$prompt_file" \
    2>"$stderr_log" \
    | tee "$raw_jsonl" \
    | python3 "$script_dir/extract-output.py" \
    > "$out_file"
  local status=("${PIPESTATUS[@]}")
  set -e

  if [ "${status[0]}" -ne 0 ]; then
    echo "::warning::opencode exited ${status[0]} for agent '$agent'. Last events:" >&2
    tail -n 15 "$raw_jsonl" | sed -E "$REDACT" >&2 || true
    sed -E "$REDACT" "$stderr_log" >&2 || true
  fi
  return "${status[0]}"
}
