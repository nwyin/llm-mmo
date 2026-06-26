"""STATE_DIR resolution + first-boot memory seeding."""

from __future__ import annotations

from pathlib import Path

import config

_REQUIRED = {
    "DISCORD_BOT_TOKEN": "x",
    "OPENROUTER_API_KEY": "x",
    "GITHUB_DISPATCH_TOKEN": "x",
    "GITHUB_REPO": "o/r",
}


def test_state_dir_env_override_places_all_mutable_state(monkeypatch, tmp_path: Path) -> None:
    for key, value in _REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "data"))

    cfg = config.load_config()

    state = (tmp_path / "data").resolve()
    assert cfg.state_dir == state
    assert cfg.store_path == state / "state.db"
    assert cfg.cron_path == state / "cron.json"
    assert cfg.memory_dir == state / "memory"
    assert cfg.skills_runtime_dir == state / "memory" / "skills"
    # Nothing mutable resolves back into the checkout.
    assert config.REPO_ROOT not in cfg.store_path.parents


def test_ensure_state_dir_seeds_memory_from_repo(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    runtime_skills = memory_dir / "skills"

    config._ensure_state_dir(memory_dir, runtime_skills)

    assert memory_dir.is_dir()
    assert runtime_skills.is_dir()
    # Seeded from the repo's tracked seed files.
    assert (memory_dir / "MEMORY.md").exists()
    assert (memory_dir / "USER.md").exists()


def test_ensure_state_dir_never_overwrites_live_memory(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    runtime_skills = memory_dir / "skills"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("§\nlive operational note\n", encoding="utf-8")

    config._ensure_state_dir(memory_dir, runtime_skills)

    assert "live operational note" in (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
