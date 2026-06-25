"""Background-review fork: scope, write isolation, and result reporting. No network."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import agent
import review
from memory import MemoryStore
from skills import SkillLibrary


def _run_review(monkeypatch, scripted, tmp_path: Path) -> tuple[review.ReviewResult, MemoryStore, list[Any]]:
    memory = MemoryStore(tmp_path / "memory", max_chars=4000)
    skills = SkillLibrary(tmp_path / "curated", runtime_dir=tmp_path / "runtime")
    seen_tools: list[Any] = []
    steps = iter(scripted)

    async def fake_complete(**kwargs: Any) -> dict[str, Any]:
        seen_tools.append(kwargs.get("tools"))
        return next(steps)

    monkeypatch.setattr(agent, "complete", fake_complete)
    result = asyncio.run(
        review.run_background_review(
            api_key="k",
            model="m",
            memory=memory,
            skills=skills,
            transcript=[{"role": "user", "content": "use uv not pip here"}, {"role": "assistant", "content": "ok"}],
        )
    )
    return result, memory, seen_tools


def test_review_only_exposes_memory_and_skill_tools(monkeypatch, tmp_path: Path) -> None:
    _, _, seen_tools = _run_review(monkeypatch, [{"role": "assistant", "content": "Nothing to save."}], tmp_path)

    names = {spec["function"]["name"] for spec in seen_tools[0]}
    assert names == {"remember", "skill_manage"}


def test_review_saves_agent_memory_and_counts_it(monkeypatch, tmp_path: Path) -> None:
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "remember", "arguments": '{"action": "add", "target": "agent", "content": "Use uv not pip."}'},
                }
            ],
        },
        {"role": "assistant", "content": "Saved."},
    ]
    result, memory, _ = _run_review(monkeypatch, scripted, tmp_path)

    assert result.memory_writes == 1
    assert result.saved_anything
    assert "Use uv not pip." in memory.snapshot()
    assert result.notice() and "memory" in result.notice()


def test_review_cannot_write_user_profile(monkeypatch, tmp_path: Path) -> None:
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "remember", "arguments": '{"action": "add", "target": "user", "content": "secret profile"}'},
                }
            ],
        },
        {"role": "assistant", "content": "done"},
    ]
    result, memory, _ = _run_review(monkeypatch, scripted, tmp_path)

    assert result.memory_writes == 0
    assert "secret profile" not in memory.snapshot()


def test_review_reports_nothing_when_idle(monkeypatch, tmp_path: Path) -> None:
    result, _, _ = _run_review(monkeypatch, [{"role": "assistant", "content": "Nothing to save."}], tmp_path)

    assert not result.saved_anything
    assert result.notice() is None
