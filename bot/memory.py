"""Flat-file long-term memory store."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

TARGETS = {"agent": "MEMORY.md", "user": "USER.md"}

_DELIMITER = re.compile(r"(?m)^\s*§\s*$")


class MemoryStore:
    def __init__(self, dir: Path, *, max_chars: int) -> None:
        self.dir = dir
        self.max_chars = max_chars
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, target: str) -> Path:
        try:
            filename = TARGETS[target]
        except KeyError as exc:
            raise ValueError(f"unknown memory target: {target}") from exc
        return self.dir / filename

    def _entries(self, target: str) -> list[str]:
        path = self._path(target)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        _, body = _split_header(text)
        return _parse_entries(body)

    def _write(self, target: str, entries: list[str]) -> None:
        path = self._path(target)
        header, _ = _read_header(path)
        body = _render_entries(entries)
        text = body
        if header:
            text = header.rstrip() + ("\n\n" + body if body else "\n")

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def add(self, target: str, content: str) -> str:
        entries = self._entries(target)
        updated = [*entries, content.strip()]
        error = self._limit_error(target, updated)
        if error:
            return error
        self._write(target, updated)
        return f"ok: added memory to {target}"

    def replace(self, target: str, old_text: str, content: str) -> str:
        entries = self._entries(target)
        match = _single_match(entries, old_text)
        if match.error:
            return match.error

        updated = [*entries]
        updated[match.index] = content.strip()
        error = self._limit_error(target, updated)
        if error:
            return error
        self._write(target, updated)
        return f"ok: replaced memory in {target}"

    def remove(self, target: str, old_text: str) -> str:
        entries = self._entries(target)
        match = _single_match(entries, old_text)
        if match.error:
            return match.error

        updated = [entry for index, entry in enumerate(entries) if index != match.index]
        self._write(target, updated)
        return f"ok: removed memory from {target}"

    def apply(self, operations: list[dict[str, Any]]) -> str:
        staged = {target: self._entries(target) for target in TARGETS}
        changed: set[str] = set()

        for index, operation in enumerate(operations, start=1):
            action = operation.get("action")
            target = operation.get("target")
            if not isinstance(target, str):
                return f"error in operation {index}: target is required"
            if target not in TARGETS:
                return f"error in operation {index}: unknown memory target: {target}"

            entries = staged[target]
            if action == "add":
                content = str(operation.get("content", "")).strip()
                staged[target] = [*entries, content]
                changed.add(target)
            elif action == "replace":
                match = _single_match(entries, str(operation.get("old_text", "")))
                if match.error:
                    return f"error in operation {index}: {match.error}"
                content = str(operation.get("content", "")).strip()
                updated = [*entries]
                updated[match.index] = content
                staged[target] = updated
                changed.add(target)
            elif action == "remove":
                match = _single_match(entries, str(operation.get("old_text", "")))
                if match.error:
                    return f"error in operation {index}: {match.error}"
                staged[target] = [entry for entry_index, entry in enumerate(entries) if entry_index != match.index]
                changed.add(target)
            else:
                return f"error in operation {index}: unknown memory action: {action}"

        for target, entries in staged.items():
            error = self._limit_error(target, entries)
            if error:
                return error

        for target in TARGETS:
            if target in changed:
                self._write(target, staged[target])
        return f"ok: applied {len(operations)} memory operation(s)"

    def snapshot(self) -> str:
        agent = _render_snapshot_entries(self._entries("agent"))
        user = _render_snapshot_entries(self._entries("user"))
        return f"MEMORY (agent notes):\n{agent}\n\nUSER (profile):\n{user}"

    def _limit_error(self, target: str, entries: list[str]) -> str | None:
        total = len(_render_entries(entries))
        if total > self.max_chars:
            return f"error: {target} memory would exceed {self.max_chars} chars"
        return None


class _Match:
    def __init__(self, index: int = -1, error: str | None = None) -> None:
        self.index = index
        self.error = error


def _split_header(text: str) -> tuple[str, str]:
    if not text.startswith("<!--"):
        return "", text
    end = text.find("-->")
    if end == -1:
        return "", text
    end += len("-->")
    return text[:end], text[end:].lstrip()


def _read_header(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", ""
    return _split_header(path.read_text(encoding="utf-8", errors="replace"))


def _parse_entries(text: str) -> list[str]:
    return [entry.strip() for entry in _DELIMITER.split(text) if entry.strip()]


def _render_entries(entries: list[str]) -> str:
    return "\n\n§\n\n".join(entry.strip() for entry in entries if entry.strip())


def _single_match(entries: list[str], old_text: str) -> _Match:
    matches = [(index, entry) for index, entry in enumerate(entries) if old_text in entry]
    if not matches:
        return _Match(error=f"error: no entry matches {old_text!r}")
    if len(matches) > 1:
        candidates = "\n".join(f"- {entry}" for _, entry in matches)
        return _Match(error=f"error: multiple entries match {old_text!r}; candidates:\n{candidates}")
    return _Match(index=matches[0][0])


def _render_snapshot_entries(entries: list[str]) -> str:
    if not entries:
        return "(empty)"
    return "\n".join(f"- {entry}" for entry in entries)
