"""TTSService - ElevenLabs text-to-speech for voiceover generation."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# ElevenLabs API constants
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"


@dataclass
class TTSResult:
    """Result from a TTS generation."""

    file_path: str
    duration_seconds: float
    file_size_bytes: int
    voice_id: str
    model: str
    cost_estimate_usd: float  # rough estimate: ~$0.30 per 1K chars


class TTSService:
    """Generates voiceover audio from narration script segments via ElevenLabs."""

    def __init__(
        self,
        api_key: str,
        voice_id: str = "",
        model: str = "eleven_multilingual_v2",
        output_dir: str = "/tmp/tce-audio",
    ):
        if not api_key:
            raise ValueError("ElevenLabs API key is required")
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def list_voices(self) -> list[dict[str, Any]]:
        """List available ElevenLabs voices."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{ELEVENLABS_API_URL}/voices",
                headers={"xi-api-key": self.api_key},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"ElevenLabs voices error ({resp.status_code}): {resp.text[:300]}")
            data = resp.json()
            return [
                {
                    "voice_id": v["voice_id"],
                    "name": v["name"],
                    "category": v.get("category", ""),
                    "labels": v.get("labels", {}),
                }
                for v in data.get("voices", [])
            ]

    async def generate(
        self,
        segments: list[dict[str, Any]],
        *,
        voice_id: str | None = None,
        voice_config: dict[str, Any] | None = None,
        run_id: uuid.UUID | None = None,
    ) -> TTSResult:
        """Generate voiceover audio from narration script segments.

        Concatenates all segment narratorText into a single text block,
        sends to ElevenLabs TTS API, and saves the resulting MP3.

        Args:
            segments: List of dicts with 'narratorText' keys
            voice_id: Override voice ID (uses instance default if None)
            voice_config: Optional dict with stability, similarity_boost, style, etc.
            run_id: Pipeline run ID for organizing output

        Returns:
            TTSResult with file path, duration, and cost estimate
        """
        import httpx

        # Build the full narration text with natural pauses between segments
        text_parts = []
        for seg in segments:
            narrator_text = seg.get("narratorText", "").strip()
            if narrator_text:
                text_parts.append(narrator_text)

        if not text_parts:
            raise ValueError("No narratorText found in segments")

        # Join with pause markers for natural segment breaks
        full_text = "\n\n".join(text_parts)
        char_count = len(full_text)

        vid = voice_id or self.voice_id
        if not vid:
            raise ValueError(
                "No voice_id configured. Set ELEVENLABS_VOICE_ID or pass voice_id parameter."
            )

        # Build voice settings
        voice_settings = {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        }
        if voice_config:
            voice_settings.update({
                k: v for k, v in voice_config.items()
                if k in ("stability", "similarity_boost", "style", "use_speaker_boost")
            })

        logger.info(
            "tts.generate.start",
            voice_id=vid,
            model=self.model,
            char_count=char_count,
            segment_count=len(text_parts),
        )

        # Call ElevenLabs API
        payload = {
            "text": full_text,
            "model_id": self.model,
            "voice_settings": voice_settings,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{ELEVENLABS_API_URL}/text-to-speech/{vid}",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=payload,
            )

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            logger.error(
                "tts.generate.failed",
                status_code=resp.status_code,
                error=error_detail,
            )
            raise RuntimeError(
                f"ElevenLabs TTS error ({resp.status_code}): {error_detail}"
            )

        # Save MP3 to output directory
        rid = str(run_id or uuid.uuid4())
        out_dir = self.output_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = out_dir / "voiceover.mp3"
        await asyncio.to_thread(mp3_path.write_bytes, resp.content)

        file_size = mp3_path.stat().st_size

        # Detect actual duration
        duration = await self._detect_duration(str(mp3_path))

        # Cost estimate: ElevenLabs charges ~$0.30 per 1K characters
        cost_estimate = (char_count / 1000) * 0.30

        logger.info(
            "tts.generate.complete",
            file_path=str(mp3_path),
            duration=f"{duration:.1f}s",
            file_size=file_size,
            char_count=char_count,
            cost_estimate=f"${cost_estimate:.3f}",
        )

        return TTSResult(
            file_path=str(mp3_path),
            duration_seconds=round(duration, 2),
            file_size_bytes=file_size,
            voice_id=vid,
            model=self.model,
            cost_estimate_usd=round(cost_estimate, 4),
        )

    async def _detect_duration(self, audio_path: str) -> float:
        """Detect audio duration using mutagen or ffprobe."""
        try:
            import mutagen

            audio = await asyncio.to_thread(mutagen.File, audio_path)
            if audio and audio.info:
                return audio.info.length
        except ImportError:
            pass

        # Fallback: ffprobe
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

        # Last resort: estimate from file size (MP3 ~128kbps = 16KB/s)
        size = os.path.getsize(audio_path)
        return size / 16000

    async def generate_with_timestamps(
        self,
        segments: list[dict[str, Any]],
        *,
        voice_id: str | None = None,
        voice_config: dict[str, Any] | None = None,
        run_id: uuid.UUID | None = None,
    ) -> tuple[TTSResult, list[dict[str, Any]]]:
        """Generate voiceover and compute per-segment timestamps.

        Returns the TTSResult plus an updated segments list with
        estimated startSec/endSec based on proportional word counts.
        """
        result = await self.generate(
            segments,
            voice_id=voice_id,
            voice_config=voice_config,
            run_id=run_id,
        )

        # Calculate proportional timing from actual audio duration
        total_words = 0
        seg_words = []
        for seg in segments:
            words = len(seg.get("narratorText", "").split())
            seg_words.append(max(words, 1))
            total_words += max(words, 1)

        if total_words == 0:
            return result, segments

        cursor = 0.0
        timed_segments = []
        for seg, wc in zip(segments, seg_words):
            proportion = wc / total_words
            duration = proportion * result.duration_seconds
            updated = dict(seg)
            updated["startSec"] = round(cursor, 2)
            updated["endSec"] = round(cursor + duration, 2)
            timed_segments.append(updated)
            cursor += duration

        return result, timed_segments
