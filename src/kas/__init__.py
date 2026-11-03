"""Knowledge Acquisition Studio — Phase 1 foundation.

Phase 1 implements exactly four things:

* manifest loading and validation (AC-01),
* configuration loading with strict key checking (AC-19),
* the dual status writer, `status.json` + `docs/status/status.md` (AC-14),
* a CLI that makes the above usable and testable.

No ingestion, transcription or extraction happens yet.
"""

__version__ = "0.1.0"
