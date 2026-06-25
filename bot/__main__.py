"""Discord bot entrypoint.

Run with:  uv run python -m bot

Handles two interaction styles:
  • @mention (gateway, free-form chat)  → answer inline using the knowledge base
  • /ask, /save (slash commands)        → structured chat / dispatch an action to GitHub
"""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands

import agent
import dispatch
from config import KNOWLEDGE_DIR, PERSONAS_DIR, Config, load_config
from knowledge import KnowledgeBase
from personas import Personas
from tools import build_delegate_tool, build_knowledge_tools

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
        self.tools = build_knowledge_tools(self.knowledge, max_files=cfg.max_context_files, max_chars=cfg.max_context_chars) + [
            build_delegate_tool(
                self.knowledge,
                max_files=cfg.max_context_files,
                max_chars=cfg.max_context_chars,
                api_key=cfg.openrouter_api_key,
                model=cfg.chat_model,
                max_iterations=cfg.max_iterations,
            )
        ]
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        register_commands(self)
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
        history = await self._recent_history(message)
        try:
            return await agent.run_agent(
                api_key=self.cfg.openrouter_api_key,
                model=self.cfg.chat_model,
                system_prompt=system_prompt + "\n\n" + agent.KNOWLEDGE_TOOL_GUIDANCE,
                user_message=question,
                tools=self.tools,
                history=history,
                max_iterations=self.cfg.max_iterations,
            )
        except Exception:  # noqa: BLE001 — surface a friendly error, log the detail
            log.exception("chat reply failed")
            return "⚠️ I hit an error talking to the model. Check the bot logs."

    async def _recent_history(self, message: discord.Message) -> list[dict[str, str]]:
        turns = self.cfg.history_turns
        if turns <= 0:
            return []
        history: list[dict[str, str]] = []
        async for prior in message.channel.history(limit=turns + 1, before=message):
            if not prior.clean_content:
                continue
            role = "assistant" if prior.author == self.user else "user"
            history.append({"role": role, "content": prior.clean_content})
        history.reverse()
        return history


def register_commands(bot: MMOBot) -> None:
    @bot.tree.command(name="ask", description="Ask a persona a question about the knowledge base.")
    @app_commands.describe(question="Your question", persona="Which persona to ask (optional)")
    async def ask(interaction: discord.Interaction, question: str, persona: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        _, system_prompt = bot.personas.get(persona)
        try:
            reply = await agent.run_agent(
                api_key=bot.cfg.openrouter_api_key,
                model=bot.cfg.chat_model,
                system_prompt=system_prompt + "\n\n" + agent.KNOWLEDGE_TOOL_GUIDANCE,
                user_message=question,
                tools=bot.tools,
                max_iterations=bot.cfg.max_iterations,
            )
        except Exception:  # noqa: BLE001
            log.exception("/ask failed")
            reply = "⚠️ I hit an error talking to the model. Check the bot logs."
        await interaction.followup.send(reply[:1900])

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
