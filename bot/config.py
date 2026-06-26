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
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"


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
    state_dir: Path
    store_path: Path
    memory_dir: Path
    memory_max_chars: int
    memory_allow_writes: bool
    # Workspace admins. Privileged tools (cron, workspace_recall, skill_manage, user-profile
    # memory) fail CLOSED when this is empty — an unset list means "no admins", never "everyone".
    admin_ids: tuple[str, ...]
    skills_dir: Path
    web_provider: str
    web_api_key: str
    web_timeout: int
    web_max_chars: int
    web_max_results: int
    workspace_recall_enabled: bool
    save_note_action: str
    skills_runtime_dir: Path
    review_enabled: bool
    review_notify: bool
    review_max_iterations: int
    review_interval: int
    nudge_memory_interval: int
    nudge_skill_interval: int
    cron_enabled: bool
    cron_path: Path
    cron_tick_seconds: int
    action_map: dict[str, str] = field(default_factory=dict)


def _ensure_state_dir(memory_dir: Path, runtime_skills_dir: Path) -> None:
    """Create the state dirs and seed memory files from the repo on first boot.

    The repo's memory/*.md are SEEDS: when the state volume has no copy yet (fresh deploy),
    copy the seed in; thereafter the bot only ever writes the volume copy, so the two diverge
    safely and `git pull` of the checkout never touches live memory.
    """
    memory_dir.mkdir(parents=True, exist_ok=True)
    runtime_skills_dir.mkdir(parents=True, exist_ok=True)
    seed_dir = REPO_ROOT / "memory"
    for filename in ("MEMORY.md", "USER.md"):
        target = memory_dir / filename
        seed = seed_dir / filename
        if target.exists() or not seed.exists() or seed.resolve() == target.resolve():
            continue
        target.write_text(seed.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


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
    memory = raw.get("memory", {})
    # Canonical admin list. Prefer [admins].ids; fall back to the legacy [memory].admins so
    # existing configs keep working. Empty = no admins (privileged tools fail closed).
    admins_section = raw.get("admins", {})
    admin_ids = tuple(str(admin) for admin in admins_section.get("ids", memory.get("admins", [])))

    # All MUTABLE runtime state lives under STATE_DIR — a persistent volume in production —
    # kept OUT of the git checkout so a `git pull` of knowledge never conflicts with files the
    # bot writes. Default to a gitignored bot/.state for local dev; set STATE_DIR=/data to the
    # host volume in production. Everything mutable derives from it (no per-path knobs).
    state_dir_env = os.environ.get("STATE_DIR", "").strip()
    state_dir = Path(state_dir_env) if state_dir_env else BOT_DIR / ".state"
    if not state_dir.is_absolute():
        state_dir = BOT_DIR / state_dir
    state_dir = state_dir.resolve()
    store_path = state_dir / "state.db"
    cron_path = state_dir / "cron.json"
    memory_dir = state_dir / "memory"
    skills_runtime_dir = memory_dir / "skills"
    _ensure_state_dir(memory_dir, skills_runtime_dir)

    # Curated, git-tracked skills (read-only to the agent) stay in the checkout, not STATE_DIR.
    skills = raw.get("skills", {})
    skills_dir = Path(skills.get("dir", SKILLS_DIR))
    if not skills_dir.is_absolute():
        skills_dir = BOT_DIR / skills_dir
    skills_dir = skills_dir.resolve()
    review = raw.get("review", {})
    cron = raw.get("cron", {})

    guild = os.environ.get("DISCORD_GUILD_ID", "").strip()

    web = raw.get("web", {})
    web_provider = os.environ.get("WEB_SEARCH_PROVIDER", web.get("provider", "ddgs")).strip().lower()
    # Provider-specific API keys come from the environment, never config.toml.
    web_api_key = os.environ.get("TAVILY_API_KEY" if web_provider == "tavily" else "EXA_API_KEY", "").strip()

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
        state_dir=state_dir,
        store_path=store_path,
        memory_dir=memory_dir,
        memory_max_chars=int(memory.get("max_chars", 2000)),
        memory_allow_writes=bool(memory.get("allow_writes", False)),
        admin_ids=admin_ids,
        skills_dir=skills_dir,
        web_provider=web_provider,
        web_api_key=web_api_key,
        web_timeout=int(web.get("timeout_seconds", 20)),
        web_max_chars=int(web.get("max_chars", 8000)),
        web_max_results=int(web.get("max_results", 5)),
        workspace_recall_enabled=bool(raw.get("recall", {}).get("workspace_enabled", False)),
        save_note_action=str(raw.get("actions", {}).get("save_note", "save_note")),
        skills_runtime_dir=skills_runtime_dir,
        review_enabled=bool(review.get("enabled", True)),
        review_notify=bool(review.get("notify", True)),
        review_max_iterations=int(review.get("max_iterations", 4)),
        review_interval=max(1, int(review.get("interval", 3))),
        nudge_memory_interval=int(review.get("memory_nudge_interval", 10)),
        nudge_skill_interval=int(review.get("skill_nudge_interval", 10)),
        cron_enabled=bool(cron.get("enabled", True)),
        cron_path=cron_path,
        cron_tick_seconds=int(cron.get("tick_seconds", 60)),
        action_map={str(k): str(v) for k, v in raw.get("actions", {}).items()},
    )
