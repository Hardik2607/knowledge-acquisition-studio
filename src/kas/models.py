"""Data contracts: Source Record, transcripts, knowledge units, evidence.

These are the shapes every stage reads and writes. They are plain dataclasses so a
test can construct them without any I/O.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class SourceRecord:
    source_id: str
    kind: str
    origin: str
    title: str
    checksum: str
    raw_path: str
    retrieved_at: str
    author: str | None = None
    license: str | None = None
    language: str | None = None
    status: str = "ingested"
    reason: str | None = None
    media_type: str = "audio"
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Segment:
    start: float
    end: float
    text: str
    language: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Transcript:
    source_id: str
    provider: str
    model: str
    language: str | None
    segments: list[Segment] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "generated_at": self.generated_at,
            "schema_version": SCHEMA_VERSION,
            "segments": [asdict(s) for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(
            source_id=data["source_id"],
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            language=data.get("language"),
            generated_at=data.get("generated_at", ""),
            segments=[Segment(**s) for s in data.get("segments", [])],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


@dataclass
class KnowledgeUnit:
    id: str
    statement: str
    source_refs: list[dict[str, Any]]
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    task_id: str
    criteria: list[str]
    result: str
    artifacts: list[str] = field(default_factory=list)
    command: str | None = None
    run_at: str = ""
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, project_dir: Path) -> Path:
        path = Path(project_dir) / "evidence" / f"{self.task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path
