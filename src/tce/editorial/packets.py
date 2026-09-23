"""Recording packets: one selected idea -> walking bullets, phrase script, text posts.

One subscription job writes the packet. Code then validates the shape (5-7 bullets,
a phrase-broken script ending in the strategy-session invitation, no giveaway CTA)
and runs the deterministic public-safety scan over every public field. When the LLM
is unavailable nothing is persisted: the caller gets the waiting state.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce import llm as _llm
from tce.editorial import voice_retrieval
from tce.editorial.common import (
    SessionSource,
    coerce_uuid,
    job_can_requeue,
    job_prompt_text,
    open_session,
    packet_key_text,
    packet_to_json,
    parse_packet_header,
    replay_request,
)
from tce.editorial.safety import scan_public_text
from tce.editorial.voice import HOOK_RULE, first_banned
from tce.llm import LLMRequest, LLMUnavailable
from tce.models.editorial import EvidenceSource, RecordingPacket, TopicCandidate
from tce.models.llm_job import LLMJob
from tce.models.recording_session import RecordingSession
from tce.services.strategy_loader import load_effective_strategy

PROMPT_VERSION = "recording_packet.v2"
JOB_TYPE = "recording_packet"
AGENT_NAME = "recording_packet_writer"
MIN_BULLETS = 5
MAX_BULLETS = 7
# What the writer must produce. The list grows later (more openings, a voice pass).
HOOK_OPTIONS_WRITTEN = 3
# A take set in one of these states has clips bound to its packet version; the
# opening of that version cannot be switched underneath it (see choose_hook).
RECORDING_IN_PROGRESS_STATUSES = ("recording", "finalizing")

_CTA = re.compile(r"strategy[\s-]+session", re.IGNORECASE)
_GIVEAWAY = re.compile(
    r"\b(?:free (?:guide|download|checklist|template|pdf|ebook)|giveaway|lead magnet|"
    r"comment (?:the word|below with)|dm me (?:the word|for the)|"
    r"download (?:my|the|our) (?:free )?(?:guide|checklist|template))",
    re.IGNORECASE,
)
# "Comment GUIDE below" style keyword CTAs (case-sensitive on the keyword)
_KEYWORD_CTA = re.compile(r"\b[Cc]omment\s+[\"']?[A-Z]{3,}\b")

SYSTEM_PROMPT = (
    """\
