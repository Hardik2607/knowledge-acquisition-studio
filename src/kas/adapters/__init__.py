"""Adapter registry."""

from __future__ import annotations

from .git import GitAdapter
from .video import VideoAdapter, build_adapter

DEFAULT_KINDS = ("video", "audio")


def default_registry(binary: str | None = None) -> dict:
    video_adapter = VideoAdapter(binary)
    git_adapter = GitAdapter()
    reg = {kind: video_adapter for kind in DEFAULT_KINDS}
    reg["git"] = git_adapter
    reg["repo"] = git_adapter
    return reg


__all__ = [
    "GitAdapter",
    "VideoAdapter",
    "build_adapter",
    "default_registry",
    "DEFAULT_KINDS",
]
