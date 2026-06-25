# Phase 5 spec — skills (index in prompt + skill_view tool)

Goal: surface the repo's existing agentskills.io skills to the bot. A compact name:description
**index** goes in the system prompt; the model loads a skill's full body **on demand** via a
`skill_view(name)` tool. We already ship `.agents/skills/<name>/SKILL.md`
(creating-workflows, getting-started), so this just reads them.

## Reference architecture (hermes-agent, `./hermes-agent/`)
- `agent/skill_utils.py` (parse_frontmatter, iter_skill_index_files), `agent/prompt_builder.py`
  (build_skills_system_prompt — the `## Skills` + `<available_skills>` index block), and the
  `skill_view` tool in `tools/skills_tool.py`. Take the SHAPE. SKIP: the 2-layer disk-snapshot
  cache, skill bundles, external dirs, config injection, inline-shell expansion, usage tracking,
  environment gating, curator.

## Zero new dependencies
Our SKILL.md frontmatter uses YAML with **block scalars** (`description: >-` spanning multiple
indented lines). There is no YAML parser in the stdlib and we are NOT adding pyyaml. Write a tiny
frontmatter reader that handles exactly what we use:
- Frontmatter is the block between the first two `---` fence lines at the top of the file.
- Parse top-level `key: value` pairs. If a value is `>-`, `>`, `|`, or `|-` (block scalar) or
  empty, gather the subsequent more-indented lines and join them (folded: join with spaces;
  literal `|`: join with newlines — folded is fine for our use, keep it simple and join with
  spaces, collapsing whitespace). Otherwise take the inline value (strip surrounding quotes).
- We only need `name` and `description`. Ignore everything else. Be tolerant: a missing
  frontmatter or missing field → skip that skill (don't crash).

---

## Implementation (single change set; reviewer will check parser + wiring separately)

### `bot/skills.py`
- `def parse_frontmatter(text: str) -> dict[str, str]` — the tiny reader above (name/description).
- `@dataclass(frozen=True) class Skill: name: str; description: str; path: Path` (path = the SKILL.md).
- `class SkillLibrary`:
  - `__init__(self, dir: Path)` — store dir; `self.reload()`.
  - `reload(self)` — discover `dir.rglob("SKILL.md")`; for each, parse frontmatter; keep those
    with a non-empty `name`; build `self.skills: dict[str, Skill]` keyed by name. Tolerate a
    missing dir (empty library).
  - `index_text(self) -> str` — if empty, return "" (caller omits the block). Else:
    ```
    ## Skills
    Load a skill with skill_view(name) when its description matches your task, then follow it.
    <available_skills>
    - <name>: <description, single line, truncated to ~200 chars>
    </available_skills>
    ```
  - `view(self, name: str) -> str` — look up by exact name; if unknown, return
    `"error: no skill named <name>. Available: <comma list>"`; else return the full SKILL.md
    text (frontmatter + body) read fresh. Lookup is by name only (no path input → no traversal risk).

### `bot/agent.py`
- Add `SKILLS_GUIDANCE` constant (concise): the system prompt lists available skills; when one
  matches the task, call `skill_view(name)` to load its instructions and follow them.

### `bot/tools.py`
- `build_skill_view_tool(skills: SkillLibrary) -> Tool` named `skill_view`, required `name`
  string param, sync handler returning `skills.view(name)`. Description: "Load the full
  instructions for a named skill from the index in your system prompt."

### `bot/config.py` / `config.toml`
- `[skills] dir = "../.agents/skills"` → `Config.skills_dir: Path` (resolve relative to BOT_DIR;
  default `REPO_ROOT / ".agents/skills"`).

### `bot/__main__.py`
- `__init__`: `self.skills = SkillLibrary(cfg.skills_dir)`; append `build_skill_view_tool(self.skills)`
  to `self.tools` (top-level only; delegate child unchanged).
- `_system_prompt`: append the skills index + guidance when the library is non-empty, e.g. after
  the memory snapshot: `+ ("\n\n" + agent.SKILLS_GUIDANCE + "\n\n" + idx if (idx := self.skills.index_text()) else "")`.
  Keep it readable.

### Tests `bot/tests/test_skills.py` (offline)
- `parse_frontmatter` handles a `description: >-` block scalar (multi-line) → single joined string,
  and an inline quoted `name`.
- `SkillLibrary` over a tmp dir with one SKILL.md: `index_text()` contains the name + description;
  `view(name)` returns the body; `view("nope")` returns the error.
- **Against the real repo skills**: `SkillLibrary(REPO_ROOT/".agents/skills")` discovers both
  `creating-workflows` and `getting-started` (guards our real frontmatter format).

## Acceptance
- `cd bot && uv run pytest -q` green; `uvx ruff check bot && uvx ruff format --check bot` clean.
- `uv --project bot run python -c "import bot.__main__; print('OK')"` prints OK.
- Minimalism: no YAML/Markdown deps; no caching; delegate child stays knowledge-only.
