"""/production/agent-talks: a filmed voice call with an agent, sent in pieces (contract C4).

The KM BOT voice service relays what the call's page records: it creates the talk when
he taps record, sends each MediaRecorder slice as it is spooled, and finishes the talk
when the call ends (or its sweeper finds the recording idle). The private key stays on
that server; a browser never holds it. Auth and the workspace come from
`require_private_workspace`, like every /production route, and every query filters on
the workspace explicitly.

1. POST /production/agent-talks {"agent","call_id","started_at","mime"}
   -> 201 {"talk_id","status":"recording"} (200 with the same talk when it was sent before)
2. PUT /production/agent-talks/{talk_id}/chunks/{seq} raw bytes, seq from 0
   -> {"ok":true,"bytes_total":N}; the same piece again changes nothing
3. POST /production/agent-talks/{talk_id}/finish {"ended_at","duration_ms","transcript","edit"}
   -> {"upload_id","status","edit","archived"}: the pieces joined (remuxed, never
   re-encoded), a library video with source "agent_talk" titled "Talk with <Agent>,
   <date>". With "edit": true (or no "edit", for an older caller) its edit starts unless
   TCE_PRODUCTION_AUTO_EDIT is off. With "edit": false (4-Oct, C4.1: he chose "Archive,
   don't edit") the video is stored archived: no edit, no check by Jennifer, not in
   Still to do; the Library's Archived list offers "Edit this now". Finishing again
   returns the same video and keeps the first choice, and says so.
   With "background": true (23-Nov, wait-less B9; the contract is in claim_finish) the
   finish is written down on the talk and answered 202 at once, the join runs behind
   the answer, and GET /production/agent-talks/{talk_id} says in "finish" how it ended.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.api.private_access import require_private_workspace, scoped_editor_workspace
from tce.db.session import get_db
from tce.editorial.agent_talk_topics import talk_topic
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tce.production.agent_talks import TalkError
from tce.settings import settings

router = APIRouter(prefix="/production/agent-talks", tags=["production"])

_finish_locks: dict[uuid.UUID, asyncio.Lock] = {}
# 23-Nov (wait-less B9): a finish answered before its join. The talk's status says it is
# claimed, and its join_meta["claim"] holds what that finish carried (written whole, the
# transcript too, before the 202), so a restart loses none of it; resume_claimed_talks
# joins it after a restart. A plain string in a String(20) column: no migration.
FINISHING = "finishing"
_claim_locks: dict[uuid.UUID, asyncio.Lock] = {}
_claim_tasks: dict[uuid.UUID, asyncio.Task] = {}
_CLAIM_WAITS = 3


def _finish_lock(talk_id: uuid.UUID) -> asyncio.Lock:
    """One finish of a talk at a time in this process: the call ending and the sweeper
    finding it idle can both ask, and must make one video."""
    lock = _finish_locks.get(talk_id)
    if lock is None:
        lock = _finish_locks[talk_id] = asyncio.Lock()
    return lock


def _claim_lock(talk_id: uuid.UUID) -> asyncio.Lock:
    """Held for a moment by whoever writes a claim's end, or adds to a claim: a later
    finish's transcript is never written over by the join's own last write (B9)."""
    lock = _claim_locks.get(talk_id)
    if lock is None:
        lock = _claim_locks[talk_id] = asyncio.Lock()
    return lock


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _root() -> Path:
    return Path(settings.evidence_upload_dir)


class AgentTalkCreate(BaseModel):
    agent: str = Field(min_length=1, max_length=80)
    call_id: str = Field(min_length=1, max_length=200)
    started_at: str = Field(min_length=1, max_length=64)
    mime: str = Field(min_length=1, max_length=120)


class TranscriptLine(BaseModel):
    who: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=20000)
    t_ms: float | None = None


class AgentTalkFinish(BaseModel):
    ended_at: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    transcript: list[TranscriptLine] | None = Field(default=None, max_length=50000)
    # 4-Oct (C4.1): his choice after Stop. False keeps the video archived and unedited.
    # Missing means True, so a caller from before the choice is edited as it always was.
    edit: bool | None = None
    # 23-Nov (wait-less B9): true answers 202 at once and joins behind the answer (see
    # claim_finish). Missing or false is the finish as it always was: held for the join.
    background: bool | None = None


def _subject(agent: str) -> str:
    """What a status line calls it: "the talk with Atlas", or "your recording" for a take
    with no script (12-Oct)."""
    if agent_talks.is_solo(agent):
        return "your recording"
    if agent_talks.book_episode(agent) is not None:
        return "your book session"
    return f"the talk with {agent_talks.display_name(agent)}"


def _http(exc: TalkError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _talk(db: AsyncSession, ws: uuid.UUID, talk_id: uuid.UUID) -> AgentTalk:
    row = (
        await db.execute(
            select(AgentTalk).where(AgentTalk.id == talk_id, AgentTalk.workspace_id == ws)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent talk not found")
    return row


def _folder(row: AgentTalk) -> Path:
    return agent_talks.talk_folder(_root(), row.workspace_id, row.id)


def talk_json(row: AgentTalk, *, pieces: int | None = None, bytes_total: int | None = None) -> dict[str, Any]:
    if pieces is None or bytes_total is None:
        pieces, bytes_total = agent_talks.received(_folder(row))
        meta = row.join_meta or {}
        if row.upload_id and not pieces:
            pieces, bytes_total = int(meta.get("pieces") or 0), int(meta.get("bytes") or 0)
    return {
        "talk_id": str(row.id),
        "status": row.status,
        "agent": agent_talks.display_name(row.agent),
        "title": agent_talks.talk_title(row.agent, row.started_at),
        "call_id": row.call_id,
        "pieces": pieces,
        "bytes_total": bytes_total,
        "upload_id": str(row.upload_id) if row.upload_id else None,
        "detail": row.status_detail,
    }


@router.post("", status_code=201)
async def create_agent_talk(
    body: AgentTalkCreate,
    request: Request,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    # 12-Oct: a take with no script is the owner's first, until Ziv says a client gets it.
    if (
        agent_talks.is_solo(body.agent)
        and not settings.production_solo_for_clients
        and scoped_editor_workspace(request.headers.get("x-tce-editor-key")) is not None
    ):
        raise HTTPException(status_code=403, detail="Recording without a script is not on for this workspace yet")
    try:
        extension = agent_talks.container_for(body.mime)
        started = agent_talks.parse_instant(body.started_at)
    except TalkError as exc:
        raise _http(exc) from exc
    agent = body.agent.strip()
    call_id = body.call_id.strip()

    async def existing() -> AgentTalk | None:
        return (
            await db.execute(
                select(AgentTalk).where(
                    AgentTalk.workspace_id == ws,
                    AgentTalk.agent == agent,
                    AgentTalk.call_id == call_id,
                    AgentTalk.started_at == started,
                )
            )
        ).scalar_one_or_none()

    # A create sent twice (the relay retried) is the same talk, whatever it became since.
    found = await existing()
    if found is not None:
        return JSONResponse(status_code=200, content=talk_json(found))
    row = AgentTalk(
        workspace_id=ws,
        agent=agent,
        call_id=call_id,
        started_at=started,
        mime_type=body.mime.strip()[:120],
        file_extension=extension,
        status="recording",
        status_detail=(
            "Recording: the pieces arrive while you record"
            if agent_talks.is_solo(agent)
            else f"Recording the talk with {agent_talks.display_name(agent)}: the pieces arrive "
            "while the call runs"
        ),
        join_meta={},
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        found = await existing()
        if found is None:
            raise
        return JSONResponse(status_code=200, content=talk_json(found))
    # 3-Oct review: a new talk is the moment to finish this workspace's talks whose
    # finish never came (in the background; this answer does not wait for it).
    if await _idle_talks(db, ws):
        from tce.api.routers import production as production_routes

        production_routes._spawn(finish_idle_talks(ws))
    return talk_json(row, pieces=0, bytes_total=0)


@router.get("/{talk_id}")
async def get_agent_talk(
    talk_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Where a talk stands: the pieces that arrived, and the video once there is one.
    "finish" (B9) says how a finish answered before its join is going, or how it ended."""
    row = await _talk(db, ws, talk_id)
    return {**talk_json(row), "finish": await _finish_state(db, ws, row)}


