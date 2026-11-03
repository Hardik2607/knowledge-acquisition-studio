# Phase 3 — Knowledge, procedures, source map, verification, retry, offline

- **Status:** complete
- **Date:** 2026-11-03
- **Exit criteria:** AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-15, AC-16, AC-17 pass
- **Tests:** 73 passed (`pytest -q`)

## What exists now

Added to `src/kas/`:

- `knowledge.py` — `build_units`, `build_procedures_stage`, `build_source_map`, `validate_knowledge` (AC-07…AC-09, AC-15).
- `verify.py` — `check_evidence`, `gate`, `VerificationError` (AC-10).
- `retry.py` — `run_with_retry`, `RetryResult`, `Attempt` (AC-11).
- Offline guards in `http.py`, `adapters/video.py`, `extract.ChatClient`, `transcribe.transcribe_source` (AC-16, AC-17).

## Commands

Same as Phase 2; `kas build` now also writes:

- `knowledge/units.json` — atomic knowledge units with content-addressed ids (`k-<sha256[0:12]>`).
- `knowledge/procedures/*.md` — ordered, numbered procedures whose steps cite unit ids.
- `knowledge/source-map.json` — one entry per ingested source.
- `evidence/t-knowledge.json` — AC-07, AC-08, AC-09, AC-15.

## Evidence (host, 2026-11-03)

```text
$ .venv/bin/python -m pytest -q
73 passed in 0.10s

$ .venv/bin/kas build --project projects/live-youtube
... phase 3 complete: Phase 3 — knowledge, procedures, source map, verification and retry
exit=0
```

Live project `projects/live-youtube` now contains 4 knowledge units, 1 procedure (4 steps) and a 1-entry source map; `validate_knowledge` returns `[]`.

## Provider findings (continued)

- Unorouter `gemini-2.5-flash` requires provider consent; failover model switched to `mistral-small-3.2:free`, which answers without consent.
- DeepSeek returns `claim`/`source_ref` (string) shapes for units and a flat `procedure` list for procedures; `extract._coerce_*` now accepts these, plus the documented shapes.

## Deliberate limits

- **No vault projection or hand-edit detection** (AC-24, AC-25) — Phase 4.
- **No daemon trigger** (ADR-006 D18) — Phase 4.
- **No QA report, application report, derived content or Skill packaging** (AC-20…AC-23) — Phase 5.
- **No local model fallback** (ADR-006 D20).

## Next

Phase 4: vault projection (`vault.py`) with frontmatter and hand-edit detection, daemon trigger, publishable content.
