"""Phase 2 orchestration: ingest → transcript → notes → evidence → status.

The pipeline is deliberately a plain function chain with no hidden global state. Every
stage takes its collaborators as arguments, so the tests can run the whole thing with
a fake adapter, a fake transcriber and a fake chat client and still exercise the real
validation and file-writing code.

What "pass" means here is not "the model said so". Every transcript is checked against
the AC-05 invariants, every note range against its transcript, and every Source Record
against the sha256 of the bytes actually on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .adapters import default_registry
from .extract import ChatClient, ExtractionError, NoteBook, build_notes, validate_notes
from .ids import sha256_file, source_id_for
from .http import set_network_enabled
from .ingest import IngestSummary, ingest, load_source_records
from .knowledge import build_knowledge
from .models import Evidence, SourceRecord, Transcript
from .status import StatusRecord
from .transcribe import TranscriptionError, transcribe_source, validate_segments

PHASE2 = "Phase 2 — ingest, transcript and notes implemented"
PHASE3 = "Phase 3 — knowledge, procedures, source map, verification and retry"
PHASE5 = "Phase 5 — QA, derived content, application report, vault projection complete"
AUDIO_SUFFIXES = {".m4a", ".mp3", ".webm", ".opus", ".wav", ".mp4", ".aac", ".ogg", ".flac"}
SUBTITLE_SUFFIXES = {".vtt", ".srt"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class BuildResult:
    ingested: IngestSummary
    transcripts: dict[str, Transcript] = field(default_factory=dict)
    notebooks: dict[str, NoteBook] = field(default_factory=dict)
    units: list = field(default_factory=list)
    procedures: list = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    evidence: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ingested.ok and not self.failures


# --------------------------------------------------------------------- checks


def verify_source_records(project_dir: Path, records: dict[str, SourceRecord]) -> list[str]:
    """AC-03: every record's checksum and id must match the bytes on disk."""
    problems: list[str] = []
    for source_id, record in records.items():
        raw = Path(project_dir) / record.raw_path
        if not raw.is_file():
            problems.append(f"{source_id}: raw file missing at {record.raw_path}")
            continue
        checksum = sha256_file(raw)
        if checksum != record.checksum:
            problems.append(f"{source_id}: checksum does not match raw bytes")
        if source_id != source_id_for(record.checksum):
            problems.append(f"{source_id}: id is not src-<checksum[0:12]>")
    return problems


def _media_kind(record: SourceRecord) -> str:
    if record.media_type in ("text/vtt", "text/srt", "subtitles"):
        return "subtitles"
    suffix = Path(record.raw_path).suffix.lower()
    if suffix in SUBTITLE_SUFFIXES:
        return "subtitles"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return "unknown"


# ------------------------------------------------------------------- stages


def transcribe_pending(
    project_dir: Path,
    records: dict[str, SourceRecord],
    config,
    transcriber=None,
) -> tuple[dict[str, Transcript], list[str]]:
    """Transcribe every audio source that does not already have a transcript."""
    project_dir = Path(project_dir)
    transcripts: dict[str, Transcript] = {}
    failures: list[str] = []

    for source_id, record in sorted(records.items()):
        transcript_path = project_dir / "sources" / source_id / "transcript.json"
        if transcript_path.is_file():
            try:
                transcript = Transcript.from_dict(json.loads(transcript_path.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError) as exc:
                failures.append(f"{source_id}: unreadable transcript.json ({exc})")
                continue
            problems = validate_segments(transcript.segments)
            if problems:
                failures.append(f"{source_id}: existing transcript invalid: {'; '.join(problems)}")
            else:
                transcripts[source_id] = transcript
            continue

        kind = _media_kind(record)
        if kind == "subtitles":
            failures.append(f"{source_id}: subtitle source has no transcript.json")
            continue
        if kind == "unknown":
            failures.append(f"{source_id}: cannot transcribe media type {record.media_type!r}")
            continue

        raw = project_dir / record.raw_path
        if not raw.is_file():
            failures.append(f"{source_id}: raw file missing at {record.raw_path}")
            continue

        try:
            transcript, _attempts = transcribe_source(
                raw, source_id, config, language=record.language, transcriber=transcriber
            )
        except TranscriptionError as exc:
            failures.append(f"{source_id}: {exc.code}: {exc.message}")
            continue

        transcript.generated_at = now_iso()
        transcript_path.write_text(transcript.to_json(), encoding="utf-8")
        transcripts[source_id] = transcript

    return transcripts, failures


def generate_notes(
    project_dir: Path,
    records: dict[str, SourceRecord],
    transcripts: dict[str, Transcript],
    config,
    client=None,
) -> tuple[dict[str, NoteBook], list[str]]:
    """AC-06: build notes and refuse any note whose range is not in the transcript."""
    project_dir = Path(project_dir)
    if client is None:
        client = ChatClient(config, stage="extract")

    notebooks: dict[str, NoteBook] = {}
    failures: list[str] = []
    for source_id, transcript in sorted(transcripts.items()):
        record = records.get(source_id)
        if record is None:
            failures.append(f"{source_id}: transcript has no Source Record")
            continue
        try:
            notebook = build_notes(client, record, transcript)
        except ExtractionError as exc:
            failures.append(f"{source_id}: {exc.code}: {exc.message}")
            continue
        problems = validate_notes(notebook, transcripts)
        if problems:
            failures.append(f"{source_id}: invalid notes: {'; '.join(problems)}")
            continue
        write_notes(project_dir, notebook)
        notebooks[source_id] = notebook

    return notebooks, failures


def write_notes(project_dir: Path, notebook: NoteBook) -> Path:
    notes_dir = Path(project_dir) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_id": notebook.source_id,
        "provider": notebook.provider,
        "model": notebook.model,
        "generated_at": now_iso(),
        "schema_version": 1,
        "notes": notebook.bullets,
    }
    json_path = notes_dir / f"{notebook.source_id}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (notes_dir / f"{notebook.source_id}.md").write_text(notebook.to_markdown(), encoding="utf-8")
    return json_path


