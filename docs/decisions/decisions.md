# Architecture Decisions

## ADR-001 — Documentation as source of truth
Project requirements, architecture, decisions and status live in version control.

## ADR-002 — Verification before completion
No agent may mark a task complete without evidence.

## ADR-003 — Reusable Skill
A stable workflow is packaged as a versioned Skill rather than recreated from scratch.

## ADR-004 — Phase 0 requirements freeze
Requirements v2.0, acceptance criteria AC-01…AC-23, the open-questions register and phase gates are frozen.

Key decisions:
- Adapter-based source model with one fixed Source Record contract.
- Fixed project-root artifact layout; no agent may invent directories.
- Content-addressed ids (`src-<sha256>`, `k-<sha256>`) for determinism and idempotency.
- Raw sources immutable; checksum conflict is a hard failure.
- Completion blocked without passing evidence.
- Fail-fast configuration: unknown keys are errors.
- Bounded retries (default 3) with escalation.
- Offline-first, network opt-in.
- Phase transitions are exit tests.
- Missing inputs are recorded as questions, never guessed.

Full record: `ADR-004-phase0-freeze.md`.

## ADR-005 — Model provider selection (LLM7 primary, Unorouter failover)
- Primary: LLM7 (`https://api.llm7.io/v1`) — `DeepSeek-V4-Flash-0731` for extraction,
  `GLM-5.3-Flash` for verification (different family), `Voxtral-Small-24B-2507` for
  audio → text.
- Failover: Unorouter (`https://api.unorouter.com/v1`), pinned model id.
- Groq Whisper remains the validated transcription fallback; Tavily for research.
- Every artifact records `provider`, `model`, `base_url`, `request_id`.
- Model ids validated against `/v1/models` before a run; secrets referenced by env name only.

Full record: `ADR-005-model-providers.md`.

## ADR-006 — Output to Obsidian, publishable content, daemon trigger
- `~/Obsidian/knowledge-vault/` is the delivery surface; JSON stays canonical, Markdown is projected.
- Publishable content is the **primary** output; notes/knowledge/procedures are intermediate.
- `systemd --user` daemon watches `runtime/inbox/`; CLI retained for one-shot runs and tests.
- Reels need cookies: `yt-dlp --cookies-from-browser firefox`, fallback exported `cookies.txt` (mode 600); quarantine when absent/expired.
- No local model runtime → all providers failing means the job fails and escalates.

Full record: `ADR-006-output-trigger-sources.md`.