You write recording packets for Ziv Raviv, a business coach (Super Coaching: his human \
team and AI team become the client's). He records walking, phone in hand, one file per \
idea, reading one short phrase, looking up, saying it.

Write for coaches first and event-industry small business owners second. One lesson only. \
Tell it from Ziv's own first-person experience. Beats are flexible around the lesson; no \
fixed number of parts. No forced company names, statistics, news hooks or crisis hooks.

Hard rules:
- bullets: 5 to 7 short walking bullets he can talk from.
- script_phrases: the FULL script, first person, one short phrase per item (roughly 3-12 \
words each). The final phrase(s) invite the viewer to book a strategy session.
- The only call to action is booking a strategy session. No giveaway, guide, download, \
comment keyword or software pitch.
- Never prices, fees, revenue, money figures or business percentages.
- No client or customer names, no customer words or quotes, no credentials, no private \
links, no identifying sensitive stories. Keep only the general lesson.
- Claims discipline: built, tested, deployed, used and measured are different. State no \
outcome that the cited evidence does not measure.
- facebook_post and linkedin_post adapt the same lesson for text, ending with the same \
strategy-session invitation. No long dashes.
- interviewer_prompt: one question an interviewer could ask so Ziv answers in his own words.
"""
    + HOOK_RULE
    + """
- beats: one beat for each walking bullet. Use stable phrase IDs p001, p002 and so on and map
  every beat to an ordered inclusive phrase range.
- self_check: report honestly whether each rule holds.

Return only JSON matching the schema."""
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 7},
        "script_phrases": {"type": "array", "items": {"type": "string"}, "minItems": 6},
        "facebook_post": {"type": "string"},
        "linkedin_post": {"type": "string"},
        "interviewer_prompt": {"type": "string"},
        "hook_options": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "text",
                    "question",
                    "payoff_phrase_id",
                    "moment_ids",
                    "rationale",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "question": {"type": "string"},
                    "payoff_phrase_id": {"type": "string"},
                    "moment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "rationale": {"type": "string"},
                },
            },
        },
        "selected_hook_id": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "label", "bullet_index", "start_phrase_id", "end_phrase_id"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "bullet_index": {"type": "integer"},
                    "start_phrase_id": {"type": "string"},
                    "end_phrase_id": {"type": "string"},
                },
            },
        },
        "self_check": {
            "type": "object",
            "properties": {
                "one_lesson": {"type": "boolean"},
                "claims_supported": {"type": "boolean"},
                "no_prices_or_money": {"type": "boolean"},
                "no_customer_words_or_identities": {"type": "boolean"},
                "cta_is_strategy_session": {"type": "boolean"},
                "notes": {"type": "string"},
            },
        },
    },
    "required": [
        "bullets",
        "script_phrases",
        "facebook_post",
        "linkedin_post",
        "interviewer_prompt",
        "hook_options",
        "selected_hook_id",
        "beats",
        "self_check",
    ],
}


class PacketValidationError(ValueError):
    pass


@dataclass
class PacketOutcome:
    status: str  # ready | issues | waiting_capacity | failed | timeout | cancelled | invalid
    packet: dict[str, Any] | None = None
    job_id: uuid.UUID | None = None
    detail: str | None = None
    retry_at: datetime | None = None
    errors: list[str] = field(default_factory=list)
    # The version the saved packet replaced, when there was one.
    replaced_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packet": self.packet,
            "job_id": str(self.job_id) if self.job_id else None,
            "detail": self.detail,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
            "errors": self.errors,
            "replaced_version": self.replaced_version,
        }


def validate_packet_output(
    data: Any,
    *,
    max_hooks: int = HOOK_OPTIONS_WRITTEN,
    news_terms: list[str] | None = None,
) -> dict[str, Any]:
    """Return a cleaned packet dict or raise PacketValidationError with all problems.

    `max_hooks` is three when a packet is first written and MAX_HOOK_OPTIONS when an
    existing one is re-validated. Asking for more openings grows that list on
    purpose, and choose_hook re-validates the whole packet: with a flat rule of
    exactly three, every opening added after the first three was unselectable.
    """
    if not isinstance(data, dict):
        raise PacketValidationError("packet output is not a JSON object")
    errors: list[str] = []

    bullets = data.get("bullets")
    if not isinstance(bullets, list) or not all(isinstance(b, str) and b.strip() for b in bullets):
        errors.append("bullets must be a list of non-empty strings")
        bullets = []
    elif not MIN_BULLETS <= len(bullets) <= MAX_BULLETS:
        errors.append(f"bullets must have {MIN_BULLETS}-{MAX_BULLETS} items, got {len(bullets)}")

    phrases = data.get("script_phrases")
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        errors.append("script_phrases must be a list of non-empty strings")
        phrases = []
    elif len(phrases) < 6:
        errors.append("script_phrases must be a full script (at least 6 phrases)")
    elif not _CTA.search(" ".join(phrases[-3:])):
        errors.append("script must end with the strategy-session invitation")

    for key in ("facebook_post", "linkedin_post", "interviewer_prompt"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} is required")

    phrase_ids = [f"p{i:03d}" for i in range(1, len(phrases) + 1)]
    phrase_positions = {pid: index for index, pid in enumerate(phrase_ids)}
    options = data.get("hook_options")
    if not isinstance(options, list) or not HOOK_OPTIONS_WRITTEN <= len(options) <= max_hooks:
        errors.append(
            f"hook_options must contain exactly {HOOK_OPTIONS_WRITTEN} openings"
            if max_hooks == HOOK_OPTIONS_WRITTEN
            else f"hook_options must contain {HOOK_OPTIONS_WRITTEN} to {max_hooks} openings"
        )
        options = []
    clean_options: list[dict[str, Any]] = []
    option_ids: set[str] = set()
    for option in options:
        if not isinstance(option, dict):
            errors.append("each hook option must be an object")
            continue
        clean = {
            key: str(option.get(key) or "").strip()
            for key in ("id", "text", "question", "payoff_phrase_id", "rationale")
        }
        moment_ids = [str(value) for value in (option.get("moment_ids") or []) if str(value)]
        if not all(clean.values()) or not moment_ids:
            errors.append("each hook needs text, question, payoff, evidence and rationale")
            continue
        if clean["id"] in option_ids:
            errors.append("hook option ids must be unique")
        option_ids.add(clean["id"])
        if clean["payoff_phrase_id"] not in phrase_positions:
            errors.append(f"hook {clean['id']} has an unknown payoff phrase")
        clean["moment_ids"] = moment_ids
        clean_options.append(clean)
    selected_hook_id = str(data.get("selected_hook_id") or "").strip()
    selected = next((item for item in clean_options if item["id"] == selected_hook_id), None)
    if selected is None:
        errors.append("selected_hook_id must identify one hook option")
    elif phrases and selected["text"] != phrases[0].strip():
        errors.append("the selected hook text must be the first spoken script phrase")

    beats = data.get("beats")
    if not isinstance(beats, list) or len(beats) != len(bullets):
        errors.append("beats must contain one ordered range for every bullet")
        beats = []
    clean_beats: list[dict[str, Any]] = []
    for expected_index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            errors.append("each beat must be an object")
            continue
        start_id = str(beat.get("start_phrase_id") or "")
        end_id = str(beat.get("end_phrase_id") or "")
        try:
            bullet_index = int(beat.get("bullet_index"))
        except (TypeError, ValueError):
            bullet_index = -1
        if bullet_index != expected_index:
            errors.append("beat bullet indexes must be sequential")
        if start_id not in phrase_positions or end_id not in phrase_positions:
            errors.append("beat range references an unknown phrase")
        elif phrase_positions[start_id] > phrase_positions[end_id]:
            errors.append("beat range ends before it starts")
        clean_beats.append(
            {
                "id": str(beat.get("id") or f"b{expected_index + 1:02d}"),
                "label": str(beat.get("label") or bullets[expected_index]).strip(),
                "bullet_index": bullet_index,
                "start_phrase_id": start_id,
                "end_phrase_id": end_id,
            }
        )

    public = [
        *(bullets or []),
        *(phrases or []),
        str(data.get("facebook_post") or ""),
        str(data.get("linkedin_post") or ""),
    ]
    public += [str(option.get("text") or "") for option in clean_options]
    for text in public:
        m = _GIVEAWAY.search(text) or _KEYWORD_CTA.search(text)
        if m:
            errors.append(f"giveaway-style CTA is not allowed: '{m.group(0)}'")
            break
    banned = first_banned(public)
    if banned:
        errors.append(f"banned vocabulary is not allowed: '{banned}'")

    if errors:
        raise PacketValidationError("; ".join(errors))
    clean_packet = {
        "bullets": [b.strip() for b in bullets],
        "script_phrases": [p.strip() for p in phrases],
        "facebook_post": data["facebook_post"].strip(),
        "linkedin_post": data["linkedin_post"].strip(),
        "interviewer_prompt": data["interviewer_prompt"].strip(),
        "hook_options": clean_options,
        "selected_hook_id": selected_hook_id,
        "beats": clean_beats,
        "self_check": data.get("self_check") if isinstance(data.get("self_check"), dict) else {},
    }
    # Third lane only. None for every evergreen packet, so nothing above changes
    # for the two lanes that already work.
    if news_terms is not None:
        from tce.editorial.news_packet import news_errors

        problems = news_errors(clean_packet, news_terms)
        if problems:
            raise PacketValidationError("; ".join(problems))
    return clean_packet


async def news_block_for(
    session: AsyncSession, ws: uuid.UUID, cand: TopicCandidate
) -> tuple[dict[str, Any] | None, str | None]:
    """The news block a packet carries, or (None, None) for any other idea.

    Taken from the stored appraisal, whose confirmed facts already survived the
    check that each quote is really in the announcement. Nothing is re-derived
    here, so a script can never gain a "fact" the appraisal did not verify.
    """
    from tce.models.news import NewsAppraisal, NewsItem

    if not cand.news_item_id:
        return None, None
    appraisal = (
        await session.execute(
            select(NewsAppraisal)
            .where(
                NewsAppraisal.workspace_id == ws,
                NewsAppraisal.news_item_id == cand.news_item_id,
                NewsAppraisal.verdict == "publish",
            )
            .order_by(NewsAppraisal.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if appraisal is None:
        return None, None
    item = await session.get(NewsItem, cand.news_item_id)

    def iso(value: Any) -> str | None:
        return value.isoformat() if value else None

    block = {
        "what_happened": appraisal.what_happened,
        "primary_url": (item.primary_url or item.url) if item else None,
        "publisher": item.publisher if item else None,
        "published_at": iso(item.published_at) if item else None,
        "expires_at": iso(appraisal.expires_at),
        "confirmed_facts": list(appraisal.confirmed_facts or []),
        "ziv_interpretation": list(appraisal.ziv_interpretation or []),
        "predictions": list(appraisal.predictions or []),
    }
    return block, appraisal.format


async def news_terms_for(
    session: AsyncSession, ws: uuid.UUID, candidate_id: Any
) -> list[str] | None:
    """The names a news idea's opening must not use, or None for any other idea.

    None is the important return: it is what keeps every evergreen packet on
    exactly the validation it had before the third lane existed.
    """
    from tce.editorial.news_packet import forbidden_terms_for
    from tce.models.news import NewsAppraisal, NewsItem

    cand = await session.get(TopicCandidate, coerce_uuid(candidate_id))
    if cand is None or cand.workspace_id != ws or not cand.news_item_id:
        return None
    item = await session.get(NewsItem, cand.news_item_id)
    appraisal = (
        await session.execute(
            select(NewsAppraisal)
            .where(
                NewsAppraisal.workspace_id == ws,
                NewsAppraisal.news_item_id == cand.news_item_id,
            )
            .order_by(NewsAppraisal.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ref = {"publisher": item.publisher} if item is not None else {}
    return forbidden_terms_for(ref, (appraisal.anchors if appraisal else None) or [])


async def _participants(session: AsyncSession, ws: uuid.UUID, cand: TopicCandidate) -> list[str]:
    names: list[str] = []
    source_ids = set()
    for cit in cand.citations_private or []:
        if cit.get("speaker"):
            names.append(cit["speaker"])
        if cit.get("source_id"):
            try:
                source_ids.add(uuid.UUID(str(cit["source_id"])))
            except ValueError:
                pass
    if source_ids:
        sources = (
            await session.execute(
                select(EvidenceSource).where(
                    EvidenceSource.workspace_id == ws, EvidenceSource.id.in_(source_ids)
                )
            )
        ).scalars()
        for src in sources:
            payload = src.payload_private or {}
            for turn in payload.get("turns") or []:
                if isinstance(turn, dict) and turn.get("speaker"):
                    names.append(turn["speaker"])
            for p in (payload.get("participants") or []) + (
                (src.meta or {}).get("participants") or []
            ):
                if isinstance(p, dict):
                    names.append(p.get("name"))
                elif isinstance(p, str):
                    names.append(p)
    return names


def safety_fields(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "bullets": packet["bullets"],
        "script_phrases": packet["script_phrases"],
        "facebook_post": packet["facebook_post"],
        "linkedin_post": packet["linkedin_post"],
        "interviewer_prompt": packet["interviewer_prompt"],
    }


def build_packet_prompt(strategy_text: str, cand: TopicCandidate, voice_block: str = "") -> str:
    # The moment_id is the only citation the validator accepts; without it in the
    # prompt the model invented labels ("ev1") and every packet failed (20-Sep-2026).
    evidence = [
        {
            "moment_id": str(c.get("moment_id") or ""),
            "claim_type": c.get("claim_type"),
            "speaker_confidence": c.get("speaker_confidence"),
            "translation_label": c.get("translation_label"),
            "sensitivity_flags": c.get("sensitivity_flags"),
            "excerpt_private": (c.get("excerpt_private") or "")[:800],
        }
        for c in (cand.citations_private or [])
    ]
    allowed_ids = [str(value) for value in (cand.moment_ids or [])]
    for item, fallback in zip(evidence, allowed_ids, strict=False):
        if not item["moment_id"]:
            item["moment_id"] = fallback
    parts = ["STRATEGY:\n" + (strategy_text or "(none)")]
    # His own words on this subject, when the corpus has any. Placed before the idea
    # so the register is set before the task is read.
    if voice_block:
        parts.append(voice_block)
    return "\n\n".join(
        [
            *parts,
            "SELECTED IDEA:\n"
            + json.dumps(
                {
                    "title": cand.title,
                    "lesson": cand.lesson,
                    "audience": cand.audience,
                    "public_angle": cand.public_angle,
                    "reasons_to_care": cand.reasons_to_care,
                    "public_safety_notes": cand.public_safety_notes,
                    "freshness_role": cand.freshness_role,
                    "editor_notes": cand.editor_notes,
                },
                indent=1,
            ),
            "PRIVATE EVIDENCE (for accuracy only; do not quote other speakers or customers).\n"
            "Every hook's moment_ids must be copied verbatim from the moment_id values below; "
            "inventing a label is a rejected packet:\n" + json.dumps(evidence, indent=1),
        ]
    )


async def build_packet(
    sessionmaker_or_session: SessionSource,
    workspace_id: uuid.UUID | str,
    candidate_id: uuid.UUID | str,
    *,
    on_activity: Any = None,
    resume_job_id: uuid.UUID | str | None = None,
    on_saved: Any = None,
) -> PacketOutcome:
    """Write one packet. `resume_job_id` re-attaches to an earlier request's job (after a
    restart) by replaying its stored request, so no second job is enqueued.

    `on_saved(session, candidate, replaced, packet, job_id)` is awaited inside the
    transaction that saves a packet over an earlier one, with the version it
    replaced at that moment, so what it records commits (or not) with the packet.
    """
    ws = coerce_uuid(workspace_id)

    def activity(msg: str, **kw: Any) -> None:
        if on_activity:
            on_activity(msg, **kw)

    async with open_session(sessionmaker_or_session) as session:
        cand = (
            await session.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == coerce_uuid(candidate_id),
                    TopicCandidate.workspace_id == ws,
                )
            )
        ).scalar_one_or_none()
        if cand is None:
            raise LookupError(str(candidate_id))
        if cand.status in ("rejected", "withdrawn"):
            return PacketOutcome(status="invalid", detail=f"candidate is {cand.status}")

        request: LLMRequest | None = None
        requeue = False
        if resume_job_id is not None:
            job = (
                await session.execute(
                    select(LLMJob).where(
                        LLMJob.id == coerce_uuid(resume_job_id),
                        LLMJob.workspace_id == ws,
                        LLMJob.job_type == JOB_TYPE,
                        LLMJob.run_id == cand.id,
                    )
                )
            ).scalar_one_or_none()
            nonce = parse_packet_header(job_prompt_text(job.request_json)) if job else None
            request = replay_request(job, packet_key_text(ws, nonce)) if nonce else None
            if request is None:
                return PacketOutcome(
                    status="failed",
                    job_id=job.id if job else None,
                    detail="the interrupted packet job could not be resumed; request a new packet",
                )
            requeue = job_can_requeue(job)
        else:
            # include_voice: his 36 patterns, the banned vocabulary and the meta-rule.
            # Without it the writer had never been shown how he sounds.
            strategy = await load_effective_strategy(session, ws, include_voice=True)
            voice_block, voice_used = await voice_retrieval.block_for_idea(
                session, ws, title=cand.title, lesson=cand.lesson
            )
            nonce = str(uuid.uuid4())
            # The header line lets a restarted process rebuild this job's key.
            prompt = f"PACKET REQUEST: {nonce}\n\n" + build_packet_prompt(
                strategy.text, cand, voice_block
            )
            if voice_used["samples"]:
                activity(
                    f"Writing in his voice: {len(voice_used['samples'])} stretches of his "
                    f"own speech ({voice_used['sample_words']} words) on this subject"
                )
            elif voice_used.get("error"):
                activity(f"Writing without the voice corpus: {voice_used['error']}")
            request = LLMRequest(
                job_type=JOB_TYPE,
                agent_name=AGENT_NAME,
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_PROMPT,
                output_schema=OUTPUT_SCHEMA,
                max_tokens=6000,
                prompt_version=PROMPT_VERSION,
                workspace_id=ws,
                run_id=cand.id,
                # one job per build request: regenerating must not replay an earlier
                # (possibly rejected) output
                idempotency_key=packet_key_text(ws, nonce),
            )
        activity("Waiting for subscription packet job" + (" (resumed)" if resume_job_id else ""))
        try:
            if requeue:
                llm = await _llm.complete(request, requeue_failed=True)
            else:
                llm = await _llm.complete(request)
        except LLMUnavailable as exc:
            return PacketOutcome(
                status=exc.status, job_id=exc.job_id, detail=exc.detail, retry_at=exc.retry_at
            )
        activity("Packet job returned; validating", job_id=llm.job_id)

        data = llm.structured
        if data is None:
            try:
                data = json.loads(llm.text)
            except (TypeError, ValueError):
                data = None
        news_terms = await news_terms_for(session, ws, cand.id)
        news_block, news_format = await news_block_for(session, ws, cand)
        try:
            clean = validate_packet_output(data, news_terms=news_terms)
        except PacketValidationError as exc:
            # Persist nothing; the job is reported as failed so it can be re-run.
            return PacketOutcome(
                status="failed",
                job_id=llm.job_id,
                detail="packet failed validation",
                errors=str(exc).split("; "),
            )
        cited_moments = {
            moment_id for option in clean["hook_options"] for moment_id in option["moment_ids"]
        }
        if not cited_moments.issubset({str(value) for value in (cand.moment_ids or [])}):
            return PacketOutcome(
                status="failed",
                job_id=llm.job_id,
                detail="packet hook cited evidence outside the selected idea",
                errors=["hook moment IDs must belong to the candidate"],
            )

        try:
            safety = scan_public_text(
                safety_fields(clean), participants=await _participants(session, ws, cand)
            )
        except Exception as exc:  # the scan itself broke: never report clean
            safety = {
                "checked": False,
                "status": "unevaluated",
                "issues": [],
                "error": type(exc).__name__,
            }
        safety["model_self_check"] = clean["self_check"]

        # A job's output is saved once, even if two requests resumed the same job.
        already = (
            await session.execute(
                select(RecordingPacket).where(
                    RecordingPacket.workspace_id == ws,
                    RecordingPacket.candidate_id == cand.id,
                    RecordingPacket.job_id == llm.job_id,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            clean_before = (already.public_safety or {}).get("status") == "clean"
            return PacketOutcome(
                status="ready" if clean_before else "issues",
                packet=packet_to_json(already),
                job_id=llm.job_id,
                detail="this packet job was already saved",
            )

        current_max = (
            await session.execute(
                select(func.max(RecordingPacket.version)).where(
                    RecordingPacket.workspace_id == ws, RecordingPacket.candidate_id == cand.id
                )
            )
        ).scalar_one_or_none() or 0
        older = (
            (
                await session.execute(
                    select(RecordingPacket).where(
                        RecordingPacket.workspace_id == ws,
                        RecordingPacket.candidate_id == cand.id,
                        RecordingPacket.status != "superseded",
                    )
                )
            )
            .scalars()
            .all()
        )
        # What this packet replaces is decided now, at save time: an edit made while
        # it was written is part of the script it replaces.
        replaced = max(older, key=lambda p: p.version) if older else None
        for old in older:
            old.status = "superseded"

        now = datetime.now(UTC).replace(tzinfo=None)
        packet = RecordingPacket(
            workspace_id=ws,
            candidate_id=cand.id,
            version=int(current_max) + 1,
            bullets=clean["bullets"],
            script_phrases=clean["script_phrases"],
            facebook_post=clean["facebook_post"],
            linkedin_post=clean["linkedin_post"],
            interviewer_prompt=clean["interviewer_prompt"],
            hook_options=clean["hook_options"],
            selected_hook_id=clean["selected_hook_id"],
            beats=clean["beats"],
            citations_private=list(cand.citations_private or []),
            public_safety=safety,
            status="ready" if safety["status"] == "clean" else "draft",
            prompt_version=PROMPT_VERSION,
            job_id=llm.job_id,
            created_at=now,
            updated_at=now,
            news_block=news_block,
            format=news_format,
        )
        session.add(packet)
        if on_saved is not None and replaced is not None:
            await session.flush()
            await on_saved(session, cand, replaced, packet, llm.job_id)
        await session.commit()
        activity(f"Packet v{packet.version} saved ({safety['status']})")
        return PacketOutcome(
            status="ready" if safety["status"] == "clean" else "issues",
            packet=packet_to_json(packet),
            job_id=llm.job_id,
            replaced_version=replaced.version if replaced is not None else None,
        )


async def list_packets(
    session: AsyncSession, workspace_id: uuid.UUID | str, candidate_id: uuid.UUID | str
) -> list[RecordingPacket]:
    return list(
        (
            await session.execute(
                select(RecordingPacket)
                .where(
                    RecordingPacket.workspace_id == coerce_uuid(workspace_id),
                    RecordingPacket.candidate_id == coerce_uuid(candidate_id),
                )
                .order_by(RecordingPacket.version.desc())
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Voice pass: score the openings, and rewrite them in his register when they fail
# ---------------------------------------------------------------------------

VOICE_PASS_JOB_TYPE = "recording_packet_voice"
VOICE_PASS_AGENT = "recording_voice_critic"
VOICE_PASS_PROMPT_VERSION = "recording_voice.v1"
# Same bar the Facebook and LinkedIn critic uses.
VOICE_PASS_MARK = 7

VOICE_PASS_SYSTEM = """\
You are the Voice Critic for Ziv Raviv's recording scripts. You judge the OPENINGS
of a script that is already written, against his documented voice, and you replace
them when they fail.

