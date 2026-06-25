# `_template` — scaffold for a new agent

This directory is **not an agent**. It's a starting point you copy. Anything under a
`_`-prefixed directory is ignored by the registries (`actions.toml`, `review-routing.toml`) —
never register `_template` itself.

## Make a new action by hand

```bash
cp -r workflows/agents/_template workflows/agents/<id>     # <id> = ^[a-z0-9_]+$
$EDITOR workflows/agents/<id>/PROMPT.md                    # rewrite for your task
```

Then do the two registry steps in the **`creating-workflows` skill**
([`../../../.claude/skills/creating-workflows/SKILL.md`](../../../.claude/skills/creating-workflows/SKILL.md)):
add the agent to `opencode.json` and register it in `actions.toml`. That skill has copy-paste
snippets and the invariants you must keep, and your coding agent auto-loads it when you ask.

## …or let an agent do it

Dispatch the **`new_action`** meta-agent with a plain-English description in the `note` field
and it scaffolds all of the above for you and opens a PR. See
[`../new_action/PROMPT.md`](../new_action/PROMPT.md).
