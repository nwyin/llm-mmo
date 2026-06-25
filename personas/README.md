# Personas

Each `.md` file here is a **chatbot persona** — its system prompt. The filename (without
`.md`) is the persona's id.

## How to talk to one

- **Default persona:** just `@mention` the bot. It uses `default.md`.
- **A specific persona:** mention it by id at the start of your message, e.g.
  `@YourBot thumbnail-scout: what hooks are working for fitness?` — or set a per-channel
  default in `bot/config.toml`.
- **Slash command:** `/ask persona:thumbnail-scout question:...`

## Adding a persona

Create `personas/<id>.md`. The whole file becomes the system prompt. That's it — the bot picks
it up on next start (or on `git pull`, if you've enabled `pull_interval_seconds`).

Keep prompts focused:
- State the persona's voice and job in the first paragraph.
- Tell it it has access to a knowledge base of markdown notes (the bot injects matches).
- Tell it what to do when it doesn't know — usually "say so, don't invent."
- If the persona should *create* knowledge, point users at the `/save` action rather than
  having the chat persona pretend it can write files (it can't — only actions open PRs).

See `default.md` and `thumbnail-scout.md` for examples.
