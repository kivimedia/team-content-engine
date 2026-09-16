"""Fathom adapter + coverage ledger. Synthetic fixtures only."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select

from tce.evidence.collect import collect_fathom
from tce.evidence.common import RetryPolicy
from tce.evidence.fathom import FathomClient, detect_language, normalize_turns
from tce.models.editorial import EvidenceCollectionRun, EvidenceMoment, EvidenceSource

WS = uuid.uuid4()
START = datetime(2026, 9, 7, tzinfo=UTC)
END = datetime(2026, 9, 14, tzinfo=UTC)


def meeting(rid: int, start: str, transcript=True, text="We fixed the intake form first."):
    item = {
        "recording_id": rid,
        "title": f"Synthetic meeting {rid}",
        "url": f"https://example.test/calls/{rid}",
        "share_url": f"https://example.test/share/{rid}",
        "created_at": start,
        "recording_start_time": start,
        "recording_end_time": start.replace("T10:", "T11:"),
        "transcript_language": "en",
        "calendar_invitees": [
            {"name": "Host", "email": "host@example.test", "is_external": False,
             "matched_speaker_display_name": "Host"},
        ],
        "transcript": None,
    }
    if transcript:
        item["transcript"] = [
            {"speaker": {"display_name": "Host",
                         "matched_calendar_invitee_email": "host@example.test"},
             "text": text, "timestamp": "00:00:05"},
            {"speaker": {"display_name": "Guest", "matched_calendar_invitee_email": None},
             "text": "Why that one first?", "timestamp": "00:00:20"},
            {"speaker": {"display_name": "Host",
                         "matched_calendar_invitee_email": "host@example.test"},
             "text": "Because every lead passes through it.", "timestamp": "00:00:31"},
        ]
    return item


class FakeFathom:
    def __init__(self, pages: list[list[dict]], transcripts: dict[str, list] | None = None):
        self.pages = pages
        self.transcripts = transcripts or {}
        self.calls: list[httpx.Request] = []
        self.rate_limited_once = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers.get("X-Api-Key") == "test-key"
        path = request.url.path
        if path.endswith("/meetings"):
            cursor = request.url.params.get("cursor")
            idx = 0 if not cursor else int(cursor.removeprefix("c"))
            if idx == 1 and not self.rate_limited_once:
                self.rate_limited_once = True
                return httpx.Response(429, headers={"Retry-After": "3"})
            nxt = f"c{idx + 1}" if idx + 1 < len(self.pages) else None
            return httpx.Response(200, json={"items": self.pages[idx], "next_cursor": nxt})
        if "/recordings/" in path and path.endswith("/transcript"):
            rid = path.split("/")[-2]
            if rid in self.transcripts:
                return httpx.Response(200, json={"transcript": self.transcripts[rid]})
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(404)


def make_client(fake: FakeFathom, sleeps: list[float]) -> FathomClient:
    async def sleep(s: float) -> None:
        sleeps.append(s)

    return FathomClient(
        "test-key", "https://fathom.example.test/external/v1",
        transport=httpx.MockTransport(fake.handler), sleep=sleep,
        retry=RetryPolicy(max_attempts=4, base_backoff_s=0.01),
    )


def base_pages():
    return [
        [meeting(1, "2026-09-08T10:00:00Z"), meeting(2, "2026-09-09T10:00:00Z")],
        [
            meeting(2, "2026-09-09T10:00:00Z"),  # duplicate across pages
            meeting(3, "2026-09-20T10:00:00Z"),  # returned by the API but outside window
            meeting(4, "2026-09-10T10:00:00Z", transcript=False),  # transcript unobtainable
        ],
    ]


async def _run(sessionmaker, fake):
    sleeps: list[float] = []
    client = make_client(fake, sleeps)
    run_id = await collect_fathom(sessionmaker, WS, START, END, client=client)
    await client.aclose()
    async with sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    return run, sleeps


async def test_pagination_retry_dedupe_window_and_missing_transcript(editorial_sessionmaker):
    fake = FakeFathom(base_pages())
    run, sleeps = await _run(editorial_sessionmaker, fake)

    assert 3.0 in sleeps  # Retry-After honoured
    list_calls = [c for c in fake.calls if c.url.path.endswith("/meetings")]
    assert list_calls[0].url.params["include_transcript"] == "true"
    assert list_calls[0].url.params["created_after"] < "2026-09-07"  # margin applied
    assert "created_before" not in list_calls[0].url.params  # late processing stays visible
    assert run.counts["pages"] == 2
    assert run.counts["duplicates_skipped"] == 1
    assert run.counts["in_window"] == 3
    assert run.counts["outside_window"] == 1
    states = {i["external_id"]: i["state"] for i in run.items}
    assert states == {"1": "processed", "2": "processed", "4": "unavailable"}
    reason4 = next(i["reason"] for i in run.items if i["external_id"] == "4")
    assert "transcript" in reason4
    assert run.complete is True  # pagination finished, nothing failed
    assert run.status == "partial"  # one meeting has no transcript
    assert "Finished" in run.current_activity

    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(EvidenceSource))).scalars().all()
    by_id = {r.external_id: r for r in rows}
    assert set(by_id) == {"1", "2", "4"}
    assert by_id["4"].fetch_status == "partial"
    assert by_id["1"].payload_private["turns"][0]["start_s"] == 5.0
    assert by_id["1"].payload_private["turns"][0]["end_s"] == 20.0


async def test_rerun_unchanged_late_recording_and_edit(editorial_sessionmaker):
    pages = base_pages()
    await _run(editorial_sessionmaker, FakeFathom(copy.deepcopy(pages)))

    # moment attached to meeting 1
    async with editorial_sessionmaker() as s:
        src1 = (await s.execute(
            select(EvidenceSource).where(EvidenceSource.external_id == "1")
        )).scalar_one()
        s.add(EvidenceMoment(
            workspace_id=WS, source_id=src1.id, source_version_hash=src1.version_hash,
            excerpt_private="x", lesson_summary="y", claim_type="quoted", status="active",
        ))
        await s.commit()

    # same data -> unchanged, no duplicates
    run2, _ = await _run(editorial_sessionmaker, FakeFathom(copy.deepcopy(pages)))
    states = {i["external_id"]: i["state"] for i in run2.items}
    assert states["1"] == "unchanged" and states["2"] == "unchanged"

    # late recording inside the window appears + transcript of 1 edited
    pages3 = copy.deepcopy(pages)
    pages3[0][0] = meeting(1, "2026-09-08T10:00:00Z", text="We fixed the booking form first.")
    pages3[1].append(meeting(5, "2026-09-12T10:00:00Z"))
    run3, _ = await _run(editorial_sessionmaker, FakeFathom(pages3))
    states = {i["external_id"]: i["state"] for i in run3.items}
    assert states["5"] == "processed"
    assert states["1"] == "updated"
    assert states["2"] == "unchanged"

    async with editorial_sessionmaker() as s:
        count = (await s.execute(select(func.count()).select_from(EvidenceSource))).scalar()
        src1 = (await s.execute(
            select(EvidenceSource).where(EvidenceSource.external_id == "1")
        )).scalar_one()
        moment = (await s.execute(select(EvidenceMoment))).scalar_one()
    assert count == 4
    assert src1.revision == 2
    assert src1.source_updated_at is not None
    assert moment.status == "stale"


async def test_transcript_fetched_separately_when_not_included(editorial_sessionmaker):
    m = meeting(7, "2026-09-11T10:00:00Z", transcript=False)
    full = meeting(7, "2026-09-11T10:00:00Z")["transcript"]
    fake = FakeFathom([[m]], transcripts={"7": full})
    run, _ = await _run(editorial_sessionmaker, fake)
    assert run.items == [{"external_id": "7", "state": "processed", "reason": None}]
    assert run.status == "complete" and run.complete is True


async def test_page_cap_marks_run_incomplete(editorial_sessionmaker):
    pages = [[meeting(10 + i, "2026-09-08T10:00:00Z")] for i in range(5)]
    fake = FakeFathom(pages)
    fake.rate_limited_once = True
    sleeps: list[float] = []
    client = make_client(fake, sleeps)
    client.max_pages = 2
    run_id = await collect_fathom(editorial_sessionmaker, WS, START, END, client=client)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    assert run.complete is False
    assert run.status == "partial"
    assert any("page cap" in e["reason"] for e in run.errors)


async def test_listing_failure_is_failed_run(editorial_sessionmaker):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    client = FathomClient("test-key", "https://fathom.example.test",
                          transport=httpx.MockTransport(handler))
    run_id = await collect_fathom(editorial_sessionmaker, WS, START, END, client=client)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    assert run.status == "failed" and run.complete is False
    assert "test-key" not in str(run.errors)


def test_speaker_confidence_unknown_and_low():
    turns = normalize_turns([
        {"speaker": {"display_name": "", "matched_calendar_invitee_email": None},
         "text": "Hello there.", "timestamp": "00:00:01"},
        {"speaker": {"display_name": "Host", "matched_calendar_invitee_email": "h@example.test"},
         "text": "So the thing we need to", "timestamp": "00:00:04"},
        {"speaker": {"display_name": "Guest", "matched_calendar_invitee_email": None},
         "text": "change is the follow up.", "timestamp": "00:00:07"},
        {"speaker": {"display_name": "Host", "matched_calendar_invitee_email": "h@example.test"},
         "text": "Right.", "timestamp": "00:00:06"},  # overlapping timestamp
        {"speaker": {"display_name": "Planner", "matched_calendar_invitee_email": None},
         "text": "A clean sentence.", "timestamp": "00:00:30"},
    ])
    assert turns[0]["speaker_confidence"] == "unknown"
    assert turns[1]["speaker_confidence"] == "low"  # label switch mid-sentence
    assert turns[2]["speaker_confidence"] == "low"
    assert turns[3]["speaker_confidence"] == "low"  # timestamps overlap
    assert turns[4]["speaker_confidence"] == "medium"
    assert "mid-sentence" in " ".join(turns[1]["confidence_reasons"])


def test_rapid_alternation_is_low():
    turns = normalize_turns([
        {"speaker": {"display_name": "A"}, "text": "First point here.", "timestamp": "00:00:10"},
        {"speaker": {"display_name": "B"}, "text": "Yes.", "timestamp": "00:00:12"},
        {"speaker": {"display_name": "A"}, "text": "Second point.", "timestamp": "00:00:12"},
    ])
    assert turns[1]["speaker_confidence"] == "low"


def test_language_detection_mixed_turn():
    assert detect_language("שלום לכום") == ("he", False)
    assert detect_language("plain english words") == ("en", False)
    lang, uncertain = detect_language("שלום לכום follow up")
    assert lang == "mixed" and uncertain is True
    turns = normalize_turns([
        {"speaker": {"display_name": "A"},
         "text": "נעשה follow up מחר", "timestamp": "00:00:01"},
    ])
    assert turns[0]["language_uncertain"] is True
