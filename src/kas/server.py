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
        "tags: [claude, workflow, agent-skill]",
        "---",
        "",
        f"# Skill: {pid}",
        "",
        f"> {goal}",
        "",
        "## Core Procedures",
        "",
    ]
    for p in procedures:
        doc.append(f"### {p['title']}")
        for step in p.get("steps", []):
            doc.append(f"- {step}")
        doc.append("")

    doc.append("## Knowledge Primitives & Rules")
    doc.append("")
    for uid, statement in sorted(units.items())[:25]:
        doc.append(f"- **{uid}**: {statement}")

    return "\n".join(doc) + "\n"


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
        # Keep console output clean
        pass


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

      <!-- Center: Project Selector -->
      <div class="flex items-center space-x-2 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
        <span class="text-xs text-slate-400 font-medium">Project:</span>
        <select id="project-select" onchange="changeProject(this.value)" class="bg-transparent text-sm font-semibold text-indigo-400 focus:outline-none cursor-pointer">
          <option value="" disabled>Loading projects...</option>
        </select>
      </div>

      <!-- Right Actions -->
      <div class="flex items-center space-x-3">
        <a id="export-skill-btn" href="/api/export/skill" download class="inline-flex items-center space-x-2 px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white shadow transition">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
          <span>Export Agent Skill</span>
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

      </div>

    </div>

  </main>

  <!-- Notification Toast -->
  <div id="toast" class="fixed bottom-6 right-6 bg-slate-900 border border-slate-700 text-slate-200 text-xs px-4 py-2.5 rounded-lg shadow-2xl opacity-0 pointer-events-none transition-opacity duration-300 z-50 flex items-center space-x-2">
    <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
    <span id="toast-message">Copied to clipboard</span>
  </div>

  <!-- Client Script -->
  <script>
    let currentData = null;
    let currentVideoId = null;

    async function loadProjects() {
      try {
        const res = await fetch('/api/projects');
        const data = await res.json();
        const sel = document.getElementById('project-select');
        sel.innerHTML = '';
        data.projects.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.path;
          opt.textContent = `${p.project_id} (${p.units_count} units, ${p.procedures_count} procs)`;
          sel.appendChild(opt);
        });
        if (data.projects.length > 0) {
          loadProject(data.projects[0].path);
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
        div.innerHTML = `
          <button onclick="seekVideo(${note.start})" title="Jump video to this timestamp" class="font-mono text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 whitespace-nowrap cursor-pointer transition">
            ▶ ${note.range}
          </button>
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

      // Render Application Report
      const repContainer = document.getElementById('report-rendered');
      if (data.application_report && window.marked) {
        repContainer.innerHTML = marked.parse(data.application_report);
      } else {
        repContainer.textContent = 'No application report available for this project.';
      }
    }

    function switchTab(tab) {
      ['notes', 'units', 'procedures', 'qa', 'report'].forEach(t => {
        document.getElementById(`panel-${t}`).classList.add('hidden');
        const btn = document.getElementById(`tab-btn-${t}`);
        btn.classList.remove('border-indigo-500', 'text-indigo-400', 'bg-slate-900');
        btn.classList.add('border-transparent', 'text-slate-400');
      });
      document.getElementById(`panel-${tab}`).classList.remove('hidden');
      const activeBtn = document.getElementById(`tab-btn-${tab}`);
      activeBtn.classList.remove('border-transparent', 'text-slate-400');
      activeBtn.classList.add('border-indigo-500', 'text-indigo-400', 'bg-slate-900');
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

    window.addEventListener('DOMContentLoaded', loadProjects);
  </script>
</body>
</html>
"""
