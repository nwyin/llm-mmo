"""Cron scheduler tests: parsing, due selection, persistence, gating, no double-fire."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from cron import CronScheduler, CronStore, IntervalSchedule, ScheduleError, parse_schedule
from tools import build_cronjob_tool

# ---- schedule parsing -------------------------------------------------------


def test_parse_natural_language_shortcuts() -> None:
    assert parse_schedule("daily 9am").matches(datetime(2026, 1, 1, 9, 0))
    assert not parse_schedule("daily 9am").matches(datetime(2026, 1, 1, 10, 0))
    assert parse_schedule("daily 21:30").matches(datetime(2026, 1, 1, 21, 30))
    # weekly mon: 2026-06-01 is a Monday.
    assert parse_schedule("weekly mon 9am").matches(datetime(2026, 6, 1, 9, 0))
    assert not parse_schedule("weekly mon 9am").matches(datetime(2026, 6, 2, 9, 0))


def test_parse_interval() -> None:
    schedule = parse_schedule("every 2 hours")
    assert isinstance(schedule, IntervalSchedule)
    assert schedule.seconds == 7200


def test_parse_raw_cron_fields() -> None:
    schedule = parse_schedule("*/15 * * * *")
    assert schedule.matches(datetime(2026, 1, 1, 0, 0))
    assert schedule.matches(datetime(2026, 1, 1, 0, 15))
    assert not schedule.matches(datetime(2026, 1, 1, 0, 7))


def test_invalid_schedules_raise() -> None:
    for bad in ["", "every 0 minutes", "weekly funday 9am", "daily 99:99", "1 2 3", "a b c d e"]:
        with pytest.raises(ScheduleError):
            parse_schedule(bad)


def test_cron_next_run() -> None:
    schedule = parse_schedule("0 9 * * *")
    nxt = schedule.next_run(datetime(2026, 1, 1, 10, 0))
    assert nxt == datetime(2026, 1, 2, 9, 0)


def test_is_due_fires_once_per_minute() -> None:
    schedule = parse_schedule("0 9 * * *")
    now = datetime(2026, 1, 1, 9, 0)
    assert schedule.is_due(now, last_run=None)
    assert not schedule.is_due(now, last_run=now.timestamp())


# ---- store persistence ------------------------------------------------------


def test_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cron.json"
    store = CronStore(path)
    job = store.add(schedule="daily 9am", prompt="digest", channel_id="c1", persona=None, created_by="u1")

    reloaded = CronStore(path)
    assert job.id in {j.id for j in reloaded.list()}
    got = reloaded.list()[0]
    assert got.schedule == "daily 9am"
    assert got.channel_id == "c1"

    # ids keep climbing across reloads (no collision).
    assert reloaded.add(schedule="hourly", prompt="x", channel_id="c1", persona=None, created_by="u1").id != job.id


# ---- scheduler --------------------------------------------------------------


def test_due_jobs_skips_disabled_and_unmatched(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    store.add(schedule="0 9 * * *", prompt="morning", channel_id="c1", persona=None, created_by="u1")
    paused = store.add(schedule="0 9 * * *", prompt="paused", channel_id="c1", persona=None, created_by="u1")
    store.set_enabled(paused.id, False)
    store.add(schedule="0 18 * * *", prompt="evening", channel_id="c1", persona=None, created_by="u1")

    scheduler = CronScheduler(store, runner=_no_runner, deliver=_no_deliver)
    due = scheduler.due_jobs(datetime(2026, 1, 1, 9, 0))

    assert [j.prompt for j in due] == ["morning"]


def test_tick_runs_due_job_once_even_if_called_twice(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    store.add(schedule="0 9 * * *", prompt="digest", channel_id="c1", persona=None, created_by="u1")
    runs: list[str] = []
    delivered: list[str] = []

    async def runner(job):
        runs.append(job.id)
        return f"result for {job.id}"

    async def deliver(job, text):
        delivered.append(text)

    scheduler = CronScheduler(store, runner=runner, deliver=deliver)
    now = datetime(2026, 1, 1, 9, 0)

    async def go():
        await scheduler.tick(now)
        await scheduler.tick(now)  # same minute → must not re-fire

    asyncio.run(go())
    assert runs == ["j1"]
    assert delivered == ["result for j1"]


def test_tick_survives_a_failing_job(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    store.add(schedule="0 9 * * *", prompt="boom", channel_id="c1", persona=None, created_by="u1")
    errors: list[Exception] = []

    async def runner(job):
        raise RuntimeError("kaboom")

    async def deliver(job, text):  # pragma: no cover - never reached
        raise AssertionError

    scheduler = CronScheduler(store, runner=runner, deliver=deliver, on_error=lambda j, e: errors.append(e))
    asyncio.run(scheduler.tick(datetime(2026, 1, 1, 9, 0)))

    assert len(errors) == 1


# ---- tool gating ------------------------------------------------------------


def test_cronjob_tool_blocks_non_admin(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    tool = build_cronjob_tool(store, user_id="999", admins=("123",), channel_id="c1")

    result = tool.handler({"action": "create", "schedule": "daily 9am", "prompt": "x"})
    assert result.startswith("error:")
    assert store.list() == []


def test_cronjob_tool_create_list_pause_delete(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    tool = build_cronjob_tool(store, user_id="123", admins=("123",), channel_id="c1")

    created = tool.handler({"action": "create", "schedule": "daily 9am", "prompt": "digest"})
    assert created.startswith("ok:")
    assert "digest" in tool.handler({"action": "list"})

    job_id = store.list()[0].id
    assert tool.handler({"action": "pause", "id": job_id}).startswith("ok:")
    assert store.list()[0].enabled is False
    assert tool.handler({"action": "delete", "id": job_id}).startswith("ok:")
    assert store.list() == []


def test_cronjob_tool_fails_closed_with_no_admins(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    tool = build_cronjob_tool(store, user_id="123", admins=(), channel_id="c1")

    result = tool.handler({"action": "create", "schedule": "daily 9am", "prompt": "x"})
    assert result.startswith("error:")
    assert store.list() == []


def test_cronjob_tool_rejects_disallowed_target_channel(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    tool = build_cronjob_tool(
        store,
        user_id="123",
        admins=("123",),
        channel_id="c1",
        channel_allowed=lambda cid: cid == "c1",  # only the current channel is reachable
    )

    blocked = tool.handler({"action": "create", "schedule": "daily 9am", "prompt": "x", "channel_id": "999"})
    assert blocked.startswith("error:")
    assert store.list() == []

    # The current channel is always allowed even though it is not in the allow-set explicitly.
    ok = tool.handler({"action": "create", "schedule": "daily 9am", "prompt": "x"})
    assert ok.startswith("ok:")
    assert store.list()[0].channel_id == "c1"


def test_cronjob_tool_rejects_bad_schedule(tmp_path: Path) -> None:
    store = CronStore(tmp_path / "cron.json")
    tool = build_cronjob_tool(store, user_id="123", admins=("123",), channel_id="c1")

    result = tool.handler({"action": "create", "schedule": "every blue moon", "prompt": "x"})
    assert result.startswith("error:")
    assert store.list() == []


async def _no_runner(job):  # pragma: no cover - placeholder
    return None


async def _no_deliver(job, text):  # pragma: no cover - placeholder
    return None
