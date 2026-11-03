"""Content-addressed identifiers (ADR-004 D3).

Determinism and idempotency depend entirely on these two functions: the same bytes
must always produce the same `source_id`, the same statement the same `unit_id`.
"""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id_for(checksum: str) -> str:
    return f"src-{checksum[:12]}"


def normalize_statement(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def unit_id_for(statement: str) -> str:
    return "k-" + hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()[:12]


def procedure_id_for(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")[:40]
    return f"p-{slug or 'procedure'}"
