"""TCE's own faster-whisper WebSocket transcription worker.

TCE's editor (`src/tce/production/media.py`) speaks one contract:

    -> JSON meta {lesson_id, title, filename, video_seconds, language}
    -> the whole media file as one binary frame
    <- {"status": "receiving_audio"} / {"status": "transcribing"}
    <- {"status": "complete", "words": [{start, end, word}], "transcript_md": "..."}
    <- {"status": "error", "message": "..."}

`words` gives the editor word-level precision; `transcript_md` ("[HH:MM:SS] text"
lines) is the coarse fallback the editor already understands, so both are sent
and the editor picks the better one.

Why TCE owns this: the CourseIQ worker that used to serve :8765 returns only
`transcript_md`, and it disappeared from pm2 between 16 and 20 September 2026.
This file lives in the TCE repo, deploys with it, and is started as pm2
`tce-asr` with the ASR virtualenv:

    pm2 start /opt/phoneiq/venv-asr/bin/python --name tce-asr -- \
        /home/ziv/team-content-engine/scripts/tce_asr_worker.py
    pm2 save

Nothing here is metered: faster-whisper runs locally on the CPU. Paid Whisper
stays disabled.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel

MODEL_NAME = os.getenv("TCE_ASR_MODEL", "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
DEVICE = os.getenv("TCE_ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("TCE_ASR_COMPUTE_TYPE", "int8")
DEFAULT_LANGUAGE = os.getenv("TCE_ASR_LANGUAGE") or None
BEAM_SIZE = int(os.getenv("TCE_ASR_BEAM_SIZE", "5"))
MAX_CONCURRENT = int(os.getenv("TCE_ASR_MAX_CONCURRENT", "1"))
HOST = os.getenv("TCE_ASR_HOST", "127.0.0.1")
PORT = int(os.getenv("TCE_ASR_PORT", "8765"))

app = FastAPI(title="TCE faster-whisper worker")
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_model: WhisperModel | None = None


def model() -> WhisperModel:
    """Loaded once, on the first request, so pm2 reports the process up fast."""
    global _model
    if _model is None:
        print(f"[startup] loading {MODEL_NAME} on {DEVICE} ({COMPUTE_TYPE})", flush=True)
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
        print("[startup] model loaded", flush=True)
    return _model


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "model_loaded": _model is not None,
        "words": True,
    }


def timestamp(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def build_transcript_md(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{timestamp(s['start'])}] {s['text'].strip()}" for s in segments if s["text"].strip()
    )


def transcribe_file(path: Path, language: str | None) -> dict[str, Any]:
    started = time.time()
    segments_iter, info = model().transcribe(
        str(path),
        language=language or DEFAULT_LANGUAGE,
        beam_size=BEAM_SIZE,
        vad_filter=True,
        word_timestamps=True,
    )
    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for segment in segments_iter:
        segments.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "avg_logprob": segment.avg_logprob,
            }
        )
        for word in segment.words or []:
            text = (word.word or "").strip()
            # The editor drops a word list that is not strictly ordered, so a
            # zero-length word is skipped rather than sent and rejected.
            if text and word.end > word.start:
                words.append({"start": word.start, "end": word.end, "word": text})
    logprobs = [s["avg_logprob"] for s in segments if s.get("avg_logprob") is not None]
    confidence = round(math.exp(sum(logprobs) / len(logprobs)), 3) if logprobs else 0.0
    return {
        "words": words,
        "transcript_md": build_transcript_md(segments),
        "confidence": confidence,
        "word_count": len(words) or sum(len(s["text"].split()) for s in segments),
        "elapsed_seconds": round(time.time() - started, 1),
        "language": info.language,
        "duration_seconds": round(info.duration, 2),
    }


@app.websocket("/transcribe")
async def transcribe(ws: WebSocket) -> None:
    await ws.accept()
    async with _semaphore:
        lesson_id = "unknown"
        try:
            meta = json.loads(await ws.receive_text())
            lesson_id = str(meta.get("lesson_id") or "unknown")
            filename = str(meta.get("filename") or "audio.wav")
            language = meta.get("language") or None
            await ws.send_text(json.dumps({"status": "receiving_audio", "lesson_id": lesson_id}))
            audio = await ws.receive_bytes()
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / Path(filename).name
                path.write_bytes(audio)
                await ws.send_text(json.dumps({"status": "transcribing", "lesson_id": lesson_id}))
                result = await asyncio.to_thread(transcribe_file, path, language)
            await ws.send_text(json.dumps({"status": "complete", "lesson_id": lesson_id, **result}))
            print(
                f"[done] {lesson_id}: {result['word_count']} words, "
                f"{result['elapsed_seconds']}s for {result['duration_seconds']}s of audio",
                flush=True,
            )
        except WebSocketDisconnect:
            print(f"[warn] {lesson_id}: client disconnected", flush=True)
        except Exception as exc:  # never leave the editor waiting on a silent socket
            print(f"[error] {lesson_id}: {exc}\n{traceback.format_exc()}", flush=True)
            try:
                await ws.send_text(json.dumps({"status": "error", "message": str(exc)}))
            except Exception:
                pass


# The whole recording arrives as ONE message. uvicorn's default cap is 16 MB, so a
# 5m41s walk (182 MB) was cut off mid-send on 24-Sep ("Connection lost").
WS_MAX_BYTES = 2 * 1024**3

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", ws_max_size=WS_MAX_BYTES)
