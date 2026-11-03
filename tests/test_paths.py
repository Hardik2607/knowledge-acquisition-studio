"""AC-18 — path confinement."""

from __future__ import annotations

from pathlib import Path

import pytest

from kas.errors import ValidationError
from kas.manifest import load_manifest
from kas.paths import confine_path, is_remote


def write_manifest(project: Path, origin: str) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    path = project / "manifest.yaml"
    path.write_text(
        "project_id: demo\ngoal: g\nsources:\n"
        f"  - kind: video\n    origin: {origin}\n    title: t\n",
        encoding="utf-8",
    )
    return path


def test_remote_origins_are_not_paths() -> None:
    assert is_remote("https://www.youtube.com/watch?v=x")
    assert is_remote("www.instagram.com/reel/x")
    assert not is_remote("media/clip.mp3")


def test_absolute_path_outside_root_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    path = write_manifest(project, str(outside))

    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)

    rendered = excinfo.value.render()
    assert "sources[0].origin" in rendered
    assert "outside the project root" in rendered


def test_absolute_path_inside_root_is_allowed(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    inside = project / "media" / "clip.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"x")
    path = write_manifest(project, str(inside))

    manifest = load_manifest(path)

    assert manifest.sources[0].origin == str(inside)


def test_relative_escape_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "proj", "../secrets.mp4")
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "path traversal" in excinfo.value.render()


def test_confine_path_reports_the_problem(tmp_path: Path) -> None:
    resolved, problem = confine_path("../../etc/passwd", tmp_path / "proj")
    assert resolved is None
    assert problem and "outside the project root" in problem
