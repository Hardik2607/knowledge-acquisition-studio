"""AC-24, AC-25 — Obsidian vault projection and hand-edit detection."""

from __future__ import annotations

import json
from pathlib import Path

from kas.cli import main
from kas.models import SourceRecord
from kas.vault import (
    VAULT_FOLDERS,
    _frontmatter,
    _split_frontmatter,
    ensure_vault,
    load_and_project,
    project,
)


def test_ensure_vault_creates_expected_folders(tmp_path: Path) -> None:
    vault_dir = tmp_path / "test-vault"
    ensured = ensure_vault(vault_dir)
    assert ensured == vault_dir
    for folder in VAULT_FOLDERS:
        assert (vault_dir / folder).is_dir()


def test_frontmatter_render_and_split() -> None:
    fields = {
        "source_id": "src-1234567890ab",
        "provider": "llm7",
        "schema_version": 1,
        "source_uri": "https://example.com/video",
    }
    rendered = _frontmatter(fields)
    assert rendered.startswith("---\n")
    assert rendered.endswith("---\n")

    parsed, body = _split_frontmatter(rendered + "\nHello world\n")
    assert parsed["source_id"] == "src-1234567890ab"
    assert parsed["provider"] == "llm7"
    assert parsed["schema_version"] == "1"
    assert "Hello world" in body


def make_dummy_project(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "manifest.yaml").write_text(
        "project_id: vault-demo\ngoal: test vault projection\nsources:\n"
        "  - kind: video\n    origin: https://www.youtube.com/watch?v=abc\n    title: Test Video\n",
        encoding="utf-8",
    )
    # sources
    src_dir = project_dir / "sources" / "src-8e18a126899c"
    src_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "source_id": "src-8e18a126899c",
        "kind": "video",
        "origin": "https://www.youtube.com/watch?v=abc",
        "title": "Test Video",
        "author": "tester",
        "license": "cc-by",
        "language": "en",
        "checksum": "8e18a126899c111122223333444455556666777788889999aaaabbbbccccdddd",
        "raw_path": "sources/src-8e18a126899c/raw.mp4",
        "retrieved_at": "2026-11-03T00:00:00Z",
        "status": "stored",
    }
    (src_dir / "source.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (src_dir / "raw.mp4").write_bytes(b"dummy")

    # notes
    notes_dir = project_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_data = {
        "source_id": "src-8e18a126899c",
        "provider": "llm7",
        "model": "deepseek",
        "notes": [
            {"source_id": "src-8e18a126899c", "start": 0.0, "end": 2.0, "range": "00:00–00:02", "text": "First point"}
        ],
    }
    (notes_dir / "src-8e18a126899c.json").write_text(json.dumps(notes_data, indent=2), encoding="utf-8")

    # knowledge
    k_dir = project_dir / "knowledge"
    k_dir.mkdir(parents=True, exist_ok=True)
    units_data = {
        "units": [
            {
                "id": "k-111122223333",
                "statement": "An elephant has a trunk",
                "source_refs": [{"source_id": "src-8e18a126899c", "start": 0.0, "end": 2.0}],
                "confidence": "high",
            }
        ]
    }
    (k_dir / "units.json").write_text(json.dumps(units_data, indent=2), encoding="utf-8")

    # procedures
    proc_dir = k_dir / "procedures"
    proc_dir.mkdir(parents=True, exist_ok=True)
    proc_text = "# Identifying an elephant\n\n1. Look for trunk [[k-111122223333]]\n"
    (proc_dir / "p-identify-elephant.md").write_text(proc_text, encoding="utf-8")


def test_vault_projection_fidelity_ac24(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    vault_dir = tmp_path / "vault"
    make_dummy_project(project_dir)

    written, conflicts = load_and_project(project_dir, vault_dir)

    assert not conflicts
    assert len(written) == 4  # 1 source, 1 note, 1 unit, 1 procedure

    # Sources note
    src_note = vault_dir / "Sources" / "src-8e18a126899c.md"
    assert src_note.is_file()
    fields, body = _split_frontmatter(src_note.read_text(encoding="utf-8"))
    assert fields["source_id"] == "src-8e18a126899c"
    assert "content_hash" in fields
    assert "Test Video" in body

    # Notes note
    notes_note = vault_dir / "Notes" / "src-8e18a126899c.md"
    assert notes_note.is_file()
    n_fields, n_body = _split_frontmatter(notes_note.read_text(encoding="utf-8"))
    assert n_fields["source_id"] == "src-8e18a126899c"
    assert "First point" in n_body

    # Knowledge note
    k_note = vault_dir / "Knowledge" / "k-111122223333.md"
    assert k_note.is_file()
    k_fields, k_body = _split_frontmatter(k_note.read_text(encoding="utf-8"))
    assert "An elephant has a trunk" in k_body
    assert "[[src-8e18a126899c]]" in k_body

    # Procedure note
    p_note = vault_dir / "Procedures" / "p-identify-elephant.md"
    assert p_note.is_file()
    p_fields, p_body = _split_frontmatter(p_note.read_text(encoding="utf-8"))
    assert "[[k-111122223333]]" in p_body

    # Evidence written
    evidence_path = project_dir / "evidence" / "t-vault.json"
    assert evidence_path.is_file()
    ev_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert ev_data["result"] == "pass"
    assert "AC-24" in ev_data["criteria"]
    assert "AC-25" in ev_data["criteria"]


def test_vault_projection_idempotent_ac24(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    vault_dir = tmp_path / "vault"
    make_dummy_project(project_dir)

    written1, conflicts1 = load_and_project(project_dir, vault_dir)
    assert len(written1) == 4
    assert not conflicts1

    k_note = vault_dir / "Knowledge" / "k-111122223333.md"
    content_before = k_note.read_text(encoding="utf-8")

    written2, conflicts2 = load_and_project(project_dir, vault_dir)
    assert len(written2) == 4
    assert not conflicts2

    content_after = k_note.read_text(encoding="utf-8")
    assert content_before == content_after


def test_vault_hand_edit_detection_ac25(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    vault_dir = tmp_path / "vault"
    make_dummy_project(project_dir)

    written, conflicts = load_and_project(project_dir, vault_dir)
    assert not conflicts

    # Hand-edit the body of a knowledge note
    k_note = vault_dir / "Knowledge" / "k-111122223333.md"
    original_text = k_note.read_text(encoding="utf-8")
    modified_text = original_text + "\n<!-- user hand-edit comment -->\n"
    k_note.write_text(modified_text, encoding="utf-8")

    # Project again
    written2, conflicts2 = load_and_project(project_dir, vault_dir)

    assert str(k_note) in conflicts2
    assert k_note.read_text(encoding="utf-8") == modified_text  # NOT overwritten


def test_vault_cli(tmp_path: Path, capsys) -> None:
    project_dir = tmp_path / "proj"
    vault_dir = tmp_path / "vault"
    make_dummy_project(project_dir)

    code = main(["vault", "--project", str(project_dir), "--vault", str(vault_dir)])
    assert code == 0
    out = capsys.readouterr().out
    assert "projected 4 notes" in out
