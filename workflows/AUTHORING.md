# Authoring workflows

This is the **spec for adding a new event-driven workflow** to this repo. It's written so that
either a human or an agent can follow it end to end. The `new_action` meta-agent
(`agents/new_action/PROMPT.md`) reads this file and the `_template` to scaffold new actions on
its own.

There are two kinds of workflow, and they differ only in what they're allowed to do:

| Kind | Trigger | Permissions | Output | Runs via |
|------|---------|-------------|--------|----------|
| **Action** | Discord `repository_dispatch` | writes files, opens a PR | a `PR_TITLE:` block | `scripts/run-action.sh` → `agent-action.yml` |
| **Reviewer** | a PR is opened/labeled | **read-only** | a PR comment | `scripts/run-review.sh` → `review.yml` |

Both are just an opencode agent (a markdown prompt + a permission block) plus one or two lines
of registry config. The shell scripts are fixed plumbing — you almost never touch them.

---

## Anatomy of an action

An action turns a Discord request into a reviewable pull request. To add one named `<id>`
(must match `^[a-z0-9_]+$` — lowercase, digits, underscores):

### 1. Write the agent prompt — `agents/<id>/PROMPT.md`

Copy `agents/_template/PROMPT.md` and fill it in. The contract the prompt **must** honor:

- It describes a task that ends by **writing files into the repo** (under `knowledge/` unless
  this action declares a different `add_paths`).
- It ends by emitting, as the agent's final message, a PR block whose **first line** is
  `PR_TITLE:` — `run-action.sh` greps the first `^PR_TITLE:` line for the PR title and uses
  everything after it as the PR body:

  ```
  PR_TITLE: <short imperative title>

  <2–4 sentence markdown summary of what changed and any gaps. List the files touched.>
  ```

- `SHARED.md` (the house rules) is injected automatically — don't repeat it, build on it.

The task input reaches the agent as a templated message built by `run-action.sh` from the
dispatch payload. Available fields: **`link`**, **`note`**, **`requested_by`**, plus today's
date. (`note` is the free-text field — a flexible "what the user wants" channel. The
`new_action` meta-agent, for example, reads the desired spec out of `note`.)

### 2. Declare the agent — `opencode.json`

Add an entry under `"agent"`. Actions that write files need `write`/`edit` (and usually
`bash` for things like `curl`, and `webfetch` to pull pages). Keep everything else at the
repo-wide default (denied). Minimal write-capable action:

```json
"<id>": {
  "mode": "primary",
  "model": "openrouter/anthropic/claude-sonnet-4.6",
  "prompt": "{file:./agents/<id>/PROMPT.md}",
  "steps": 30,
  "permission": {
    "read": "allow", "grep": "allow", "glob": "allow",
    "webfetch": "allow", "bash": "allow", "edit": "allow", "write": "allow"
  }
}
```

### 3. Register the action — `actions.toml`

```toml
[<id>]
agent = "<id>"          # the opencode agent to run (defaults to the action id)
title = "Human title"   # used in the PR-title fallback and the Discord notification
target_dir = "knowledge/"   # informational hint to the agent
# add_paths = "knowledge/"  # what run-action.sh `git add`s + checks for changes.
                            # Default "knowledge/". Set this if the action writes
                            # elsewhere (e.g. "workflows/ knowledge/" for a meta-action).
```

> **`add_paths` is the one footgun.** `run-action.sh` only commits paths listed here, and only
> opens a PR if one of them changed. If your action writes outside `knowledge/` and you forget
> this, the run will report "no changes" and silently skip the PR. May be a space-separated
> string or a TOML list.

### 4. (Optional) Surface it in Discord — `bot/config.toml`

Map a friendly slash-command/keyword to the action under `[actions]`. Not required: any action
can be dispatched with its raw `<id>`. The free-text spec rides in the `note` field.

That's the whole action. No script edits.

---

## Anatomy of a reviewer

A reviewer reads a PR and comments. It never writes. To add one named `<id>`:

1. **`agents/<id>/PROMPT.md`** — a read-only reviewer prompt. It **must** start its final
   output with a `## Knowledge Review` heading (this exact string is how `run-review.sh` finds
   the comment and how `post-comment.py` tags it — keep it verbatim).
2. **`opencode.json`** — add the agent with `read`/`grep`/`glob` allowed and
   `write`/`edit`/`bash` **denied**:

   ```json
   "<id>": {
     "mode": "primary",
     "model": "openrouter/anthropic/claude-sonnet-4.6",
     "prompt": "{file:./agents/<id>/PROMPT.md}",
     "steps": 20,
     "permission": {
       "read": "allow", "grep": "allow", "glob": "allow", "websearch": "allow",
       "bash": "deny", "edit": "deny", "write": "deny"
     }
   }
   ```
3. **`review-routing.toml`** — route a PR label to it:

   ```toml
   [labels.<label>]
   agent = "<id>"
   ```

   PRs carrying `<label>` get this reviewer; PRs with no matching label get `[default]`.
   Multiple matching labels run multiple reviewers and combine their comments.

---

## Invariants (don't break these)

- **Agent ids** match `^[a-z0-9_]+$`. The id is the directory name and the opencode agent key.
- **Three coupled strings stay in lockstep** for reviews: the `## Knowledge Review` heading in
  every reviewer prompt, the `HEADING` in `scripts/post-comment.py`, and the grep in
  `scripts/run-review.sh`.
- **The `PR_TITLE:` first-line contract** for actions is parsed by `scripts/run-action.sh`.
- **Least privilege.** Reviewers are read-only. Actions get only the write/bash/webfetch they
  need. The repo-wide default in `opencode.json` denies write/edit/bash.
- **Every agent key in `opencode.json`** referenced by `actions.toml` or `review-routing.toml`
  must actually exist, or the run errors out.
- Directories beginning with `_` (like `_template`) are **scaffolding, not agents** — never
  register them.

## Verify before opening the PR

```bash
python3 -c "import json; json.load(open('workflows/opencode.json'))"   # valid JSON
python3 -c "import tomllib; tomllib.load(open('workflows/actions.toml','rb'))"
python3 -c "import tomllib; tomllib.load(open('workflows/review-routing.toml','rb'))"
bash -n workflows/scripts/run-action.sh                                 # script still parses
```

Dry-run an action locally (see the bottom of `README.md`):

```bash
LINK=... NOTE=... REQUESTED_BY=me workflows/scripts/run-action.sh <id>
```
