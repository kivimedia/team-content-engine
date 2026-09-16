"""Editorial selector: evidence moments -> ranked, gated topic candidates.

Pool: active moments of this workspace from the week, plus an evergreen reserve of
earlier moments no selected/recorded/published candidate has used yet. Sources that
are excluded, failed, unavailable, reverted or low-signal never enter the pool, and
neither do stale moments.

One subscription LLM job proposes candidates and explicit rejections. Code then
enforces what the model cannot be trusted to: all four gates with reasons, citations
that exist in this workspace's pool, no measured outcome without a measured moment,
uncertainty carried as public-safety notes, and no quota padding. Rejections are
persisted as `status=rejected, origin=selector_rejected` rows for later sampling.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce import llm as _llm
from tce.editorial.common import (
    ORIGIN_SELECTOR,
    ORIGIN_SELECTOR_REJECTED,
    SessionSource,
    candidate_to_json,
    coerce_uuid,
    open_session,
    week_bounds,
)
from tce.editorial.feedback import summarize_feedback
from tce.llm import LLMRequest, LLMUnavailable
from tce.models.editorial import (
    REJECTION_GATES,
    EvidenceMoment,
    EvidenceSource,
    TopicCandidate,
)
from tce.services.strategy_loader import load_effective_strategy

PROMPT_VERSION = "editorial_selection.v1"
JOB_TYPE = "editorial_selection"
AGENT_NAME = "editorial_selector"
MAX_CANDIDATES_CAP = 6
WEEK_POOL_LIMIT = 60
RESERVE_POOL_LIMIT = 30
EXCERPT_CHARS = 600

EXCLUDED_FETCH_STATUSES = ("excluded", "failed", "unavailable")
USED_STATUSES = ("selected", "recorded", "published")

CLAIM_SUPPORT = {
    "measured": 1.0,
    "demonstrated": 0.9,
    "quoted": 0.8,
    "paraphrased": 0.7,
    "inferred": 0.4,
}

# Outcome / result language. Advice in the imperative ("reduce your admin") is fine;
# stated results ("reduced admin by half", "doubled bookings", "30%") need a measured moment.
_OUTCOME_LANGUAGE = re.compile(
    r"\b(?:saved|increased|grew|doubled|tripled|boosted|reduced|cut\s+\w*\s*(?:by|in half)|"
    r"halved|improved\s+\w+\s+by|more\s+(?:clients|sales|bookings|leads|revenue|inquiries)|"
    r"fewer\s+(?:errors|no-shows|complaints|cancellations)|revenue|roi|return on investment|"
    r"conversion rate|\d+(?:\.\d+)?\s*(?:%|percent|x\b|times\s+(?:more|faster)))",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """\
You are the editorial selector for Ziv Raviv's coaching content. You act like an editor \
who was in the room: you pick the few ideas from real evidence (his calls and his team's \
work) that are worth him saying on camera this week.