# -------------------------------------------------------------------- evidence


def _write_evidence(
    project_dir: Path,
    records: dict[str, SourceRecord],
    transcripts: dict[str, Transcript],
    notebooks: dict[str, NoteBook],
    ingest_problems: list[str],
    transcript_problems: list[str],
    note_problems: list[str],
    knowledge_failures: list[str],
) -> list[Path]:
    source_files = [f"sources/{sid}/source.json" for sid in sorted(records)]
    transcript_files = [f"sources/{sid}/transcript.json" for sid in sorted(transcripts)]
    note_files = [f"notes/{sid}.json" for sid in sorted(notebooks)]
    knowledge_dir = Path(project_dir) / "knowledge"
    procedure_files = [f"knowledge/procedures/{p.name}" for p in sorted((knowledge_dir / "procedures").glob("*.md"))] if (knowledge_dir / "procedures").is_dir() else []
    knowledge_files = []
    if (knowledge_dir / "units.json").is_file():
        knowledge_files.append("knowledge/units.json")
    if (knowledge_dir / "source-map.json").is_file():
        knowledge_files.append("knowledge/source-map.json")
    knowledge_files.extend(procedure_files)

    records_ok = not ingest_problems and not any(not r.checksum for r in records.values())
    transcript_ok = not transcript_problems and bool(transcripts) == bool(records) and bool(transcripts)
    notes_ok = not note_problems and bool(notebooks) == bool(transcripts) and bool(notebooks)
    knowledge_ok = not knowledge_failures and bool(knowledge_files)

    specs = [
        (
            "t-ingest",
            ["AC-02", "AC-03", "AC-04"],
            records_ok,
            source_files,
            ingest_problems,
            "Source Records written and checksums recomputed from raw bytes.",
        ),
        (
            "t-transcribe",
            ["AC-05"],
            transcript_ok,
            transcript_files,
            transcript_problems,
            "Segments ordered, start < end, no overlap, none over 30s, all non-empty.",
        ),
        (
            "t-notes",
            ["AC-06"],
            notes_ok,
            note_files,
            note_problems,
            "Every note carries source_id and a range inside that source's transcript.",
        ),
        (
            "t-knowledge",
            ["AC-07", "AC-08", "AC-09", "AC-15"],
            knowledge_ok,
            knowledge_files,
            knowledge_failures,
            "Units, procedures and source map are valid and provenance-clean.",
        ),
    ]

    written: list[Path] = []
    for task_id, criteria, passed, artifacts, problems, note in specs:
        evidence = Evidence(
            task_id=task_id,
            criteria=criteria,
            result="pass" if passed else "fail",
            artifacts=artifacts,
            command=f"kas build --project {project_dir}",
            run_at=now_iso(),
            notes="; ".join(problems) if problems else note,
        )
        written.append(evidence.write(project_dir))
    return written


# ---------------------------------------------------------------- status write


