"""Video adapter — YouTube (subtitles first) and Instagram/Facebook Reels (cookies).

Uses the system `yt-dlp` binary. Two paths:

1. **Subtitles available** (YouTube): download only the VTT track and parse it into
   timed segments. No audio download, no transcription cost.
2. **No subtitles** (Reels, or videos without captions): download the audio stream and
   leave transcription to the transcribe stage.

Failures are typed. An auth failure is `auth_expired` so the caller can quarantine
instead of retrying (ADR-006 D19).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..models import Segment, Transcript
from .base import AdapterError, FetchedSource

TIMESTAMP = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})"
)
TAGS = re.compile(r"<[^>]+>")
CUE_INDEX = re.compile(r"^\d+$")

AUTH_MARKERS = (
    "login required",
    "empty media response",
    "use --cookies",
    "authentication",
    "private video",
    "requested content is not available",
)


def _seconds(stamp: str) -> float:
    parts = stamp.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, (minutes, seconds) = 0, parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_vtt(text: str) -> list[Segment]:
    """Parse a WEBVTT track into clean, ordered segments.

    Auto-generated YouTube captions repeat lines and carry inline word timings, so the
    text is de-duplicated line by line before being joined.
    """
    segments: list[Segment] = []
    start = end = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal start, end, buffer
        if start is not None and end is not None:
            cleaned = [
                TAGS.sub("", line).strip()
                for line in buffer
                if line.strip() and not line.strip().startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))
            ]
            deduped: list[str] = []
            for line in cleaned:
                if not deduped or deduped[-1] != line:
                    deduped.append(line)
            body = " ".join(deduped).strip()
            if body:
                segments.append(Segment(start=start, end=max(end, start + 0.1), text=body))
        start = end = None
        buffer = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        match = TIMESTAMP.match(line.strip())
        if match:
            flush()
            start, end = _seconds(match.group("start")), _seconds(match.group("end"))
            continue
        if start is None:
            continue
        if not line.strip() or CUE_INDEX.match(line.strip()):
            continue
        buffer.append(line)
    flush()
    return _normalize(segments)


def _normalize(segments: list[Segment]) -> list[Segment]:
    ordered = sorted(segments, key=lambda s: (s.start, s.end))
    out: list[Segment] = []
    for seg in ordered:
        if out and seg.start < out[-1].end:
            seg = Segment(start=out[-1].end, end=max(seg.end, out[-1].end + 0.1), text=seg.text)
        if out and seg.text == out[-1].text:
            out[-1] = Segment(start=out[-1].start, end=max(out[-1].end, seg.end), text=out[-1].text)
            continue
        out.append(seg)
    return out


class VideoAdapter:
    kinds = ("video", "audio")

    def __init__(self, binary: str | None = None):
        self.binary = binary or shutil.which("yt-dlp") or str(Path.home() / ".local/bin/yt-dlp")

    # ------------------------------------------------------------------ helpers

    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise AdapterError("adapter_missing", f"yt-dlp not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("timeout", f"yt-dlp exceeded {timeout}s") from exc

    def _raise_for_stderr(self, completed: subprocess.CompletedProcess) -> None:
        stderr = (completed.stderr or "").lower()
        if completed.returncode == 0:
            return
        for marker in AUTH_MARKERS:
            if marker in stderr:
                raise AdapterError("auth_expired", completed.stderr.strip().splitlines()[-1][:300])
        tail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown error"
        raise AdapterError("fetch_failed", tail[:300])

    # ------------------------------------------------------------------ fetch

    def fetch(self, source, workdir: Path, config, timeout: int = 600) -> FetchedSource:
        from ..paths import is_remote

        if is_remote(source.origin) and not (config.get("network.enabled", True) if config else True):
            raise AdapterError("network_disabled", f"network is disabled; cannot fetch remote origin {source.origin}")
        workdir.mkdir(parents=True, exist_ok=True)
        cookies_browser = source.cookies_from_browser or (
            config.get("sources.reels.cookies_from_browser") if config else None
        )
        cookies_file = (
            config.get("sources.reels.cookies_file") if config else None
        )
        browser = cookies_browser if _needs_cookies(source.origin) else None

        prefer_subs = bool(config.get("sources.youtube.prefer_subtitles", True)) if config else True
        languages = config.get("sources.youtube.languages", ["en"]) if config else ["en"]

        if prefer_subs and "youtube" in source.origin:
            fetched = self._try_subtitles(source, workdir, languages, browser, timeout)
            if fetched is not None:
                return fetched

        return self._download_audio(source, workdir, browser, cookies_file, timeout)

    def _cookie_args(self, browser: str | None, cookies_file: str | None) -> list[str]:
        if browser:
            return ["--cookies-from-browser", browser]
        if cookies_file:
            return ["--cookies", str(Path(cookies_file).expanduser())]
        return []

    def _try_subtitles(self, source, workdir, languages, browser, timeout) -> FetchedSource | None:
        langs = ",".join(f"{lang}.*" if len(lang) == 2 else lang for lang in languages)
        args = [
            "--no-warnings",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", langs,
            "--sub-format", "vtt/best",
            "--no-playlist",
            "-o", str(workdir / "%(id)s.%(ext)s"),
            *self._cookie_args(browser, None),
            source.origin,
        ]
        completed = self._run(args, timeout)
        if completed.returncode != 0:
            return None
        vtts = sorted(workdir.glob("*.vtt"))
        if not vtts:
            return None
        vtt = vtts[0]
        segments = parse_vtt(vtt.read_text(encoding="utf-8", errors="replace"))
        if not segments:
            return None
        language = vtt.stem.split(".")[-1] if "." in vtt.stem else None
        transcript = Transcript(
            source_id="",
            provider="yt-dlp",
            model="subtitles",
            language=language,
            segments=segments,
        )
        return FetchedSource(
            raw_file=vtt,
            media_type="text/vtt",
            language=language,
            transcript=transcript,
            metadata={"path": "subtitles"},
        )

    def _download_audio(self, source, workdir, browser, cookies_file, timeout) -> FetchedSource:
        args = [
            "--no-warnings",
            "--no-playlist",
            "-f", "bestaudio/best",
            "--write-info-json",
            "-o", str(workdir / "%(id)s.%(ext)s"),
            *self._cookie_args(browser, cookies_file),
            source.origin,
        ]
        completed = self._run(args, timeout)
        self._raise_for_stderr(completed)

        media = [
            p for p in workdir.iterdir()
            if p.suffix.lower() in {".m4a", ".mp3", ".webm", ".opus", ".wav", ".mp4", ".aac", ".ogg"}
        ]
        if not media:
            raise AdapterError("fetch_failed", "yt-dlp produced no media file")
        return FetchedSource(
            raw_file=max(media, key=lambda p: p.stat().st_size),
            media_type="audio",
            metadata={"path": "audio"},
        )


def _needs_cookies(origin: str) -> bool:
    return any(host in origin for host in ("instagram.com", "facebook.com", "fb.watch"))


def build_adapter(kind: str, binary: str | None = None):
    if kind in ("video", "audio"):
        return VideoAdapter(binary)
    return None
