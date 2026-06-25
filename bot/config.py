"""Configuration loading: secrets from the environment, knobs from config.toml.

Repo layout is discovered relative to this file so the bot works regardless of the
current working directory (it reads ../knowledge and ../personas from the repo root).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
REPO_ROOT = BOT_DIR.parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
PERSONAS_DIR = REPO_ROOT / "personas"


@dataclass(frozen=True)
class Config:
    # secrets (env)
    discord_token: str
    openrouter_api_key: str
    github_dispatch_token: str
    github_repo: str
    discord_guild_id: int | None
    # knobs (config.toml)
    chat_model: str
    max_context_files: int
    max_context_chars: int
    history_turns: int
    max_iterations: int
    default_persona: str
    persona_by_channel: dict[str, str]
    pull_interval_seconds: int
    store_path: Path
    memory_dir: Path
    memory_max_chars: int
    action_map: dict[str, str] = field(default_factory=dict)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var {name}. Copy .env.example to .env and fill it in.")
    return value


def load_config() -> Config:
    load_dotenv(BOT_DIR / ".env")

    with (BOT_DIR / "config.toml").open("rb") as fh:
        raw = tomllib.load(fh)

    chat = raw.get("chat", {})
    personas = raw.get("personas", {})
    knowledge = raw.get("knowledge", {})
    store = raw.get("store", {})
    store_path = Path(store.get("path", "state.db"))
    if not store_path.is_absolute():
        store_path = BOT_DIR / store_path
    memory = raw.get("memory", {})
    memory_dir = Path(memory.get("dir", REPO_ROOT / "memory"))
    if not memory_dir.is_absolute():
        memory_dir = BOT_DIR / memory_dir
    memory_dir = memory_dir.resolve()

    guild = os.environ.get("DISCORD_GUILD_ID", "").strip()

    return Config(
        discord_token=_require("DISCORD_BOT_TOKEN"),
        openrouter_api_key=_require("OPENROUTER_API_KEY"),
        github_dispatch_token=_require("GITHUB_DISPATCH_TOKEN"),
        github_repo=_require("GITHUB_REPO"),
        discord_guild_id=int(guild) if guild.isdigit() else None,
        chat_model=chat.get("model", "anthropic/claude-sonnet-4.6"),
        max_context_files=int(chat.get("max_context_files", 6)),
        max_context_chars=int(chat.get("max_context_chars", 24000)),
        history_turns=int(chat.get("history_turns", 6)),
        max_iterations=int(chat.get("max_iterations", 6)),
        default_persona=personas.get("default", "default"),
        persona_by_channel={str(k): str(v) for k, v in personas.get("by_channel", {}).items()},
        pull_interval_seconds=int(knowledge.get("pull_interval_seconds", 0)),
        store_path=store_path,
        memory_dir=memory_dir,
        memory_max_chars=int(memory.get("max_chars", 2000)),
        action_map={str(k): str(v) for k, v in raw.get("actions", {}).items()},
    )
