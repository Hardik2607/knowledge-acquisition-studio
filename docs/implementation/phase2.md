# Phase 2 — Ingest, transcript and notes (implemented)

- **Status:** complete
- **Date:** 2026-11-03
- **Exit criteria:** AC-02, AC-03, AC-04, AC-05, AC-06, AC-18 pass
- **Tests:** 62 passed (`pytest -q`)

## What exists now

```text
knowledge-acquisition-studio/
├── src/kas/
│   ├── ids.py            # content-addressed ids: src-<sha256[0:12]>, k-<sha256[0:12]>
│   ├── models.py         # SourceRecord, Segment, Transcript, KnowledgeUnit, Evidence
│   ├── paths.py          # AC-18 path confinement
│   ├── adapters/
│   │   ├── base.py       # SourceAdapter protocol + AdapterError (auth_expired, …)
│   │   └── video.py      # yt-dlp: subtitles first, audio fallback, VTT parser
│   ├── ingest.py         # immutable raw, checksum conflict, unsupported kind
│   ├── http.py           # stdlib JSON/multipart, Cloudflare-safe User-Agent
│   ├── transcribe.py     # Voxtral (LLM7) → Groq Whisper fallback, normalisation
│   ├── extract.py        # timestamped notes with range validation
│   └── pipeline.py       # ingest → transcript → notes → evidence → status
└── tests/
    ├── fakes.py          # FakeAdapter, FakeTranscriber, FakeClient, StaticClient
    ├── test_ingest.py    # AC-02, AC-03, AC-04
    ├── test_transcribe.py# AC-05
    ├── test_extract.py   # AC-06
    ├── test_paths.py     # AC-18
    └── test_pipeline.py  # end-to-end with fakes
```

## Commands

```bash
.venv/bin/kas validate --project projects/<id>
.venv/bin/kas ingest  --project projects/<id>      # raw bytes + Source Records only
.venv/bin/kas build   --project projects/<id>      # ingest + transcribe + notes
.venv/bin/kas run     --project projects/<id>      # alias for build
.venv/bin/kas status  --project projects/<id>
```

Exit codes: `0` ok, `1` pipeline completed with a failed/quarantined source, `2` validation error, `3` environment/IO error.

## Design decisions realised

| Decision | Where |
|---|---|
| Content-addressed source ids (D3) | `ids.source_id_for` (sha256 of raw bytes) |
| Immutable raw; checksum conflict on change (FR-03, AC-04) | `ingest.ingest` (`IntegrityError` → `checksum_conflict`) |
| Unsupported kind fails that source only (AC-02) | `ingest.ingest` |
| Auth failure → `quarantined` (ADR-006 D19) | `adapters.video.VideoAdapter._raise_for_stderr` |
| Subtitles first, audio fallback (cost) | `VideoAdapter.fetch` |
| Transcript invariants (AC-05) | `transcribe.normalize_segments`, `validate_segments` |
| Note range must exist in a transcript segment (AC-06) | `extract.build_notes`, `_assert_range_in_transcript` |
| Provider failover, no local model (ADR-005) | `transcribe.transcribe_source` (LLM7 → Groq), `extract.ChatClient` (extract → Unorouter) |
| Path confinement before any write (AC-18) | `manifest` via `paths.confine_path` |
| Evidence records per stage | `pipeline._write_evidence` → `evidence/t-{ingest,transcribe,notes}.json` |

## Evidence (run on the host, 2026-11-03)

```text
$ .venv/bin/python -m pytest -q
..............................................................           [100%]
62 passed

$ .venv/bin/kas build --project projects/live-youtube
ingested: 1 source record(s)
reused:   1 unchanged
failed:   0
  ✓ src-8e18a126899c  sources/src-8e18a126899c/raw/jNQXAC9IVRw.webm
transcripts: 1
notes:       1
evidence:    t-ingest.json, t-transcribe.json, t-notes.json

phase 2 complete: Phase 2 — ingest, transcript and notes implemented
exit=0
```

Live source: `https://www.youtube.com/watch?v=jNQXAC9IVRw` ("Me at the zoo", 19 s). Resulting notes (`projects/live-youtube/notes/src-8e18a126899c.md`):

```
- [src-8e18a126899c] 00:00–00:04 — The speaker is in front of the elephants at the zoo.
- [src-8e18a126899c] 00:04–00:13 — The elephants have really, really, really long trunks, which is highlighted as a cool feature.
- [src-8e18a126899c] 00:13–00:15 — The speaker reiterates that the long trunks are cool.
- [src-8e18a126899c] 00:17–00:19 — The speaker concludes that this is pretty much all there is to say.
```

Re-running the build left the raw file mtime and `source.json` byte-identical (`reused: 1 unchanged`).

## Provider findings (recorded, not silently worked around)

- LLM7 audio (`Voxtral-Small-24B-2507`) calls `/audio/transcriptions` but returns `402 insufficient_balance` on this account. The chain falls through to Groq Whisper, which is validated end to end.
- LLM7 chat (`DeepSeek-V4-Flash-0731`) is the validated extraction model. Its note JSON used an alternate key shape (`timestamp`/`note`); `extract._coerce_note` now accepts both, so a chatty model cannot break the pipeline.
- Groq's Cloudflare layer rejects the default `Python-urllib` agent with HTTP 403 / error 1010. `http.USER_AGENT` identifies `kas/0.1` and is sent on every request.
- Unorouter's originally configured model id `anthropic/claude-sonnet-4-6` does not exist in its catalogue (326 models). The failover model was changed to `gemini-2.5-flash` and verified against `/v1/models`. ADR-005 was updated to match.

## Deliberate limits

- **No knowledge units, procedures or source map.** Those are Phase 3 (AC-07, AC-08, AC-09).
- **No retry/escalation or idempotency harness** beyond raw immutability (AC-10…AC-13) — Phase 3.
- **No vault projection or hand-edit detection** (AC-24, AC-25) — Phase 4/5.
- **No daemon trigger** (ADR-006 D18) — Phase 4.
- **No local model fallback.** Provider exhaustion fails loudly with the provider's error body (ADR-006 D20).

## Next

Phase 3, in order:

1. `extract_units` → `knowledge/units.json` with content-addressed ids (AC-07, AC-13).
2. `build_procedures` → `knowledge/procedures/*.md` (AC-08).
3. `source-map.json` covering every ingested source (AC-09).
4. Verification gate + bounded retry/escalation (AC-10, AC-11) and idempotent re-run harness (AC-12).
5. Provenance sweep across `notes/`, `knowledge/`, `derived/`, `application/` (AC-15).
6. Offline mode enforcement (`network.enabled: false`) (AC-16, AC-17).
