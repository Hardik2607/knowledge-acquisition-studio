from __future__ import annotations

from pathlib import Path

import pytest

from kas.errors import ValidationError
from kas.manifest import load_manifest


def test_valid_manifest_loads(valid_manifest: Path) -> None:
    manifest = load_manifest(valid_manifest)
    assert manifest.project_id == "reels-demo"
    assert len(manifest.sources) == 2
    assert manifest.sources[0].kind == "video"
    assert manifest.sources[1].cookies_from_browser == "firefox"


def test_missing_required_field_reports_path(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        sources:
          - kind: video
            origin: https://example.com/v
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    rendered = excinfo.value.render()
    assert "goal: expected string, got missing" in rendered


def test_unknown_top_level_key_is_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sourcez:
          - kind: video
            origin: https://example.com/v
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "manifest.sourcez" in excinfo.value.render()


def test_unknown_source_key_is_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sources:
          - kind: video
            origin: https://example.com/v
            title: t
            quality: best
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "sources[0].quality" in excinfo.value.render()


def test_unknown_kind_is_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sources:
          - kind: hologram
            origin: https://example.com/v
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "sources[0].kind" in excinfo.value.render()


def test_empty_sources_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sources: []
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "at least one source" in excinfo.value.render()


def test_path_traversal_in_origin_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sources:
          - kind: video
            origin: ../../etc/passwd
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "path traversal" in excinfo.value.render()


def test_invalid_project_id_rejected(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: Bad Name!
        goal: g
        sources:
          - kind: video
            origin: https://example.com/v
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "project_id" in excinfo.value.render()


def test_wrong_type_reports_expected_type(write_manifest) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: 42
        sources:
          - kind: video
            origin: https://example.com/v
            title: t
        """
    )
    with pytest.raises(ValidationError) as excinfo:
        load_manifest(path)
    assert "goal: expected string, got integer" in excinfo.value.render()


def test_loading_writes_nothing(write_manifest, tmp_path: Path) -> None:
    path = write_manifest(
        """
        project_id: demo
        goal: g
        sources:
          - kind: video
            origin: https://example.com/v
            title: t
        """
    )
    before = sorted(p.name for p in tmp_path.iterdir())
    load_manifest(path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
