"""Manifest schema and loader.

The manifest is the frozen input contract (requirements §4, ADR-004 D2). Rules:

* required fields must be present and correctly typed;
* unknown keys are errors, not warnings (AC-19);
* source kinds must be known;
* every problem is reported with its dotted path (AC-01);
* loading never writes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import FieldError, ValidationError, type_name
from .paths import confine_path, is_remote

SOURCE_KINDS = ("video", "audio", "pdf", "epub", "html", "text", "image")

PROJECT_REQUIRED = {
    "project_id": "string",
    "goal": "string",
    "sources": "list",
}
PROJECT_OPTIONAL = {
    "schema_version": "integer",
    "language": "string",
    "notes": "string",
}

SOURCE_REQUIRED = {
    "kind": "string",
    "origin": "string",
    "title": "string",
}
SOURCE_OPTIONAL = {
    "author": "string",
    "license": "string",
    "language": "string",
    "cookies_from_browser": "string",
    "notes": "string",
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class Source:
    kind: str
    origin: str
    title: str
    author: str | None = None
    license: str | None = None
    language: str | None = None
    cookies_from_browser: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Manifest:
    project_id: str
    goal: str
    sources: tuple[Source, ...]
    schema_version: int = 1
    language: str | None = None
    notes: str | None = None
    path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _check_type(path: str, value: Any, expected: str, errors: list[FieldError]) -> bool:
    ok = True
    if expected == "string":
        ok = isinstance(value, str)
    elif expected == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "boolean":
        ok = isinstance(value, bool)
    elif expected == "list":
        ok = isinstance(value, list)
    elif expected == "mapping":
        ok = isinstance(value, dict)
    if not ok:
        errors.append(FieldError(path, expected, type_name(value)))
    return ok


def _validate_source(index: int, raw: Any, errors: list[FieldError], root: Path) -> Source | None:
    base = f"sources[{index}]"
    if not _check_type(base, raw, "mapping", errors):
        return None

    for key in raw:
        if key not in SOURCE_REQUIRED and key not in SOURCE_OPTIONAL:
            errors.append(
                FieldError(
                    f"{base}.{key}",
                    "a known source field",
                    f"unknown key {key!r}",
                    "unknown keys are rejected rather than ignored",
                )
            )

    for key, expected in SOURCE_REQUIRED.items():
        if key not in raw:
            errors.append(FieldError(f"{base}.{key}", expected, "missing"))
        else:
            _check_type(f"{base}.{key}", raw[key], expected, errors)

    for key, expected in SOURCE_OPTIONAL.items():
        if key in raw and raw[key] is not None:
            _check_type(f"{base}.{key}", raw[key], expected, errors)

    kind = raw.get("kind")
    if isinstance(kind, str) and kind not in SOURCE_KINDS:
        errors.append(
            FieldError(f"{base}.kind", f"one of {SOURCE_KINDS}", repr(kind))
        )

    origin = raw.get("origin")
    if isinstance(origin, str):
        if not origin.strip():
            errors.append(FieldError(f"{base}.origin", "non-empty string", "empty"))
        elif ".." in origin:
            errors.append(
                FieldError(
                    f"{base}.origin",
                    "a value without '..'",
                    repr(origin),
                    "path traversal is rejected (AC-18)",
                )
            )
        elif not is_remote(origin):
            _, problem = confine_path(origin, root)
            if problem:
                errors.append(
                    FieldError(
                        f"{base}.origin",
                        "a path inside the project root or a remote URI",
                        repr(origin),
                        problem + " (AC-18)",
                    )
                )

    if errors and any(e.path.startswith(base) for e in errors):
        return None

    return Source(
        kind=raw["kind"],
        origin=raw["origin"].strip(),
        title=raw["title"].strip(),
        author=raw.get("author"),
        license=raw.get("license"),
        language=raw.get("language"),
        cookies_from_browser=raw.get("cookies_from_browser"),
        notes=raw.get("notes"),
    )


def load_manifest(path: Path) -> Manifest:
    """Load and validate a manifest. Raises ValidationError with every problem found."""
    path = Path(path)
    if not path.is_file():
        raise ValidationError("manifest", [FieldError(str(path), "existing file", "missing")])

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValidationError(
            "manifest", [FieldError(str(path), "valid YAML", "parse error", str(exc))]
        ) from exc

    errors: list[FieldError] = []
    if not _check_type("manifest", raw, "mapping", errors):
        raise ValidationError("manifest", errors)

    for key in raw:
        if key not in PROJECT_REQUIRED and key not in PROJECT_OPTIONAL:
            errors.append(
                FieldError(
                    f"manifest.{key}",
                    "a known manifest field",
                    f"unknown key {key!r}",
                    "unknown keys are rejected rather than ignored",
                )
            )

    for key, expected in PROJECT_REQUIRED.items():
        if key not in raw:
            errors.append(FieldError(key, expected, "missing"))
        else:
            _check_type(key, raw[key], expected, errors)

    for key, expected in PROJECT_OPTIONAL.items():
        if key in raw and raw[key] is not None:
            _check_type(key, raw[key], expected, errors)

    project_id = raw.get("project_id")
    if isinstance(project_id, str) and not _SLUG.match(project_id):
        errors.append(
            FieldError(
                "project_id",
                "lowercase slug [a-z0-9_-], 2-64 chars",
                repr(project_id),
            )
        )

    sources: list[Source] = []
    raw_sources = raw.get("sources")
    if isinstance(raw_sources, list):
        if not raw_sources:
            errors.append(FieldError("sources", "at least one source", "empty list"))
        root = path.parent
        for index, item in enumerate(raw_sources):
            parsed = _validate_source(index, item, errors, root)
            if parsed is not None:
                sources.append(parsed)

    if errors:
        raise ValidationError("manifest", errors)

    return Manifest(
        project_id=raw["project_id"],
        goal=raw["goal"].strip(),
        sources=tuple(sources),
        schema_version=raw.get("schema_version", 1),
        language=raw.get("language"),
        notes=raw.get("notes"),
        path=path,
    )
