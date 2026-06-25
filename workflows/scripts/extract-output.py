#!/usr/bin/env python3
"""Extract an agent's final text from opencode's `--format json` event stream.

opencode emits one JSON object per line. Text arrives as `{"type":"text","sessionID":...,
"part":{"id":...,"text":...}}` events, interleaved with tool/step/error events. Subagents emit
under different sessionIDs; only the root session's final text part is the agent's answer.

Prints that final text to stdout. Exits 1 (with a reason on stderr) if no text was found, so
the caller can treat an empty run as a failure instead of committing/posting nothing.
"""

import json
import sys


def extract(stream):
    root_session = None
    parts: dict[str, str] = {}
    last_part_id = None
    last_error = ""

    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        session_id = event.get("sessionID")
        if root_session is None and session_id:
            root_session = session_id

        etype = event.get("type", "")
        if etype == "error" and (session_id == root_session or root_session is None):
            err = event.get("error", {})
            last_error = err.get("data", {}).get("message", "") or err.get("name", "")
            continue
        if etype != "text" or session_id != root_session:
            continue

        part = event.get("part", {})
        part_id = part.get("id")
        text = part.get("text", "")
        if part_id and text:  # the same part is re-emitted as it grows; keep the latest
            parts[part_id] = text
            last_part_id = part_id

    final = parts.get(last_part_id, "") if last_part_id else ""
    return final.strip(), last_error


def main():
    text, last_error = extract(sys.stdin)
    if not text:
        print("extract-output: no text found in event stream", file=sys.stderr)
        if last_error:
            print(f"extract-output: last error event: {last_error}", file=sys.stderr)
        sys.exit(1)
    print(text)


if __name__ == "__main__":
    main()
