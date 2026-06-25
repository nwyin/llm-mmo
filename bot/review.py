"""Background-review fork: after a turn, look back and persist operational learnings.

This is the autonomous half of the self-improvement loop. It replays the just-finished turn
through the agent with a TIGHT toolset — only agent-memory writes and skill management — and
asks it to capture things a future session should already know: repeated corrections ("use X
not Y"), tool/workflow preferences, reusable techniques.

It is deliberately scoped to OPERATIONAL memory. It is given no ability to write user
profiles (``allow_user_writes=False``), no delegate/web/save tools, and it is not a bot turn,
so it cannot trigger another review (no recursion). Failures are the caller's to swallow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent import run_agent
from memory import MemoryStore
from skills import SkillLibrary
from tools import build_remember_tool, build_skill_manage_tool

REVIEW_PROMPT = (
    "You are a background reviewer for an assistant shared by a team. Look back at the conversation "
    "excerpt below and decide whether anything OPERATIONAL is worth persisting for future sessions:\n"
    "  • a repeated correction or stated preference (e.g. 'use X not Y', 'keep answers terse');\n"
    "  • a tool/workflow convention the team follows;\n"
    "  • a reusable technique, fix, or pitfall that emerged.\n\n"
    "If so, save it: use remember(target=agent) for a durable fact, or skill_manage to create/patch a skill. "
    "Do NOT record per-person profile details, secrets, or transient chatter. Do NOT restate the conversation. "
    "If nothing is worth saving, reply exactly 'Nothing to save.' and stop."
)


@dataclass(frozen=True)
class ReviewResult:
    memory_writes: int
    skill_writes: int

    @property
    def saved_anything(self) -> bool:
        return self.memory_writes > 0 or self.skill_writes > 0

    def notice(self) -> str | None:
        if not self.saved_anything:
            return None
        parts: list[str] = []
        if self.memory_writes:
            parts.append(f"{self.memory_writes} memory note(s)")
        if self.skill_writes:
            parts.append(f"{self.skill_writes} skill update(s)")
        return "learned: " + ", ".join(parts)


def format_transcript(transcript: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    for message in transcript:
        role = str(message.get("role", "")).upper()
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    text = "\n\n".join(lines)
    if len(text) > max_chars:
        text = "…" + text[-max_chars:]
    return text or "(empty conversation)"


async def run_background_review(
    *,
    api_key: str,
    model: str,
    memory: MemoryStore,
    skills: SkillLibrary,
    transcript: list[dict[str, Any]],
    max_iterations: int = 4,
) -> ReviewResult:
    memory_writes = 0
    skill_writes = 0

    def _on_memory() -> None:
        nonlocal memory_writes
        memory_writes += 1

    def _on_skill() -> None:
        nonlocal skill_writes
        skill_writes += 1

    tools = [
        build_remember_tool(
            memory,
            user_id="__review__",
            admins=(),
            allow_user_writes=False,  # the fork can never write user profiles
            on_agent_write=_on_memory,
        ),
        build_skill_manage_tool(skills, on_write=_on_skill),
    ]
    await run_agent(
        api_key=api_key,
        model=model,
        system_prompt=REVIEW_PROMPT,
        user_message="Conversation excerpt to review:\n\n" + format_transcript(transcript),
        tools=tools,
        max_iterations=max_iterations,
    )
    return ReviewResult(memory_writes=memory_writes, skill_writes=skill_writes)
