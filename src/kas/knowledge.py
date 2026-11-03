"""Knowledge units, procedures and source map (AC-07, AC-08, AC-09)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extract import (
    ExtractionError,
    ChatClient,
    build_procedures,
    extract_units as _extract_units,
    validate_procedures,
    validate_units,
)
from .ids import procedure_id_for, unit_id_for
from .extract import Procedure
from .models import KnowledgeUnit, SourceRecord, Transcript


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _titles(records: dict[str, SourceRecord]) -> dict[str, str]:
    return {sid: record.title for sid, record in records.items()}


def build_units(
    project_dir: Path,
    transcripts: list[Transcript],
    records: dict[str, SourceRecord],
    config,
    client=None,
) -> tuple[list[KnowledgeUnit], list[str]]:
    project_dir = Path(project_dir)
    knowledge_dir = project_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        client = ChatClient(config, stage="extract")

    failures: list[str] = []
    try:
        units = _extract_units(client, transcripts, _titles(records))
    except ExtractionError as exc:
        return [], [f"units: {exc.code}: {exc.message}"]

    problems = validate_units(units, {t.source_id: t for t in transcripts})
    if problems:
        failures.extend(f"units: {problem}" for problem in problems)

    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "provider": getattr(client, "provider", {}).name if hasattr(client, "provider") else "llm7",
        "model": None,
        "units": [unit.to_dict() for unit in units],
    }
    # producer is the configured extract provider; the fake client has no provider attr
    payload["provider"] = getattr(getattr(client, "provider", None), "name", "llm7")
    if getattr(client, "provider", None) is not None:
        payload["model"] = getattr(client.provider, "model", None)
    (knowledge_dir / "units.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return units, failures


def build_procedures_stage(
    project_dir: Path,
    units: list[KnowledgeUnit],
    config,
    client=None,
) -> tuple[list[Procedure], list[str]]:
    project_dir = Path(project_dir)
    procedures_dir = project_dir / "knowledge" / "procedures"
    procedures_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        client = ChatClient(config, stage="extract")

    failures: list[str] = []
    if not units:
        return [], ["procedures: no knowledge units available"]

    # clear stale procedure files so re-runs do not leave orphans
    for stale in procedures_dir.glob("*.md"):
        stale.unlink()

    try:
        procedures = build_procedures(client, units)
    except ExtractionError as exc:
        return [], [f"procedures: {exc.code}: {exc.message}"]

    problems = validate_procedures(procedures, units)
    if problems:
        failures.extend(f"procedures: {problem}" for problem in problems)

    for procedure in procedures:
        path = procedures_dir / f"{procedure.id}.md"
        if path.exists():
            path = procedures_dir / f"{procedure.id}-{len(list(procedures_dir.glob(procedure.id + '*.md')))}".replace("--", "-") + ".md"
        path.write_text(procedure.to_markdown(), encoding="utf-8")

    return procedures, failures


def build_source_map(
    project_dir: Path,
    records: dict[str, SourceRecord],
) -> tuple[list[dict[str, Any]], list[str]]:
    project_dir = Path(project_dir)
    knowledge_dir = project_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    entries = [{"source_id": sid} for sid in sorted(records)]
    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "entries": entries,
    }
    (knowledge_dir / "source-map.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    problems: list[str] = []
    if len(entries) != len(records):
        problems.append("source-map: entry count does not match ingested source count")
    if len({e["source_id"] for e in entries}) != len(entries):
        problems.append("source-map: duplicate source_id")
    for entry in entries:
        if entry["source_id"] not in records:
            problems.append(f"source-map: unknown source {entry['source_id']}")
    return entries, problems


def validate_knowledge(project_dir: Path, records: dict[str, SourceRecord]) -> list[str]:
    """AC-07, AC-08, AC-09, AC-15: structural + provenance checks."""
    project_dir = Path(project_dir)
    problems: list[str] = []

    units_path = project_dir / "knowledge" / "units.json"
    if not units_path.is_file():
        problems.append("knowledge/units.json is missing")
        units = []
    else:
        try:
            data = json.loads(units_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"units.json: invalid JSON ({exc})")
            data = {}
        units = data.get("units", []) if isinstance(data, dict) else []
        ids = []
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                problems.append(f"unit {index}: not an object")
                continue
            for field_name in ("id", "statement", "source_refs", "confidence"):
                if field_name not in unit:
                    problems.append(f"unit {index}: missing {field_name}")
            uid = unit.get("id")
            statement = unit.get("statement", "")
            if uid is not None and uid != unit_id_for(str(statement)):
                problems.append(f"unit {index}: id does not match statement hash")
            if uid in ids:
                problems.append(f"unit {index}: duplicate id {uid}")
            ids.append(uid)
            if unit.get("confidence") not in {"low", "medium", "high"}:
                problems.append(f"unit {index}: bad confidence")
            refs = unit.get("source_refs") or []
            if not refs:
                problems.append(f"unit {index}: no source_refs")
            for ref in refs:
                if not isinstance(ref, dict) or ref.get("source_id") not in records:
                    problems.append(f"unit {index}: dangling source ref {ref!r}")

    # procedures
    procedures_dir = project_dir / "knowledge" / "procedures"
    procedure_files = list(procedures_dir.glob("*.md")) if procedures_dir.is_dir() else []
    known_unit_ids = {u.get("id") for u in units if isinstance(u, dict)}
    for path in procedure_files:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            problems.append(f"{path.name}: empty procedure")
            continue
        # numbered steps: lines starting with digit + "."
        steps = [line for line in text.splitlines() if line.strip()[:1].isdigit()]
        if not steps:
            problems.append(f"{path.name}: no numbered steps")
        for step in steps:
            # extract [[k-...]] references
            refs = [token.strip("[]") for token in step.split() if token.strip("[]").startswith("k-")]
            if not refs:
                problems.append(f"{path.name}: step with no unit reference: {step[:60]!r}")
            for ref in refs:
                if ref not in known_unit_ids:
                    problems.append(f"{path.name}: unknown unit {ref}")

    # source map
    sm_path = project_dir / "knowledge" / "source-map.json"
    if not sm_path.is_file():
        problems.append("knowledge/source-map.json is missing")
    else:
        try:
            sm = json.loads(sm_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"source-map.json: invalid JSON ({exc})")
            sm = {}
        entries = sm.get("entries", []) if isinstance(sm, dict) else []
        if len(entries) != len(records):
            problems.append(f"source-map: {len(entries)} entries, expected {len(records)}")
        seen = set()
        for entry in entries:
            sid = entry.get("source_id") if isinstance(entry, dict) else None
            if sid in seen:
                problems.append(f"source-map: duplicate {sid}")
            seen.add(sid)
            if sid not in records:
                problems.append(f"source-map: unknown source {sid}")

    # provenance sweep: notes must resolve
    notes_dir = project_dir / "notes"
    if notes_dir.is_dir():
        for path in notes_dir.glob("*.json"):
            try:
                note = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                problems.append(f"{path.name}: invalid JSON")
                continue
            sid = note.get("source_id")
            if sid not in records:
                problems.append(f"{path.name}: dangling source_id {sid!r}")

    return problems


def build_knowledge(project_dir, records, transcripts, config, client=None):
    """Orchestrate units + procedures + source map. Returns (units, procedures, failures)."""
    from .extract import ChatClient

    if client is None:
        client = ChatClient(config, stage="extract")

    units, unit_failures = build_units(project_dir, list(transcripts.values()), records, config, client)
    procedures, proc_failures = build_procedures_stage(project_dir, units, config, client)
    _entries, sm_failures = build_source_map(project_dir, records)

    failures = list(unit_failures) + list(proc_failures) + list(sm_failures)

    # provenance check
    prov = validate_knowledge(project_dir, records)
    failures.extend(f"provenance: {p}" for p in prov)

    return units, procedures, failures
