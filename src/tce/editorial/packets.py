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
from tce.editorial.common import SessionSource, coerce_uuid, open_session, packet_to_json
from tce.editorial.safety import scan_public_text
from tce.llm import LLMRequest, LLMUnavailable
from tce.models.editorial import EvidenceSource, RecordingPacket, TopicCandidate
from tce.services.strategy_loader import load_effective_strategy

PROMPT_VERSION = "recording_packet.v1"
JOB_TYPE = "recording_packet"
AGENT_NAME = "recording_packet_writer"
MIN_BULLETS = 5
MAX_BULLETS = 7

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
) -> PacketOutcome:
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

        strategy = await load_effective_strategy(session, ws)
        activity("Waiting for subscription packet job")
        try:
            llm = await _llm.complete(
                LLMRequest(
                    job_type=JOB_TYPE,
                    agent_name=AGENT_NAME,
                    messages=[
                        {"role": "user", "content": build_packet_prompt(strategy.text, cand)}
                    ],
                    system=SYSTEM_PROMPT,
                    output_schema=OUTPUT_SCHEMA,
                    max_tokens=6000,
                    prompt_version=PROMPT_VERSION,
                    workspace_id=ws,
                    run_id=cand.id,
                    # one job per build request: regenerating must not replay an earlier
                    # (possibly rejected) output
                    idempotency_key=f"recording_packet:{ws}:{uuid.uuid4()}",
                )
            )
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
