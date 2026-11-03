from __future__ import annotations

import json
from pathlib import Path

from kas.status import StatusRecord, is_consistent


def sample() -> StatusRecord:
    return StatusRecord(
        project_id="reels-demo",
        phase="Phase 1 — Foundation implemented",
        completed=["manifest validated", "config validated"],
        evidence=["pytest tests/"],
        decisions=["ADR-004", "ADR-005", "ADR-006"],
        risks=["pipeline not implemented"],
        remaining=["Phase 2 adapters"],
        next_task="youtube adapter",
        updated_at="2026-11-02T18:00:00Z",
    )


REQUIRED_SECTIONS = (
    "## Current phase",
    "## Completed",
    "## Evidence",
    "## Decisions",
    "## Risks / issues",
    "## Remaining work",
    "## Next executable task",
    "## Last updated",
)


def test_write_creates_both_files_and_is_consistent(tmp_path: Path) -> None:
    written = sample().write(tmp_path)
    assert {p.name for p in written} == {"status.json", "status.md"}
    assert (tmp_path / "status.json").is_file()
    assert (tmp_path / "docs" / "status" / "status.md").is_file()
    assert is_consistent(tmp_path) is True


def test_markdown_contains_every_required_section(tmp_path: Path) -> None:
    record = sample()
    record.write(tmp_path)
    text = (tmp_path / "docs" / "status" / "status.md").read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in text
    assert "reels-demo" in text
    assert "2026-11-02T18:00:00Z" in text


def test_json_roundtrip(tmp_path: Path) -> None:
    record = sample()
    record.write(tmp_path)
    loaded = StatusRecord.read(tmp_path)
    assert loaded == record


def test_json_keys_match_record(tmp_path: Path) -> None:
    record = sample()
    record.write(tmp_path)
    data = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert set(data) == {
        "project_id",
        "phase",
        "completed",
        "evidence",
        "decisions",
        "risks",
        "remaining",
        "next_task",
        "updated_at",
        "schema_version",
    }


def test_idempotent_write(tmp_path: Path) -> None:
    record = sample()
    record.write(tmp_path)
    first = (tmp_path / "docs" / "status" / "status.md").read_bytes()
    record.write(tmp_path)
    assert (tmp_path / "docs" / "status" / "status.md").read_bytes() == first


def test_tampered_markdown_is_detected(tmp_path: Path) -> None:
    record = sample()
    record.write(tmp_path)
    md = tmp_path / "docs" / "status" / "status.md"
    md.write_text(md.read_text(encoding="utf-8").replace("Phase 1", "Phase 9"), encoding="utf-8")
    assert is_consistent(tmp_path) is False


def test_empty_lists_render_as_none(tmp_path: Path) -> None:
    record = StatusRecord(project_id="p", phase="Phase 0", updated_at="2026-11-02T00:00:00Z")
    record.write(tmp_path)
    text = (tmp_path / "docs" / "status" / "status.md").read_text(encoding="utf-8")
    assert "- none" in text
    assert "none" in text
