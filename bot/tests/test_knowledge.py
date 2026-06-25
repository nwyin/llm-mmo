"""Retrieval + persona-loading tests. Run with `uv run pytest`.

These exercise the pure logic (no Discord, no network), so they're a fast sanity check that
the knowledge base and personas load and rank sensibly.
"""

from __future__ import annotations

from pathlib import Path

from knowledge import KnowledgeBase, format_context
from personas import Personas


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_search_ranks_relevant_note_first(tmp_path: Path) -> None:
    _write(tmp_path, "thumbnail-ideas/cooking.md", "# Cooking hook\nClose-up of sizzling food with hands in frame.")
    _write(tmp_path, "competitors/pricing.md", "# Pricing\nCompetitor pricing tiers and plans.")
    knowledge_base = KnowledgeBase(tmp_path)

    results = knowledge_base.search("what cooking thumbnails work?", k=5, max_chars=10000)

    assert results, "expected at least one match"
    assert results[0].path == "thumbnail-ideas/cooking.md"


def test_search_drops_zero_overlap_notes(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# Apples\nAll about apples.")
    knowledge_base = KnowledgeBase(tmp_path)

    assert knowledge_base.search("quantum chromodynamics", k=5, max_chars=10000) == []


def test_search_respects_char_budget(tmp_path: Path) -> None:
    _write(tmp_path, "big.md", "# Cooking\n" + ("cooking " * 1000))
    knowledge_base = KnowledgeBase(tmp_path)

    results = knowledge_base.search("cooking", k=5, max_chars=100)

    assert len(results[0].text) <= 100 + len("\n…[truncated]")


def test_readme_is_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "# Readme\ncooking cooking cooking")
    _write(tmp_path, "real.md", "# Real\ncooking notes")
    knowledge_base = KnowledgeBase(tmp_path)

    assert all(n.path != "README.md" for n in knowledge_base.notes)


def test_format_context_handles_empty() -> None:
    assert "no matching notes" in format_context([])


def test_personas_fallback_when_missing(tmp_path: Path) -> None:
    personas = Personas(tmp_path, default_id="default")
    resolved_id, prompt = personas.get("nonexistent")

    assert resolved_id == "fallback"
    assert prompt


def test_personas_loads_and_selects(tmp_path: Path) -> None:
    (tmp_path / "default.md").write_text("Default persona.", encoding="utf-8")
    (tmp_path / "scout.md").write_text("Scout persona.", encoding="utf-8")
    personas = Personas(tmp_path, default_id="default")

    assert set(personas.ids()) == {"default", "scout"}
    assert personas.get("scout") == ("scout", "Scout persona.")
    assert personas.get(None)[0] == "default"
