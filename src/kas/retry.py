"""Bounded retry and escalation (AC-11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Attempt:
    number: int
    ok: bool
    diagnostics: str | None = None


@dataclass
class RetryResult:
    value: Any = None
    attempts: list[Attempt] = field(default_factory=list)
    escalated: bool = False

    @property
    def ok(self) -> bool:
        return not self.escalated and bool(self.attempts) and self.attempts[-1].ok


def run_with_retry(
    task: Callable[[], Any],
    max_retries: int = 3,
    on_attempt: Callable[[Attempt], None] | None = None,
) -> RetryResult:
    """Run ``task`` up to ``1 + max_retries`` times.

    Returns the result, the full attempt list and whether it escalated. A caller that
    escalates must not schedule any further tasks on the same branch.
    """
    result = RetryResult()
    total = max_retries + 1
    for number in range(1, total + 1):
        try:
            value = task()
        except Exception as exc:  # noqa: BLE001 - escalation needs the raw failure
            attempt = Attempt(number=number, ok=False, diagnostics=f"{type(exc).__name__}: {exc}")
            result.attempts.append(attempt)
            if on_attempt is not None:
                on_attempt(attempt)
            if number == total:
                result.escalated = True
                return result
            continue
        attempt = Attempt(number=number, ok=True, diagnostics=None)
        result.attempts.append(attempt)
        if on_attempt is not None:
            on_attempt(attempt)
        result.value = value
        return result
    result.escalated = True
    return result