def _update_status(project_dir: Path, manifest, result: BuildResult, config) -> None:
    written_records = len(result.ingested.records)
    written_notes = len(result.notebooks)
    completed = [
        f"Ingested {written_records} source(s); {len(result.ingested.skipped)} reused unchanged",
        f"Transcripts available for {len(result.transcripts)} source(s)",
        f"Notes written for {written_notes} source(s) with timestamp provenance",
        f"Knowledge units: {len(result.units)}; procedures: {len(result.procedures)}; source map: {len(result.ingested.records)} entries",
        "Evidence written for AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-15",
    ]
    risks = [
        "OQ-6 (copyright) remains open; notes quote the source and are not publishable drafts",
    ]
    for failure in result.failures:
        risks.append(f"Failure: {failure}")
    for record in result.ingested.failed:
        risks.append(f"Quarantined/failed: {record.origin} — {record.reason}")

    record = StatusRecord(
        project_id=manifest.project_id,
        phase=PHASE3,
        completed=completed if result.ok else completed[:1],
        evidence=[str(path.relative_to(project_dir)) for path in result.evidence],
        decisions=[
            "ADR-004 — content-addressed ids, immutable raw, verification gate",
            "ADR-005 — LLM7 primary with Groq Whisper fallback for timestamps",
            "ADR-006 — cookies via browser profile for reels; no local model fallback",
        ],
        risks=risks,
        remaining=[
            "Phase 4 — vault projection and hand-edit detection (AC-24, AC-25)",
            "Phase 4 — daemon trigger and publishable content (ADR-006)",
            "Phase 5 — QA report, application, derived content, Skill packaging (AC-20…AC-23)",
            "OQ-5/6/8 remain open with documented defaults",
        ],
        next_task="Implement knowledge units and the source map (AC-07, AC-09)",
        updated_at=now_iso(),
    )
    record.write(project_dir, write_markdown=bool(config.get("status.write_markdown", True)))


def update_status_complete(project_dir: Path, manifest, config) -> None:
    project_dir = Path(project_dir)
    ev_dir = project_dir / "evidence"
    ev_files = sorted([str(p.relative_to(project_dir)) for p in ev_dir.glob("*.json")]) if ev_dir.is_dir() else []

    status_path = project_dir / "status.json"
    prev_completed = []
    if status_path.is_file():
        try:
            prev_completed = json.loads(status_path.read_text(encoding="utf-8")).get("completed", [])
        except Exception:
            pass

    completed = [item for item in prev_completed if not item.startswith("Phase")]
    for c in (
        "Phase 4 — Vault projected with frontmatter and hand-edit guards",
        "Phase 5 — Derived content, application report and QA report generated",
    ):
        if c not in completed:
            completed.append(c)

    record = StatusRecord(
        project_id=manifest.project_id,
        phase=PHASE5,
        completed=completed,
        evidence=ev_files,
        decisions=[
            "ADR-004 — content-addressed ids, immutable raw, verification gate",
            "ADR-005 — LLM7 primary with Groq Whisper fallback for timestamps",
            "ADR-006 — cookies via browser profile for reels; no local model fallback",
        ],
        risks=[
            "OQ-6 (copyright) remains open; notes quote the source and are not publishable drafts",
        ],
        remaining=[],
        next_task="none — all phases complete",
        updated_at=now_iso(),
    )
    record.write(project_dir, write_markdown=bool(config.get("status.write_markdown", True)))


# ---------------------------------------------------------------------- build


def build(
    manifest,
    project_dir: Path,
    config,
    registry: dict | None = None,
    transcriber=None,
    client=None,
    timeout: int = 600,
) -> BuildResult:
    project_dir = Path(project_dir)
    set_network_enabled(bool(config.get('network.enabled', True)))
    registry = default_registry() if registry is None else registry

    summary = ingest(manifest, project_dir, config, registry, timeout=timeout)
    records = load_source_records(project_dir)

    ingest_problems = verify_source_records(project_dir, records)
    ingest_problems += [f"{record.origin}: {record.reason}" for record in summary.failed]
    transcripts, transcript_problems = transcribe_pending(project_dir, records, config, transcriber)
    notebooks, note_problems = generate_notes(project_dir, records, transcripts, config, client)

    units, procedures, knowledge_failures = build_knowledge(project_dir, records, transcripts, config, client)

    failures = [f"{record.origin}: {record.reason}" for record in summary.failed]
    failures += transcript_problems + note_problems + knowledge_failures

    result = BuildResult(
        ingested=summary,
        transcripts=transcripts,
        notebooks=notebooks,
        units=units,
        procedures=procedures,
        failures=failures,
    )
    result.evidence = _write_evidence(
        project_dir,
        records,
        transcripts,
        notebooks,
        ingest_problems,
        transcript_problems,
        note_problems,
        knowledge_failures,
    )
    _update_status(project_dir, manifest, result, config)
    return result
