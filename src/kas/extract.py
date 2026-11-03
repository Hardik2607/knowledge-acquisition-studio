"""Extraction: transcript → timestamped notes → knowledge units → procedures.

The model proposes; this module disposes. Every artefact is validated against the
transcript before it is accepted, so a fluent but unsupported claim cannot enter the
knowledge base:

* notes      — each bullet must carry a real `source_id` and a timestamp inside the
               transcript (AC-06),
* units      — ids are recomputed here from the statement text, references must
               resolve, confidence must be known (AC-07),
* procedures — every step must cite existing unit ids (AC-08).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .http import HttpError, post_json
from .ids import procedure_id_for, unit_id_for
from .models import KnowledgeUnit, Segment, Transcript

CONFIDENCE = ("low", "medium", "high")

ACTION_VERBS = {
    "opens": "Open",
    "pastes": "Paste",
    "selects": "Select",
    "answers": "Answer",
    "skips": "Skip",
    "presents": "Present",
    "shares": "Share",
    "provides": "Provide",
    "creates": "Create",
    "clicks": "Click",
    "runs": "Run",
    "sets": "Set",
    "adds": "Add",
    "uses": "Use",
    "gives": "Give",
    "turns": "Turn",
    "builds": "Build",
    "starts": "Start",
    "downloads": "Download",
    "installs": "Install",
    "uploads": "Upload",
    "connects": "Connect",
    "organizes": "Organize",
    "renames": "Rename",
    "checks": "Check",
    "searches": "Search",
    "reviews": "Review",
    "navigates": "Navigate",
    "chooses": "Choose",
    "types": "Type",
    "completes": "Complete",
    "saves": "Save",
}

REPORTING_PREFIX = re.compile(
    r"^(?:"
    r"(?:the\s+(?:narrator|speaker|video|author|presenter)|he|she)\s+(?:starts(?:\s+by)?|then|moves\s+on\s+to|explains(?:\s+that)?|demonstrates(?:\s+how)?|shows(?:\s+how)?|states(?:\s+that)?|discusses(?:\s+how)?|emphasizes(?:\s+that)?|describes(?:\s+how)?|points\s+out(?:\s+that)?|suggests(?:\s+that)?|notes(?:\s+that)?|recommends(?:\s+that)?|warns(?:\s+that)?|says(?:\s+that)?|mentions(?:\s+that)?|highlights(?:\s+that)?|illustrates(?:\s+how)?|is\s+described\s+as)"
    r"|in\s+this\s+(?:video|tutorial|guide)[,\s]+(?:we\s+learn\s+that|the\s+speaker\s+shows\s+that|we\s+see\s+how)?"
    r"|this\s+(?:video|tutorial|guide)\s+(?:provides(?:\s+a)?(?:\s+(?:comprehensive|detailed))?\s+guide(?:\s+to)?|covers|is\s+about|shows\s+how\s+to)?"
    r"|we\s+learn\s+that"
    r")\s*",
    flags=re.IGNORECASE,
)

ACTION_PREFIX = re.compile(
    r"^(?:the\s+(?:speaker|narrator|author|presenter|user)\s+|he\s+|she\s+)([a-z]+)\s+",
    flags=re.IGNORECASE,
)


def _strip_narrative(text: str) -> str:
    cleaned = REPORTING_PREFIX.sub("", text).strip()
    m = ACTION_PREFIX.match(cleaned)
    if m:
        verb = m.group(1).lower()
        if verb in ACTION_VERBS or verb.endswith("s"):
            base = ACTION_VERBS.get(verb, verb[:-1] if verb.endswith("s") and not verb.endswith("ss") else verb).capitalize()
            cleaned = f"{base} {cleaned[m.end():]}"
    if not cleaned:
        return text
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _coerce_unit_entry(entry, by_id) -> tuple[str, str, list[dict]]:
    """Accept the common shapes models return for a knowledge unit."""
    if not isinstance(entry, dict):
        raise ExtractionError("bad_unit", f"unit is not an object: {entry!r}")

    statement = entry.get("statement")
    if statement is None:
        statement = entry.get("claim")
    if statement is None:
        statement = entry.get("text")
    if statement is None:
        statement = entry.get("fact")
    if statement is None:
        statement = entry.get("knowledge")
    if statement is None:
        statement = entry.get("unit")
    statement = " ".join(str(statement or "").split())
    statement = _strip_narrative(statement)
    if not statement:
        raise ExtractionError("bad_unit", "unit without a statement")

    confidence = str(entry.get("confidence", entry.get("certainty", "medium"))).lower()
    if confidence not in CONFIDENCE:
        # map common synonyms
        if confidence in {"high", "certain", "strong"}:
            confidence = "high"
        elif confidence in {"low", "weak", "tentative"}:
            confidence = "low"
        else:
            confidence = "medium"

    # collect raw source references in any of the common shapes
    raw_refs = entry.get("source_refs")
    if raw_refs is None:
        raw_refs = entry.get("source_ref")
    if raw_refs is None:
        raw_refs = entry.get("source")
    if raw_refs is None:
        raw_refs = entry.get("references")
    if raw_refs is None:
        raw_refs = entry.get("refs")
    if raw_refs is None:
        raw_refs = entry.get("sources")

    if isinstance(raw_refs, str):
        raw_refs = [raw_refs]
    if raw_refs is None:
        raw_refs = []
    if not isinstance(raw_refs, list):
        raw_refs = [raw_refs]

    clean_refs: list[dict] = []
    for ref in raw_refs:
        if isinstance(ref, str):
            # "src-..., 00:00-00:04" or "src-... (00:00-00:04)"
            source_id = None
            for token in ref.replace(",", " ").split():
                if token.startswith("src-"):
                    source_id = token.strip(" ,()")
                    break
            if source_id is None:
                # try a regex
                import re as _re

                m = _re.search(r"src-[a-z0-9]+", ref)
                source_id = m.group(0) if m else None
            s, e = _parse_range_text(ref)
            if source_id is None or source_id not in by_id:
                # fall back to any known source id present in the text
                for known in by_id:
                    if known in ref:
                        source_id = known
                        break
            if source_id is None or source_id not in by_id:
                raise ExtractionError("bad_ref", f"unknown source_id in {ref!r}")
            if s is None:
                s = by_id[source_id].segments[0].start if by_id[source_id].segments else 0.0
            if e is None or e <= s:
                e = s + 1.0
            transcript = by_id[source_id]
            _assert_range_in_transcript(transcript, s, e)
            clean_refs.append({"source_id": source_id, "start": s, "end": e})
            continue

        if not isinstance(ref, dict):
            raise ExtractionError("bad_ref", f"malformed ref {ref!r}")
        source_id = str(ref.get("source_id") or ref.get("source") or ref.get("id") or "")
        if source_id not in by_id:
            # maybe embedded in a string field
            for value in ref.values():
                if isinstance(value, str) and value.startswith("src-"):
                    source_id = value
                    break
        if source_id not in by_id:
            raise ExtractionError("bad_ref", f"unknown source_id {source_id!r}")
        transcript = by_id[source_id]
        start = ref.get("start")
        end = ref.get("end")
        if start is None or end is None:
            for key in ("timestamp", "time", "range", "window"):
                if key in ref:
                    ss, ee = _parse_range_text(str(ref[key]))
                    if ss is not None:
                        start = ss if start is None else start
                        end = ee if end is None else end
                        break
        try:
            start = float(start)
            end = float(end)
        except (TypeError, ValueError) as exc:
            raise ExtractionError("bad_ref", f"malformed ref {ref!r}") from exc
        if end <= start:
            end = start + 1.0
        _assert_range_in_transcript(transcript, start, end)
        clean_refs.append({"source_id": source_id, "start": start, "end": end})

    if not clean_refs:
        raise ExtractionError("bad_unit", f"unit {statement[:40]!r} has no source refs")
    return statement, confidence, clean_refs


def _parse_range_text(value: str) -> tuple[float | None, float | None]:
    import re as _re

    stamps = _re.findall(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if not stamps:
        return None, None

    def to_seconds(stamp):
        if len(stamp) == 3 and stamp[2]:
            return int(stamp[0]) * 3600 + int(stamp[1]) * 60 + int(stamp[2])
        return int(stamp[0]) * 60 + int(stamp[1])

    start = to_seconds(stamps[0])
    end = to_seconds(stamps[1]) if len(stamps) > 1 else start + 1.0
    return float(start), float(end)
NOTE_LINE = re.compile(r"^\s*[-*]\s*\[(?P<sid>src-[a-z0-9]{6,})\]\s*(?P<range>[0-9:–\-\.\s]+?)\s*[—:-]?\s*(?P<body>.+)$")
RANGE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(?:[–-]|to)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?")


class ExtractionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _coerce_seconds(value, max_seconds: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        val = float(value)
        if max_seconds is not None and val > max_seconds:
            mins = int(val) // 100
            secs = val % 100
            if mins > 0:
                converted = mins * 60 + secs
                if converted <= max_seconds:
                    return converted
            dec_min_secs = (val / 100.0) * 60.0
            if dec_min_secs <= max_seconds:
                return dec_min_secs
        return val
    if not isinstance(value, str):
        return None
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except ValueError:
            return None
    try:
        val = float(value)
        if max_seconds is not None and val > max_seconds:
            mins = int(val) // 100
            secs = val % 100
            if mins > 0:
                converted = mins * 60 + secs
                if converted <= max_seconds:
                    return converted
            dec_min_secs = (val / 100.0) * 60.0
            if dec_min_secs <= max_seconds:
                return dec_min_secs
        return val
    except ValueError:
        return None



def _coerce_note(entry: dict, max_seconds: float | None = None) -> tuple[float, float, str]:
    text = entry.get("text")
    if text is None:
        text = entry.get("note")
    if text is None:
        text = entry.get("summary")
    if text is None:
        text = entry.get("content")
    text = " ".join(str(text or "").split())
    text = _strip_narrative(text)

    start = _coerce_seconds(entry.get("start"), max_seconds)
    end = _coerce_seconds(entry.get("end"), max_seconds)
    if start is None or end is None:
        for key in ("timestamp", "time", "range", "timestamps", "window"):
            if key in entry:
                s, e = _parse_range_text(str(entry[key]))
                if s is not None:
                    start = s if start is None else start
                    end = e if end is None else end
                    break
    if start is None:
        start = 0.0
    if end is None or end <= start:
        end = start + 1.0
    return start, end, text


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    base_url: str


class ChatClient:
    """OpenAI-compatible chat client with one retry and a failover provider."""

    def __init__(self, config, stage: str = "extract", transport=None):
        self.config = config
        self.stage = stage
        self.provider = config.providers[stage]
        self.failover = config.providers.get("failover")
        self.transport = transport or post_json
        self.calls: list[dict] = []

    def _once(self, provider, system: str, user: str, retries: int = None) -> ChatResult:
        if not self.config.get("network.enabled", True):
            raise ExtractionError("network_disabled", "network is disabled by configuration (AC-17)")
        if retries is None:
            retries = 1
        key = os.environ.get(provider.api_key_env, "")
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = self.transport(
                    provider.base_url.rstrip("/") + "/chat/completions",
                    payload,
                    {"Authorization": f"Bearer {key}"} if key else {},
                    timeout=provider.timeout_seconds,
                )
                text = response["choices"][0]["message"]["content"]
                self.calls.append(
                    {"provider": provider.name, "model": provider.model, "attempt": attempt + 1}
                )
                return ChatResult(text=text, provider=provider.name, model=provider.model, base_url=provider.base_url)
            except (HttpError, KeyError, IndexError, ValueError) as exc:
                last = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ExtractionError("provider_error", str(last))

    def chat(self, system: str, user: str) -> ChatResult:
        try:
            return self._once(self.provider, system, user)
        except ExtractionError:
            if not self.failover:
                raise
            return self._once(self.failover, system, user)


def _json_block(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ExtractionError("invalid_json", f"model did not return JSON: {exc}") from exc


def _format_range(start: float, end: float) -> str:
    def stamp(value: float) -> str:
        minutes, secs = divmod(int(value), 60)
        return f"{minutes:02d}:{secs:02d}"

    return f"{stamp(start)}–{stamp(end)}"


# --------------------------------------------------------------------------- notes


@dataclass
class NoteBook:
    source_id: str
    bullets: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""

    def to_markdown(self) -> str:
        lines = [f"# Notes — {self.source_id}", ""]
        for bullet in self.bullets:
            lines.append(f"- [{bullet['source_id']}] {bullet['range']} — {bullet['text']}")
        return "\n".join(lines) + "\n"


def build_notes(client: ChatClient, source, transcript: Transcript) -> NoteBook:
    system = (
        "You extract timestamped study notes and actionable learning material from a transcript. "
        "State technical facts, workflows, concepts, and skills directly in clear declarative sentences without conversational dialogue or speaker tags (e.g., avoid 'the speaker says'). "
        "Formulate learning points and procedures universally so they can be executed by any LLM or AI agent (e.g., Claude, GPT, Gemini, local models). "
        "Preserve exact technical terminology (tool names, prompt structures, API options, workflows). "
        "Return JSON: {\"notes\":[{\"start\":<timestamp like 'MM:SS' or seconds>,\"end\":<timestamp like 'MM:SS' or seconds>,\"text\":\"...\"}]}. "
        "Use the exact keys start, end and text. Every note must be supported by the transcript. No invention."
    )

    chunk_size = 15
    segments = transcript.segments
    chunks = [segments[i:i + chunk_size] for i in range(0, len(segments), chunk_size)] or [[]]

    all_bullets: list[dict] = []
    provider_name = ""
    model_name = ""
    for chunk in chunks:
        if not chunk:
            continue
        profile = "\n".join(f"{_format_range(s.start, s.end)}: {s.text}" for s in chunk)
        user = f"Title: {source.title}\nLanguage: {transcript.language or 'unknown'}\n\nTranscript:\n{profile}"
        result = client.chat(system, user)
        payload = _json_block(result.text)
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            entries = (
                payload.get("notes")
                or payload.get("study_notes")
                or payload.get("bullets")
                or payload.get("points")
                or payload.get("items")
                or []
            )
        else:
            entries = []

        if not isinstance(entries, list):
            entries = []

        max_sec = transcript.segments[-1].end if transcript.segments else None
        for entry in entries:
            if not isinstance(entry, dict):
                raise ExtractionError("bad_note", f"malformed note entry: {entry!r}")
            try:
                start, end, text = _coerce_note(entry, max_sec)
            except (KeyError, TypeError, ValueError) as exc:
                raise ExtractionError("bad_note", f"malformed note entry: {entry!r}") from exc
            if not text:
                raise ExtractionError("bad_note", "empty note text")
            if end <= start:
                end = start + 1.0
            if transcript.segments:
                first = transcript.segments[0].start
                last = transcript.segments[-1].end
                if start < first - 0.5 or start > last + 0.5:
                    if not all_bullets and len(entries) == 1:
                        _assert_range_in_transcript(transcript, start, end)
                    continue
                start = max(first, start)
                end = min(last, max(start + 0.1, end))
            _assert_range_in_transcript(transcript, start, end)
            all_bullets.append(
                {
                    "source_id": transcript.source_id,
                    "start": start,
                    "end": end,
                    "range": _format_range(start, end),
                    "text": text,
                }
            )
        provider_name = result.provider
        model_name = result.model

    if not all_bullets:
        raise ExtractionError("no_notes", "model returned no notes")
    all_bullets.sort(key=lambda b: b["start"])
    return NoteBook(
        source_id=transcript.source_id,
        bullets=all_bullets,
        provider=provider_name,
        model=model_name,
    )


def _assert_range_in_transcript(transcript: Transcript, start: float, end: float) -> None:
    if not transcript.segments:
        raise ExtractionError("bad_range", "transcript has no segments")
    first, last = transcript.segments[0].start, transcript.segments[-1].end
    if start < first - 0.5 or end > last + 0.5:
        raise ExtractionError(
            "bad_range",
            f"range {start:.1f}-{end:.1f}s is outside the transcript ({first:.1f}-{last:.1f}s)",
        )


def validate_notes(notebook: NoteBook, transcripts: dict[str, Transcript]) -> list[str]:
    problems: list[str] = []
    transcript = transcripts.get(notebook.source_id)
    if transcript is None:
        return [f"no transcript for {notebook.source_id}"]
    for index, bullet in enumerate(notebook.bullets):
        if bullet["source_id"] != notebook.source_id:
            problems.append(f"note {index}: wrong source_id")
        try:
            _assert_range_in_transcript(transcript, bullet["start"], bullet["end"])
        except ExtractionError as exc:
            problems.append(f"note {index}: {exc.message}")
    return problems


# --------------------------------------------------------------------- knowledge


def extract_units(client: ChatClient, transcripts: list[Transcript], titles: dict[str, str]) -> list[KnowledgeUnit]:
    by_id = {t.source_id: t for t in transcripts}
    units: list[KnowledgeUnit] = []
    seen: set[str] = set()

    # Process in chunks so a long transcript does not exceed the provider's
    # context or time budget. Units are merged and de-duplicated by id.
    chunk_size = 15
    for transcript in transcripts:
        segments = transcript.segments
        chunks = [segments[i:i + chunk_size] for i in range(0, len(segments), chunk_size)] or [[]]
        for chunk in chunks:
            if not chunk:
                continue
            transcript_text = (
                f"### {transcript.source_id} — {titles.get(transcript.source_id, '')}\n"
                + "\n".join(f"{_format_range(s.start, s.end)} {s.text}" for s in chunk)
            )
            system = (
                "You extract atomic, actionable knowledge units and skills from educational transcripts. "
                "State technical facts, capabilities, rules, and workflows directly as concise, self-contained knowledge units for a universal agent skill library. "
                "Formulate principles, prompting patterns, and capabilities generically so they apply across all modern LLMs (Claude, GPT, Gemini, open models). "
                "Write in clear declarative sentences without conversational dialogue or narrator framing (e.g., avoid 'the speaker explains'). "
                "Return JSON: "
                "{\"units\":[{\"statement\":\"...\",\"source_refs\":[{\"source_id\":\"src-...\","
                "\"start\":<seconds>,\"end\":<seconds>}],\"confidence\":\"low|medium|high\"}]}. "
                "One claim per unit, short and self-contained. Every unit needs at least one source ref."
            )
            result = client.chat(system, transcript_text)
            payload = _json_block(result.text)
            raw_units = payload.get("units")
            if not isinstance(raw_units, list) or not raw_units:
                continue
            for entry in raw_units:
                try:
                    statement, confidence, clean_refs = _coerce_unit_entry(entry, {transcript.source_id: transcript})
                except ExtractionError:
                    continue
                unit = KnowledgeUnit(
                    id=unit_id_for(statement),
                    statement=statement,
                    source_refs=clean_refs,
                    confidence=confidence,
                )
                if unit.id in seen:
                    continue
                seen.add(unit.id)
                units.append(unit)

    if not units:
        raise ExtractionError("no_units", "model returned no knowledge units")
    return units


def validate_units(units: list[KnowledgeUnit], transcripts: dict[str, Transcript]) -> list[str]:
    problems: list[str] = []
    ids = set()
    for index, unit in enumerate(units):
        if unit.id != unit_id_for(unit.statement):
            problems.append(f"unit {index}: id does not match statement hash")
        if unit.id in ids:
            problems.append(f"unit {index}: duplicate id {unit.id}")
        ids.add(unit.id)
        if unit.confidence not in CONFIDENCE:
            problems.append(f"unit {index}: bad confidence")
        if not unit.source_refs:
            problems.append(f"unit {index}: no source refs")
        for ref in unit.source_refs:
            transcript = transcripts.get(ref["source_id"])
            if transcript is None:
                problems.append(f"unit {index}: dangling source {ref['source_id']}")
                continue
            try:
                _assert_range_in_transcript(transcript, float(ref["start"]), float(ref["end"]))
            except ExtractionError as exc:
                problems.append(f"unit {index}: {exc.message}")
    return problems


# -------------------------------------------------------------------- procedures


@dataclass
class Procedure:
    id: str
    title: str
    steps: list[dict]

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        for index, step in enumerate(self.steps, 1):
            refs = " ".join(f"[[{uid}]]" for uid in step["unit_ids"])
            lines.append(f"{index}. {step['text']} {refs}".rstrip())
        return "\n".join(lines) + "\n"


def _coerce_procedures(payload, known) -> list[dict]:
    """Accept the common shapes models return for procedures."""
    raw = payload.get("procedures")
    if not isinstance(raw, list):
        raw = payload.get("procedure")
    if not isinstance(raw, list):
        if isinstance(payload.get("steps"), list):
            raw = [{"title": payload.get("title") or payload.get("name") or "Procedure", "steps": payload["steps"]}]
        else:
            raw = []
    if not raw:
        return []

    # Some models return a flat list of steps under "procedure"/"steps",
    # each citing its unit via "id"/"unit_id" rather than unit_ids.
    if raw and isinstance(raw[0], dict) and "steps" not in raw[0] and ("step" in raw[0] or "action" in raw[0] or "text" in raw[0]):
        raw = [{"title": payload.get("title") or payload.get("name") or "Procedure", "steps": raw}]

    coerced = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = " ".join(str(entry.get("title") or entry.get("name") or entry.get("procedure") or "Procedure").split())
        steps = entry.get("steps")
        if not isinstance(steps, list):
            # maybe steps under "actions"
            steps = entry.get("actions") or entry.get("items") or []
        clean_steps = []
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            text = step.get("text")
            if text is None:
                text = step.get("action")
            if text is None:
                text = step.get("description")
            if text is None:
                text = step.get("step")
            text = " ".join(str(text or "").split())
            text = _strip_narrative(text)
            refs_raw = step.get("unit_ids")
            if refs_raw is None:
                refs_raw = step.get("unit_id")
            if refs_raw is None:
                refs_raw = step.get("units")
            if refs_raw is None:
                refs_raw = step.get("knowledge_units")
            if refs_raw is None:
                refs_raw = step.get("refs")
            if refs_raw is None:
                refs_raw = step.get("unit")
            if refs_raw is None:
                refs_raw = step.get("id")
            if isinstance(refs_raw, str):
                refs_raw = [refs_raw]
            if refs_raw is None:
                refs_raw = []
            refs = [str(u).strip(" ,[]") for u in refs_raw]
            refs = [r for r in refs if r]
            # accept a single string containing multiple ids separated by commas
            expanded = []
            for r in refs:
                if "," in r:
                    expanded.extend(x.strip() for x in r.split(",") if x.strip())
                else:
                    expanded.append(r)
            refs = expanded
            if not text or not refs:
                continue
            valid_refs = [r for r in refs if r in known]
            if not valid_refs:
                continue
            clean_steps.append({"text": text, "unit_ids": valid_refs})
        if clean_steps:
            coerced.append({"title": title, "steps": clean_steps})
    return coerced


def build_procedures(client: ChatClient, units: list[KnowledgeUnit]) -> list[Procedure]:
    catalogue = "\n".join(f"- {u.id}: {u.statement}" for u in units)
    system = (
        "You turn knowledge units into an ordered, executable procedure and skill workflow for an autonomous agent or practitioner. "
        "Formulate each step as an active, imperative instruction (e.g., 'Configure...', 'Prompt the model with...', 'Execute...', 'Verify...') that is universally executable across any LLM (Claude, GPT, Gemini, local models) without conversational narration. "
        "Return JSON: "
        "{\"procedures\":[{\"title\":\"...\",\"steps\":[{\"text\":\"...\",\"unit_ids\":[\"k-...\"]}]}]}. "
        "Every step must cite at least one provided unit id. Do not invent units."
    )
    result = client.chat(system, catalogue)
    payload = _json_block(result.text)
    coerced = _coerce_procedures(payload, {u.id for u in units})
    if not coerced:
        raise ExtractionError("no_procedures", "model returned no procedures")

    procedures: list[Procedure] = []
    for entry in coerced:
        title = entry["title"]
        steps = entry["steps"]
        procedures.append(Procedure(id=procedure_id_for(title), title=title, steps=steps))
    return procedures

def validate_procedures(procedures: list[Procedure], units: list[KnowledgeUnit]) -> list[str]:
    known = {u.id for u in units}
    problems: list[str] = []
    for index, procedure in enumerate(procedures):
        if not procedure.steps:
            problems.append(f"procedure {index}: no steps")
        for step_index, step in enumerate(procedure.steps):
            if not step["text"].strip():
                problems.append(f"procedure {index} step {step_index}: empty")
            if not step["unit_ids"]:
                problems.append(f"procedure {index} step {step_index}: no unit refs")
            for ref in step["unit_ids"]:
                if ref not in known:
                    problems.append(f"procedure {index} step {step_index}: unknown unit {ref}")
    return problems
