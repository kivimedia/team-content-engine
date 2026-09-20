"""Moment extraction: one subscription LLM job per source (per chunk for long meetings).

Returned moments are validated against the source before they are stored: spans must
lie inside the source's turn range and the speaker must actually speak in that span;
code refs must name a SHA and a path that exist in the group. Invalid moments are
dropped with a recorded reason. LLMUnavailable is surfaced in the run ledger, never
swallowed and never replaced by a fabricated result.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import tce.llm as llm
from tce.evidence.collect import FATHOM_KIND, GITHUB_KIND, RunLedger
from tce.evidence.common import stable_hash, to_db
from tce.models.editorial import CLAIM_TYPES, EvidenceMoment, EvidenceSource
from tce.settings import settings

logger = structlog.get_logger()

EXTRACTION_RUN_KIND = "moment_extraction"
PROMPT_VERSION = "evidence_moments.v1"
JOB_TYPE = "evidence_moments"
AGENT_NAME = "evidence_moment_extractor"
CHUNK_CHARS = 24000
CHUNK_OVERLAP_TURNS = 8
SPAN_TOLERANCE_S = 1.0
_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1, "unknown": 0}

SYSTEM_PROMPT = """You extract citable evidence moments for Ziv's editorial system.

Ziv is the account owner. His audience is owners of small service businesses: coaches
first, event-business owners second.

Extract ONLY moments where Ziv teaches, decides, diagnoses or demonstrates something that
would be useful to that audience. Skip small talk, logistics, other people's monologues and
anything that is not Ziv's own reasoning or action. Returning zero moments is correct when
nothing qualifies.

Rules:
- Spans: use the exact start and end seconds of the numbered turns you were given. Never
  invent times. The speaker must be the exact speaker label shown on those turns.
- excerpt_private: the exact words from the turns (private, editor-only).
- lesson_summary: the lesson in public-safe words. No client or company names, no customer
  words, no health details, no money figures, no credentials, no identifying detail.
- claim_type: quoted | paraphrased | inferred | demonstrated | measured.
  A proposal, plan or intention is never "demonstrated" or "measured".
  Merged code is at most "demonstrated"; code never proves a business outcome.
  "measured" only when the source states an actual observed measurement.
- Humor, sarcasm or a throwaway remark on its own is not advice. Do not extract it.
- Language: if the turns are Hebrew and your lesson is English, set translation_label to
  "English adaptation from Hebrew". Set language_uncertain true when the language or the
  speaker attribution is unclear (mixed-script turns, low speaker confidence).
- sensitivity_flags: any of client_identity, customer_words, health, money, credential,
  personal, legal that apply to the excerpt.
