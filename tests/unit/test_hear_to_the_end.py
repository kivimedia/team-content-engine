"""A transcript that stopped before the original did (27-Nov): the walk's transcript
ended at word 16 (0:07) while the original ran on, every edit kept 7 seconds, and
Jennifer asked him to upload the walk again. The rest is heard from the original."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production import autoedit, media, tail
from tce.settings import settings

WS = uuid.UUID("cccccccc-3333-4333-8333-333333333333")


def w(text: str, start: float, end: float) -> dict:
    return {"text": text, "start_s": start, "end_s": end, "precision": "word"}


# The first line, as the recogniser heard it: then nothing, though he spoke to 1:40.
FIRST_LINE = [w("Most", 0.4, 0.7), w("coaches", 0.7, 1.2), w("price", 1.2, 1.6),
              w("by", 1.6, 1.8), w("the", 1.8, 1.9), w("hour.", 1.9, 2.5)]
SPEECH = [(0.4, 2.5), (9.0, 14.0), (16.0, 30.0), (31.0, 70.0), (95.0, 100.0)]


def test_a_transcript_that_reaches_the_end_of_the_speech_is_left_alone():
    assert tail.unheard_stretches(FIRST_LINE, [(0.4, 2.5), (3.0, 4.0)], 5.0) == []


def test_a_cough_after_the_last_word_is_not_a_script():
    assert tail.unheard_stretches(FIRST_LINE, [(0.4, 2.5), (20.0, 21.0)], 30.0) == []


def test_the_speech_after_the_last_word_is_heard_in_recogniser_sized_stretches():
    got = tail.unheard_stretches(FIRST_LINE, SPEECH, 101.0)
    assert got[0][0] == 8.7 and got[-1][1] == 100.3
    assert all(b - a <= tail.CLIP_S + 1e-6 for a, b in got)
    covered = lambda s, e: any(a <= s and e <= b for a, b in got)  # noqa: E731
    assert covered(9.0, 14.0) and covered(16.0, 30.0) and covered(95.0, 100.0)
    # The long region is heard in pieces that follow one another, with no gap between.
    pieces = [g for g in got if g[0] >= 30.7 and g[1] <= 71.0]
    assert len(pieces) == 2
    assert all(pieces[k][1] == pieces[k + 1][0] for k in range(len(pieces) - 1))


def test_a_stretch_never_runs_past_the_end_of_the_file():
    assert tail.unheard_stretches(FIRST_LINE, [(0.4, 2.5), (40.0, 44.95)], 45.0)[-1][1] == 45.0


def test_the_words_heard_come_back_on_the_recordings_clock_once_each():
    heard = [
        (8.7, 14.3, {"words": [{"word": "That", "start": 0.4, "end": 0.7},
                               {"word": "tells", "start": 0.7, "end": 1.0}]}),
        (14.3, 39.3, {"words": [{"word": "But", "start": 1.8, "end": 2.0},
                                {"word": "cut", "start": 24.9, "end": 25.3}]}),  # middle past the end
        (39.3, 64.3, {"words": [{"word": "cut", "start": -0.1, "end": 0.3},  # middle here: kept
                                {"word": "", "start": 1.0, "end": 1.2}]}),
        (64.3, 70.3, None),  # the worker did not answer for this one
    ]
    added = tail.place(FIRST_LINE, heard)
    assert [(x["text"], x["start_s"]) for x in added] == [
        ("That", 9.1), ("tells", 9.4), ("But", 16.1), ("cut", 39.2)]
    assert all(x["precision"] == "word" and x["heard_to_end"] for x in added)


def test_jennifer_is_told_the_original_is_on_the_server():
    assert "never ask him to upload, re-upload or find the original" in autoedit.edit_request_system()


async def _seed(sessionmaker, tmp_path, words, status="edited"):
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic walk")
    cand = TopicCandidate(
        workspace_id=WS, week_start=datetime(2026, 11, 23), moment_ids=[str(uuid.uuid4())],
        title="Price the change", lesson="l", audience="a", public_angle="p", gates={},
        status="selected",
    )
    async with sessionmaker() as s:
        s.add(cand)
        await s.flush()
        row = RecordingUpload(
            workspace_id=WS, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(src), sha256=uuid.uuid4().hex * 2, duration_s=101.0,
            transcript=words, status=status, status_detail="Edited",
        )
        s.add(row)
        await s.commit()
        return row.id


def _hearing(monkeypatch, sessionmaker, regions, answer):
    monkeypatch.setattr(prod, "session_factory", lambda: sessionmaker)
    monkeypatch.setattr(settings, "production_transcribe_ws_url", "ws://worker")

    async def activity(_src):
        return SimpleNamespace(regions=regions)

    heard: list[tuple[float, float]] = []

    async def clip(_src, a, b, **_kw):
        heard.append((a, b))
        return answer(a, b)

    monkeypatch.setattr(prod, "_speech_activity", activity)
    monkeypatch.setattr(media, "transcribe_clip", clip)
    return heard


async def test_the_rest_of_the_original_is_heard_and_added(editorial_sessionmaker, monkeypatch, tmp_path):
    upload_id = await _seed(editorial_sessionmaker, tmp_path, FIRST_LINE)
    heard = _hearing(monkeypatch, editorial_sessionmaker, SPEECH,
                     lambda a, b: {"words": [{"word": f"w{int(a)}", "start": 0.5, "end": 0.9}]})
    added = await prod._hear_to_the_end(upload_id, WS)
    assert added == len(heard) > 1
    async with editorial_sessionmaker() as s:
        row = await prod._load(s, upload_id, WS)
    assert row.transcript[:6] == FIRST_LINE and len(row.transcript) == 6 + added
    assert row.edit_plan["heard_to_end"]["heard_until"] == 2.5
    assert "stopped at 0:02" in row.status_detail and "Heard the rest of the original" in row.status_detail
    # Heard once: the next edit finds the transcript reaching the end and hears nothing.
    assert await prod._hear_to_the_end(upload_id, WS) == 0


async def test_a_worker_that_hears_nothing_leaves_the_card_as_it_was(
    editorial_sessionmaker, monkeypatch, tmp_path
):
    upload_id = await _seed(editorial_sessionmaker, tmp_path, FIRST_LINE)
    _hearing(monkeypatch, editorial_sessionmaker, SPEECH, lambda a, b: {"words": []})
    assert await prod._hear_to_the_end(upload_id, WS) == 0
    async with editorial_sessionmaker() as s:
        row = await prod._load(s, upload_id, WS)
    assert row.transcript == FIRST_LINE
    assert (row.status, row.status_detail) == ("edited", "Edited")


async def test_a_complete_transcript_is_never_sent_to_the_worker(editorial_sessionmaker, monkeypatch, tmp_path):
    upload_id = await _seed(editorial_sessionmaker, tmp_path, FIRST_LINE)
    heard = _hearing(monkeypatch, editorial_sessionmaker, [(0.4, 2.5)], lambda a, b: {})
    assert await prod._hear_to_the_end(upload_id, WS) == 0 and heard == []
