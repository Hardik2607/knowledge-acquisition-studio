# ADR-004 — Phase 0 requirements freeze

- **Date:** 2026-11-02
- **Status:** Accepted (pending Director sign-off on blocking open questions)
- **Deciders:** Director, Orchestrator
- **Supersedes:** none
- **Related:** requirements v2.0, acceptance-criteria v1.0, open-questions v1.0

## Context

The project shipped as a documentation scaffold (v1.0): structure, contracts and prompts existed, but no requirement was testable and no artifact contract was defined. Phase 0 of the implementation plan requires frozen requirements, a Director's Section and acceptance criteria before any code is written.

## Decisions

**D1 — Adapter-based source model.**
Every origin is normalized into one Source Record (requirements §4). Adapters are pluggable and may not change the record. *Consequence:* new origins are additive; the core pipeline never branches on source kind.

**D2 — Fixed artifact layout.**
The project-root directory contract in requirements §6 is frozen. *Consequence:* tests and agents can assert paths; no agent may invent directories.

**D3 — Content-addressed identifiers.**
`source_id = src-<sha256[0:12]>`, `knowledge unit id = k-<sha256(statement)[0:12]>`. *Consequence:* determinism and idempotency (AC-12, AC-13) fall out of the design instead of being bolted on.

**D4 — Raw sources are immutable.**
A checksum conflict is a hard failure, never an overwrite. *Consequence:* provenance is trustworthy; re-ingest is safe.

**D5 — Verification is a gate, not a report.**
Completion without an `evidence/<task_id>.json` with `result: "pass"` is rejected by the orchestrator (AC-10). *Consequence:* "done" is falsifiable.

**D6 — Fail-fast configuration.**
Unknown manifest or config keys are errors (AC-19). *Consequence:* typos surface immediately instead of producing silently degraded runs.

**D7 — Bounded retries with escalation.**
`max_retries` (default 3) then stop the branch and record `escalated: true` (AC-11). *Consequence:* no infinite loops, no hidden repeated failures.

**D8 — Offline-first, network opt-in.**
`network.enabled: false` is the default; egress attempts are blocked and logged (AC-16, AC-17). *Consequence:* reproducible and privacy-preserving by default.

**D9 — Phase gates are exit tests.**
Phase transitions require the named criteria to pass (acceptance-criteria §4), not a verbal claim. *Consequence:* the roadmap becomes mechanically checkable.

**D10 — Unanswered questions are recorded, not guessed.**
Blocking questions live in `open-questions.md` with an explicit default used only if the Director waives them. *Consequence:* satisfies the Director's "do not silently invent missing inputs" non-negotiable.

## Consequences

- Phase 1 can start on manifest/config/status without resolving OQ-1…OQ-4, but **Phase 2 cannot**.
- Every later behaviour change requires a new ADR and a version bump (requirements §10).
- The `VERSION` field in the packaged Skill must track the requirements version (AC-22).

## Open items

OQ-1 (source kinds), OQ-2 (output destination), OQ-3 (model runtime), OQ-4 (knowledge definition), OQ-7 (trigger) are blocking for their phase. OQ-5, OQ-6, OQ-8 have safe defaults.