Return JSON matching the schema, nothing else."""

_MOMENT_COMMON = {
    "excerpt_private": {"type": "string"},
    "context_private": {"type": ["string", "null"]},
    "lesson_summary": {"type": "string"},
    "claim_type": {"type": "string", "enum": list(CLAIM_TYPES)},
    "language": {"type": ["string", "null"]},
    "translation_label": {"type": ["string", "null"]},
    "language_uncertain": {"type": "boolean"},
    "sensitivity_flags": {"type": "array", "items": {"type": "string"}},
}

MEETING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["moments"],
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "span_start_s", "span_end_s", "speaker", "excerpt_private",
                    "lesson_summary", "claim_type",
                ],
                "properties": {
                    "span_start_s": {"type": "number"},
                    "span_end_s": {"type": "number"},
                    "speaker": {"type": "string"},
                    **_MOMENT_COMMON,
                },
            },
        }
    },
}

COMMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["moments"],
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code_refs", "excerpt_private", "lesson_summary", "claim_type"],
                "properties": {
                    "code_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["sha", "path"],
                            "properties": {"sha": {"type": "string"}, "path": {"type": "string"}},
                        },
                    },
                    **_MOMENT_COMMON,
                },
            },
        }
    },
}


def _fmt_ts(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d} ({seconds:g}s)"


def render_turn(turn: dict[str, Any]) -> str:
    return (
        f"[{turn['index']}] {_fmt_ts(turn.get('start_s'))} - {_fmt_ts(turn.get('end_s'))} | "
        f"speaker: {turn.get('speaker') or 'UNKNOWN'} "
        f"(confidence {turn.get('speaker_confidence')}; language {turn.get('language')}"
        f"{', uncertain' if turn.get('language_uncertain') else ''}) | {turn.get('text')}"
    )


def chunk_meeting(
    turns: list[dict[str, Any]],
    max_chars: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP_TURNS,
) -> list[list[dict[str, Any]]]:
    """Consecutive turn windows under `max_chars`, overlapping by `overlap` turns."""
    if not turns:
        return []
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(turns):
        size = 0
        end = start
        while end < len(turns):
            size += len(render_turn(turns[end])) + 1
            if size > max_chars and end > start:
                break
            end += 1
        chunks.append(turns[start:end])
        if end >= len(turns):
            break
        start = max(start + 1, end - overlap)
    return chunks


def render_commit_group(payload: dict[str, Any]) -> str:
    lines = [f"Repository: {payload.get('repo')}"]
    for c in payload.get("commits", []):
        lines.append(f"\n## Commit {c['sha']} at {c.get('committed_at')}")
        if c.get("reverts"):
            lines.append(f"Reverts: {', '.join(c['reverts'])}")
        if c.get("reverted_by"):
            lines.append(f"Reverted by: {', '.join(c['reverted_by'])}")
        lines.append("Message:\n" + (c.get("message") or ""))
        lines.append("Files at this SHA:")
        for f in c.get("files", []):
            lines.append(f"- {f['path']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})")
        for f in c.get("files", []):
            if f.get("patch_excluded"):
                lines.append(f"\n### Patch {f['path']} not shown: {f['patch_excluded']}")
            elif f.get("patch_excerpt"):
                trunc = " (excerpt, truncated)" if f.get("patch_truncated") else ""
                lines.append(f"\n### Patch {f['path']}{trunc}\n{f['patch_excerpt']}")
    return "\n".join(lines)


def _structured(result: Any) -> dict[str, Any]:
    if isinstance(result.structured, dict):
        return result.structured
    text = (result.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM result is not a JSON object")
    return data


def _worst_confidence(turns: list[dict[str, Any]]) -> str:
    if not turns:
        return "unknown"
    return min(
        (t.get("speaker_confidence") or "unknown" for t in turns),
        key=lambda c: _CONFIDENCE_ORDER.get(c, 0),
    )



def _norm_words(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def _attribution_error(
    raw: dict[str, Any],
    speaker_turns: list[dict[str, Any]],
    in_span: list[dict[str, Any]],
    speaker: str,
) -> str | None:
    """Reject excerpts that are really another participant's words.

    A speaker merely talking somewhere in the span is not proof that the quoted
    words are theirs. Quotes must appear in the attributed speaker's own turns;
    paraphrases must overlap more with the speaker than with anyone else.
    """
    excerpt = _norm_words(raw.get("excerpt_private") or "")
    if not excerpt:
        return None
    own = _norm_words(" ".join(t.get("text") or "" for t in speaker_turns))
    others = _norm_words(
        " ".join(t.get("text") or "" for t in in_span if t.get("speaker") != speaker)
    )
    phrase = " ".join(excerpt)
    in_own = phrase in " ".join(own)
    in_others = phrase in " ".join(others)
    if raw.get("claim_type") == "quoted":
        if in_own:
            return None
        if in_others:
            return "quoted excerpt belongs to another speaker"
        return "quoted excerpt not found in the attributed speaker's words"
    if in_others and not in_own:
        return "excerpt belongs to another speaker"
    vocab = set(excerpt)
    own_overlap = len(vocab & set(own)) / len(vocab)
    other_overlap = len(vocab & set(others)) / len(vocab)
    if other_overlap >= 0.6 and other_overlap > own_overlap:
        return "excerpt matches another speaker more than the attributed speaker"
    return None


def validate_meeting_moment(
    raw: dict[str, Any], turns: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (moment_fields, None) or (None, drop_reason)."""
    timed = [t for t in turns if t.get("start_s") is not None]
    if not timed:
        return None, "source has no timed turns"
    lo = min(t["start_s"] for t in timed)
    hi = max((t.get("end_s") if t.get("end_s") is not None else t["start_s"]) for t in timed)
    try:
        start = float(raw.get("span_start_s"))
        end = float(raw.get("span_end_s"))
    except (TypeError, ValueError):
        return None, "span is not numeric"
    if end < start:
        return None, "span end before span start"
    if start < lo - SPAN_TOLERANCE_S or end > hi + SPAN_TOLERANCE_S:
        return None, "span outside the source turn range"
    speaker = (raw.get("speaker") or "").strip()
    speakers = {t.get("speaker") for t in turns if t.get("speaker")}
    if not speaker or speaker not in speakers:
        return None, "speaker does not exist in the source"
    in_span = [
        t for t in timed
        if t["start_s"] <= end + SPAN_TOLERANCE_S
        and (t.get("end_s") if t.get("end_s") is not None else t["start_s"])
        >= start - SPAN_TOLERANCE_S
    ]
    speaker_turns = [t for t in in_span if t.get("speaker") == speaker]
    if not speaker_turns:
        return None, "speaker does not speak inside the span"
    attribution_error = _attribution_error(raw, speaker_turns, in_span, speaker)
    if attribution_error:
        return None, attribution_error
    common = _common_fields(raw)
    if isinstance(common, str):
        return None, common
    common.update({
        "span_start_s": start,
        "span_end_s": end,
        "speaker": speaker,
        "speaker_confidence": _worst_confidence(speaker_turns),
        "language_uncertain": bool(raw.get("language_uncertain"))
        or any(t.get("language_uncertain") for t in speaker_turns),
        "code_refs": None,
    })
    if not common.get("language"):
        langs = [t.get("language") for t in speaker_turns if t.get("language")]
        common["language"] = max(set(langs), key=langs.count) if langs else None
    return common, None


