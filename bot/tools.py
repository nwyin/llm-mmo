"""Knowledge-base tools for the minimal agent loop."""

from __future__ import annotations

from typing import Any

from agent import RESEARCH_SUBAGENT_PROMPT, Tool, run_agent
from knowledge import KnowledgeBase
from memory import TARGETS, MemoryStore
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


def build_remember_tool(memory: MemoryStore) -> Tool:
    def remember(args: dict[str, Any]) -> str:
        operations = args.get("operations")
        if operations is not None:
            if not isinstance(operations, list):
                return "error: operations must be an array"
            error = _validate_memory_operations(operations)
            if error:
                return error
            return memory.apply(operations)

        action = args.get("action")
        target = args.get("target")
        if not isinstance(action, str) or not action:
            return "error: action is required"
        if not isinstance(target, str) or not target:
            return "error: target is required"
        if target not in TARGETS:
            return f"error: unknown memory target: {target}"

        if action == "add":
            content = args.get("content")
            if not isinstance(content, str) or not content.strip():
                return "error: content is required for add"
            return memory.add(target, content)
        if action == "replace":
            old_text = args.get("old_text")
            content = args.get("content")
            if not isinstance(old_text, str) or not old_text:
                return "error: old_text is required for replace"
            if not isinstance(content, str) or not content.strip():
                return "error: content is required for replace"
            return memory.replace(target, old_text, content)
        if action == "remove":
            old_text = args.get("old_text")
            if not isinstance(old_text, str) or not old_text:
                return "error: old_text is required for remove"
            return memory.remove(target, old_text)
        return f"error: unknown memory action: {action}"

    return Tool(
        name="remember",
        description=(
            "Save durable long-term facts. Use target=agent for team/project notes and target=user for the user's preferences. "
            "Prefer operations[] for atomic batches when consolidating or editing several memories. Never save secrets or transient chatter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "replace", "remove"], "description": "Single memory edit action."},
                "target": {
                    "type": "string",
                    "enum": ["agent", "user"],
                    "description": "agent for team/project notes; user for the user's preferences.",
                },
                "content": {"type": "string", "description": "Memory content for add or replacement content for replace."},
                "old_text": {"type": "string", "description": "Substring identifying the memory to replace or remove."},
                "operations": {
                    "type": "array",
                    "description": "Atomic batch of memory edits. Prefer this when consolidating.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                            "target": {"type": "string", "enum": ["agent", "user"]},
                            "content": {"type": "string"},
                            "old_text": {"type": "string"},
                        },
                        "required": ["action", "target"],
                    },
                },
            },
        },
        handler=remember,
    )


def _validate_memory_operations(operations: list[Any]) -> str | None:
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            return f"error in operation {index}: operation must be an object"
        action = operation.get("action")
        target = operation.get("target")
        if not isinstance(action, str) or not action:
            return f"error in operation {index}: action is required"
        if not isinstance(target, str) or not target:
            return f"error in operation {index}: target is required"
        if target not in TARGETS:
            return f"error in operation {index}: unknown memory target: {target}"
        if action == "add":
            content = operation.get("content")
            if not isinstance(content, str) or not content.strip():
                return f"error in operation {index}: content is required for add"
        elif action == "replace":
            old_text = operation.get("old_text")
            content = operation.get("content")
            if not isinstance(old_text, str) or not old_text:
                return f"error in operation {index}: old_text is required for replace"
            if not isinstance(content, str) or not content.strip():
                return f"error in operation {index}: content is required for replace"
        elif action == "remove":
            old_text = operation.get("old_text")
            if not isinstance(old_text, str) or not old_text:
                return f"error in operation {index}: old_text is required for remove"
        else:
            return f"error in operation {index}: unknown memory action: {action}"
    return None
