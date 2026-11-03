# Open Questions Register — Knowledge Acquisition Studio

- **Version:** 1.4
- **Opened:** 2026-11-02 (Phase 0 freeze)
- **Rule:** the pipeline must never answer these by guessing. Unanswered **blocking** questions halt the phase that depends on them.

Status values: `open`, `answered`, `waived`.

## 1. Resolution state

| ID | Question | Blocks | Default if waived | Status |
|---|---|---|---|---|
| OQ-1 | Which source kinds must the first release ingest? | Phase 2 adapters | Video + local audio + PDF | **answered** |
| OQ-2 | Where does knowledge output go? | Phase 2 artifact store | Plain folder | **answered** |
| OQ-3 | Which model provider runs extraction/verification? | Phase 2 extraction | Local-only, pluggable | **answered** |
| OQ-4 | What counts as "actionable knowledge" — the primary output? | Phase 2 knowledge schema | Notes + procedures | **answered** |
| OQ-5 | Which languages must transcription and extraction support? | Phase 2 (non-blocking) | Any; language tag per segment | open |
| OQ-6 | Copyright/consent policy for quoting ingested material? | **Phase 4** | Local use only, attributed quotes | open |
| OQ-7 | Trigger interface: CLI, watched folder, or daemon? | Phase 1 CLI shape | One-shot CLI | **answered** |
| OQ-8 | Retention: keep or purge raw media? | Phase 2 (non-blocking) | Keep raw, purge opt-in | open |
| OQ-9 | How are Instagram/Facebook Reels accessed? | Reels adapter | Public-only | **answered** |
| OQ-10 | Behaviour when all API providers fail? | Phase 2 orchestration | Fail loudly | **answered** |

**Open: 3** (OQ-5, OQ-6, OQ-8) — none block Phase 1 or 2 start. OQ-6 blocks Phase 4.

## 2. Resolution log

```text
OQ-1  answered 2026-11-02 — Short-form video first: YouTube videos/Shorts and
      Instagram/Facebook Reels. Adapters: `youtube`, `reels`. PDFs, ebooks and
      web articles deferred.
      (answered by: Director)

OQ-2  answered 2026-11-02 — Obsidian vault as the delivery surface, with JSON kept
      canonical in the project directory and Markdown projected into the vault.
      Vault: ~/Obsidian/knowledge-vault/. Details and rules: ADR-006 D16.
      (answered by: Director)

OQ-3  answered 2026-11-02, revised twice (v1.3) — Remote APIs allowed, credentials
      read from ~/.hermes/.env by variable name only. Provider order:
        1. LLM7        — extraction, verification, transcription (LLM7_API_KEY)
        2. Unorouter   — failover for the same roles (UNOROUTER_API_KEY)
        3. Groq        — Whisper STT fallback (GROQ_API_KEY)
        4. Tavily      — research (TAVILY_API_KEY)
      Pinned models and rationale: ADR-005.
      (answered by: Director)

OQ-4  answered 2026-11-02 — Publishable content (reel/blog scripts) is the primary
      output. Notes, knowledge units and procedures become intermediate artifacts
      whose job is to support content drafts that cite them. ADR-006 D17.
      (answered by: Director)

OQ-7  answered 2026-11-02 — Daemon: `systemd --user` service watching an inbox,
      with a CLI for one-shot runs and tests. Directories and locking fixed in
      ADR-006 D18.
      (answered by: Director)

OQ-9  answered 2026-11-02 — Cookies required. Preferred extraction via
      `yt-dlp --cookies-from-browser firefox`; fallback exported
      `~/.hermes/cookies/instagram.txt` (mode 600). Public-only quarantine when
      cookies are missing or expired. ADR-006 D19.
      (answered by: Director)

OQ-10 answered 2026-11-02 — No local model runtime exists on the host, so there is
      no local fallback. All providers failing means the job fails and escalates;
      no degraded output. ADR-006 D20.
      (answered by: Director)
```

## 3. Provider verification (for OQ-3)

Both endpoints respond and are OpenAI-compatible:

| Provider | Base URL | Models | Auth |
|---|---|---|---|
| LLM7 | `https://api.llm7.io/v1` | 12+ | `LLM7_API_KEY` |
| Unorouter | `https://api.unorouter.com/v1` | 325 | `UNOROUTER_API_KEY` |

Confirmed LLM7 models:

| Model | Input | Context | $ / 1M in·out |
|---|---|---|---|
| `DeepSeek-V4-Flash-0731` | text | 400 k | 0.02 · 0.04 |
| `GLM-5.3-Flash` | text | 400 k | 0.02 · 0.04 |
| `Inkling-Small` | text | 512 k | 0.50 · 1.20 |
| `Voxtral-Mini-3B-2507` | **audio** | — | — |
| `Voxtral-Small-24B-2507` | **audio** | — | — |

## 4. Environment facts recorded during resolution

- `~/.hermes/.env` holds 37 variables; `LLM7_API_KEY`, `UNOROUTER_API_KEY`,
  `GROQ_API_KEY`, `TAVILY_API_KEY` are present. No ElevenLabs/Deepgram/AssemblyAI key.
- That file is mode `644` (world-readable). Recommend `chmod 600 ~/.hermes/.env`
  and `chmod 700 ~/.hermes`. **Still outstanding.**
- Host has `flatpak` + flathub, `yay`, `pamac`, Firefox / Brave / Vivaldi profiles.
  No `uv`, no `yt-dlp` yet. Python 3.14.6.
- Obsidian was not installed at the time OQ-2 was answered; installation is part of
  fulfilling D16.

## 5. Still open

| ID | Why it matters | Default in use until answered |
|---|---|---|
| OQ-5 | Reels are often Hindi/Hinglish; transcription + extraction quality depends on it | Accept any language, store `language` per segment |
| OQ-6 | **Publishable output over copyrighted material.** Must synthesise, not reproduce | Attributed quotes only, no verbatim long-form reproduction |
| OQ-8 | Raw reels/YouTube audio can be large; disk is at 79% | Keep raw, `retention.purge_raw` opt-in |
