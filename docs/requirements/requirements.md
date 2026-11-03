# Requirements — Knowledge Acquisition Studio

- **Version:** 2.1 (Phase 0 freeze; ADR-006 applied)
- **Status:** Frozen — conditional on the blocking questions in `docs/requirements/open-questions.md`
- **Frozen on:** 2026-11-02 (rev 2.1: 2026-11-02)
- **Owner:** Director
- **Supersedes:** v1.0 (2026-09-06)

## 1. Purpose

Ingest tutorials, transcripts and learning sources, extract actionable knowledge, verify it, and apply it to projects.

The system converts untrusted, unstructured learning material into **traceable, verifiable, reusable knowledge artifacts**.

## 2. Scope

### 2.1 In scope

- Ingest a declared set of sources described by a project manifest.
- Preserve the original bytes and full provenance of every source.
- Produce timestamped notes, a knowledge base, and step-by-step procedures.
- Verify every produced artifact against a written acceptance criterion.
- Apply extracted knowledge to a downstream project and record the application.
- Persist status, decisions and evidence for every task.
- Package the stable workflow as a versioned Skill.

### 2.2 Out of scope (v0.x)

- Publishing or redistributing ingested material.
- Copyright circumvention, DRM removal, or scraping behind authentication without explicit consent recorded in the manifest.
- Real-time / streaming ingestion.
- Multi-user accounts, roles or hosted service.
- Fine-tuning or training models on ingested content.
- Automatic purchase or download of paid sources.

## 3. Actors

| Actor | Responsibility |
|---|---|
| Director (human) | Approves scope, resolves open questions, signs off releases |
| Orchestrator | Decomposes goal into tasks, selects next unblocked task, enforces gates |
| Ingestion adapters | Normalize one source origin into a Source Record |
| Specialist agents | Transcribe, research, extract, compose, apply |
| Verification agent | Executes acceptance criteria, emits evidence |
| Status agent | Persists status, decisions, risks, next task |

## 4. Source model

Every input is normalized into a **Source Record** regardless of origin. Support for an origin is provided by an *ingestion adapter*. Adapters are pluggable and **must not** alter the Source Record contract.

Required Source Record fields:

| Field | Type | Rule |
|---|---|---|
| `source_id` | string | stable, derived from checksum; `src-<sha256[0:12]>` |
| `kind` | enum | `video`, `audio`, `pdf`, `epub`, `html`, `text`, `image` |
| `origin` | string | original URI, path, or user-supplied identifier |
| `title` | string | non-empty |
| `author` | string \| null | attribution if known |
| `retrieved_at` | ISO-8601 | UTC |
| `checksum` | string | sha256 of raw bytes |
| `raw_path` | string | path under `sources/<source_id>/raw/` |
| `license` | string \| null | declared license/consent; `unknown` allowed but surfaced in QA |
| `status` | enum | `ingested`, `failed`, `quarantined` |

The concrete adapter set is **not** frozen — see OQ-1. FR-02 only requires that every source kind in a manifest has a declared adapter.

## 5. Functional requirements

| ID | Requirement | Priority | Acceptance |
|---|---|---|---|
| FR-01 | Validate a project manifest before any work starts. Invalid manifests produce field-level errors and write no artifacts. | Must | AC-01 |
| FR-02 | Ingest every source declared in the manifest via an adapter matching its kind. Unsupported kinds fail the task with a named reason. | Must | AC-02, AC-03 |
| FR-03 | Preserve raw source bytes immutably; never overwrite differing bytes. | Must | AC-04 |
| FR-04 | Produce a normalized transcript with monotonic, non-overlapping timestamped segments. | Must | AC-05 |
| FR-05 | Produce timestamped notes where every claim carries `source_id` + timestamp range that exists in the transcript. | Must | AC-06 |
| FR-06 | Extract atomic knowledge units with stable ids, source references and confidence. | Must | AC-07 |
| FR-07 | Compose ordered, checkable step-by-step procedures referencing knowledge units. | Must | AC-08 |
| FR-08 | Maintain a source map that accounts for 100% of ingested sources exactly once. | Must | AC-09 |
| FR-09 | Block task completion unless a matching evidence artifact exists. | Must | AC-10 |
| FR-10 | On failure: record diagnostics, retry up to `max_retries` (default 3), then escalate and stop that branch. | Must | AC-11 |
| FR-11 | Be idempotent: re-running a task must not duplicate artifacts or change content-addressed ids. | Must | AC-12, AC-13 |
| FR-12 | Update status after every task with phase, completed work, evidence, risks, remaining work, next task and timestamp. | Must | AC-14 |
| FR-13 | Keep every derived artifact traceable to existing source records. | Must | AC-16 |
| FR-14 | Operate fully offline with local sources; network access is opt-in and explicit. | Must | AC-17 |
| FR-15 | Confine all writes to the project root; reject path traversal. | Must | AC-18 |
| FR-16 | Reject unknown configuration keys and unknown manifest fields rather than guessing. | Must | AC-19 |
| FR-17 | Record application of extracted knowledge to a downstream project with an application report. | Should | AC-20 |
| FR-18 | Emit original educational content derived from the knowledge base, clearly separable from quoted source material. This is the **primary** output; notes and procedures exist to support it. | Must | AC-21 |
| FR-19 | Package the workflow as a versioned Skill whose VERSION tracks the release. | Must | AC-22 |
| FR-20 | Produce a QA report summarising every acceptance criterion and its result. | Must | AC-23 |
| FR-21 | Project canonical artifacts into an Obsidian vault as generated Markdown with provenance frontmatter, without the vault becoming the source of truth. | Must | AC-24 |
| FR-22 | Detect and report hand-edits to projected vault notes instead of silently overwriting them. | Must | AC-25 |

