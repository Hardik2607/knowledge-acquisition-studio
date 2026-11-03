"""AC-06 — note provenance."""

from __future__ import annotations

import pytest
from fakes import FakeClient, ONE_NOTE

from kas.extract import ExtractionError, build_notes, validate_notes
from kas.models import Segment, Transcript


class Source:
    title = "A talk"


def transcript() -> Transcript:
    return Transcript(
        source_id="src-aaaaaaaaaaaa",
        provider="fake",
        model="fake",
        language="en",
        segments=[Segment(0.0, 2.0, "first"), Segment(2.0, 4.0, "second")],
    )


def test_every_note_carries_source_and_in_range_timestamp() -> None:
    notebook = build_notes(FakeClient([ONE_NOTE]), Source(), transcript())

    assert len(notebook.bullets) == 1
    bullet = notebook.bullets[0]
    assert bullet["source_id"] == "src-aaaaaaaaaaaa"
    assert 0.0 <= bullet["start"] < bullet["end"] <= 4.0
    assert bullet["range"] == "00:00–00:01"
    assert validate_notes(notebook, {"src-aaaaaaaaaaaa": transcript()}) == []


def test_note_outside_the_transcript_is_rejected() -> None:
    too_late = {"notes": [{"start": 10, "end": 12, "text": "invented ending"}]}
    with pytest.raises(ExtractionError) as excinfo:
        build_notes(FakeClient([too_late]), Source(), transcript())
    assert excinfo.value.code == "bad_range"


def test_tampered_note_range_is_caught_by_validation() -> None:
    notebook = build_notes(FakeClient([ONE_NOTE]), Source(), transcript())
    notebook.bullets[0]["end"] = 99.0

    problems = validate_notes(notebook, {"src-aaaaaaaaaaaa": transcript()})

    assert problems and "outside the transcript" in problems[0]


def test_wrong_source_id_is_caught() -> None:
    notebook = build_notes(FakeClient([ONE_NOTE]), Source(), transcript())
    notebook.bullets[0]["source_id"] = "src-bbbbbbbbbbbb"

    problems = validate_notes(notebook, {"src-aaaaaaaaaaaa": transcript()})

    assert any("wrong source_id" in problem for problem in problems)
