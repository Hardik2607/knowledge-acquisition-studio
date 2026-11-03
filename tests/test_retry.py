"""AC-11 — bounded retry and escalation."""

from __future__ import annotations

import pytest

from kas.retry import run_with_retry


def test_succeeds_on_first_attempt() -> None:
    calls = {"n": 0}

    def task() -> str:
        calls["n"] += 1
        return "done"

    result = run_with_retry(task, max_retries=3)

    assert result.ok
    assert result.escalated is False
    assert result.value == "done"
    assert len(result.attempts) == 1
    assert calls["n"] == 1


def test_escalates_after_exactly_one_plus_max_retries_attempts() -> None:
    calls = {"n": 0}

    def task() -> str:
        calls["n"] += 1
        raise RuntimeError("boom")

    result = run_with_retry(task, max_retries=3)

    assert result.escalated is True
    assert result.ok is False
    assert len(result.attempts) == 4
    assert calls["n"] == 4
    assert all(not attempt.ok for attempt in result.attempts)
    assert "RuntimeError" in (result.attempts[-1].diagnostics or "")


def test_succeeds_on_the_third_attempt() -> None:
    calls = {"n": 0}

    def task() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    result = run_with_retry(task, max_retries=3)

    assert result.ok
    assert result.escalated is False
    assert result.value == "ok"
    assert len(result.attempts) == 3
    assert calls["n"] == 3
    assert result.attempts[0].ok is False
    assert result.attempts[1].ok is False
    assert result.attempts[2].ok is True


def test_max_retries_zero_means_a_single_attempt() -> None:
    calls = {"n": 0}

    def task() -> str:
        calls["n"] += 1
        raise RuntimeError("no retry allowed")

    result = run_with_retry(task, max_retries=0)

    assert result.escalated is True
    assert len(result.attempts) == 1
    assert calls["n"] == 1