He recognises the AI default on sight and rejects it: the curiosity gap. "Here is
why...", "The truth about...", "What nobody tells you...", "Have you ever...",
any question, any withheld subject, any promise of a secret. Those score 3 or less
no matter how well written they are.

What passes is what he actually does: a flat statement that takes a position,
disagreeing with what the viewer believes or naming the mistake they are making.
The tension comes from disagreement, not from a gap.

Score 1-10. Seven or more passes and you return no replacements. Below seven you
return exactly three replacement openings, each:
- in his register, drawn from how he talks in the samples given to you, never
  quoting them and never reusing their examples or anyone's private situation,
- naming the belief it contradicts,
- citing only the evidence moment ids given to you, copied verbatim,
- with a payoff_phrase_id that exists in the script,
- with the first one being the strongest.

Return only JSON matching the schema."""

VOICE_PASS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "verdict", "violations", "hook_options"],
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["quote", "issue"],
                "properties": {
                    "quote": {"type": "string"},
                    "issue": {"type": "string"},
                },
            },
        },
        "hook_options": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "text",
                    "question",
                    "payoff_phrase_id",
                    "moment_ids",
                    "rationale",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "question": {"type": "string"},
                    "payoff_phrase_id": {"type": "string"},
                    "moment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "rationale": {"type": "string"},
                },
            },
        },
    },
}


def build_voice_pass_prompt(
    packet: RecordingPacket, cand: TopicCandidate, voice_spec: str, voice_block: str
) -> str:
    """Everything the critic needs: the rules, his own words, and the script as written."""
    phrases = list(packet.script_phrases or [])
    script = [{"id": f"p{i:03d}", "text": text} for i, text in enumerate(phrases, start=1)]
    openings = [
        {"id": o.get("id"), "text": o.get("text"), "rationale": o.get("rationale")}
        for o in (packet.hook_options or [])
    ]
    parts = ["HIS VOICE (the rules):\n" + (voice_spec or "(none)")]
    if voice_block:
        parts.append(voice_block)
    parts.append("THE IDEA:\n" + json.dumps({"title": cand.title, "lesson": cand.lesson}, indent=1))
    parts.append(
        "THE SCRIPT AS WRITTEN (phrase ids you may pay off):\n" + json.dumps(script, indent=1)
    )
    parts.append("THE OPENINGS TO JUDGE:\n" + json.dumps(openings, indent=1))
    parts.append(
        "EVIDENCE MOMENT IDS you may cite, copied verbatim:\n"
        + json.dumps([str(m) for m in (cand.moment_ids or [])], indent=1)
    )
    return "\n\n".join(parts)


def voice_pass_key_text(ws: uuid.UUID, packet_id: uuid.UUID, version: int) -> str:
    return f"{VOICE_PASS_JOB_TYPE}:{ws}:{packet_id}:{version}"


MORE_HOOKS_JOB_TYPE = "recording_packet_hooks"
MORE_HOOKS_AGENT = "recording_hook_writer"
MORE_HOOKS_PROMPT_VERSION = "recording_hooks.v1"
# How many openings a packet may end up holding. Three arrive with the script;
# a person who wants more usually wants a different angle, not a longer list.
MAX_HOOK_OPTIONS = 9

MORE_HOOKS_SYSTEM = """\
You write alternative openings for a video Ziv is about to record.

