"""AC-10 — verification gate."""

from __future__ import annotations

import json
from pathlib import Path

from kas.verify import VerificationError, check_evidence, gate


def write_evidence(project: Path, task_id: str, result: str, criteria: list[str]) -> Path:
    directory = project / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.json"
    path.write_text(
        json.dumps({"task_id": task_id, "result": result, "criteria": criteria, "run_at": "2026-11-03T00:00:00Z"}),
        encoding="utf-8",
    )
    return path


def test_gate_passes_with_a_passing_artifact(tmp_path: Path) -> None:
    write_evidence(tmp_path, "t-1", "pass", ["AC-10"])

    assert check_evidence(tmp_path, "t-1", ["AC-10"]) == []
    gate(tmp_path, "t-1", ["AC-10"])  # no exception


def test_gate_fails_when_artifact_is_missing(tmp_path: Path) -> None:
    problems = check_evidence(tmp_path, "t-missing", ["AC-10"])

    assert problems and "missing" in problems[0]
    try:
        gate(tmp_path, "t-missing", ["AC-10"])
    except VerificationError as exc:
        assert exc.task_id == "t-missing"
    else:
        raise AssertionError("gate did not raise")


def test_gate_fails_when_result_is_not_pass(tmp_path: Path) -> None:
    write_evidence(tmp_path, "t-2", "fail", ["AC-10"])

    problems = check_evidence(tmp_path, "t-2")

    assert problems and "fail" in problems[0]
    try:
        gate(tmp_path, "t-2")
    except VerificationError:
        pass
    else:
        raise AssertionError("gate did not raise")


def test_gate_fails_when_criteria_are_not_covered(tmp_path: Path) -> None:
    write_evidence(tmp_path, "t-3", "pass", ["AC-03"])

    problems = check_evidence(tmp_path, "t-3", ["AC-10"])

    assert problems and "AC-10" in problems[0]
