# Skills

[Agent Skills](https://agentskills.io) — reusable, on-demand instructions for whatever coding
agent you run *locally* in this repo. A skill is a `<name>/SKILL.md` directory (YAML frontmatter
with `name` + `description`, then a markdown body). The agent loads it when your request matches
the description, or you invoke it directly (`/creating-workflows` in Claude Code, `$creating-workflows` in Codex).

> These are **local-dev** skills, separate from the repo's CI agents in `workflows/opencode.json`
> (those run headless in GitHub Actions and are configured there, not as skills).

## Why the same skill lives in two places

No single directory is read by all harnesses, so each skill is mirrored:

| Directory | Read by |
|-----------|---------|
| `.claude/skills/<name>/` | Claude Code, opencode |
| `.agents/skills/<name>/` | Codex, opencode |

The two copies are byte-identical and self-contained — when you change a skill, update both. We
keep a real file in each location (rather than a symlink) so the template stays Windows-clone-safe.
