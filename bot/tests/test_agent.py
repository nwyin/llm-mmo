"""Agent loop tests. Run with `uv run pytest`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import agent
from knowledge import KnowledgeBase
from tools import build_knowledge_tools


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_run_agent_searches_reads_and_returns_final_content(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path, "ideas/cooking.md", "# Cooking\nUse close-up shots and cite this page.")
    _write(tmp_path, "ideas/pricing.md", "# Pricing\nPackage tiers and offers.")
    kb = KnowledgeBase(tmp_path)
    tools = build_knowledge_tools(kb, max_files=3, max_chars=10_000)
    calls: list[list[dict[str, Any]]] = []
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_search",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": '{"query": "cooking thumbnails"}'},
                },
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_read",
                    "type": "function",
                    "function": {"name": "read_page", "arguments": '{"path": "ideas/cooking.md"}'},
                },
            ],
        },
        {"role": "assistant", "content": "Use close-up shots. Cite ideas/cooking.md."},
    ]

    async def fake_complete(**kwargs: Any) -> dict[str, Any]:
        calls.append(list(kwargs["messages"]))
        return scripted[len(calls) - 1]

    monkeypatch.setattr(agent, "complete", fake_complete)

    result = asyncio.run(
        agent.run_agent(
            api_key="test-key",
            model="test-model",
            system_prompt="Answer from knowledge.",
            user_message="What cooking thumbnails work?",
            tools=tools,
        )
    )

    assert result == "Use close-up shots. Cite ideas/cooking.md."
    assert any(message["role"] == "tool" and message["tool_call_id"] == "call_search" for message in calls[1])
    assert any(message["role"] == "tool" and message["tool_call_id"] == "call_read" for message in calls[2])


def test_run_agent_uses_grace_call_when_budget_is_exhausted(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path, "ideas/cooking.md", "# Cooking\nUse close-up shots.")
    tools = build_knowledge_tools(KnowledgeBase(tmp_path), max_files=3, max_chars=10_000)
    calls = 0

    async def fake_complete(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if kwargs["tools"] is None:
            return {"role": "assistant", "content": "Forced final answer."}
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{calls}",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": '{"query": "cooking"}'},
                },
            ],
        }

    monkeypatch.setattr(agent, "complete", fake_complete)

    result = asyncio.run(
        agent.run_agent(
            api_key="test-key",
            model="test-model",
            system_prompt="Answer from knowledge.",
            user_message="What cooking thumbnails work?",
            tools=tools,
            max_iterations=2,
        )
    )

    assert result == "Forced final answer."
    assert calls == 3


def test_read_page_rejects_paths_outside_knowledge_base(tmp_path: Path) -> None:
    tools = build_knowledge_tools(KnowledgeBase(tmp_path), max_files=3, max_chars=10_000)
    read_page = next(tool for tool in tools if tool.name == "read_page")

    assert read_page.handler({"path": "../../etc/passwd"}) == "error: path is outside the knowledge base"
