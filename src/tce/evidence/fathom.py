"""Fathom adapter: list meetings in a bounded window, normalize transcripts.

Read-only. The API key travels only in the `X-Api-Key` header and is never logged.
The API-side `created_after` filter narrows the listing (with a margin, and no upper
bound, so recordings processed long after the window are caught on a rerun), but every
meeting's recording date is re-verified here against explicit tz-aware bounds.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from tce.evidence.common import (
    EvidenceHTTPError,
    RetryPolicy,
    Sleep,
    as_utc,
    in_window,
    iso_z,
    maybe_await,
    parse_iso,
    request_with_retries,
    stable_hash,
)

DEFAULT_MAX_PAGES = 200
DEFAULT_MARGIN = timedelta(days=3)

_HEBREW = re.compile(r"[֐-׿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_TERMINAL = tuple(".?!…:;\"')׃")
_WORD = re.compile(r"\S+")


@dataclass
class FathomListing:
    meetings: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    listed: int = 0
    duplicates: int = 0
    pagination_finished: bool = False
    stop_reason: str | None = None


class FathomClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("Fathom API key is not configured")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            transport=transport,
            timeout=timeout_s,
        )
        self._sleep = sleep
        self._retry = retry or RetryPolicy()
        self.max_pages = max_pages

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FathomClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _get(
        self, path: str, params: dict[str, Any], on_wait: Callable[[str], Any] | None
    ) -> httpx.Response:
        return await request_with_retries(
            self._client, "GET", path, params=params, policy=self._retry,
            sleep=self._sleep, on_wait=on_wait,
        )

    async def list_meetings(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        margin: timedelta = DEFAULT_MARGIN,
        on_page: Callable[[int, int], Any] | None = None,
        on_wait: Callable[[str], Any] | None = None,
    ) -> FathomListing:
        """All meetings the API returns for the margin-widened window, all pages.

        Raises EvidenceHTTPError if a page cannot be fetched (the caller marks the run).
        Stops at `max_pages` only as a safety limit and says so in `stop_reason`.
        """
        listing = FathomListing()
        seen: set[str] = set()
        cursor: str | None = None
        base_params = {
            "include_transcript": "true",
            "include_summary": "false",
            # Lower bound only: a recording is never created before it starts (the margin
            # absorbs clock/scheduling skew), but it can be processed days or weeks after
            # the window ends. No upper bound, so a past week stays reconcilable.
            "created_after": iso_z(as_utc(window_start) - margin),
        }
        seen_cursors: set[str] = set()
        while True:
            if listing.pages >= self.max_pages:
                listing.stop_reason = f"page cap {self.max_pages} reached before the last page"
                return listing
            params = dict(base_params)
            if cursor:
                params["cursor"] = cursor
            resp = await self._get("/meetings", params, on_wait)
            if resp.status_code != 200:
                raise EvidenceHTTPError(resp.status_code, f"listing page {listing.pages + 1}")
            data = resp.json()
            listing.pages += 1
            items = data.get("items") or []
            listing.listed += len(items)
            for item in items:
                key = meeting_external_id(item)
                if key in seen:
                    listing.duplicates += 1
                    continue
                seen.add(key)
                listing.meetings.append(item)
            if on_page:
                await maybe_await(on_page(listing.pages, len(listing.meetings)))
            cursor = data.get("next_cursor")
            if not cursor:
                listing.pagination_finished = True
                return listing
            if cursor in seen_cursors:
                listing.stop_reason = "API repeated a pagination cursor"
                return listing
            seen_cursors.add(cursor)

    async def get_transcript(
        self, recording_id: str, on_wait: Callable[[str], Any] | None = None
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Return (transcript, None) or (None, reason)."""
        try:
            resp = await self._get(f"/recordings/{recording_id}/transcript", {}, on_wait)
        except EvidenceHTTPError as exc:
            return None, f"transcript request failed: {exc.reason}"
        if resp.status_code != 200:
            return None, f"transcript HTTP {resp.status_code}"
        data = resp.json()
        transcript = data.get("transcript") if isinstance(data, dict) else data
        if not transcript:
            return None, "transcript empty"
        return transcript, None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def meeting_external_id(item: dict[str, Any]) -> str:
    rid = item.get("recording_id")
    if rid is not None:
        return str(rid)
    return str(item.get("url") or item.get("share_url") or stable_hash(item))


def meeting_started_at(item: dict[str, Any]) -> datetime | None:
    return parse_iso(item.get("recording_start_time")) or parse_iso(
        item.get("scheduled_start_time")
    ) or parse_iso(item.get("created_at"))


def meeting_in_window(item: dict[str, Any], start: datetime, end: datetime) -> bool:
    return in_window(meeting_started_at(item), start, end)


def parse_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    parts = str(value).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def detect_language(text: str) -> tuple[str | None, bool]:
    """(language, uncertain) by script ratio. Mixed-script turns are uncertain."""
    heb = len(_HEBREW.findall(text or ""))
    lat = len(_LATIN.findall(text or ""))
    total = heb + lat
    if total == 0:
        return None, False
    ratio = heb / total
    if ratio >= 0.85:
        return "he", False
    if ratio <= 0.15:
        return "en", False
    return "mixed", True


