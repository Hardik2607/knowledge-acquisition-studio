# Phase 1 — Foundation (implemented)

- **Status:** complete
- **Date:** 2026-11-02
- **Exit criteria:** AC-01, AC-14, AC-19 pass

## What exists now

```text
knowledge-acquisition-studio/
├── pyproject.toml            # package `kas`, console script `kas`
├── config/default.yaml       # strict schema, providers pinned (ADR-005)
├── examples/example-manifest.yaml
├── src/kas/
│   ├── errors.py             # FieldError / ValidationError — dotted paths
│   ├── manifest.py           # manifest schema + loader (AC-01, AC-19)
│   ├── config.py             # config schema, defaults, secret-name enforcement (AC-19)
│   ├── status.py             # status.json + docs/status/status.md (AC-14)
│   ├── cli.py                # validate | status | run | init
│   └── __main__.py
└── tests/                    # 38 tests, pytest
```

## Commands

```bash
.venv/bin/kas validate --project projects/<id>      # schema check, exit 2 on problems
.venv/bin/kas status   --project projects/<id>       # print + verify md/json agreement
.venv/bin/kas status   --project projects/<id> --write
.venv/bin/kas run      --project projects/<id>       # validate, prepare, report plan
.venv/bin/kas run      --project projects/<id> --dry-run
.venv/bin/kas init     --project <dir> --name <slug>
```

Exit codes: `0` ok, `2` validation error, `3` environment/IO error.

## Design decisions realised

| Decision | Where |
|---|---|
| Unknown keys are errors (D6) | `manifest._validate_source`, `config._walk` |
| Secrets by env-var name only (D15) | `config._is_secret_like`, `ENV_NAME` |
| Verification model ≠ extraction model (D11) | `config.load_config` distinct-model check |
| Content-addressed ids (D3) | reserved for Phase 2 (`src-<sha256[0:12]>`, `k-<sha256[0:12]>`) |
| Status is dual-form and must agree (D5, AC-14) | `status.StatusRecord`, `is_consistent` |
| No writes on invalid input (AC-01) | `cli.cmd_run` validates before `_prepare` |

## Evidence (run on the host, 2026-11-02)

```text
$ .venv/bin/python -m pytest -q
......................................                                   [100%]
38 passed

$ .venv/bin/kas validate --project /tmp --manifest /tmp/bad-manifest.yaml
error: invalid manifest: 2 problem(s)
  - goal: expected string, got missing
  - sources: expected list, got missing
exit=2                     # and no artifact directories were created

$ .venv/bin/kas validate --project projects/demo-reels --config /tmp/bad-config.yaml
error: invalid config: 1 problem(s)
  - orchestrator.max_retry: expected a known configuration key, got unknown key 'max_retry'
exit=2

$ .venv/bin/kas run --project projects/demo-reels
project:  reels-notes-demo
sources:  2
extract:  llm7/DeepSeek-V4-Flash-0731
verify:   llm7/GLM-5.3-Flash
transcribe: llm7/Voxtral-Small-24B-2507
exit=0                     # status.json + docs/status/status.md written, consistent

$ .venv/bin/kas status --project projects/demo-reels   # exit 0 = files agree
```

## Deliberate limits

- **No pipeline.** `run` validates, prepares directories and writes status. It does not
  ingest, transcribe or extract. Claiming otherwise would violate the verification gate.
- **No network calls.** No provider is contacted in Phase 1. Model ids are configuration,
  not proof: Phase 2 must validate them against `/v1/models` (ADR-005 D14).
- **No id hashing yet.** Content-addressing lands with ingestion, where it can be tested
  against real bytes.
- **Credentials are not loaded.** `validate` only warns about missing environment
  variables by name; it never reads or prints a value.

## Next

Phase 2, in order:

1. `youtube` adapter: `yt-dlp` → `sources/<id>/raw/` + Source Record (AC-03, AC-04).
2. Transcript: Voxtral via LLM7, Groq Whisper fallback, normalized segments (AC-05).
3. Notes with timestamp provenance (AC-06).
4. `reels` adapter behind cookies (quarantine on `auth_expired`).
