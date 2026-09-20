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

SYSTEM_PROMPT = """\
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
- hook_options: exactly three honest openings, ranked best first. Each names the unresolved
  viewer question, the phrase ID that pays it off, the evidence moment IDs that support it,
  and a private ranking rationale. The first option is selected by default and its text must
  be the first spoken script phrase. Curiosity cannot hide or distort the central lesson.
- beats: one beat for each walking bullet. Use stable phrase IDs p001, p002 and so on and map
  every beat to an ordered inclusive phrase range.
- self_check: report honestly whether each rule holds.

Return only JSON matching the schema."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packet": self.packet,
            "job_id": str(self.job_id) if self.job_id else None,
            "detail": self.detail,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
            "errors": self.errors,
        }


def validate_packet_output(data: Any) -> dict[str, Any]:
    """Return a cleaned packet dict or raise PacketValidationError with all problems."""
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
    if not isinstance(options, list) or len(options) != 3:
        errors.append("hook_options must contain exactly three openings")
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
    for text in public:
        m = _GIVEAWAY.search(text) or _KEYWORD_CTA.search(text)
        if m:
            errors.append(f"giveaway-style CTA is not allowed: '{m.group(0)}'")
            break

    if errors:
        raise PacketValidationError("; ".join(errors))
    return {
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


def build_packet_prompt(strategy_text: str, cand: TopicCandidate) -> str:
    evidence = [
        {
            "claim_type": c.get("claim_type"),
            "speaker_confidence": c.get("speaker_confidence"),
            "translation_label": c.get("translation_label"),
            "sensitivity_flags": c.get("sensitivity_flags"),
            "excerpt_private": (c.get("excerpt_private") or "")[:800],
        }
        for c in (cand.citations_private or [])
    ]
    return "\n\n".join(
        [
            "STRATEGY:\n" + (strategy_text or "(none)"),
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
            "PRIVATE EVIDENCE (for accuracy only; do not quote other speakers or customers):\n"
            + json.dumps(evidence, indent=1),
        ]
    )


async def build_packet(
    sessionmaker_or_session: SessionSource,
    workspace_id: uuid.UUID | str,
    candidate_id: uuid.UUID | str,
    *,
    on_activity: Any = None,
    resume_job_id: uuid.UUID | str | None = None,
) -> PacketOutcome:
    """Write one packet. `resume_job_id` re-attaches to an earlier request's job (after a
    restart) by replaying its stored request, so no second job is enqueued."""
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
            strategy = await load_effective_strategy(session, ws)
            nonce = str(uuid.uuid4())
            # The header line lets a restarted process rebuild this job's key.
            prompt = f"PACKET REQUEST: {nonce}\n\n" + build_packet_prompt(strategy.text, cand)
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
        try:
            clean = validate_packet_output(data)
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
        )
        session.add(packet)
        await session.commit()
        activity(f"Packet v{packet.version} saved ({safety['status']})")
        return PacketOutcome(
            status="ready" if safety["status"] == "clean" else "issues",
            packet=packet_to_json(packet),
            job_id=llm.job_id,
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
        }
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
        job_id=original.job_id,
        created_at=now,
        updated_at=now,
    )
    session.add(clone)
    await session.flush()
    return clone
