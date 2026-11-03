from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

VALID_MANIFEST = textwrap.dedent(
    """
    project_id: reels-demo
    goal: Turn saved reels into publishable scripts
    language: en
    sources:
      - kind: video
        origin: https://www.youtube.com/watch?v=abc123
        title: How to build a habit
        author: Some Channel
      - kind: video
        origin: https://www.instagram.com/reel/XYZ/
        title: Three note-taking tricks
        cookies_from_browser: firefox
    """
).lstrip()


@pytest.fixture()
def valid_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(VALID_MANIFEST, encoding="utf-8")
    return path


@pytest.fixture()
def write_manifest(tmp_path: Path):
    def _write(text: str, name: str = "manifest.yaml") -> Path:
        path = tmp_path / name
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path

    return _write
