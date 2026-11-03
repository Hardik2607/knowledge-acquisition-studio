"""Configuration schema and loader.

Rules (ADR-004 D6, ADR-005 D15, ADR-006):

* unknown keys are errors with their dotted path (AC-19);
* secrets are referenced by environment-variable **name** only;
* a literal that looks like a secret is rejected;
* defaults are merged for absent keys, never for unknown ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import FieldError, ValidationError, type_name

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_PREFIXES = ("sk-", "gsk_", "hf_", "xoxb-", "xoxp-", "glpat-", "ghp_", "nvapi-")

DEFAULTS: dict[str, Any] = {
    "project": {"version": "0.1.0", "mode": "local-first", "name": None},
    "orchestrator": {"auto_continue": True, "max_retries": 3, "lock_timeout_seconds": 600},
    "verification": {
        "require_evidence": True,
        "fail_on_missing_artifact": True,
        "require_distinct_verify_model": True,
    },
    "status": {"update_after_each_task": True, "write_markdown": True},
    "providers": {
        "extract": {
            "name": "llm7",
            "base_url": "https://api.llm7.io/v1",
            "api_key_env": "LLM7_API_KEY",
            "model": "DeepSeek-V4-Flash-0731",
            "timeout_seconds": 300,
        },
        "verify": {
            "name": "llm7",
            "base_url": "https://api.llm7.io/v1",
            "api_key_env": "LLM7_API_KEY",
            "model": "GLM-5.3-Flash",
            "timeout_seconds": 120,
        },
        "transcribe": {
            "name": "llm7",
            "base_url": "https://api.llm7.io/v1",
            "api_key_env": "LLM7_API_KEY",
            "model": "Voxtral-Small-24B-2507",
            "timeout_seconds": 300,
        },
        "research": {
            "name": "tavily",
            "base_url": "https://api.tavily.com",
            "api_key_env": "TAVILY_API_KEY",
            "model": "search",
            "timeout_seconds": 60,
        },
        "failover": {
            "name": "unorouter",
            "base_url": "https://api.unorouter.com/v1",
            "api_key_env": "UNOROUTER_API_KEY",
            "model": "mistral-small-3.2:free",
            "timeout_seconds": 120,
        },
    },
    "network": {"enabled": True},
    "retention": {"keep_raw": True, "purge_raw": False},
    "paths": {"vault": "~/Obsidian/knowledge-vault", "runtime": "runtime"},
    "daemon": {"inbox": "runtime/inbox", "poll_seconds": 5, "max_parallel": 1},
    "sources": {
        "youtube": {"prefer_subtitles": True, "languages": ["en", "hi"]},
        "reels": {"cookies_from_browser": "firefox", "cookies_file": None},
    },
}

# Expected type per leaf: "string" | "integer" | "boolean" | "list" | ("enum", (...))
SCHEMA: dict[str, Any] = {
    "project": {"version": "string", "mode": ("enum", ("local-first", "api")), "name": ("string", "nullable")},
    "orchestrator": {
        "auto_continue": "boolean",
        "max_retries": "integer",
        "lock_timeout_seconds": "integer",
    },
    "verification": {
        "require_evidence": "boolean",
        "fail_on_missing_artifact": "boolean",
        "require_distinct_verify_model": "boolean",
    },
    "status": {"update_after_each_task": "boolean", "write_markdown": "boolean"},
    "providers": {
        stage: {
            "name": "string",
            "base_url": "string",
            "api_key_env": "string",
            "model": "string",
            "timeout_seconds": "integer",
        }
        for stage in ("extract", "verify", "transcribe", "research", "failover")
    },
    "network": {"enabled": "boolean"},
    "retention": {"keep_raw": "boolean", "purge_raw": "boolean"},
    "paths": {"vault": "string", "runtime": "string"},
    "daemon": {"inbox": "string", "poll_seconds": "integer", "max_parallel": "integer"},
    "sources": {
        "youtube": {"prefer_subtitles": "boolean", "languages": "list"},
        "reels": {"cookies_from_browser": ("string", "nullable"), "cookies_file": ("string", "nullable")},
    },
}


@dataclass(frozen=True)
class Provider:
    stage: str
    name: str
    base_url: str
    api_key_env: str
    model: str
    timeout_seconds: int = 120


@dataclass(frozen=True)
class Config:
    data: dict[str, Any]
    path: Path | None = None
    providers: dict[str, Provider] = field(default_factory=dict)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _is_secret_like(value: str) -> bool:
    return len(value) >= 20 and value.lower().startswith(SECRET_PREFIXES)


def _walk(
    node: Any,
    schema: dict[str, Any],
    prefix: str,
    errors: list[FieldError],
    merged: dict[str, Any],
) -> None:
    if not isinstance(node, dict):
        errors.append(FieldError(prefix or "config", "mapping", type_name(node)))
        return

    for key, raw in schema.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in node or node[key] is None:
            merged[key] = None
            continue
        value = node[key]
        if isinstance(raw, dict):
            child: dict[str, Any] = {}
            _walk(value, raw, path, errors, child)
            # keep whatever children validated, even if some failed
            merged[key] = child
            continue

        nullable = False
        expected = raw
        if isinstance(raw, tuple) and raw[1] == "nullable":
            nullable, expected = True, raw[0]
        if isinstance(expected, tuple) and expected[0] == "enum":
            allowed = expected[1]
            if value not in allowed:
                errors.append(FieldError(path, f"one of {allowed}", repr(value)))
            else:
                merged[key] = value
            continue

        if value is None and nullable:
            merged[key] = None
            continue

        ok = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "list": isinstance(value, list),
        }[expected]
        if not ok:
            errors.append(FieldError(path, expected, type_name(value)))
            continue

        if expected == "string" and _is_secret_like(value):
            errors.append(
                FieldError(
                    path,
                    "an environment variable name, not a literal secret",
                    "value that looks like an API key",
                    "secrets must be referenced by name (ADR-005 D15)",
                )
            )
            continue

        merged[key] = value

    for key in node:
        if key not in schema:
            errors.append(
                FieldError(
                    f"{prefix}.{key}" if prefix else key,
                    "a known configuration key",
                    f"unknown key {key!r}",
                    "unknown keys are rejected rather than ignored (AC-19)",
                )
            )


def _merge(defaults: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            out[key] = _merge(value, override.get(key) or {})
        else:
            out[key] = override[key] if key in override and override[key] is not None else value
    return out


def load_config(path: Path | None = None) -> Config:
    """Load config, merging defaults. Raises ValidationError on any invalid key."""
    raw: dict[str, Any] = {}
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise ValidationError("config", [FieldError(str(path), "existing file", "missing")])
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValidationError(
                "config", [FieldError(str(path), "valid YAML", "parse error", str(exc))]
            ) from exc
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValidationError(
                    "config", [FieldError("config", "mapping", type_name(loaded))]
                )
            raw = loaded

    errors: list[FieldError] = []
    validated: dict[str, Any] = {}
    _walk(raw, SCHEMA, "", errors, validated)

    # every provider must name a valid env variable
    for stage, block in (validated.get("providers") or {}).items():
        env = (block or {}).get("api_key_env")
        if isinstance(env, str) and not ENV_NAME.match(env):
            errors.append(
                FieldError(
                    f"providers.{stage}.api_key_env",
                    "an environment variable name matching [A-Z][A-Z0-9_]*",
                    repr(env),
                )
            )

    if errors:
        raise ValidationError("config", errors)

    data = _merge(DEFAULTS, validated)

    providers = {
        stage: Provider(
            stage=stage,
            name=block["name"],
            base_url=block["base_url"],
            api_key_env=block["api_key_env"],
            model=block["model"],
            timeout_seconds=block.get("timeout_seconds", 120),
        )
        for stage, block in data["providers"].items()
    }

    if data["verification"].get("require_distinct_verify_model"):
        if providers["extract"].model == providers["verify"].model:
            raise ValidationError(
                "config",
                [
                    FieldError(
                        "providers.verify.model",
                        "a model different from providers.extract.model",
                        repr(providers["verify"].model),
                        "verification must not reuse the generator's model (ADR-005 D11)",
                    )
                ],
            )

    return Config(data=data, path=path, providers=providers)