The script, the lesson and the evidence are fixed. Only the first spoken line
changes, and the rest of the script must still follow from it.

- An opening is a flat, plain statement that disagrees with what the viewer
  currently believes, or names the mistake they are making right now. Not a
  question, not a tease, not "here is why", and it never withholds the subject to
  create curiosity. Name the belief it contradicts and the phrase id that pays it off.
- Cite only the evidence moment ids given to you, copied verbatim.
- Be different from the openings that already exist: a new angle, a different
  entry point, not a rewording. Say in the rationale what is different about it.
- No hype, no promise the evidence does not support, no long dashes.

Return only JSON matching the schema."""

MORE_HOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hook_options"],
    "properties": {
        "hook_options": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "text",
                    "question",
                    "payoff_phrase_id",
                    "moment_ids",
                    "rationale",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "question": {"type": "string"},
                    "payoff_phrase_id": {"type": "string"},
                    "moment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}


def build_more_hooks_prompt(packet: RecordingPacket, cand: TopicCandidate, wanted: int) -> str:
    existing = [
        {"id": h.get("id"), "text": h.get("text"), "question": h.get("question")}
        for h in (packet.hook_options or [])
    ]
    phrases = [
        {"phrase_id": f"p{n + 1:03d}", "text": text}
        for n, text in enumerate(packet.script_phrases or [])
    ]
    evidence = [
        {
            "moment_id": str(c.get("moment_id") or ""),
            "claim_type": c.get("claim_type"),
            "excerpt_private": (c.get("excerpt_private") or "")[:400],
        }
        for c in (cand.citations_private or [])
    ]
    return "\n\n".join(
        [
            f"WRITE {wanted} NEW OPENING(S).",
            "THE IDEA:\n" + json.dumps({"title": cand.title, "lesson": cand.lesson}, indent=1),
            "OPENINGS THAT ALREADY EXIST (do not repeat or reword these):\n"
            + json.dumps(existing, indent=1),
            "THE SCRIPT (payoff_phrase_id must be one of these phrase_ids):\n"
            + json.dumps(phrases, indent=1),
            "EVIDENCE (moment_ids must be copied verbatim from here):\n"
            + json.dumps(evidence, indent=1),
        ]
    )


def merge_hook_options(
    existing: list[dict[str, Any]], fresh: list[dict[str, Any]], phrase_count: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Existing openings first, then the new ones that are usable and new.

    Returns the merged list and the reasons anything was dropped, so the caller
    can say "two of three were new" rather than silently returning fewer.
    """
    phrase_ids = {f"p{n + 1:03d}" for n in range(phrase_count)}
    seen_ids = {str(h.get("id")) for h in existing}
    seen_text = {str(h.get("text") or "").strip().casefold() for h in existing}
    merged = list(existing)
    dropped: list[str] = []
    if len(merged) >= MAX_HOOK_OPTIONS:
        return merged, [f"this script already has {MAX_HOOK_OPTIONS} openings"]
    for option in fresh:
        clean = {
            key: str(option.get(key) or "").strip()
            for key in ("id", "text", "question", "payoff_phrase_id", "rationale")
        }
        moment_ids = [str(value) for value in (option.get("moment_ids") or []) if str(value)]
        if not all(clean.values()) or not moment_ids:
            dropped.append("an opening was missing its question, payoff, evidence or reason")
            continue
        if clean["payoff_phrase_id"] not in phrase_ids:
            dropped.append(f"{clean['text'][:40]}...: payoff phrase is not in this script")
            continue
        if clean["text"].casefold() in seen_text:
            dropped.append(f"{clean['text'][:40]}...: same as an opening already there")
            continue
        # Ids are ours, not the model's: a collision would silently replace an
        # opening the person may be reading right now.
        index = len(merged) + 1
        while f"h{index}" in seen_ids:
            index += 1
        clean["id"] = f"h{index}"
        clean["moment_ids"] = moment_ids
        seen_ids.add(clean["id"])
        seen_text.add(clean["text"].casefold())
        merged.append(clean)
        if len(merged) >= MAX_HOOK_OPTIONS:
            dropped.append("stopped at the maximum number of openings")
            break
    return merged, dropped


