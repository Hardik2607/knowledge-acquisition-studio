"""Vault projection (AC-24, AC-25)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

VAULT_FOLDERS = ("Sources", "Notes", "Knowledge", "Procedures", "Content", "Attachments", "Templates")


def ensure_vault(vault_path: Path) -> Path:
    vault_path = Path(vault_path).expanduser()
    for folder in VAULT_FOLDERS:
        (vault_path / folder).mkdir(parents=True, exist_ok=True)
    return vault_path


def _frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str) and ("\n" in value or ":" in value):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    fields: dict = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
    return fields, match.group(2)


def _projected_path(vault_path: Path, folder: str, name: str) -> Path:
    return vault_path / folder / name


def _write_note(path: Path, fields: dict, body: str, conflicts: list[str]) -> bool:
    content_hash = _hash_body(body.strip())
    fields = dict(fields)
    fields["content_hash"] = content_hash

    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        existing_fields, existing_body = _split_frontmatter(existing)
        recorded = existing_fields.get("content_hash")
        if recorded and recorded != _hash_body(existing_body.strip()):
            conflicts.append(str(path))
            return False

    rendered = _frontmatter(fields) + "\n" + body.lstrip("\n")
    if not rendered.endswith("\n"):
        rendered += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def project(project_dir, vault_path, records, transcripts, notebooks, units, procedures, generated_at):
    vault_path = ensure_vault(vault_path)
    conflicts: list[str] = []
    written: list[Path] = []

    for source_id, record in records.items():
        body = (
            f"# {record.title}\n\n"
            f"- **source_id:** `{source_id}`\n"
            f"- **origin:** {record.origin}\n"
            f"- **kind:** {record.kind}\n"
            f"- **author:** {record.author or 'unknown'}\n"
            f"- **license:** {record.license or 'unknown'}\n"
            f"- **checksum:** `{record.checksum}`\n"
        )
        path = _projected_path(vault_path, "Sources", f"{source_id}.md")
        fields = {
            "source_id": source_id,
            "source_uri": record.origin,
            "provider": "ingest",
            "model": "n/a",
            "generated_at": generated_at,
            "schema_version": 1,
        }
        if _write_note(path, fields, body, conflicts):
            written.append(path)

    for source_id, notebook in notebooks.items():
        body_lines = [f"# Notes — {source_id}", ""]
        for bullet in notebook.bullets:
            body_lines.append(f"- `{bullet['range']}` — {bullet['text']}")
        body = "\n".join(body_lines) + "\n"
        path = _projected_path(vault_path, "Notes", f"{source_id}.md")
        origin = records[source_id].origin if source_id in records else ""
        fields = {
            "source_id": source_id,
            "source_uri": origin,
            "provider": getattr(notebook, "provider", "unknown") or "unknown",
            "model": getattr(notebook, "model", "unknown") or "unknown",
            "generated_at": generated_at,
            "schema_version": 1,
        }
        if _write_note(path, fields, body, conflicts):
            written.append(path)

    for unit in units:
        uid = unit["id"] if isinstance(unit, dict) else unit.id
        statement = unit["statement"] if isinstance(unit, dict) else unit.statement
        refs = unit["source_refs"] if isinstance(unit, dict) else unit.source_refs
        confidence = unit["confidence"] if isinstance(unit, dict) else unit.confidence
        links = " ".join(f"[[{r['source_id']}]]" for r in refs)
        body = f"# {statement}\n\n**Confidence:** {confidence}\n\n**Sources:** {links}\n"
        path = _projected_path(vault_path, "Knowledge", f"{uid}.md")
        primary_source = refs[0]["source_id"] if refs else ""
        origin = records[primary_source].origin if primary_source in records else ""
        fields = {
            "source_id": primary_source,
            "source_uri": origin,
            "provider": "extract",
            "model": "llm7",
            "generated_at": generated_at,
            "schema_version": 1,
        }
        if _write_note(path, fields, body, conflicts):
            written.append(path)

    for procedure in procedures:
        pid = procedure.id if hasattr(procedure, "id") else procedure["id"]
        title = procedure.title if hasattr(procedure, "title") else procedure["title"]
        steps = procedure.steps if hasattr(procedure, "steps") else procedure["steps"]
        body_lines = [f"# {title}", ""]
        for index, step in enumerate(steps, 1):
            refs = " ".join(f"[[{uid}]]" for uid in step["unit_ids"])
            body_lines.append(f"{index}. {step['text']} {refs}".rstrip())
        body = "\n".join(body_lines) + "\n"
        primary_unit = steps[0]["unit_ids"][0] if steps and steps[0].get("unit_ids") else ""
        primary_source = ""
        for u in units:
            uid = u["id"] if isinstance(u, dict) else u.id
            if uid == primary_unit:
                refs = u["source_refs"] if isinstance(u, dict) else u.source_refs
                primary_source = refs[0]["source_id"] if refs else ""
                break
        origin = records[primary_source].origin if primary_source in records else ""
        path = _projected_path(vault_path, "Procedures", f"{pid}.md")
        fields = {
            "source_id": primary_source,
            "source_uri": origin,
            "provider": "extract",
            "model": "llm7",
            "generated_at": generated_at,
            "schema_version": 1,
        }
        if _write_note(path, fields, body, conflicts):
            written.append(path)

    return written, conflicts


def load_and_project(project_dir: Path, vault_path: Path) -> tuple[list[Path], list[str]]:
    project_dir = Path(project_dir)
    vault_path = Path(vault_path).expanduser()

    records = {}
    sources_dir = project_dir / "sources"
    if sources_dir.is_dir():
        from .ingest import load_source_records

        records = load_source_records(project_dir)

    notebooks = {}
    notes_dir = project_dir / "notes"
    if notes_dir.is_dir():
        for path in notes_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            notebooks[data.get("source_id")] = _NotebookProxy(data)

    units = []
    units_path = project_dir / "knowledge" / "units.json"
    if units_path.is_file():
        try:
            units = json.loads(units_path.read_text(encoding="utf-8")).get("units", [])
        except json.JSONDecodeError:
            units = []

    procedures = []
    procedures_dir = project_dir / "knowledge" / "procedures"
    if procedures_dir.is_dir():
        for path in procedures_dir.glob("*.md"):
            procedures.append(_ProcedureProxy(path))

    generated_at = _generated_at(project_dir)

    written, conflicts = project(project_dir, vault_path, records, {}, notebooks, units, procedures, generated_at)
    write_vault_evidence(project_dir, written, conflicts, generated_at)
    return written, conflicts


def write_vault_evidence(
    project_dir: Path, written: list[Path], conflicts: list[str], generated_at: str | None = None
) -> Path:
    from .models import Evidence

    project_dir = Path(project_dir)
    ev = Evidence(
        task_id="t-vault",
        criteria=["AC-24", "AC-25"],
        result="pass" if not conflicts and bool(written) else ("fail" if conflicts else "not-run"),
        artifacts=[str(p) for p in written],
        command=f"kas vault --project {project_dir}",
        run_at=generated_at or _generated_at(project_dir),
        notes=f"Projected {len(written)} notes into vault; hand-edit conflicts: {len(conflicts)}",
    )
    return ev.write(project_dir)


def _generated_at(project_dir: Path) -> str:
    status_path = project_dir / "status.json"
    if status_path.is_file():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("updated_at"):
                return data["updated_at"]
        except json.JSONDecodeError:
            pass
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _NotebookProxy:
    def __init__(self, data):
        self.source_id = data.get("source_id")
        self.provider = data.get("provider", "")
        self.model = data.get("model", "")
        self.bullets = data.get("notes", [])


class _ProcedureProxy:
    def __init__(self, path: Path):
        self.id = path.stem
        self.title = path.stem
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("# "):
                self.title = line[2:].strip()
                break
        self.steps = []
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^\d+\.\s+(.*)$", stripped)
            if not match:
                continue
            body = match.group(1)
            refs = re.findall(r"\[\[([^\]]+)\]\]", body)
            text_part = re.sub(r"\s*\[\[[^\]]+\]\]", "", body).strip()
            if text_part:
                self.steps.append({"text": text_part, "unit_ids": refs})
