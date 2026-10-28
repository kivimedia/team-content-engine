"""AudioAlignmentService - word-timestamp audio-to-script segment alignment.

Word timings come from OpenAI Whisper (whisper-1) or Deepgram, picked by
settings.word_timings_provider. Both come back in Whisper's verbose_json shape,
{"text", "duration", "words": [{"word", "start", "end"}]}, so align_segments,
audio_cleanup and the saved whisper_transcript read either one unchanged.
"""

from __future__ import annotations

import asyncio
import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Words per second estimate for script duration calculation
WPS_ESTIMATE = 2.5

WORD_TIMINGS_PROVIDERS = ("openai", "deepgram")

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_PARAMS = {
    # Numerals, casing and punctuation the way whisper-1 writes them, so the
    # script's own words still match.
    "smart_format": "true",
    # nova-3 leaves um and uh out unless asked, and audio_cleanup cuts fillers by word.
    "filler_words": "true",
    # whisper-1 was never told the language either.
    "detect_language": "true",
}
# Deepgram reads the container from Content-Type; these are the formats upload-audio takes.
_AUDIO_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}
# whisper-1's words carry no punctuation; Deepgram's punctuated_word does.
_EDGE_PUNCTUATION = ".,!?;:\"'()[]“”‘’…"


def _deepgram_word(word: dict[str, Any]) -> str:
    raw = (word.get("punctuated_word") or word.get("word") or "").strip()
    return raw.strip(_EDGE_PUNCTUATION) or raw


def deepgram_to_whisper(payload: dict[str, Any]) -> dict[str, Any]:
    """Deepgram's pre-recorded answer in the Whisper verbose_json shape."""
    channels = (payload.get("results") or {}).get("channels") or [{}]
    channel = channels[0] or {}
    alternatives = channel.get("alternatives") or [{}]
    best = alternatives[0] or {}
    words = [
        {
            "word": _deepgram_word(w),
            "start": float(w.get("start", 0)),
            "end": float(w.get("end", 0)),
        }
        for w in best.get("words") or []
    ]
    result: dict[str, Any] = {
        "provider": "deepgram",
        "text": best.get("transcript", ""),
        "duration": (payload.get("metadata") or {}).get("duration"),
        "words": words,
    }
    if channel.get("detected_language"):
        result["language"] = channel["detected_language"]
    return result


def _token(word: str) -> str:
    return (word or "").lower().strip(_EDGE_PUNCTUATION + " ")


# Symbols a reader says out loud ("salt & pepper"). Any other token with no
# letter or digit is a mark nobody says, like the " - " house style puts
# between words, and no engine writes it as a word.
_SPOKEN_SYMBOLS = frozenset("&+=@#%$×")


def spoken_words(text: str) -> list[str]:
    """The words a reader says for a script line, lowercased, in order."""
    return [
        token
        for token in (text or "").lower().split()
        if any(ch.isalnum() or ch in _SPOKEN_SYMBOLS for ch in token)
    ]


def estimate_duration(text: str) -> float:
    """Estimate speaking duration in seconds from word count."""
    words = len(text.split())
    if words == 0:
        return 0.5  # Minimum segment duration for empty text
    return words / WPS_ESTIMATE


