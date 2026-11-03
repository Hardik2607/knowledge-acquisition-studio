# Project Status

<!-- generated from status.json by `kas status --write`; do not edit by hand -->

**Project:** `test-yt2`

## Current phase
Phase 3 — knowledge, procedures, source map, verification and retry

## Completed
- Ingested 1 source(s); 0 reused unchanged

## Evidence
- evidence/t-ingest.json
- evidence/t-transcribe.json
- evidence/t-notes.json
- evidence/t-knowledge.json

## Decisions
- ADR-004 — content-addressed ids, immutable raw, verification gate
- ADR-005 — LLM7 primary with Groq Whisper fallback for timestamps
- ADR-006 — cookies via browser profile for reels; no local model fallback

## Risks / issues
- OQ-6 (copyright) remains open; notes quote the source and are not publishable drafts
- Failure: units: invalid_json: model did not return JSON: Expecting value: line 1 column 1 (char 0)
- Failure: procedures: no knowledge units available
- Failure: provenance: knowledge/units.json is missing

## Remaining work
- Phase 4 — vault projection and hand-edit detection (AC-24, AC-25)
- Phase 4 — daemon trigger and publishable content (ADR-006)
- Phase 5 — QA report, application, derived content, Skill packaging (AC-20…AC-23)
- OQ-5/6/8 remain open with documented defaults

## Next executable task
Implement knowledge units and the source map (AC-07, AC-09)

## Last updated
2026-11-02T20:13:03Z
