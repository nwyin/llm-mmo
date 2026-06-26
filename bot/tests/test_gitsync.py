"""Knowledge git-sync: change detection and failure isolation. No real git, no network."""

from __future__ import annotations

import asyncio
from pathlib import Path

from gitsync import pull_knowledge


def _runner(code: int, out: str, err: str = ""):
    async def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
        assert args == ["pull", "--ff-only"]
        return code, out, err

    return run


def test_pull_reports_change_on_new_commits() -> None:
    out = "Updating a1b2c3..d4e5f6\nFast-forward\n knowledge/x.md | 2 +\n"
    assert asyncio.run(pull_knowledge(Path("."), runner=_runner(0, out))) is True


def test_pull_reports_no_change_when_up_to_date() -> None:
    assert asyncio.run(pull_knowledge(Path("."), runner=_runner(0, "Already up to date.\n"))) is False


def test_pull_failure_is_swallowed_as_no_change() -> None:
    assert asyncio.run(pull_knowledge(Path("."), runner=_runner(1, "", "fatal: not a git repository"))) is False


def test_pull_runner_exception_is_swallowed() -> None:
    async def boom(args: list[str], cwd: Path) -> tuple[int, str, str]:
        raise OSError("git binary not found")

    assert asyncio.run(pull_knowledge(Path("."), runner=boom)) is False
