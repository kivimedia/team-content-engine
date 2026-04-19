"""Weekly walking-video pipeline agents.

Four HTTP-based (non-LLM) agents that orchestrate the one-button weekly split-and-edit flow:
  1. WeeklyTranscriberAgent  - POST /transcribe to CutSense, stores word-level transcript
  2. WeeklyScriptAlignerAgent - fuzzy anchor matching, produces 5 segment boundaries
  3. WeeklyClipSplitterAgent  - POST /split to CutSense, gets 5 clip paths back
  4. WeeklyClipEditorAgent    - POST /edit x5 (async), polls until all done

All agents read/write WeeklyWalkingRecording and WalkingVideoScript rows via the DB session.
No LLM calls - cost is FFmpeg + Whisper + CutSense pipeline time only.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
import structlog

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

logger = structlog.get_logger()

_POLL_INTERVAL_S = 5
_EDIT_TIMEOUT_S = 60 * 60  # 1h per clip max


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _cutsense_headers(service_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if service_key:
        headers["X-Service-Key"] = service_key
    return headers


# ---------------------------------------------------------------------------
# Fuzzy anchor alignment helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[lb]


def _fuzzy_confidence(anchor: str, candidate: str) -> float:
    """Levenshtein similarity in [0, 1]. 1 = identical."""
    max_len = max(len(anchor), len(candidate), 1)
    return 1.0 - _levenshtein(anchor, candidate) / max_len


def _extract_anchor(script) -> str:
    """First 8 normalised words of hook or full_script."""
    text = ""
    if hasattr(script, "hook") and script.hook:
        text = script.hook
    elif hasattr(script, "full_script") and script.full_script:
        text = script.full_script
    elif isinstance(script, dict):
        text = script.get("hook") or script.get("full_script") or ""

    words = _normalise(text).split()
    return " ".join(words[:8])


def _find_best_anchor(anchor: str, words: list[dict]) -> tuple[float, float, float]:
    """Slide a window over word-level transcript, return (start_sec, end_sec, confidence).

    Words is a list of {word, start, end, confidence} dicts from faster-whisper.
    Window size = number of words in anchor. Returns (-1, -1, 0) if no match found.
    """
    anchor_words = anchor.split()
    n = len(anchor_words)
    if n == 0 or len(words) < n:
        return -1.0, -1.0, 0.0

    best_conf = 0.0
    best_start = -1.0
    best_end = -1.0

    for i in range(len(words) - n + 1):
        window = " ".join(_normalise(w.get("word", "")) for w in words[i: i + n])
        conf = _fuzzy_confidence(anchor, window)
        if conf > best_conf:
            best_conf = conf
            best_start = words[i].get("start", 0.0)
            best_end = words[i + n - 1].get("end", best_start + 1.0)

    return best_start, best_end, best_conf


# ---------------------------------------------------------------------------
# Agent 1 - Transcriber
# ---------------------------------------------------------------------------

@register_agent
class WeeklyTranscriberAgent(AgentBase):
    """Calls CutSense POST /transcribe on the uploaded long video.

    Context in:  recording_id (UUID str)
    Context out: transcript_json (word-level), recording updated to transcribing->done step
    """

    name = "weekly_transcriber"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import select
        from tce.models.weekly_walking_recording import WeeklyWalkingRecording

        recording_id = uuid.UUID(context["recording_id"])
        result = await self.db.execute(select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.id == recording_id))
        recording = result.scalar_one()

        if not recording.long_video_path:
            raise ValueError("recording.long_video_path is not set")

        recording.status = "transcribing"
        recording.updated_at = _utcnow()
        await self.db.commit()

        api_url = self.settings.cutsense_api_url
        service_key = self.settings.cutsense_service_key
        headers = _cutsense_headers(service_key)

        self._report(f"Calling CutSense /transcribe on {recording.long_video_path}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_url}/transcribe",
                json={"video_path": recording.long_video_path},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30 * 60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"CutSense /transcribe returned {resp.status}: {body}")
                transcript = await resp.json()

        word_count = len(transcript.get("words", []))
        self._report(f"Transcription done: {word_count} words")

        recording.transcript_json = transcript
        recording.transcribed_at = _utcnow()
        recording.updated_at = _utcnow()
        await self.db.commit()

        return {"transcript_json": transcript}


# ---------------------------------------------------------------------------
# Agent 2 - Script Aligner
# ---------------------------------------------------------------------------

@register_agent
class WeeklyScriptAlignerAgent(AgentBase):
    """Anchor-based fuzzy alignment of 5 walking scripts to the transcript.

    Extracts first-8-word anchor from each script's hook/full_script,
    fuzzy-matches against word-level transcript (Levenshtein), derives segment boundaries.
    Rejects alignment if any anchor confidence < 0.6 or anchors are out of order.

    Context in:  recording_id, weekly_plan_id
    Context out: alignment_json (list of 5 entries)
    """

    name = "weekly_script_aligner"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import select
        from tce.models.weekly_walking_recording import WeeklyWalkingRecording
        from tce.models.walking_video_script import WalkingVideoScript

        recording_id = uuid.UUID(context["recording_id"])
        weekly_plan_id = uuid.UUID(context["weekly_plan_id"])

        result = await self.db.execute(select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.id == recording_id))
        recording = result.scalar_one()

        if not recording.transcript_json:
            raise ValueError("transcript_json is empty - run weekly_transcriber first")

        recording.status = "aligning"
        recording.updated_at = _utcnow()
        await self.db.commit()

        words: list[dict] = recording.transcript_json.get("words", [])

        # Load the 5 walking scripts for this week, ordered by creation (proxy for day order)
        scripts_result = await self.db.execute(
            select(WalkingVideoScript)
            .where(WalkingVideoScript.pipeline_run_id == weekly_plan_id)
            .order_by(WalkingVideoScript.created_at)
        )
        scripts = scripts_result.scalars().all()

        # Fallback: if pipeline_run_id link not set, caller must pass script_ids
        if not scripts and "script_ids" in context:
            ids = [uuid.UUID(sid) for sid in context["script_ids"]]
            scripts_result = await self.db.execute(
                select(WalkingVideoScript).where(WalkingVideoScript.id.in_(ids))
            )
            scripts = scripts_result.scalars().all()
            scripts = sorted(scripts, key=lambda s: ids.index(s.id))

        if not scripts:
            raise ValueError("No walking scripts found for this week. Pass script_ids in context.")

        self._report(f"Aligning {len(scripts)} scripts against {len(words)} transcript words")

        alignment = []
        prev_start_sec = -1.0

        for idx, script in enumerate(scripts):
            anchor = _extract_anchor(script)
            if not anchor:
                raise ValueError(f"Script {idx+1} has no hook or full_script to use as anchor")

            start_sec, end_sec, confidence = _find_best_anchor(anchor, words)

            if confidence < 0.6:
                raise ValueError(
                    f"Script {idx+1} anchor '{anchor}' matched with confidence {confidence:.2f} < 0.6. "
                    f"The alignment stopped. Re-upload or adjust the script's hook to be more distinctive."
                )

            if start_sec <= prev_start_sec:
                raise ValueError(
                    f"Script {idx+1} anchor found at {start_sec:.2f}s but script {idx} was at {prev_start_sec:.2f}s. "
                    f"Anchors are out of order - check that scripts are in recording sequence."
                )

            self._report(
                f"Script {idx+1}: anchor '{anchor[:40]}...' matched at {start_sec:.2f}s "
                f"(confidence {confidence:.2f})"
            )

            alignment.append({
                "script_id": str(script.id),
                "anchor_text": anchor,
                "start_sec": max(0.0, start_sec - 0.3),  # 0.3s breathing buffer before
                "anchor_start_sec": start_sec,
                "match_confidence": round(confidence, 3),
            })
            prev_start_sec = start_sec

        # Fill in end_sec: each segment ends 0.5s after next anchor's start (or EOF)
        total_sec = words[-1].get("end", 0.0) if words else 0.0
        for i, seg in enumerate(alignment):
            if i + 1 < len(alignment):
                seg["end_sec"] = alignment[i + 1]["anchor_start_sec"] - 0.3
            else:
                seg["end_sec"] = total_sec + 0.5

        recording.alignment_json = alignment
        recording.aligned_at = _utcnow()
        recording.status = "aligned"
        recording.updated_at = _utcnow()
        await self.db.commit()

        self._report(f"Alignment complete: {len(alignment)} segments")
        return {"alignment_json": alignment}


# ---------------------------------------------------------------------------
# Agent 3 - Clip Splitter
# ---------------------------------------------------------------------------

@register_agent
class WeeklyClipSplitterAgent(AgentBase):
    """Calls CutSense POST /split once with all 5 segments, gets clip paths back.

    Context in:  recording_id
    Context out: clips (list of {name, path}), updates recording.status=splitting->split
    """

    name = "weekly_clip_splitter"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import select
        from tce.models.weekly_walking_recording import WeeklyWalkingRecording

        recording_id = uuid.UUID(context["recording_id"])
        result = await self.db.execute(select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.id == recording_id))
        recording = result.scalar_one()

        if not recording.alignment_json:
            raise ValueError("alignment_json is empty - run weekly_script_aligner first")

        recording.status = "splitting"
        recording.updated_at = _utcnow()
        await self.db.commit()

        import os
        clips_dir = os.path.join(
            self.settings.video_output_dir,
            "weekly_recordings",
            str(recording.weekly_plan_id),
            "clips",
        )

        segments = []
        for idx, seg in enumerate(recording.alignment_json):
            clip_name = f"script_{idx+1}_{seg['script_id'][:8]}"
            segments.append({
                "start_sec": seg["start_sec"],
                "end_sec": seg["end_sec"],
                "clip_name": clip_name,
            })

        self._report(f"Splitting {len(segments)} clips from {recording.long_video_path}")

        api_url = self.settings.cutsense_api_url
        service_key = self.settings.cutsense_service_key
        headers = _cutsense_headers(service_key)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_url}/split",
                json={
                    "video_path": recording.long_video_path,
                    "segments": segments,
                    "output_dir": clips_dir,
                },
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30 * 60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"CutSense /split returned {resp.status}: {body}")
                data = await resp.json()

        clips = data.get("clips", [])
        self._report(f"Split done: {len(clips)} clips in {clips_dir}")

        recording.split_at = _utcnow()
        recording.status = "split"
        recording.updated_at = _utcnow()
        await self.db.commit()

        return {"clips": clips}


# ---------------------------------------------------------------------------
# Agent 4 - Clip Editor
# ---------------------------------------------------------------------------

@register_agent
class WeeklyClipEditorAgent(AgentBase):
    """Dispatches a CutSense edit job for each clip, polls until done, writes results.

    Fires all 5 /edit calls at once (non-blocking), then polls all job statuses
    concurrently until every clip reaches render_done or fails.
    On completion, sets walking_video_scripts[i].edited_video_file_path + status=edited.

    Context in:  recording_id, clips (from splitter), alignment_json
    Context out: cutsense_jobs (script_id -> job_id map)
    """

    name = "weekly_clip_editor"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import select
        from tce.models.weekly_walking_recording import WeeklyWalkingRecording
        from tce.models.walking_video_script import WalkingVideoScript

        recording_id = uuid.UUID(context["recording_id"])
        clips: list[dict] = context.get("clips", [])
        alignment: list[dict] = context.get("alignment_json", [])

        result = await self.db.execute(select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.id == recording_id))
        recording = result.scalar_one()

        recording.status = "editing"
        recording.editing_started_at = _utcnow()
        recording.updated_at = _utcnow()
        await self.db.commit()

        api_url = self.settings.cutsense_api_url
        service_key = self.settings.cutsense_service_key
        headers = _cutsense_headers(service_key)

        # Build clip_path -> script_id map from alignment order
        clip_to_script: dict[str, str] = {}
        for idx, clip in enumerate(clips):
            if idx < len(alignment):
                clip_to_script[clip["name"]] = alignment[idx]["script_id"]

        # Load cutsense_prompt per script for the edit instruction
        script_prompts: dict[str, str] = {}
        if alignment:
            script_ids = [uuid.UUID(seg["script_id"]) for seg in alignment]
            scripts_result = await self.db.execute(
                select(WalkingVideoScript).where(WalkingVideoScript.id.in_(script_ids))
            )
            for s in scripts_result.scalars().all():
                script_prompts[str(s.id)] = s.cutsense_prompt or (
                    "Edit this walking video: remove pauses, pick the best take, add jumbo captions."
                )

        # Fire all edit jobs
        self._report(f"Firing {len(clips)} CutSense edit jobs")
        job_map: dict[str, str] = {}  # clip_name -> job_id

        async with aiohttp.ClientSession() as session:
            for clip in clips:
                script_id = clip_to_script.get(clip["name"], "")
                prompt = script_prompts.get(script_id, "Edit this walking video clip.")
                async with session.post(
                    f"{api_url}/edit",
                    json={
                        "clip_path": clip["path"],
                        "prompt": prompt,
                        "captions": "jumbo",
                        "silence_cut_min_ms": 1000,
                        "take_picker": "vision_audio",
                    },
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 202:
                        body = await resp.text()
                        raise RuntimeError(f"CutSense /edit returned {resp.status} for {clip['name']}: {body}")
                    data = await resp.json()
                    job_id = data["job_id"]
                    job_map[clip["name"]] = job_id
                    self._report(f"Edit job dispatched for {clip['name']}: job_id={job_id}")

        # Persist job map immediately (so dashboard can poll statuses)
        script_job_map = {clip_to_script.get(name, name): job_id for name, job_id in job_map.items()}
        recording.cutsense_jobs = script_job_map
        recording.updated_at = _utcnow()
        await self.db.commit()

        # Poll all jobs until done or timeout
        self._report(f"Polling {len(job_map)} CutSense jobs...")
        pending = dict(job_map)  # clip_name -> job_id still running
        deadline = asyncio.get_event_loop().time() + _EDIT_TIMEOUT_S

        async with aiohttp.ClientSession() as session:
            while pending and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(_POLL_INTERVAL_S)
                completed_names = []
                for clip_name, job_id in pending.items():
                    async with session.get(
                        f"{api_url}/jobs/{job_id}/status",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        status_data = await resp.json()

                    state = status_data.get("state", "")
                    if state == "render_done":
                        output_path = status_data.get("output_path", "")
                        self._report(f"Job {job_id} ({clip_name}) done. Output: {output_path}")

                        # Write output to the WalkingVideoScript row
                        script_id = clip_to_script.get(clip_name)
                        if script_id and output_path:
                            script_result = await self.db.execute(
                                select(WalkingVideoScript).where(
                                    WalkingVideoScript.id == uuid.UUID(script_id)
                                )
                            )
                            script = script_result.scalar_one_or_none()
                            if script:
                                script.edited_video_file_path = output_path
                                script.status = "edited"
                                script.updated_at = _utcnow()
                            await self.db.commit()

                        completed_names.append(clip_name)

                    elif state in ("ingest_failed", "understand_failed", "edit_failed", "render_failed"):
                        error = status_data.get("error", "unknown error")
                        self._report(f"Job {job_id} ({clip_name}) FAILED: {error}")
                        completed_names.append(clip_name)

                for name in completed_names:
                    pending.pop(name, None)

        if pending:
            raise TimeoutError(f"Edit jobs timed out after {_EDIT_TIMEOUT_S}s: {list(pending.keys())}")

        recording.done_at = _utcnow()
        recording.status = "done"
        recording.updated_at = _utcnow()
        await self.db.commit()

        self._report("All clips edited successfully")
        return {"cutsense_jobs": script_job_map}
