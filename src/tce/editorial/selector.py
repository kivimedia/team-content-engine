"""Editorial selector: evidence moments -> ranked, gated topic candidates.

Pool: EVERY active moment of this workspace from the week (Monday to Monday in Israel
time), plus a bounded evergreen reserve of earlier moments no selected/recorded/published
candidate has used yet (round robin across sources, omitted count reported). Sources that
are excluded, failed, unavailable, reverted or low-signal never enter the pool, and
neither do stale moments.

The pool is split into bounded shards (sources kept together), one subscription LLM job
per shard, so a busy late-week source can never push earlier evidence out of view. Each
shard must account for every moment it was shown; moments the model skipped are reported
as unaccounted, never invented into rejections. If any shard does not finish, nothing is
saved and every shard's state is reported; retrying the same run resumes the same jobs.

Each job proposes candidates and explicit rejections. Code then
enforces what the model cannot be trusted to: all four gates with reasons, citations
that exist in this workspace's pool, no measured outcome without a measured moment,
uncertainty carried as public-safety notes, and no quota padding. Rejections are
persisted as `status=rejected, origin=selector_rejected` rows for later sampling.
"""

from __future__ import annotations

import asyncio
import json
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
    WEEK_TIMEZONE,
    SessionSource,
    candidate_to_json,
    coerce_uuid,
    job_can_requeue,
    job_prompt_text,
    open_session,
    parse_selection_header,
    replay_request,
    selection_key_text,
    week_bounds,
    week_source_window,
)
from tce.editorial.feedback import summarize_feedback
from tce.llm import LLMRequest, LLMUnavailable
from tce.models.editorial import (
    REJECTION_GATES,
    EvidenceMoment,
    EvidenceSource,
    TopicCandidate,
)
from tce.models.llm_job import LLMJob
from tce.services.strategy_loader import load_effective_strategy

# v2: sharded full-week coverage with explicit per-moment accounting
PROMPT_VERSION = "editorial_selection.v2"
JOB_TYPE = "editorial_selection"
AGENT_NAME = "editorial_selector"
MAX_CANDIDATES_CAP = 6
# Week moments are never capped; they are split into jobs of at most SHARD_SIZE moments.
SHARD_SIZE = 40
# Above this many jobs a run is refused with an explanation instead of silently trimmed.
MAX_SHARDS = 30
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
class PoolPlan:
    moments: list[PoolMoment]  # week moments (oldest first) then the picked reserve
    week_total: int
    reserve_eligible: int
    reserve_included: int
    window_start: datetime  # naive UTC
    window_end: datetime


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
    job_ids: list[uuid.UUID] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    resumed: bool = False
    max_candidates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_run_id": str(self.selection_run_id),
            "status": self.status,
            "resumed": self.resumed,
            "max_candidates": self.max_candidates,
            "job_ids": [str(j) for j in self.job_ids],
            "coverage": self.coverage,
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


def _pm_sort_key(pm: PoolMoment) -> tuple[datetime, str]:
    return (_moment_time(pm.source, pm.moment) or datetime.min, pm.id)


def _pick_reserve(reserve: list[PoolMoment], limit: int) -> list[PoolMoment]:
    """Newest-first round robin across sources, so one busy source cannot fill the
    whole reserve. Deterministic for a given pool."""
    by_source: dict[str, list[PoolMoment]] = {}
    for pm in sorted(reserve, key=_pm_sort_key, reverse=True):
        by_source.setdefault(str(pm.source.id), []).append(pm)
    queues = sorted(by_source.values(), key=lambda q: _pm_sort_key(q[0]), reverse=True)
    picked: list[PoolMoment] = []
    depth = 0
    while len(picked) < limit and any(depth < len(q) for q in queues):
        for q in queues:
            if depth < len(q) and len(picked) < limit:
                picked.append(q[depth])
        depth += 1
    return picked


async def collect_pool(
    session: AsyncSession, workspace_id: uuid.UUID, week_start: date | datetime | str
) -> PoolPlan:
    """Every eligible moment of the week, plus a bounded evergreen reserve.

    The week is the Israel-time window of the label (see `week_source_window`). Week
    moments are never capped here: coverage is achieved by sharding the model jobs.
    """
    label_start, _ = week_bounds(week_start)
    start, end = week_source_window(week_start)
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
                TopicCandidate.week_start < label_start,
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

    week.sort(key=_pm_sort_key)
    picked = _pick_reserve(reserve, RESERVE_POOL_LIMIT)
    return PoolPlan(
        moments=week + picked,
        week_total=len(week),
        reserve_eligible=len(reserve),
        reserve_included=len(picked),
        window_start=start,
        window_end=end,
    )


