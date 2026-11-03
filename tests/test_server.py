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


def test_server_project_create(tmp_path):
    # Isolated workspace root
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "projects").mkdir()

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args, **kwargs: KasStudioHandler(*args, workspace_root=workspace, **kwargs)
    )
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()

    conn = HTTPConnection("127.0.0.1", port)

    # 1. Validation error: missing fields
    conn.request("POST", "/api/project/create", body=json.dumps({}), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 400
    res_data = json.loads(res.read().decode("utf-8"))
    assert "Missing required field" in res_data["error"]

    # 2. Validation error: invalid project_id slug
    bad_payload = {"project_id": "Bad Project!", "goal": "Some goal", "origin": "https://example.com/video"}
    conn.request("POST", "/api/project/create", body=json.dumps(bad_payload), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 400
    res_data = json.loads(res.read().decode("utf-8"))
    assert "Invalid project_id" in res_data["error"]

    # 3. Successful project creation (without auto_ingest)
    valid_payload = {
        "project_id": "demo-agent-skill",
        "goal": "Extract agent skills from tutorial video",
        "kind": "video",
        "title": "Tutorial Demo",
        "origin": "https://www.youtube.com/watch?v=9oJySubZRSA",
        "auto_ingest": False,
    }
    conn.request("POST", "/api/project/create", body=json.dumps(valid_payload), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 201
    created_data = json.loads(res.read().decode("utf-8"))
    assert created_data["status"] == "ok"
    assert created_data["project_id"] == "demo-agent-skill"

    proj_dir = workspace / "projects" / "demo-agent-skill"
    assert (proj_dir / "manifest.yaml").is_file()
    assert (proj_dir / "status.json").is_file()
    assert (proj_dir / "sources").is_dir()
    assert (proj_dir / "knowledge" / "procedures").is_dir()

    # 4. Duplicate creation conflict
    conn.request("POST", "/api/project/create", body=json.dumps(valid_payload), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 409

    # 5. Verify the newly created project appears in /api/projects
    conn.request("GET", "/api/projects")
    res = conn.getresponse()
    assert res.status == 200
    p_list = json.loads(res.read().decode("utf-8"))
    p_ids = [p["project_id"] for p in p_list["projects"]]
    assert "demo-agent-skill" in p_ids

    conn.close()
    server.shutdown()
    server.server_close()