async def more_hook_options(
    sessionmaker_or_session: Any,
    workspace_id: uuid.UUID | str,
    packet_id: uuid.UUID | str,
    *,
    wanted: int = 3,
) -> PacketOutcome:
    """Ask for more openings for a packet, as a new immutable version.

    The script, the bullets and the evidence do not change: only the list of
    openings grows, and the one in use stays in use. A take set already holding
    clips blocks this for the same reason it blocks choosing: the opening the
    person is reading must not move under them.
    """
    ws = coerce_uuid(workspace_id)
    async with open_session(sessionmaker_or_session) as session:
        packet = (
            await session.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == coerce_uuid(packet_id),
                    RecordingPacket.workspace_id == ws,
                )
            )
        ).scalar_one_or_none()
        if packet is None:
            return PacketOutcome(status="invalid", detail="packet not found")
        in_progress = (
            await session.execute(
                select(RecordingSession.packet_version).where(
                    RecordingSession.workspace_id == ws,
                    RecordingSession.candidate_id == packet.candidate_id,
                    RecordingSession.status.in_(RECORDING_IN_PROGRESS_STATUSES),
                )
            )
        ).first()
        if in_progress is not None:
            return PacketOutcome(
                status="invalid",
                detail=(
                    f"a take set is in progress on packet version {in_progress[0]}; "
                    "finish that session before asking for more openings"
                ),
            )
        if len(packet.hook_options or []) >= MAX_HOOK_OPTIONS:
            return PacketOutcome(
                status="invalid",
                detail=f"this script already has {MAX_HOOK_OPTIONS} openings to choose from",
            )
        cand = (
            await session.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == packet.candidate_id, TopicCandidate.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        if cand is None:
            return PacketOutcome(status="invalid", detail="idea not found")

        # A job that already finished for this packet is applied rather than
        # paid for twice. The worker keeps running while the API restarts (a
        # deploy, a crash), and the in-memory task that was waiting for it dies:
        # twice on 20-Sep a good answer was written, billed and then dropped.
        done = (
            await session.execute(
                select(LLMJob)
                .where(
                    LLMJob.workspace_id == ws,
                    LLMJob.job_type == MORE_HOOKS_JOB_TYPE,
                    LLMJob.run_id == packet.candidate_id,
                    LLMJob.status == "succeeded",
                )
                .order_by(LLMJob.completed_at.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        if done is not None and done.id != packet.job_id:
            applied = await _apply_more_hooks(session, ws, packet, cand, done.result_json, done.id)
            if applied.status == "ok":
                return applied

        nonce = str(uuid.uuid4())
        request = LLMRequest(
            job_type=MORE_HOOKS_JOB_TYPE,
            agent_name=MORE_HOOKS_AGENT,
            messages=[
                {
                    "role": "user",
                    "content": f"MORE OPENINGS: {nonce}\n\n"
                    + build_more_hooks_prompt(packet, cand, wanted),
                }
            ],
            system=MORE_HOOKS_SYSTEM,
            output_schema=MORE_HOOKS_SCHEMA,
            max_tokens=2000,
            prompt_version=MORE_HOOKS_PROMPT_VERSION,
            workspace_id=ws,
            run_id=cand.id,
            idempotency_key=f"more-hooks:{ws}:{packet.id}:{nonce}",
        )
        try:
            llm = await _llm.complete(request)
        except LLMUnavailable as exc:
            return PacketOutcome(
                status=exc.status, job_id=exc.job_id, detail=exc.detail, retry_at=exc.retry_at
            )

        return await _apply_more_hooks(
            session, ws, packet, cand, llm.structured or llm.text, llm.job_id
        )


async def _apply_more_hooks(
    session: AsyncSession,
    ws: uuid.UUID,
    packet: RecordingPacket,
    cand: TopicCandidate,
    payload: Any,
    job_id: uuid.UUID | None,
) -> PacketOutcome:
    """Turn one finished job's answer into the next packet version.

    The version is built on what is current NOW, not on `packet`, which was read
    before the minutes-long wait for the worker. An edit made in that wait (a
    point changed on the voice call, a line fixed in the workspace) wrote a newer
    version; cloning the stale one silently put the old text back as current, and
    the edit's undo then refused because the text had "changed again".
    """
    current = (
        (
            await session.execute(
                select(RecordingPacket)
                .where(
                    RecordingPacket.workspace_id == ws,
                    RecordingPacket.candidate_id == packet.candidate_id,
                    RecordingPacket.status != "superseded",
                )
                .order_by(RecordingPacket.version.desc())
                .limit(1)
                # The session may still hold the rows it read before the wait;
                # take what the database says now.
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    if current is None:
        return PacketOutcome(
            status="invalid", job_id=job_id, detail="this script is no longer here"
        )
    taking = (
        await session.execute(
            select(RecordingSession.packet_version).where(
                RecordingSession.workspace_id == ws,
                RecordingSession.candidate_id == packet.candidate_id,
                RecordingSession.status.in_(RECORDING_IN_PROGRESS_STATUSES),
            )
        )
    ).first()
    if taking is not None:
        return PacketOutcome(
            status="invalid",
            job_id=job_id,
            detail=(
                f"a take set started on packet version {taking[0]} while the openings were "
                "being written; finish that session and ask for more openings again"
            ),
        )
    packet = current
    data = payload if isinstance(payload, dict) else None
    if data is None:
        try:
            data = json.loads(payload or "")
        except (TypeError, ValueError):
            data = None
    fresh = (data or {}).get("hook_options")
    if not isinstance(fresh, list) or not fresh:
        return PacketOutcome(status="failed", job_id=job_id, detail="no usable opening came back")
    allowed = {str(value) for value in (cand.moment_ids or [])}
    fresh = [
        option
        for option in fresh
        if isinstance(option, dict)
        and {str(m) for m in (option.get("moment_ids") or [])}.issubset(allowed)
    ]
    if not fresh:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail="the new openings cited evidence outside this idea",
        )
    merged, dropped = merge_hook_options(
        list(packet.hook_options or []), fresh, len(packet.script_phrases or [])
    )
    added = len(merged) - len(packet.hook_options or [])
    if not added:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail="; ".join(dropped) or "nothing new came back",
            errors=dropped,
        )
    maximum = (
        await session.execute(
            select(func.max(RecordingPacket.version)).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id == packet.candidate_id,
            )
        )
    ).scalar_one() or 0
    now = datetime.now(UTC).replace(tzinfo=None)
    clone = RecordingPacket(
        workspace_id=ws,
        candidate_id=packet.candidate_id,
        version=int(maximum) + 1,
        bullets=list(packet.bullets or []),
        script_phrases=list(packet.script_phrases or []),
        facebook_post=packet.facebook_post,
        linkedin_post=packet.linkedin_post,
        interviewer_prompt=packet.interviewer_prompt,
        hook_options=merged,
        selected_hook_id=packet.selected_hook_id,
        beats=list(packet.beats or []),
        citations_private=list(packet.citations_private or []),
        public_safety=dict(packet.public_safety or {}),
        status=packet.status,
        prompt_version=packet.prompt_version,
        news_block=packet.news_block,
        format=packet.format,
        job_id=job_id,
        created_at=now,
        updated_at=now,
    )
    session.add(clone)
    # The version it was built on stays readable; it is simply no longer current.
    packet.status = "superseded"
    await session.commit()
    return PacketOutcome(
        status="ok",
        job_id=job_id,
        packet=packet_to_json(clone),
        detail=f"{added} new opening(s) to choose from",
        errors=dropped,
    )


async def voice_pass(
    sessionmaker_or_session: Any,
    workspace_id: uuid.UUID | str,
    packet_id: uuid.UUID | str,
) -> PacketOutcome:
    """Score a script's openings against his voice, and rewrite them if they fail.

    One subscription job. A pass changes nothing and says so; a fail appends three
    replacements as a new packet version, so the openings it judged stay readable
    next to the ones it wrote. A take set already holding clips blocks the pass for
    the same reason it blocks choosing: what he is reading must not move.
    """
    ws = coerce_uuid(workspace_id)
    async with open_session(sessionmaker_or_session) as session:
        packet = (
            await session.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == coerce_uuid(packet_id),
                    RecordingPacket.workspace_id == ws,
                )
            )
        ).scalar_one_or_none()
        if packet is None:
            return PacketOutcome(status="invalid", detail="packet not found")
        in_progress = (
            await session.execute(
                select(RecordingSession.packet_version).where(
                    RecordingSession.workspace_id == ws,
                    RecordingSession.candidate_id == packet.candidate_id,
                    RecordingSession.status.in_(RECORDING_IN_PROGRESS_STATUSES),
                )
            )
        ).first()
        if in_progress is not None:
            return PacketOutcome(
                status="invalid",
                detail=(
                    f"a take set is in progress on packet version {in_progress[0]}; "
                    "finish that session before rewriting the openings"
                ),
            )
        cand = (
            await session.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == packet.candidate_id, TopicCandidate.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        if cand is None:
            return PacketOutcome(status="invalid", detail="idea not found")

        # A job that already finished for this packet is applied rather than paid
        # for twice: the worker keeps running while the API restarts.
        done = (
            await session.execute(
                select(LLMJob)
                .where(
                    LLMJob.workspace_id == ws,
                    LLMJob.job_type == VOICE_PASS_JOB_TYPE,
                    LLMJob.run_id == packet.candidate_id,
                    LLMJob.status == "succeeded",
                )
                .order_by(LLMJob.completed_at.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        if done is not None and done.id != packet.job_id:
            applied = await _apply_voice_pass(session, ws, packet, cand, done.result_json, done.id)
            if applied.status == "ok":
                return applied

        strategy = await load_effective_strategy(session, ws, include_voice=True)
        voice_block, _used = await voice_retrieval.block_for_idea(
            session, ws, title=cand.title, lesson=cand.lesson
        )
        nonce = str(uuid.uuid4())
        request = LLMRequest(
            job_type=VOICE_PASS_JOB_TYPE,
            agent_name=VOICE_PASS_AGENT,
            messages=[
                {
                    "role": "user",
                    "content": f"VOICE PASS: {nonce}\n\n"
                    + build_voice_pass_prompt(packet, cand, strategy.text, voice_block),
                }
            ],
            system=VOICE_PASS_SYSTEM,
            output_schema=VOICE_PASS_SCHEMA,
            max_tokens=3000,
            prompt_version=VOICE_PASS_PROMPT_VERSION,
            workspace_id=ws,
            run_id=cand.id,
            idempotency_key=f"voice-pass:{ws}:{packet.id}:{nonce}",
        )
        try:
            llm = await _llm.complete(request)
        except LLMUnavailable as exc:
            return PacketOutcome(
                status=exc.status, job_id=exc.job_id, detail=exc.detail, retry_at=exc.retry_at
            )
        return await _apply_voice_pass(
            session, ws, packet, cand, llm.structured or llm.text, llm.job_id
        )


def _merged_id_for(merged: list[dict[str, Any]], wanted: dict[str, Any]) -> str | None:
    """The id the merge gave this opening, found by its text."""
    text = str(wanted.get("text") or "").strip().casefold()
    for option in merged:
        if str(option.get("text") or "").strip().casefold() == text:
            return str(option.get("id"))
    return None


async def _apply_voice_pass(
    session: AsyncSession,
    ws: uuid.UUID,
    packet: RecordingPacket,
    cand: TopicCandidate,
    payload: Any,
    job_id: uuid.UUID | None,
) -> PacketOutcome:
    """Turn the critic's answer into either a verdict or the next packet version."""
    data = payload if isinstance(payload, dict) else None
    if data is None:
        try:
            data = json.loads(payload or "")
        except (TypeError, ValueError):
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("score"), int):
        # A critic that returned nothing usable has not judged anything. It must
        # never read as a pass.
        return PacketOutcome(
            status="failed", job_id=job_id, detail="the voice pass returned no score"
        )
    score = int(data["score"])
    violations = [
        f"{v.get('quote', '')}: {v.get('issue', '')}".strip(": ")
        for v in (data.get("violations") or [])
        if isinstance(v, dict)
    ]
    if score >= VOICE_PASS_MARK and data.get("verdict") != "revise":
        return PacketOutcome(
            status="ok",
            job_id=job_id,
            packet=packet_to_json(packet),
            detail=f"The openings sound like him ({score} out of 10). Nothing rewritten.",
            errors=violations,
        )

    fresh = data.get("hook_options")
    if not isinstance(fresh, list) or not fresh:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail=f"scored {score} out of 10 but sent no replacement openings",
            errors=violations,
        )
    allowed = {str(value) for value in (cand.moment_ids or [])}
    fresh = [
        option
        for option in fresh
        if isinstance(option, dict)
        and {str(m) for m in (option.get("moment_ids") or [])}.issubset(allowed)
    ]
    banned = first_banned([str(o.get("text") or "") for o in fresh])
    if banned:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail=f"a replacement opening used banned vocabulary: '{banned}'",
            errors=violations,
        )
    if not fresh:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail="the replacement openings cited evidence outside this idea",
            errors=violations,
        )
    merged, dropped = merge_hook_options(
        list(packet.hook_options or []), fresh, len(packet.script_phrases or [])
    )
    added = len(merged) - len(packet.hook_options or [])
    if not added:
        return PacketOutcome(
            status="failed",
            job_id=job_id,
            detail="; ".join(dropped) or "nothing usable came back",
            errors=violations + dropped,
        )
    maximum = (
        await session.execute(
            select(func.max(RecordingPacket.version)).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id == packet.candidate_id,
            )
        )
    ).scalar_one() or 0
    now = datetime.now(UTC).replace(tzinfo=None)
    clone = RecordingPacket(
        workspace_id=ws,
        candidate_id=packet.candidate_id,
        version=int(maximum) + 1,
        bullets=list(packet.bullets or []),
        script_phrases=list(packet.script_phrases or []),
        facebook_post=packet.facebook_post,
        linkedin_post=packet.linkedin_post,
        interviewer_prompt=packet.interviewer_prompt,
        hook_options=merged,
        # The first replacement becomes the one in use: it is the point of the pass.
        # Matched by TEXT, because merge_hook_options deliberately re-ids incoming
        # openings - selecting the model's own id left the packet pointing at an id
        # that did not exist, and the recorder silently fell back to the old opening.
        selected_hook_id=_merged_id_for(merged, fresh[0]) or packet.selected_hook_id,
        beats=list(packet.beats or []),
        citations_private=list(packet.citations_private or []),
        public_safety=dict(packet.public_safety or {}),
        status=packet.status,
        prompt_version=packet.prompt_version,
        news_block=packet.news_block,
        format=packet.format,
        job_id=job_id,
        created_at=now,
        updated_at=now,
    )
    session.add(clone)
    await session.commit()
    return PacketOutcome(
        status="ok",
        job_id=job_id,
        packet=packet_to_json(clone),
        detail=(
            f"The openings scored {score} out of 10, so {added} were rewritten in his "
            "voice. The originals are still on the script to compare."
        ),
        errors=violations + dropped,
    )


async def choose_hook(
    session: AsyncSession,
    workspace_id: uuid.UUID | str,
    packet_id: uuid.UUID | str,
    hook_id: str,
) -> RecordingPacket:
    """Create a validated packet version with a different compatible opening.

    Existing packets are immutable because recordings bind to their exact version.
    While any take set of this candidate is in progress the opening is frozen for
    the whole candidate: the recording queue shows one packet per candidate (the
    newest), so a newer version created now would hide the take set that is
    still being recorded. A draft session (opened, nothing recorded) does not
    block; the new version simply gets its own session.
    """
    ws = coerce_uuid(workspace_id)
    original = (
        await session.execute(
            select(RecordingPacket).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.id == coerce_uuid(packet_id),
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise PacketValidationError("packet not found")
    in_progress = (
        await session.execute(
            select(RecordingSession.packet_version).where(
                RecordingSession.workspace_id == ws,
                RecordingSession.candidate_id == original.candidate_id,
                RecordingSession.status.in_(RECORDING_IN_PROGRESS_STATUSES),
            )
        )
    ).first()
    if in_progress is not None:
        raise PacketValidationError(
            f"a take set is in progress on packet version {in_progress[0]}; "
            "finish that session before changing the opening"
        )
    options = list(original.hook_options or [])
    selected = next((item for item in options if item.get("id") == hook_id), None)
    if selected is None:
        raise PacketValidationError("hook option not found")
    phrases = list(original.script_phrases or [])
    if not phrases:
        raise PacketValidationError("packet has no script")
    phrases[0] = str(selected.get("text") or "").strip()
    clean = validate_packet_output(
        {
            "bullets": list(original.bullets or []),
            "script_phrases": phrases,
            "facebook_post": original.facebook_post,
            "linkedin_post": original.linkedin_post,
            "interviewer_prompt": original.interviewer_prompt,
            "hook_options": options,
            "selected_hook_id": hook_id,
            "beats": list(original.beats or []),
        },
        max_hooks=MAX_HOOK_OPTIONS,
        # Switching to another opening must not smuggle a news headline back in.
        news_terms=await news_terms_for(session, ws, original.candidate_id),
    )
    maximum = (
        await session.execute(
            select(func.max(RecordingPacket.version)).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id == original.candidate_id,
            )
        )
    ).scalar_one() or 0
    now = datetime.now(UTC).replace(tzinfo=None)
    clone = RecordingPacket(
        workspace_id=ws,
        candidate_id=original.candidate_id,
        version=int(maximum) + 1,
        bullets=clean["bullets"],
        script_phrases=clean["script_phrases"],
        facebook_post=clean["facebook_post"],
        linkedin_post=clean["linkedin_post"],
        interviewer_prompt=clean["interviewer_prompt"],
        hook_options=clean["hook_options"],
        selected_hook_id=clean["selected_hook_id"],
        beats=clean["beats"],
        citations_private=list(original.citations_private or []),
        public_safety=dict(original.public_safety or {}),
        status="ready" if (original.public_safety or {}).get("status") == "clean" else "draft",
        prompt_version=original.prompt_version,
        news_block=original.news_block,
        format=original.format,
        job_id=original.job_id,
        created_at=now,
        updated_at=now,
    )
    session.add(clone)
    await session.flush()
    return clone