async def build_pool(
    session: AsyncSession, workspace_id: uuid.UUID, week_start: date | datetime | str
) -> list[PoolMoment]:
    return (await collect_pool(session, workspace_id, week_start)).moments


def plan_shards(pool: list[PoolMoment], shard_size: int | None = None) -> list[list[PoolMoment]]:
    """Split the pool into bounded shards without dropping anything.

    Moments of one source stay together (a meeting is judged as a whole) unless the
    source alone exceeds a shard. Shards are balanced so the last one is not a stub.
    """
    size = max(1, shard_size or SHARD_SIZE)
    if not pool:
        return []
    groups: dict[str, list[PoolMoment]] = {}
    for pm in sorted(pool, key=_pm_sort_key):
        groups.setdefault(str(pm.source.id), []).append(pm)
    ordered = sorted(groups.values(), key=lambda g: (not g[0].in_week, _pm_sort_key(g[0])))
    n = -(-len(pool) // size)
    target = -(-len(pool) // n)
    shards: list[list[PoolMoment]] = [[]]
    for group in ordered:
        for i in range(0, len(group), size):
            chunk = group[i : i + size]
            # chunk <= size and target <= size, so a chunk always fits a fresh shard
            if shards[-1] and len(shards[-1]) + len(chunk) > target:
                shards.append([])
            shards[-1].extend(chunk)
    return [s for s in shards if s]


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
    *,
    shard: int = 1,
    shards: int = 1,
    total_moments: int | None = None,
) -> str:
    import json

    total = len(pool) if total_moments is None else total_moments
    # The first three lines are durable headers parsed by tce.editorial.common.
    return "\n\n".join(
        [
            f"WEEK STARTING: {week_start.date().isoformat()}\n"
            f"SELECTION SHARD: {shard}/{shards}\n"
            f"RETURN AT MOST {max_candidates} candidates from this shard. Fewer or zero is "
            "correct when the evidence does not support more. Three strong ideas is the "
            "usual target for the whole week.",
            "STRATEGY (effective for this workspace):\n" + (strategy_text or "(none)"),
            feedback_text,
            f"COVERAGE: this is shard {shard} of {shards}. The week's pool has {total} "
            f"moments; this shard holds {len(pool)} of them and other shards are judged "
            "separately with the same instructions, so judge these on their own merit.",
            "ACCOUNTING: every moment_id below must appear in your answer exactly once: in "
            "a candidate's moment_ids, or in a rejection with the gate it failed and a "
            "reason. Do not leave any moment out.",
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


def _iso_z(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


@dataclass
class ShardSpec:
    shard: int
    shards: int
    request: LLMRequest
    moment_ids: list[str]
    requeue_failed: bool = False
    job_status: str | None = None  # stored job status when resuming


async def _stored_shard_specs(
    session: AsyncSession, ws: uuid.UUID, run_id: uuid.UUID
) -> tuple[list[ShardSpec], str | None]:
    """Rebuild the exact requests of a run that already has jobs. Returns (specs, problem)."""
    jobs = (
        (
            await session.execute(
                select(LLMJob).where(
                    LLMJob.workspace_id == ws,
                    LLMJob.job_type == JOB_TYPE,
                    LLMJob.run_id == run_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not jobs:
        return [], None
    specs: list[ShardSpec] = []
    expected = None
    for job in jobs:
        meta = parse_selection_header(job_prompt_text(job.request_json))
        if meta is None:
            return [], f"job {job.id} has no selection header; start a new selection"
        key = selection_key_text(ws, run_id, meta["shard"], meta["shards"])
        req = replay_request(job, key)
        if req is None:
            return [], f"job {job.id} could not be rebuilt exactly; start a new selection"
        expected = meta["shards"]
        specs.append(
            ShardSpec(
                shard=meta["shard"] or 1,
                shards=meta["shards"],
                request=req,
                moment_ids=meta["moment_ids"],
                requeue_failed=job_can_requeue(job),
                job_status=job.status,
            )
        )
    specs.sort(key=lambda s: s.shard)
    if expected is None or len(specs) != expected or len({s.shard for s in specs}) != expected:
        return specs, (
            f"run has {len(specs)} of {expected} shard jobs (interrupted while enqueueing); "
            "start a new selection"
        )
    return specs, None


_FAILURE_ORDER = ("failed", "invalid_output", "cancelled", "waiting_capacity", "timeout")


async def select_candidates(
    sessionmaker_or_session: SessionSource,
    workspace_id: uuid.UUID | str,
    week_start: date | datetime | str,
    *,
    max_candidates: int = 6,
    selection_run_id: uuid.UUID | None = None,
    on_activity: Any = None,
) -> SelectionResult:
    """Run (or resume) one selection for a week.

    Passing the `selection_run_id` of a run whose jobs already exist resumes it: the
    stored requests are replayed under the same idempotency keys, so the queue returns
    the existing jobs (finished ones immediately) and nothing is enqueued twice.
    """
    ws = coerce_uuid(workspace_id)
    start, _end = week_bounds(week_start)
    max_candidates = max(0, min(int(max_candidates), MAX_CANDIDATES_CAP))
    run_id = selection_run_id or uuid.uuid4()

    def activity(msg: str, **kw: Any) -> None:
        if on_activity:
            on_activity(msg, **kw)

    async with open_session(sessionmaker_or_session) as session:
        activity("Building evidence pool")
        plan = await collect_pool(session, ws, start)
        result = SelectionResult(
            selection_run_id=run_id,
            status="complete",
            pool_size=len(plan.moments),
            week_pool=plan.week_total,
            reserve_pool=plan.reserve_included,
            max_candidates=max_candidates,
        )
        coverage: dict[str, Any] = {
            "window": {
                "timezone": WEEK_TIMEZONE,
                "start_utc": _iso_z(plan.window_start),
                "end_utc": _iso_z(plan.window_end),
            },
            "week_moments": plan.week_total,
            "reserve": {
                "eligible": plan.reserve_eligible,
                "included": plan.reserve_included,
                "omitted": plan.reserve_eligible - plan.reserve_included,
                "policy": f"evergreen reserve: at most {RESERVE_POOL_LIMIT} unused earlier "
                "moments, newest first, round robin across sources",
            },
            "shards": [],
            "considered": 0,
            "unaccounted_moment_ids": [],
            "not_in_this_run_moment_ids": [],
            "no_longer_eligible_moment_ids": [],
            "complete": False,
        }
        result.coverage = coverage

        specs, problem = await _stored_shard_specs(session, ws, run_id)
        if problem:
            result.status = "failed"
            result.detail = problem
            return result
        pool_by_id = {pm.id: pm for pm in plan.moments}
        if specs:
            result.resumed = True
            stored_max = parse_selection_header(specs[0].request.messages[0]["content"])
            if stored_max and stored_max["max_candidates"] is not None:
                max_candidates = result.max_candidates = stored_max["max_candidates"]
            in_run = {i for s in specs for i in s.moment_ids}
            coverage["not_in_this_run_moment_ids"] = [
                pm.id for pm in plan.moments if pm.in_week and pm.id not in in_run
            ]
            coverage["no_longer_eligible_moment_ids"] = sorted(
                i for i in in_run if i not in pool_by_id
            )
        elif plan.moments and max_candidates > 0:
            shards = plan_shards(plan.moments)
            if len(shards) > MAX_SHARDS:
                result.status = "failed"
                result.detail = (
                    f"{len(plan.moments)} moments need {len(shards)} selection jobs, above the "
                    f"limit of {MAX_SHARDS}; nothing was sent or saved. Narrow the evidence "
                    "(exclude low-signal sources) and retry."
                )
                return result
            activity(f"Loading strategy and feedback ({len(plan.moments)} moments in pool)")
            strategy = await load_effective_strategy(session, ws)
            feedback = await summarize_feedback(session, ws)
            feedback_text = feedback.to_prompt_text()
            for i, shard in enumerate(shards, start=1):
                prompt = build_selection_prompt(
                    strategy.text,
                    feedback_text,
                    shard,
                    max_candidates,
                    start,
                    shard=i,
                    shards=len(shards),
                    total_moments=len(plan.moments),
                )
                specs.append(
                    ShardSpec(
                        shard=i,
                        shards=len(shards),
                        moment_ids=[pm.id for pm in shard],
                        request=LLMRequest(
                            job_type=JOB_TYPE,
                            agent_name=AGENT_NAME,
                            messages=[{"role": "user", "content": prompt}],
                            system=SYSTEM_PROMPT,
                            output_schema=OUTPUT_SCHEMA,
                            max_tokens=8192,
                            prompt_version=PROMPT_VERSION,
                            workspace_id=ws,
                            run_id=run_id,
                            # one job per shard of this run: a new run is a fresh
                            # selection, a resumed run replays the same keys
                            idempotency_key=selection_key_text(ws, run_id, i, len(shards)),
                        ),
                    )
                )

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        if not specs:
            result.status = "no_evidence" if not plan.moments else "complete"
            if not plan.moments:
                result.detail = "No eligible evidence moments for this week"
            # max_candidates=0 asks for nothing: say so rather than claim coverage
            coverage["complete"] = not plan.moments
        else:
            n_moments = sum(len(s.moment_ids) for s in specs)
            done = {"n": 0}
            activity(
                f"Waiting for {len(specs)} subscription selection job(s) covering "
                f"{n_moments} moments" + (" (resumed)" if result.resumed else "")
            )

            async def run_shard(spec: ShardSpec) -> tuple[ShardSpec, Any, Any]:
                try:
                    if spec.requeue_failed:
                        llm = await _llm.complete(spec.request, requeue_failed=True)
                    else:
                        llm = await _llm.complete(spec.request)
                    outcome: tuple[ShardSpec, Any, Any] = (spec, llm, None)
                except LLMUnavailable as exc:
                    outcome = (spec, None, exc)
                done["n"] += 1
                activity(
                    f"Selection shard {spec.shard}/{spec.shards} "
                    f"{'returned' if outcome[1] else outcome[2].status} "
                    f"({done['n']} of {len(specs)} finished)",
                    job_id=outcome[1].job_id if outcome[1] else outcome[2].job_id,
                )
                return outcome

            outcomes = await asyncio.gather(*(run_shard(s) for s in specs))

            shard_rows: list[dict[str, Any]] = []
            parsed: list[tuple[ShardSpec, uuid.UUID, dict[str, Any]]] = []
            for spec, llm, exc in outcomes:
                row: dict[str, Any] = {
                    "shard": spec.shard,
                    "shards": spec.shards,
                    "moments": len(spec.moment_ids),
                    "job_id": None,
                    "status": None,
                    "detail": None,
                    "retry_at": None,
                }
                if exc is not None:
                    row.update(
                        job_id=str(exc.job_id) if exc.job_id else None,
                        status=exc.status,
                        detail=exc.detail,
                        retry_at=exc.retry_at.isoformat() if exc.retry_at else None,
                    )
                    if exc.job_id:
                        result.job_ids.append(exc.job_id)
                    if exc.retry_at and (result.retry_at is None or exc.retry_at > result.retry_at):
                        result.retry_at = exc.retry_at
                else:
                    result.job_ids.append(llm.job_id)
                    row["job_id"] = str(llm.job_id)
                    data = llm.structured if isinstance(llm.structured, dict) else None
                    if data is None:
                        try:
                            data = json.loads(llm.text)
                        except (TypeError, ValueError):
                            data = None
                    if not isinstance(data, dict):
                        row.update(status="invalid_output", detail="job returned no valid JSON")
                    else:
                        row["status"] = "succeeded"
                        parsed.append((spec, llm.job_id, data))
                shard_rows.append(row)
            coverage["shards"] = shard_rows
            result.job_id = result.job_ids[0] if result.job_ids else None

            bad = [r for r in shard_rows if r["status"] != "succeeded"]
            if bad:
                # A shard that did not finish is NOT evidence that its moments were weak:
                # save nothing, supersede nothing, report every shard's state.
                statuses = {r["status"] for r in bad}
                worst = next((s for s in _FAILURE_ORDER if s in statuses), "failed")
                result.status = "failed" if worst == "invalid_output" else worst
                result.detail = (
                    "; ".join(
                        f"shard {r['shard']}/{r['shards']} {r['status']}"
                        + (f": {r['detail']}" if r["detail"] else "")
                        for r in bad
                    )
                    + f". {len(shard_rows) - len(bad)} of {len(shard_rows)} shard(s) finished; "
                    "nothing was saved and earlier candidates are untouched. Retrying resumes "
                    "the same jobs."
                )
                return result

            all_cited = [
                str(i)
                for _spec, _job, data in parsed
                for c in (data.get("candidates") or [])
                if isinstance(c, dict)
                for i in (c.get("moment_ids") or [])
            ]
            ws_ids = await _workspace_moment_ids(session, ws, all_cited)
            unaccounted: list[str] = []
            for spec, job_id, data in parsed:
                shard_ids = set(spec.moment_ids)
                shard_pool = [pool_by_id[i] for i in spec.moment_ids if i in pool_by_id]
                raw_candidates = data.get("candidates") or []
                acc, rej = enforce_candidates(raw_candidates, shard_pool, ws_ids)
                accounted = {
                    str(i)
                    for c in raw_candidates
                    if isinstance(c, dict)
                    for i in (c.get("moment_ids") or [])
                }
                dropped_rejections = 0
                for r in data.get("rejections") or []:
                    if not isinstance(r, dict):
                        continue
                    ids = [str(i) for i in (r.get("moment_ids") or [])]
                    kept = [i for i in ids if i in shard_ids]
                    if ids and not kept:
                        # cites nothing this shard was shown (another tenant, a guess):
                        # not persisted, only counted
                        dropped_rejections += 1
                        continue
                    accounted.update(kept)
                    gate = r.get("gate") if r.get("gate") in REJECTION_GATES else None
                    rej.append(
                        _reject(
                            r,
                            kept,
                            gate or "unspecified",
                            "model_rejected",
                            str(r.get("reason") or ""),
                        )
                    )
                for item in acc + rej:
                    item["job_id"] = job_id
                accepted.extend(acc)
                rejected.extend(rej)
                missing = [i for i in spec.moment_ids if i not in accounted]
                unaccounted.extend(missing)
                for row in shard_rows:
                    if row["shard"] == spec.shard:
                        row.update(
                            accounted=len(shard_ids) - len(missing),
                            unaccounted=len(missing),
                            rejections_dropped=dropped_rejections,
                        )
            coverage["considered"] = sum(len(s.moment_ids) for s in specs)
            coverage["unaccounted_moment_ids"] = unaccounted
            coverage["complete"] = not unaccounted and not coverage["not_in_this_run_moment_ids"]
            notes = []
            if unaccounted:
                notes.append(
                    f"{len(unaccounted)} of {coverage['considered']} moments were not accounted "
                    "for by the model (coverage.unaccounted_moment_ids); they are not recorded "
                    "as rejections."
                )
            if coverage["not_in_this_run_moment_ids"]:
                notes.append(
                    f"{len(coverage['not_in_this_run_moment_ids'])} week moments arrived after "
                    "this resumed run started and were not judged "
                    "(coverage.not_in_this_run_moment_ids); run a new selection to include them."
                )
            result.detail = " ".join(notes) or None

        # A run is saved once. A second request resuming an already saved run (double
        # click, two processes) returns what was saved instead of writing it again.
        saved = (
            (
                await session.execute(
                    select(TopicCandidate).where(
                        TopicCandidate.workspace_id == ws,
                        TopicCandidate.selection_run_id == run_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if saved:
            result.candidates = [
                candidate_to_json(r)
                for r in sorted(saved, key=lambda r: r.rank or 0)
                if r.origin == ORIGIN_SELECTOR
            ]
            result.rejected = [
                {
                    "moment_ids": list(r.moment_ids or []),
                    "gate": (r.gates or {}).get("_rejection", {}).get("gate"),
                    "code": (r.gates or {}).get("_rejection", {}).get("code"),
                    "reason": r.editor_notes,
                    "title": r.title,
                }
                for r in saved
                if r.origin == ORIGIN_SELECTOR_REJECTED
            ]
            result.detail = "this selection run was already saved; returning the saved rows"
            return result

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
                dup = _reject(
                    cand,
                    cand["moment_ids"],
                    "unspecified",
                    "already_selected",
                    "the same evidence is already selected this week",
                )
                dup["job_id"] = cand.get("job_id")
                rejected.append(dup)
            else:
                deduped.append(cand)
        deduped.sort(key=lambda c: c["rank_score"], reverse=True)
        for extra in deduped[max_candidates:]:
            cut = _reject(
                extra,
                extra["moment_ids"],
                "unspecified",
                "below_cut",
                f"ranked below the top {max_candidates}",
            )
            cut["job_id"] = extra.get("job_id")
            rejected.append(cut)
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
                job_id=cand.get("job_id"),
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
                    job_id=rej.get("job_id"),
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
