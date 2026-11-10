"""The book app's API (9-Nov-2026, T-19730).

Since T-19824 the chapters, their versions and their status come from the book
editor's own record whenever it exists (settings.book_editor_record), read on every call.

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
GET  /book/voices                        ElevenLabs voices with gender and accent (10-Nov)
GET  /book/voice-sample?voice_id=&model= a short sample of a paragraph, charged to the
                                         same narration budget (10-Nov, T-19955)
POST /book/voice                         {"voice_id", "model"} Ziv's pick, read from then on

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
from tce.book.store import STATUS_WORDS, STATUSES, BookStore, EditorRecord, RecordWriteError, summary
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
    record = None
    if settings.book_editor_record:
        record = EditorRecord(Path(settings.book_editor_record), settings.book_written_through)
    book = BookStore(Path(settings.evidence_upload_dir) / "book", record=record)
    book.ensure_imported(settings.book_source_path)
    return book


def _chapter(book: BookStore, n: int) -> dict[str, Any]:
    for chapter in book.chapters():
        if chapter["n"] == n:
            return chapter
    raise HTTPException(status_code=404, detail=f"There is no chapter {n}")


def reading_voice(book: BookStore) -> dict[str, str]:
    """The voice and model the Book reads with: Ziv's pick when he made one (10-Nov,
    T-19955), else the settings."""
    chosen = book.voice()
    if chosen:
        return {"voice_id": chosen["voice_id"], "model": chosen["model"] or settings.book_tts_model or settings.elevenlabs_model,
                "name": chosen["name"], "chosen": "yes"}
    return {"voice_id": settings.book_voice_id, "model": settings.book_tts_model or settings.elevenlabs_model, "name": "", "chosen": ""}


def narration_state(book: BookStore) -> dict[str, Any]:
    spent = int(book.state()["chars_spent"])
    budget = int(settings.book_tts_char_budget or 0)
    voice = reading_voice(book)
    configured = bool(settings.elevenlabs_api_key and voice["voice_id"])
    total = sum(sum(len(p) for p in c["paragraphs"]) for c in book.chapters())
    return {
        "configured": configured,
        "on": configured and budget > spent,
        "budget_chars": budget,
        "spent_chars": spent,
        "book_chars": total,
        "book_cost_usd": round(total / 1000 * USD_PER_1K_CHARS, 2),
        "voice_id": voice["voice_id"],
        "model": voice["model"],
        "voice_name": voice["name"],
    }


@router.get("/chapters")
async def list_chapters(ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    return {
        "chapters": summary(book),
        "source": "editor" if book.record is not None else "import",
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
        "version": chapter.get("version", 0),
        "layout_items": chapter.get("layout_items", []),
        "layout_text": chapter.get("layout_text", ""),
        "group": chapter.get("group", "written"),
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
    except RecordWriteError as exc:
        # Never keep a second copy of his decision: it is in the editor's record or nowhere.
        logger.warning("book.status_not_written", chapter=n, error=str(exc)[:300])
        raise HTTPException(status_code=503, detail="The editor's record could not be written, so nothing changed") from exc
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
    reading = reading_voice(book)
    voice = reading["voice_id"]
    # The cache is per voice AND model, so a new pick never replays the old voice.
    path = book.audio_path(text, voice if reading["model"] == settings.elevenlabs_model else f"{voice}|{reading['model']}")
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
                svc = TTSService(api_key=settings.elevenlabs_api_key, model=reading["model"], output_dir=str(out))
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


# --- 10-Nov-2026 (T-19955): choosing the reading voice --------------------------------
# Ziv: "I want to use version four. And I don't like that voice. Needs to be a man voice."
# The voices list and short samples let him hear two or three male voices on Eleven v4 and
# pick one; the pick is saved in the Book's own state, so it needs no release. A sample is
# charged to the same narration budget he approved, and is refused past it.

SAMPLE_CHARS = 320


@router.get("/voices")
async def list_voices(ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    from tce.services.tts import TTSService

    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=409, detail="No ElevenLabs key is set on this server")
    try:
        voices = await TTSService(api_key=settings.elevenlabs_api_key).list_voices()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs did not list its voices: {str(exc)[:200]}") from exc
    rows = [
        {"voice_id": v["voice_id"], "name": v["name"], "category": v["category"],
         "gender": str((v.get("labels") or {}).get("gender") or ""),
         "accent": str((v.get("labels") or {}).get("accent") or ""),
         "age": str((v.get("labels") or {}).get("age") or ""),
         "description": str((v.get("labels") or {}).get("description") or (v.get("labels") or {}).get("descriptive") or "")}
        for v in voices
    ]
    return {"voices": rows, "current": reading_voice(store())}


@router.get("/voice-sample")
async def voice_sample(voice_id: str, model: str = "eleven_v4", chapter: int = 12, paragraph: int = 0,
                       ws: uuid.UUID = Depends(require_owner)):
    if not voice_id.isalnum() or len(voice_id) > 40 or not model.replace("_", "").isalnum() or len(model) > 40:
        raise HTTPException(status_code=422, detail="That voice or model id is not valid")
    book = store()
    chap = _chapter(book, chapter)
    if not chap["paragraphs"]:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter} has no text yet")
    text = chap["paragraphs"][min(max(0, paragraph), len(chap["paragraphs"]) - 1)]
    if len(text) > SAMPLE_CHARS:
        cut = text.rfind(". ", 0, SAMPLE_CHARS)
        text = text[: cut + 1] if cut > 80 else text[:SAMPLE_CHARS]
    path = book.root / "samples" / f"{model}-{voice_id}-{book.audio_path(text, voice_id).stem}.mp3"
    if path.is_file():
        return FileResponse(path, media_type="audio/mpeg")
    state = narration_state(book)
    if not settings.elevenlabs_api_key or state["spent_chars"] + len(text) > state["budget_chars"]:
        raise HTTPException(status_code=409, detail="No sample can be bought: no key, or the narration budget is spent")
    from tce.services.tts import TTSService

    out = Path(tempfile.mkdtemp(prefix="tce-book-sample-"))
    try:
        svc = TTSService(api_key=settings.elevenlabs_api_key, model=model, output_dir=str(out))
        result = await svc.generate(segments=[{"narratorText": text}], voice_id=voice_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(result.file_path, path)
        spent = book.charge(len(text))
        logger.info("book.voice_sample", voice=voice_id, model=model, chars=len(text), spent=spent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("book.voice_sample_failed", voice=voice_id, model=model, error=str(exc)[:300])
        raise HTTPException(status_code=502, detail=f"ElevenLabs did not make the sample: {str(exc)[:200]}") from exc
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return FileResponse(path, media_type="audio/mpeg")


class VoiceBody(BaseModel):
    voice_id: str = Field(min_length=6, max_length=40, pattern=r"^[A-Za-z0-9]+$")
    model: str = Field(default="eleven_v4", min_length=3, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(default="", max_length=80)
    by: str = Field(default="", max_length=40)


@router.post("/voice")
async def choose_voice(body: VoiceBody, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    book.set_voice(body.voice_id, body.model, name=body.name, by=body.by)
    return {"narration": narration_state(book)}