_TOO_BIG = f"The piece is larger than {agent_talks.MAX_CHUNK_BYTES // (1024 * 1024)} MB"
_BEING_JOINED = "This talk is being joined into its video right now; a piece sent now would not be in it"


async def _read_piece(request: Request) -> bytes:
    """The piece's bytes, never more than MAX_CHUNK_BYTES of them held (3-Oct review): a
    body sent without a length (chunked) is read in parts and refused the moment it
    passes the limit, instead of being read whole into memory first."""
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > agent_talks.MAX_CHUNK_BYTES:
            raise HTTPException(status_code=413, detail=_TOO_BIG)
    return bytes(data)


@router.put("/{talk_id}/chunks/{seq}")
async def put_agent_talk_chunk(
    talk_id: uuid.UUID,
    seq: int,
    request: Request,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _talk(db, ws, talk_id)
    if row.upload_id is not None or row.status == "finished":
        raise HTTPException(
            status_code=409,
            detail="This talk is finished and its video is made; a piece sent now would not be in it",
        )
    # B9: a finish claimed in the background holds the talk from its claim, through any
    # wait for the lock and across a restart, until its join ends.
    if _finish_lock(talk_id).locked() or row.status == FINISHING:
        raise HTTPException(status_code=409, detail=_BEING_JOINED)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > agent_talks.MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail=_TOO_BIG)
    data = await _read_piece(request)
    try:
        stored = await asyncio.to_thread(agent_talks.store_piece, _folder(row), seq, data)
    except TalkError as exc:
        raise _http(exc) from exc
    row.last_chunk_at = _utcnow()
    if row.status == "failed":  # a join failed; pieces still arriving make it a recording again
        row.status = "recording"
    row.status_detail = (
        f"Recording {_subject(row.agent)}: "
        f"{stored.pieces} {'piece' if stored.pieces == 1 else 'pieces'} here, "
        f"{stored.bytes_total / 1_000_000:.1f} MB, the last at {agent_talks.local_time(row.last_chunk_at):%H:%M:%S}"
    )
    await db.commit()
    return {
        "ok": True,
        "bytes_total": stored.bytes_total,
        "seq": seq,
        "pieces": stored.pieces,
        "duplicate": not stored.created,
    }


