"""Transcription with normalization (AC-05).

Two providers behind one interface:

* `VoxtralTranscriber` — LLM7's `/audio/transcriptions` endpoint. May return real
  segment timings when the account has balance; otherwise it raises and the chain
  falls through to Groq.
* `GroqTranscriber` — `/audio/transcriptions` with `verbose_json`, which returns real
  segment timings. This is the validated fallback.

`normalize_segments` is the single place that guarantees the AC-05 invariants:
ordered, non-overlapping, `start < end`, non-empty text, no segment longer than 30 s.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .http import HttpError, post_multipart
from .models import Segment, Transcript

MAX_SEGMENT_SECONDS = 30.0
STAMPED_LINE = re.compile(r"^\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*(.+)$")


class TranscriptionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class TranscriptionResult:
    transcript: Transcript


def _split_long(segment: Segment) -> list[Segment]:
    if segment.duration <= MAX_SEGMENT_SECONDS:
        return [segment]
    words = segment.text.split()
    if not words:
        return [segment]
    parts = max(2, int(segment.duration // MAX_SEGMENT_SECONDS) + 1)
    per = max(1, len(words) // parts)
    out: list[Segment] = []
    span = segment.duration / parts
    for index in range(parts):
        chunk = words[index * per : (index + 1) * per] if index < parts - 1 else words[index * per :]
        if not chunk:
            continue
        out.append(
            Segment(
                start=round(segment.start + index * span, 3),
                end=round(min(segment.start + (index + 1) * span, segment.end), 3),
                text=" ".join(chunk),
                language=segment.language,
            )
        )
    return out


def normalize_segments(segments: list[Segment]) -> list[Segment]:
    cleaned: list[Segment] = []
    for segment in sorted(segments, key=lambda s: (s.start, s.end)):
        text = " ".join(segment.text.split())
        if not text:
            continue
        start = max(0.0, float(segment.start))
        end = float(segment.end)
        if end <= start:
            end = start + 0.1
        for piece in _split_long(Segment(start=start, end=end, text=text, language=segment.language)):
            if cleaned and piece.start < cleaned[-1].end:
                piece = Segment(
                    start=cleaned[-1].end,
                    end=max(piece.end, cleaned[-1].end + 0.1),
                    text=piece.text,
                    language=piece.language,
                )
            cleaned.append(piece)
    return cleaned


def validate_segments(segments: list[Segment]) -> list[str]:
    """Return human-readable violations; empty list means the transcript is valid."""
    problems: list[str] = []
    if not segments:
        return ["transcript has no segments"]
    previous_end = -1.0
    for index, segment in enumerate(segments):
        if not segment.text.strip():
            problems.append(f"segment {index}: empty text")
        if segment.start >= segment.end:
            problems.append(f"segment {index}: start >= end")
        if segment.duration > MAX_SEGMENT_SECONDS + 1e-6:
            problems.append(f"segment {index}: {segment.duration:.1f}s exceeds {MAX_SEGMENT_SECONDS}s")
        if segment.start < previous_end - 1e-6:
            problems.append(f"segment {index}: overlaps previous segment")
        previous_end = max(previous_end, segment.end)
    return problems


# --------------------------------------------------------------------- providers


class GroqTranscriber:
    name = "groq"

    def __init__(self, provider):
        self.provider = provider
        self.model = "whisper-large-v3"

    def transcribe(self, audio: Path, source_id: str, language: str | None = None) -> Transcript:
        key = os.environ.get(self.provider.api_key_env)
        if not key:
            raise TranscriptionError("missing_credentials", f"{self.provider.api_key_env} is not set")
        url = self.provider.base_url.rstrip("/") + "/audio/transcriptions"
        fields = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            fields["language"] = language
        try:
            payload = post_multipart(
                url,
                fields,
                {"file": audio},
                {"Authorization": f"Bearer {key}"},
                timeout=self.provider.timeout_seconds,
            )
        except HttpError as exc:
            raise TranscriptionError("provider_error", str(exc)) from exc

        raw_segments = payload.get("segments") or []
        if not raw_segments:
            raise TranscriptionError("no_segments", "provider returned no timestamped segments")
        segments = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=str(s["text"]),
                language=payload.get("language") or language,
            )
            for s in raw_segments
        ]
        return Transcript(
            source_id=source_id,
            provider=self.name,
            model=self.model,
            language=payload.get("language") or language,
            segments=normalize_segments(segments),
        )


class VoxtralTranscriber:
    name = "llm7"

    def __init__(self, provider):
        self.provider = provider
        self.model = provider.model

    def transcribe(self, audio: Path, source_id: str, language: str | None = None) -> Transcript:
        key = os.environ.get(self.provider.api_key_env)
        if not key:
            raise TranscriptionError("missing_credentials", f"{self.provider.api_key_env} is not set")
        url = self.provider.base_url.rstrip("/") + "/audio/transcriptions"
        fields = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            fields["language"] = language
        try:
            payload = post_multipart(
                url,
                fields,
                {"file": audio},
                {"Authorization": f"Bearer {key}"},
                timeout=self.provider.timeout_seconds,
            )
        except HttpError as exc:
            raise TranscriptionError("provider_error", str(exc)) from exc

        raw_segments = payload.get("segments") or []
        if raw_segments:
            segments = [
                Segment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")),
                    language=payload.get("language") or language,
                )
                for s in raw_segments
            ]
        else:
            segments = _parse_stamped_lines(payload.get("text", ""))
        if not segments:
            raise TranscriptionError(
                "no_timestamps",
                "provider returned no timestamped segments; check model and balance",
            )
        return Transcript(
            source_id=source_id,
            provider=self.name,
            model=self.model,
            language=payload.get("language") or language,
            segments=normalize_segments(segments),
        )


def _parse_stamped_lines(text: str) -> list[Segment]:
    stamped: list[tuple[float, str]] = []
    for line in text.splitlines():
        match = STAMPED_LINE.match(line.strip())
        if not match:
            continue
        first, second, third, body = match.groups()
        if third is None:
            seconds = int(first) * 60 + int(second)
        else:
            seconds = int(first) * 3600 + int(second) * 60 + int(third)
        stamped.append((float(seconds), body.strip()))
    segments: list[Segment] = []
    for index, (start, body) in enumerate(stamped):
        end = stamped[index + 1][0] if index + 1 < len(stamped) else start + 5.0
        segments.append(Segment(start=start, end=max(end, start + 0.5), text=body))
    return segments


# --------------------------------------------------------------------- chain


def transcribe_source(
    audio: Path,
    source_id: str,
    config,
    language: str | None = None,
    transcriber=None,
) -> tuple[Transcript, list[str]]:
    """Transcribe with the configured provider, then Groq, recording what was tried."""
    attempts: list[str] = []

    if not (config.get("network.enabled", True) if config is not None else True) and transcriber is None:
        raise TranscriptionError("network_disabled", "network is disabled by configuration (AC-17)")
    if transcriber is not None:
        transcript = transcriber.transcribe(audio, source_id, language=language)
        attempts.append(getattr(transcriber, "name", "injected"))
        return _finalize(transcript, attempts), attempts

    primary = config.providers["transcribe"]
    chain: list = []
    if primary.name == "llm7":
        chain.append(VoxtralTranscriber(primary))
    elif primary.name == "groq":
        chain.append(GroqTranscriber(primary))

    if primary.name != "groq":
        from .config import Provider

        chain.append(
            GroqTranscriber(
                Provider(
                    stage="transcribe",
                    name="groq",
                    base_url="https://api.groq.com/openai/v1",
                    api_key_env="GROQ_API_KEY",
                    model="whisper-large-v3",
                    timeout_seconds=max(primary.timeout_seconds, 300),
                )
            )
        )

    errors: list[str] = []
    for candidate in chain:
        try:
            transcript = candidate.transcribe(audio, source_id, language=language)
            problems = validate_segments(transcript.segments)
            if problems:
                raise TranscriptionError("invalid_segments", "; ".join(problems))
            attempts.append(candidate.name)
            return transcript, attempts
        except TranscriptionError as exc:
            attempts.append(f"{candidate.name}:{exc.code}")
            errors.append(f"{candidate.name}: {exc.code} ({exc.message[:160]})")

    raise TranscriptionError("all_providers_failed", "; ".join(errors) or "no provider configured")


def _finalize(transcript: Transcript, attempts: list[str]) -> Transcript:
    problems = validate_segments(transcript.segments)
    if problems:
        raise TranscriptionError("invalid_segments", "; ".join(problems))
    return transcript
