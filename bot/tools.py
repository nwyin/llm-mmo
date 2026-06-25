"""Knowledge-base tools for the minimal agent loop."""

from __future__ import annotations

from typing import Any

from agent import Tool
from knowledge import KnowledgeBase


def build_knowledge_tools(kb: KnowledgeBase, *, max_files: int, max_chars: int, snippet_chars: int = 400) -> list[Tool]:
    def search_knowledge(args: dict[str, Any]) -> str:
        query = args["query"]
        notes = kb.search(query, k=max_files, max_chars=max_chars)
        if not notes:
            return "no matches found in the knowledge base"
        lines = []
        for note in notes:
            snippet = " ".join(note.text.split())[:snippet_chars]
            lines.append(f"- {note.path}\n    {snippet}")
        return "\n".join(lines)

    def read_page(args: dict[str, Any]) -> str:
        path = args["path"]
        root = kb.root.resolve()
        target = (kb.root / path).resolve()
        if not target.is_relative_to(root):
            return "error: path is outside the knowledge base"
        if not target.is_file():
            return f"error: page not found: {path}"
        return target.read_text(encoding="utf-8", errors="replace")

    return [
        Tool(
            name="search_knowledge",
            description="Search the knowledge base first. Then read the most relevant pages in full and cite paths in the answer.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for relevant knowledge-base pages."},
                },
                "required": ["query"],
            },
            handler=search_knowledge,
        ),
        Tool(
            name="read_page",
            description="Read a full knowledge-base page after searching. Use this for relevant results and cite the page path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "repo-relative path under knowledge/, e.g. as returned by search_knowledge",
                    },
                },
                "required": ["path"],
            },
            handler=read_page,
        ),
    ]
