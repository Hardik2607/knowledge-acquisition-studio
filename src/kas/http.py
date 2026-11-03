"""Minimal HTTP helpers (stdlib only).

Kept deliberately small: JSON POST and multipart POST are all the providers need.
Every call is bounded by a timeout and surfaces the provider's error body verbatim,
because "401" alone is not a diagnosis.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Some providers sit behind Cloudflare, which rejects the default
# ``Python-urllib/3.x`` agent with HTTP 403 / error 1010. Identify honestly instead.
USER_AGENT = "kas/0.1 (Knowledge Acquisition Studio)"

NETWORK_ENABLED = True


def set_network_enabled(value: bool) -> None:
    global NETWORK_ENABLED
    NETWORK_ENABLED = bool(value)


def network_enabled() -> bool:
    return NETWORK_ENABLED


class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body[:800]
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {self.body}")


def _request(request: urllib.request.Request, timeout: int) -> bytes:
    if not NETWORK_ENABLED:
        raise HttpError(0, "network disabled by configuration (AC-17)", request.full_url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, body, request.full_url) from exc
    except urllib.error.URLError as exc:
        raise HttpError(0, str(exc.reason), request.full_url) from exc


def post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    return json.loads(_request(request, timeout).decode("utf-8"))


def post_multipart(
    url: str,
    fields: dict[str, str],
    files: dict[str, Path],
    headers: dict,
    timeout: int = 300,
) -> dict:
    boundary = f"----kas{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'
            ).encode()
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
            **headers,
        },
        method="POST",
    )
    return json.loads(_request(request, timeout).decode("utf-8"))
