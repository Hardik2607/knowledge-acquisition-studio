# Acceptance Criteria — Knowledge Acquisition Studio

- **Version:** 1.0 (Phase 0 freeze)
- **Frozen on:** 2026-11-02
- **Applies to:** requirements v2.1
- **Gate rule:** a criterion is *passed* only when the stated evidence exists and is reproducible.

## 1. Conventions

- `PASS` requires a command, fixture or artifact path that a second person can re-run.
- Every criterion is verified by the **verification agent** and recorded as `evidence/<task_id>.json`.
- Evidence record shape:

```json
{
  "task_id": "t-0007",
  "criteria": ["AC-03"],
  "result": "pass",
  "artifacts": ["sources/src-1a2b3c4d5e6f/source.json"],
  "command": "pytest tests/test_ingest.py -k checksum",
  "run_at": "2026-11-02T18:40:00Z",
  "notes": null
}
```

- Manual review is allowed only for AC marked `review`; everything else must be automated.

## 2. Criteria

### AC-01 — Manifest validation (FR-01) · automated

Given a manifest missing a required field or containing an unknown field
When the orchestrator starts
Then it exits non-zero, prints the field path and the expected type, and writes no files under `sources/`, `notes/`, `knowledge/` or `evidence/`.

### AC-02 — Unsupported source kind (FR-02) · automated

Given a manifest declaring `kind: epub` and no registered epub adapter
When ingestion runs
Then the task is marked `failed`, the reason names the unsupported kind, and remaining sources still ingest.

### AC-03 — Source Record completeness (FR-02) · automated

Given a successfully ingested source
When `sources/<source_id>/source.json` is read
Then all fields in requirements §4 are present, `checksum` equals the sha256 recomputed from `raw/`, and `source_id` equals `src-<checksum[0:12]>`.

### AC-04 — Raw immutability (FR-03) · automated

Given a source already ingested
When ingestion runs again with identical bytes
Then the raw file hash and mtime are unchanged and no duplicate record is created.
When ingestion runs with different bytes under the same `source_id`
Then it fails with a checksum-conflict error and does not overwrite `raw/`.

### AC-05 — Transcript normalization (FR-04) · automated

Given a completed transcription
When `transcript.json` is read
Then segments are ordered, `start < end`, `start[n] >= end[n-1]` (no overlap), no segment exceeds 30 s, and every segment has non-empty `text`.

### AC-06 — Note provenance (FR-05) · automated

Given generated notes for a source
When each note bullet is checked
Then it carries `source_id` and a timestamp range that exists within a transcript segment of that source; any bullet failing this fails the criterion.

### AC-07 — Knowledge unit integrity (FR-06) · automated

Given `knowledge/units.json`
When validated
Then every unit has `id`, `statement`, `source_refs` (≥1), `confidence` ∈ {`low`,`medium`,`high`}, ids are unique and equal to `k-<sha256(statement)[0:12]>`.

### AC-08 — Procedural executability (FR-07) · automated

Given `knowledge/procedures/*.md`
When parsed
Then each procedure has an ordered list of numbered steps, every step references ≥1 knowledge unit id that exists, and no step is empty or a restatement of a section heading.

### AC-09 — Source map coverage (FR-08) · automated

Given N ingested sources
When `knowledge/source-map.json` is read
Then it contains exactly N entries, each `source_id` appears once, and no entry references a missing Source Record.

### AC-10 — Verification gate (FR-09) · automated

Given a task whose evidence artifact is absent or has `result: "fail"`
When completion is attempted
Then the task stays `in_progress`/`failed`, the orchestrator reports a gate violation, and `status.json` is not advanced.

### AC-11 — Bounded retry and escalation (FR-10) · automated

Given an agent that raises on every attempt and `max_retries: 3`
When the task runs
Then exactly 4 attempts are recorded (1 + 3), each with diagnostics, the task ends `failed` with `escalated: true`, and no further tasks from that branch run.

### AC-12 — Idempotent re-run (FR-11) · automated

Given a completed task
When the same task is executed again with unchanged inputs
Then artifact count is unchanged, file contents are byte-identical except `generated_at`, and `status.json` records no duplicate completions.

### AC-13 — Deterministic ids (FR-11) · automated

Given two independent runs over the same source set on different dates
When unit and source ids are compared
Then the id sets are identical.

### AC-14 — Status contract (FR-12) · automated

Given any completed or failed task
When `status.json` and `docs/status/status.md` are read
Then both contain current phase, completed items, evidence references, risks, remaining work, next executable task and an ISO-8601 timestamp; `status.md` matches `status.json`.

