"""TCE-owned GPT-Live WebRTC sessions for the week and Jennifer."""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.brain import ask_brain, client_config
from tce.standalone.jobs import queue_job
from tce.standalone.models import StandaloneLiveSession, StandaloneRecording, StandaloneSecret
from tce.standalone.secrets import decrypt
from tce.standalone.workflow import _talk_context

router = APIRouter(prefix="/api/live", dependencies=[Depends(current_principal)])


class LiveStart(BaseModel):
    sdp: str = Field(min_length=10, max_length=100000)
    mode: str
    context_id: uuid.UUID | None = None


class LiveDelegation(BaseModel):
    session_id: str = Field(min_length=8, max_length=160)
    delegation_id: str = Field(min_length=8, max_length=160)
    transcript: str = Field(min_length=1, max_length=5000)
    history: str = Field(default="", max_length=8000)


async def parse_live_reply(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    mode: str,
    context_id: uuid.UUID | None,
    raw: str,
) -> dict:
    """Keep a spoken answer; accept only a client-scoped, inspectable cut proposal."""
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return {"answer": raw.strip()[:1800], "proposal": None}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("answer"), str):
        return {"answer": raw.strip()[:1800], "proposal": None}
    answer = parsed["answer"].strip()[:1800]
    if not answer:
        raise HTTPException(status_code=422, detail="Voice reply has no answer")
    result = {"answer": answer, "proposal": None}
    proposal = parsed.get("proposal")
    if mode != "jennifer" or context_id is None or not isinstance(proposal, dict):
        return result
    if proposal.get("kind") != "trim":
        return result
    start, end = proposal.get("start_s"), proposal.get("end_s")
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
        or not math.isfinite(start) or not math.isfinite(end)
    ):
        return result
    recording = (
        await db.execute(
            select(StandaloneRecording).where(
                StandaloneRecording.id == context_id,
                StandaloneRecording.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if recording is None:
        return result
    duration = float((recording.qc or {}).get("duration_s") or 0)
    if not 0 <= start < end <= duration + 0.1:
        return result
    result["proposal"] = {
        "kind": "trim",
        "recording_id": str(context_id),
        "start_s": round(float(start), 2),
        "end_s": round(float(end), 2),
        "note": str(proposal.get("note") or "Spoken edit proposal")[:400],
    }
    return result


async def _create_provider_session(key: str, session: dict, sdp: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(
                "https://api.openai.com/v1/live/sessions",
                headers={"Authorization": f"Bearer {key}"},
                json={"session": session, "transport": {"type": "webrtc", "sdp": sdp}},
            )
        if response.status_code != 201:
            raise HTTPException(
                status_code=503, detail=f"Live voice returned HTTP {response.status_code}"
            )
        result = response.json()
        if not result.get("session", {}).get("id") or not result.get("transport", {}).get("sdp"):
            raise HTTPException(status_code=502, detail="Live voice returned an incomplete answer")
        return result
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Live voice is unavailable") from exc


@router.post("/session", status_code=201)
async def start_live(
    body: LiveStart,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    if body.mode not in {"week", "jennifer"}:
        raise HTTPException(status_code=422, detail="Choose the week or Jennifer")
    if body.mode == "jennifer" and body.context_id is None:
        raise HTTPException(status_code=422, detail="Choose a recording for Jennifer")
    config = await client_config(db, principal.workspace_id)
    context = await _talk_context(db, principal.workspace_id, body.mode, body.context_id)
    secret = (
        await db.execute(
            select(StandaloneSecret).where(
                StandaloneSecret.workspace_id == principal.workspace_id,
                StandaloneSecret.kind == "openai_live",
            )
        )
    ).scalar_one_or_none()
    if secret is None or secret.verified_at is None:
        raise HTTPException(status_code=409, detail="Verify your OpenAI live key in Settings")
    today = datetime.now(UTC) - timedelta(hours=24)
    count = (
        await db.execute(
            select(func.count(StandaloneLiveSession.id)).where(
                StandaloneLiveSession.workspace_id == principal.workspace_id,
                StandaloneLiveSession.created_at >= today.replace(tzinfo=None),
            )
        )
    ).scalar_one()
    if count >= 30:
        raise HTTPException(status_code=429, detail="Daily live voice session limit reached")
    key = decrypt(secret.encrypted_value, principal.workspace_id, "openai_live")
    instructions = (
        f"You are speaking with {config['display_name']}. Be concise and conversational. "
        f"Audience: {config.get('audience', '')}. Voice: {config.get('voice_notes', '')}. "
        f"Avoid: {config.get('avoid', '')}. "
        + (
            "Discuss this week's selected ideas. Suggest changes but do not claim to save them. "
            if body.mode == "week"
            else "You are Jennifer, the video editor. Discuss edit ideas. "
            "You have technical checks "
            "and notes, not the video itself. Never claim to have watched it. "
        )
        + f"Context: {context[:8000]}"
    )
    session = {
        "model": "gpt-live-1",
        "delegation": {"type": "client"},
        "instructions": instructions,
        "audio": {"output": {"voice": "marin"}},
    }
    result = await _create_provider_session(key, session, body.sdp)
    db.add(
        StandaloneLiveSession(
            workspace_id=principal.workspace_id,
            account_id=principal.account_id,
            mode=body.mode,
            context_id=body.context_id,
            provider_session_id=result["session"]["id"],
        )
    )
    return {"session_id": result["session"]["id"], "sdp": result["transport"]["sdp"]}


@router.post("/delegation")
async def delegate_to_client_brain(
    body: LiveDelegation,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    session = (
        await db.execute(
            select(StandaloneLiveSession).where(
                StandaloneLiveSession.workspace_id == principal.workspace_id,
                StandaloneLiveSession.account_id == principal.account_id,
                StandaloneLiveSession.provider_session_id == body.session_id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Voice session not found")
    if session.created_at.replace(tzinfo=UTC) < datetime.now(UTC) - timedelta(hours=1):
        raise HTTPException(status_code=410, detail="Voice session expired")
    context = await _talk_context(db, principal.workspace_id, session.mode, session.context_id)
    mode_instruction = (
        "Help plan this week's ideas. You may suggest changes, but do not claim to save them."
        if session.mode == "week"
        else "You are Jennifer, the video editor. Discuss cuts and pacing using notes and "
        "technical checks only. You have not watched the full video. Propose a trim only "
        "when the client gave clear timing. Never claim to have edited it."
    )
    prompt = (
        "Return JSON with answer (short spoken response) and proposal (null or an object). "
        "Only for Jennifer, when the client explicitly gave trim timing, proposal may be "
        '{"kind":"trim","start_s":number,"end_s":number,"note":"brief reason"}. '
        "Timing is measured on the original video. Never invent a cut from sampled frames. "
        "The client must inspect and apply any proposal.\n"
        f"Workspace context: {context[:7000]}\nRecent transcript: {body.history[-6000:]}\n"
        f"Latest user speech: {body.transcript}"
    )
    system = "You support a live voice conversation. " + mode_instruction
    config = await client_config(db, principal.workspace_id)
    if config.get("brain_mode") == "claude_code":
        job = await queue_job(
            db,
            principal.workspace_id,
            "live_reply",
            {
                "prompt": system + "\n" + prompt,
                "mode": session.mode,
                "context_id": str(session.context_id) if session.context_id else None,
            },
        )
        return JSONResponse(
            status_code=202,
            content={"delegation_id": body.delegation_id, "job_id": str(job.id)},
        )
    raw = await ask_brain(db, principal.workspace_id, system, prompt, max_tokens=450)
    reply = await parse_live_reply(
        db, principal.workspace_id, session.mode, session.context_id, raw
    )
    return {"delegation_id": body.delegation_id, **reply}
