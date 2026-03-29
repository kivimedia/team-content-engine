"""AudioAlignmentService - Whisper-based audio-to-script segment alignment."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Words per second estimate for script duration calculation
WPS_ESTIMATE = 2.5


def estimate_duration(text: str) -> float:
    """Estimate speaking duration in seconds from word count."""
    words = len(text.split())
    if words == 0:
        return 0.5  # Minimum segment duration for empty text
    return words / WPS_ESTIMATE


class AudioAlignmentService:
    """Aligns narration script segments to audio using OpenAI Whisper."""

    def __init__(self, openai_api_key: str, audio_dir: str = "/tmp/tce-audio"):
        self.openai_api_key = openai_api_key
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    async def detect_duration(self, audio_path: str) -> float:
        """Detect audio duration in seconds using mutagen or ffprobe."""
        try:
            import mutagen

            # Run sync I/O in thread to avoid blocking event loop
            audio = await asyncio.to_thread(mutagen.File, audio_path)
            if audio and audio.info:
                return audio.info.length
        except ImportError:
            pass

        # Fallback: use ffprobe if available
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return float(stdout.strip())

        raise RuntimeError(f"Could not detect audio duration for {audio_path}")

    async def transcribe_with_timestamps(
        self, audio_path: str
    ) -> dict[str, Any]:
        """Call OpenAI Whisper API to get word-level timestamps.

        Returns the full Whisper response with word-level timing data.
        """
        import httpx

        url = "https://api.openai.com/v1/audio/transcriptions"

        # Read file in thread to avoid blocking event loop
        file_bytes = await asyncio.to_thread(Path(audio_path).read_bytes)
        filename = os.path.basename(audio_path)

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.openai_api_key}"},
                data={
                    "model": "whisper-1",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                },
                files={"file": (filename, file_bytes)},
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Whisper API error ({response.status_code}): {response.text[:300]}"
            )

        result = response.json()
        logger.info(
            "whisper.transcribed",
            duration=result.get("duration"),
            word_count=len(result.get("words", [])),
        )
        return result

    def align_segments(
        self,
        segments: list[dict[str, Any]],
        whisper_words: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fuzzy-match script segments to Whisper word timestamps.

        For each segment, finds the range of Whisper words that best match
        the segment's narrator_text, then sets start_sec and end_sec.
        """
        if not whisper_words:
            return segments

        word_idx = 0
        aligned = []
        total_words = len(whisper_words)

        for seg in segments:
            narrator_words = seg.get("narratorText", "").lower().split()
            if not narrator_words:
                # Empty segment - assign a short window
                if word_idx < total_words:
                    updated = dict(seg)
                    updated["startSec"] = whisper_words[word_idx].get("start", 0)
                    updated["endSec"] = updated["startSec"] + 0.5
                    aligned.append(updated)
                else:
                    aligned.append(seg)
                continue

            # Guard: if we've exhausted all whisper words, estimate remaining
            if word_idx >= total_words:
                last_end = aligned[-1]["endSec"] if aligned else 0
                est_dur = len(narrator_words) / WPS_ESTIMATE
                updated = dict(seg)
                updated["startSec"] = last_end + 0.15
                updated["endSec"] = last_end + 0.15 + est_dur
                aligned.append(updated)
                continue

            # Find the best starting position for this segment
            best_start_idx = word_idx
            best_score = 0

            search_end = min(total_words, word_idx + len(narrator_words) * 3)
            for candidate_start in range(word_idx, search_end):
                score = self._match_score(
                    narrator_words, whisper_words, candidate_start
                )
                if score > best_score:
                    best_score = score
                    best_start_idx = candidate_start

            # Set timing from matched word range (clamp to valid indices)
            match_end_idx = min(
                best_start_idx + len(narrator_words) - 1, total_words - 1
            )

            start_sec = whisper_words[best_start_idx].get("start", 0)
            end_sec = whisper_words[match_end_idx].get("end", start_sec + 3)

            updated = dict(seg)
            updated["startSec"] = max(0, start_sec - 0.15)
            updated["endSec"] = end_sec + 0.15

            aligned.append(updated)
            word_idx = match_end_idx + 1

        return aligned

    def _match_score(
        self,
        narrator_words: list[str],
        whisper_words: list[dict[str, Any]],
        start_idx: int,
    ) -> int:
        """Score how well narrator words match Whisper words starting at start_idx."""
        score = 0
        for i, nw in enumerate(narrator_words):
            wi = start_idx + i
            if wi >= len(whisper_words):
                break
            ww = whisper_words[wi].get("word", "").lower().strip(".,!?;:")
            nw_clean = nw.strip(".,!?;:")
            if ww == nw_clean:
                score += 2
            elif nw_clean in ww or ww in nw_clean:
                score += 1
        return score

    async def align_script(
        self,
        audio_path: str,
        segments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Full alignment pipeline: transcribe then match segments."""
        whisper_result = await self.transcribe_with_timestamps(audio_path)
        whisper_words = whisper_result.get("words", [])

        aligned = self.align_segments(segments, whisper_words)

        logger.info(
            "alignment.complete",
            segments_aligned=len(aligned),
            whisper_words=len(whisper_words),
        )

        return aligned, whisper_result
