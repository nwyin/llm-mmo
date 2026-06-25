"""Knowledge-base tools for the minimal agent loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import dispatch
from agent import RESEARCH_SUBAGENT_PROMPT, Tool, run_agent
from cron import CronStore, ScheduleError, parse_schedule
from knowledge import KnowledgeBase
from memory import TARGETS, MemoryStore
from skills import SkillLibrary
from store import Store
from web import WebClient, WebError, format_results


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


def build_web_tools(web: WebClient, *, max_results: int = 5) -> list[Tool]:
    async def web_search(args: dict[str, Any]) -> str:
        query = args.get("query", "")
        try:
            results = await web.search(query, k=max_results)
        except WebError as exc:
            return f"error: {exc}"
        return format_results(results)

    async def web_extract(args: dict[str, Any]) -> str:
        url = args.get("url", "")
        try:
            return await web.extract(url)
        except WebError as exc:
            return f"error: {exc}"

    return [
        Tool(
            name="web_search",
            description=(
                "Search the public web for external facts (markets, competitors, prospective clients, news). "
                "Returns ranked title/url/snippet results. Follow up with web_extract to read a page, and cite URLs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Web search query."},
                },
                "required": ["query"],
            },
            handler=web_search,
        ),
        Tool(
            name="web_extract",
            description="Fetch an http(s) URL and return its main text (length-capped). Use after web_search; cite the URL.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL to fetch and read."},
                },
                "required": ["url"],
            },
            handler=web_extract,
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
    web: WebClient | None = None,
    web_max_results: int = 5,
) -> Tool:
    async def delegate(args: dict[str, Any]) -> str:
        goal = args["goal"]
        subagent_tools = build_knowledge_tools(kb, max_files=max_files, max_chars=max_chars)
        if web is not None:
            subagent_tools = subagent_tools + build_web_tools(web, max_results=web_max_results)
        return await run_agent(
            api_key=api_key,
            model=model,
            system_prompt=RESEARCH_SUBAGENT_PROMPT,
            user_message=goal,
            tools=subagent_tools,
            max_iterations=max_iterations,
        )

    return Tool(
        name="delegate",
        description=(
            "Delegate a focused research question to an isolated subagent that searches/reads the knowledge base and the web, then "
            "returns a brief with sources. Use for multi-step or broad research (e.g. profiling a client or competitor); for a single "
            "quick fact, use search_knowledge/read_page or web_search directly."
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


def build_skill_view_tool(skills: SkillLibrary) -> Tool:
    def skill_view(args: dict[str, Any]) -> str:
        name = args["name"]
        return skills.view(name)

    return Tool(
        name="skill_view",
        description="Load the full instructions for a named skill from the index in your system prompt.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact skill name from the system prompt skills index."},
            },
            "required": ["name"],
        },
        handler=skill_view,
    )


def build_skill_manage_tool(skills: SkillLibrary, *, on_write: Callable[[], None] | None = None) -> Tool:
    def skill_manage(args: dict[str, Any]) -> str:
        action = str(args.get("action", "")).strip()
        name = str(args.get("name", "")).strip()
        if not action:
            return "error: action is required"
        if not name:
            return "error: name is required"

        if action == "create":
            result = skills.create(name, str(args.get("description", "")), str(args.get("body", "")))
        elif action == "edit":
            description = args.get("description")
            body = args.get("body")
            result = skills.edit(
                name,
                description=str(description) if isinstance(description, str) else None,
                body=str(body) if isinstance(body, str) else None,
            )
        elif action == "patch":
            result = skills.patch(name, str(args.get("old_text", "")), str(args.get("new_text", "")))
        elif action == "remove":
            result = skills.remove(name)
        else:
            return f"error: unknown skill action: {action}"

        if result.startswith("ok") and on_write is not None:
            on_write()
        return result

    return Tool(
        name="skill_manage",
        description=(
            "Create or improve your own reusable skills (procedural memory). Use create for a new skill, edit to rewrite its body, "
            "patch for a small substring change, remove to delete one. Encode tool/workflow preferences and techniques so future "
            "sessions start already knowing. Only your runtime skills are writable; curated skills are read-only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "edit", "patch", "remove"], "description": "Skill operation."},
                "name": {"type": "string", "description": "Skill name: lowercase letters, digits, hyphens."},
                "description": {"type": "string", "description": "One-line description (create/edit)."},
                "body": {"type": "string", "description": "Full markdown body of the skill (create/edit)."},
                "old_text": {"type": "string", "description": "Unique substring to replace (patch)."},
                "new_text": {"type": "string", "description": "Replacement text (patch)."},
            },
            "required": ["action", "name"],
        },
        handler=skill_manage,
    )


def build_recall_tool(store: Store, *, channel_id: str) -> Tool:
    def recall(args: dict[str, Any]) -> str:
        rows = store.search(args["query"], channel_id=channel_id)
        if not rows:
            return "no earlier matches"
        return "\n".join(f"{row['role']} @ {row['ts']}: {row['snippet']}" for row in rows)

    return Tool(
        name="recall",
        description="Search this channel's past conversations (across sessions) for something discussed before.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for earlier conversation snippets."},
            },
            "required": ["query"],
        },
        handler=recall,
    )


def _validate_kb_path(path: str) -> str | None:
    """Reject anything that would write outside knowledge/. Returns an error string or None."""
    path = (path or "").strip()
    if not path:
        return "error: path is required"
    if "\\" in path:
        return "error: path must use forward slashes (got a backslash)"
    if path.startswith("/") or path.startswith("~"):
        return "error: path must be relative to knowledge/, not absolute"
    parts = PurePosixPath(path).parts
    if any(part in ("..", "") for part in parts):
        return "error: path must stay within knowledge/ (no '..' segments)"
    if not path.endswith(".md"):
        return "error: path must end in .md"
    return None


def build_save_to_kb_tool(*, token: str, repo: str, action: str, requested_by: str, channel_id: str) -> Tool:
    async def save_to_kb(args: dict[str, Any]) -> str:
        path = str(args.get("path", ""))
        content = str(args.get("content", ""))
        error = _validate_kb_path(path)
        if error:
            return error
        if not content.strip():
            return "error: content is required"
        payload = {
            "path": path,
            "title": str(args.get("title", "")).strip(),
            "content": content,
            "reason": str(args.get("reason", "")).strip(),
            "requested_by": requested_by,
            "channel_id": channel_id,
        }
        try:
            await dispatch.dispatch_action(token=token, repo=repo, action=action, payload=payload)
        except Exception as exc:  # noqa: BLE001 — surface dispatch failure as a tool error
            return f"error: could not request the save: {exc}"
        return f"ok: requested a save of knowledge/{path}. A PR will open in {repo} for review — nothing is written until it is merged."

    return Tool(
        name="save_to_kb",
        description=(
            "Persist a finished note (research brief, collated customer feedback, client profile) to the knowledge base. "
            "This does NOT write directly — it opens a pull request for human review. Provide the full markdown content; "
            "path is repo-relative under knowledge/ and must end in .md."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative path under knowledge/, ending in .md, e.g. 'clients/acme.md'."},
                "title": {"type": "string", "description": "Short human title for the PR."},
                "content": {"type": "string", "description": "Full markdown body of the note to save."},
                "reason": {"type": "string", "description": "Why this is being saved (for the PR description)."},
            },
            "required": ["path", "content"],
        },
        handler=save_to_kb,
    )


def build_workspace_recall_tool(store: Store) -> Tool:
    def workspace_recall(args: dict[str, Any]) -> str:
        rows = store.search_all_channels(args["query"])
        if not rows:
            return "no matches across channels"
        return "\n".join(f"[{row['channel_id']}] {row['role']} @ {row['ts']}: {row['snippet']}" for row in rows)

    return Tool(
        name="workspace_recall",
        description=(
            "Search ALL channels' past conversations for institutional knowledge discussed anywhere in the workspace. "
            "Admin-only and cross-channel — use the channel-scoped recall for the current conversation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query across every channel's history."},
            },
            "required": ["query"],
        },
        handler=workspace_recall,
    )


def build_cronjob_tool(
    store: CronStore,
    *,
    user_id: str,
    admins: tuple[str, ...] | frozenset[str],
    channel_id: str,
) -> Tool:
    def cronjob(args: dict[str, Any]) -> str:
        if admins and user_id not in admins:
            return "error: scheduled jobs can only be managed by admins for this server."
        action = str(args.get("action", "")).strip()

        if action == "create":
            schedule = str(args.get("schedule", "")).strip()
            prompt = str(args.get("prompt", "")).strip()
            if not schedule:
                return "error: schedule is required"
            if not prompt:
                return "error: prompt is required"
            try:
                parse_schedule(schedule)
            except ScheduleError as exc:
                return f"error: {exc}"
            target = str(args.get("channel_id", "")).strip() or channel_id
            persona = str(args.get("persona", "")).strip() or None
            job = store.add(schedule=schedule, prompt=prompt, channel_id=target, persona=persona, created_by=user_id)
            return f"ok: scheduled {job.summary()}"

        if action == "list":
            jobs = store.list()
            if not jobs:
                return "no scheduled jobs"
            return "\n".join(job.summary() for job in jobs)

        job_id = str(args.get("id", "")).strip()
        if action in {"delete", "pause", "resume"} and not job_id:
            return "error: id is required"
        if action == "delete":
            return f"ok: deleted {job_id}" if store.remove(job_id) else f"error: no job {job_id}"
        if action == "pause":
            return f"ok: paused {job_id}" if store.set_enabled(job_id, False) else f"error: no job {job_id}"
        if action == "resume":
            return f"ok: resumed {job_id}" if store.set_enabled(job_id, True) else f"error: no job {job_id}"
        return f"error: unknown cron action: {action}"

    return Tool(
        name="cronjob",
        description=(
            "Manage scheduled automations (admin only). create a recurring job that runs a prompt and posts the result to a channel "
            "(e.g. a daily customer-feedback digest or weekly competitor scan); list/pause/resume/delete existing jobs. Schedule can be "
            "natural language ('daily 9am', 'weekly mon 9am', 'every 2 hours') or a 5-field cron expression."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list", "delete", "pause", "resume"], "description": "Job operation."},
                "schedule": {"type": "string", "description": "When to run (create): 'daily 9am', 'weekly mon 9am', 'every 2 hours', or cron."},
                "prompt": {"type": "string", "description": "What the agent should do each run (create)."},
                "channel_id": {"type": "string", "description": "Target channel id (create); defaults to the current channel."},
                "persona": {"type": "string", "description": "Optional persona id to run as (create)."},
                "id": {"type": "string", "description": "Job id (delete/pause/resume)."},
            },
            "required": ["action"],
        },
        handler=cronjob,
    )


def build_remember_tool(
    memory: MemoryStore,
    *,
    user_id: str,
    admins: tuple[str, ...] | frozenset[str],
    allow_user_writes: bool = True,
    on_agent_write: Callable[[], None] | None = None,
) -> Tool:
    """Proactive long-term memory.

    target=agent (operational notes) is ungated — the agent saves durable team/tool/workflow
    facts as it works. target=user (per-person profile) stays gated: it requires
    ``allow_user_writes`` and, if an admin list is set, admin membership.
    """

    def _user_writes_allowed() -> bool:
        return allow_user_writes and (not admins or user_id in admins)

    _USER_DENIED = "error: user-profile memory writes are restricted to admins for this server."

    def _signal_agent_write(result: str, touched_agent: bool) -> str:
        if touched_agent and on_agent_write is not None and result.startswith("ok"):
            on_agent_write()
        return result

    def remember(args: dict[str, Any]) -> str:
        operations = args.get("operations")
        if operations is not None:
            if not isinstance(operations, list):
                return "error: operations must be an array"
            error = _validate_memory_operations(operations)
            if error:
                return error
            targets = {op.get("target") for op in operations}
            if "user" in targets and not _user_writes_allowed():
                return _USER_DENIED
            return _signal_agent_write(memory.apply(operations), "agent" in targets)

        action = args.get("action")
        target = args.get("target")
        if not isinstance(action, str) or not action:
            return "error: action is required"
        if not isinstance(target, str) or not target:
            return "error: target is required"
        if target not in TARGETS:
            return f"error: unknown memory target: {target}"
        if target == "user" and not _user_writes_allowed():
            return _USER_DENIED

        if action == "add":
            content = args.get("content")
            if not isinstance(content, str) or not content.strip():
                return "error: content is required for add"
            return _signal_agent_write(memory.add(target, content), target == "agent")
        if action == "replace":
            old_text = args.get("old_text")
            content = args.get("content")
            if not isinstance(old_text, str) or not old_text:
                return "error: old_text is required for replace"
            if not isinstance(content, str) or not content.strip():
                return "error: content is required for replace"
            return _signal_agent_write(memory.replace(target, old_text, content), target == "agent")
        if action == "remove":
            old_text = args.get("old_text")
            if not isinstance(old_text, str) or not old_text:
                return "error: old_text is required for remove"
            return _signal_agent_write(memory.remove(target, old_text), target == "agent")
        return f"error: unknown memory action: {action}"

    return Tool(
        name="remember",
        description=(
            "Save durable long-term facts proactively as you work. Use target=agent for team/project/tool/workflow notes "
            "(e.g. 'the team prefers terse answers', 'use uv not pip here') — save these whenever something durable comes up. "
            "Use target=user for an individual's preferences (admin-gated). "
            "Prefer operations[] for atomic batches when consolidating. Never save secrets or transient chatter."
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