def _chosen_edit(row: AgentTalk) -> bool:
    """The choice the first finish carried. A talk finished before the choice existed
    (no "edit" in its join_meta) was edited, so it reads as True."""
    return (row.join_meta or {}).get("edit", True) is not False


def _finished(row: AgentTalk, upload: RecordingUpload | None) -> dict[str, Any]:
    return {
        "upload_id": str(row.upload_id) if row.upload_id else None,
        "status": upload.status if upload is not None else row.status,
        "talk_id": str(row.id),
        "title": agent_talks.talk_title(row.agent, row.started_at),
        "detail": upload.status_detail if upload is not None else row.status_detail,
        "missing_pieces": list((row.join_meta or {}).get("missing") or []),
        "edit": _chosen_edit(row),
        "archived": bool(upload is not None and upload.archived_at is not None),
    }


def _choice_words(edit: bool) -> str:
    return "send it to be edited" if edit else "archive it without an edit"


async def _upload_of(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID | None) -> RecordingUpload | None:
    if upload_id is None:
        return None
    return (
        await db.execute(
            select(RecordingUpload).where(
                RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
            )
        )
    ).scalar_one_or_none()


async def _finished_again(
    db: AsyncSession, ws: uuid.UUID, row: AgentTalk, body: AgentTalkFinish
) -> dict[str, Any]:
    """A finish for a talk that already has its video answers with that video. If the
    first finish came without the call's transcript (the sweeper finishing an idle talk)
    and this one brings it, the video keeps it: the next plan tells the voices apart."""
    upload = await _upload_of(db, ws, row.upload_id)
    lines = [line.model_dump() for line in body.transcript or []]
    if upload is not None and lines and not upload.call_transcript:
        upload.call_transcript = lines
        await db.commit()
    result = _finished(row, upload)
    # 4-Oct (C4.1): the first finish's choice stands; a later one never flips it (the
    # page and the sweeper can both finish the same talk). The answer says so.
    first = result["edit"]
    asked = None if body.edit is None else body.edit is not False
    result["already_finished"] = True
    result["choice_kept"] = asked is not None and asked != first
    result["note"] = (
        f"This talk was already finished, and its first choice stands: {_choice_words(first)}."
        + (
            f" This finish asked to {_choice_words(asked)}, and nothing changed."
            if result["choice_kept"]
            else ""
        )
    )
    result["edit_started"] = False
    return result


def _missing_line(missing: list[int], count: int | None = None) -> str:
    count = len(missing) if count is None else max(count, len(missing))
    if not count:
        return ""
    shown = ", ".join(str(n) for n in missing[:8]) + (" and more" if count > 8 else "")
    return (
        f" {count} {'piece' if count == 1 else 'pieces'} never arrived "
        f"(number {shown}), so the video skips there."
    )


