"""Cron schedule smoke test (no network, no Discord).

Registers a couple of jobs in a temp store and prints each job's next run time.

    uv run --no-project python cron_smoke.py
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from cron import CronStore, parse_schedule


def main() -> None:
    now = datetime(2026, 1, 1, 12, 0)
    with tempfile.TemporaryDirectory() as d:
        store = CronStore(Path(d) / "cron.json")
        store.add(schedule="daily 9am", prompt="Post a customer-feedback digest.", channel_id="123", persona=None, created_by="admin")
        store.add(schedule="weekly mon 9am", prompt="Scan competitors and summarize.", channel_id="123", persona=None, created_by="admin")
        store.add(schedule="every 2 hours", prompt="Check for new mentions.", channel_id="123", persona=None, created_by="admin")

        print(f"now = {now}\n")
        for job in store.list():
            schedule = parse_schedule(job.schedule)
            nxt = schedule.next_run(now) if hasattr(schedule, "next_run") else "?"
            print(f"{job.summary()}\n    next run after now: {nxt}\n")


if __name__ == "__main__":
    main()
