"""Background knowledge sync: keep the running bot's `knowledge/` fresh after PRs merge.

The bot serves `knowledge/**` from its local checkout, so a merged PR doesn't reach it until
the checkout is updated. This runs `git pull --ff-only` in the repo on an interval and reports
whether anything changed (so the caller can reload the index only when needed).

This is safe ONLY because mutable runtime state lives under STATE_DIR, outside the checkout —
the working tree stays clean, so a fast-forward pull never hits a conflict. Authentication for
private repos is configured at deploy time on the `origin` remote URL (see the Dockerfile
entrypoint), so the bot's git invocation stays credential-agnostic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger("llm-mmo.gitsync")

# (args, cwd) -> (returncode, stdout, stderr). Injectable so tests avoid real git/network.
GitRunner = Callable[[list[str], Path], Awaitable[tuple[int, str, str]]]


async def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def pull_knowledge(repo_root: Path, *, runner: GitRunner | None = None) -> bool:
    """Fast-forward the checkout. Returns True if new commits arrived (caller should reload).

    Never raises: a failed pull (offline, dirty tree, non-FF) is logged and reported as
    "nothing changed" so the loop keeps running on the last-good knowledge.
    """
    run = runner or _run_git
    try:
        code, out, err = await run(["pull", "--ff-only"], repo_root)
    except Exception:  # noqa: BLE001 — git missing / spawn failure must not kill the loop
        log.warning("git pull could not run", exc_info=True)
        return False
    if code != 0:
        log.warning("git pull failed (code %d): %s", code, (err or out).strip()[:300])
        return False
    # `git pull` prints "Already up to date." when there is nothing new.
    return "Already up to date" not in out
