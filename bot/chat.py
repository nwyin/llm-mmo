"""Chat replies via the OpenRouter chat-completions API.

This is the only LLM call the bot makes directly — interactive Q&A needs low latency, so it
hits the model API rather than spinning up an agent. The async agent work (which opens PRs)
runs in GitHub Actions via dispatch.py.
"""

from __future__ import annotations

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Wrapper that frames the retrieved notes for the model without overriding the persona voice.
_CONTEXT_PREAMBLE = (
    "You have access to the following excerpts from the team's knowledge base. "
    "Use them to answer; cite the file path when you draw on one. If they don't cover the "
    "question, say so.\n\n<knowledge_base>\n{context}\n</knowledge_base>"
)


async def chat_reply(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    knowledge_context: str,
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Return the assistant's reply text. Raises httpx.HTTPError on transport/HTTP failure."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": _CONTEXT_PREAMBLE.format(context=knowledge_context)},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional attribution headers OpenRouter recommends; harmless if unused.
        "X-Title": "llm-mmo",
    }
    payload = {"model": model, "messages": messages}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()