def _ends_sentence(text: str) -> bool:
    stripped = (text or "").rstrip()
    return not stripped or stripped.endswith(_TERMINAL)


def _starts_mid_sentence(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0].isalpha() and stripped[0].islower()


def normalize_turns(
    transcript: list[dict[str, Any]], duration_s: float | None = None
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for raw in transcript or []:
        speaker = raw.get("speaker") or {}
        if isinstance(speaker, str):
            speaker = {"display_name": speaker}
        name = (speaker.get("display_name") or "").strip() or None
        email = speaker.get("matched_calendar_invitee_email") or None
        text = (raw.get("text") or "").strip()
        lang, uncertain = detect_language(text)
        turns.append({
            "index": len(turns),
            "speaker": name,
            "speaker_email": email,
            "start_s": parse_timestamp(raw.get("timestamp")),
            "end_s": None,
            "text": text,
            "speaker_confidence": "unknown" if not name else ("high" if email else "medium"),
            "language": lang,
            "language_uncertain": uncertain,
            "confidence_reasons": [] if name else ["speaker name missing"],
        })

    for i, turn in enumerate(turns):
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if nxt is not None and nxt["start_s"] is not None:
            turn["end_s"] = nxt["start_s"]
        elif turn["start_s"] is not None:
            words = len(_WORD.findall(turn["text"]))
            estimate = turn["start_s"] + max(1.0, words / 2.5)
            if duration_s is not None and duration_s >= turn["start_s"]:
                turn["end_s"] = max(duration_s, turn["start_s"])
            else:
                turn["end_s"] = estimate

    def lower(turn: dict[str, Any], reason: str) -> None:
        if turn["speaker_confidence"] != "unknown":
            turn["speaker_confidence"] = "low"
        if reason not in turn["confidence_reasons"]:
            turn["confidence_reasons"].append(reason)

    for i, turn in enumerate(turns):
        prev = turns[i - 1] if i > 0 else None
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if prev is not None and turn["start_s"] is not None and prev["start_s"] is not None:
            if turn["start_s"] < prev["start_s"]:
                lower(prev, "overlapping timestamps")
                lower(turn, "overlapping timestamps")
        if (
            prev is not None
            and prev["speaker"] != turn["speaker"]
            and not _ends_sentence(prev["text"])
            and _starts_mid_sentence(turn["text"])
        ):
            lower(prev, "speaker label switches mid-sentence")
            lower(turn, "speaker label switches mid-sentence")
        if (
            prev is not None
            and nxt is not None
            and prev["speaker"] == nxt["speaker"]
            and turn["speaker"] != prev["speaker"]
            and turn["start_s"] is not None
            and turn["end_s"] is not None
            and turn["end_s"] - turn["start_s"] <= 1.0
        ):
            lower(prev, "rapid speaker alternation")
            lower(turn, "rapid speaker alternation")
            lower(nxt, "rapid speaker alternation")
        if turn["start_s"] is not None and turn["end_s"] is not None:
            duration = turn["end_s"] - turn["start_s"]
            words = len(_WORD.findall(turn["text"]))
            if words >= 12 and duration > 0 and words / duration > 7.0:
                lower(turn, "too many words for the turn length (interleaved speakers)")
    return turns


def normalize_meeting(
    item: dict[str, Any], transcript: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Normalized private payload. Hash covers only content that matters for extraction."""
    started = parse_iso(item.get("recording_start_time"))
    ended = parse_iso(item.get("recording_end_time"))
    duration = (ended - started).total_seconds() if started and ended else None
    turns = normalize_turns(transcript or [], duration)
    langs = [t["language"] for t in turns if t["language"] in ("he", "en")]
    language = item.get("transcript_language") or (
        max(set(langs), key=langs.count) if langs else None
    )
    invitees = item.get("calendar_invitees") or []
    return {
        "recording_id": meeting_external_id(item),
        "title": item.get("title") or item.get("meeting_title"),
        "started_at": iso_z(started) if started else None,
        "ended_at": iso_z(ended) if ended else None,
        "duration_s": duration,
        "language": language,
        "turns": turns,
        "participants": [
            {
                "name": i.get("name"),
                "email": i.get("email"),
                "is_external": i.get("is_external"),
                "matched_speaker_display_name": i.get("matched_speaker_display_name"),
            }
            for i in invitees
        ],
    }


def meeting_meta(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    turns = payload["turns"]
    return {
        "participants_count": len(payload["participants"]),
        "external_participants": sum(1 for p in payload["participants"] if p.get("is_external")),
        "turn_count": len(turns),
        "speaker_count": len({t["speaker"] for t in turns if t["speaker"]}),
        "low_confidence_turns": sum(
            1 for t in turns if t["speaker_confidence"] in ("low", "unknown")
        ),
        "language_uncertain_turns": sum(1 for t in turns if t["language_uncertain"]),
        "duration_s": payload["duration_s"],
    }
