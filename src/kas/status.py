"""Status writer.

Writes the single source of truth for run state in two synchronised forms:

* `<project>/status.json` — machine-readable,
* `<project>/docs/status/status.md` — human-readable, same content.

AC-14 requires both to carry phase, completed work, evidence, risks, remaining work,
next task and a timestamp, and requires the Markdown to match the JSON.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class StatusRecord:
    project_id: str
    phase: str
    completed: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    next_task: str = ""
    updated_at: str = field(default_factory=now_iso)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    # ---------- rendering ----------

    def to_markdown(self) -> str:
        def bullets(items: list[str], empty: str = "- none") -> str:
            return "\n".join(f"- {item}" for item in items) if items else empty

        return "\n".join(
            [
                "# Project Status",
                "",
                "<!-- generated from status.json by `kas status --write`; do not edit by hand -->",
                "",
                f"**Project:** `{self.project_id}`",
                "",
                "## Current phase",
                self.phase,
                "",
                "## Completed",
                bullets(self.completed),
                "",
                "## Evidence",
                bullets(self.evidence),
                "",
                "## Decisions",
                bullets(self.decisions),
                "",
                "## Risks / issues",
                bullets(self.risks),
                "",
                "## Remaining work",
                bullets(self.remaining),
                "",
                "## Next executable task",
                self.next_task or "none",
                "",
                "## Last updated",
                self.updated_at,
                "",
            ]
        )

    # ---------- persistence ----------

    def write(self, project_dir: Path, write_markdown: bool = True) -> list[Path]:
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        json_path = project_dir / "status.json"
        _atomic_write(json_path, json.dumps(self.to_dict(), indent=2) + "\n")
        written.append(json_path)

        if write_markdown:
            md_path = project_dir / "docs" / "status" / "status.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(md_path, self.to_markdown())
            written.append(md_path)

        return written

    @classmethod
    def read(cls, project_dir: Path) -> "StatusRecord":
        data = json.loads((Path(project_dir) / "status.json").read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def is_consistent(project_dir: Path) -> bool:
    """True when status.md reflects status.json exactly."""
    project_dir = Path(project_dir)
    record = StatusRecord.read(project_dir)
    md_path = project_dir / "docs" / "status" / "status.md"
    if not md_path.is_file():
        return False
    return md_path.read_text(encoding="utf-8") == record.to_markdown()
