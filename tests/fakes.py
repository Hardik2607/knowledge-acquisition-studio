"""Test doubles. No network, no yt-dlp, no provider keys."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from kas.adapters.base import AdapterError, FetchedSource
from kas.extract import ChatResult
from kas.ids import unit_id_for
from kas.models import Segment, Transcript
from kas.transcribe import TranscriptionError

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
First idea here.

00:00:02.000 --> 00:00:04.000
Second <i>idea</i> here.
"""


@dataclass
class Route:
    payload: bytes
    filename: str = "clip.vtt"
    media_type: str = "text/vtt"
    transcript: Transcript | None = None
    error: tuple[str, str] | None = None


def vtt_transcript() -> Transcript:
    from kas.adapters.video import parse_vtt

    return Transcript(
        source_id="",
        provider="yt-dlp",
        model="subtitles",
        language="en",
        segments=parse_vtt(VTT),
    )


class FakeAdapter:
    kinds = ("video", "audio")

    def __init__(self, routes: dict[str, Route], default: Route | None = None):
        self.routes = routes
        self.default = default
        self.calls: list[str] = []

    def fetch(self, source, workdir: Path, config, timeout: int = 600) -> FetchedSource:
        self.calls.append(source.origin)
        route = self.routes.get(source.origin, self.default)
        if route is None:
            raise AdapterError("fetch_failed", f"no fake route for {source.origin}")
        if route.error is not None:
            raise AdapterError(*route.error)
        workdir.mkdir(parents=True, exist_ok=True)
        path = workdir / route.filename
        path.write_bytes(route.payload)
        transcript = None
        if route.transcript is not None:
            transcript = Transcript.from_dict(route.transcript.to_dict())
        return FetchedSource(
            raw_file=path,
            media_type=route.media_type,
            language=transcript.language if transcript else None,
            transcript=transcript,
        )


class FakeTranscriber:
    name = "fake-asr"

    def __init__(self, segments: list[Segment] | None = None, error: tuple[str, str] | None = None):
        self.segments = segments or [
            Segment(0.0, 1.5, "reel opening line"),
            Segment(1.5, 3.0, "reel closing line"),
        ]
        self.error = error

    def transcribe(self, audio: Path, source_id: str, language: str | None = None) -> Transcript:
        if self.error is not None:
            raise TranscriptionError(*self.error)
        return Transcript(
            source_id=source_id,
            provider=self.name,
            model="fake-asr-v1",
            language=language or "en",
            segments=[Segment(**vars(s)) for s in self.segments],
        )


class FakeClient:
    """Returns prepared JSON payloads, one per chat call."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> ChatResult:
        self.calls.append((system, user))
        if not self.responses:
            raise AssertionError("FakeClient ran out of responses")
        payload = self.responses.pop(0)
        return ChatResult(
            text=json.dumps(payload),
            provider="fake",
            model="fake-chat",
            base_url="http://fake.invalid",
        )


class StaticClient:
    """Always returns the same JSON payload."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> ChatResult:
        self.calls.append((system, user))
        return ChatResult(
            text=json.dumps(self.payload),
            provider="fake",
            model="fake-chat",
            base_url="http://fake.invalid",
        )


class Phase3Client:
    """Handles notes, units and procedures in one fake client."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> ChatResult:
        self.calls.append((system, user))
        if "timestamped study notes" in system:
            payload = {"notes": [{"start": 0, "end": 1, "text": "A key point"}]}
        elif "atomic, actionable knowledge units" in system:
            match = re.search(r"### (src-[a-z0-9]+)", user)
            sid = match.group(1) if match else "src-unknown"
            payload = {
                "units": [
                    {
                        "statement": "Elephants have long trunks.",
                        "source_refs": [{"source_id": sid, "start": 0, "end": 4}],
                        "confidence": "high",
                    }
                ]
            }
        elif "ordered, executable procedure" in system:
            uid = unit_id_for("Elephants have long trunks.")
            payload = {
                "procedures": [
                    {
                        "title": "Observe elephants",
                        "steps": [{"text": "Look at the trunks", "unit_ids": [uid]}],
                    }
                ]
            }
        else:
            payload = {}
        return ChatResult(
            text=json.dumps(payload),
            provider="fake",
            model="fake-chat",
            base_url="http://fake.invalid",
        )


ONE_NOTE = {"notes": [{"start": 0, "end": 1, "text": "A key point"}]}
