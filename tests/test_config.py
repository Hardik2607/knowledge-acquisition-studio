from __future__ import annotations

from pathlib import Path

import pytest

from kas.config import load_config
from kas.errors import ValidationError


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "kas.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_load_without_file() -> None:
    config = load_config(None)
    assert config.providers["extract"].model == "DeepSeek-V4-Flash-0731"
    assert config.providers["verify"].model == "GLM-5.3-Flash"
    assert config.providers["transcribe"].model == "Voxtral-Small-24B-2507"
    assert config.get("network.enabled") is True
    assert config.get("paths.vault").endswith("knowledge-vault")


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "nonsense: true\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "nonsense" in excinfo.value.render()


def test_unknown_nested_key_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "orchestrator:\n  max_retry: 5\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "orchestrator.max_retry" in excinfo.value.render()


def test_unknown_provider_stage_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers:\n  summarise:\n    model: x\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "providers.summarise" in excinfo.value.render()


def test_literal_secret_rejected(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "providers:\n  extract:\n    api_key_env: sk-abcdefghijklmnopqrstuvwxyz\n",
    )
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "looks like" in excinfo.value.render()


def test_nvidia_literal_secret_rejected(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "providers:\n  extract:\n    api_key_env: nvapi-abcdefghijklmnopqrstuvwxyz123456\n",
    )
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "looks like" in excinfo.value.render()


def test_nvidia_config_profile_loads_cleanly() -> None:
    profile = Path(__file__).resolve().parent.parent / "config" / "nvidia.yaml"
    config = load_config(profile)
    assert config.providers["extract"].name == "ollama"
    assert config.providers["extract"].model == "mistral-nemo:12b"
    assert config.providers["verify"].model == "qwen2.5-coder:7b"
    assert config.providers["transcribe"].name == "nvidia"


def test_local_9b_config_profile_loads_cleanly() -> None:
    profile = Path(__file__).resolve().parent.parent / "config" / "local-9b.yaml"
    config = load_config(profile)
    assert config.providers["extract"].name == "ollama"
    assert config.providers["extract"].model == "qwen2.5-coder:7b"
    assert config.providers["verify"].model == "qwen3:8b"
    assert config.providers["transcribe"].name == "nvidia"


def test_invalid_env_name_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers:\n  extract:\n    api_key_env: llm7_api_key\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "providers.extract.api_key_env" in excinfo.value.render()


def test_verify_model_must_differ_from_extract(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers:\n  verify:\n    model: DeepSeek-V4-Flash-0731\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "verification must not reuse" in excinfo.value.render()


def test_distinct_model_check_can_be_disabled(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "verification:\n  require_distinct_verify_model: false\n"
        "providers:\n  verify:\n    model: DeepSeek-V4-Flash-0731\n",
    )
    config = load_config(path)
    assert config.providers["verify"].model == "DeepSeek-V4-Flash-0731"


def test_partial_override_keeps_other_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers:\n  extract:\n    name: unorouter\n")
    config = load_config(path)
    assert config.providers["extract"].name == "unorouter"
    assert config.providers["extract"].base_url == "https://api.llm7.io/v1"
    assert config.providers["transcribe"].name == "llm7"


def test_wrong_type_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "orchestrator:\n  max_retries: three\n")
    with pytest.raises(ValidationError) as excinfo:
        load_config(path)
    assert "orchestrator.max_retries: expected integer, got string" in excinfo.value.render()
