import json
from pathlib import Path
from http.client import HTTPConnection
from threading import Thread
import time

from kas.server import KasStudioHandler, extract_youtube_id, export_as_antigravity_skill, load_project_data
from http.server import ThreadingHTTPServer


def test_extract_youtube_id():
    assert extract_youtube_id("https://www.youtube.com/watch?v=9oJySubZRSA") == "9oJySubZRSA"
    assert extract_youtube_id("https://youtu.be/9oJySubZRSA?t=10") == "9oJySubZRSA"
    assert extract_youtube_id("https://www.youtube.com/embed/9oJySubZRSA") == "9oJySubZRSA"
    assert extract_youtube_id("invalid-url") is None


def test_export_as_antigravity_skill():
    mock_data = {
        "project_id": "test-project",
        "manifest": {"goal": "Test goal"},
        "procedures": [
            {"title": "Test Proc", "steps": ["Step 1", "Step 2"]}
        ],
        "units": [
            {"id": "k-001", "statement": "Test rule"}
        ]
    }
    skill_md = export_as_antigravity_skill(mock_data)
    assert "name: test-project" in skill_md
    assert "Test Proc" in skill_md
    assert "Step 1" in skill_md
    assert "k-001" in skill_md


def test_server_routes():
    workspace = Path(__file__).parent.parent
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args, **kwargs: KasStudioHandler(*args, workspace_root=workspace, **kwargs)
    )
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()

    conn = HTTPConnection("127.0.0.1", port)

    # 1. GET /
    conn.request("GET", "/")
    res = conn.getresponse()
    assert res.status == 200
    body = res.read().decode("utf-8")
    assert "Knowledge Acquisition Studio" in body

    # 2. GET /api/projects
    conn.request("GET", "/api/projects")
    res = conn.getresponse()
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert "projects" in data

    # 3. GET /api/project
    conn.request("GET", "/api/project?name=claude-tutorial")
    res = conn.getresponse()
    assert res.status == 200
    pdata = json.loads(res.read().decode("utf-8"))
    assert pdata["project_id"] == "claude-tutorial"
    assert len(pdata["units"]) > 0

    # 4. GET /api/skills
    conn.request("GET", "/api/skills?path=projects/claude-tutorial&q=prompt")
    res = conn.getresponse()
    assert res.status == 200
    sdata = json.loads(res.read().decode("utf-8"))
    assert sdata["count"] > 0

    # 5. GET /api/export/skill
    conn.request("GET", "/api/export/skill?path=projects/claude-tutorial")
    res = conn.getresponse()
    assert res.status == 200
    assert "attachment" in res.headers.get("Content-Disposition", "")
    content = res.read().decode("utf-8")
    assert "name: claude-tutorial" in content

    conn.close()
    server.shutdown()
    server.server_close()
