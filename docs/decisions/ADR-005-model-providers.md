# ADR-005 — Model provider selection (LLM7 primary, Unorouter failover)

- **Date:** 2026-11-02
- **Status:** Accepted
- **Deciders:** Director
- **Related:** OQ-3, requirements §5 FR-06/FR-09, acceptance-criteria AC-07/AC-23

## Context

OQ-3 asked which runtime performs extraction and verification. The Director chose
LLM7 over OpenRouter, with Unorouter as an alternative. Both endpoints were probed
from the host:

| Provider | Base URL | Auth | Models | Notes |
|---|---|---|---|---|
| LLM7 | `https://api.llm7.io/v1` | `LLM7_API_KEY` | 12+ | OpenAI-compatible; text and audio models |
| Unorouter | `https://api.unorouter.com/v1` | `UNOROUTER_API_KEY` | **325** | OpenAI-compatible; many `:free`, plus `claude-*`/`gpt-*` |

Verified LLM7 entries:

| Model | Input | Context | Price / 1M in·out | Tools |
|---|---|---|---|---|
| `DeepSeek-V4-Flash-0731` | text | 400 k | $0.02 · $0.04 | yes |
| `GLM-5.3-Flash` | text | 400 k | $0.02 · $0.04 | yes |
| `Inkling-Small` | text | 512 k | $0.50 · $1.20 | yes |
| `Voxtral-Mini-3B-2507` | **audio** | — | — | yes |
| `Voxtral-Small-24B-2507` | **audio** | — | — | yes |

## Decision

**D11 — LLM7 is the primary provider.**
- Extraction, notes and procedure generation: `DeepSeek-V4-Flash-0731`.
- Verification: `GLM-5.3-Flash` — a different model family from the generator, so a
  pass is not the generator agreeing with itself. This directly strengthens AC-10.
- Transcription: `Voxtral-Small-24B-2507` (audio → text), with Groq
  `whisper-large-v3` as fallback.

**D12 — Unorouter is failover, not primary.**
Used when LLM7 returns errors/timeouts beyond the retry budget. Model id is pinned in
`config/default.yaml`, never resolved dynamically at runtime.

**D13 — Every artifact records its producer.**
`provider`, `model`, `base_url` and `request_id` go into artifact metadata and into
`evidence/<task_id>.json`. A run with an unknown producer is invalid.

**D14 — Model ids are validated before a run.**
The orchestrator checks the configured model id appears in the provider's `/v1/models`
and aborts with a named error otherwise. Cheap check, prevents silent 404-to-fallback.

**D15 — Secrets stay in `~/.hermes/.env`.**
Config references environment variable names only (`api_key_env: LLM7_API_KEY`).

## Consequences

- Cost is negligible for the chosen models (~$0.02/1M in, $0.04/1M out).
- Two model families means extraction and verification failures are less correlated.
- LLM7 is a small provider: an outage blocks the pipeline unless Unorouter is configured.
  OQ-10 records whether a fully local fallback is required.
- Voxtral removes the hard dependency on Groq for transcription, but its timestamp
  behaviour is unproven — AC-05 must be tested against it, and Groq Whisper must remain
  validated as the fallback path.
- Unorouter's 325-model catalogue is a moving target; pinning ids (D12) keeps runs
  reproducible.

## Open items

- OQ-10: behaviour when LLM7 **and** Unorouter both fail (fail loudly vs local model).
- Confirm Voxtral emits segment timestamps; if it only returns plain text, word-level
  timing must come from Groq Whisper or an alignment pass (lyrical-video already uses
  forced alignment, which can be reused).
