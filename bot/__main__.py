"""Discord bot entrypoint.

Run with:  uv run python -m bot

Handles two interaction styles:
  • @mention (gateway, free-form chat)  → answer inline using the knowledge base
  • /ask, /save (slash commands)        → structured chat / dispatch an action to GitHub
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import discord
from discord import app_commands

import agent
import dispatch
from config import KNOWLEDGE_DIR, PERSONAS_DIR, Config, load_config
from cron import CronScheduler, CronStore, Job
from knowledge import KnowledgeBase
from memory import MemoryStore
from nudge import NudgeTracker
from personas import Personas
from review import run_background_review
from skills import SkillLibrary
from store import Store
from tools import (
    build_cronjob_tool,
    build_delegate_tool,
    build_knowledge_tools,
    build_recall_tool,
    build_remember_tool,
    build_save_to_kb_tool,
    build_skill_manage_tool,
    build_skill_view_tool,
    build_web_tools,
    build_workspace_recall_tool,
)
from web import WebClient

# Background-review status notices are posted with this marker so they can be filtered out of
# conversation history (they are non-conversational bookkeeping, not turns).
REVIEW_NOTICE_PREFIX = "🧠"

log = logging.getLogger("llm-mmo")

# Matches a leading "persona-id:" selector in an @mention message.
_PERSONA_PREFIX = re.compile(r"^\s*([a-z0-9][a-z0-9_-]*)\s*:\s*", re.IGNORECASE)


class MMOBot(discord.Client):
    def __init__(self, cfg: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # required to read @mention text; enable in the dev portal too
        super().__init__(intents=intents)
        self.cfg = cfg
        self.knowledge = KnowledgeBase(KNOWLEDGE_DIR)
        self.personas = Personas(PERSONAS_DIR, cfg.default_persona)
        self.store = Store(cfg.store_path)
        self.memory = MemoryStore(cfg.memory_dir, max_chars=cfg.memory_max_chars)
        self.skills = SkillLibrary(cfg.skills_dir, runtime_dir=cfg.skills_runtime_dir)
        self.trackers: dict[str, NudgeTracker] = {}
        self.cron_store = CronStore(cfg.cron_path)
        self.cron = CronScheduler(
            self.cron_store,
            runner=self._run_cron_job,
            deliver=self._deliver_cron,
            on_error=lambda job, exc: log.warning("cron job %s failed: %s", job.id, exc),
        )
        self.web = self._build_web_client(cfg)
        web_tools = build_web_tools(self.web, max_results=cfg.web_max_results) if self.web else []
        self.base_tools = (
            build_knowledge_tools(self.knowledge, max_files=cfg.max_context_files, max_chars=cfg.max_context_chars)
            + web_tools
            + [
                build_delegate_tool(
                    self.knowledge,
                    max_files=cfg.max_context_files,
                    max_chars=cfg.max_context_chars,
                    api_key=cfg.openrouter_api_key,
                    model=cfg.chat_model,
                    max_iterations=cfg.max_iterations,
                    web=self.web,
                    web_max_results=cfg.web_max_results,
                ),
                build_skill_view_tool(self.skills),
            ]
        )
        self.tree = app_commands.CommandTree(self)

    @staticmethod
    def _build_web_client(cfg: Config) -> WebClient | None:
        try:
            return WebClient(
                provider=cfg.web_provider,
                api_key=cfg.web_api_key,
                timeout=cfg.web_timeout,
                max_chars=cfg.web_max_chars,
            )
        except Exception:  # noqa: BLE001 — a misconfigured provider disables web tools, not the bot
            log.warning("web research disabled: invalid provider config", exc_info=True)
            return None

    def _is_admin(self, user_id: str) -> bool:
        # Mirrors the remember-tool gate: an empty admin list means "anyone".
        return (not self.cfg.memory_admins) or user_id in self.cfg.memory_admins

    def _tracker(self, channel_id: str) -> NudgeTracker:
        tracker = self.trackers.get(channel_id)
        if tracker is None:
            tracker = NudgeTracker(memory_interval=self.cfg.nudge_memory_interval, skill_interval=self.cfg.nudge_skill_interval)
            self.trackers[channel_id] = tracker
        return tracker

    def _request_tools(self, *, channel_id: str, user_id: str, tracker: NudgeTracker) -> list[agent.Tool]:
        # Recall is intentionally scoped to the requesting Discord channel.
        tools = [*self.base_tools, build_recall_tool(self.store, channel_id=channel_id)]
        if self.cfg.github_dispatch_token and self.cfg.github_repo:
            tools.append(
                build_save_to_kb_tool(
                    token=self.cfg.github_dispatch_token,
                    repo=self.cfg.github_repo,
                    action=self.cfg.save_note_action,
                    requested_by=user_id,
                    channel_id=channel_id,
                )
            )
        # Cross-channel recall is a privileged path: only surface it to admins, and only when enabled.
        if self.cfg.workspace_recall_enabled and self._is_admin(user_id):
            tools.append(build_workspace_recall_tool(self.store))
        # Proactive operational memory + procedural skills (the in-turn half of self-improvement).
        # target=agent is ungated; target=user stays gated by memory_allow_writes + admins.
        tools.append(
            build_remember_tool(
                self.memory,
                user_id=user_id,
                admins=self.cfg.memory_admins,
                allow_user_writes=self.cfg.memory_allow_writes,
                on_agent_write=tracker.note_memory_write,
            )
        )
        tools.append(build_skill_manage_tool(self.skills, on_write=tracker.note_skill_write))
        # Scheduled automations: surfaced only to admins (the tool also re-checks).
        if self.cfg.cron_enabled and self._is_admin(user_id):
            tools.append(build_cronjob_tool(self.cron_store, user_id=user_id, admins=self.cfg.memory_admins, channel_id=channel_id))
        return tools

    async def setup_hook(self) -> None:
        register_commands(self)
        if self.cfg.cron_enabled:
            self.cron.use_asyncio_lock()  # now that an event loop exists
            self.loop.create_task(self._cron_loop())
        if self.cfg.discord_guild_id:
            guild = discord.Object(id=self.cfg.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)  # instant in one guild (global sync takes ~1h)
        else:
            synced = await self.tree.sync()
        log.info("Synced %d slash command(s)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s | personas: %s | notes: %d", self.user, ", ".join(self.personas.ids()), len(self.knowledge.notes))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None or self.user not in message.mentions:
            return

        # Strip the bot mention, then an optional "persona:" selector.
        content = message.clean_content
        content = re.sub(rf"@{re.escape(self.user.display_name)}", "", content).strip()
        persona_id: str | None = None
        if (m := _PERSONA_PREFIX.match(content)) and m.group(1).lower() in self.personas.prompts:
            persona_id = m.group(1).lower()
            content = content[m.end() :].strip()

        channel_persona = self.cfg.persona_by_channel.get(str(message.channel.id))
        resolved_id, system_prompt = self.personas.get(persona_id or channel_persona)

        if not content:
            await message.reply(f"Hi — I'm **{resolved_id}**. Ask me something about the knowledge base.")
            return

        async with message.channel.typing():
            reply = await self._answer(system_prompt, content, message)
        await message.reply(reply[:1900])  # Discord's 2000-char message limit, with headroom

    async def _answer(self, system_prompt: str, question: str, message: discord.Message) -> str:
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        self._log_store(channel_id, "user", question)
        history = await self._recent_history(message)
        tracker = self._tracker(channel_id)
        tracker.record_turn()
        try:
            reply = await agent.run_agent(
                api_key=self.cfg.openrouter_api_key,
                model=self.cfg.chat_model,
                system_prompt=self._system_prompt(system_prompt, tracker),
                user_message=question,
                tools=self._request_tools(channel_id=channel_id, user_id=user_id, tracker=tracker),
                history=history,
                max_iterations=self.cfg.max_iterations,
            )
            self._log_store(channel_id, "assistant", reply)
            self._spawn_review(history, question, reply, message.channel)
            return reply
        except Exception:  # noqa: BLE001 — surface a friendly error, log the detail
            log.exception("chat reply failed")
            return "⚠️ I hit an error talking to the model. Check the bot logs."

    def _spawn_review(self, history: list[dict[str, str]], question: str, reply: str, channel: Any) -> None:
        """Fire the background-review fork without blocking the reply. Best-effort; never raises."""
        if not self.cfg.review_enabled:
            return
        transcript = [*history, {"role": "user", "content": question}, {"role": "assistant", "content": reply}]
        asyncio.create_task(self._run_review(transcript, channel))

    async def _run_review(self, transcript: list[dict[str, str]], channel: Any) -> None:
        try:
            result = await run_background_review(
                api_key=self.cfg.openrouter_api_key,
                model=self.cfg.chat_model,
                memory=self.memory,
                skills=self.skills,
                transcript=transcript,
                max_iterations=self.cfg.review_max_iterations,
            )
        except Exception:  # noqa: BLE001 — the fork is best-effort; the user's reply already went out
            log.warning("background review failed", exc_info=True)
            return
        notice = result.notice()
        if notice and self.cfg.review_notify and channel is not None:
            try:
                await channel.send(f"{REVIEW_NOTICE_PREFIX} _{notice}_")
            except Exception:  # noqa: BLE001
                log.warning("could not post review notice", exc_info=True)

    async def _run_cron_job(self, job: Job) -> str | None:
        """Run a scheduled job as a normal agent turn (full toolset, incl. web)."""
        _, system_prompt = self.personas.get(job.persona)
        tracker = self._tracker(job.channel_id)
        self._log_store(job.channel_id, "user", f"[scheduled] {job.prompt}")
        reply = await agent.run_agent(
            api_key=self.cfg.openrouter_api_key,
            model=self.cfg.chat_model,
            system_prompt=self._system_prompt(system_prompt),
            user_message=job.prompt,
            tools=self._request_tools(channel_id=job.channel_id, user_id=job.created_by, tracker=tracker),
            max_iterations=self.cfg.max_iterations,
        )
        self._log_store(job.channel_id, "assistant", reply)
        return reply

    async def _deliver_cron(self, job: Job, text: str) -> None:
        channel = self.get_channel(int(job.channel_id))
        if channel is None:
            log.warning("cron job %s: channel %s not found for delivery", job.id, job.channel_id)
            return
        await channel.send(f"⏰ **{job.id}** · {job.schedule}\n{text[:1850]}")

    async def _cron_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.cron.tick()
            except Exception:  # noqa: BLE001 — the loop must survive any single tick failure
                log.warning("cron tick failed", exc_info=True)
            await asyncio.sleep(self.cfg.cron_tick_seconds)

    def _system_prompt(self, persona_prompt: str, tracker: NudgeTracker | None = None) -> str:
        prompt = persona_prompt + "\n\n" + agent.KNOWLEDGE_TOOL_GUIDANCE
        if self.web is not None:
            prompt += "\n\n" + agent.WEB_TOOL_GUIDANCE
        prompt += "\n\n" + agent.RECALL_GUIDANCE
        prompt += "\n\n" + agent.MEMORY_GUIDANCE + "\n\n" + self.memory.snapshot()
        skills_index = self.skills.index_text()
        if skills_index:
            prompt += "\n\n" + agent.SKILLS_GUIDANCE + "\n\n" + skills_index
        if tracker is not None and (nudge := tracker.take_nudge()):
            prompt += "\n\n" + nudge
        return prompt

    async def _recent_history(self, message: discord.Message) -> list[dict[str, str]]:
        turns = self.cfg.history_turns
        if turns <= 0:
            return []
        history: list[dict[str, str]] = []
        started = self.store.session_started_at(str(message.channel.id))
        async for prior in message.channel.history(limit=turns + 1, before=message):
            if started is not None and prior.created_at.timestamp() < started:
                continue
            if not prior.clean_content:
                continue
            # Skip our own non-conversational review notices so they don't pollute context.
            if prior.author == self.user and prior.clean_content.startswith(REVIEW_NOTICE_PREFIX):
                continue
            role = "assistant" if prior.author == self.user else "user"
            history.append({"role": role, "content": prior.clean_content})
        history.reverse()
        return history

    def _log_store(self, channel_id: str, role: str, content: str) -> None:
        try:
            self.store.log(channel_id, role, content)
        except Exception:  # noqa: BLE001
            log.warning("store log failed", exc_info=True)


def register_commands(bot: MMOBot) -> None:
    @bot.tree.command(name="ask", description="Ask a persona a question about the knowledge base.")
    @app_commands.describe(question="Your question", persona="Which persona to ask (optional)")
    async def ask(interaction: discord.Interaction, question: str, persona: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        _, system_prompt = bot.personas.get(persona)
        channel_id = str(interaction.channel_id)
        bot._log_store(channel_id, "user", question)
        tracker = bot._tracker(channel_id)
        tracker.record_turn()
        try:
            reply = await agent.run_agent(
                api_key=bot.cfg.openrouter_api_key,
                model=bot.cfg.chat_model,
                system_prompt=bot._system_prompt(system_prompt, tracker),
                user_message=question,
                tools=bot._request_tools(channel_id=channel_id, user_id=str(interaction.user.id), tracker=tracker),
                max_iterations=bot.cfg.max_iterations,
            )
            bot._log_store(channel_id, "assistant", reply)
            bot._spawn_review([], question, reply, interaction.channel)
        except Exception:  # noqa: BLE001
            log.exception("/ask failed")
            reply = "⚠️ I hit an error talking to the model. Check the bot logs."
        await interaction.followup.send(reply[:1900])

    @bot.tree.command(name="new", description="Start a fresh chat session in this channel.")
    async def new(interaction: discord.Interaction) -> None:
        bot.store.new_session(str(interaction.channel_id))
        await interaction.response.send_message(
            "🧵 Started a fresh session — earlier messages won't be used as context (still searchable via recall)."
        )

    @bot.tree.command(name="save", description="Save a link to the knowledge base (opens a PR).")
    @app_commands.describe(link="URL to save", note="Why it's interesting / what to capture")
    async def save(interaction: discord.Interaction, link: str, note: str = "") -> None:
        await interaction.response.defer(thinking=True)
        action = bot.cfg.action_map.get("save", "save_link")
        try:
            await dispatch.dispatch_action(
                token=bot.cfg.github_dispatch_token,
                repo=bot.cfg.github_repo,
                action=action,
                payload={
                    "link": link,
                    "note": note,
                    "requested_by": str(interaction.user),
                    "channel_id": str(interaction.channel_id),
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("/save dispatch failed")
            await interaction.followup.send("⚠️ Couldn't trigger the save action. Check the bot logs / dispatch token.")
            return
        await interaction.followup.send(f"📥 On it — running **{action}** for <{link}>. A PR will open in `{bot.cfg.github_repo}` shortly.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    bot = MMOBot(cfg)
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
