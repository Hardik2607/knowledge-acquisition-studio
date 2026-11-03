"""End-to-end Phase 2 run with fakes: ingest → transcript → notes → evidence → status."""

from __future__ import annotations

import json
from pathlib import Path

from fakes import VTT, FakeAdapter, FakeTranscriber, Route, Phase3Client, vtt_transcript

from kas.config import load_config
from kas.ids import sha256_file
from kas.manifest import load_manifest
from kas.pipeline import build

YOUTUBE = "https://www.youtube.com/watch?v=abc123"
REEL = "https://www.instagram.com/reel/XYZ/"


def make_project(tmp_path: Path) -> tuple[object, Path]:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "manifest.yaml").write_text(
        "project_id: demo\ngoal: turn videos into notes\nsources:\n"
        f"  - kind: video\n    origin: {YOUTUBE}\n    title: A talk\n"
        f"  - kind: video\n    origin: {REEL}\n    title: A reel\n    cookies_from_browser: firefox\n",
        encoding="utf-8",
    )
    return load_manifest(project / "manifest.yaml"), project


def routes(reel_error: tuple[str, str] | None = None) -> dict[str, Route]:
    return {
        YOUTUBE: Route(
            payload=VTT.encode("utf-8"),
            filename="yt.en.vtt",
            media_type="text/vtt",
            transcript=vtt_transcript(),
        ),
        REEL: Route(
            payload=b"fake-audio-bytes",
            filename="reel.mp3",
            media_type="audio",
            error=reel_error,
        ),
    }


def test_build_produces_sources_transcripts_notes_evidence_and_status(tmp_path: Path) -> None:
    manifest, project = make_project(tmp_path)
    config = load_config(None)

    result = build(
        manifest,
        project,
        config,
        registry={"video": FakeAdapter(routes())},
        transcriber=FakeTranscriber(),
        client=Phase3Client(),
    )

    assert result.ok, result.failures
    assert len(result.ingested.records) == 2
    assert len(result.transcripts) == 2
    assert len(result.notebooks) == 2

    source_dirs = sorted((project / "sources").glob("src-*"))
    assert len(source_dirs) == 2
    for directory in source_dirs:
        source_id = directory.name
        assert (directory / "source.json").is_file()
        assert (directory / "transcript.json").is_file()
        notes = json.loads((project / "notes" / f"{source_id}.json").read_text(encoding="utf-8"))
        assert notes["source_id"] == source_id
        assert notes["provider"] == "fake"
        assert notes["notes"]
        for bullet in notes["notes"]:
            assert bullet["source_id"] == source_id
            assert bullet["start"] < bullet["end"]

    assert (project / "knowledge" / "units.json").is_file()
    assert (project / "knowledge" / "source-map.json").is_file()
    assert list((project / "knowledge" / "procedures").glob("*.md"))

    for task in ("t-ingest", "t-transcribe", "t-notes", "t-knowledge"):
        evidence = json.loads((project / "evidence" / f"{task}.json").read_text(encoding="utf-8"))
        assert evidence["result"] == "pass", evidence
        assert evidence["artifacts"]
        assert evidence["run_at"].endswith("Z")

    status = json.loads((project / "status.json").read_text(encoding="utf-8"))
    assert status["phase"].startswith("Phase 3")
    assert "evidence/t-ingest.json" in status["evidence"]
    assert (project / "docs" / "status" / "status.md").is_file()


def test_build_rerun_is_idempotent_for_sources(tmp_path: Path) -> None:
    manifest, project = make_project(tmp_path)
    config = load_config(None)
    kwargs = dict(
        registry={"video": FakeAdapter(routes())},
        transcriber=FakeTranscriber(),
        client=Phase3Client(),
    )
    build(manifest, project, config, **kwargs)

    snapshots = {}
    for record in (project / "sources").glob("*/source.json"):
        data = json.loads(record.read_text(encoding="utf-8"))
        raw = project / data["raw_path"]
        snapshots[record.parent.name] = (
            record.read_bytes(),
            sha256_file(raw),
            raw.stat().st_mtime_ns,
        )

    second = build(manifest, project, config, **kwargs)

    assert second.ok, second.failures
    assert second.ingested.skipped
    assert len(list((project / "sources").glob("src-*"))) == 2
    for source_id, (record_bytes, raw_hash, raw_mtime) in snapshots.items():
        directory = project / "sources" / source_id
        data = json.loads((directory / "source.json").read_text(encoding="utf-8"))
        raw = project / data["raw_path"]
        assert (directory / "source.json").read_bytes() == record_bytes
        assert sha256_file(raw) == raw_hash
        assert raw.stat().st_mtime_ns == raw_mtime


def test_build_reports_a_quarantined_source_without_losing_the_rest(tmp_path: Path) -> None:
    manifest, project = make_project(tmp_path)
    config = load_config(None)

    result = build(
        manifest,
        project,
        config,
        registry={"video": FakeAdapter(routes(reel_error=("auth_expired", "login required")))},
        transcriber=FakeTranscriber(),
        client=Phase3Client(),
    )

    assert not result.ok
    assert any("auth_expired" in failure for failure in result.failures)
    assert len(result.ingested.records) == 1
    assert len(result.notebooks) == 1

    ingest_evidence = json.loads((project / "evidence" / "t-ingest.json").read_text(encoding="utf-8"))
    assert ingest_evidence["result"] == "fail"

    status = json.loads((project / "status.json").read_text(encoding="utf-8"))
    assert any("Quarantined" in risk for risk in status["risks"])
