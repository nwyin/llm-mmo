"""Nudge counter logic: fires at the interval, resets on write."""

from __future__ import annotations

from nudge import MEMORY_NUDGE, SKILL_NUDGE, NudgeTracker


def test_no_nudge_before_interval() -> None:
    tracker = NudgeTracker(memory_interval=3, skill_interval=3)
    for _ in range(2):
        tracker.record_turn()
        assert tracker.take_nudge() is None


def test_memory_nudge_fires_at_interval_then_resets() -> None:
    tracker = NudgeTracker(memory_interval=3, skill_interval=100)
    for _ in range(3):
        tracker.record_turn()
    nudge = tracker.take_nudge()
    assert nudge is not None
    assert MEMORY_NUDGE in nudge
    assert SKILL_NUDGE not in nudge
    # Reset after firing — does not fire again immediately.
    tracker.record_turn()
    assert tracker.take_nudge() is None


def test_write_resets_counter_so_it_does_not_fire() -> None:
    tracker = NudgeTracker(memory_interval=3, skill_interval=100)
    tracker.record_turn()
    tracker.record_turn()
    tracker.note_memory_write()  # write resets the counter
    tracker.record_turn()
    assert tracker.take_nudge() is None


def test_skill_and_memory_fire_independently() -> None:
    tracker = NudgeTracker(memory_interval=2, skill_interval=4)
    for _ in range(2):
        tracker.record_turn()
    first = tracker.take_nudge()
    assert first is not None and MEMORY_NUDGE in first and SKILL_NUDGE not in first

    for _ in range(2):
        tracker.record_turn()
    second = tracker.take_nudge()
    # memory fired again at turn 4 (reset at 2), and skill fires at turn 4 for the first time.
    assert second is not None and MEMORY_NUDGE in second and SKILL_NUDGE in second


def test_zero_interval_disables_nudge() -> None:
    tracker = NudgeTracker(memory_interval=0, skill_interval=0)
    for _ in range(50):
        tracker.record_turn()
    assert tracker.take_nudge() is None
