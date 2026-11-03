---
name: knowledge-acquisition-studio
description: Ingest tutorials, transcripts and learning sources, extract actionable knowledge, verify it, and apply it to projects.
---

# Skill: knowledge-acquisition-studio

## Version
0.1.0

## Purpose
Ingest tutorials, transcripts and learning sources, extract actionable knowledge, verify it, and apply it to projects.

## Inputs
Project-specific source materials and configuration.

## Outputs
- source map
- timestamped notes
- knowledge base
- step-by-step procedure
- verification evidence
- original educational content

## Execution
Invoke the project orchestrator, execute the workflow, verify every stage, update status, and continue automatically to the next unblocked task.

## Failure policy
Do not silently skip failures. Diagnose, retry within configured limits, and escalate only when blocked.

## Quality gate
All mandatory acceptance tests must pass before release.
