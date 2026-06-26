"""Token-usage accounting."""

from __future__ import annotations

from usage import UsageMeter


def test_meter_accumulates_across_calls() -> None:
    meter = UsageMeter()
    meter.record({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
    meter.record({"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60})

    assert meter.calls == 2
    assert meter.prompt_tokens == 150
    assert meter.completion_tokens == 30
    assert meter.total_tokens == 180
    assert "2 call(s)" in meter.summary()
    assert "180 tokens" in meter.summary()


def test_meter_derives_total_when_absent_and_tolerates_empty() -> None:
    meter = UsageMeter()
    meter.record({"prompt_tokens": 7, "completion_tokens": 3})  # no total_tokens
    meter.record({})  # empty usage (e.g. provider omitted it)

    assert meter.calls == 2
    assert meter.total_tokens == 10
