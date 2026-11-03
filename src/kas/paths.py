"""Path confinement (AC-18).

A manifest may point at a remote URI (http, https, or a yt-dlp-supported site) or at a
local file. A local file must live inside the project root. Nothing is written before
this check, so a traversal attempt can never create a file outside the project.
"""

from __future__ import annotations

import re
from pathlib import Path

_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def is_remote(origin: str) -> bool:
    """True for anything that is not a local path."""
    return bool(_SCHEME.match(origin)) or origin.startswith("www.")


def confine_path(origin: str, root: Path) -> tuple[Path | None, str | None]:
    """Resolve a local origin against ``root``.

    Returns ``(path, None)`` when the path stays inside the root, otherwise
    ``(None, reason)``.
    """
    root = Path(root).resolve()
    candidate = Path(origin).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"{origin!r} resolves outside the project root ({root})"
    return resolved, None
