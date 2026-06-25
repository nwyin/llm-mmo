"""Agent-writable runtime skills + dual-dir indexing tests."""

from __future__ import annotations

from pathlib import Path

from skills import SkillLibrary
from tools import build_skill_manage_tool


def _curated(root: Path, name: str) -> None:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: Curated {name}.\n---\n\n# {name}\n", encoding="utf-8")


def test_create_edit_patch_remove_runtime_skill(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    runtime = tmp_path / "runtime"
    curated.mkdir()
    library = SkillLibrary(curated, runtime_dir=runtime)

    assert library.create("market-scan", "How to scan a market.", "# Market scan\nstep 1").startswith("ok")
    assert "market-scan" in library.skills
    assert "step 1" in library.view("market-scan")

    assert library.patch("market-scan", "step 1", "step one").startswith("ok")
    assert "step one" in library.view("market-scan")

    assert library.edit("market-scan", body="# Market scan\nrewritten").startswith("ok")
    assert "rewritten" in library.view("market-scan")

    assert library.remove("market-scan").startswith("ok")
    assert "market-scan" not in library.skills


def test_runtime_and_curated_both_indexed_curated_wins(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    runtime = tmp_path / "runtime"
    _curated(curated, "shared")
    library = SkillLibrary(curated, runtime_dir=runtime)
    library.create("runtime-only", "Runtime skill.", "# body")

    # Agent tries to shadow a curated skill: refused, curated entry stays.
    assert library.create("shared", "Shadow attempt.", "# x").startswith("error")
    assert "runtime-only" in library.skills
    assert "shared" in library.skills
    assert "Curated shared." in library.index_text()


def test_cannot_modify_curated_skill(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    runtime = tmp_path / "runtime"
    _curated(curated, "locked")
    library = SkillLibrary(curated, runtime_dir=runtime)

    assert library.patch("locked", "locked", "x").startswith("error")
    assert library.edit("locked", body="x").startswith("error")
    assert library.remove("locked").startswith("error")


def test_create_rejects_bad_name(tmp_path: Path) -> None:
    library = SkillLibrary(tmp_path / "curated", runtime_dir=tmp_path / "runtime")
    assert library.create("Bad Name", "d", "b").startswith("error")
    assert library.create("../escape", "d", "b").startswith("error")


def test_skill_manage_tool_fires_write_callback(tmp_path: Path) -> None:
    library = SkillLibrary(tmp_path / "curated", runtime_dir=tmp_path / "runtime")
    fired = []
    tool = build_skill_manage_tool(library, on_write=lambda: fired.append(True))

    result = tool.handler({"action": "create", "name": "demo", "description": "Demo.", "body": "# Demo"})

    assert result.startswith("ok")
    assert fired == [True]


def test_skill_manage_tool_unknown_action(tmp_path: Path) -> None:
    library = SkillLibrary(tmp_path / "curated", runtime_dir=tmp_path / "runtime")
    tool = build_skill_manage_tool(library)
    assert tool.handler({"action": "frobnicate", "name": "demo"}).startswith("error")
