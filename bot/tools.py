"""Knowledge-base tools for the minimal agent loop."""

from __future__ import annotations

from typing import Any

from agent import RESEARCH_SUBAGENT_PROMPT, Tool, run_agent
from knowledge import KnowledgeBase
from store import Store


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


def build_delegate_tool(
    kb: KnowledgeBase,
    *,
    max_files: int,
    max_chars: int,
    api_key: str,
    model: str,
    max_iterations: int,
) -> Tool:
    async def delegate(args: dict[str, Any]) -> str:
        goal = args["goal"]
        return await run_agent(
            api_key=api_key,
            model=model,
            system_prompt=RESEARCH_SUBAGENT_PROMPT,
            user_message=goal,
            tools=build_knowledge_tools(kb, max_files=max_files, max_chars=max_chars),
            max_iterations=max_iterations,
        )

    return Tool(
        name="delegate",
        description=(
            "Delegate a focused research question to an isolated subagent that searches/reads the knowledge base and returns a "
            "brief. Use for multi-step or broad lookups; for a single quick fact, use search_knowledge/read_page directly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Focused research question or task for the isolated knowledge-base subagent.",
                },
            },
            "required": ["goal"],
        },
        handler=delegate,
    )


def build_recall_tool(store: Store) -> Tool:
    def recall(args: dict[str, Any]) -> str:
        rows = store.search(args["query"])
        if not rows:
            return "no earlier matches"
        return "\n".join(f"{row['role']} @ {row['ts']}: {row['snippet']}" for row in rows)

    return Tool(
        name="recall",
        description="Search the bot's own past conversations (across sessions) for something discussed before.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for earlier conversation snippets."},
            },
            "required": ["query"],
        },
        handler=recall,
    )
