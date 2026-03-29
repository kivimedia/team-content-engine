"""Audio cleanup service - filler removal, gap tightening, best-take selection.

Uses ffmpeg for audio manipulation and Whisper word-level data for intelligent editing.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Common filler words to detect and remove
FILLER_WORDS = {"um", "uh", "umm", "uhh", "hmm", "hm", "ah", "er", "erm", "like"}

# Silence threshold in seconds - gaps longer than this get tightened
SILENCE_MAX_SEC = 0.5
SILENCE_TARGET_SEC = 0.25


class AudioCleanupService:
    """Post-recording audio cleanup: fillers, gaps, best-take selection."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path

    async def clean_audio(
        self,
        audio_path: str,
        whisper_result: dict[str, Any],
        segments: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run full cleanup pipeline on recorded audio.

        Returns (cleaned_audio_path, updated_segments).
        Non-destructive: original audio is preserved, cleaned version saved as *_cleaned.wav.
        """
        src = Path(audio_path)
        if not src.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        words = whisper_result.get("words", [])
        if not words:
            logger.info("audio_cleanup.no_words", path=audio_path)
            return audio_path, segments

        # Step 1: Find filler word intervals
        filler_intervals = self._find_filler_intervals(words)
        logger.info("audio_cleanup.fillers_found", count=len(filler_intervals))

        # Step 2: Find best takes if duplicates exist
        bad_take_intervals = self._find_bad_takes(words, segments)
        logger.info("audio_cleanup.bad_takes_found", count=len(bad_take_intervals))

        # Step 3: Merge all cut intervals
        cut_intervals = sorted(filler_intervals + bad_take_intervals, key=lambda x: x[0])
        cut_intervals = self._merge_overlapping(cut_intervals)

        # Step 4: Find long silence gaps to tighten
        gap_edits = self._find_silence_gaps(words, cut_intervals)
        logger.info("audio_cleanup.gaps_to_tighten", count=len(gap_edits))

        if not cut_intervals and not gap_edits:
            logger.info("audio_cleanup.nothing_to_clean", path=audio_path)
            return audio_path, segments

        # Step 5: Apply edits with ffmpeg
        output_path = src.parent / f"{src.stem}_cleaned.wav"
        await self._apply_edits(str(src), str(output_path), cut_intervals, gap_edits)

        logger.info(
            "audio_cleanup.done",
            original=audio_path,
            cleaned=str(output_path),
            cuts=len(cut_intervals),
            gaps_tightened=len(gap_edits),
        )

        return str(output_path), segments

    def _find_filler_intervals(self, words: list[dict]) -> list[tuple[float, float]]:
        """Find time intervals of filler words (um, uh, etc.)."""
        intervals = []
        for w in words:
            text = (w.get("word") or w.get("text", "")).strip().lower().rstrip(".,!?")
            if text in FILLER_WORDS:
                start = w.get("start", 0)
                end = w.get("end", start)
                if end > start:
                    # Add small padding to avoid click artifacts
                    intervals.append((max(0, start - 0.02), end + 0.02))
        return intervals

    def _find_bad_takes(
        self, words: list[dict], segments: list[dict[str, Any]]
    ) -> list[tuple[float, float]]:
        """Detect duplicate readings of the same segment and pick the best take.

        If a user reads a line twice (e.g. stumbles and re-reads), we detect
        overlapping text matches and keep the take with higher average confidence.
        """
        bad_intervals = []

        for seg in segments:
            narrator_text = seg.get("narratorText", "").strip()
            if not narrator_text:
                continue

            # Tokenize the segment text
            seg_tokens = narrator_text.lower().split()
            if len(seg_tokens) < 3:
                continue

            # Find all windows in whisper words that match this segment
            takes = self._find_matching_windows(words, seg_tokens)
            if len(takes) < 2:
                continue

            # Score each take by average word confidence
            scored = []
            for start_idx, end_idx in takes:
                take_words = words[start_idx:end_idx]
                avg_conf = sum(
                    w.get("probability", w.get("confidence", 0.5))
                    for w in take_words
                ) / max(len(take_words), 1)
                scored.append((avg_conf, start_idx, end_idx))

            scored.sort(key=lambda x: x[0], reverse=True)

            # Keep the best take (highest confidence), mark others for removal
            for i, (conf, si, ei) in enumerate(scored):
                if i == 0:
                    continue  # Keep best
                start_sec = words[si].get("start", 0)
                end_sec = words[min(ei, len(words) - 1)].get("end", start_sec)
                if end_sec > start_sec:
                    bad_intervals.append((max(0, start_sec - 0.05), end_sec + 0.05))
                    logger.info(
                        "audio_cleanup.dropping_take",
                        segment_text=narrator_text[:40],
                        confidence=round(conf, 3),
                        time=f"{start_sec:.1f}-{end_sec:.1f}",
                    )

        return bad_intervals

    def _find_matching_windows(
        self, words: list[dict], seg_tokens: list[str]
    ) -> list[tuple[int, int]]:
        """Find all windows in whisper words that match the segment tokens."""
        matches = []
        threshold = 0.6  # 60% of words must match

        for start_idx in range(len(words)):
            if start_idx + len(seg_tokens) > len(words):
                break

            # Check if this window matches
            window = words[start_idx : start_idx + len(seg_tokens)]
            match_count = 0
            for wt, st in zip(window, seg_tokens):
                w_text = (wt.get("word") or wt.get("text", "")).strip().lower().rstrip(".,!?")
                if w_text == st.rstrip(".,!?"):
                    match_count += 1

            if match_count / len(seg_tokens) >= threshold:
                end_idx = start_idx + len(seg_tokens)
                # Avoid overlapping with previous match
                if matches and start_idx < matches[-1][1]:
                    continue
                matches.append((start_idx, end_idx))

        return matches

    def _find_silence_gaps(
        self, words: list[dict], cut_intervals: list[tuple[float, float]]
    ) -> list[tuple[float, float, float]]:
        """Find silence gaps between words that are longer than threshold.

        Returns list of (start, end, target_duration) tuples.
        """
        gaps = []
        for i in range(len(words) - 1):
            end_current = words[i].get("end", 0)
            start_next = words[i + 1].get("start", 0)
            gap_duration = start_next - end_current

            if gap_duration > SILENCE_MAX_SEC:
                # Check if this gap falls within a cut interval (already being removed)
                in_cut = any(
                    cs <= end_current and ce >= start_next
                    for cs, ce in cut_intervals
                )
                if not in_cut:
                    gaps.append((end_current, start_next, SILENCE_TARGET_SEC))

        return gaps

    @staticmethod
    def _merge_overlapping(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Merge overlapping intervals."""
        if not intervals:
            return []
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    async def _apply_edits(
        self,
        input_path: str,
        output_path: str,
        cut_intervals: list[tuple[float, float]],
        gap_edits: list[tuple[float, float, float]],
    ) -> None:
        """Apply audio edits using ffmpeg.

        Strategy: Build a list of audio segments to keep (inverse of cuts),
        then concatenate them, with silence gaps shortened.
        """
        # Get total duration first
        duration = await self._get_duration(input_path)
        if duration <= 0:
            shutil.copy2(input_path, output_path)
            return

        # Build keep-segments from cut intervals
        keep_segments = self._compute_keep_segments(duration, cut_intervals)

        if not keep_segments:
            shutil.copy2(input_path, output_path)
            return

        # Apply gap tightening to keep segments
        keep_segments = self._apply_gap_tightening(keep_segments, gap_edits)

        # Build ffmpeg filter complex
        filter_parts = []
        concat_inputs = []
        for i, (start, end) in enumerate(keep_segments):
            filter_parts.append(
                f"[0:a]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS[s{i}]"
            )
            concat_inputs.append(f"[s{i}]")

        if not filter_parts:
            shutil.copy2(input_path, output_path)
            return

        concat_str = "".join(concat_inputs) + f"concat=n={len(keep_segments)}:v=0:a=1[out]"
        filter_complex = ";".join(filter_parts) + ";" + concat_str

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "44100",
            "-ac", "1",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode()[:500]
            logger.error("audio_cleanup.ffmpeg_failed", returncode=proc.returncode, stderr=err)
            # Fallback: copy original
            shutil.copy2(input_path, output_path)

    def _compute_keep_segments(
        self, duration: float, cut_intervals: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Compute segments to keep (inverse of cut intervals)."""
        if not cut_intervals:
            return [(0, duration)]

        keeps = []
        pos = 0.0
        for cut_start, cut_end in cut_intervals:
            if cut_start > pos:
                keeps.append((pos, cut_start))
            pos = max(pos, cut_end)
        if pos < duration:
            keeps.append((pos, duration))
        return keeps

    def _apply_gap_tightening(
        self,
        segments: list[tuple[float, float]],
        gap_edits: list[tuple[float, float, float]],
    ) -> list[tuple[float, float]]:
        """Tighten gaps within keep segments by splitting them.

        For each gap_edit (gap_start, gap_end, target_duration),
        if the gap falls within a keep segment, split it into
        two parts with the shortened gap between them.
        """
        if not gap_edits:
            return segments

        result = list(segments)
        for gap_start, gap_end, target in gap_edits:
            new_result = []
            for seg_start, seg_end in result:
                if seg_start <= gap_start and gap_end <= seg_end:
                    # Gap is inside this segment - split it
                    if gap_start > seg_start:
                        new_result.append((seg_start, gap_start))
                    # Add a short silence segment (target duration from gap start)
                    gap_keep = min(target, gap_end - gap_start)
                    if gap_keep > 0:
                        new_result.append((gap_start, gap_start + gap_keep))
                    if gap_end < seg_end:
                        new_result.append((gap_end, seg_end))
                else:
                    new_result.append((seg_start, seg_end))
            result = new_result
        return result

    async def _get_duration(self, path: str) -> float:
        """Get audio duration using ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return float(stdout.decode().strip())
        except (ValueError, FileNotFoundError):
            return 0.0
