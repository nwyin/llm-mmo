---
name: creating-workflows
description: >-
  Add a new event-driven workflow to this repo — an "action" (does work and opens a PR) or a
  "reviewer" (comments on PRs). Use when creating or registering a new opencode agent under
  workflows/, wiring up a Discord-triggered action, or routing PR reviews by label.
license: MIT
---

# Creating workflows

This repo runs LLM agents two ways, and adding either is the same shape of task:

- **Action** — Discord `repository_dispatch` → an opencode agent writes files → opens a PR.
- **Reviewer** — a PR is opened/labeled → a read-only opencode agent → posts a PR comment.

Each is an opencode agent (a markdown prompt + a permission block in `workflows/opencode.json`)
plus one or two lines of registry config. The shell scripts under `workflows/scripts/` are fixed
plumbing — you almost never touch them.

## Authoritative spec

The full procedure, copy-paste JSON/TOML snippets, and the invariants you must not break live in
**`workflows/AUTHORING.md`**. Read it before editing — this skill is just the entry point. The
copyable scaffold for a new action is **`workflows/agents/_template/`**.

## Procedure (summary)

1. Decide the kind (action vs reviewer) and pick an id matching `^[a-z0-9_]+$`.
2. **Action:** `cp -r workflows/agents/_template workflows/agents/<id>` and rewrite `PROMPT.md`
   — it must end by emitting a `PR_TITLE:` first line.
   **Reviewer:** write a read-only prompt whose final output *starts with* the exact heading
   `## Knowledge Review`.
3. Declare the agent in `workflows/opencode.json` with least-privilege permissions (writers get
   `write`/`edit`/`bash`; reviewers get read-only).
4. Register it: actions in `workflows/actions.toml` (set `add_paths` if it writes outside
   `knowledge/`); reviewers as a label route in `workflows/review-routing.toml`.
5. Verify JSON/TOML parse and run the checks at the bottom of `workflows/AUTHORING.md`.

## Or let the meta-agent do it

To scaffold a workflow from a plain-English description without doing the above by hand, dispatch
the **`new_action`** meta-agent (`workflows/agents/new_action/PROMPT.md`) with the description in
the `note` field — it edits the prompt + registries and opens a PR you review.
