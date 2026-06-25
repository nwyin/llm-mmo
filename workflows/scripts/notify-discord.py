#!/usr/bin/env python3
"""Post a short message to a Discord channel webhook. No-op if no webhook is configured.

Used by agent-action.yml to tell the channel "your PR is ready" after an action finishes.
Usage: notify-discord.py "message text"   (reads DISCORD_WEBHOOK_URL from the environment)
"""

import json
import os
import sys
import urllib.request


def main():
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("DISCORD_WEBHOOK_URL not set — skipping Discord notification.")
        return
    message = sys.argv[1] if len(sys.argv) > 1 else ""
    if not message:
        return
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": message[:1900]}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        print(f"Discord notify: HTTP {resp.status}")


if __name__ == "__main__":
    main()
