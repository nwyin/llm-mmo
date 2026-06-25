#!/usr/bin/env bash
# check-deps.sh — report which CLI tools this project uses and whether they're
# installed and authenticated.
#
# SAFE TO RUN: this script is read-only. It does NOT install anything, change
# settings, or touch secrets — it only checks `command -v` and prints the exact
# install command for anything missing. Run it as often as you like.
#
#   bash scripts/check-deps.sh
set -uo pipefail

case "$(uname -s)" in
  Darwin) PLATFORM=macOS ;;
  Linux)  PLATFORM=Linux ;;
  *)      PLATFORM="$(uname -s)" ;;
esac

if [ -t 1 ]; then G='\033[32m'; R='\033[31m'; Y='\033[33m'; B='\033[1m'; X='\033[0m'
else G=''; R=''; Y=''; B=''; X=''; fi

missing_required=0

echo
printf '%bChecking dependencies on %s%b\n' "$B" "$PLATFORM" "$X"
echo "(read-only — nothing is installed or changed)"
echo

# check <cmd> <required|optional> <purpose> <install-macos> <install-linux> <docs>
check() {
  cmd="$1"; level="$2"; purpose="$3"; inst_mac="$4"; inst_linux="$5"; docs="$6"
  if command -v "$cmd" >/dev/null 2>&1; then
    ver="$("$cmd" --version 2>/dev/null | head -1)"
    printf '  %b✓%b %-7s %s\n' "$G" "$X" "$cmd" "$ver"
    return 0
  fi
  if [ "$level" = required ]; then
    printf '  %b✗%b %-7s %bMISSING (required)%b — %s\n' "$R" "$X" "$cmd" "$R" "$X" "$purpose"
    missing_required=$((missing_required + 1))
  else
    printf '  %b•%b %-7s %bnot installed (optional)%b — %s\n' "$Y" "$X" "$cmd" "$Y" "$X" "$purpose"
  fi
  if [ "$PLATFORM" = macOS ]; then printf '      install: %s\n' "$inst_mac"
  else printf '      install: %s\n' "$inst_linux"; fi
  printf '      about:   %s\n' "$docs"
  return 1
}

printf '%bCore (needed to run anything)%b\n' "$B" "$X"
check git required \
  "version control; you clone and commit with it" \
  "brew install git" "sudo apt install git" \
  "https://git-scm.com"
check uv required \
  "Python package/venv manager that runs the bot and its tests" \
  "brew install uv" "curl -LsSf https://astral.sh/uv/install.sh | sh" \
  "https://docs.astral.sh/uv/"
if command -v python3 >/dev/null 2>&1; then
  py="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  printf '  %b✓%b %-7s python %s ' "$G" "$X" python3 "$py"
  case "$py" in 3.1[2-9]|3.[2-9]*) printf '\n' ;;
    *) printf '%b(3.12+ recommended; uv can install it: `uv python install 3.12`)%b\n' "$Y" "$X" ;; esac
else
  printf '  %b•%b %-7s not found — uv can install one: `uv python install 3.12`\n' "$Y" "$X" python3
fi

echo
printf '%bGitHub (to upload secrets and let the bot trigger Actions)%b\n' "$B" "$X"
if check gh required \
  "GitHub CLI — used by set-github-secrets.sh to upload repo secrets" \
  "brew install gh" "see https://github.com/cli/cli#installation" \
  "https://cli.github.com"; then
  if gh auth status >/dev/null 2>&1; then
    printf '      %b✓ authenticated%b (gh auth status)\n' "$G" "$X"
  else
    printf '      %b! not logged in%b — run: gh auth login\n' "$Y" "$X"
  fi
fi

echo
printf '%bHosting the always-on bot (pick ONE path)%b\n' "$B" "$X"
if check fly optional \
  "Fly.io CLI — easiest always-on host (deploy-bot-fly.sh uses it)" \
  "brew install flyctl" "curl -L https://fly.io/install.sh | sh" \
  "https://fly.io/docs/flyctl/"; then
  if fly auth whoami >/dev/null 2>&1; then
    printf '      %b✓ authenticated%b as %s\n' "$G" "$X" "$(fly auth whoami 2>/dev/null)"
  else
    printf '      %b! not logged in%b — run: fly auth login\n' "$Y" "$X"
  fi
fi
check docker optional \
  "alternative host: run the bot in a container anywhere (VPS, Pi, home box)" \
  "https://www.docker.com/products/docker-desktop/" "https://docs.docker.com/engine/install/" \
  "https://docs.docker.com"

echo
if [ "$missing_required" -gt 0 ]; then
  printf '%b%d required tool(s) missing.%b Install the ones marked ✗ above, then re-run this script.\n' "$R" "$missing_required" "$X"
  exit 1
fi
printf '%b✓ All required tools are present.%b Optional tools depend on how you host the bot.\n' "$G" "$X"
echo "Next: open the getting-started skill, or see SETUP.md."