class AudioAlignmentService:
    """Aligns narration script segments to audio word timings."""

    def __init__(
        self,
        openai_api_key: str,
        audio_dir: str = "/tmp/tce-audio",
        provider: str = "openai",
        deepgram_api_key: str = "",
        deepgram_model: str = "nova-3",
    ):
        self.openai_api_key = openai_api_key
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.provider = (provider or "openai").strip().lower()
        self.deepgram_api_key = deepgram_api_key
        self.deepgram_model = deepgram_model or "nova-3"

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
        """Word-level timestamps from the configured provider, in Whisper's shape."""
        if self.provider == "deepgram":
            return await self._transcribe_deepgram(audio_path)
        if self.provider == "openai":
            return await self._transcribe_openai(audio_path)
        raise RuntimeError(
            f"Unknown TCE_WORD_TIMINGS_PROVIDER {self.provider!r}; "
            f"use one of {', '.join(WORD_TIMINGS_PROVIDERS)}"
        )

    async def _transcribe_deepgram(self, audio_path: str) -> dict[str, Any]:
        import httpx

        if not self.deepgram_api_key:
            raise RuntimeError(
                "Deepgram word timings are switched on but TCE_DEEPGRAM_API_KEY is empty"
            )

        file_bytes = await asyncio.to_thread(Path(audio_path).read_bytes)
        content_type = _AUDIO_CONTENT_TYPES.get(
            Path(audio_path).suffix.lower(), "application/octet-stream"
        )

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                DEEPGRAM_LISTEN_URL,
                params={"model": self.deepgram_model, **DEEPGRAM_PARAMS},
                headers={
                    "Authorization": f"Token {self.deepgram_api_key}",
                    "Content-Type": content_type,
                },
                content=file_bytes,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Deepgram API error ({response.status_code}): {response.text[:300]}"
            )

        result = deepgram_to_whisper(response.json())
        logger.info(
            "deepgram.transcribed",
            duration=result.get("duration"),
            word_count=len(result["words"]),
            language=result.get("language"),
        )
        return result

    async def _transcribe_openai(self, audio_path: str) -> dict[str, Any]:
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
            # Count only what is said, or a dash ends the line one word late.
            narrator_words = spoken_words(seg.get("narratorText", ""))
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

    def compare_timings(
        self,
        openai_result: dict[str, Any],
        deepgram_result: dict[str, Any],
        segments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """How far Deepgram's word timings sit from whisper-1's on the same clip.

        Words both engines heard alike are paired in order and their start and
        end gaps summarised in milliseconds (positive = Deepgram later). With
        segments, both word lists also go through align_segments, which is the
        timing a narration keeps.
        """
        from tce.services.audio_cleanup import FILLER_WORDS

        a_words = openai_result.get("words") or []
        b_words = deepgram_result.get("words") or []
        a_tokens = [_token(w.get("word", "")) for w in a_words]
        b_tokens = [_token(w.get("word", "")) for w in b_words]

        pairs = []
        matcher = SequenceMatcher(None, a_tokens, b_tokens, autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                pairs.append((a_words[block.a + k], b_words[block.b + k]))

        def spread(key: str) -> dict[str, int] | None:
            deltas = [
                (float(b.get(key, 0)) - float(a.get(key, 0))) * 1000 for a, b in pairs
            ]
            if not deltas:
                return None
            ordered = sorted(abs(d) for d in deltas)
            return {
                "bias": round(sum(deltas) / len(deltas)),
                "mean": round(sum(ordered) / len(ordered)),
                "p90": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]),
                "max": round(ordered[-1]),
            }

        def engine(
            result: dict[str, Any], words: list[dict[str, Any]], tokens: list[str]
        ) -> dict[str, Any]:
            return {
                "words": len(words),
                "duration": result.get("duration"),
                "language": result.get("language"),
                "fillers": [
                    {"word": w.get("word"), "start": w.get("start")}
                    for w, t in zip(words, tokens)
                    if t in FILLER_WORDS
                ],
            }

        report: dict[str, Any] = {
            "openai": engine(openai_result, a_words, a_tokens),
            "deepgram": engine(deepgram_result, b_words, b_tokens),
            "matched_words": len(pairs),
            "matched_share": round(len(pairs) / len(a_words), 3) if a_words else None,
            "start_ms": spread("start"),
            "end_ms": spread("end"),
            "segments": [],
        }

        if segments:
            by_openai = self.align_segments(segments, a_words)
            by_deepgram = self.align_segments(segments, b_words)
            for seg, x, y in zip(segments, by_openai, by_deepgram):
                row: dict[str, Any] = {
                    "text": (seg.get("narratorText") or "")[:80],
                    "openai": [x.get("startSec"), x.get("endSec")],
                    "deepgram": [y.get("startSec"), y.get("endSec")],
                }
                if None not in row["openai"] + row["deepgram"]:
                    row["start_ms"] = round((y["startSec"] - x["startSec"]) * 1000)
                    row["end_ms"] = round((y["endSec"] - x["endSec"]) * 1000)
                report["segments"].append(row)

        return report
