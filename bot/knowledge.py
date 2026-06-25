"""Knowledge base loading + retrieval.

Intentionally simple: load every markdown file under knowledge/ and rank them against a
query by keyword overlap. No embeddings, no index — good enough for hundreds of small notes
and trivial to reason about. Swap `search()` for an embedding lookup when you outgrow it
(the rest of the bot only depends on the (path, text) tuples it returns).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
# Words too common to be useful signal when scoring.
_STOP = frozenset(
    "a an the of to in on for and or is are be with what how why which that this "
    "i you we they it do does can could would should about from as at by".split()
)


@dataclass(frozen=True)
class Note:
    path: str  # repo-relative, e.g. "thumbnail-ideas/foo.md"
    text: str


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


class KnowledgeBase:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.notes: list[Note] = []
        self.reload()

    def reload(self) -> None:
        notes: list[Note] = []
        if self.root.is_dir():
            for path in sorted(self.root.rglob("*.md")):
                if path.name == "README.md":
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                notes.append(Note(path=str(path.relative_to(self.root)), text=text))
        self.notes = notes

    def search(self, query: str, *, k: int, max_chars: int) -> list[Note]:
        """Return up to `k` notes most relevant to `query`, capped at `max_chars` total.

        Score = sum over query terms of (term frequency in note) weighted so that matching
        the title/path counts extra. Notes with zero overlap are dropped.
        """
        terms = _tokenize(query)
        if not self.notes:
            return []
        if not terms:
            # No usable query terms — return the smallest notes so something useful is sent.
            return self._cap(sorted(self.notes, key=lambda n: len(n.text)), max_chars)

        wanted = set(terms)
        scored: list[tuple[float, Note]] = []
        for note in self.notes:
            body_tokens = _tokenize(note.text)
            path_tokens = set(_tokenize(note.path))
            if not body_tokens:
                continue
            score = sum(1 for t in body_tokens if t in wanted)
            score += 3 * sum(1 for t in wanted if t in path_tokens)  # path/title match is strong signal
            if score > 0:
                scored.append((score, note))

        scored.sort(key=lambda pair: (-pair[0], len(pair[1].text)))
        return self._cap([note for _, note in scored[:k]], max_chars)

    @staticmethod
    def _cap(notes: list[Note], max_chars: int) -> list[Note]:
        out: list[Note] = []
        budget = max_chars
        for note in notes:
            if budget <= 0:
                break
            if len(note.text) <= budget:
                out.append(note)
                budget -= len(note.text)
            else:
                out.append(Note(path=note.path, text=note.text[:budget] + "\n…[truncated]"))
                budget = 0
        return out


def format_context(notes: list[Note]) -> str:
    """Render retrieved notes as a single block for the model's system context."""
    if not notes:
        return "(The knowledge base has no matching notes for this query.)"
    blocks = [f"### knowledge/{n.path}\n\n{n.text.strip()}" for n in notes]
    return "\n\n---\n\n".join(blocks)
