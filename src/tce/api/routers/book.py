"""The book app's API (9-Nov-2026, T-19730).

GET  /book/chapters                      the chapter list, each with its status, and
                                         whether narration can be bought
GET  /book/chapters/{n}                  one chapter's paragraphs and status
POST /book/chapters/{n}/status           {"status": draft|in_review|approved, "note"}
GET  /book/chapters/{n}/audio/{i}        paragraph i read aloud (mp3). 409 with
                                         "device_voice": true when no narration may be
                                         bought: the page then reads it with the
                                         device's own voice, free
POST /book/import                        {"text"} new chapter text (the book editor)
POST /book/sessions                      the next episode: the agent name a filmed
                                         session records under ("_book_7" becomes
                                         "Book session, episode 7")

The owner's only: a client login never reaches it (the scoped fence lists no /book
path, and this router refuses a scoped key as well).
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from tce.api.private_access import require_private_workspace, scoped_editor_workspace
from tce.book.store import STATUS_WORDS, STATUSES, BookStore, summary
from tce.production import agent_talks
from tce.settings import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/book", tags=["book"])

# ElevenLabs bills by character; this is the rate TTSService itself estimates with.
USD_PER_1K_CHARS = 0.30


async def require_owner(
    ws: uuid.UUID = Depends(require_private_workspace),
    x_tce_editor_key: str | None = Header(None),
) -> uuid.UUID:
    if scoped_editor_workspace(x_tce_editor_key) is not None:
        raise HTTPException(status_code=403, detail="The book is the owner's only")
    return ws


def store() -> BookStore:
    book = BookStore(Path(settings.evidence_upload_dir) / "book")
    book.ensure_imported(settings.book_source_path)
    return book


def _chapter(book: BookStore, n: int) -> dict[str, Any]:
    for chapter in book.chapters():
        if chapter["n"] == n:
            return chapter
    raise HTTPException(status_code=404, detail=f"There is no chapter {n}")


def narration_state(book: BookStore) -> dict[str, Any]:
    spent = int(book.state()["chars_spent"])
    budget = int(settings.book_tts_char_budget or 0)
    configured = bool(settings.elevenlabs_api_key and settings.book_voice_id)
    total = sum(sum(len(p) for p in c["paragraphs"]) for c in book.chapters())
    return {
        "configured": configured,
        "on": configured and budget > spent,
        "budget_chars": budget,
        "spent_chars": spent,
        "book_chars": total,
        "book_cost_usd": round(total / 1000 * USD_PER_1K_CHARS, 2),
        "voice_id": settings.book_voice_id,
    }


@router.get("/chapters")
async def list_chapters(ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    return {
        "chapters": summary(book),
        "narration": narration_state(book),
        "editor_seat": settings.book_editor_seat,
        "statuses": [{"id": s, "words": STATUS_WORDS[s]} for s in STATUSES],
    }


@router.get("/chapters/{n}")
async def get_chapter(n: int, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    chapter = _chapter(book, n)
    entry = book.status_of(n)
    numbers = [c["n"] for c in book.chapters()]
    at = numbers.index(n)
    return {
        **chapter,
        "status": entry.get("status", "draft"),
        "status_words": STATUS_WORDS.get(entry.get("status", "draft"), "Draft"),
        "status_at": entry.get("at"),
        "history": entry.get("history", []),
        "previous": numbers[at - 1] if at > 0 else None,
        "next": numbers[at + 1] if at + 1 < len(numbers) else None,
        "narration": narration_state(book),
        "editor_seat": settings.book_editor_seat,
    }


class StatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=2000)
    by: str = Field(default="ziv", max_length=40)


@router.post("/chapters/{n}/status")
async def set_status(n: int, body: StatusBody, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    _chapter(book, n)
    try:
        entry = book.set_status(n, body.status, by=body.by or "ziv", note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("book.status", chapter=n, status=body.status, by=body.by)
    return {"n": n, "status": entry["status"], "status_words": STATUS_WORDS[entry["status"]], "at": entry["at"]}


_generating: dict[str, asyncio.Lock] = {}


@router.get("/chapters/{n}/audio/{i}")
async def paragraph_audio(n: int, i: int, ws: uuid.UUID = Depends(require_owner)):
    book = store()
    chapter = _chapter(book, n)
    if i < 0 or i >= len(chapter["paragraphs"]):
        raise HTTPException(status_code=404, detail=f"Chapter {n} has no paragraph {i + 1}")
    text = chapter["paragraphs"][i]
    voice = settings.book_voice_id
    path = book.audio_path(text, voice)
    if path.is_file():
        return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})
    state = narration_state(book)
    if not state["configured"] or state["spent_chars"] + len(text) > state["budget_chars"]:
        # No narration may be bought: the page reads this paragraph with the device's
        # own voice. Never a silent spend (Ziv: any added ElevenLabs cost comes to him first).
        return JSONResponse(
            status_code=409,
            content={
                "device_voice": True,
                "detail": "Narration is not switched on yet, so this device reads it aloud.",
                "chars": len(text),
            },
        )
    lock = _generating.setdefault(path.name, asyncio.Lock())
    async with lock:
        if not path.is_file():
            from tce.services.tts import TTSService

            out = Path(tempfile.mkdtemp(prefix="tce-book-"))
            try:
                svc = TTSService(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model, output_dir=str(out))
                result = await svc.generate(segments=[{"narratorText": text}], voice_id=voice)
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(result.file_path, path)
                spent = book.charge(len(text))
                logger.info("book.narrated", chapter=n, paragraph=i, chars=len(text), spent=spent)
            except Exception as exc:  # noqa: BLE001 - the page falls back to the device voice
                logger.warning("book.narration_failed", chapter=n, paragraph=i, error=str(exc)[:300])
                return JSONResponse(
                    status_code=409,
                    content={"device_voice": True, "detail": "The reading voice did not answer, so this device reads it aloud."},
                )
            finally:
                shutil.rmtree(out, ignore_errors=True)
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})


class ImportBody(BaseModel):
    text: str = Field(min_length=1, max_length=5_000_000)
    source: str = Field(default="", max_length=400)


@router.post("/import")
async def import_text(body: ImportBody, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = BookStore(Path(settings.evidence_upload_dir) / "book")
    try:
        found = book.import_text(body.text, source=body.source or "import")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"chapters": len(found), "titles": [c["title"] for c in found]}


@router.post("/sessions", status_code=201)
async def next_session(ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    episode = store().next_episode()
    agent = f"{agent_talks.BOOK_PREFIX}{episode}"
    return {"episode": episode, "agent": agent, "title": f"Book session, episode {episode}"}
