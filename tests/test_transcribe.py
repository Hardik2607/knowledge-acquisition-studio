"""AC-05 — transcript normalization."""

from __future__ import annotations

import json
from pathlib import Path

from fakes import FakeAdapter, FakeTranscriber, Route

from kas.adapters.video import parse_vtt
from kas.config import load_config
from kas.ingest import ingest, load_source_records
from kas.manifest import load_manifest
from kas.models import Segment, Transcript
from kas.pipeline import transcribe_pending
from kas.transcribe import normalize_segments, validate_segments

REEL = "https://www.instagram.com/reel/XYZ/"


def make_reel_project(tmp_path: Path) -> tuple[object, Path]:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "manifest.yaml").write_text(
        "project_id: demo\ngoal: g\nsources:\n"
        f"  - kind: video\n    origin: {REEL}\n    title: A reel\n",
        encoding="utf-8",
    )
    return load_manifest(project / "manifest.yaml"), project


def test_parse_vtt_orders_and_cleans_cues() -> None:
    segments = parse_vtt(
        """WEBVTT
Kind: captions
Language: en

00:00:04.000 --> 00:00:06.000
Second line

00:00:00.000 --> 00:00:02.000
First line

00:00:06.000 --> 00:00:08.000
Second line
"""
    )

    assert [s.text for s in segments] == ["First line", "Second line"]
    assert segments[0].start == 0.0
    assert segments[-1].end == 8.0
    assert validate_segments(segments) == []


def test_normalize_repairs_every_invariant() -> None:
    messy = [
        Segment(start=5.0, end=45.0, text="one two three four five six seven eight nine ten"),
        Segment(start=40.0, end=41.0, text="overlaps the long one"),
        Segment(start=3.0, end=3.0, text="zero length"),
        Segment(start=2.0, end=2.5, text="   "),
        Segment(start=1.0, end=2.0, text="out of order"),
    ]

    cleaned = normalize_segments(messy)

    assert validate_segments(cleaned) == []
    assert [s.start for s in cleaned] == sorted(s.start for s in cleaned)
    assert all(s.text.strip() for s in cleaned)
    assert all(s.duration <= 30.0 + 1e-6 for s in cleaned)


def test_transcribe_writes_a_valid_transcript_json(tmp_path: Path) -> None:
    manifest, project = make_reel_project(tmp_path)
    config = load_config(None)
    audio = Route(payload=b"not-really-audio", filename="clip.mp3", media_type="audio", transcript=None)
    ingest(manifest, project, config, {"video": FakeAdapter({REEL: audio})})

    transcripts, failures = transcribe_pending(project, load_source_records(project), config, FakeTranscriber())

    assert failures == []
    assert len(transcripts) == 1
    source_id, transcript = next(iter(transcripts.items()))
    stored = json.loads((project / "sources" / source_id / "transcript.json").read_text(encoding="utf-8"))
    assert stored["source_id"] == source_id
    assert stored["segments"] == [
        {"start": s.start, "end": s.end, "text": s.text, "language": s.language}
        for s in transcript.segments
    ]
    assert validate_segments(transcript.segments) == []


def test_existing_invalid_transcript_is_reported(tmp_path: Path) -> None:
    manifest, project = make_reel_project(tmp_path)
    config = load_config(None)
    audio = Route(payload=b"bytes", filename="clip.mp3", media_type="audio", transcript=None)
    ingest(manifest, project, config, {"video": FakeAdapter({REEL: audio})})
    source_id = next((project / "sources").glob("*/source.json")).parent.name
    bad = Transcript(
        source_id=source_id,
        provider="x",
        model="y",
        language="en",
        segments=[Segment(0, 5, "later"), Segment(1, 2, "overlap")],
    )
    (project / "sources" / source_id / "transcript.json").write_text(bad.to_json(), encoding="utf-8")

    transcripts, failures = transcribe_pending(project, load_source_records(project), config, FakeTranscriber())

    assert not transcripts
    assert failures and "existing transcript invalid" in failures[0]
