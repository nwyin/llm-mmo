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


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class SkillLibrary:
    """Indexes skills from a read-only curated dir plus an optional agent-writable runtime dir.

    Curated skills (e.g. .agents/skills, tracked in git) are never modified by the agent.
    The agent can create/edit/patch/remove its own skills in ``runtime_dir`` via skill_manage;
    those are the procedural half of the self-improvement loop. On a name collision the curated
    skill wins the index entry (the agent cannot shadow a curated skill).
    """

    def __init__(self, dir: Path, *, runtime_dir: Path | None = None) -> None:
        self.dir = dir
        self.runtime_dir = runtime_dir
        self.skills: dict[str, Skill] = {}
        self.reload()

    def _scan(self, root: Path | None, skills: dict[str, Skill], *, overwrite: bool) -> None:
        if root is None or not root.exists():
            return
        for path in sorted(root.rglob("SKILL.md")):
            try:
                frontmatter = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            name = frontmatter.get("name", "").strip()
            description = frontmatter.get("description", "").strip()
            if name and description and (overwrite or name not in skills):
                skills[name] = Skill(name=name, description=description, path=path)

    def reload(self) -> None:
        skills: dict[str, Skill] = {}
        # Runtime first, then curated overwrites — curated wins on collision.
        self._scan(self.runtime_dir, skills, overwrite=True)
        self._scan(self.dir, skills, overwrite=True)
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

    # ---- agent-writable runtime skills (skill_manage backend) ----------------

    def _runtime_skill_path(self, name: str) -> Path:
        if self.runtime_dir is None:
            raise ValueError("no runtime skills directory is configured")
        return self.runtime_dir / name / "SKILL.md"

    def _is_curated(self, name: str) -> bool:
        skill = self.skills.get(name)
        if skill is None or self.runtime_dir is None:
            return skill is not None
        return not skill.path.is_relative_to(self.runtime_dir)

    def create(self, name: str, description: str, body: str) -> str:
        if self.runtime_dir is None:
            return "error: skill creation is disabled (no runtime skills directory)"
        if not _SKILL_NAME_RE.match(name or ""):
            return "error: skill name must be lowercase letters, digits, and hyphens"
        if not (description or "").strip():
            return "error: description is required"
        if name in self.skills:
            return f"error: a skill named {name} already exists; edit or patch it instead"
        path = self._runtime_skill_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_skill(name, description, body), encoding="utf-8")
        self.reload()
        return f"ok: created skill {name}"

    def edit(self, name: str, *, description: str | None = None, body: str | None = None) -> str:
        guard = self._writable_guard(name)
        if guard:
            return guard
        existing = parse_frontmatter(self._runtime_skill_path(name).read_text(encoding="utf-8", errors="replace"))
        new_description = description if description is not None and description.strip() else existing.get("description", "")
        if body is None:
            return "error: body is required to edit a skill"
        self._runtime_skill_path(name).write_text(_render_skill(name, new_description, body), encoding="utf-8")
        self.reload()
        return f"ok: edited skill {name}"

    def patch(self, name: str, old_text: str, new_text: str) -> str:
        guard = self._writable_guard(name)
        if guard:
            return guard
        if not old_text:
            return "error: old_text is required to patch a skill"
        path = self._runtime_skill_path(name)
        content = path.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)
        if count == 0:
            return f"error: old_text not found in skill {name}"
        if count > 1:
            return f"error: old_text matches {count} times in skill {name}; make it unique"
        path.write_text(content.replace(old_text, new_text), encoding="utf-8")
        self.reload()
        return f"ok: patched skill {name}"

    def remove(self, name: str) -> str:
        guard = self._writable_guard(name)
        if guard:
            return guard
        path = self._runtime_skill_path(name)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
        self.reload()
        return f"ok: removed skill {name}"

    def _writable_guard(self, name: str) -> str | None:
        if self.runtime_dir is None:
            return "error: skill editing is disabled (no runtime skills directory)"
        if name not in self.skills:
            return f"error: no skill named {name}"
        if self._is_curated(name):
            return f"error: {name} is a curated skill and cannot be modified"
        return None


def _render_skill(name: str, description: str, body: str) -> str:
    body = (body or "").strip()
    front = f"---\nname: {name}\ndescription: {description.strip()}\n---\n"
    return f"{front}\n{body}\n" if body else front


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
