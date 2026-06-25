# Skills

[Agent Skills](https://agentskills.io) — reusable, on-demand instructions for whatever coding
agent you run *locally* in this repo. A skill is a `<name>/SKILL.md` directory (YAML frontmatter
with `name` + `description`, then a markdown body). The agent loads it when your request matches
the description, or you invoke it directly (`/creating-workflows` in Claude Code, `$creating-workflows` in Codex).

> These are **local-dev** skills, separate from the repo's CI agents in `workflows/opencode.json`
> (those run headless in GitHub Actions and are configured there, not as skills).

## Why the same skill lives in two places

No single directory is read by all harnesses, so each skill is exposed in two:

| Directory | Read by |
|-----------|---------|
| `.agents/skills/<name>/` | Codex, opencode — **the real files live here** |
| `.claude/skills/<name>/` | Claude Code, opencode — a **symlink** to the `.agents/` copy |

There's a single source of truth: the skill content lives under `.agents/skills/`, and each
`.claude/skills/<name>` is a relative symlink to it, so editing one updates both. (The symlink is
repo-relative, so it survives "Use this template" and clones on macOS/Linux. On Windows, enable
symlink support — `git config --global core.symlinks true` with Developer Mode on — or replace
the link with a copy of the `.agents/` file.)
