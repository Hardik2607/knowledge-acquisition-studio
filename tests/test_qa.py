"""AC-20…AC-23 — Derived notes, application report, QA report."""

from __future__ import annotations

import json
from pathlib import Path

from kas.cli import main
from kas.manifest import Manifest, Source
from kas.qa import (
    VERSION,
    build_application_report,
    build_derived,
    build_qa_report,
    run_phase5,
)


def make_dummy_project(project_dir: Path) -> Manifest:
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(
        project_id="qa-demo",
        goal="demonstrate QA phase",
        sources=(Source(kind="video", origin="https://example.com/v", title="Demo"),),
        path=project_dir / "manifest.yaml",
    )
    (project_dir / "manifest.yaml").write_text(
        "project_id: qa-demo\ngoal: demonstrate QA phase\nsources:\n"
        "  - kind: video\n    origin: https://example.com/v\n    title: Demo\n",
        encoding="utf-8",
    )
    # notes
    notes_dir = project_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_data = {
        "source_id": "src-1234567890ab",
        "notes": [
            {"source_id": "src-1234567890ab", "start": 0.0, "end": 2.0, "text": "Quoted fact"}
        ],
    }
    (notes_dir / "src-1234567890ab.json").write_text(json.dumps(notes_data), encoding="utf-8")

    # knowledge
    k_dir = project_dir / "knowledge"
    k_dir.mkdir(parents=True, exist_ok=True)
    units_data = {
        "units": [
            {
                "id": "k-abcdef123456",
                "statement": "Elephants have trunks",
                "source_refs": [{"source_id": "src-1234567890ab", "start": 0.0, "end": 2.0}],
                "confidence": "high",
            }
        ]
    }
    (k_dir / "units.json").write_text(json.dumps(units_data), encoding="utf-8")
    return manifest


def test_build_derived_notes_ac21(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    make_dummy_project(project_dir)

    written = build_derived(project_dir)
    assert len(written) == 1
    assert written[0].name == "k-abcdef123456.md"

    text = written[0].read_text(encoding="utf-8")
    assert "Original synthesis" in text
    assert "Elephants have trunks" in text
    assert "Source quote (attributed)" in text
    assert "Quoted fact" in text
    assert "src-1234567890ab" in text


def test_build_derived_notes_handles_empty_refs(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    make_dummy_project(project_dir)
    # Unit with no refs
    (project_dir / "knowledge" / "units.json").write_text(
        json.dumps({"units": [{"id": "k-empty", "statement": "Empty ref statement", "source_refs": []}]}),
        encoding="utf-8",
    )

    written = build_derived(project_dir)
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "Empty ref statement" in text
    assert "_Source: unknown_" in text


def test_build_application_report_ac20(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    manifest = make_dummy_project(project_dir)

    rep_path = build_application_report(project_dir, manifest)
    assert rep_path.is_file()
    text = rep_path.read_text(encoding="utf-8")
    assert "qa-demo" in text
    assert "k-abcdef123456" in text
    assert "Elephants have trunks" in text


def test_build_qa_report_ac23(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    manifest = make_dummy_project(project_dir)

    qa_path = build_qa_report(project_dir, manifest)
    assert qa_path.is_file()
    text = qa_path.read_text(encoding="utf-8")
    for i in range(1, 26):
        assert f"AC-{i:02d}" in text
    assert f"**Version:** {VERSION}" in text


def test_run_phase5_writes_evidence(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    manifest = make_dummy_project(project_dir)

    result = run_phase5(project_dir, manifest)
    assert len(result["derived"]) == 1
    assert result["application"].is_file()
    assert result["qa"].is_file()

    ev_dir = project_dir / "evidence"
    assert (ev_dir / "t-derived.json").is_file()
    assert (ev_dir / "t-application.json").is_file()
    assert (ev_dir / "t-qa.json").is_file()


def test_qa_cli(tmp_path: Path, capsys) -> None:
    project_dir = tmp_path / "proj"
    make_dummy_project(project_dir)

    code = main(["qa", "--project", str(project_dir)])
    assert code == 0
    out = capsys.readouterr().out
    assert "derived: 1 note(s)" in out
    assert "qa report:" in out
