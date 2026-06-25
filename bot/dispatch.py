"""Trigger GitHub Actions from Discord via the repository_dispatch API.

The bot does no heavy work itself: it packages the request into a client_payload and fires a
`repository_dispatch` event. `.github/workflows/agent-action.yml` listens for it, runs the
matching agent, and opens a PR. Keeping the bot a thin sensor means all the agent logic,
secrets, and write access live in GitHub, not on the bot's host.
"""

from __future__ import annotations

import httpx

# Single event type for all actions; the specific action is a field in the payload so we
# only need one workflow file. The workflow branches on client_payload.action.
EVENT_TYPE = "agent-action"


async def dispatch_action(
    *,
    token: str,
    repo: str,
    action: str,
    payload: dict[str, str],
) -> None:
    """Fire a repository_dispatch event. Raises httpx.HTTPError on failure.

    GitHub limits client_payload to 10 top-level properties and ~64KB — we send a flat,
    small dict (action + the user's input + who/where it came from), well within that.
    """
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {"event_type": EVENT_TYPE, "client_payload": {"action": action, **payload}}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()  # 204 No Content on success
