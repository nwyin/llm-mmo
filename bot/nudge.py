"""Per-channel nudge counters for the self-improvement loop.

A nudge is a one-turn reminder injected into the system prompt telling the live agent to
persist operational learnings (durable agent-memory facts, or a skill update). We track two
independent counters per channel: turns since the last agent-memory write and turns since the
last skill write. A counter fires when it reaches its interval, and resets both when it fires
and when the corresponding write happens — so a productive channel is never nagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MEMORY_NUDGE = (
    "Reminder: if anything durable about the team, tools, or workflow came up recently and "
    "isn't saved yet, record it now with remember(target=agent)."
)
SKILL_NUDGE = (
    "Reminder: if a repeated correction or a reusable technique has emerged, capture it with "
    "skill_manage (create or patch a skill) so future sessions start knowing it."
)


@dataclass
class NudgeTracker:
    memory_interval: int = 10
    skill_interval: int = 10
    _turns_since_memory: int = field(default=0)
    _turns_since_skill: int = field(default=0)

    def record_turn(self) -> None:
        self._turns_since_memory += 1
        self._turns_since_skill += 1

    def note_memory_write(self) -> None:
        self._turns_since_memory = 0

    def note_skill_write(self) -> None:
        self._turns_since_skill = 0

    def take_nudge(self) -> str | None:
        """Return the nudge text to inject this turn (and reset fired counters), or None."""
        parts: list[str] = []
        if self.memory_interval > 0 and self._turns_since_memory >= self.memory_interval:
            parts.append(MEMORY_NUDGE)
            self._turns_since_memory = 0
        if self.skill_interval > 0 and self._turns_since_skill >= self.skill_interval:
            parts.append(SKILL_NUDGE)
            self._turns_since_skill = 0
        return "\n".join(parts) if parts else None
