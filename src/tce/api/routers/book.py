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
POST /book/sessions                      {"chapter"} the agent name a filmed session
                                         records under: "_book_7_e12" becomes "Book
                                         session on Episode 12, 10 Nov" (T-20030); with no
                                         chapter "_book_7" is "Book session, episode 7"
GET  /book/voices                        ElevenLabs voices with gender and accent (10-Nov)
GET  /book/voice-sample?voice_id=&model= a short sample of a paragraph, charged to the
                                         same narration budget (10-Nov, T-19955)
POST /book/voice                         {"voice_id", "model"} Ziv's pick, read from then on
POST /book/chapters/{n}/layout           {"action": approve|reopen|note, "note"} his word on a
                                         new chapter's layout (12-Nov, T-20758)
POST /book/chapters/{n}/write            his ask to write a chapter from its approved layout

12-Nov-2026 (T-20758): a new chapter's text and audio are HELD (no paragraphs, 423 on
audio) until its layout is approved and its current version was written or confirmed
after that. The page cannot get round it: the server never sends held text.

The owner's only: a client login never reaches it (the scoped fence lists no /book
path, and this router refuses a scoped key as well).
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from tce.api.private_access import require_private_workspace, scoped_editor_workspace
from tce.book.store import PHASE_WORDS, STATUS_WORDS, STATUSES, BookStore, EditorRecord, RecordWriteError, summary
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
        record = EditorRecord(Path(settings.book_editor_record), settings.book_written_through,
                              seed=settings.book_layout_seed or None)
    book = BookStore(Path(settings.evidence_upload_dir) / "book", record=record)
    book.ensure_imported(settings.book_source_path)
    return book


def _chapter(book: BookStore, n: int) -> dict[str, Any]:
    for chapter in book.chapters():
        if chapter["n"] == n:
            return chapter
    raise HTTPException(status_code=404, detail=f"There is no chapter {n}")


def _refuse_held(chapter: dict[str, Any]) -> None:
    if not chapter.get("readable", True):
        raise HTTPException(
            status_code=423,
            detail=f"Episode {chapter['n']} is held: its layout has to be approved and the chapter written from it first",
        )


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
        "phases": [{"id": p, "words": w} for p, w in PHASE_WORDS.items()],
    }


@router.get("/chapters/{n}")
async def get_chapter(n: int, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    chapter = _chapter(book, n)
    entry = book.status_of(n)
    numbers = [c["n"] for c in book.chapters()]
    at = numbers.index(n)
    held = not chapter.get("readable", True)
    return {
        **chapter,
        # Held text never leaves the server (T-20758), so no page can show or read it.
        "paragraphs": [] if held else chapter["paragraphs"],
        "held_paragraphs": len(chapter["paragraphs"]) if held else 0,
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
    _refuse_held(chapter)
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


class SessionBody(BaseModel):
    # 10-Nov (T-20030): the chapter he is on when he presses Film, so the take is named
    # after it ("Book session on Episode 12, 10 Nov") and not only by a running count.
    chapter: int | None = Field(default=None, ge=1, le=10_000)


@router.post("/sessions", status_code=201)
async def next_session(body: SessionBody | None = None, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    n = body.chapter if body else None
    found = next((c for c in book.chapters() if int(c.get("n", 0)) == n), None) if n else None
    episode = book.next_episode()
    if found is None:
        agent = agent_talks.book_agent(episode)
    else:
        agent = agent_talks.book_agent(episode, n, new=found.get("group", "written") == "new")
    title = agent_talks.talk_title(agent, datetime.now(UTC).replace(tzinfo=None))
    return {"episode": episode, "agent": agent, "title": title, "place": agent_talks.book_place(agent)}


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
async def voice_sample(voice_id: str, model: str = "eleven_v4", chapter: int = 0, paragraph: int = 0,
                       ws: uuid.UUID = Depends(require_owner)):
    if not voice_id.isalnum() or len(voice_id) > 40 or not model.replace("_", "").isalnum() or len(model) > 40:
        raise HTTPException(status_code=422, detail="That voice or model id is not valid")
    book = store()
    if chapter <= 0:
        # The first chapter he may hear (T-20758: a held episode is never read, not even as a sample).
        chap = next((c for c in book.chapters() if c.get("readable", True) and c["paragraphs"]), None)
        if chap is None:
            raise HTTPException(status_code=404, detail="No chapter is ready to be read yet")
    else:
        chap = _chapter(book, chapter)
        _refuse_held(chap)
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


# --- 12-Nov-2026 (T-20758): layout first, then write, then listen ----------------------
# Ziv, on a call: he wants to agree each chapter's layout before any text is written or read
# to him, the way TCE has a big idea, then a script, then a workshop. His approval, his notes
# and his ask to write go into the editor's own record, the way Approve does.


class LayoutBody(BaseModel):
    action: str = Field(pattern=r"^(approve|reopen|note)$")
    note: str = Field(default="", max_length=2000)
    by: str = Field(default="ziv", max_length=40)


def _editor_record(book: BookStore) -> EditorRecord:
    if book.record is None:
        raise HTTPException(status_code=409, detail="The editor's record is not on this server, so layouts cannot be kept")
    return book.record


@router.post("/chapters/{n}/layout")
async def layout_word(n: int, body: LayoutBody, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    record = _editor_record(book)
    _chapter(book, n)
    by = body.by or "ziv"
    try:
        if body.action == "note":
            text = body.note.strip()
            if not text:
                raise HTTPException(status_code=422, detail="The note is empty")
            out = record.add_layout_note(n, text, by=by)
        else:
            out = record.layout_decision(n, body.action == "approve", by=by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecordWriteError as exc:
        logger.warning("book.layout_not_written", chapter=n, action=body.action, error=str(exc)[:300])
        raise HTTPException(status_code=503, detail="The editor's record could not be written, so nothing changed") from exc
    logger.info("book.layout", chapter=n, action=body.action, by=by)
    chapter = _chapter(store(), n)
    return {"n": n, "action": body.action, "result": out, "phase": chapter.get("phase"), "phase_words": chapter.get("phase_words")}


class WriteBody(BaseModel):
    by: str = Field(default="ziv", max_length=40)


@router.post("/chapters/{n}/write")
async def ask_to_write(n: int, body: WriteBody | None = None, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    book = store()
    record = _editor_record(book)
    _chapter(book, n)
    by = (body.by if body else "") or "ziv"
    try:
        out = record.request_write(n, by=by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecordWriteError as exc:
        logger.warning("book.write_not_asked", chapter=n, error=str(exc)[:300])
        raise HTTPException(status_code=503, detail="The editor's record could not be written, so nothing changed") from exc
    logger.info("book.write_requested", chapter=n, by=by, already=out.get("already"))
    return {"n": n, **out}