Apply the strategy you are given. In short: audience is coaches first, event-industry \
small business owners second. The offer is Super Coaching (coaching plus AI integration \
inside the client's business). The only call to action is a strategy session. Never \
prices, never a giveaway.

Every candidate must pass ALL four gates, each with a one-sentence reason:
- small_service_business: applies to a small owner-led service business
- coach_or_event_owner_relevance: a coach or event-business owner would use it in \
day-to-day work
- concrete_supported_substance: the cited moments actually support the lesson as stated
- connects_to_ziv_work: it grows out of Ziv's coaching or his team's delivery

Rules:
- One lesson per candidate. The idea is the decision or lesson, not the product release.
- Keep coaching lessons that do not mention AI. Do not turn ideas into AI news commentary.
- Cite only moment ids from the pool. Never invent ids.
- Claims discipline: built, tested, deployed, used and measured are different. Never state \
an outcome (saved, grew, increased, percentages, more clients) unless a cited moment has \
claim_type "measured".
- Low speaker confidence or a translation label means paraphrase only, never quote; say so \
in public_safety_notes.
- Keep credentials, client and customer identities, customer words, sensitive personal \
stories and money figures out of title, lesson and public_angle.
- Do NOT fill a quota. Return fewer candidates, or none, when evidence is weak.
- Every moment you considered and did not use for a candidate goes in rejections with the \
gate it failed and a reason, so the editor can review what was left out.
- freshness_role is "evergreen" unless the idea depends on current news; "news" ideas need \
a verification_note naming what must be checked before recording.
- Scores are 0-5: owner_relevance (how useful to the owner's week), useful_lesson (can the \
reader do something with it), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

_GATE_SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "moment_ids": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "lesson": {"type": "string"},
                    "audience": {"type": "string", "enum": ["coaches", "event_owners", "both"]},
                    "reasons_to_care": {"type": "array", "items": {"type": "string"}},
                    "public_angle": {"type": "string"},
                    "public_safety_notes": {"type": "string"},
                    "gates": {
                        "type": "object",
                        "properties": {g: _GATE_SCHEMA for g in REJECTION_GATES},
                        "required": list(REJECTION_GATES),
                    },
                    "freshness_role": {"type": "string", "enum": ["evergreen", "news"]},
                    "verification_note": {"type": "string"},
                    "scores": {
                        "type": "object",
                        "properties": {
                            "owner_relevance": {"type": "number"},
                            "useful_lesson": {"type": "number"},
                            "support_strength": {"type": "number"},
                        },
                    },
                },
                "required": ["moment_ids", "title", "lesson", "audience", "public_angle", "gates"],
            },
        },
        "rejections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "moment_ids": {"type": "array", "items": {"type": "string"}},
                    "gate": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["moment_ids", "reason"],
            },
        },
    },
    "required": ["candidates", "rejections"],
}


@dataclass
class PoolMoment:
    moment: EvidenceMoment
    source: EvidenceSource
    in_week: bool

    @property
    def id(self) -> str:
        return str(self.moment.id)


@dataclass
class SelectionResult:
    selection_run_id: uuid.UUID
    status: str  # complete | no_evidence | waiting_capacity | failed | timeout | cancelled
    candidates: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    pool_size: int = 0
    week_pool: int = 0
    reserve_pool: int = 0
    job_id: uuid.UUID | None = None
    superseded: int = 0
    detail: str | None = None
    retry_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_run_id": str(self.selection_run_id),
            "status": self.status,
            "candidates": self.candidates,
            "rejected": self.rejected,
            "pool": {
                "total": self.pool_size,
                "week": self.week_pool,
                "evergreen_reserve": self.reserve_pool,
            },
            "job_id": str(self.job_id) if self.job_id else None,
            "superseded": self.superseded,
            "detail": self.detail,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
        }


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


def source_is_excluded(source: EvidenceSource) -> bool:
    if source.fetch_status in EXCLUDED_FETCH_STATUSES:
        return True
    meta = source.meta or {}
    if meta.get("reverted") or meta.get("low_signal") or meta.get("superseded"):
        return True
    if meta.get("exclude_reason"):
        return True
    return False


def _moment_time(pm_source: EvidenceSource, moment: EvidenceMoment) -> datetime | None:
    return pm_source.occurred_at or moment.created_at


async def build_pool(
    session: AsyncSession, workspace_id: uuid.UUID, week_start: date | datetime | str
) -> list[PoolMoment]:
    start, end = week_bounds(week_start)
    rows = (
        await session.execute(
            select(EvidenceMoment, EvidenceSource)
            .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
            .where(
                EvidenceMoment.workspace_id == workspace_id,
                EvidenceSource.workspace_id == workspace_id,
                EvidenceMoment.status == "active",
                or_(EvidenceSource.occurred_at.is_(None), EvidenceSource.occurred_at < end),
            )
        )
    ).all()

    used: set[str] = set()
    used_rows = (
        await session.execute(
            select(TopicCandidate.moment_ids).where(
                TopicCandidate.workspace_id == workspace_id,
                TopicCandidate.status.in_(USED_STATUSES),
                TopicCandidate.week_start < start,
            )
        )
    ).scalars()
    for ids in used_rows:
        used.update(str(i) for i in (ids or []))

    week: list[PoolMoment] = []
    reserve: list[PoolMoment] = []
    for moment, source in rows:
        if source_is_excluded(source):
            continue
        # extraction from an older version of the source is stale even if not yet marked
        if moment.source_version_hash and moment.source_version_hash != source.version_hash:
            continue
        when = _moment_time(source, moment)
        if when is not None and start <= when < end:
            week.append(PoolMoment(moment, source, True))
        elif when is not None and when < start and str(moment.id) not in used:
            reserve.append(PoolMoment(moment, source, False))

    def sort_key(pm: PoolMoment) -> datetime:
        return _moment_time(pm.source, pm.moment) or datetime.min

    week.sort(key=sort_key, reverse=True)
    reserve.sort(key=sort_key, reverse=True)
    return week[:WEEK_POOL_LIMIT] + reserve[:RESERVE_POOL_LIMIT]


