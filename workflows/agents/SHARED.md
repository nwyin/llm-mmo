# Shared agent rules

You are an agent operating on a **markdown knowledge base** stored in a git repository. The
knowledge base lives under `knowledge/`. Personas that chat about it live under `personas/`.

These rules apply to every agent in this repo, on top of your specific task prompt.

## Ground rules

- **Stay inside the repo.** Only read and write files within the checked-out repository.
- **Markdown only, in `knowledge/`.** New knowledge goes in `.md` files under `knowledge/`,
  organized into sensible subfolders. Binary assets (images) may accompany them.
- **Be honest.** Never fabricate facts, metadata, or descriptions. If you couldn't fetch or
  verify something, say so in the file and in your output rather than inventing it.
- **Small, focused files.** One topic per note. Good titles and paths (they're how the chat
  bot finds things later).
- **Don't touch unrelated files.** Make the minimal set of changes your task requires.
- **Cite sources.** When a note is derived from a URL, record the source URL in the note.

## House style for knowledge notes

Start each note with an H1 title, then a short metadata block, then the content:

```markdown
# <concise descriptive title>

- **source:** <url or origin>
- **tags:** <comma, separated, keywords>
- **saved:** <YYYY-MM-DD>

<the actual notes>
```

Tags and a descriptive title matter: the chat bot retrieves notes by keyword, so the words in
the title, path, and tags are what make a note findable later.
