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
import shutil
import subprocess
import tempfile
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


class LocalWhisperTranscriber:
    """Local offline Whisper transcriber supporting CUDA/CPU execution."""

    def __init__(self, provider):
        self.provider = provider
        self.name = getattr(provider, "name", "nvidia")
        self.model = getattr(provider, "model", "base") or "base"

    def transcribe(self, audio: Path, source_id: str, language: str | None = None) -> Transcript:
        audio = Path(audio).resolve()
        if not audio.is_file():
            raise TranscriptionError("file_not_found", f"audio file not found: {audio}")

        # 1. In-process whisper library if available
        try:
            import torch  # type: ignore
            import whisper  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = whisper.load_model(self.model, device=device)
            kwargs = {}
            if language:
                kwargs["language"] = language
            result = model.transcribe(str(audio), **kwargs)
            raw_segments = result.get("segments") or []
            detected_language = result.get("language") or language
            segments = [
                Segment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")),
                    language=detected_language,
                )
                for s in raw_segments
            ]
            if not segments:
                raise TranscriptionError("no_segments", "local whisper returned no segments")
            return Transcript(
                source_id=source_id,
                provider=self.name,
                model=self.model,
                language=detected_language,
                segments=normalize_segments(segments),
            )
        except ImportError:
            pass
        except Exception as exc:
            raise TranscriptionError("provider_error", f"whisper python failed: {exc}") from exc

        # 2. External CLI whisper executable or python3 -m whisper
        whisper_bin = shutil.which("whisper")
        if not whisper_bin:
            user_bin = Path.home() / ".local" / "bin" / "whisper"
            if user_bin.is_file() and os.access(user_bin, os.X_OK):
                whisper_bin = str(user_bin)

        if not whisper_bin:
            try:
                check = subprocess.run(
                    ["python3", "-c", "import whisper"],
                    capture_output=True,
                    timeout=5,
                )
                if check.returncode == 0:
                    whisper_bin = "python3"
            except Exception:
                pass

        if not whisper_bin:
            raise TranscriptionError(
                "whisper_unavailable",
                "Local whisper is not available (install openai-whisper or whisper CLI)",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            base_cmd = (
                [whisper_bin, str(audio)]
                if whisper_bin != "python3"
                else ["python3", "-m", "whisper", str(audio)]
            )
            base_cmd.extend(["--model", self.model, "--output_format", "json", "--output_dir", tmpdir])
            if language:
                base_cmd.extend(["--language", language])

            cuda_cmd = list(base_cmd) + ["--device", "cuda"]
            proc = subprocess.run(cuda_cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                cpu_cmd = list(base_cmd) + ["--device", "cpu"]
                proc = subprocess.run(cpu_cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise TranscriptionError(
                        "provider_error",
                        f"whisper CLI exited with {proc.returncode}: {proc.stderr[:200]}",
                    )

            json_files = list(Path(tmpdir).glob("*.json"))
            if not json_files:
                raise TranscriptionError("no_output", "whisper CLI did not produce a json output file")

            try:
                payload = json.loads(json_files[0].read_text(encoding="utf-8"))
            except Exception as exc:
                raise TranscriptionError("invalid_json", f"could not parse whisper json: {exc}") from exc

            raw_segments = payload.get("segments") or []
            detected_language = payload.get("language") or language
            segments = [
                Segment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")),
                    language=detected_language,
                )
                for s in raw_segments
            ]
            if not segments:
                raise TranscriptionError("no_segments", "whisper returned no segments")

            return Transcript(
                source_id=source_id,
                provider=self.name,
                model=self.model,
                language=detected_language,
                segments=normalize_segments(segments),
            )


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

    primary = config.providers.get("transcribe") if config and hasattr(config, "providers") else None
    is_local = primary and primary.name in ("nvidia", "whisper", "local")

    if not (config.get("network.enabled", True) if config is not None else True) and transcriber is None and not is_local:
        raise TranscriptionError("network_disabled", "network is disabled by configuration (AC-17)")
    if transcriber is not None:
        transcript = transcriber.transcribe(audio, source_id, language=language)
        attempts.append(getattr(transcriber, "name", "injected"))
        return _finalize(transcript, attempts), attempts

    chain: list = []
    if primary:
        if primary.name in ("nvidia", "whisper", "local"):
            chain.append(LocalWhisperTranscriber(primary))
        elif primary.name == "llm7":
            chain.append(VoxtralTranscriber(primary))
        elif primary.name == "groq":
            chain.append(GroqTranscriber(primary))

    if not primary or primary.name != "groq":
        from .config import Provider

        timeout = primary.timeout_seconds if primary else 300
        chain.append(
            GroqTranscriber(
                Provider(
                    stage="transcribe",
                    name="groq",
                    base_url="https://api.groq.com/openai/v1",
                    api_key_env="GROQ_API_KEY",
                    model="whisper-large-v3",
                    timeout_seconds=max(timeout, 300),
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
