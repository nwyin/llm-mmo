<!--
  TEMPLATE — copy this directory to agents/<your-action-id>/ and rewrite it.
  Leading-underscore directories are scaffolding and are NEVER registered as agents.
  Full spec: the `creating-workflows` skill   ·   Working example: ../save_link/PROMPT.md
  Delete this comment when you adapt it.
-->

# <Action name> agent

Your job: <one or two sentences — what this action accomplishes and what it leaves behind in
the knowledge base>. You write files into the repository; the surrounding script handles the
git commit and PR. The shared house rules in SHARED.md apply (don't repeat them here).

## Input

Your task message contains:
- `link` — <what the URL means for this action, or "unused">.
- `note` — the user's free-text intent / details (may be empty).
- `requested_by` — who asked (for attribution).

## What to do

1. <First concrete step — e.g. identify / fetch / validate the input.>
2. <Do the work. Use your tools: `webfetch` for pages, `bash` for `curl`/file ops.>
3. **Write the result** as markdown under `knowledge/<area>/<slug>.md` (slug = short
   kebab-case). Follow the house style in SHARED.md: H1 title, then a `source` / `tags` /
   `saved` metadata block, then the content.
4. **Be honest about gaps.** If you couldn't fetch or verify something, say so in the file —
   never invent facts, metadata, or descriptions.
5. Pick a non-colliding filename; if the slug exists, append a short suffix.

## Output

After writing the files, output **only** a PR description in this exact shape — the script
parses the first line:

```
PR_TITLE: <short imperative title of what you did>

<2–4 sentence markdown summary: what you captured, what's in the new file(s), and any gaps.
List the files you created.>
```

If you could not produce anything useful, still output a `PR_TITLE:` line explaining why, and
do not create junk files.