def _pool_prompt_item(pm: PoolMoment) -> dict[str, Any]:
    m, s = pm.moment, pm.source
    return {
        "moment_id": pm.id,
        "pool": "this_week" if pm.in_week else "evergreen_reserve",
        "source_kind": s.source_kind,
        "occurred_at": s.occurred_at.isoformat() if s.occurred_at else None,
        "lesson_summary": m.lesson_summary,
        "claim_type": m.claim_type,
        "speaker_confidence": m.speaker_confidence,
        "translation_label": m.translation_label,
        "language_uncertain": bool(m.language_uncertain),
        "sensitivity_flags": list(m.sensitivity_flags or []),
        "excerpt_private": (m.excerpt_private or "")[:EXCERPT_CHARS],
    }


def build_selection_prompt(
    strategy_text: str,
    feedback_text: str,
    pool: list[PoolMoment],
    max_candidates: int,
    week_start: datetime,
) -> str:
    import json

    return "\n\n".join(
        [
            f"WEEK STARTING: {week_start.date().isoformat()}",
            "STRATEGY (effective for this workspace):\n" + (strategy_text or "(none)"),
            feedback_text,
            f"RETURN AT MOST {max_candidates} candidates. Fewer or zero is correct when the "
            "evidence does not support more. Three strong ideas is the usual target.",
            "EVIDENCE POOL (private; excerpts are for your judgment, never for quoting "
            "customers):\n" + json.dumps([_pool_prompt_item(pm) for pm in pool], indent=1),
        ]
    )


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def _reject(
    raw: dict[str, Any], moment_ids: list[str], gate: str, code: str, reason: str
) -> dict[str, Any]:
    return {
        "moment_ids": moment_ids,
        "gate": gate,
        "code": code,
        "reason": reason,
        "title": str(raw.get("title") or "")[:300],
        "lesson": str(raw.get("lesson") or ""),
        "public_angle": str(raw.get("public_angle") or ""),
        "audience": raw.get("audience")
        if raw.get("audience") in ("coaches", "event_owners", "both")
        else "both",
        "gates": raw.get("gates") if isinstance(raw.get("gates"), dict) else {},
    }


def _score(value: Any) -> float:
    try:
        return max(0.0, min(5.0, float(value))) / 5.0
    except (TypeError, ValueError):
        return 0.0


def _citation(pm: PoolMoment) -> dict[str, Any]:
    m, s = pm.moment, pm.source
    return {
        "moment_id": pm.id,
        "source_id": str(s.id),
        "source_kind": s.source_kind,
        "source_title": s.title,
        "occurred_at": s.occurred_at.isoformat() if s.occurred_at else None,
        "span_start_s": m.span_start_s,
        "span_end_s": m.span_end_s,
        "code_refs": m.code_refs,
        "url_private": s.url_private,
        "claim_type": m.claim_type,
        "speaker": m.speaker,
        "speaker_confidence": m.speaker_confidence,
        "translation_label": m.translation_label,
        "language_uncertain": bool(m.language_uncertain),
        "sensitivity_flags": list(m.sensitivity_flags or []),
        "excerpt_private": m.excerpt_private,
    }


