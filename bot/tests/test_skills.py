"""Skill loader tests. Run with `uv run pytest`."""

from __future__ import annotations

from pathlib import Path

from config import REPO_ROOT
from skills import SkillLibrary, parse_frontmatter


def test_parse_frontmatter_handles_block_scalar_description_and_quoted_name() -> None:
    text = """---
name: "quoted-skill"
description: >-
  First line of the description
  continues on the second line.
license: MIT
---

# Body
"""

    frontmatter = parse_frontmatter(text)

    assert frontmatter["name"] == "quoted-skill"
    assert frontmatter["description"] == "First line of the description continues on the second line."


def test_skill_library_indexes_and_views_tmp_skill(tmp_path: Path) -> None:
    skill_path = tmp_path / "demo" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text(
        """---
name: demo-skill
description: Demo skill for testing.
---

# Demo

Full body.
""",
        encoding="utf-8",
    )
    library = SkillLibrary(tmp_path)

    index = library.index_text()

    assert "demo-skill" in index
    assert "Demo skill for testing." in index
    assert "# Demo" in library.view("demo-skill")
    assert library.view("nope").startswith("error: no skill named nope. Available: demo-skill")


def test_real_repo_skills_are_discovered() -> None:
    library = SkillLibrary(REPO_ROOT / ".agents" / "skills")

    assert "creating-workflows" in library.skills
    assert "getting-started" in library.skills