def validate_commit_moment(
    raw: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    commits = {c["sha"]: c for c in payload.get("commits", [])}
    refs_in = raw.get("code_refs") or []
    if not refs_in:
        return None, "no code refs"
    refs = []
    for ref in refs_in:
        sha = (ref or {}).get("sha") or ""
        matches = [s for s in commits if s == sha or (len(sha) >= 7 and s.startswith(sha))]
        if len(matches) != 1:
            return None, "code ref sha is not in the group"
        commit = commits[matches[0]]
        path = ref.get("path")
        file = next((f for f in commit.get("files", []) if f["path"] == path), None)
        if file is None:
            return None, "code ref path is not in that commit"
        refs.append({
            "repo": payload.get("repo"),
            "sha": commit["sha"],
            "path": path,
            "url_at_sha": file["blob_url_at_sha"],
        })
    common = _common_fields(raw)
    if isinstance(common, str):
        return None, common
    if common["claim_type"] == "measured":
        return None, "code cannot support a measured claim"
    common.update({
        "span_start_s": None,
        "span_end_s": None,
        "speaker": None,
        "speaker_confidence": "unknown",
        "language_uncertain": bool(raw.get("language_uncertain")),
        "code_refs": refs,
    })
    return common, None


def _common_fields(raw: dict[str, Any]) -> dict[str, Any] | str:
    claim = raw.get("claim_type")
    if claim not in CLAIM_TYPES:
        return "invalid claim_type"
    excerpt = (raw.get("excerpt_private") or "").strip()
    lesson = (raw.get("lesson_summary") or "").strip()
    if not excerpt:
        return "empty excerpt"
    if not lesson:
        return "empty lesson summary"
    flags = raw.get("sensitivity_flags") or []
    return {
        "excerpt_private": excerpt,
        "context_private": raw.get("context_private"),
        "lesson_summary": lesson,
        "claim_type": claim,
        "language": raw.get("language"),
        "translation_label": raw.get("translation_label"),
        "sensitivity_flags": [str(f) for f in flags if isinstance(f, str | int)],
    }


def _jobs_for_source(source: EvidenceSource) -> list[tuple[str, dict[str, Any]]]:
    """(user_message, schema) per job."""
    payload = source.payload_private or {}
    if source.source_kind == FATHOM_KIND:
        turns = payload.get("turns") or []
        chunks = chunk_meeting(turns)
        jobs = []
        for n, chunk in enumerate(chunks, start=1):
            header = (
                f"Meeting transcript, part {n} of {len(chunks)} "
                f"(turns {chunk[0]['index']}-{chunk[-1]['index']} of {len(turns)}). "
                f"Recording language: {payload.get('language')}.\n"
                "Each line: [turn] start - end | speaker (confidence; language) | text\n\n"
            )
            jobs.append((header + "\n".join(render_turn(t) for t in chunk), MEETING_SCHEMA))
        return jobs
    if source.source_kind == GITHUB_KIND:
        return [(
            "Group of related commits. Each file path is exact at the given SHA.\n\n"
            + render_commit_group(payload),
            COMMIT_SCHEMA,
        )]
    return []


async def sources_needing_extraction(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    window_start: datetime | None,
    window_end: datetime | None,
    source_kinds: list[str] | None = None,
    source_ids: list[uuid.UUID] | None = None,
) -> list[EvidenceSource]:
    stmt = select(EvidenceSource).where(
        EvidenceSource.workspace_id == workspace_id,
        EvidenceSource.fetch_status.in_(("ok", "partial")),
    )
    if source_kinds:
        stmt = stmt.where(EvidenceSource.source_kind.in_(source_kinds))
    if source_ids:
        stmt = stmt.where(EvidenceSource.id.in_(source_ids))
    if window_start is not None:
        stmt = stmt.where(EvidenceSource.occurred_at >= to_db(window_start))
    if window_end is not None:
        stmt = stmt.where(EvidenceSource.occurred_at < to_db(window_end))
    sources = (await session.execute(stmt.order_by(EvidenceSource.occurred_at))).scalars().all()
    active = (
        await session.execute(
            select(EvidenceMoment.source_id, EvidenceMoment.source_version_hash).where(
                EvidenceMoment.workspace_id == workspace_id,
                EvidenceMoment.status == "active",
            )
        )
    ).all()
    has_active = {(sid, h) for sid, h in active}
    out = []
    for s in sources:
        meta = s.meta or {}
        if (s.id, s.version_hash) in has_active:
            continue
        if meta.get("moments_extracted_for") == s.version_hash:
            continue
        out.append(s)
    return out


def skip_reason(source: EvidenceSource) -> str | None:
    meta = source.meta or {}
    if meta.get("exclude_reason"):
        return f"excluded group: {meta['exclude_reason']}"
    if source.source_kind == FATHOM_KIND and not (source.payload_private or {}).get("turns"):
        return "no transcript turns"
    return None


async def extract_moments(
    sessionmaker: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    *,
    run_id: uuid.UUID | None = None,
    wait_timeout_s: float | None = None,
    source_kinds: list[str] | None = None,
    source_ids: list[uuid.UUID] | None = None,
    concurrency: int | None = None,
) -> uuid.UUID:
    """Extract moments for every source lacking active moments for its current hash.

    `source_kinds` limits the run (e.g. meetings first); the rest stay pending.
    Up to `concurrency` sources wait on their subscription jobs at once (default
    settings.evidence_extract_concurrency). After the first LLM stop no new
    source starts; those are counted as not_started and a rerun picks them up.
    """
    if run_id is None:
        run_id = await RunLedger.create_run(
            sessionmaker, workspace_id, EXTRACTION_RUN_KIND,
            window_start or datetime(1970, 1, 1), window_end or datetime(2100, 1, 1),
        )
    ledger = RunLedger(sessionmaker, run_id)
    job_ids: list[str] = []
    width = max(1, concurrency or settings.evidence_extract_concurrency)
    try:
        async with sessionmaker() as session:
            sources = await sources_needing_extraction(
                session, workspace_id, window_start, window_end, source_kinds, source_ids
            )
        ledger.counts["sources"] = len(sources)
        await ledger.set_activity(f"Moment extraction: {len(sources)} sources need extraction")
        stopped: str | None = None
        started = 0
        finished = 0
        in_flight = 0
        gate = asyncio.Semaphore(width)

        async def extract_one(s_idx: int, source: EvidenceSource) -> None:
            nonlocal stopped, started, finished, in_flight
            skip = skip_reason(source)
            if skip:
                started += 1
                ledger.add_item(source.external_id, "excluded", skip, source_id=str(source.id))
                return
            async with gate:
                if stopped is not None:
                    return  # never started; counted as not_started below
                started += 1
                in_flight += 1
                try:
                    await _extract_source(s_idx, source)
                except Exception as exc:  # one source's failure is recorded, not fatal
                    reason = f"{type(exc).__name__}: {exc}"[:300]
                    ledger.add_item(
                        source.external_id, "failed", reason, source_id=str(source.id)
                    )
                    ledger.add_error(f"source:{source.id}", reason)
                finally:
                    in_flight -= 1
                    finished += 1

        async def _extract_source(s_idx: int, source: EvidenceSource) -> None:
            nonlocal stopped
            jobs = _jobs_for_source(source)
            raw_moments: list[dict[str, Any]] = []
            source_job_ids: list[str] = []
            unavailable: Exception | None = None
            for j_idx, (message, schema) in enumerate(jobs, start=1):
                await ledger.set_activity(
                    f"Moment extraction: {finished} of {len(sources)} sources done, "
                    f"{in_flight} in flight. Source {s_idx} ({source.source_kind}): "
                    f"waiting for LLM job {j_idx} of {len(jobs)}"
                )
                req = llm.LLMRequest(
                    job_type=JOB_TYPE,
                    agent_name=AGENT_NAME,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": message}],
                    output_schema=schema,
                    max_tokens=8000,
                    prompt_version=PROMPT_VERSION,
                    workspace_id=workspace_id,
                    run_id=run_id,
                )
                try:
                    result = await llm.complete(req, wait_timeout_s=wait_timeout_s)
                except llm.LLMUnavailable as exc:
                    unavailable = exc
                    break
                source_job_ids.append(str(result.job_id))
                job_ids.append(str(result.job_id))
                data = _structured(result)
                for m in data.get("moments") or []:
                    if isinstance(m, dict):
                        raw_moments.append({**m, "_job_id": str(result.job_id)})

            if unavailable is not None:
                exc = unavailable
                retry_at = getattr(exc, "retry_at", None)
                reason = f"LLM {exc.status}: {exc.detail}"[:300]
                ledger.add_item(
                    source.external_id, "unavailable", reason, source_id=str(source.id),
                    llm_job_id=str(exc.job_id) if exc.job_id else None,
                    retry_at=retry_at.isoformat() if retry_at else None,
                )
                ledger.add_error(f"source:{source.id}", reason)
                if stopped is None:  # the first stop reason wins; no new sources start
                    stopped = (
                        f"LLM {exc.status}"
                        + (f" (job {exc.job_id})" if exc.job_id else "")
                        + (f", retry at {retry_at.isoformat()}" if retry_at else "")
                    )
                return

            stored, dropped = await _store_moments(
                sessionmaker, workspace_id, source, raw_moments, source_job_ids
            )
            ledger.counts["moments_stored"] += stored
            ledger.counts["moments_dropped"] += len(dropped)
            ledger.add_item(
                source.external_id, "processed",
                f"{stored} moments stored, {len(dropped)} dropped",
                source_id=str(source.id), job_ids=source_job_ids,
                dropped=[d["reason"] for d in dropped],
            )

        await asyncio.gather(
            *(extract_one(i, s) for i, s in enumerate(sources, start=1))
        )
        if len(sources) - started:
            ledger.counts["not_started"] = len(sources) - started
        ledger.counts["llm_jobs"] = len(job_ids)
        await ledger.finish(pagination_finished=stopped is None, fatal=stopped)
    except Exception as exc:
        ledger.add_error("run", f"{type(exc).__name__}: {exc}"[:300])
        await ledger.finish(pagination_finished=False, fatal=type(exc).__name__)
    return run_id


async def _store_moments(
    sessionmaker: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    source: EvidenceSource,
    raw_moments: list[dict[str, Any]],
    job_ids: list[str],
) -> tuple[int, list[dict[str, Any]]]:
    payload = source.payload_private or {}
    turns = payload.get("turns") or []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    stored = 0
    async with sessionmaker() as session:
        row = await session.get(EvidenceSource, source.id)
        if row is None or row.workspace_id != workspace_id:
            return 0, [{"reason": "source disappeared"}]
        if row.version_hash != source.version_hash:
            return 0, [{"reason": "source changed during extraction"}]
        for i, raw in enumerate(raw_moments):
            if source.source_kind == FATHOM_KIND:
                fields, reason = validate_meeting_moment(raw, turns)
            else:
                fields, reason = validate_commit_moment(raw, payload)
            if fields is None:
                dropped.append({"index": i, "reason": reason})
                continue
            key = stable_hash([
                fields.get("span_start_s") and round(fields["span_start_s"]),
                fields.get("span_end_s") and round(fields["span_end_s"]),
                fields.get("speaker"),
                [(r["sha"], r["path"]) for r in fields.get("code_refs") or []],
                fields["excerpt_private"] if fields.get("code_refs") else None,
            ])
            if key in seen:
                dropped.append({"index": i, "reason": "duplicate from chunk overlap"})
                continue
            seen.add(key)
            session.add(EvidenceMoment(
                workspace_id=workspace_id,
                source_id=source.id,
                source_version_hash=source.version_hash,
                extraction_job_id=uuid.UUID(raw["_job_id"]),
                status="active",
                **fields,
            ))
            stored += 1
        row.meta = {
            **(row.meta or {}),
            "moments_extracted_for": source.version_hash,
            "extraction": {
                "prompt_version": PROMPT_VERSION,
                "job_ids": job_ids,
                "stored": stored,
                "dropped": dropped,
            },
        }
        await session.commit()
    return stored, dropped
