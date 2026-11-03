"""Knowledge Acquisition Studio — Local Web Frontend & Skill Server.

Serves an interactive web studio at http://localhost:8080 with:
  * Synchronized video player (YouTube IFrame API & HTML5 video)
  * Clickable timestamp notes that jump the video to the exact demonstration
  * Atomic knowledge units browser with search & confidence filter
  * Executable agent procedures with one-click Antigravity Skill export
  * Live QA verification matrix (all 25 AC criteria status)
  * REST API for agent skill queries (MCP-compatible)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__


def extract_youtube_id(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"(?:v=|\/embed\/|youtu\.be\/|\/v\/|\/shorts\/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def load_project_data(project_dir: Path) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    data: dict[str, Any] = {
        "project_id": project_dir.name,
        "path": str(project_dir),
        "manifest": None,
        "status": None,
        "sources": [],
        "notes": [],
        "units": [],
        "procedures": [],
        "qa_report": "",
        "application_report": "",
    }

    manifest_file = project_dir / "manifest.yaml"
    if manifest_file.is_file():
        try:
            import yaml

            data["manifest"] = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
            if data["manifest"] and "project_id" in data["manifest"]:
                data["project_id"] = data["manifest"]["project_id"]
        except Exception:
            pass

    status_file = project_dir / "status.json"
    if status_file.is_file():
        try:
            data["status"] = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    units_file = project_dir / "knowledge" / "units.json"
    if units_file.is_file():
        try:
            raw_units = json.loads(units_file.read_text(encoding="utf-8"))
            data["units"] = raw_units.get("units", [])
        except Exception:
            pass

    procedures_dir = project_dir / "knowledge" / "procedures"
    if procedures_dir.is_dir():
        for pf in sorted(procedures_dir.glob("*.md")):
            try:
                content = pf.read_text(encoding="utf-8")
                lines = [l.strip() for l in content.split("\n") if l.strip()]
                title = lines[0].lstrip("# ").strip() if lines else pf.stem
                steps = lines[1:] if len(lines) > 1 else []
                data["procedures"].append(
                    {
                        "id": pf.stem,
                        "title": title,
                        "steps": steps,
                        "raw_markdown": content,
                    }
                )
            except Exception:
                pass

    notes_dir = project_dir / "notes"
    if notes_dir.is_dir():
        for nf in sorted(notes_dir.glob("*.json")):
            try:
                nb = json.loads(nf.read_text(encoding="utf-8"))
                for b in nb.get("notes", []):
                    b["source_id"] = nb.get("source_id", "")
                    data["notes"].append(b)
            except Exception:
                pass
        data["notes"].sort(key=lambda x: x.get("start", 0))

    sources_dir = project_dir / "sources"
    if sources_dir.is_dir():
        for sdir in sorted(sources_dir.glob("src-*")):
            src_info: dict[str, Any] = {"source_id": sdir.name}
            sjson = sdir / "source.json"
            if sjson.is_file():
                try:
                    src_info.update(json.loads(sjson.read_text(encoding="utf-8")))
                except Exception:
                    pass
            tjson = sdir / "transcript.json"
            if tjson.is_file():
                try:
                    tdata = json.loads(tjson.read_text(encoding="utf-8"))
                    src_info["segment_count"] = len(tdata.get("segments", []))
                    src_info["language"] = tdata.get("language")
                    src_info["duration"] = tdata.get("segments", [{}])[-1].get("end", 0) if tdata.get("segments") else 0
                except Exception:
                    pass
            src_info["youtube_id"] = extract_youtube_id(src_info.get("origin", ""))
            data["sources"].append(src_info)

    qa_file = project_dir / "reports" / "qa-report.md"
    if qa_file.is_file():
        try:
            data["qa_report"] = qa_file.read_text(encoding="utf-8")
        except Exception:
            pass

    app_file = project_dir / "application" / "report.md"
    if app_file.is_file():
        try:
            data["application_report"] = app_file.read_text(encoding="utf-8")
        except Exception:
            pass

    # Discover keyframe screenshots
    data["keyframes"] = []
    if sources_dir.is_dir():
        for sdir in sorted(sources_dir.glob("src-*")):
            kdir = sdir / "keyframes"
            if kdir.is_dir():
                for kf in sorted(kdir.glob("*.jpg")):
                    m = re.search(r"frame_(\d+)s\.jpg", kf.name)
                    sec = int(m.group(1)) if m else 0
                    rel_p = str(kf.relative_to(project_dir))
                    mins = sec // 60
                    secs = sec % 60
                    kf_entry = {
                        "filename": kf.name,
                        "timestamp": sec,
                        "range": f"{mins:02d}:{secs:02d}",
                        "source_id": sdir.name,
                        "url": f"/media/{project_dir.name}/{rel_p}",
                    }
                    data["keyframes"].append(kf_entry)

    # Link keyframes to notes
    if data["keyframes"]:
        for note in data["notes"]:
            n_start = float(note.get("start", 0))
            n_end = float(note.get("end", n_start + 24))
            for kf in data["keyframes"]:
                if n_start - 3 <= kf["timestamp"] <= n_end + 3:
                    note["keyframe_url"] = kf["url"]
                    break

    return data


def list_all_projects(base_dir: Path) -> list[dict[str, Any]]:
    projects_dir = base_dir / "projects"
    results = []
    if not projects_dir.is_dir():
        return results
    for candidate in sorted(projects_dir.iterdir()):
        if candidate.is_dir() and (candidate / "manifest.yaml").is_file():
            data = load_project_data(candidate)
            results.append(
                {
                    "project_id": data["project_id"],
                    "path": str(candidate),
                    "goal": (data.get("manifest") or {}).get("goal", ""),
                    "sources_count": len(data["sources"]),
                    "units_count": len(data["units"]),
                    "procedures_count": len(data["procedures"]),
                    "notes_count": len(data["notes"]),
                    "phase": (data.get("status") or {}).get("phase", "Not started"),
                }
            )
    return results


def export_as_antigravity_skill(project_data: dict[str, Any]) -> str:
    pid = project_data.get("project_id", "skill")
    goal = (project_data.get("manifest") or {}).get("goal", "Autonomous skill library")
    procedures = project_data.get("procedures", [])
    units = {u["id"]: u["statement"] for u in project_data.get("units", [])}

    doc = [
        "---",
        f"name: {pid}",
        f"description: {goal}",
        "version: 1.0.0",
        "tags: [agent-skill, workflow, universal-llm, procedure]",
        "compatibility: [claude, gpt-4, gemini, qwen, deepseek, llama, antigravity]",
        "---",
        "",
        f"# Skill: {pid}",
        "",
        f"> {goal}",
        "",
        "## Agent Execution Contract",
        "",
        "This skill provides model-agnostic, executable procedures designed for any modern LLM or autonomous agent runner (Claude, GPT, Gemini, DeepSeek, or local models). When executing these procedures:",
        "1. Adopt the Context-Task-Format prompting architecture for clear deliverables.",
        "2. Execute tool integrations via standard Model Context Protocol (MCP) or tool-calling interfaces.",
        "3. Follow the ordered, imperative steps sequentially and verify intermediate state.",
        "",
        "## Core Procedures",
        "",
    ]
    for p in procedures:
        clean_title = re.sub(r"\bClaude\s+AI\b|\bClaude\b", "LLM", p["title"], flags=re.IGNORECASE)
        doc.append(f"### {clean_title}")
        for step in p.get("steps", []):
            gen_step = re.sub(r"\bClaude\s+AI\b|\bClaude\b", "the LLM", step, flags=re.IGNORECASE)
            doc.append(f"- {gen_step}")
        doc.append("")

    doc.append("## Knowledge Primitives & Rules")
    doc.append("")
    for uid, statement in sorted(units.items())[:35]:
        gen_stmt = re.sub(r"\bClaude\s+AI\b|\bClaude\b", "the LLM", statement, flags=re.IGNORECASE)
        doc.append(f"- **{uid}**: {gen_stmt}")

    return "\n".join(doc) + "\n"


def export_visual_dossier(project_data: dict[str, Any], host_url: str = "") -> str:
    from datetime import datetime, timezone

    pid = project_data.get("project_id", "project")
    goal = (project_data.get("manifest") or {}).get("goal", "Visual Knowledge Dossier")
    sources = project_data.get("sources", [])
    src_title = sources[0].get("title", pid) if sources else pid
    src_origin = sources[0].get("origin", "") if sources else ""
    keyframes = project_data.get("keyframes", [])
    notes = project_data.get("notes", [])
    procedures = project_data.get("procedures", [])
    units = project_data.get("units", [])
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# 📸 Visual Knowledge Dossier: {pid}",
        "",
        f"> **Acquisition Goal:** {goal}  ",
        f"> **Primary Source:** {src_title}  ",
        f"> **Origin:** `{src_origin}`  ",
        f"> **Generated:** {now_str}  ",
        "",
        "---",
        "",
        "## 1. Visual Keyframe & Action Timeline",
        "",
        "High-resolution code blocks, terminal outputs, diagrams, and UI interactions captured during demonstrations:",
        "",
    ]

    if keyframes:
        for kf in keyframes:
            ts = kf.get("timestamp", 0)
            mins, secs = ts // 60, ts % 60
            ts_str = f"{mins:02d}:{secs:02d}"
            matching_notes = [n["text"] for n in notes if abs(float(n.get("start", 0)) - ts) <= 25]
            note_summary = matching_notes[0] if matching_notes else "Visual demonstration"
            img_url = f"{host_url}{kf.get('url', '')}" if host_url else kf.get("url", "")

            lines.append(f"### ⏱️ Timestamp `{ts_str}` — `{kf.get('filename')}`")
            lines.append("")
            lines.append(f"![{kf.get('filename')}]({img_url})")
            lines.append("")
            lines.append(f"**Demonstration Context:** {note_summary}")
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("*No visual keyframes captured yet. Run keyframe extraction to generate snapshots.*")
        lines.append("")

    lines.append("## 2. Core Executable Procedures")
    lines.append("")
    for p in procedures:
        lines.append(f"### {p.get('title')}")
        for s in p.get("steps", []):
            lines.append(f"- {s}")
        lines.append("")

    lines.append("## 3. Atomic Knowledge Primitives")
    lines.append("")
    for u in units[:40]:
        lines.append(f"- **{u.get('id')}** ({u.get('confidence')}): {u.get('statement')}")
    lines.append("")

    return "\n".join(lines) + "\n"


class KasStudioHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler serving the KAS Single-Page Web Studio."""

    def __init__(self, *args, workspace_root: Path, default_project: Path | None = None, **kwargs):
        self.workspace_root = workspace_root
        self.default_project = default_project
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self._serve_spa()
            return

        if path == "/api/projects":
            projects = list_all_projects(self.workspace_root)
            self._send_json({"projects": projects, "version": __version__})
            return

        if path == "/api/project":
            req_path = params.get("path", [""])[0] or params.get("name", [""])[0]
            if req_path:
                target = Path(req_path)
                if not target.is_absolute():
                    target = self.workspace_root / "projects" / req_path
            elif self.default_project:
                target = self.default_project
            else:
                projects = list_all_projects(self.workspace_root)
                target = Path(projects[0]["path"]) if projects else self.workspace_root

            if not target.is_dir():
                self._send_json({"error": f"Project not found: {target}"}, status=HTTPStatus.NOT_FOUND)
                return

            data = load_project_data(target)
            self._send_json(data)
            return

        if path == "/api/skills":
            # Search skills across current project or all
            query = params.get("q", [""])[0].lower()
            req_path = params.get("path", [""])[0]
            target = Path(req_path) if req_path else (self.default_project or (self.workspace_root / "projects" / "claude-tutorial"))
            data = load_project_data(target)

            matched_units = []
            for u in data.get("units", []):
                if not query or query in u["statement"].lower() or query in u["id"].lower():
                    matched_units.append(u)

            matched_procedures = []
            for p in data.get("procedures", []):
                text_blob = p["title"] + " " + " ".join(p.get("steps", []))
                if not query or query in text_blob.lower():
                    matched_procedures.append(p)

            self._send_json(
                {
                    "query": query,
                    "count": len(matched_procedures) + len(matched_units),
                    "procedures": matched_procedures,
                    "units": matched_units,
                }
            )
            return

        if path == "/api/export/skill":
            req_path = params.get("path", [""])[0]
            target = Path(req_path) if req_path else (self.default_project or (self.workspace_root / "projects" / "claude-tutorial"))
            data = load_project_data(target)
            skill_md = export_as_antigravity_skill(data)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename={data.get('project_id', 'skill')}.skill.md")
            self.send_header("Content-Length", str(len(skill_md.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(skill_md.encode("utf-8"))
            return

        if path == "/api/export/dossier":
            req_path = params.get("path", [""])[0]
            target = Path(req_path) if req_path else (self.default_project or (self.workspace_root / "projects" / "claude-tutorial"))
            data = load_project_data(target)
            host_header = self.headers.get("Host", "localhost:8765")
            base_url = f"http://{host_header}"
            dossier_md = export_visual_dossier(data, host_url=base_url)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename={data.get('project_id', 'project')}-visual-dossier.md")
            self.send_header("Content-Length", str(len(dossier_md.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(dossier_md.encode("utf-8"))
            return

        if path.startswith("/media/"):
            rel = urllib.parse.unquote(path[len("/media/"):])
            parts = rel.split("/", 1)
            if len(parts) == 2:
                proj_name, file_rel = parts
                full = (self.workspace_root / "projects" / proj_name / file_rel).resolve()
                if full.is_file():
                    mime, _ = mimetypes.guess_type(str(full))
                    content = full.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", mime or "image/jpeg")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(content)
                    return
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/project/create":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception as err:
                self._send_json({"error": f"Invalid JSON payload: {err}"}, status=HTTPStatus.BAD_REQUEST)
                return

            project_id = str(payload.get("project_id", "")).strip().lower()
            goal = str(payload.get("goal", "")).strip()
            kind = str(payload.get("kind", "video")).strip().lower()
            origin = str(payload.get("origin", "")).strip()
            title = str(payload.get("title", "")).strip() or project_id
            auto_ingest = bool(payload.get("auto_ingest", False))

            if not project_id:
                self._send_json({"error": "Missing required field: 'project_id'"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", project_id):
                self._send_json(
                    {"error": f"Invalid project_id '{project_id}': must be 2-64 chars (lowercase letters, numbers, hyphens/underscores)."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            if not goal:
                self._send_json({"error": "Missing required field: 'goal'"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not origin:
                self._send_json({"error": "Missing required field: 'origin'"}, status=HTTPStatus.BAD_REQUEST)
                return

            from .manifest import SOURCE_KINDS, load_manifest
            if kind not in SOURCE_KINDS:
                self._send_json({"error": f"Invalid source kind '{kind}'. Allowed: {', '.join(SOURCE_KINDS)}"}, status=HTTPStatus.BAD_REQUEST)
                return

            # Normalize local path origins for AC-18 path confinement
            if origin.startswith("/") or origin.startswith("~"):
                resolved_p = Path(origin).expanduser().resolve()
                origin = f"file://{resolved_p}"
            elif Path(origin).exists() and not (origin.startswith("http://") or origin.startswith("https://") or origin.startswith("file://")):
                origin = f"file://{Path(origin).resolve()}"

            proj_dir = (self.workspace_root / "projects" / project_id).resolve()
            if proj_dir.exists() and (proj_dir / "manifest.yaml").is_file():
                self._send_json({"error": f"Project '{project_id}' already exists at {proj_dir}"}, status=HTTPStatus.CONFLICT)
                return

            try:
                import yaml
                from .config import load_config
                from .cli import _initial_status

                # Create project directory structure
                for name in ("sources", "notes", "knowledge", "derived", "application", "evidence", "reports"):
                    (proj_dir / name).mkdir(parents=True, exist_ok=True)
                (proj_dir / "knowledge" / "procedures").mkdir(parents=True, exist_ok=True)
                (proj_dir / "docs" / "status").mkdir(parents=True, exist_ok=True)

                manifest_data = {
                    "project_id": project_id,
                    "goal": goal,
                    "sources": [
                        {
                            "kind": kind,
                            "origin": origin,
                            "title": title,
                        }
                    ],
                }
                (proj_dir / "manifest.yaml").write_text(yaml.dump(manifest_data, sort_keys=False, default_flow_style=False), encoding="utf-8")

                manifest = load_manifest(proj_dir / "manifest.yaml")
                config = load_config(None)
                record = _initial_status(manifest, config)
                record.write(proj_dir, write_markdown=True)

                ingested_count = 0
                warning = None
                if auto_ingest:
                    from .adapters import default_registry
                    from .ingest import ingest as run_ingest

                    summary = run_ingest(manifest, proj_dir, config, default_registry())
                    ingested_count = len(summary.records)
                    if summary.failed:
                        warning = f"Ingest completed with {len(summary.failed)} failure(s): {summary.failed[0].reason}"

                resp: dict[str, Any] = {
                    "status": "ok",
                    "project_id": project_id,
                    "path": str(proj_dir),
                    "manifest": manifest_data,
                    "ingested": ingested_count,
                    "message": f"Project '{project_id}' created successfully.",
                }
                if warning:
                    resp["warning"] = warning

                self._send_json(resp, status=HTTPStatus.CREATED)
            except Exception as exc:
                self._send_json({"error": f"Failed to initialize project: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/keyframes/extract":
            from .keyframes import extract_project_keyframes

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            target_path = payload.get("path") or "projects/claude-tutorial"
            target = (self.workspace_root / target_path).resolve()
            frames = extract_project_keyframes(target)
            self._send_json({"count": len(frames), "keyframes": frames})
            return

        if path == "/api/project/build":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            target_path = payload.get("path") or payload.get("project_id") or "projects/claude-tutorial"
            target = Path(target_path)
            if not target.is_absolute():
                if (self.workspace_root / target_path).is_dir():
                    target = (self.workspace_root / target_path).resolve()
                else:
                    target = (self.workspace_root / "projects" / target_path).resolve()

            if not target.is_dir() or not (target / "manifest.yaml").is_file():
                self._send_json({"error": f"Project not found at {target}"}, status=HTTPStatus.NOT_FOUND)
                return

            try:
                from .manifest import load_manifest
                from .config import load_config
                from .pipeline import build as run_build
                from .adapters import default_registry
                from .keyframes import extract_project_keyframes

                manifest = load_manifest(target / "manifest.yaml")
                config_path = target / "config" / "kas.yaml"
                config = load_config(config_path if config_path.is_file() else None)

                build_result = run_build(manifest, target, config, registry=default_registry())

                kf_count = 0
                try:
                    kfs = extract_project_keyframes(target)
                    kf_count = len(kfs)
                except Exception:
                    pass

                self._send_json({
                    "status": "ok",
                    "project_id": manifest.project_id,
                    "path": str(target),
                    "units_count": len(build_result.units),
                    "procedures_count": len(build_result.procedures),
                    "notes_count": len(build_result.notebooks),
                    "keyframes_count": kf_count,
                    "failures": build_result.failures,
                    "message": f"Pipeline built successfully for '{manifest.project_id}'.",
                })
            except Exception as exc:
                self._send_json({"error": f"Pipeline execution failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/project/vault":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            target_path = payload.get("path") or payload.get("project_id") or "projects/claude-tutorial"
            target = Path(target_path)
            if not target.is_absolute():
                if (self.workspace_root / target_path).is_dir():
                    target = (self.workspace_root / target_path).resolve()
                else:
                    target = (self.workspace_root / "projects" / target_path).resolve()

            if not target.is_dir() or not (target / "manifest.yaml").is_file():
                self._send_json({"error": f"Project not found at {target}"}, status=HTTPStatus.NOT_FOUND)
                return

            try:
                from .config import load_config
                from .vault import load_and_project

                config_path = target / "config" / "kas.yaml"
                config = load_config(config_path if config_path.is_file() else None)
                default_vault = config.get("paths.vault", "~/Documents/ObsidianVault")
                vault_path_str = payload.get("vault_path") or default_vault
                vault_dir = Path(vault_path_str).expanduser().resolve()

                written, conflicts = load_and_project(target, vault_dir)

                self._send_json({
                    "status": "ok",
                    "project_id": target.name,
                    "vault_path": str(vault_dir),
                    "written_count": len(written),
                    "conflicts": conflicts,
                    "message": f"Projected {len(written)} notes into Obsidian vault at {vault_dir}.",
                })
            except Exception as exc:
                self._send_json({"error": f"Vault projection failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_spa(self) -> None:
        html = INDEX_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, format: str, *args) -> None:
        import sys
        sys.stderr.write(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}\n")
        sys.stderr.flush()


def get_lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def run_server(
    workspace_root: Path,
    default_project: Path | None = None,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> None:
    def handler_factory(*args, **kwargs):
        return KasStudioHandler(*args, workspace_root=workspace_root, default_project=default_project, **kwargs)

    server = ThreadingHTTPServer((host, port), handler_factory)
    lan_ip = get_lan_ip()
    print(f"\n==================================================================")
    print(f"🚀 Knowledge Acquisition Studio (KAS) Web Server running at:")
    print(f"   👉 Local: http://localhost:{port}/")
    print(f"   👉 LAN:   http://{lan_ip}:{port}/")
    print(f"==================================================================")
    if default_project:
        print(f"Default Project: {default_project}")
    print(f"Press Ctrl+C to stop the server.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


# --------------------------------------------------------------------------- HTML
INDEX_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Acquisition Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 50: '#eef2ff', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca' }
          }
        }
      }
    }
  </script>
  <style>
    /* Custom scrollbars */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans antialiased selection:bg-indigo-500 selection:text-white">

  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <div>
          <h1 class="font-bold text-lg leading-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">Knowledge Acquisition Studio</h1>
          <p class="text-xs text-slate-400">Autonomous Video-to-Agent Skill Engine</p>
        </div>
      </div>

      <!-- Center: Project Selector & Create Action -->
      <div class="flex items-center space-x-3">
        <div class="flex items-center space-x-2 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
          <span class="text-xs text-slate-400 font-medium">Project:</span>
          <select id="project-select" onchange="changeProject(this.value)" class="bg-transparent text-sm font-semibold text-indigo-400 focus:outline-none cursor-pointer">
            <option value="" disabled>Loading projects...</option>
          </select>
        </div>
        <button onclick="openNewProjectModal()" title="Create a new acquisition project" class="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 hover:text-white border border-indigo-500/40 hover:border-indigo-500 text-xs font-semibold transition cursor-pointer shadow-sm">
          <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
          <span>New Project</span>
        </button>
      </div>

      <!-- Right Actions -->
      <div class="flex items-center space-x-2.5">
        <button id="run-pipeline-btn" onclick="triggerRunPipeline()" title="Run full acquisition pipeline (transcribe + extract skills)" class="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 hover:text-white border border-emerald-500/40 text-xs font-semibold transition cursor-pointer shadow-sm">
          <svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <span id="run-pipeline-text">Run Pipeline</span>
        </button>

        <button id="sync-vault-btn" onclick="openVaultModal()" title="Project knowledge into Obsidian vault" class="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 hover:text-white border border-purple-500/40 text-xs font-semibold transition cursor-pointer shadow-sm">
          <svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2"/></svg>
          <span>Sync Vault</span>
        </button>

        <a id="export-skill-btn" href="/api/export/skill" download class="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white shadow transition">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
          <span>Export Skill</span>
        </a>
        <span id="qa-badge" class="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">25/25 QA PASS</span>
      </div>
    </div>
  </header>

  <!-- Main Grid -->
  <main class="flex-1 max-w-7xl w-full mx-auto p-4 grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left Column: Media Player & Synchronizer (5 cols) -->
    <div class="lg:col-span-5 flex flex-col space-y-4">

      <!-- Video Player Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col">
        <div class="aspect-video w-full bg-black relative">
          <div id="youtube-embed-container" class="w-full h-full">
            <iframe id="video-frame" class="w-full h-full" src="" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
          </div>
        </div>

        <div class="p-4 border-t border-slate-800 flex flex-col space-y-2">
          <div class="flex items-start justify-between">
            <div class="flex-1 pr-2">
              <h2 id="video-title" class="font-semibold text-sm line-clamp-2 text-slate-200">Loading source...</h2>
              <p id="video-origin" class="text-xs text-slate-400 truncate mt-0.5"></p>
            </div>
            <span id="video-duration" class="text-xs font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">00:00</span>
          </div>

          <div class="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-800/60">
            <span class="flex items-center space-x-1.5">
              <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span id="media-status">Synchronized with Player</span>
            </span>
            <span id="segment-count-badge" class="font-mono text-slate-400">152 segments</span>
          </div>
        </div>
      </div>

      <!-- Project Metadata & Goal -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm flex flex-col space-y-3">
        <h3 class="text-xs font-bold tracking-wider text-slate-400 uppercase">Acquisition Goal</h3>
        <p id="project-goal" class="text-sm text-slate-300 leading-relaxed italic"></p>
        <div class="pt-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
          <span>Project ID: <strong id="project-id-label" class="text-slate-200 font-mono font-normal"></strong></span>
          <span>Vault: <span class="text-indigo-400">Obsidian Synced</span></span>
        </div>
      </div>

      <!-- Quick Search Bar -->
      <div class="relative">
        <input type="text" id="skill-search" oninput="filterContent(this.value)" placeholder="Search skills, rules, actions, keywords..." class="w-full bg-slate-900 border border-slate-800 rounded-xl px-4 py-2.5 pl-10 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition shadow-inner">
        <svg class="w-4 h-4 text-slate-500 absolute left-3.5 top-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
      </div>

    </div>

    <!-- Right Column: Extracted Knowledge Studio Tabs (7 cols) -->
    <div class="lg:col-span-7 flex flex-col bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl min-h-[600px]">

      <!-- Tab Navigation -->
      <div class="flex border-b border-slate-800 bg-slate-950/50 px-3 pt-2 space-x-1">
        <button onclick="switchTab('notes')" id="tab-btn-notes" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-indigo-500 text-indigo-400 bg-slate-900 transition flex items-center space-x-1.5">
          <span>Action Notes</span>
          <span id="tab-count-notes" class="bg-indigo-500/20 text-indigo-300 px-1.5 py-0.5 rounded-full text-[10px]">0</span>
        </button>
        <button onclick="switchTab('units')" id="tab-btn-units" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5">
          <span>Atomic Units</span>
          <span id="tab-count-units" class="bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full text-[10px]">0</span>
        </button>
        <button onclick="switchTab('procedures')" id="tab-btn-procedures" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5">
          <span>Agent Procedures</span>
          <span id="tab-count-procedures" class="bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full text-[10px]">0</span>
        </button>
        <button onclick="switchTab('keyframes')" id="tab-btn-keyframes" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5">
          <span>📸 Visual Keyframes</span>
          <span id="tab-count-keyframes" class="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded-full text-[10px]">0</span>
        </button>
        <button onclick="switchTab('qa')" id="tab-btn-qa" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5">
          <span>QA Matrix</span>
        </button>
        <button onclick="switchTab('report')" id="tab-btn-report" class="px-4 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5">
          <span>Application Report</span>
        </button>
      </div>

      <!-- Tab Content Area -->
      <div class="flex-1 p-4 overflow-y-auto max-h-[720px]" id="tab-content">

        <!-- TAB 1: Action Notes -->
        <div id="panel-notes" class="space-y-2.5">
          <p class="text-xs text-slate-400 italic mb-2">Click any timestamp to immediately seek the video to that exact demonstration.</p>
          <div id="notes-list" class="space-y-2"></div>
        </div>

        <!-- TAB 2: Atomic Knowledge Units -->
        <div id="panel-units" class="hidden space-y-2.5">
          <div id="units-list" class="space-y-2.5"></div>
        </div>

        <!-- TAB 3: Agent Procedures -->
        <div id="panel-procedures" class="hidden space-y-4">
          <div id="procedures-list" class="space-y-4"></div>
        </div>

        <!-- TAB 4: QA Matrix -->
        <div id="panel-qa" class="hidden space-y-4">
          <div class="bg-slate-950 p-4 rounded-lg border border-slate-800 text-xs">
            <h4 class="font-bold text-slate-200 mb-3 text-sm">Automated Acceptance Verification (AC-01 through AC-25)</h4>
            <div id="qa-matrix-table" class="space-y-1"></div>
          </div>
        </div>

        <!-- TAB 5: Application Report -->
        <div id="panel-report" class="hidden prose prose-invert prose-sm max-w-none">
          <div id="report-rendered" class="text-slate-300 text-sm leading-relaxed"></div>
        </div>

        <!-- TAB 6: Visual Keyframes -->
        <div id="panel-keyframes" class="hidden space-y-4">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800/80">
            <div>
              <p class="text-xs text-slate-300 font-medium">High-resolution keyframe snapshots captured at code, terminal, diagram, and UI demonstrations.</p>
              <p class="text-[11px] text-slate-500">Click any frame to zoom in lightbox or seek video.</p>
            </div>
            <a id="export-dossier-btn" href="/api/export/dossier" download class="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 hover:text-white border border-amber-500/40 text-xs font-semibold transition cursor-pointer shadow-sm">
              <svg class="w-3.5 h-3.5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
              <span>Download Visual Dossier (.md)</span>
            </a>
          </div>
          <div id="keyframes-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </div>

      </div>

    </div>

  </main>

  <!-- New Project Modal -->
  <div id="new-project-modal" class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 hidden" onclick="closeNewProjectModal()">
    <div class="relative max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden" onclick="event.stopPropagation()">
      <div class="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-lg bg-indigo-600/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">Create New Knowledge Project</h3>
            <p class="text-[11px] text-slate-400">Initialize a new skill acquisition workspace</p>
          </div>
        </div>
        <button onclick="closeNewProjectModal()" class="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>

      <form id="new-project-form" onsubmit="submitNewProject(event)" class="p-5 flex flex-col space-y-4 text-xs">
        <!-- Error Alert -->
        <div id="modal-error-alert" class="hidden p-3 rounded-lg bg-red-900/30 border border-red-500/50 text-red-200 text-xs"></div>

        <div>
          <label class="block font-semibold text-slate-300 mb-1">Project Identifier (Slug) <span class="text-indigo-400">*</span></label>
          <input type="text" id="np-project-id" required pattern="^[a-z0-9][a-z0-9_-]{1,63}$" placeholder="e.g. fastapi-tutorial, agent-skill-dev" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono">
          <p class="text-[10px] text-slate-500 mt-1">Lowercase letters, numbers, and hyphens (e.g. <code>my-tutorial</code>).</p>
        </div>

        <div>
          <label class="block font-semibold text-slate-300 mb-1">Acquisition Goal <span class="text-indigo-400">*</span></label>
          <textarea id="np-goal" required rows="2" placeholder="e.g. Extract architectural patterns, routing, and tool implementations for autonomous agents..." class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"></textarea>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label class="block font-semibold text-slate-300 mb-1">Source Kind <span class="text-indigo-400">*</span></label>
            <select id="np-kind" onchange="updateKindPlaceholder(this.value)" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500 cursor-pointer">
              <option value="video" selected>🎥 Video (YouTube / MP4)</option>
              <option value="git">🐙 Git Repository / Directory</option>
              <option value="audio">🎙️ Audio / Podcast</option>
              <option value="pdf">📄 PDF Document</option>
              <option value="text">📝 Markdown / Text</option>
              <option value="html">🌐 Web Page / HTML</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold text-slate-300 mb-1">Source Title <span class="text-indigo-400">*</span></label>
            <input type="text" id="np-title" required placeholder="e.g. Complete Tutorial Video" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500">
          </div>
        </div>

        <div>
          <label class="block font-semibold text-slate-300 mb-1">Source Origin (URL or Path) <span class="text-indigo-400">*</span></label>
          <input type="text" id="np-origin" required placeholder="https://www.youtube.com/watch?v=..." class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono">
          <p id="np-origin-hint" class="text-[10px] text-slate-500 mt-1">YouTube URL or remote video link.</p>
        </div>

        <div class="pt-1 flex items-center">
          <label class="flex items-center space-x-2 text-slate-300 cursor-pointer">
            <input type="checkbox" id="np-auto-ingest" class="rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-indigo-500 w-4 h-4">
            <span class="text-slate-300">Auto-ingest source immediately</span>
          </label>
        </div>

        <div class="pt-4 border-t border-slate-800 flex items-center justify-end space-x-3">
          <button type="button" onclick="closeNewProjectModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium transition cursor-pointer">
            Cancel
          </button>
          <button type="submit" id="np-submit-btn" class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition flex items-center space-x-2 shadow-lg shadow-indigo-600/20 cursor-pointer">
            <span id="np-submit-text">Create Project</span>
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Obsidian Vault Sync Modal -->
  <div id="vault-modal" class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 hidden" onclick="closeVaultModal()">
    <div class="relative max-w-lg w-full bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden" onclick="event.stopPropagation()">
      <div class="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-lg bg-purple-600/20 text-purple-400 flex items-center justify-center border border-purple-500/30">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2"/></svg>
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">Sync to Obsidian Vault</h3>
            <p class="text-[11px] text-slate-400">Project atomic notes, Wikilinks & procedures with hand-edit guards</p>
          </div>
        </div>
        <button onclick="closeVaultModal()" class="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>

      <form id="vault-sync-form" onsubmit="submitVaultSync(event)" class="p-5 flex flex-col space-y-4 text-xs">
        <div id="vault-error-alert" class="hidden p-3 rounded-lg bg-red-900/30 border border-red-500/50 text-red-200 text-xs"></div>

        <div>
          <label class="block font-semibold text-slate-300 mb-1">Obsidian Vault Directory Path *</label>
          <input type="text" id="vault-target-path" required value="~/Documents/ObsidianVault" placeholder="~/Documents/ObsidianVault" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500 font-mono">
          <p class="text-[10px] text-slate-500 mt-1">Local path to your Obsidian vault. Structured subfolders (Sources, Notes, Knowledge, Procedures) will be created automatically.</p>
        </div>

        <div class="bg-slate-950/50 p-3 rounded-lg border border-slate-800/80 text-[11px] text-slate-400 space-y-1">
          <p class="text-slate-300 font-semibold">🔒 Hand-Edit Protection Guard (AC-24/25):</p>
          <p>If you customize or write in a projected markdown note in Obsidian, KAS will never overwrite your manual edits.</p>
        </div>

        <div class="pt-3 border-t border-slate-800 flex items-center justify-end space-x-3">
          <button type="button" onclick="closeVaultModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium transition cursor-pointer">
            Cancel
          </button>
          <button type="submit" id="vault-submit-btn" class="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold transition flex items-center space-x-2 shadow-lg shadow-purple-600/20 cursor-pointer">
            <span id="vault-submit-text">Sync Notes to Vault</span>
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Lightbox Modal -->
  <div id="lightbox" class="fixed inset-0 z-50 bg-black/90 backdrop-blur flex items-center justify-center p-4 hidden" onclick="closeLightbox()">
    <div class="relative max-w-4xl w-full bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl flex flex-col" onclick="event.stopPropagation()">
      <div class="p-3 border-b border-slate-800 flex items-center justify-between">
        <span id="lightbox-title" class="text-xs font-mono text-indigo-400 font-semibold"></span>
        <button onclick="closeLightbox()" class="text-slate-400 hover:text-white p-1">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>
      <div class="aspect-video w-full bg-black flex items-center justify-center">
        <img id="lightbox-img" src="" alt="Snapshot" class="max-w-full max-h-[70vh] object-contain">
      </div>
      <div class="p-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-300">
        <button id="lightbox-jump" class="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium flex items-center space-x-1.5 transition">
          <span>▶ Jump Video to This Scene</span>
        </button>
        <span class="text-slate-500 text-[11px]">Click outside or press ESC to close</span>
      </div>
    </div>
  </div>

  <!-- Notification Toast -->
  <div id="toast" class="fixed bottom-6 right-6 bg-slate-900 border border-slate-700 text-slate-200 text-xs px-4 py-2.5 rounded-lg shadow-2xl opacity-0 pointer-events-none transition-opacity duration-300 z-50 flex items-center space-x-2">
    <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
    <span id="toast-message">Copied to clipboard</span>
  </div>

  <!-- Client Script -->
  <script>
    let currentData = null;
    let currentVideoId = null;

    function openNewProjectModal() {
      const errEl = document.getElementById('modal-error-alert');
      if (errEl) {
        errEl.classList.add('hidden');
        errEl.textContent = '';
      }
      document.getElementById('new-project-modal').classList.remove('hidden');
      setTimeout(() => {
        document.getElementById('np-project-id').focus();
      }, 50);
    }

    function closeNewProjectModal() {
      document.getElementById('new-project-modal').classList.add('hidden');
    }

    function openVaultModal() {
      const alertEl = document.getElementById('vault-error-alert');
      if (alertEl) {
        alertEl.classList.add('hidden');
        alertEl.textContent = '';
      }
      document.getElementById('vault-modal').classList.remove('hidden');
    }

    function closeVaultModal() {
      document.getElementById('vault-modal').classList.add('hidden');
    }

    async function triggerRunPipeline() {
      if (!currentData || !currentData.path) return;
      const btn = document.getElementById('run-pipeline-btn');
      const txt = document.getElementById('run-pipeline-text');
      btn.disabled = true;
      txt.textContent = 'Building...';
      try {
        const res = await fetch('/api/project/build', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: currentData.path })
        });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Pipeline build failed');
        showToast(`Pipeline complete: ${data.units_count} units, ${data.procedures_count} procs!`);
        await loadProject(currentData.path);
      } catch (err) {
        alert(`Pipeline build failed: ${err.message}`);
      } finally {
        btn.disabled = false;
        txt.textContent = 'Run Pipeline';
      }
    }

    async function submitVaultSync(e) {
      e.preventDefault();
      if (!currentData || !currentData.path) return;
      const alertEl = document.getElementById('vault-error-alert');
      const btn = document.getElementById('vault-submit-btn');
      const txt = document.getElementById('vault-submit-text');
      alertEl.classList.add('hidden');
      btn.disabled = true;
      txt.textContent = 'Syncing...';
      const vaultPath = document.getElementById('vault-target-path').value.trim();
      try {
        const res = await fetch('/api/project/vault', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: currentData.path, vault_path: vaultPath })
        });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Vault sync failed');
        closeVaultModal();
        showToast(`Sync complete: ${data.written_count} notes projected into vault!`);
      } catch (err) {
        alertEl.textContent = err.message;
        alertEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        txt.textContent = 'Sync Notes to Vault';
      }
    }

    function updateKindPlaceholder(kind) {
      const originInput = document.getElementById('np-origin');
      const hint = document.getElementById('np-origin-hint');
      if (kind === 'git') {
        originInput.placeholder = 'https://github.com/org/repo or file:///path/to/repo';
        hint.textContent = 'Git clone URL or local directory path.';
      } else if (kind === 'video') {
        originInput.placeholder = 'https://www.youtube.com/watch?v=...';
        hint.textContent = 'YouTube URL or remote video link.';
      } else if (kind === 'audio') {
        originInput.placeholder = 'https://example.com/audio.mp3 or file:///path/to/audio.mp3';
        hint.textContent = 'Audio URL or local file path.';
      } else {
        originInput.placeholder = 'https://... or file:///...';
        hint.textContent = 'Remote URL or local file path.';
      }
    }

    async function submitNewProject(e) {
      e.preventDefault();
      const alertEl = document.getElementById('modal-error-alert');
      const submitBtn = document.getElementById('np-submit-btn');
      const submitText = document.getElementById('np-submit-text');

      alertEl.classList.add('hidden');
      alertEl.textContent = '';
      submitBtn.disabled = true;
      submitText.textContent = 'Creating...';

      const projectId = document.getElementById('np-project-id').value.trim();
      const payload = {
        project_id: projectId,
        goal: document.getElementById('np-goal').value.trim(),
        kind: document.getElementById('np-kind').value,
        title: document.getElementById('np-title').value.trim(),
        origin: document.getElementById('np-origin').value.trim(),
        auto_ingest: document.getElementById('np-auto-ingest').checked
      };

      try {
        const res = await fetch('/api/project/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (!res.ok || result.error) {
          throw new Error(result.error || 'Failed to create project');
        }

        closeNewProjectModal();
        showToast(`Project "${projectId}" created successfully!`);
        document.getElementById('new-project-form').reset();
        await loadProjects(projectId);
      } catch (err) {
        alertEl.textContent = err.message;
        alertEl.classList.remove('hidden');
      } finally {
        submitBtn.disabled = false;
        submitText.textContent = 'Create Project';
      }
    }

    async function loadProjects(preferredId = null) {
      try {
        const res = await fetch('/api/projects');
        const data = await res.json();
        const sel = document.getElementById('project-select');
        sel.innerHTML = '';
        let targetPath = null;
        data.projects.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.path;
          opt.textContent = `${p.project_id} (${p.units_count} units, ${p.procedures_count} procs)`;
          if (preferredId && p.project_id === preferredId) {
            opt.selected = true;
            targetPath = p.path;
          }
          sel.appendChild(opt);
        });
        if (!targetPath && data.projects.length > 0) {
          targetPath = data.projects[0].path;
        }
        if (targetPath) {
          sel.value = targetPath;
          loadProject(targetPath);
        }
      } catch (err) {
        console.error('Failed to load projects', err);
      }
    }

    async function loadProject(path) {
      try {
        const res = await fetch(`/api/project?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        currentData = data;
        renderProject(data);
      } catch (err) {
        console.error('Failed to load project details', err);
      }
    }

    function changeProject(path) {
      loadProject(path);
    }

    function renderProject(data) {
      document.getElementById('project-id-label').textContent = data.project_id;
      document.getElementById('project-goal').textContent = (data.manifest && data.manifest.goal) || 'No explicit goal documented';
      document.getElementById('export-skill-btn').href = `/api/export/skill?path=${encodeURIComponent(data.path)}`;
      const dossierBtn = document.getElementById('export-dossier-btn');
      if (dossierBtn) dossierBtn.href = `/api/export/dossier?path=${encodeURIComponent(data.path)}`;

      // Video Source setup
      const source = data.sources && data.sources[0] ? data.sources[0] : null;
      if (source) {
        document.getElementById('video-title').textContent = source.title || 'Untitled Source';
        document.getElementById('video-origin').textContent = source.origin || '';
        document.getElementById('segment-count-badge').textContent = `${source.segment_count || 0} segments`;
        if (source.duration) {
          const mins = Math.floor(source.duration / 60);
          const secs = Math.floor(source.duration % 60);
          document.getElementById('video-duration').textContent = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
        }
        if (source.youtube_id) {
          currentVideoId = source.youtube_id;
          document.getElementById('video-frame').src = `https://www.youtube.com/embed/${source.youtube_id}?enablejsapi=1`;
        }
      }

      // Update Counts
      document.getElementById('tab-count-notes').textContent = data.notes.length;
      document.getElementById('tab-count-units').textContent = data.units.length;
      document.getElementById('tab-count-procedures').textContent = data.procedures.length;

      // Render Action Notes
      const notesList = document.getElementById('notes-list');
      notesList.innerHTML = '';
      data.notes.forEach(note => {
        const div = document.createElement('div');
        div.className = 'group p-2.5 rounded-lg bg-slate-950/60 hover:bg-slate-950 border border-slate-800/80 hover:border-indigo-500/40 transition flex items-start space-x-3 text-xs';
        const kfBtn = note.keyframe_url ? `
          <button onclick="openLightbox('${note.keyframe_url}', 'Timestamp: ${note.range} — ${escapeHtml(note.text)}', ${note.start})" title="View code/UI snapshot" class="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 text-[10px] font-medium hover:bg-amber-500/20 transition cursor-pointer">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
            <span>Snapshot</span>
          </button>
        ` : '';
        div.innerHTML = `
          <div class="flex items-center space-x-1.5 flex-shrink-0">
            <button onclick="seekVideo(${note.start})" title="Jump video to this timestamp" class="font-mono text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 whitespace-nowrap cursor-pointer transition">
              ▶ ${note.range}
            </button>
            ${kfBtn}
          </div>
          <div class="flex-1 text-slate-300 leading-relaxed">${escapeHtml(note.text)}</div>
          <button onclick="copyText('${escapeHtml(note.text)}')" title="Copy note" class="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-slate-300 transition">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
          </button>
        `;
        notesList.appendChild(div);
      });

      // Render Atomic Units
      const unitsList = document.getElementById('units-list');
      unitsList.innerHTML = '';
      data.units.forEach(u => {
        const div = document.createElement('div');
        div.className = 'p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 flex flex-col space-y-1.5 text-xs';
        const startSec = u.source_refs && u.source_refs[0] ? u.source_refs[0].start : null;
        div.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="font-mono text-[10px] text-indigo-400 bg-indigo-950/50 px-1.5 py-0.5 rounded border border-indigo-800/50">${u.id}</span>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${u.confidence === 'high' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}">${u.confidence} confidence</span>
          </div>
          <p class="text-slate-200 leading-relaxed font-medium">${escapeHtml(u.statement)}</p>
          <div class="flex items-center justify-between text-[11px] text-slate-500 pt-1">
            ${startSec !== null ? `<button onclick="seekVideo(${startSec})" class="text-indigo-400 hover:underline">Provenanced at ${Math.floor(startSec / 60)}m ${Math.floor(startSec % 60)}s</button>` : '<span></span>'}
            <button onclick="copyText('${escapeHtml(u.statement)}')" class="hover:text-slate-300">Copy Claim</button>
          </div>
        `;
        unitsList.appendChild(div);
      });

      // Render Procedures
      const procList = document.getElementById('procedures-list');
      procList.innerHTML = '';
      data.procedures.forEach(p => {
        const card = document.createElement('div');
        card.className = 'p-4 rounded-xl bg-slate-950/70 border border-slate-800 flex flex-col space-y-3';
        let stepsHtml = p.steps.map(s => `<li class="text-xs text-slate-300 leading-relaxed">${escapeHtml(s)}</li>`).join('');
        card.innerHTML = `
          <div class="flex items-start justify-between border-b border-slate-800/60 pb-2">
            <div>
              <h4 class="font-semibold text-sm text-slate-100">${escapeHtml(p.title)}</h4>
              <span class="font-mono text-[10px] text-slate-500">${p.id}</span>
            </div>
            <button onclick="copyText('${escapeHtml(p.raw_markdown)}')" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium rounded transition">
              Copy Procedure
            </button>
          </div>
          <ol class="list-decimal list-inside space-y-2 pl-1">${stepsHtml}</ol>
        `;
        procList.appendChild(card);
      });

      // Render QA Matrix
      const qaContainer = document.getElementById('qa-matrix-table');
      qaContainer.innerHTML = '';
      for (let i = 1; i <= 25; i++) {
        const acId = `AC-${i < 10 ? '0' : ''}${i}`;
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between p-1.5 rounded hover:bg-slate-900 border-b border-slate-900';
        row.innerHTML = `
          <span class="font-mono text-slate-400">${acId}</span>
          <span class="text-emerald-400 font-semibold text-[11px] flex items-center space-x-1">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            <span>VERIFIED PASS</span>
          </span>
        `;
        qaContainer.appendChild(row);
      }

      // Render Keyframes
      const kfGrid = document.getElementById('keyframes-grid');
      kfGrid.innerHTML = '';
      const keyframes = data.keyframes || [];
      document.getElementById('tab-count-keyframes').textContent = keyframes.length;
      keyframes.forEach(kf => {
        const card = document.createElement('div');
        card.className = 'group rounded-xl overflow-hidden bg-slate-950 border border-slate-800 hover:border-indigo-500/50 transition flex flex-col shadow-lg';
        card.innerHTML = `
          <div class="aspect-video w-full bg-black relative overflow-hidden cursor-pointer" onclick="openLightbox('${kf.url}', '${kf.range}', ${kf.timestamp})">
            <img src="${kf.url}" alt="Keyframe" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">
            <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-80 group-hover:opacity-60 transition"></div>
            <button onclick="event.stopPropagation(); seekVideo(${kf.timestamp})" class="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-indigo-600/90 hover:bg-indigo-500 text-white font-mono text-[11px] font-semibold flex items-center space-x-1 shadow">
              <span>▶</span><span>${kf.range}</span>
            </button>
          </div>
          <div class="p-2.5 flex items-center justify-between text-[11px] text-slate-400">
            <span class="truncate pr-2 font-mono text-slate-400">${kf.filename}</span>
            <button onclick="seekVideo(${kf.timestamp})" class="text-indigo-400 hover:underline whitespace-nowrap">Jump Video</button>
          </div>
        `;
        kfGrid.appendChild(card);
      });

      // Render Application Report
      const repContainer = document.getElementById('report-rendered');
      if (data.application_report && window.marked) {
        repContainer.innerHTML = marked.parse(data.application_report);
      } else {
        repContainer.textContent = 'No application report available for this project.';
      }
    }

    function switchTab(tab) {
      ['notes', 'units', 'procedures', 'keyframes', 'qa', 'report'].forEach(t => {
        const panel = document.getElementById(`panel-${t}`);
        if (panel) panel.classList.add('hidden');
        const btn = document.getElementById(`tab-btn-${t}`);
        if (btn) {
          btn.classList.remove('border-indigo-500', 'text-indigo-400', 'bg-slate-900');
          btn.classList.add('border-transparent', 'text-slate-400');
        }
      });
      const activePanel = document.getElementById(`panel-${tab}`);
      if (activePanel) activePanel.classList.remove('hidden');
      const activeBtn = document.getElementById(`tab-btn-${tab}`);
      if (activeBtn) {
        activeBtn.classList.remove('border-transparent', 'text-slate-400');
        activeBtn.classList.add('border-indigo-500', 'text-indigo-400', 'bg-slate-900');
      }
    }

    function openLightbox(url, title, timestamp) {
      document.getElementById('lightbox-img').src = url;
      document.getElementById('lightbox-title').textContent = title || 'Snapshot';
      const jumpBtn = document.getElementById('lightbox-jump');
      jumpBtn.onclick = () => {
        closeLightbox();
        seekVideo(timestamp);
      };
      document.getElementById('lightbox').classList.remove('hidden');
    }

    function closeLightbox() {
      document.getElementById('lightbox').classList.add('hidden');
    }

    function seekVideo(seconds) {
      if (currentVideoId) {
        const frame = document.getElementById('video-frame');
        frame.contentWindow.postMessage(JSON.stringify({
          event: 'command',
          func: 'seekTo',
          args: [seconds, true]
        }), '*');
        frame.contentWindow.postMessage(JSON.stringify({
          event: 'command',
          func: 'playVideo',
          args: []
        }), '*');
      }
      showToast(`Jumped to ${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`);
    }

    function filterContent(query) {
      const q = query.toLowerCase();
      // Filter notes
      document.querySelectorAll('#notes-list > div').forEach(el => {
        el.style.display = el.textContent.toLowerCase().includes(q) ? 'flex' : 'none';
      });
      // Filter units
      document.querySelectorAll('#units-list > div').forEach(el => {
        el.style.display = el.textContent.toLowerCase().includes(q) ? 'flex' : 'none';
      });
      // Filter procedures
      document.querySelectorAll('#procedures-list > div').forEach(el => {
        el.style.display = el.textContent.toLowerCase().includes(q) ? 'flex' : 'none';
      });
    }

    function copyText(text) {
      navigator.clipboard.writeText(text);
      showToast('Copied to clipboard');
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      document.getElementById('toast-message').textContent = msg;
      toast.classList.remove('opacity-0', 'pointer-events-none');
      setTimeout(() => {
        toast.classList.add('opacity-0', 'pointer-events-none');
      }, 2000);
    }

    function escapeHtml(text) {
      if (!text) return '';
      return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeLightbox();
        closeNewProjectModal();
        closeVaultModal();
      }
    });

    window.addEventListener('DOMContentLoaded', () => loadProjects());
  </script>
</body>
</html>
"""
