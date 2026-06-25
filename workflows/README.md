# Workflows — the agent half

Everything that *does work* runs here, in GitHub Actions, using [opencode](https://opencode.ai)
over [OpenRouter](https://openrouter.ai). Agents are defined by editable markdown prompts; the
shell scripts are thin orchestration. Same pattern as a CI code-review bot, pointed at a
markdown knowledge base.

## Layout

| Path | What |
|------|------|
| `AUTHORING.md` | **The spec for adding a workflow.** Read this before adding an action or reviewer. |
| `opencode.json` | Declares the agents (model, prompt file, permissions). |
| `agents/SHARED.md` | Rules injected into **every** agent (via opencode `instructions`). |
| `agents/_template/` | Scaffold you copy to start a new action (not a registered agent). |
| `agents/new_action/` | Meta-agent: scaffolds a brand-new workflow from a description, opens a PR. |
| `agents/<id>/PROMPT.md` | A single agent's system prompt. |
| `actions.toml` | Registry: which agent each dispatchable action runs. |
| `review-routing.toml` | Maps PR labels → reviewer agents. |
| `scripts/run-action.sh` | Runs an action agent, commits its output, opens a PR. |
| `scripts/run-review.sh` | Runs label-routed reviewer agent(s), posts a PR comment. |
| `scripts/lib.sh` | Shared: opencode auth, timeout wrapper, `run_opencode`. |
| `scripts/extract-output.py` | Pulls the agent's final text out of the JSON event stream. |
| `scripts/post-comment.py` | Posts/queries Knowledge review comments (with a turn cap). |
| `scripts/notify-discord.py` | Optional: posts the finished PR link back to a Discord webhook. |

## The two triggers

**Action** (`.github/workflows/agent-action.yml`) — fired by the bot's `repository_dispatch`:

```
repository_dispatch(agent-action, {action, link, note, ...})
  → run-action.sh <action>
      → opencode --agent <action>   (writes files into knowledge/)
      → git commit + gh pr create
      → notify-discord.py (optional)
```

**Review** (`.github/workflows/review.yml`) — fired on PR open/label/update:

```
pull_request
  → run-review.sh <pr> <repo> <base>
      → resolve agents from labels (review-routing.toml)
      → opencode --agent <reviewer>  (read-only)
      → post-comment.py
```

## Adding a workflow

Full instructions, copy-paste snippets, and the invariants live in
**[AUTHORING.md](AUTHORING.md)**. The short version:

**New action** (does work → opens a PR):

1. `cp -r agents/_template agents/<id>` and rewrite `PROMPT.md`. End it by telling the agent to
   emit a `PR_TITLE:` line (run-action.sh parses it).
2. Add the agent to `opencode.json` with the permissions it needs (writers get
   `write`/`edit`/`bash`; everything else denied).
3. Register it in `actions.toml`. If it writes outside `knowledge/`, set `add_paths`.
4. (Optional) Expose it as a slash command in `bot/config.toml` `[actions]`.

**New reviewer** (read-only → comments on PRs):

1. Create `agents/<id>/PROMPT.md` (emit a `## Knowledge Review` heading verbatim).
2. Add the agent to `opencode.json` (read/grep/glob allowed; write/bash denied).
3. Add a rule to `review-routing.toml`: `[labels.<label>] agent = "<id>"`.

PRs carrying that label get that reviewer; PRs with no matching label get the `[default]`
reviewer. Multiple matching labels run multiple reviewers and combine their comments.

## Let an agent add it for you

The **`new_action`** meta-agent does all of the above from a plain-English description. Dispatch
the `new_action` action with the description in the `note` field (e.g. *"add an action that
saves a competitor's landing page as a note under knowledge/competitors/"*) and it scaffolds the
prompt, edits `opencode.json` + the registry, self-checks the JSON/TOML, and opens a PR you
review like any other. It reads `AUTHORING.md` and `agents/_template/` to do this — so keeping
those accurate keeps the meta-agent accurate.

## Why a PAT for opening PRs?

A PR opened with the Actions-provided `GITHUB_TOKEN` does **not** trigger other workflows — so
`review.yml` would never fire on action-created PRs. `agent-action.yml` therefore opens PRs
with `secrets.PR_TOKEN` (a PAT) when available, falling back to `GITHUB_TOKEN` (PR opens, but
no automatic review) otherwise.

## Run locally

```bash
export OPENROUTER_API_KEY=sk-or-...
export GH_TOKEN=...                 # a PAT, for the PR
export GITHUB_REPO=youruser/yourfork
LINK="https://youtu.be/dQw4w9WgXcQ" NOTE="testing" REQUESTED_BY="me" \
  workflows/scripts/run-action.sh save_link
```

Tuning knobs (GitHub **Variables**): `AGENT_MODEL`, `MAX_REVIEW_TURNS`, `REVIEW_TIMEOUT`,
`ACTION_TIMEOUT`.