## 6. Artifact contract

```text
projects/<project_id>/
  manifest.yaml              # frozen input contract
  status.json                # machine-readable status
  sources/
    <source_id>/
      source.json            # Source Record
      raw/                   # original bytes, immutable
      transcript.json        # normalized segments
  notes/
    <source_id>.md           # timestamped notes
  knowledge/
    units.json               # atomic knowledge units
    procedures/*.md          # step-by-step procedures
    source-map.json           # source coverage
  derived/                   # original educational content
  application/
    report.md                # how knowledge was applied
  evidence/
    <task_id>.json           # verification evidence
  reports/
    qa-report.md
```

Rules:

- `raw/` is immutable after ingest. A checksum mismatch is a hard error, never a silent overwrite.
- Every derived artifact records `source_ids`, `generator`, `generated_at` and `schema_version`.
- Knowledge unit ids are content-addressed: `k-<sha256[0:12]>` over normalized statement text.
- No artifact may reference a `source_id` that has no Source Record.
- Artifacts are inspectable plain text (JSON/Markdown); no opaque binaries in derived output.

## 6.1 Delivery projection (ADR-006)

Canonical output lives in the project directory (§6). A projection step mirrors it into
an Obsidian vault so the knowledge is readable and linkable:

```text
~/Obsidian/knowledge-vault/
  Sources/  Notes/  Knowledge/  Procedures/  Content/  Attachments/  Templates/
```

- Markdown is generated, never authored by hand as the source of truth.
- Each note carries `source_id`, `source_uri`, `provider`, `model`, `generated_at`,
  `schema_version`, `content_hash`.
- `Knowledge/` notes are cross-linked with `[[k-<id>]]` so the vault graph mirrors the
  knowledge graph.
- Obsidian plugins are optional; correctness must not depend on one.

## 7. Quality requirements

Retained from v1.0:

- No silent failures.
- No unverified completion.
- Configuration must be explicit.
- Intermediate artifacts must be inspectable.
- Manual approval is required only where defined by the Director's Section.

Added in v2.0:

- **Determinism:** identical inputs produce identical content-addressed ids and artifact content, excluding `generated_at`/timestamps in metadata.
- **Provenance:** every extracted claim is traceable to a source and a timestamp range.
- **Idempotency:** re-running any task is safe and produces no duplicates.
- **Offline-first:** no outbound network call without an explicit opt-in.
- **Non-destructive:** no write outside the project root; no deletion of raw sources by the pipeline.
- **Fail-fast config:** unknown keys are errors, not warnings.

## 8. Expected outputs (retained)

- source map
- timestamped notes
- knowledge base
- step-by-step procedure
- verification evidence
- original educational content

## 9. Acceptance and release

The full criteria set lives in `docs/testing/acceptance-criteria.md`.

A release is approved only when:

1. Every **Must** acceptance criterion passes.
2. `reports/qa-report.md` exists and lists each criterion with a result.
3. `docs/status/status.md` is updated.
4. `skills/knowledge-acquisition-studio/VERSION` matches the release version.

## 10. Change control

This document is frozen. Any change requires:

1. A new ADR in `docs/decisions/` with rationale and consequences.
2. A version bump in this document and in `skills/knowledge-acquisition-studio/VERSION`.
3. An update to `docs/testing/acceptance-criteria.md` where behaviour changes.
