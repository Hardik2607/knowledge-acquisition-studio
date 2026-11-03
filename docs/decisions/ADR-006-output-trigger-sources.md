# ADR-006 — Output to Obsidian, publishable content, daemon trigger

- **Date:** 2026-11-02
- **Status:** Accepted
- **Deciders:** Director
- **Resolves:** OQ-2, OQ-4, OQ-7, OQ-9, OQ-10
- **Related:** ADR-004 (artifact contract), ADR-005 (providers)

## Context

Phase 0 needed five answers before Phase 2 could start: where output goes, what the
primary artifact is, how runs are triggered, how Instagram Reels are accessed, and
what happens when every remote provider fails.

## Decisions

**D16 — Obsidian vault is the delivery surface (OQ-2).**
The canonical store stays the project directory (JSON, per ADR-004 D2). A
**projection step** writes human-facing Markdown into an Obsidian vault:

```text
~/Obsidian/knowledge-vault/
  Sources/            # one note per source, frontmatter + timestamped claims
  Notes/              # per-source distilled notes
  Knowledge/          # atomic knowledge units as notes, [[wikilinks]] between them
  Procedures/         # step-by-step procedures
  Content/            # publishable drafts
  Attachments/        # audio/frames only if retention allows (OQ-8)
  Templates/          # source.md, knowledge.md, procedure.md, content.md
```

Rules:
- JSON is canonical; Markdown is generated and **never hand-edited as source of truth**
  (a hand-edit is detected by hash and reported, not silently overwritten).
- Every projected note carries frontmatter: `source_id`, `source_uri`, `provider`,
  `model`, `generated_at`, `schema_version`, `content_hash`.
- Wikilinks use knowledge-unit ids (`[[k-1a2b3c4d5e6f]]`), so the vault graph mirrors
  the knowledge graph.
- Obsidian is a *viewer*: no plugin is required for correctness. Dataview is optional.

**D17 — Publishable content is the primary output (OQ-4).**
Notes, knowledge units and procedures are **intermediate** artifacts whose purpose is
to support publishable drafts in `Content/`. Consequences:
- Content drafts must cite the knowledge units they use, and those units must cite
  sources + timestamps (keeps AC-06/AC-15 meaningful end-to-end).
- A draft with no resolvable unit citations fails verification.
- FR-18 (original content separation) becomes a `Must` for release, not a `Should`.

**D18 — Daemon trigger (OQ-7).**
A `systemd --user` service (`kas-daemon`) watches an inbox and runs the pipeline:

```text
~/ai-agent-ecosystem/runtime/inbox/      # drop a job file (yaml) here
~/ai-agent-ecosystem/runtime/queue/      # claimed jobs
~/ai-agent-ecosystem/runtime/done/       # completed, with evidence pointer
~/ai-agent-ecosystem/runtime/failed/     # escalated, with diagnostics
```

- One worker at a time per project (lockfile), jobs processed FIFO.
- CLI remains available (`kas run --project <dir>`) for one-shot work and tests.
- The daemon is a thin shell around the same orchestrator; no logic lives only in it.

**D19 — Reels access requires cookies (OQ-9).**
Instagram/Facebook Reels need an authenticated session. Plan:
- Preferred: `yt-dlp --cookies-from-browser firefox` (Firefox profile exists on the host),
  so no credential file is written by us.
- Fallback: an exported Netscape `cookies.txt` at `~/.hermes/cookies/instagram.txt`,
  mode `600`, referenced by path in config — never copied into the repo or artifacts.
- Public-only mode is the default when cookies are absent: login-gated reels are
  `quarantined` with a named reason, not silently skipped.
- Cookies expire. The daemon must detect auth failure and quarantine rather than retry
  forever.

**D20 — No local fallback (OQ-10).**
There is no local model runtime on the host, so D8's offline mode cannot cover
extraction. If LLM7 and Unorouter both fail beyond the retry budget, the job is marked
`failed` with `escalated: true` and the run stops. No degraded output is produced.
Ingestion, checksumming and transcript storage still work offline.

## Consequences

- A markdown projection layer and its tests are added to Phase 2 scope.
- Obsidian must be installed on the host (flatpak, user scope, no root needed).
- The daemon is Phase 5 work, but its directories and locking rules are fixed now.
- Because content is the primary output, OQ-6 (copyright/consent) becomes urgent:
  publishable drafts over copyrighted reels must synthesise, not reproduce, source text.
- Cookie handling becomes a documented operational task with an expiry failure mode.
