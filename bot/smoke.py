"""Offline smoke test: load the real knowledge base + personas and run a sample query.

No Discord, no network, no secrets. Proves the retrieval + persona wiring works against the
actual repo content.

    uv run --no-project python smoke.py "what cooking thumbnails work?"
"""

from __future__ import annotations

import sys
from pathlib import Path

from knowledge import KnowledgeBase, format_context
from personas import Personas

# Resolve repo dirs directly so this runs with no third-party deps (no dotenv).
REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
PERSONAS_DIR = REPO_ROOT / "personas"


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "thumbnail ideas"

    personas = Personas(PERSONAS_DIR, default_id="default")
    print(f"Personas loaded: {personas.ids()}")

    knowledge_base = KnowledgeBase(KNOWLEDGE_DIR)
    print(f"Notes loaded: {len(knowledge_base.notes)}")

    notes = knowledge_base.search(query, k=6, max_chars=24000)
    print(f"\nTop matches for {query!r}: {[n.path for n in notes]}\n")
    print("--- context that would be sent to the model ---")
    print(format_context(notes)[:800])


if __name__ == "__main__":
    main()
