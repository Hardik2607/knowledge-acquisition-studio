"""Adapter contract.

One adapter per source origin. An adapter's only job is to turn a manifest source
into immutable bytes plus, when the origin provides them, a transcript. It must not
write outside the working directory it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import Transcript


class AdapterError(Exception):
    """A fetch failure with a stable reason code (never a silent skip)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class FetchedSource:
    raw_file: Path
    media_type: str
    language: str | None = None
    transcript: Transcript | None = None
    metadata: dict = field(default_factory=dict)


class SourceAdapter(Protocol):
    kinds: tuple[str, ...]

    def fetch(self, source, workdir: Path, config, timeout: int = 600) -> FetchedSource: ...
