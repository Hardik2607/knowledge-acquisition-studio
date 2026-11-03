"""Adapter registry."""

from __future__ import annotations

from .video import VideoAdapter, build_adapter

DEFAULT_KINDS = ("video", "audio")


def default_registry(binary: str | None = None) -> dict:
    adapter = VideoAdapter(binary)
    return {kind: adapter for kind in DEFAULT_KINDS}


__all__ = ["VideoAdapter", "build_adapter", "default_registry", "DEFAULT_KINDS"]
