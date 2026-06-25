# Knowledge base

Drop markdown files here. This is what the Discord bot reads to answer questions, and what
the action agents add to.

## How it's used

- **Chat:** when you ask a persona a question, the bot scores every `.md` file under this
  directory against your message (keyword match over the title + body) and feeds the top few
  to the model as context. Small bases are sent whole.
- **Actions:** agents write new files here (e.g. `save_link` creates entries under
  `thumbnail-ideas/`) and open a PR.

## Conventions (recommended, not enforced)

- One topic per file. Lots of small files retrieve better than a few huge ones.
- Start each file with an `# H1 title` and, optionally, a short front-matter-ish header:

  ```markdown
  # Cooking POV hook — fast cuts

  - **source:** https://youtu.be/...
  - **tags:** cooking, pov, hook
  - **saved:** 2026-06-25

  Notes go here...
  ```

- Use folders to group (`thumbnail-ideas/`, `competitors/`, `scripts/`). The retriever treats
  the path as searchable text, so good folder/file names improve matches.

## EXTENSION

Retrieval is intentionally simple (keyword scoring, no embeddings). When the base outgrows
that, swap `bot/knowledge.py`'s `search()` for an embedding index — the rest of the bot doesn't care
how files are ranked.