def enforce_candidates(
    raw_candidates: list[Any],
    pool: list[PoolMoment],
    workspace_moment_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply code-side gates. Returns (accepted, rejected); accepted are unranked."""
    by_id = {pm.id: pm for pm in pool}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        ids = [str(i) for i in (raw.get("moment_ids") or []) if i]
        if not ids:
            rejected.append(
                _reject(
                    raw,
                    ids,
                    "concrete_supported_substance",
                    "no_citation",
                    "candidate cites no evidence moment",
                )
            )
            continue
        unknown = [i for i in ids if i not in workspace_moment_ids]
        if unknown:
            rejected.append(
                _reject(
                    raw,
                    ids,
                    "concrete_supported_substance",
                    "invalid_citation",
                    f"cited moment(s) not found in this workspace: {', '.join(unknown)}",
                )
            )
            continue
        ineligible = [i for i in ids if i not in by_id]
        if ineligible:
            rejected.append(
                _reject(
                    raw,
                    ids,
                    "concrete_supported_substance",
                    "ineligible_citation",
                    "cited moment(s) are stale, excluded, already used or outside the "
                    f"pool: {', '.join(ineligible)}",
                )
            )
            continue

        gates = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}
        failed_gate = None
        for g in REJECTION_GATES:
            val = gates.get(g)
            if not isinstance(val, dict) or val.get("pass") is not True:
                failed_gate = (
                    g,
                    "gate_failed" if isinstance(val, dict) else "gate_missing",
                    (val or {}).get("reason") if isinstance(val, dict) else None,
                )
                break
            if not str(val.get("reason") or "").strip():
                failed_gate = (g, "gate_reason_missing", None)
                break
        if failed_gate:
            g, code, why = failed_gate
            rejected.append(_reject(raw, ids, g, code, why or f"gate {g} not passed with a reason"))
            continue

        cited = [by_id[i] for i in ids]
        public_text = " ".join(str(raw.get(k) or "") for k in ("title", "lesson", "public_angle"))
        if _OUTCOME_LANGUAGE.search(public_text) and not any(
            pm.moment.claim_type == "measured" for pm in cited
        ):
            match = _OUTCOME_LANGUAGE.search(public_text)
            rejected.append(
                _reject(
                    raw,
                    ids,
                    "concrete_supported_substance",
                    "invented_outcome",
                    f"states an outcome ('{match.group(0) if match else ''}') without a "
                    "cited measured moment",
                )
            )
            continue

        notes: list[str] = []
        model_note = str(raw.get("public_safety_notes") or "").strip()
        if model_note:
            notes.append(model_note)
        for pm in cited:
            m = pm.moment
            if m.speaker_confidence in ("low", "unknown"):
                notes.append(
                    f"Speaker attribution confidence is {m.speaker_confidence} for moment "
                    f"{pm.id}: paraphrase, do not quote or attribute."
                )
            if m.translation_label or m.language_uncertain:
                label = m.translation_label or "language uncertain"
                notes.append(f"Translation ({label}) for moment {pm.id}: paraphrase, do not quote.")
            if m.sensitivity_flags:
                notes.append(
                    f"Sensitive material ({', '.join(m.sensitivity_flags)}) in moment {pm.id}: "
                    "keep only the general lesson."
                )

        freshness_role = "news" if raw.get("freshness_role") == "news" else "evergreen"
        if freshness_role == "news":
            vnote = str(raw.get("verification_note") or "").strip()
            notes.append(
                "News claim: verify it is still current before recording."
                + (f" {vnote}" if vnote else "")
            )

        scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
        code_support = sum(
            CLAIM_SUPPORT.get(pm.moment.claim_type, 0.3)
            * (0.7 if pm.moment.speaker_confidence == "low" else 1.0)
            for pm in cited
        ) / len(cited)
        support = 0.5 * code_support + 0.5 * _score(scores.get("support_strength", 2.5))
        rank_score = (
            0.40 * _score(scores.get("owner_relevance"))
            + 0.35 * _score(scores.get("useful_lesson"))
            + 0.25 * support
        )
        if freshness_role == "evergreen" and any(pm.in_week for pm in cited):
            rank_score += 0.05  # freshness is only a small bonus for evergreen ideas

        audience = raw.get("audience")
        accepted.append(
            {
                "moment_ids": ids,
                "title": str(raw.get("title") or "").strip()[:300],
                "lesson": str(raw.get("lesson") or "").strip(),
                "audience": audience if audience in ("coaches", "event_owners", "both") else "both",
                "reasons_to_care": [str(r) for r in (raw.get("reasons_to_care") or [])][:6],
                "public_angle": str(raw.get("public_angle") or "").strip(),
                "public_safety_notes": "\n".join(dict.fromkeys(notes)) or None,
                "gates": {
                    g: {"pass": True, "reason": str(gates[g]["reason"])} for g in REJECTION_GATES
                },
                "freshness_role": freshness_role,
                "rank_score": round(rank_score, 4),
                "citations_private": [_citation(pm) for pm in cited],
            }
        )
    return accepted, rejected


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _workspace_moment_ids(
    session: AsyncSession, workspace_id: uuid.UUID, ids: list[str]
) -> set[str]:
    uuids = []
    for i in ids:
        try:
            uuids.append(uuid.UUID(str(i)))
        except ValueError:
            continue
    if not uuids:
        return set()
    rows = (
        await session.execute(
            select(EvidenceMoment.id).where(
                EvidenceMoment.workspace_id == workspace_id, EvidenceMoment.id.in_(uuids)
            )
        )
    ).scalars()
    return {str(r) for r in rows}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def select_candidates(
    sessionmaker_or_session: SessionSource,
    workspace_id: uuid.UUID | str,
    week_start: date | datetime | str,
    *,
    max_candidates: int = 6,
    selection_run_id: uuid.UUID | None = None,
    on_activity: Any = None,
) -> SelectionResult:
    ws = coerce_uuid(workspace_id)
    start, _end = week_bounds(week_start)
    max_candidates = max(0, min(int(max_candidates), MAX_CANDIDATES_CAP))
    run_id = selection_run_id or uuid.uuid4()

    def activity(msg: str, **kw: Any) -> None:
        if on_activity:
            on_activity(msg, **kw)

    async with open_session(sessionmaker_or_session) as session:
        activity("Building evidence pool")
        pool = await build_pool(session, ws, start)
        week_n = sum(1 for pm in pool if pm.in_week)
        result = SelectionResult(
            selection_run_id=run_id,
            status="complete",
            pool_size=len(pool),
            week_pool=week_n,
            reserve_pool=len(pool) - week_n,
        )

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        job_id: uuid.UUID | None = None

        if not pool or max_candidates == 0:
            result.status = "no_evidence" if not pool else "complete"
            result.detail = "No eligible evidence moments for this week" if not pool else None
        else:
            activity(f"Loading strategy and feedback ({len(pool)} moments in pool)")
            strategy = await load_effective_strategy(session, ws)
            feedback = await summarize_feedback(session, ws)
            prompt = build_selection_prompt(
                strategy.text, feedback.to_prompt_text(), pool, max_candidates, start
            )
            activity(f"Waiting for subscription selection job ({len(pool)} moments)")
            try:
                llm = await _llm.complete(
                    LLMRequest(
                        job_type=JOB_TYPE,
                        agent_name=AGENT_NAME,
                        messages=[{"role": "user", "content": prompt}],
                        system=SYSTEM_PROMPT,
                        output_schema=OUTPUT_SCHEMA,
                        max_tokens=8192,
                        prompt_version=PROMPT_VERSION,
                        workspace_id=ws,
                        run_id=run_id,
                        # one job per selection run: a rerun is a fresh selection, not a
                        # cached replay of the previous one
                        idempotency_key=f"editorial_selection:{ws}:{run_id}",
                    )
                )
            except LLMUnavailable as exc:
                # Persist nothing, supersede nothing: prior candidates stay as they were.
                result.status = exc.status
                result.detail = exc.detail
                result.job_id = exc.job_id
                result.retry_at = exc.retry_at
                return result
            job_id = llm.job_id
            result.job_id = job_id
            activity("Selection job returned; enforcing gates", job_id=job_id)
            data = llm.structured if isinstance(llm.structured, dict) else None
            if data is None:
                import json

                try:
                    data = json.loads(llm.text)
                except (TypeError, ValueError):
                    result.status = "failed"
                    result.detail = "selection job returned no valid JSON"
                    return result
            raw_candidates = data.get("candidates") or []
            all_cited = [
                str(i)
                for c in raw_candidates
                if isinstance(c, dict)
                for i in (c.get("moment_ids") or [])
            ]
            ws_ids = await _workspace_moment_ids(session, ws, all_cited)
            accepted, rejected = enforce_candidates(raw_candidates, pool, ws_ids)
            for r in data.get("rejections") or []:
                if not isinstance(r, dict):
                    continue
                gate = r.get("gate") if r.get("gate") in REJECTION_GATES else None
                rejected.append(
                    _reject(
                        r,
                        [str(i) for i in (r.get("moment_ids") or [])],
                        gate or "unspecified",
                        "model_rejected",
                        str(r.get("reason") or ""),
                    )
                )

        # Existing week rows: supersede proposed + prior selector rejections; never touch
        # selected/recorded/published/editor-rejected/calibration rows.
        existing = (
            (
                await session.execute(
                    select(TopicCandidate).where(
                        TopicCandidate.workspace_id == ws, TopicCandidate.week_start == start
                    )
                )
            )
            .scalars()
            .all()
        )
        kept_sets = set()
        for row in existing:
            if row.status == "proposed" or (
                row.origin == ORIGIN_SELECTOR_REJECTED and row.status == "rejected"
            ):
                row.status = "withdrawn"
                row.editor_notes = (
                    (row.editor_notes + "\n") if row.editor_notes else ""
                ) + f"superseded by selection run {run_id}"
                result.superseded += 1
            elif row.status in USED_STATUSES and row.moment_ids:
                kept_sets.add(frozenset(str(i) for i in row.moment_ids))

        deduped = []
        for cand in accepted:
            if frozenset(cand["moment_ids"]) in kept_sets:
                rejected.append(
                    _reject(
                        cand,
                        cand["moment_ids"],
                        "unspecified",
                        "already_selected",
                        "the same evidence is already selected this week",
                    )
                )
            else:
                deduped.append(cand)
        deduped.sort(key=lambda c: c["rank_score"], reverse=True)
        for extra in deduped[max_candidates:]:
            rejected.append(
                _reject(
                    extra,
                    extra["moment_ids"],
                    "unspecified",
                    "below_cut",
                    f"ranked below the top {max_candidates}",
                )
            )
        final = deduped[:max_candidates]

        now = _now()
        rows: list[TopicCandidate] = []
        for rank, cand in enumerate(final, start=1):
            row = TopicCandidate(
                workspace_id=ws,
                week_start=start,
                selection_run_id=run_id,
                moment_ids=cand["moment_ids"],
                title=cand["title"],
                lesson=cand["lesson"],
                audience=cand["audience"],
                reasons_to_care=cand["reasons_to_care"],
                public_angle=cand["public_angle"],
                public_safety_notes=cand["public_safety_notes"],
                gates=cand["gates"],
                rank=rank,
                rank_score=cand["rank_score"],
                freshness_role=cand["freshness_role"],
                citations_private=cand["citations_private"],
                status="proposed",
                prompt_version=PROMPT_VERSION,
                job_id=job_id,
                origin=ORIGIN_SELECTOR,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            rows.append(row)
        for rej in rejected:
            gates = rej.get("gates") or {}
            gates = dict(gates) if isinstance(gates, dict) else {}
            gates["_rejection"] = {
                "gate": rej["gate"],
                "code": rej["code"],
                "reason": rej["reason"],
            }
            session.add(
                TopicCandidate(
                    workspace_id=ws,
                    week_start=start,
                    selection_run_id=run_id,
                    moment_ids=rej["moment_ids"],
                    title=rej["title"] or f"Rejected: {rej['code']}",
                    lesson=rej["lesson"],
                    audience=rej["audience"],
                    reasons_to_care=[],
                    public_angle=rej["public_angle"],
                    public_safety_notes=None,
                    gates=gates,
                    freshness_role="evergreen",
                    citations_private=[],
                    status="rejected",
                    editor_notes=rej["reason"],
                    prompt_version=PROMPT_VERSION,
                    job_id=job_id,
                    origin=ORIGIN_SELECTOR_REJECTED,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
        activity(f"Selection saved: {len(rows)} candidates, {len(rejected)} rejections")

        result.candidates = [candidate_to_json(r) for r in rows]
        result.rejected = [
            {k: rej[k] for k in ("moment_ids", "gate", "code", "reason", "title")}
            for rej in rejected
        ]
        return result
