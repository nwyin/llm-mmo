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

The two copies are byte-identical. Keep them in sync — but both are thin pointers, so the real
content lives in `workflows/AUTHORING.md`; edit that for anything substantive. (On a Unix-only
team you could replace the `.agents/skills/` copy with a symlink to drop the duplication; we keep
a real file so the template stays Windows-clone-safe.)
