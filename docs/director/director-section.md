# Director's Section — Knowledge Acquisition Studio

## Intent
Ingest tutorials, transcripts and learning sources, extract actionable knowledge, verify it, and apply it to projects.

## Non-negotiables
- Follow the approved project requirements.
- Preserve source/provenance where applicable.
- Do not silently invent missing inputs.
- Do not mark work complete without verification.
- Prefer free/open-source/local solutions where practical.

## Continuity rules
- Maintain consistent project state.
- Do not contradict approved decisions without recording a new decision.
- Preserve naming and artifact contracts.

## Quality bar
The output must be usable, testable, reproducible and clearly documented.

## Prohibited deviations
- Skipping QA to claim completion.
- Hiding failed tasks.
- Changing core requirements without a recorded decision.
- Replacing evidence with assumptions.

## Approval criteria
A release is approved only when all required acceptance tests pass and status is updated.

## Phase gates (v2.0)
Phase transitions are exit tests, not opinions (`docs/testing/acceptance-criteria.md` §4):

| Gate | Exit condition |
|---|---|
| 0 → 1 | Requirements v2.0 and acceptance criteria exist; blocking open questions answered or waived. |
| 1 → 2 | Manifest, config and status layers implemented; AC-01, AC-14, AC-19 pass. |
| 2 → 3 | Ingest, transcript and notes pipeline; AC-03…AC-06, AC-18 pass. |
| 3 → 4 | Knowledge, procedures, source map, retry, idempotency; AC-07…AC-13, AC-15…AC-17 pass. |
| 4 → 5 | QA report, application, derived content, Skill packaging; AC-20…AC-23 pass. |

## Assumption policy (v2.0)
When an input is missing, the agent must do exactly one of:

1. Ask the Director and record the answer in `docs/requirements/open-questions.md`, or
2. Apply the documented default **only if** the Director explicitly waives the question, and record the waiver.

An unrecorded assumption is a defect, not a shortcut.

## Freeze policy (v2.0)
Requirements are frozen at v2.0. Any behavioural change requires an ADR in `docs/decisions/`, a version bump in `docs/requirements/requirements.md`, and a matching `skills/knowledge-acquisition-studio/VERSION`.

## Sign-off
Phase 0 is signed off when the Director resolves or waives OQ-1, OQ-2, OQ-3, OQ-4 and OQ-7.
