"""Persona loading. Each personas/<id>.md file is a system prompt; the id is the filename."""

from __future__ import annotations

from pathlib import Path


class Personas:
    def __init__(self, root: Path, default_id: str) -> None:
        self.root = root
        self.default_id = default_id
        self.prompts: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        prompts: dict[str, str] = {}
        if self.root.is_dir():
            for path in sorted(self.root.glob("*.md")):
                if path.stem == "README":
                    continue
                prompts[path.stem] = path.read_text(encoding="utf-8", errors="replace").strip()
        self.prompts = prompts

    def ids(self) -> list[str]:
        return sorted(self.prompts)

    def get(self, persona_id: str | None) -> tuple[str, str]:
        """Return (resolved_id, system_prompt). Falls back to the default persona."""
        if persona_id and persona_id in self.prompts:
            return persona_id, self.prompts[persona_id]
        if self.default_id in self.prompts:
            return self.default_id, self.prompts[self.default_id]
        # No persona files at all — a safe built-in fallback so the bot still answers.
        return "fallback", "You are a helpful assistant for a Discord knowledge base. Be concise and honest about gaps."
