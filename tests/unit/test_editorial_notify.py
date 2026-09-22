"""Notifications: a buzz only for work he asked for that finished while away.

The reconciler runs every minute, so the test that matters most is that it does
not say the same thing sixty times an hour. After that: it never buzzes about a
synthetic pipeline take, it does not wake him about something that finished two
days ago, and a browser that dropped its subscription is not an error.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from tce.editorial import notify
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate

WEEK = datetime(2026, 9, 21)


def gates() -> dict:
    return {
        k: {"pass": True, "reason": "y"}
        for k in (
            "small_service_business",
            "coach_or_event_owner_relevance",
            "concrete_supported_substance",
            "connects_to_ziv_work",
        )
    }


async def add_candidate(session, ws, title, origin="selector"):
    row = TopicCandidate(
        workspace_id=ws,
        week_start=WEEK,
        moment_ids=[],
        title=title,
        lesson="l",
        audience="coaches",
        public_angle="a",
        gates=gates(),
        status="proposed",
        origin=origin,
    )
    session.add(row)
    await session.flush()
    return row


async def add_packet(session, ws, candidate, *, status="ready", age_hours=0):
    row = RecordingPacket(
        workspace_id=ws,
        candidate_id=candidate.id,
        version=1,
        bullets=["a"],
        script_phrases=["b"],
        status=status,
        citations_private=[],
        public_safety={},
    )
    session.add(row)
    await session.flush()
    row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=age_hours)
    await session.flush()
    return row


async def add_upload(session, ws, candidate, *, status="edited", age_hours=0, digest="a"):
    row = RecordingUpload(
        workspace_id=ws,
        candidate_id=candidate.id,
        original_filename="take.mp4",
        storage_path="/tmp/take.mp4",
        sha256=digest * 64,
        status=status,
    )
    session.add(row)
    await session.flush()
    row.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=age_hours)
    await session.flush()
    return row


# ---------------------------------------------------------------- collecting


async def test_a_ready_script_is_worth_saying(editorial_session):
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "The four jobs")
    await add_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    events = await notify.collect_events(editorial_session, ws)

    assert len(events) == 1
    assert events[0]["kind"] == "script_ready"
    assert events[0]["body"] == "The four jobs"
    # Tapping it lands on the script, not on a list to hunt through.
    assert events[0]["path"].startswith("/scripts/")


async def test_a_synthetic_pipeline_take_never_buzzes(editorial_session):
    ws = uuid.uuid4()
    candidate = await add_candidate(
        editorial_session, ws, "SYNTHETIC TECHNICAL TEST", origin="technical_validation"
    )
    await add_packet(editorial_session, ws, candidate)
    await add_upload(editorial_session, ws, candidate)
    await editorial_session.commit()

    assert await notify.collect_events(editorial_session, ws) == []


async def test_something_that_finished_two_days_ago_is_not_news(editorial_session):
    """A restart must not buzz about everything that ever became ready."""
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "Old news")
    await add_packet(editorial_session, ws, candidate, age_hours=48)
    await editorial_session.commit()

    assert await notify.collect_events(editorial_session, ws) == []


async def test_a_cut_that_would_change_his_words_is_its_own_kind(editorial_session):
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "A recorded one")
    await add_upload(editorial_session, ws, candidate, status="needs_review")
    await editorial_session.commit()

    events = await notify.collect_events(editorial_session, ws)
    assert [e["kind"] for e in events] == ["needs_review"]
    assert "would change what you said" in events[0]["body"]


# ------------------------------------------------------------------- dedupe


async def test_the_same_thing_is_claimed_once_however_often_it_runs(editorial_session):
    """The reconciler runs every minute. Without this he gets sixty buzzes an hour."""
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "The four jobs")
    await add_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    events = await notify.collect_events(editorial_session, ws)
    first = await notify.record_event(editorial_session, ws, events[0])
    await editorial_session.commit()
    second = await notify.record_event(editorial_session, ws, events[0])
    await editorial_session.commit()

    assert first is not None
    assert second is None


async def test_a_new_version_of_the_same_script_is_a_new_thing_to_say(editorial_session):
    """Dedupe is per object AND the state it reached, not per object."""
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "The four jobs")
    first = await add_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    events = await notify.collect_events(editorial_session, ws)
    keys = {e["dedupe_key"] for e in events}
    assert f"script_ready:{first.id}:1" in keys


# ----------------------------------------------------------------- delivery


async def test_with_nothing_subscribed_the_event_is_recorded_not_failed(editorial_session):
    """No subscribers is a normal state, not an error to show him."""
    ws = uuid.uuid4()
    candidate = await add_candidate(editorial_session, ws, "The four jobs")
    await add_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    events = await notify.collect_events(editorial_session, ws)
    claimed = await notify.record_event(editorial_session, ws, events[0])
    await notify.deliver(editorial_session, ws, claimed)
    await editorial_session.commit()

    assert claimed.state == "no_subscribers"


async def test_a_browser_is_stored_once_however_often_it_registers(editorial_session):
    ws = uuid.uuid4()
    endpoint = "https://push.example.com/abc123"

    first = await notify.subscribe(
        editorial_session, ws, endpoint=endpoint, p256dh="key1", auth="auth1"
    )
    second = await notify.subscribe(
        editorial_session, ws, endpoint=endpoint, p256dh="key2", auth="auth2"
    )
    await editorial_session.commit()

    assert first.id == second.id
    # Rotated keys replace the old ones rather than leaving a dead row behind.
    assert second.p256dh == "key2"
    rows = await notify.active_subscriptions(editorial_session, ws)
    assert len(rows) == 1


async def test_unsubscribing_removes_the_endpoint(editorial_session):
    ws = uuid.uuid4()
    endpoint = "https://push.example.com/abc123"
    await notify.subscribe(
        editorial_session, ws, endpoint=endpoint, p256dh="k", auth="a"
    )
    await editorial_session.commit()

    removed = await notify.unsubscribe(editorial_session, ws, endpoint=endpoint)
    await editorial_session.commit()

    assert removed is True
    assert await notify.active_subscriptions(editorial_session, ws) == []


async def test_a_subscription_without_keys_is_refused(editorial_session):
    ws = uuid.uuid4()
    try:
        await notify.subscribe(
            editorial_session, ws, endpoint="https://push.example.com/x", p256dh="", auth=""
        )
    except notify.NotifyError as error:
        assert error.code == "incomplete"
    else:  # pragma: no cover
        raise AssertionError("an incomplete subscription was accepted")


async def test_another_workspace_is_never_notified(editorial_session):
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    candidate = await add_candidate(editorial_session, theirs, "Not mine")
    await add_packet(editorial_session, theirs, candidate)
    await editorial_session.commit()

    assert await notify.collect_events(editorial_session, mine) == []
