"""Command line interface.

Exit codes:
    0  success
    1  pipeline completed with failed/quarantined sources
    2  validation error (manifest or config)
    3  environment / IO error

`run` and `build` are the same operation. `ingest` stops after the raw bytes and Source
Records are written, which is useful when debugging an adapter before spending tokens.

On invalid input nothing is created: manifest and config validation both happen before
the first `mkdir` (AC-01).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .adapters import default_registry
from .config import Config, load_config
from .errors import ValidationError
from .ingest import IngestSummary, ingest as run_ingest, load_source_records
from .manifest import Manifest, load_manifest
from .models import Evidence
from .pipeline import PHASE3, build as run_build, now_iso, verify_source_records
from .status import StatusRecord, is_consistent, now_iso as status_now

EXIT_OK = 0
EXIT_PIPELINE = 1
EXIT_VALIDATION = 2
EXIT_ENV = 3

PHASE1 = "Phase 1 — Foundation implemented (manifest, config, status, CLI)"

ARTIFACT_DIRS = ("sources", "notes", "knowledge", "derived", "application", "evidence", "reports")


# --------------------------------------------------------------------------- helpers


def _project_config(project_dir: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    for candidate in (
        project_dir / "config" / "kas.yaml",
        project_dir / "config" / "default.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _manifest_path(project_dir: Path, explicit: Path | None) -> Path:
    return explicit if explicit is not None else project_dir / "manifest.yaml"


def _load(project_dir: Path, manifest_file: Path | None, config_file: Path | None) -> tuple[Manifest, Config]:
    manifest = load_manifest(_manifest_path(project_dir, manifest_file))
    config_path = _project_config(project_dir, config_file)
    config = load_config(config_path) if config_path else load_config(None)
    return manifest, config


def _fail(exc: ValidationError) -> int:
    print(f"error: {exc.render()}", file=sys.stderr)
    return EXIT_VALIDATION


def _report_env(config: Config) -> list[str]:
    """Names of missing provider credentials. Values are never printed."""
    return sorted(
        {
            provider.api_key_env
            for provider in config.providers.values()
            if provider.name not in ("local", "ollama")
            and provider.api_key_env not in ("NONE", "")
            and not os.environ.get(provider.api_key_env)
        }
    )


def _initial_status(manifest: Manifest, config: Config) -> StatusRecord:
    kinds = sorted({source.kind for source in manifest.sources})
    return StatusRecord(
        project_id=manifest.project_id,
        phase=PHASE1,
        completed=[
            f"Manifest validated: {len(manifest.sources)} source(s), kinds: {', '.join(kinds)}",
            "Configuration validated (strict keys, env-name-only secrets)",
            "Status contract written to status.json and docs/status/status.md",
            "Phase 0 frozen: requirements v2.1, acceptance criteria AC-01…AC-25",
        ],
        evidence=[
            f"manifest: {manifest.path}",
            f"config: {config.path or 'built-in defaults'}",
            "pytest: tests/test_manifest.py, tests/test_config.py, tests/test_status.py, tests/test_cli.py",
        ],
        decisions=[
            "ADR-004 — requirements freeze, content-addressed ids, verification gate",
            "ADR-005 — LLM7 primary, Unorouter failover, Groq Whisper fallback",
            "ADR-006 — Obsidian projection, publishable content, daemon, cookies",
        ],
        risks=["Pipeline not run yet in this project"],
        remaining=["Phase 2 — ingest, transcribe, notes"],
        next_task="kas build",
        updated_at=status_now(),
    )


def _prepare(project_dir: Path, manifest: Manifest, config: Config) -> StatusRecord:
    for name in ARTIFACT_DIRS:
        (project_dir / name).mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "status").mkdir(parents=True, exist_ok=True)
    record = _initial_status(manifest, config)
    record.write(project_dir, write_markdown=bool(config.get("status.write_markdown", True)))
    return record


def _print_plan(manifest: Manifest, config: Config) -> None:
    print(f"project:  {manifest.project_id}")
    print(f"goal:     {manifest.goal}")
    print(f"sources:  {len(manifest.sources)}")
    for index, source in enumerate(manifest.sources):
        print(f"  [{index}] {source.kind:5} {source.title}  <- {source.origin}")
    print(f"extract:  {config.providers['extract'].name}/{config.providers['extract'].model}")
    print(f"transcribe: {config.providers['transcribe'].name}/{config.providers['transcribe'].model}")
    print(f"vault:    {config.get('paths.vault')}")


def _print_ingest(summary: IngestSummary, project_dir: Path) -> None:
    print(f"ingested: {len(summary.records)} source record(s)")
    print(f"reused:   {len(summary.skipped)} unchanged")
    print(f"failed:   {len(summary.failed)}")
    for record in summary.failed:
        print(f"  ✗ {record.origin} — {record.reason}", file=sys.stderr)
    for record in summary.records:
        print(f"  ✓ {record.source_id}  {record.raw_path}")


def _write_ingest_evidence(project_dir: Path, summary: IngestSummary, command: str) -> Path:
    records = load_source_records(project_dir)
    problems = verify_source_records(project_dir, records)
    problems += [f"{record.origin}: {record.reason}" for record in summary.failed]
    evidence = Evidence(
        task_id="t-ingest",
        criteria=["AC-02", "AC-03", "AC-04"],
        result="pass" if not problems else "fail",
        artifacts=[f"sources/{sid}/source.json" for sid in sorted(records)],
        command=command,
        run_at=now_iso(),
        notes="; ".join(problems) or "Source Records written; checksums recomputed from raw bytes.",
    )
    return evidence.write(project_dir)


# --------------------------------------------------------------------------- commands


def cmd_validate(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    print(f"manifest ok: {manifest.project_id} ({len(manifest.sources)} sources)")
    for index, source in enumerate(manifest.sources):
        print(f"  [{index}] {source.kind:5} {source.title}  <- {source.origin}")
    print(
        f"config ok:   extract={config.providers['extract'].model} "
        f"verify={config.providers['verify'].model} "
        f"transcribe={config.providers['transcribe'].model}"
    )

    missing = _report_env(config)
    if missing:
        print(f"warning: missing credentials in environment: {', '.join(missing)}", file=sys.stderr)
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    if args.write:
        json_path = project_dir / "status.json"
        if json_path.is_file():
            record = StatusRecord.read(project_dir)
            config = None
            try:
                manifest, config = _load(project_dir, args.manifest, args.config)
            except ValidationError:
                pass
            write_markdown = bool(config.get("status.write_markdown", True)) if config else True
            record.write(project_dir, write_markdown=write_markdown)
        else:
            try:
                manifest, config = _load(project_dir, args.manifest, args.config)
            except ValidationError as exc:
                return _fail(exc)
            _prepare(project_dir, manifest, config)
        print(f"wrote {project_dir / 'status.json'}")
        print(f"wrote {project_dir / 'docs/status/status.md'}")
        return EXIT_OK

    json_path = project_dir / "status.json"
    if not json_path.is_file():
        print(f"error: {json_path} not found (run `kas status --write` first)", file=sys.stderr)
        return EXIT_ENV
    record = StatusRecord.read(project_dir)
    print(record.to_markdown())
    if not is_consistent(project_dir):
        print("error: docs/status/status.md is out of sync with status.json", file=sys.stderr)
        return EXIT_VALIDATION
    return EXIT_OK


def cmd_ingest(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    if args.dry_run:
        _print_plan(manifest, config)
        print("\ndry run: nothing written")
        return EXIT_OK

    _prepare(project_dir, manifest, config)
    summary = run_ingest(manifest, project_dir, config, default_registry())
    _print_ingest(summary, project_dir)

    evidence = _write_ingest_evidence(project_dir, summary, f"kas ingest --project {project_dir}")
    record = StatusRecord(
        project_id=manifest.project_id,
        phase="Phase 2 — ingestion only",
        completed=[
            f"Ingested {len(summary.records)} source(s); {len(summary.skipped)} reused unchanged",
            "Source Records written with content-addressed ids",
        ],
        evidence=[str(evidence.relative_to(project_dir))],
        risks=[f"{record.origin}: {record.reason}" for record in summary.failed]
        or ["Transcription and notes not run"],
        remaining=["kas build — transcribe and generate notes"],
        next_task="kas build",
        updated_at=status_now(),
    )
    record.write(project_dir, write_markdown=bool(config.get("status.write_markdown", True)))
    return EXIT_OK if summary.ok else EXIT_PIPELINE


def cmd_build(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    if args.dry_run:
        _print_plan(manifest, config)
        print("\ndry run: nothing written")
        return EXIT_OK

    _prepare(project_dir, manifest, config)
    result = run_build(manifest, project_dir, config, registry=default_registry())

    _print_ingest(result.ingested, project_dir)
    print(f"transcripts: {len(result.transcripts)}")
    print(f"notes:       {len(result.notebooks)}")
    print(f"evidence:    {', '.join(str(p.name) for p in result.evidence)}")
    for failure in result.failures:
        print(f"  ✗ {failure}", file=sys.stderr)

    if result.ok:
        if getattr(args, "all", False):
            vault_path = Path(config.get("paths.vault")).expanduser().resolve()
            from .vault import load_and_project

            written, conflicts = load_and_project(project_dir, vault_path)
            print(f"vault:       projected {len(written)} note(s) into {vault_path}")
            if conflicts:
                for conflict in conflicts:
                    print(f"  hand-edited: {conflict}", file=sys.stderr)

            from .qa import run_phase5

            res5 = run_phase5(project_dir, manifest)
            print(f"derived:     {len(res5['derived'])} note(s)")
            print(f"application: {res5['application']}")
            print(f"qa report:   {res5['qa']}")

            from .pipeline import PHASE5, update_status_complete

            update_status_complete(project_dir, manifest, config)
            print(f"\nall phases complete: {PHASE5}")
            return EXIT_OK if not conflicts else EXIT_PIPELINE

        print(f"\nphase 3 complete: {PHASE3}")
        return EXIT_OK
    print("\nphase 2 incomplete: see failures above", file=sys.stderr)
    return EXIT_PIPELINE


def cmd_vault(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    vault_path = Path(args.vault).expanduser().resolve() if args.vault else Path(config.get("paths.vault")).expanduser().resolve()
    from .vault import load_and_project

    written, conflicts = load_and_project(project_dir, vault_path)
    print(f"projected {len(written)} notes into {vault_path}")
    for conflict in conflicts:
        print(f"  hand-edited (not overwritten): {conflict}", file=sys.stderr)

    if (project_dir / "status.json").is_file():
        record = StatusRecord.read(project_dir)
        if "Phase 4 — Vault projected with frontmatter and hand-edit guards" not in record.completed:
            record.completed.append("Phase 4 — Vault projected with frontmatter and hand-edit guards")
        if "evidence/t-vault.json" not in record.evidence and (project_dir / "evidence" / "t-vault.json").is_file():
            record.evidence.append("evidence/t-vault.json")
        if record.phase.startswith("Phase 3"):
            record.phase = "Phase 4 — vault projection and daemon trigger"
        record.updated_at = status_now()
        record.write(project_dir, write_markdown=bool(config.get("status.write_markdown", True)))

    return EXIT_OK if not conflicts else EXIT_PIPELINE


def cmd_qa(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    from .qa import run_phase5

    result = run_phase5(project_dir, manifest)
    print(f"derived: {len(result['derived'])} note(s)")
    print(f"application: {result['application']}")
    print(f"qa report: {result['qa']}")

    if (project_dir / "status.json").is_file():
        from .pipeline import update_status_complete

        update_status_complete(project_dir, manifest, config)

    return EXIT_OK


def _find_kas_cmd(project_dir: Path) -> list[str]:
    kas_bin = shutil.which("kas")
    if kas_bin and Path(kas_bin).is_file():
        return [kas_bin]
    local_venv = project_dir.parent.parent / ".venv" / "bin" / "kas"
    if local_venv.is_file():
        return [str(local_venv)]
    py_kas = Path(sys.executable).parent / "kas"
    if py_kas.is_file():
        return [str(py_kas)]
    return [sys.executable, "-m", "kas.cli"]


def cmd_daemon(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    try:
        manifest, config = _load(project_dir, args.manifest, args.config)
    except ValidationError as exc:
        return _fail(exc)

    if args.install:
        unit_dir = Path("~/.config/systemd/user").expanduser()
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path = unit_dir / "kas-daemon.service"
        kas_cmd = _find_kas_cmd(project_dir)
        exec_start = f"{' '.join(kas_cmd)} daemon --project {project_dir}"
        unit_path.write_text(
            "[Unit]\n"
            "Description=Knowledge Acquisition Studio daemon\n"
            "After=default.target\n\n"
            "[Service]\n"
            f"ExecStart={exec_start}\n"
            "Restart=on-failure\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
            encoding="utf-8",
        )
        print(f"wrote {unit_path}")
        print("run: systemctl --user daemon-reload && systemctl --user enable --now kas-daemon")
        return EXIT_OK

    import time

    inbox = (project_dir / config.get("daemon.inbox", "runtime/inbox")).resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    done_dir = project_dir / "runtime" / "done"
    failed_dir = project_dir / "runtime" / "failed"
    done_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    poll = int(config.get("daemon.poll_seconds", 5))

    print(f"daemon watching {inbox} (poll {poll}s). Ctrl-C to stop.")
    try:
        while True:
            for manifest_path in sorted(inbox.glob("*.yaml")) + sorted(inbox.glob("*.yml")):
                target = project_dir / "runtime" / "queue" / manifest_path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.replace(target)
                print(f"processing {target.name}")
                try:
                    import subprocess
                    from .manifest import load_manifest

                    job_manifest = load_manifest(target)
                    if job_manifest.project_id != manifest.project_id:
                        job_project_dir = project_dir / "runtime" / "runs" / job_manifest.project_id
                        job_project_dir.mkdir(parents=True, exist_ok=True)
                    else:
                        job_project_dir = project_dir

                    kas_cmd = _find_kas_cmd(project_dir)
                    subprocess.run(
                        [*kas_cmd, "build", "--project", str(job_project_dir), "--manifest", str(target), "--all"],
                        check=True,
                    )
                    target.replace(done_dir / target.name)
                except Exception as exc:  # noqa: BLE001
                    print(f"failed {target.name}: {exc}", file=sys.stderr)
                    target.replace(failed_dir / target.name)
            time.sleep(poll)
    except KeyboardInterrupt:
        print("daemon stopped")
        return EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).expanduser().resolve()
    if project_dir.exists() and any(project_dir.iterdir()) and not args.force:
        print(f"error: {project_dir} is not empty (use --force)", file=sys.stderr)
        return EXIT_ENV
    for name in ("docs/status", "docs/requirements", "config", *ARTIFACT_DIRS):
        (project_dir / name).mkdir(parents=True, exist_ok=True)
    manifest = project_dir / "manifest.yaml"
    if not manifest.exists():
        manifest.write_text(
            "\n".join(
                [
                    f"project_id: {args.name}",
                    "goal: describe the outcome this project must produce",
                    "sources:",
                    "  - kind: video",
                    "    origin: https://www.youtube.com/watch?v=CHANGE_ME",
                    "    title: Replace with the real title",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    print(f"created {project_dir}")
    print(f"created {manifest}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import run_server

    workspace_root = Path.cwd().resolve()
    default_proj = Path(args.project).resolve() if args.project else None
    run_server(
        workspace_root=workspace_root,
        default_project=default_proj,
        host=args.host,
        port=args.port,
    )
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kas", description="Knowledge Acquisition Studio")
    parser.add_argument("--version", action="version", version=f"kas {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", required=True, help="project directory")
        p.add_argument("--manifest", type=Path, default=None, help="manifest path (default: <project>/manifest.yaml)")
        p.add_argument("--config", type=Path, default=None, help="config path (default: <project>/config/kas.yaml)")

    p_validate = sub.add_parser("validate", help="validate manifest and config")
    common(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    p_status = sub.add_parser("status", help="show or write status")
    common(p_status)
    p_status.add_argument("--write", action="store_true", help="write status.json and status.md")
    p_status.set_defaults(func=cmd_status)

    p_ingest = sub.add_parser("ingest", help="fetch sources and write Source Records")
    common(p_ingest)
    p_ingest.add_argument("--dry-run", action="store_true", help="do not write anything")
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build", help="ingest, transcribe and generate notes")
    common(p_build)
    p_build.add_argument("--dry-run", action="store_true", help="do not write anything")
    p_build.add_argument("--all", action="store_true", help="run full pipeline through vault and qa")
    p_build.set_defaults(func=cmd_build)

    p_run = sub.add_parser("run", help="alias for build")
    common(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="do not write anything")
    p_run.add_argument("--all", action="store_true", help="run full pipeline through vault and qa")
    p_run.set_defaults(func=cmd_build)

    p_vault = sub.add_parser("vault", help="project canonical artifacts into the Obsidian vault")
    common(p_vault)
    p_vault.add_argument("--vault", default=None, help="vault path (default: config paths.vault)")
    p_vault.set_defaults(func=cmd_vault)

    p_qa = sub.add_parser("qa", help="generate derived content, application report and QA report")
    common(p_qa)
    p_qa.set_defaults(func=cmd_qa)

    p_daemon = sub.add_parser("daemon", help="watch runtime/inbox and run builds (ADR-006 D18)")
    common(p_daemon)
    p_daemon.add_argument("--install", action="store_true", help="write a systemd --user unit instead of running")
    p_daemon.set_defaults(func=cmd_daemon)

    p_init = sub.add_parser("init", help="create a project skeleton")
    p_init.add_argument("--project", required=True)
    p_init.add_argument("--name", required=True)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="launch local interactive web studio and agent skill server")
    p_serve.add_argument("--project", default="projects/claude-tutorial", help="default project directory to display")
    p_serve.add_argument("--host", default="127.0.0.1", help="host address (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8765, help="port to bind (default: 8765)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValidationError as exc:
        return _fail(exc)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENV


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
