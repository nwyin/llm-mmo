"""Agent loop tests. Run with `uv run pytest`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import agent
from knowledge import KnowledgeBase
from store import Store
from tools import build_delegate_tool, build_knowledge_tools, build_recall_tool


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


def test_delegate_runs_isolated_child_and_returns_brief(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path, "team/roadmap.md", "# Roadmap\nPhase 2 adds delegate for broad KB research.")
    kb = KnowledgeBase(tmp_path)
    tools = build_knowledge_tools(kb, max_files=3, max_chars=10_000) + [
        build_delegate_tool(
            kb,
            max_files=3,
            max_chars=10_000,
            api_key="test-key",
            model="test-model",
            max_iterations=4,
        )
    ]
    calls: list[dict[str, Any]] = []

    async def fake_complete(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        messages = kwargs["messages"]
        system_prompt = messages[0]["content"]
        if system_prompt == agent.RESEARCH_SUBAGENT_PROMPT:
            if not any(message.get("role") == "tool" for message in messages):
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "child_search",
                            "type": "function",
                            "function": {"name": "search_knowledge", "arguments": '{"query": "phase 2 delegate"}'},
                        },
                    ],
                }
            return {"role": "assistant", "content": "Key finding: delegate is Phase 2. Paths used: team/roadmap.md."}

        if not any(message.get("role") == "tool" and message.get("tool_call_id") == "parent_delegate" for message in messages):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "parent_delegate",
                        "type": "function",
                        "function": {"name": "delegate", "arguments": '{"goal": "Research Phase 2 delegation."}'},
                    },
                ],
            }
        return {"role": "assistant", "content": "Phase 2 is delegate-based research: delegate is Phase 2."}

    monkeypatch.setattr(agent, "complete", fake_complete)

    result = asyncio.run(
        agent.run_agent(
            api_key="test-key",
            model="test-model",
            system_prompt="Answer from knowledge.",
            user_message="What is Phase 2?",
            tools=tools,
        )
    )

    assert result == "Phase 2 is delegate-based research: delegate is Phase 2."
    child_calls = [call for call in calls if call["messages"][0]["content"] == agent.RESEARCH_SUBAGENT_PROMPT]
    assert child_calls
    assert all(tool["function"]["name"] != "delegate" for call in child_calls for tool in call["tools"])
    assert any(
        message.get("role") == "tool" and message.get("tool_call_id") == "child_search" for call in child_calls for message in call["messages"]
    )
    parent_final_messages = calls[-1]["messages"]
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "parent_delegate"
        and "Paths used: team/roadmap.md" in message.get("content", "")
        for message in parent_final_messages
    )


def test_run_agent_awaits_async_tool_handler(monkeypatch) -> None:
    async def async_handler(args: dict[str, Any]) -> str:
        return f"async value: {args['value']}"

    tool = agent.Tool(
        name="async_echo",
        description="Return a value asynchronously.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=async_handler,
    )
    calls: list[list[dict[str, Any]]] = []

    async def fake_complete(**kwargs: Any) -> dict[str, Any]:
        calls.append(list(kwargs["messages"]))
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_async",
                        "type": "function",
                        "function": {"name": "async_echo", "arguments": '{"value": "ok"}'},
                    },
                ],
            }
        return {"role": "assistant", "content": "The tool returned async value: ok."}

    monkeypatch.setattr(agent, "complete", fake_complete)

    result = asyncio.run(
        agent.run_agent(
            api_key="test-key",
            model="test-model",
            system_prompt="Use the tool.",
            user_message="Echo.",
            tools=[tool],
        )
    )

    assert result == "The tool returned async value: ok."
    assert any(
        message["role"] == "tool" and message["tool_call_id"] == "call_async" and message["content"] == "async value: ok"
        for message in calls[1]
    )


def test_recall_tool_returns_store_hits(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        store.log("channel-a", "user", "We picked the launch checklist as the next topic.", now=100.0)
        recall = build_recall_tool(store, channel_id="channel-a")

        result = recall.handler({"query": "launch"})

        assert "user @ 100.0:" in result
        assert "[launch]" in result.lower()
    finally:
        store.close()
