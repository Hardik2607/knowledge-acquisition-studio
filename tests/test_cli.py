"""CLI behaviour: AC-01 (invalid input writes nothing), AC-14, AC-18, Phase 2 wiring."""

from __future__ import annotations

import json
from pathlib import Path

from fakes import VTT, FakeAdapter, Route, vtt_transcript

from kas.cli import main
from kas.status import StatusRecord, is_consistent

YOUTUBE = "https://www.youtube.com/watch?v=abc"

VALID = f"""
project_id: reels-demo
goal: turn reels into publishable scripts
sources:
  - kind: video
    origin: {YOUTUBE}
    title: video one
"""

ARTIFACT_DIRS = ("sources", "notes", "knowledge", "derived", "application", "evidence", "reports")


def make_project(tmp_path: Path, manifest_text: str = VALID) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "manifest.yaml").write_text(manifest_text.lstrip(), encoding="utf-8")
    return project


def stub_build(monkeypatch) -> None:
    from kas.ingest import IngestSummary
    from kas.pipeline import BuildResult

    def fake_build(manifest, project_dir, config, registry=None, **kwargs):
        return BuildResult(ingested=IngestSummary(), transcripts={}, notebooks={}, failures=[])

    monkeypatch.setattr("kas.cli.run_build", fake_build)


def stub_registry(monkeypatch, origin: str = YOUTUBE) -> None:
    def registry(binary: str | None = None):
        return {
            "video": FakeAdapter(
                {
                    origin: Route(
                        payload=VTT.encode("utf-8"),
                        filename="clip.en.vtt",
                        media_type="text/vtt",
                        transcript=vtt_transcript(),
                    )
                }
            )
        }

    monkeypatch.setattr("kas.cli.default_registry", registry)


# ------------------------------------------------------------------ validation


def test_validate_ok(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    assert main(["validate", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "manifest ok: reels-demo (1 sources)" in out
    assert "config ok:" in out


def test_validate_missing_field_exits_2_and_writes_nothing(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path, "project_id: demo\nsources:\n  - kind: video\n    origin: x\n    title: t\n")
    assert main(["validate", "--project", str(project)]) == 2
    err = capsys.readouterr().err
    assert "goal:" in err
    for name in ARTIFACT_DIRS:
        assert not (project / name).exists(), f"{name} must not be created on invalid input"


def test_unknown_key_exits_2_with_path(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path, VALID + "extra: 1\n")
    assert main(["validate", "--project", str(project)]) == 2
    assert "extra" in capsys.readouterr().err


def test_run_invalid_writes_nothing(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path, "project_id: demo\n")
    assert main(["run", "--project", str(project)]) == 2
    assert not (project / "status.json").exists()
    for name in ARTIFACT_DIRS:
        assert not (project / name).exists()


def test_run_rejects_path_escape_before_writing(tmp_path: Path, capsys) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    project = make_project(
        tmp_path,
        f"project_id: demo\ngoal: g\nsources:\n  - kind: video\n    origin: {outside}\n    title: t\n",
    )

    assert main(["run", "--project", str(project)]) == 2

    assert "outside the project root" in capsys.readouterr().err
    for name in ARTIFACT_DIRS:
        assert not (project / name).exists()


# --------------------------------------------------------------------- running


def test_run_creates_status_and_dirs(tmp_path: Path, monkeypatch, capsys) -> None:
    stub_build(monkeypatch)
    project = make_project(tmp_path)

    assert main(["run", "--project", str(project)]) == 0

    assert (project / "status.json").is_file()
    assert (project / "docs" / "status" / "status.md").is_file()
    for name in ARTIFACT_DIRS:
        assert (project / name).is_dir()
    assert is_consistent(project) is True
    assert "phase 3 complete" in capsys.readouterr().out.lower()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert main(["run", "--project", str(project), "--dry-run"]) == 0
    assert not (project / "status.json").exists()
    for name in ARTIFACT_DIRS:
        assert not (project / name).exists()


def test_ingest_writes_a_source_record_and_evidence(tmp_path: Path, monkeypatch, capsys) -> None:
    stub_registry(monkeypatch)
    project = make_project(tmp_path)

    assert main(["ingest", "--project", str(project)]) == 0

    records = list((project / "sources").glob("*/source.json"))
    assert len(records) == 1
    evidence = json.loads((project / "evidence" / "t-ingest.json").read_text(encoding="utf-8"))
    assert evidence["result"] == "pass"
    assert evidence["criteria"] == ["AC-02", "AC-03", "AC-04"]
    assert "ingested: 1" in capsys.readouterr().out


# ---------------------------------------------------------------------- status


def test_status_write_then_read(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    assert main(["status", "--project", str(project), "--write"]) == 0
    capsys.readouterr()
    assert main(["status", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "## Current phase" in out
    assert "## Next executable task" in out


def test_status_write_does_not_reset_an_existing_phase(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    record = StatusRecord(project_id="reels-demo", phase="Phase 2 — kept", updated_at="2026-11-02T00:00:00Z")
    record.write(project)

    assert main(["status", "--project", str(project), "--write"]) == 0

    reloaded = StatusRecord.read(project)
    assert reloaded.phase == "Phase 2 — kept"


def test_status_detects_drift(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    main(["status", "--project", str(project), "--write"])
    md = project / "docs" / "status" / "status.md"
    md.write_text(md.read_text(encoding="utf-8").replace("Phase 1", "Phase X"), encoding="utf-8")
    assert main(["status", "--project", str(project)]) == 2
    assert "out of sync" in capsys.readouterr().err


def test_status_without_file_exits_3(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    assert main(["status", "--project", str(project)]) == 3


def test_init_scaffold(tmp_path: Path, capsys) -> None:
    project = tmp_path / "new"
    assert main(["init", "--project", str(project), "--name", "demo"]) == 0
    manifest = (project / "manifest.yaml").read_text(encoding="utf-8")
    assert "project_id: demo" in manifest
    for name in ("sources", "docs/status", "config"):
        assert (project / name).is_dir()


def test_init_refuses_non_empty(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert main(["init", "--project", str(project), "--name", "demo"]) == 3


def test_daemon_install(tmp_path: Path, monkeypatch, capsys) -> None:
    project = make_project(tmp_path)
    # mock home directory to tmp_path so ~/.config/systemd/user is written inside tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["daemon", "--project", str(project), "--install"]) == 0
    unit = tmp_path / ".config" / "systemd" / "user" / "kas-daemon.service"
    assert unit.is_file()
    assert "ExecStart=" in unit.read_text(encoding="utf-8")


def test_run_with_all_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    stub_build(monkeypatch)
    project = make_project(tmp_path)
    vault = tmp_path / "vault"
    # mock config paths.vault to tmp_path / "vault"
    cfg = project / "config" / "kas.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"paths:\n  vault: {vault}\n", encoding="utf-8")

    assert main(["run", "--project", str(project), "--all"]) == 0
    out = capsys.readouterr().out
    assert "all phases complete" in out.lower()
    status = json.loads((project / "status.json").read_text(encoding="utf-8"))
    assert status["phase"].startswith("Phase 5")
