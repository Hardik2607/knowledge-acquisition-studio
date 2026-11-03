"""AC-02 (unsupported kind), AC-03 (Source Record), AC-04 (raw immutability)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import VTT, FakeAdapter, Route, vtt_transcript

from kas.config import load_config
from kas.ids import sha256_file
from kas.ingest import ingest, load_source_records
from kas.manifest import load_manifest

YOUTUBE = "https://www.youtube.com/watch?v=abc123"
REEL = "https://www.instagram.com/reel/XYZ/"

REQUIRED_FIELDS = {
    "source_id",
    "kind",
    "origin",
    "title",
    "author",
    "retrieved_at",
    "checksum",
    "raw_path",
    "license",
    "status",
}


def make_project(tmp_path: Path, sources: str, project_id: str = "demo") -> tuple[object, Path]:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "manifest.yaml").write_text(
        f"project_id: {project_id}\ngoal: test goal\nsources:\n{sources}", encoding="utf-8"
    )
    return load_manifest(project / "manifest.yaml"), project


def subtitle_route() -> Route:
    return Route(
        payload=VTT.encode("utf-8"),
        filename="clip.en.vtt",
        media_type="text/vtt",
        transcript=vtt_transcript(),
    )


def test_source_record_is_complete_and_content_addressed(tmp_path: Path) -> None:
    manifest, project = make_project(
        tmp_path,
        f"""  - kind: video
    origin: {YOUTUBE}
    title: A talk
""",
    )
    summary = ingest(manifest, project, load_config(None), {"video": FakeAdapter({YOUTUBE: subtitle_route()})})

    assert summary.ok
    records = list((project / "sources").glob("*/source.json"))
    assert len(records) == 1
    data = json.loads(records[0].read_text(encoding="utf-8"))

    assert REQUIRED_FIELDS <= set(data)
    raw = project / data["raw_path"]
    assert raw.is_file()
    assert data["checksum"] == sha256_file(raw)
    assert data["source_id"] == f"src-{data['checksum'][:12]}"
    assert data["status"] == "ingested"
    assert data["kind"] == "video"
    assert data["origin"] == YOUTUBE

    transcript = json.loads((records[0].parent / "transcript.json").read_text(encoding="utf-8"))
    assert transcript["source_id"] == data["source_id"]


def test_reingest_identical_bytes_changes_nothing(tmp_path: Path) -> None:
    manifest, project = make_project(
        tmp_path,
        f"""  - kind: video
    origin: {YOUTUBE}
    title: A talk
""",
    )
    config = load_config(None)
    registry = {"video": FakeAdapter({YOUTUBE: subtitle_route()})}
    ingest(manifest, project, config, registry)

    record_path = next((project / "sources").glob("*/source.json"))
    before_record = record_path.read_bytes()
    raw = project / json.loads(before_record)["raw_path"]
    before_mtime = raw.stat().st_mtime_ns
    before_hash = sha256_file(raw)

    second = ingest(manifest, project, config, registry)

    assert second.ok
    assert second.records
    assert second.skipped
    assert sha256_file(raw) == before_hash
    assert raw.stat().st_mtime_ns == before_mtime
    assert record_path.read_bytes() == before_record
    assert len(list((project / "sources").glob("*/source.json"))) == 1


def test_same_origin_with_different_bytes_is_a_conflict(tmp_path: Path) -> None:
    manifest, project = make_project(
        tmp_path,
        f"""  - kind: video
    origin: {YOUTUBE}
    title: A talk
""",
    )
    config = load_config(None)
    ingest(
        manifest,
        project,
        config,
        {"video": FakeAdapter({YOUTUBE: subtitle_route()})},
    )
    record_path = next((project / "sources").glob("*/source.json"))
    first = json.loads(record_path.read_text(encoding="utf-8"))
    raw = project / first["raw_path"]
    first_bytes = raw.read_bytes()

    changed = Route(payload=b"completely different bytes", filename="clip.bin", media_type="audio")
    summary = ingest(manifest, project, config, {"video": FakeAdapter({YOUTUBE: changed})})

    assert not summary.ok
    assert "checksum_conflict" in summary.failed[0].reason
    assert raw.read_bytes() == first_bytes
    assert len(list((project / "sources").glob("*/source.json"))) == 1


def test_unsupported_kind_fails_alone(tmp_path: Path) -> None:
    manifest, project = make_project(
        tmp_path,
        f"""  - kind: epub
    origin: https://example.com/book.epub
    title: A book
  - kind: video
    origin: {YOUTUBE}
    title: A talk
""",
    )
    summary = ingest(manifest, project, load_config(None), {"video": FakeAdapter({YOUTUBE: subtitle_route()})})

    assert not summary.ok
    assert len(summary.records) == 1
    assert summary.failed[0].kind == "epub"
    assert "unsupported_kind:epub" in summary.failed[0].reason
    assert load_source_records(project)


def test_auth_failure_quarantines_instead_of_failing_the_run(tmp_path: Path) -> None:
    manifest, project = make_project(
        tmp_path,
        f"""  - kind: video
    origin: {REEL}
    title: A reel
    cookies_from_browser: firefox
  - kind: video
    origin: {YOUTUBE}
    title: A talk
""",
    )
    registry = {
        "video": FakeAdapter(
            {
                REEL: Route(payload=b"", error=("auth_expired", "login required")),
                YOUTUBE: subtitle_route(),
            }
        )
    }
    summary = ingest(manifest, project, load_config(None), registry)

    assert not summary.ok
    quarantined = [r for r in summary.failed if r.status == "quarantined"]
    assert quarantined and quarantined[0].origin == REEL
    assert len(summary.records) == 1
    assert (project / "evidence" / "ingest-failures.log").is_file()
