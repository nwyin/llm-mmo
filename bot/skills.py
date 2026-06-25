"""Agentskills.io skill discovery and loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_BLOCK_SCALARS = {">-", ">", "|", "|-"}
_FRONTMATTER_KEYS = {"name", "description"}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return {}

    result: dict[str, str] = {}
    frontmatter = lines[1:end]
    index = 0
    while index < len(frontmatter):
        raw = frontmatter[index]
        if not raw.strip() or raw.lstrip() != raw or ":" not in raw:
            index += 1
            continue

        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key not in _FRONTMATTER_KEYS:
            index += 1
            continue

        if value in _BLOCK_SCALARS or value == "":
            block_lines: list[str] = []
            index += 1
            while index < len(frontmatter):
                candidate = frontmatter[index]
                if candidate.strip() and candidate.lstrip() == candidate and ":" in candidate:
                    break
                if candidate.strip():
                    block_lines.append(candidate.strip())
                index += 1
            result[key] = _collapse_whitespace(" ".join(block_lines))
            continue

        result[key] = _strip_quotes(value)
        index += 1

    return result


class SkillLibrary:
    def __init__(self, dir: Path) -> None:
        self.dir = dir
        self.skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        skills: dict[str, Skill] = {}
        if not self.dir.exists():
            self.skills = skills
            return

        for path in sorted(self.dir.rglob("SKILL.md")):
            try:
                frontmatter = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            name = frontmatter.get("name", "").strip()
            description = frontmatter.get("description", "").strip()
            if name and description:
                skills[name] = Skill(name=name, description=description, path=path)
        self.skills = skills

    def index_text(self) -> str:
        if not self.skills:
            return ""

        lines = [
            "## Skills",
            "Load a skill with skill_view(name) when its description matches your task, then follow it.",
            "<available_skills>",
        ]
        for skill in self.skills.values():
            lines.append(f"- {skill.name}: {_truncate(skill.description, 200)}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def view(self, name: str) -> str:
        skill = self.skills.get(name)
        if skill is None:
            available = ", ".join(self.skills)
            return f"error: no skill named {name}. Available: {available}"
        return skill.path.read_text(encoding="utf-8", errors="replace")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, max_chars: int) -> str:
    single_line = _collapse_whitespace(value)
    if len(single_line) <= max_chars:
        return single_line
    return single_line[: max_chars - 1].rstrip() + "…"
