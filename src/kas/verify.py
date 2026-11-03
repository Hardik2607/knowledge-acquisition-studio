"""Verification gate (AC-10)."""

from __future__ import annotations

import json
from pathlib import Path


class VerificationError(Exception):
    def __init__(self, task_id: str, problems: list[str]):
        self.task_id = task_id
        self.problems = list(problems)
        super().__init__(f"verification gate failed for {task_id}: {'; '.join(problems)}")


def evidence_path(project_dir: Path, task_id: str) -> Path:
    return Path(project_dir) / "evidence" / f"{task_id}.json"


def check_evidence(project_dir: Path, task_id: str, criteria: list[str] | None = None) -> list[str]:
    """Return problems; empty means the gate passes."""
    path = evidence_path(project_dir, task_id)
    if not path.is_file():
        return [f"evidence artifact missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"evidence artifact unreadable: {exc}"]
    if data.get("result") != "pass":
        return [f"evidence result is {data.get('result')!r}, expected 'pass'"]
    if criteria:
        recorded = set(data.get("criteria") or [])
        missing = [c for c in criteria if c not in recorded]
        if missing:
            return [f"evidence does not cover {missing}"]
    return []


def gate(project_dir: Path, task_id: str, criteria: list[str] | None = None) -> None:
    problems = check_evidence(project_dir, task_id, criteria)
    if problems:
        raise VerificationError(task_id, problems)
