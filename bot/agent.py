"""Minimal tool-calling agent loop for OpenRouter chat completions."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
KNOWLEDGE_TOOL_GUIDANCE = (
    "Use the knowledge-base tools when answering questions about the team or project. "
    "Search before answering, then read the most relevant pages in full before relying on them. "
    "Cite the file paths you used. If the search finds nothing relevant, say that plainly."
)
RESEARCH_SUBAGENT_PROMPT = (
    "You are an internal research subagent. Research the knowledge base for the user's goal. "
    "Search first, read the most relevant pages, then return a concise brief with key findings "
    "and the file paths used. Do not use persona voice."
)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str | Awaitable[str]]


async def complete(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Return the raw assistant message. Raises httpx.HTTPError on transport/HTTP failure."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "llm-mmo",
    }
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools is not None:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]


async def run_agent(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[Tool],
    history: list[dict[str, Any]] | None = None,
    max_iterations: int = 6,
) -> str:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    tool_specs = [
        {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}} for tool in tools
    ]
    tool_map = {tool.name: tool for tool in tools}

    for _ in range(max_iterations):
        msg = await complete(api_key=api_key, model=model, messages=messages, tools=tool_specs)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return (msg.get("content") or "").strip()

        messages.append(msg)
        for call in tool_calls:
            name = call.get("function", {}).get("name", "")
            try:
                args = json.loads(call.get("function", {}).get("arguments") or "{}")
                tool = tool_map.get(name)
                if tool is None:
                    content = f"error: unknown tool {name}"
                else:
                    result = tool.handler(args)
                    content = await result if inspect.isawaitable(result) else result
            except Exception as exc:
                content = f"error: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": content})

    msg = await complete(api_key=api_key, model=model, messages=messages, tools=None)
    return (msg.get("content") or "").strip() or "I could not complete the answer after using the available tools."
