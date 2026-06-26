"""Lightweight token-usage accounting for a single agent turn.

The agent makes one LLM call per tool-use iteration plus a final answer, so a turn's real
cost is the sum across calls. ``UsageMeter`` accumulates the ``usage`` objects OpenRouter
returns (via run_agent's on_usage hook) so the bot can log what each turn actually spent —
the first thing you want visibility into when leaving a bot running unattended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UsageMeter:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def record(self, usage: dict[str, Any]) -> None:
        self.calls += 1
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        total = usage.get("total_tokens")
        self.total_tokens += int(total) if total is not None else prompt + completion

    def summary(self) -> str:
        return f"{self.calls} call(s), {self.prompt_tokens} prompt + {self.completion_tokens} completion = {self.total_tokens} tokens"
