"""Ingestion: manifest source → immutable raw bytes + Source Record.

Guarantees:

* `source_id` is content-addressed from the raw bytes (ADR-004 D3),
* raw files are never overwritten; a different payload for the same origin is a
  checksum conflict, not a silent replacement (AC-04),
* re-running ingestion with identical bytes is a no-op — raw mtime and every written
  file stay byte-identical (AC-04, and the Phase 3 idempotency work builds on this),
* an unsupported kind fails that source only; other sources still ingest (AC-02),
* nothing is written outside `sources/` and the temporary work directory.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .adapters.base import AdapterError
from .ids import sha256_file, source_id_for
from .models import SourceRecord


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class IngestSummary:
    records: list[SourceRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[SourceRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


class IntegrityError(Exception):
    """Raised when an existing origin would be overwritten with different bytes."""


def _existing_by_origin(project_dir: Path) -> dict[str, SourceRecord]:
    index: dict[str, SourceRecord] = {}
    sources_dir = Path(project_dir) / "sources"
    if not sources_dir.is_dir():
        return index
    for record_path in sources_dir.glob("*/source.json"):
        try:
            record = SourceRecord.from_dict(json.loads(record_path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError):
            continue
        index[record.origin] = record
    return index


def _failure(source, status: str, reason: str) -> SourceRecord:
    return SourceRecord(
        source_id="",
        kind=source.kind,
        origin=source.origin,
        title=source.title,
        checksum="",
        raw_path="",
        retrieved_at=now_iso(),
        status=status,
        reason=reason,
    )


def _log_failure(project_dir: Path, source, code: str, message: str) -> None:
    evidence_dir = Path(project_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with (evidence_dir / "ingest-failures.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()}\t{source.origin}\t{code}\t{message}\n")


def ingest(
    manifest,
    project_dir: Path,
    config,
    registry: dict,
    timeout: int = 600,
) -> IngestSummary:
    project_dir = Path(project_dir)
    sources_dir = project_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = project_dir / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    existing = _existing_by_origin(project_dir)
    summary = IngestSummary()

    for index, source in enumerate(manifest.sources):
        adapter = registry.get(source.kind)
        if adapter is None:
            record = _failure(source, "failed", f"unsupported_kind:{source.kind}")
            summary.failed.append(record)
            _log_failure(project_dir, source, "unsupported_kind", source.kind)
            continue

        workdir = tmp_root / f"ingest-{index}"
        try:
            fetched = adapter.fetch(source, workdir, config, timeout=timeout)
            checksum = sha256_file(fetched.raw_file)
            source_id = source_id_for(checksum)
            dest = sources_dir / source_id

            prior = existing.get(source.origin)
            if prior is not None and prior.checksum and prior.checksum != checksum:
                raise IntegrityError(
                    f"origin {source.origin!r} was ingested as {prior.source_id} with checksum "
                    f"{prior.checksum[:12]}… but now hashes to {checksum[:12]}…; "
                    "refusing to overwrite raw bytes"
                )

            raw_dir = dest / "raw"
            already_present = raw_dir.is_dir() and any(raw_dir.iterdir())

            if already_present:
                # Immutable: keep the original record and do not rewrite any file.
                stored = dest / "source.json"
                if stored.is_file():
                    record = SourceRecord.from_dict(json.loads(stored.read_text(encoding="utf-8")))
                else:
                    record = prior or _failure(source, "ingested", "missing_record")
                    (dest / "source.json").write_text(record.to_json(), encoding="utf-8")
                summary.skipped.append(source_id)
            else:
                raw_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(fetched.raw_file), raw_dir / fetched.raw_file.name)
                record = SourceRecord(
                    source_id=source_id,
                    kind=source.kind,
                    origin=source.origin,
                    title=source.title,
                    checksum=checksum,
                    raw_path=f"sources/{source_id}/raw/{fetched.raw_file.name}",
                    retrieved_at=now_iso(),
                    author=source.author,
                    license=source.license,
                    language=fetched.language or source.language,
                    status="ingested",
                    media_type=fetched.media_type,
                )
                (dest / "source.json").write_text(record.to_json(), encoding="utf-8")
                if fetched.transcript is not None:
                    fetched.transcript.source_id = source_id
                    (dest / "transcript.json").write_text(fetched.transcript.to_json(), encoding="utf-8")

            existing[source.origin] = record
            summary.records.append(record)

        except IntegrityError as exc:
            record = _failure(source, "failed", f"checksum_conflict: {exc}")
            summary.failed.append(record)
            _log_failure(project_dir, source, "checksum_conflict", str(exc))

        except AdapterError as exc:
            status = "quarantined" if exc.code == "auth_expired" else "failed"
            summary.failed.append(_failure(source, status, f"{exc.code}: {exc.message}"))
            _log_failure(project_dir, source, exc.code, exc.message)

        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # Two manifest entries with identical bytes collapse to one content-addressed record.
    seen: set[str] = set()
    unique: list[SourceRecord] = []
    for record in summary.records:
        if record.source_id and record.source_id not in seen:
            seen.add(record.source_id)
            unique.append(record)
    summary.records = unique
    shutil.rmtree(tmp_root, ignore_errors=True)
    return summary


def load_source_records(project_dir: Path) -> dict[str, SourceRecord]:
    """All ingested Source Records in the project, keyed by source_id."""
    records: dict[str, SourceRecord] = {}
    sources_dir = Path(project_dir) / "sources"
    if not sources_dir.is_dir():
        return records
    for path in sorted(sources_dir.glob("*/source.json")):
        try:
            record = SourceRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError):
            continue
        if record.source_id:
            records[record.source_id] = record
    return records