@router.post("/{talk_id}/finish")
async def finish_agent_talk(
    talk_id: uuid.UUID,
    body: AgentTalkFinish | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _talk(db, ws, talk_id)
    body = body or AgentTalkFinish()
    if body.background is True:
        return await claim_finish(db, ws, row, body)
    return await finish_talk(db, ws, row, body)


ARCHIVED_BY_CHOICE = (
    " Archived as you chose: it is not edited. To edit it, open Archived in the Library"
    " and tap Edit this now."
)
ARCHIVED_BY_BACKSTOP = (
    " No choice came for it, so it is archived and not edited. To edit it, open Archived"
    " in the Library and tap Edit this now."
)


async def finish_talk(
    db: AsyncSession,
    ws: uuid.UUID,
    row: AgentTalk,
    body: AgentTalkFinish,
    *,
    archived_line: str = ARCHIVED_BY_CHOICE,
    claimed: bool = False,
) -> dict[str, Any] | None:
    """Join the talk's pieces into its library video and, when he chose to (C4.1), start
    the edit (the finish route, and TCE's own backstop for a talk whose finish never
    came, which archives). claimed (B9): this is the join a background finish claimed,
    its body read from the claim; how it ends is written on the talk for the GET. None
    when the claim had already ended before this one got the talk."""
    edit = body.edit is not False
    if row.upload_id is not None:  # finished before: the same video, as it stands now
        return await _finished_again(db, ws, row, body)
    async with _turn(db, row, claimed=claimed) as turn:
        if row.upload_id is not None:  # another finish made it while this one waited
            return await _finished_again(db, ws, row, body)
        if claimed and _claim_of(row) is None:
            return None
        try:
            ended = agent_talks.parse_instant(body.ended_at) or _utcnow()
        except TalkError as exc:
            raise _http(exc) from exc
        name = agent_talks.display_name(row.agent)
        try:
            joined = await agent_talks.join(_folder(row), row.file_extension)
        except TalkError as exc:
            held = claimed and await turn.hold() is not None
            if exc.status == 422:  # the pieces are here and do not make a video
                row.status = "failed"
                row.status_detail = f"{_subject(row.agent)[:1].upper()}{_subject(row.agent)[1:]} could not be joined: {exc}"[:500]
                if held:
                    row.join_meta = _failed_meta(row, 422, str(exc))
                await db.commit()
            elif held:  # refused before it wrote anything: the talk is as such a refusal leaves it
                _let_go(row)
                await db.commit()
            raise _http(exc) from exc
        sha = await asyncio.to_thread(agent_talks.sha256_of, joined.path)
        if claimed:  # the claim as it stands now: a later finish may have brought the transcript
            claim = await turn.hold()
            body = _claim_body(claim) if claim is not None else body
        lines = [line.model_dump() for line in body.transcript or []]
        duration = joined.proof.get("duration_s") or (
            body.duration_ms / 1000.0 if body.duration_ms else None
        )
        row.ended_at = ended
        row.duration_ms = body.duration_ms
        row.join_meta = {
            "pieces": joined.pieces,
            "bytes": joined.bytes,
            "missing": joined.missing,
            "missing_count": joined.missing_count,
            "container": joined.container,
            "streams": joined.proof.get("streams") or [],
            "joined_at": _utcnow().isoformat(),
            # 4-Oct (C4.1): the choice this first finish carried; a later one keeps it.
            "edit": edit,
        }
        # The same bytes are already a video here (uq_recording_upload_sha): that one it is.
        upload = (
            await db.execute(
                select(RecordingUpload).where(
                    RecordingUpload.workspace_id == ws, RecordingUpload.sha256 == sha
                )
            )
        ).scalar_one_or_none()
        created = upload is None
        if created:
            # The library names a video by its topic row: one of the agent-talk kind,
            # which no list of ideas shows (editorial/agent_talk_topics.py).
            candidate = talk_topic(ws, row.agent, row.started_at)
            db.add(candidate)
            await db.flush()
            auto = bool(settings.production_auto_edit)
            if not edit:
                tail = archived_line
            elif auto:
                tail = " Jennifer starts the edit now: transcribing first."
            else:
                tail = " Automatic editing is switched off on this server, so it waits as it is."
            solo = agent_talks.is_solo(row.agent)
            what = "Your recording" if solo else f"Agent talk with {name}"
            upload = RecordingUpload(
                workspace_id=ws,
                candidate_id=candidate.id,
                packet_id=None,
                original_filename=f"{'recording' if solo else 'agent-talk'}-{row.id}.{joined.container}",
                storage_path=str(joined.path),
                sha256=sha,
                duration_s=duration,
                status="uploaded",
                status_detail=(
                    (
                        f"{what}, joined from {joined.pieces} "
                        f"{'piece' if joined.pieces == 1 else 'pieces'} without re-encoding."
                        if joined.pieces
                        else f"{what}, joined without re-encoding."
                    )
                    + _missing_line(joined.missing, joined.missing_count)
                    + tail
                )[:500],
                job_ids=[],
                # 12-Oct: a take with no script is one voice, his, and edits as a normal
                # take: its own source, no agent, never the conversation rules.
                source=agent_talks.source_for(row.agent),
                agent_name=None if solo else name,
                call_transcript=lines,
                # Archived the way the Library's own Archive button does it: kept, out
                # of Still to do, listed under Archived (library.set_archived).
                archived_at=None if edit else _utcnow(),
            )
            db.add(upload)
            await db.flush()
        row.upload_id = upload.id
        row.status = "finished"
        row.status_detail = (
            f"Finished: {_subject(row.agent)} is in the library as “"
            f"{agent_talks.talk_title(row.agent, row.started_at)}”."
            + ("" if edit else " It is archived, not edited.")
            + _missing_line(joined.missing, joined.missing_count)
        )[:500]
        if claimed:  # how it ended, for the GET of whoever finished it in the background
            row.join_meta = {**row.join_meta, "finish": {
                "state": "finished", "edit_started": bool(created and edit and settings.production_auto_edit)}}
        await db.commit()
        upload_id = upload.id
        result = _finished(row, upload)
    if created and edit:
        # The edit runs in the background and sees the committed video. The kill switch
        # (TCE_PRODUCTION_AUTO_EDIT) is read inside start_auto_edit.
        from tce.api.routers import production as production_routes

        production_routes.start_auto_edit(upload_id, ws)
    result["edit_started"] = bool(created and edit and settings.production_auto_edit)
    result["already_finished"] = False
    result["choice_kept"] = False
    return result


# ---------------------------------------------------------------------------
# A finish answered before its join (23-Nov, wait-less B9)
#
# The KM BOT relay and the pages that finish a talk from the browser may send
# "background": true. Refusals that need no join are answered at once as before; a
# talk with its video answers 200 as before. Otherwise the finish is CLAIMED: the talk's
# status becomes "finishing" and join_meta["claim"] holds what this finish carried
# (ended_at, duration_ms, edit, the whole transcript), committed before the 202. The
# join is then finish_talk itself, under the same per-talk lock, in its own database
# session (finish_claimed). The first claim's choice stands (C4.1). A piece is refused
# 409 for as long as the talk is claimed. At startup resume_claimed_talks joins every
# talk still claimed, so a deploy mid-join costs a retry, never the recording. A finish
# without the field on a claimed talk waits for that join (_turn) and answers as a
# second finish does today; TCE's idle backstop only ever takes talks still recording.


def _without_claim(row: AgentTalk) -> dict[str, Any]:
    return {k: v for k, v in (row.join_meta or {}).items() if k != "claim"}


def _claim_of(row: AgentTalk) -> dict[str, Any] | None:
    """What the background finish that claimed this talk carried, while it is claimed."""
    if row.status != FINISHING:
        return None
    claim = (row.join_meta or {}).get("claim")
    return dict(claim) if isinstance(claim, dict) else {}


def _claim_body(claim: dict[str, Any]) -> AgentTalkFinish:
    return AgentTalkFinish(
        ended_at=claim.get("ended_at"),
        duration_ms=claim.get("duration_ms"),
        transcript=claim.get("transcript") or None,
        edit=claim.get("edit", True) is not False,
    )


def _failed_meta(row: AgentTalk, status: int, detail: str) -> dict[str, Any]:
    """The claim ends in a refused join: the GET says so with the refusal's own words,
    for as long as the talk's line is the one written with it."""
    return {**_without_claim(row), "finish": {
        "state": "failed", "error": {"status": status, "detail": detail}, "on_row": row.status_detail}}


def _let_go(row: AgentTalk) -> None:
    """The claim ends without a join (no ffmpeg, the disk, no piece): the talk is as that
    refusal leaves it when it comes straight back, and the next finish is refused at once."""
    claim = _claim_of(row) or {}
    row.status = claim.get("status_before") or "recording"
    row.status_detail = claim.get("detail_before")
    row.join_meta = _without_claim(row)


def _finishing_line(agent: str) -> str:
    subject = _subject(agent)
    return f"{subject[:1].upper()}{subject[1:]} is being put together into its video now."


def _crash_line(agent: str) -> str:
    """A crash behind the answer is a server error (500 on the GET), backed off and finished
    again by the caller, never a refused join: so never "could not be joined"."""
    subject = _subject(agent)
    return (
        f"{subject[:1].upper()}{subject[1:]} could not be put together just now: the server ran "
        "into an error while joining it. Finishing it again tries once more."
    )


class _Turn:
    """One finish's hold on a talk (see _turn)."""

    def __init__(self, db: AsyncSession, row: AgentTalk) -> None:
        self.db, self.row, self.held = db, row, None

    async def hold(self) -> dict[str, Any] | None:
        """The claim lock until the turn ends, and the row read afresh: the claim as it
        stands now, or None when it is no longer claimed."""
        if self.held is None:
            lock = _claim_lock(self.row.id)
            await lock.acquire()
            self.held = lock
        await self.db.refresh(self.row)
        return _claim_of(self.row)


@asynccontextmanager
async def _turn(db: AsyncSession, row: AgentTalk, *, claimed: bool) -> AsyncIterator[_Turn]:
    """The talk's finish lock, with the row read afresh. A finish that is not the claimed
    one first waits for the join of a background finish that claimed the talk: that join
    is the one, and this finish then answers as a second finish does."""
    lock = _finish_lock(row.id)
    for _ in range(_CLAIM_WAITS):
        if not claimed and _claim_of(row) is not None:
            await asyncio.wait({_start_claimed(row.id, row.workspace_id)})
        await lock.acquire()
        try:
            await db.refresh(row)
        except BaseException:
            lock.release()
            raise
        if claimed or _claim_of(row) is None:
            break
        lock.release()
    else:
        raise HTTPException(
            status_code=503,
            detail="This talk is still being joined in the background; finish it again in a minute",
        )
    turn = _Turn(db, row)
    try:
        yield turn
    finally:
        if turn.held is not None:
            turn.held.release()
        lock.release()


def _claim_answer(row: AgentTalk, edit: bool, choice_kept: bool) -> JSONResponse:
    return JSONResponse(status_code=202, content={
        "talk_id": str(row.id),
        "state": FINISHING,
        "status": FINISHING,
        "upload_id": None,
        "edit": edit,
        "choice_kept": choice_kept,
        "detail": _finishing_line(row.agent),
    })


async def claim_finish(db: AsyncSession, ws: uuid.UUID, row: AgentTalk, body: AgentTalkFinish) -> Any:
    """POST .../finish with "background": true (contract B9)."""
    if row.upload_id is not None:  # finished before: today's answer, at once
        return await _finished_again(db, ws, row, body)
    try:
        agent_talks.parse_instant(body.ended_at)
    except TalkError as exc:
        raise _http(exc) from exc
    lock = _finish_lock(row.id)
    while True:
        await db.refresh(row)
        if row.upload_id is not None:
            return await _finished_again(db, ws, row, body)
        if _claim_of(row) is not None:
            return await _claimed_again(db, ws, row, body)
        if not lock.locked():
            break
        # A finish without a claim (an older caller, or TCE's own backstop) is joining it
        # now: this one waits for it, as a second finish always has.
        async with lock:
            pass
    edit = body.edit is not False
    async with lock:
        await db.refresh(row)
        if row.upload_id is not None:
            return await _finished_again(db, ws, row, body)
        if _claim_of(row) is not None:
            return await _claimed_again(db, ws, row, body)
        try:
            await agent_talks.check_joinable(_folder(row))
        except TalkError as exc:
            raise _http(exc) from exc
        row.join_meta = {**{k: v for k, v in _without_claim(row).items() if k != "finish"}, "claim": {
            "ended_at": body.ended_at,
            "duration_ms": body.duration_ms,
            "edit": edit,
            "transcript": [line.model_dump() for line in body.transcript or []],
            "claimed_at": _utcnow().isoformat(),
            "status_before": row.status,
            "detail_before": row.status_detail,
        }}
        row.status = FINISHING
        row.status_detail = _finishing_line(row.agent)
        await db.commit()
    _start_claimed(row.id, ws)
    return _claim_answer(row, edit, choice_kept=False)


async def _claimed_again(db: AsyncSession, ws: uuid.UUID, row: AgentTalk, body: AgentTalkFinish) -> Any:
    """A finish while a background finish holds the talk (the page and the sweeper both
    finish): the same 202, no second join, the first choice kept. A transcript the claim
    lacks is kept with it, so the video gets it, as _finished_again does once it is made."""
    lines = [line.model_dump() for line in body.transcript or []]
    async with _claim_lock(row.id):
        await db.refresh(row)
        claim = _claim_of(row)
        if claim is not None and lines and not claim.get("transcript"):
            claim["transcript"] = lines
            row.join_meta = {**(row.join_meta or {}), "claim": claim}
            await db.commit()
    if claim is None:  # the claimed join ended between the two reads: answer as it ended
        return await claim_finish(db, ws, row, body)
    _start_claimed(row.id, ws)  # after a restart this process may not be joining it yet
    first = claim.get("edit", True) is not False
    asked = None if body.edit is None else body.edit is not False
    return _claim_answer(row, first, choice_kept=asked is not None and asked != first)


def _start_claimed(talk_id: uuid.UUID, ws: uuid.UUID) -> asyncio.Task:
    """The one task in this process that joins a claimed talk."""
    task = _claim_tasks.get(talk_id)
    if task is None or task.done():
        task = asyncio.get_running_loop().create_task(finish_claimed(talk_id, ws))
        _claim_tasks[talk_id] = task

        def forget(done: asyncio.Task, key: uuid.UUID = talk_id) -> None:
            if _claim_tasks.get(key) is done:
                del _claim_tasks[key]

        task.add_done_callback(forget)
    return task


async def finish_claimed(talk_id: uuid.UUID, ws: uuid.UUID) -> dict[str, Any] | None:
    """Join a claimed talk behind the answer: finish_talk with the claim's body, in this
    task's own database session. Never raises. A refusal is on the talk as finish_talk
    writes it; a crash is written there too (failed, in plain words), never lost."""
    import structlog

    from tce.api.routers import production as production_routes

    log = structlog.get_logger()
    try:
        async with production_routes.session_factory()() as db:
            row = (
                await db.execute(select(AgentTalk).where(AgentTalk.id == talk_id, AgentTalk.workspace_id == ws))
            ).scalar_one_or_none()
            claim = _claim_of(row) if row is not None else None
            if claim is None:
                return None
            try:
                result = await finish_talk(db, ws, row, _claim_body(claim), claimed=True)
            except HTTPException as exc:
                log.warning("agent_talks.background_finish_refused", talk=str(talk_id), status=exc.status_code,
                            detail=str(exc.detail)[:300])
                return None
            if result is not None:
                log.info("agent_talks.background_finished", talk=str(talk_id), upload=result.get("upload_id"))
            return result
    except Exception:  # noqa: BLE001 - written on the talk below
        log.warning("agent_talks.background_finish_failed", talk=str(talk_id), exc_info=True)
    try:
        async with production_routes.session_factory()() as db:
            row = await _talk(db, ws, talk_id)
            async with _claim_lock(talk_id):
                await db.refresh(row)
                if _claim_of(row) is not None:
                    row.status = "failed"
                    row.status_detail = _crash_line(row.agent)[:500]
                    row.join_meta = _failed_meta(row, 500, row.status_detail)
                    await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("agent_talks.background_crash_not_written", talk=str(talk_id), exc_info=True)
    return None


async def resume_claimed_talks() -> list[uuid.UUID]:
    """After a restart: join every talk a background finish claimed and the restart cut
    short. Called with the other boot-time resumes (production.resume_auto_work)."""
    import structlog

    from tce.api.routers import production as production_routes

    try:
        async with production_routes.session_factory()() as db:
            claimed = (
                await db.execute(select(AgentTalk.id, AgentTalk.workspace_id).where(AgentTalk.status == FINISHING))
            ).all()
    except Exception:  # noqa: BLE001 - a resume never stops what called it
        structlog.get_logger().warning("agent_talks.claimed_scan_failed", exc_info=True)
        return []
    for talk_id, ws in claimed:
        _start_claimed(talk_id, ws)
    return [talk_id for talk_id, _ws in claimed]


async def _finish_state(db: AsyncSession, ws: uuid.UUID, row: AgentTalk) -> dict[str, Any]:
    """The GET's "finish": none, finishing, finished (with the finish's own fields) or
    failed (with the refusal's status and words)."""
    mark = (row.join_meta or {}).get("finish")
    mark = mark if isinstance(mark, dict) else {}
    if row.upload_id is not None:
        result = _finished(row, await _upload_of(db, ws, row.upload_id))
        result.update(edit_started=bool(mark.get("edit_started")), already_finished=False, choice_kept=False)
        return {"state": "finished", "result": result}
    if row.status == FINISHING:
        return {"state": FINISHING}
    if row.status == "failed":
        error = mark.get("error") if mark.get("state") == "failed" and mark.get("on_row") == row.status_detail else None
        return {"state": "failed", "error": error or {"status": 422, "detail": row.status_detail or ""}}
    return {"state": "none"}


# ---------------------------------------------------------------------------
# A talk whose finish never came (3-Oct review)
#
# The KM BOT side finishes a talk when the call ends, and its sweeper finishes one that
# has been idle ten minutes (C4). If neither ever arrives (the relay died with the
# call), the pieces would sit on this disk forever and the talk would never become a
# video, with nobody told. TCE's own backstop finishes a talk that has had no piece for
# IDLE_FINISH_S, far past the relay's sweeper so the two never race: at startup, and
# whenever a new talk is created. A later finish from the relay still brings the call's
# transcript onto the video (_finished_again). 4-Oct (C4.1): no choice came with it, so
# the backstop archives the video instead of editing it.

IDLE_FINISH_S = 6 * 3600


def _idle_since(row: AgentTalk) -> datetime:
    return row.last_chunk_at or row.created_at or row.started_at


async def _idle_talks(
    db: AsyncSession, ws: uuid.UUID | None, now: datetime | None = None
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(talk, workspace) of every talk still recording with no piece for IDLE_FINISH_S."""
    cutoff = (now or _utcnow()) - timedelta(seconds=IDLE_FINISH_S)
    q = select(AgentTalk).where(AgentTalk.status == "recording", AgentTalk.upload_id.is_(None))
    if ws is not None:
        q = q.where(AgentTalk.workspace_id == ws)
    return [
        (r.id, r.workspace_id)
        for r in (await db.execute(q)).scalars().all()
        if _idle_since(r) is not None and _idle_since(r) < cutoff
    ]


async def finish_idle_talks(ws: uuid.UUID | None = None, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Finish every talk still recording with no piece for IDLE_FINISH_S (one workspace,
    or all). Returns the talks it finished. Never raises: a talk it cannot finish says
    why on its own row."""
    import structlog

    from tce.api.routers import production as production_routes

    log = structlog.get_logger()
    done: list[uuid.UUID] = []
    try:
        async with production_routes.session_factory()() as db:
            idle = await _idle_talks(db, ws, now)
    except Exception:  # noqa: BLE001 - a backstop never stops what called it
        log.warning("agent_talks.idle_scan_failed", exc_info=True)
        return done
    for talk_id, talk_ws in idle:
        try:
            async with production_routes.session_factory()() as db:
                row = await _talk(db, talk_ws, talk_id)
                if row.status != "recording" or row.upload_id is not None or _finish_lock(talk_id).locked():
                    continue
                try:
                    # 4-Oct (C4.1): no choice ever came, so it is archived, never edited
                    # ("before sending me ask me if to archive or send"). Edit this now
                    # in the Library's Archived list starts the edit.
                    await finish_talk(
                        db, talk_ws, row, AgentTalkFinish(edit=False), archived_line=ARCHIVED_BY_BACKSTOP
                    )
                    done.append(talk_id)
                except HTTPException as exc:
                    if exc.status_code == 409:  # nothing to join, or piece 0 never came
                        await db.refresh(row)
                        row.status = "failed"
                        row.status_detail = (
                            f"No piece arrived for {IDLE_FINISH_S // 3600} hours and "
                            f"{_subject(row.agent)} could not be made into a video: "
                            f"{exc.detail}"
                        )[:500]
                        await db.commit()
                    # 507 (disk) and 503 (no ffmpeg) leave it recording for the next sweep.
                    log.warning("agent_talks.idle_finish_refused", talk=str(talk_id), status=exc.status_code)
        except Exception:  # noqa: BLE001
            log.warning("agent_talks.idle_finish_failed", talk=str(talk_id), exc_info=True)
    if done:
        log.info("agent_talks.idle_finished", talks=len(done))
    return done
