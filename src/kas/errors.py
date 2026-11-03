"""Structured validation errors.

Every failure carries the dotted path to the offending value, what was expected and
what was found. This is what makes AC-01 ("field-level errors") and AC-19 ("unknown
key rejection") verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldError:
    path: str
    expected: str
    got: str
    message: str = ""

    def render(self) -> str:
        base = f"{self.path}: expected {self.expected}, got {self.got}"
        return f"{base} — {self.message}" if self.message else base


class ValidationError(Exception):
    """Raised when a manifest or config fails schema validation."""

    def __init__(self, source: str, errors: list[FieldError]):
        self.source = source
        self.errors = list(errors)
        super().__init__(self.render())

    def render(self) -> str:
        lines = [f"invalid {self.source}: {len(self.errors)} problem(s)"]
        lines.extend(f"  - {e.render()}" for e in self.errors)
        return "\n".join(lines)


def type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "mapping"
    return type(value).__name__
