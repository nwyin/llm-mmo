"""Scheduled automations: a tiny job store + scheduler with no external dependencies.

Admins register jobs in natural language ("daily 9am", "weekly mon 9am") or a raw 5-field cron
expression. The scheduler ticks inside the running bot, runs each due job as an ordinary agent
turn, and delivers the result to a Discord channel. Jobs are persisted to a JSON file so they
survive restarts; a missed window simply doesn't fire (no catch-up storm).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Day-of-week names → cron dow (0 = Sunday … 6 = Saturday).
_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))  # min, hour, dom, mon, dow


class ScheduleError(ValueError):
    """Raised when a schedule spec cannot be parsed."""


@dataclass(frozen=True)
class CronSchedule:
    minute: str
    hour: str
    dom: str
    month: str
    dow: str

    @classmethod
    def parse(cls, expr: str) -> CronSchedule:
        fields = expr.split()
        if len(fields) != 5:
            raise ScheduleError(f"cron expression must have 5 fields, got {len(fields)}: {expr!r}")
        schedule = cls(*fields)
        # Validate every field eagerly so a bad job is rejected at creation time.
        probe = datetime(2024, 1, 1, 0, 0)
        for _ in range(5):
            schedule.matches(probe)
        return schedule

    def matches(self, dt: datetime) -> bool:
        cron_dow = (dt.weekday() + 1) % 7  # Python Mon=0..Sun=6 → cron Sun=0..Sat=6
        return (
            _match_field(dt.minute, self.minute, *_FIELD_BOUNDS[0])
            and _match_field(dt.hour, self.hour, *_FIELD_BOUNDS[1])
            and _match_field(dt.day, self.dom, *_FIELD_BOUNDS[2])
            and _match_field(dt.month, self.month, *_FIELD_BOUNDS[3])
            and _match_field(cron_dow, self.dow, *_FIELD_BOUNDS[4], dow=True)
        )

    def is_due(self, now: datetime, last_run: float | None) -> bool:
        if not self.matches(now):
            return False
        minute_start = now.replace(second=0, microsecond=0).timestamp()
        return last_run is None or last_run < minute_start

    def next_run(self, after: datetime) -> datetime | None:
        cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):  # search up to a year ahead
            if self.matches(cursor):
                return cursor
            cursor += timedelta(minutes=1)
        return None

    def describe(self) -> str:
        return f"cron({self.minute} {self.hour} {self.dom} {self.month} {self.dow})"


@dataclass(frozen=True)
class IntervalSchedule:
    seconds: int

    def is_due(self, now: datetime, last_run: float | None) -> bool:
        return last_run is None or (now.timestamp() - last_run) >= self.seconds

    def next_run(self, after: datetime, last_run: float | None = None) -> datetime:
        base = after if last_run is None else datetime.fromtimestamp(last_run)
        return base + timedelta(seconds=self.seconds)

    def describe(self) -> str:
        return f"every {self.seconds}s"


def _match_field(value: int, field_spec: str, min_v: int, max_v: int, *, dow: bool = False) -> bool:
    if field_spec == "*":
        return True
    for part in field_spec.split(","):
        try:
            if "/" in part:
                base, step_s = part.split("/")
                step = int(step_s)
                if step <= 0:
                    raise ScheduleError(f"step must be positive: {part!r}")
                if base in ("*", ""):
                    lo, hi = min_v, max_v
                elif "-" in base:
                    lo, hi = (int(x) for x in base.split("-"))
                else:
                    lo, hi = int(base), max_v
                if value in range(lo, hi + 1, step):
                    return True
            elif "-" in part:
                lo, hi = (int(x) for x in part.split("-"))
                if dow:
                    lo, hi = lo % 7, hi % 7
                if lo <= value <= hi:
                    return True
            else:
                target = int(part)
                if dow:
                    target %= 7  # cron allows 7 for Sunday
                if value == target:
                    return True
        except ValueError as exc:
            raise ScheduleError(f"invalid schedule field {field_spec!r}") from exc
    return False


def _parse_time(text: str) -> tuple[int, int]:
    cleaned = text.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", cleaned)
    if not m:
        raise ScheduleError(f"could not parse time: {text!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"time out of range: {text!r}")
    return hour, minute


def parse_schedule(spec: str) -> CronSchedule | IntervalSchedule:
    """Parse a natural-language shortcut or a 5-field cron expression. Raises ScheduleError."""
    s = (spec or "").strip().lower()
    if not s:
        raise ScheduleError("schedule is empty")

    if m := re.fullmatch(r"every\s+(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h)", s):
        n = int(m.group(1))
        unit = m.group(2)
        if n <= 0:
            raise ScheduleError("interval must be positive")
        seconds = n * (3600 if unit.startswith("h") else 60)
        return IntervalSchedule(seconds=seconds)

    if s == "hourly":
        return CronSchedule.parse("0 * * * *")
    if s == "daily":
        return CronSchedule.parse("0 9 * * *")

    if m := re.fullmatch(r"daily\s+(.+)", s):
        hour, minute = _parse_time(m.group(1))
        return CronSchedule.parse(f"{minute} {hour} * * *")

    if m := re.fullmatch(r"weekly\s+(\w+)\s+(.+)", s):
        day = m.group(1)[:3]
        if day not in _DOW:
            raise ScheduleError(f"unknown weekday: {m.group(1)!r}")
        hour, minute = _parse_time(m.group(2))
        return CronSchedule.parse(f"{minute} {hour} * * {_DOW[day]}")

    return CronSchedule.parse(s)


@dataclass
class Job:
    id: str
    schedule: str
    prompt: str
    channel_id: str
    persona: str | None = None
    created_by: str = ""
    enabled: bool = True
    last_run: float | None = None

    def summary(self) -> str:
        state = "enabled" if self.enabled else "paused"
        target = f"#{self.channel_id}"
        persona = f" as {self.persona}" if self.persona else ""
        return f"{self.id} [{state}] {self.schedule} → {target}{persona}: {self.prompt[:60]}"


class CronStore:
    """JSON-file-backed job store. One row per job; ids are short sequential strings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._seq = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("jobs", []):
            job = Job(**row)
            self.jobs[job.id] = job
        self._seq = int(data.get("seq", len(self.jobs)))

    def _save(self) -> None:
        payload = {"seq": self._seq, "jobs": [asdict(job) for job in self.jobs.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, *, schedule: str, prompt: str, channel_id: str, persona: str | None, created_by: str) -> Job:
        self._seq += 1
        job_id = f"j{self._seq}"
        job = Job(id=job_id, schedule=schedule, prompt=prompt, channel_id=channel_id, persona=persona, created_by=created_by)
        self.jobs[job_id] = job
        self._save()
        return job

    def remove(self, job_id: str) -> bool:
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._save()
            return True
        return False

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        job = self.jobs.get(job_id)
        if job is None:
            return False
        job.enabled = enabled
        self._save()
        return True

    def mark_run(self, job_id: str, when: float) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.last_run = when
            self._save()

    def list(self) -> list[Job]:
        return list(self.jobs.values())


class CronScheduler:
    """Selects due jobs and runs them. Marking-before-running + a lock prevents double-fire."""

    def __init__(
        self,
        store: CronStore,
        *,
        runner: Callable[[Job], Awaitable[str | None]],
        deliver: Callable[[Job, str], Awaitable[None]],
        now_fn: Callable[[], datetime] | None = None,
        on_error: Callable[[Job, Exception], None] | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.deliver = deliver
        self._now_fn = now_fn or datetime.now
        self._on_error = on_error
        self._lock: Any = _NullLock()

    def use_asyncio_lock(self) -> None:
        import asyncio

        self._lock = asyncio.Lock()

    def due_jobs(self, now: datetime) -> list[Job]:
        due: list[Job] = []
        for job in self.store.list():
            if not job.enabled:
                continue
            try:
                schedule = parse_schedule(job.schedule)
            except ScheduleError:
                continue  # a malformed stored job never fires
            if schedule.is_due(now, job.last_run):
                due.append(job)
        return due

    async def tick(self, now: datetime | None = None) -> list[Job]:
        moment = now or self._now_fn()
        async with self._lock:
            due = self.due_jobs(moment)
            for job in due:
                # Mark before running so a concurrent/overlapping tick won't re-select it.
                self.store.mark_run(job.id, moment.timestamp())
        for job in due:
            try:
                result = await self.runner(job)
            except Exception as exc:  # noqa: BLE001 — one bad job must not stop the scheduler
                if self._on_error is not None:
                    self._on_error(job, exc)
                continue
            if result:
                try:
                    await self.deliver(job, result)
                except Exception as exc:  # noqa: BLE001
                    if self._on_error is not None:
                        self._on_error(job, exc)
        return due


class _NullLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> bool:
        return False
