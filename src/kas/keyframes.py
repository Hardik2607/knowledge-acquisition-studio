"""Keyframe screenshot extractor for video tutorials and technical demos.

Extracts high-resolution screenshots at timestamps where code, graphs, UI menus,
dashboards, or terminal commands appear, attaching visual grounding to knowledge units.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CODE_GRAPH_KEYWORDS = re.compile(
    r"\b(code|terminal|command|graph|chart|ui|interface|app|dashboard|prompt|"
    r"mock-up|design|spreadsheet|table|setting|menu|click|select|install|api|"
    r"folder|workspace|file|browser|button|window|export|import)\b",
    re.IGNORECASE,
)


def is_visual_or_code_note(text: str) -> bool:
    """Returns True if the note text refers to visible code, UI, or graphical elements."""
    return bool(CODE_GRAPH_KEYWORDS.search(text))


def extract_frame_ffmpeg(video_path: Path, timestamp: float, output_path: Path) -> bool:
    """Extracts a single JPEG keyframe from a video at timestamp seconds using ffmpeg."""
    if not video_path.is_file():
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-ss",
        f"{timestamp:.2f}",
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        "-update",
        "1",
        str(output_path),
        "-y",
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return res.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("ffmpeg extraction failed: %s", exc)
        return False


def ensure_video_available(source_dir: Path, origin: str) -> Path | None:
    """Finds an existing raw MP4 video or fetches a lightweight 360p stream for frame extraction."""
    raw_dir = source_dir / "raw"
    if raw_dir.is_dir():
        for candidate in raw_dir.glob("*.mp4"):
            if candidate.is_file() and candidate.stat().st_size > 100_000:
                return candidate

    # Check /tmp cache
    tmp_candidate = Path("/tmp/claude_360p.mp4")
    if tmp_candidate.is_file() and tmp_candidate.stat().st_size > 100_000:
        return tmp_candidate

    if not origin or ("youtube.com" not in origin and "youtu.be" not in origin):
        return None

    target = raw_dir / "preview_360p.mp4"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-f",
        "134/worst[ext=mp4]/worst",
        "-o",
        str(target),
        origin,
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if res.returncode == 0 and target.is_file():
            return target
    except Exception:
        pass
    return None


def extract_project_keyframes(
    project_dir: Path,
    max_frames: int = 15,
) -> list[dict[str, Any]]:
    """Scans project notes and procedures for code/graph/UI mentions and extracts keyframes."""
    project_dir = Path(project_dir).resolve()
    sources_dir = project_dir / "sources"
    notes_dir = project_dir / "notes"

    results: list[dict[str, Any]] = []
    if not sources_dir.is_dir() or not notes_dir.is_dir():
        return results

    for sdir in sorted(sources_dir.glob("src-*")):
        source_id = sdir.name
        source_json = sdir / "source.json"
        origin = ""
        if source_json.is_file():
            try:
                origin = json.loads(source_json.read_text(encoding="utf-8")).get("origin", "")
            except Exception:
                pass

        video_path = ensure_video_available(sdir, origin)
        if not video_path:
            continue

        note_json = notes_dir / f"{source_id}.json"
        if not note_json.is_file():
            continue

        try:
            nb = json.loads(note_json.read_text(encoding="utf-8"))
        except Exception:
            continue

        keyframes_dir = sdir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for note in nb.get("notes", []):
            text = note.get("text", "")
            if is_visual_or_code_note(text):
                start = float(note.get("start", 0))
                sec_int = int(start)
                out_file = keyframes_dir / f"frame_{sec_int}s.jpg"
                if not out_file.is_file():
                    success = extract_frame_ffmpeg(video_path, start + 1.0, out_file)
                else:
                    success = True

                if success:
                    rel_path = str(out_file.relative_to(project_dir))
                    results.append(
                        {
                            "source_id": source_id,
                            "timestamp": start,
                            "range": note.get("range", f"{sec_int}s"),
                            "text": text,
                            "image_path": rel_path,
                            "filename": out_file.name,
                        }
                    )
                    count += 1
                    if count >= max_frames:
                        break

    return results