### AC-15 — Provenance resolution (FR-13) · automated

Given every artifact under `notes/`, `knowledge/`, `derived/` and `application/`
When all `source_ids` are resolved
Then every id maps to an existing `sources/<source_id>/source.json`; zero dangling references.

### AC-16 — Offline operation (FR-14) · automated

Given `network.enabled: false` and only local file sources
When the full pipeline runs with the network interface disabled
Then it completes and all Must criteria pass.

### AC-17 — Network opt-in (FR-14) · automated

Given `network.enabled: false`
When any adapter or agent attempts an outbound connection
Then the attempt is blocked, logged with the target, and the run fails loudly rather than degrading silently.

### AC-18 — Path confinement (FR-15) · automated

Given a manifest value containing `../` or an absolute path outside the project root
When processed
Then it is rejected before any write, and no file outside the root is created or modified.

### AC-19 — Unknown key rejection (FR-16) · automated

Given a manifest or config with an unknown key
When loaded
Then loading fails with the unknown key path; it does not warn-and-continue.

### AC-20 — Application report (FR-17) · review

Given a completed knowledge base
When knowledge is applied to a downstream project
Then `application/report.md` names the target project, lists the applied units with their ids, and states the observable change made.

### AC-21 — Original content separation (FR-18) · review

Given `derived/` content
When reviewed
Then quoted source material is clearly marked with source and timestamp, and original writing is distinguishable from quotes.

### AC-22 — Skill version alignment (FR-19) · automated

Given a release
When `skills/knowledge-acquisition-studio/VERSION`, requirements version and `reports/qa-report.md` version are compared
Then all three match.

### AC-23 — QA report completeness (FR-20) · automated

Given a release candidate
When `reports/qa-report.md` is parsed
Then it lists every criteria id AC-01…AC-25 exactly once with a result, and the overall result is `pass` only if every Must criterion passed.

### AC-24 — Vault projection fidelity (FR-21) · automated

Given canonical artifacts for a project
When projection runs against an empty vault
Then every source, knowledge unit and procedure has exactly one note, each note carries the required frontmatter (`source_id`, `provider`, `model`, `generated_at`, `schema_version`, `content_hash`), and `Knowledge/` notes link to their unit ids.
When projection runs a second time with unchanged inputs
Then no duplicate notes are created and content hashes are unchanged.

### AC-25 — Hand-edit detection (FR-22) · automated

Given a projected note whose content no longer matches its recorded `content_hash`
When projection runs again
Then the note is reported as hand-edited in the run report, the file is not silently overwritten, and the run's overall result reflects the conflict.

## 3. Definition of Done (per task)

A task is complete only when all of the following exist:

1. The artifact(s) it produces.
2. An `evidence/<task_id>.json` with `result: "pass"`.
3. A status update in `status.json` + `docs/status/status.md`.
4. At least one automated test covering its behaviour (Must tasks only).

## 4. Phase gates

| Gate | Exit condition |
|---|---|
| Phase 0 → 1 | This document and requirements v2.0 exist; blocking open questions answered or explicitly waived by the Director. |
| Phase 1 → 2 | Manifest loader, config loader, status writer implemented; AC-01, AC-14, AC-19 pass. |
| Phase 2 → 3 | Ingest + transcript + notes pipeline implemented; AC-03, AC-04, AC-05, AC-06, AC-18 pass. |
| Phase 3 → 4 | Knowledge, procedures, source map, retry and idempotency implemented; AC-07…AC-13, AC-15…AC-17 pass. |
| Phase 4 → 5 | QA report, application, derived content, vault projection and Skill packaging; AC-20…AC-25 pass. |

## 5. Traceability

| Requirement | Criteria |
|---|---|
| FR-01 | AC-01 |
| FR-02 | AC-02, AC-03 |
| FR-03 | AC-04 |
| FR-04 | AC-05 |
| FR-05 | AC-06 |
| FR-06 | AC-07 |
| FR-07 | AC-08 |
| FR-08 | AC-09 |
| FR-09 | AC-10 |
| FR-10 | AC-11 |
| FR-11 | AC-12, AC-13 |
| FR-12 | AC-14 |
| FR-13 | AC-15 |
| FR-14 | AC-16, AC-17 |
| FR-15 | AC-18 |
| FR-16 | AC-19 |
| FR-17 | AC-20 |
| FR-18 | AC-21 |
| FR-19 | AC-22 |
| FR-20 | AC-23 |
| FR-21 | AC-24 |
| FR-22 | AC-25 |
