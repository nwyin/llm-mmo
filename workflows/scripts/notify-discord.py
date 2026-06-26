#!/usr/bin/env python3
"""Post a short message back to Discord after an action finishes.

Two delivery modes, picked automatically:

1. **Originating channel** (preferred) — if DISCORD_BOT_TOKEN and CHANNEL_ID are set, post as the
   bot to that exact channel via the REST API. CHANNEL_ID comes from the dispatch client_payload,
   so the message lands wherever the user invoked the command (e.g. wherever they @mentioned the
   bot). Works for any channel the bot can see.
2. **Fixed channel** (fallback) — if only DISCORD_WEBHOOK_URL is set, post via that channel webhook.
   A webhook is bound to the single channel it was created in, so this always posts there.

No-op (and never fatal) if neither is configured, or if the post fails — the PR is already open by
the time this runs, so a notification problem must not fail the action.

Usage: notify-discord.py "message text"
"""

import json
import os
import sys
import urllib.error
import urllib.request


def _build_request(message: str) -> urllib.request.Request | None:
    """Pick a delivery mode from the environment and build the POST request (or None to skip)."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("CHANNEL_ID", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    body = json.dumps({"content": message[:1900]}).encode()

    if bot_token and channel_id:
        return urllib.request.Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=body,
            method="POST",
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
        )
    if webhook:
        return urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
    return None


def main():
    message = sys.argv[1] if len(sys.argv) > 1 else ""
    if not message:
        return
    req = _build_request(message)
    if req is None:
        print(
            "No DISCORD_BOT_TOKEN+CHANNEL_ID or DISCORD_WEBHOOK_URL set — "
            "skipping Discord notification."
        )
        return
    # Best-effort: the PR is already open by the time we get here, so a bad token, bad
    # webhook, or missing bot permission must NOT fail the action. Warn and exit 0.
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Discord notify: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(
            f"warning: Discord notify failed (HTTP {e.code}) — check the bot token / "
            "channel permission or DISCORD_WEBHOOK_URL. Skipping (not fatal).",
            file=sys.stderr,
        )
    except (urllib.error.URLError, OSError) as e:
        print(f"warning: Discord notify failed ({e}) — skipping (not fatal).", file=sys.stderr)


if __name__ == "__main__":
    main()
