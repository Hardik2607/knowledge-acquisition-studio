"""Git repository adapter for software, documentation, and skill extraction."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from ..models import Segment, Transcript
from .base import AdapterError, FetchedSource

DOC_NAMES = {
    "readme.md",
    "readme.rst",
    "readme.txt",
    "readme",
    "contributing.md",
    "architecture.md",
    "skill.md",
}
MANIFEST_NAMES = {
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "makefile",
    "dockerfile",
    "docker-compose.yml",
    "go.mod",
}


class GitAdapter:
    kinds = ("git", "repo")

    def __init__(self, git_binary: str = "git"):
        self.git_binary = git_binary

    def fetch(self, source, workdir: Path, config=None, timeout: int = 600) -> FetchedSource:
        origin = source.origin.strip()
        if origin.startswith("file://"):
            origin = origin[len("file://"):]
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        repo_dir = workdir / "repo"

        commit_hash = "unknown"
        scan_root = repo_dir
        if os.path.isdir(origin):
            scan_root = Path(origin).resolve()
            try:
                p = subprocess.run([self.git_binary, "-C", str(scan_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
                if p.returncode == 0:
                    commit_hash = p.stdout.strip()
            except Exception:
                pass
        else:
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            cmd = [self.git_binary, "clone", "--depth", "1", origin, str(repo_dir)]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
                if res.returncode != 0:
                    raise AdapterError("git_clone_failed", f"Failed to clone {origin}: {res.stderr.strip()}")
                p = subprocess.run([self.git_binary, "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
                if p.returncode == 0:
                    commit_hash = p.stdout.strip()
            except subprocess.TimeoutExpired:
                raise AdapterError("timeout", f"Git clone timed out after {timeout}s: {origin}")
            except Exception as exc:
                if isinstance(exc, AdapterError):
                    raise
                raise AdapterError("git_error", str(exc))

        collected_files: list[tuple[str, str]] = []
        for root, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".venv", "__pycache__", "dist", "build", "vendor", "projects", ".tmp", "raw")]
            for f in files:
                f_lower = f.lower()
                rel_path = os.path.relpath(os.path.join(root, f), scan_root)
                if f_lower in DOC_NAMES or f_lower in MANIFEST_NAMES or rel_path.startswith("docs/") or rel_path.startswith("doc/"):
                    full_p = Path(root) / f
                    if full_p.stat().st_size < 300_000:
                        try:
                            text = full_p.read_text(encoding="utf-8", errors="ignore").strip()
                            if text:
                                collected_files.append((rel_path, text))
                        except Exception:
                            pass

        if not collected_files:
            raise AdapterError("no_docs", f"No readable README or docs found in repository {origin}")

        # Sort so README and architecture files come first
        def file_priority(item: tuple[str, str]) -> int:
            name = item[0].lower()
            if "readme" in name:
                return 0
            if "architecture" in name or "design" in name:
                return 1
            if name.startswith("docs/"):
                return 2
            return 3

        collected_files.sort(key=file_priority)

        bundle_path = workdir / "repo_bundle.tar.gz"
        with tarfile.open(bundle_path, "w:gz") as tar:
            for rel_path, _ in collected_files:
                file_full = scan_root / rel_path
                if file_full.is_file():
                    tar.add(file_full, arcname=f"repo/{rel_path}")

        segments: list[Segment] = []
        current_time = 0.0
        step_duration = 10.0

        for rel_path, text in collected_files:
            # Split sections keeping headings intact
            raw_blocks = re.split(r"(?m)(?=^#{1,4}\s+)", text)
            blocks = []
            for b in raw_blocks:
                # If block is large, further split by double newlines
                if len(b) > 800:
                    blocks.extend(re.split(r"\n\n+", b))
                else:
                    blocks.append(b)

            for b in blocks[:25]:
                clean_para = " ".join(b.split())
                if len(clean_para) < 15:
                    continue
                if len(clean_para) > 600:
                    clean_para = clean_para[:600] + "..."
                seg_text = f"[{rel_path}] {clean_para}"
                segments.append(Segment(start=current_time, end=current_time + step_duration, text=seg_text))
                current_time += step_duration

        if not segments:
            raise AdapterError("empty_content", f"Repository {origin} yielded no readable content")

        transcript = Transcript(
            source_id="",
            provider="git",
            model="repo-ingest",
            language="en",
            segments=segments,
        )

        return FetchedSource(
            raw_file=bundle_path,
            media_type="application/x-git",
            language="en",
            transcript=transcript,
            metadata={
                "origin": origin,
                "commit": commit_hash,
                "files_count": len(collected_files),
            },
        )
