"""AC-16 / AC-17 — offline mode blocks outbound attempts."""

from __future__ import annotations

import pytest

from kas.config import load_config
from kas.extract import ChatClient, ExtractionError
from kas.http import set_network_enabled


def test_http_request_is_blocked_when_network_disabled() -> None:
    set_network_enabled(False)
    try:
        from kas.http import post_json

        with pytest.raises(Exception) as excinfo:
            post_json("https://example.invalid/x", {}, {}, timeout=5)
        assert "network disabled" in str(excinfo.value).lower()
    finally:
        set_network_enabled(True)


def test_chat_client_raises_when_network_disabled(tmp_path: Path) -> None:
    set_network_enabled(False)
    try:
        config = load_config(None)
        config.data["network"]["enabled"] = False
        client = ChatClient(config, stage="extract")
        with pytest.raises(ExtractionError) as excinfo:
            client.chat("system", "user")
        assert excinfo.value.code == "network_disabled"
    finally:
        set_network_enabled(True)


def test_remote_adapter_is_blocked_when_network_disabled(tmp_path: Path) -> None:
    set_network_enabled(False)
    try:
        from kas.adapters.video import VideoAdapter
        from kas.adapters.base import AdapterError

        config = load_config(None)
        config.data["network"]["enabled"] = False
        adapter = VideoAdapter()
        from kas.manifest import Source

        source = Source(kind="video", origin="https://www.youtube.com/watch?v=x", title="t")
        with pytest.raises(AdapterError) as excinfo:
            adapter.fetch(source, tmp_path / "work", config, timeout=5)
        assert excinfo.value.code == "network_disabled"
    finally:
        set_network_enabled(True)
