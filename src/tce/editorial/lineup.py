"""The weekly recording lineup: his usual number of videos, a reserve, and a reason beside each.

The old queue answered "what has a script". This answers "what am I recording
this week, in what order, and why that one first" - which is the decision Ziv
actually makes, and the one the interface never had a place for.

Two deliberate refusals:

*No numeric score in the interface.* The selector has `rank_score` and it stays
internal. "87 points" looks precise and helps nobody choose; a sentence naming
what makes a topic urgent does.

*No quota enforcement.* Lane labels (build / coaching / ai news) are shown so an
unbalanced week is visible, never to refuse a third build topic. It is his week.

Concurrency: `WeeklyLineup.revision` is the token. Every mutation states the
revision it read and a stale write is refused with the newer state, because the
phone in his pocket and the tab on his desk are the same week.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import current_week_start, week_bounds
from tce.editorial.library import technical_candidate_ids
from tce.models.editorial import (
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
    VideoPublication,
)
from tce.models.editorial_workspace import (
    LINEUP_SLOTS,
    EditorialSettings,
    TopicDecision,
    WeeklyLineup,
    WeeklyLineupItem,
)

DEFAULT_PRIMARY_SLOTS = 3
MIN_VIDEOS_PER_WEEK = 1
MAX_VIDEOS_PER_WEEK = 14

LANE_LABELS = {
    "build": "Build",
    "coaching": "Coaching",
    # Ziv's own name for the lane (21-Sep). The key stays "ai_news" because other
    # code and stored lineups read it; only what he sees changes.
    "ai_news": "News that excites Ziv",
    "other": "Other",
    # Idea lanes of a profiled workspace (tce.editorial.lane_profile, Matan).
    "trend_reaction": "טרנד מהעולם",
    "magic_clip": "קליפ של קוסם",
    "behind_scenes": "מאחורי הקלעים",
}


class LineupError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


def week_start_for(value: date | datetime | str | None) -> datetime:
    """Normalise any week reference to the Monday datetime the rest of TCE uses."""
    return week_bounds(value if value is not None else current_week_start())[0]


def lane_for(candidate: TopicCandidate) -> str:
    """Which of the three content lanes this topic belongs to.

    Read from the evidence that produced it, so the label is a fact about the
    idea rather than a guess: news is flagged by the selector, code citations
    mean it came out of something built, and the rest is coaching.

    A workspace with idea lanes reads its lane off the cited evidence kind; the
    selector already enforced one lane's evidence per idea.
    """
    from tce.editorial import lane_profile

    profile = lane_profile.profile_for(getattr(candidate, "workspace_id", None))
    if profile is not None:
        for c in candidate.citations_private or []:
            lane = profile.lane_for_kind(c.get("source_kind")) if isinstance(c, dict) else None
            if lane is not None:
                return lane.key
        return "other"
    if candidate.freshness_role == "news":
        return "ai_news"
    kinds = {
        c.get("source_kind")
        for c in (candidate.citations_private or [])
        if isinstance(c, dict)
    }
    if "github_commit_group" in kinds:
        return "build"
    if candidate.audience in ("coaches", "both"):
        return "coaching"
    return "other"


def reason_for(candidate: TopicCandidate, *, rank: int, slot: str) -> str:
    """The sentence shown beside the item. Composed from stored facts only."""
    clauses: list[str] = []
    if candidate.freshness_role == "news":
        clauses.append("it is timely")
    kinds = [
        c.get("source_kind")
        for c in (candidate.citations_private or [])
        if isinstance(c, dict)
    ]
    if "github_commit_group" in kinds:
        clauses.append("it connects to something you built")
    if "fathom_meeting" in kinds:
        clauses.append("it came out of a real conversation")
    reasons = [r for r in (candidate.reasons_to_care or []) if isinstance(r, str) and r.strip()]
    if reasons:
        clauses.append(reasons[0].strip().rstrip("."))

    if not clauses:
        return "In reserve." if slot == "reserve" else "In this week's list."
    lead = "Record first because" if (slot == "primary" and rank == 1) else "Here because"
    if len(clauses) == 1:
        body = clauses[0]
    else:
        body = ", ".join(clauses[:-1]) + " and " + clauses[-1]
    return f"{lead} {body}."


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def get_lineup(
    db: AsyncSession, ws: uuid.UUID, week_start: datetime
) -> WeeklyLineup | None:
    result = await db.execute(
        select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws, WeeklyLineup.week_start == week_start
        )
    )
    return result.scalar_one_or_none()


async def videos_per_week(db: AsyncSession, ws: uuid.UUID) -> int:
    """His usual number of videos a week (the Settings page). Three until he sets it."""
    row = (
        await db.execute(select(EditorialSettings).where(EditorialSettings.workspace_id == ws))
    ).scalar_one_or_none()
    return row.videos_per_week if row is not None else default_videos_per_week(ws)


def default_videos_per_week(ws: uuid.UUID) -> int:
    """Three for the owner; a workspace with idea lanes starts from its profile's number
    (5-Oct: five for Matan, his minimum; he can record more, never capped)."""
    from tce.editorial.lane_profile import profile_for

    profile = profile_for(ws)
    if profile is not None and profile.videos_per_week:
        return profile.videos_per_week
    return DEFAULT_PRIMARY_SLOTS


async def post_rules(db: AsyncSession, ws: uuid.UUID) -> str:
    """How his posts must read (the Settings page). The no-call-to-action rule until he
    writes his own."""
    from tce.production.publishing import DEFAULT_POST_RULES

    row = (
        await db.execute(select(EditorialSettings).where(EditorialSettings.workspace_id == ws))
    ).scalar_one_or_none()
    text = (row.post_rules or "").strip() if row is not None else ""
    return text or DEFAULT_POST_RULES


async def set_post_rules(db: AsyncSession, ws: uuid.UUID, rules: str) -> str:
    from tce.production.publishing import DEFAULT_POST_RULES

    text = (rules or "").strip()
    if len(text) > 4000:
        raise LineupError("too_long", "keep the post rules under 4000 characters", status=400)
    row = (
        await db.execute(select(EditorialSettings).where(EditorialSettings.workspace_id == ws))
    ).scalar_one_or_none()
    if row is None:
        row = EditorialSettings(workspace_id=ws, videos_per_week=default_videos_per_week(ws))
        db.add(row)
    row.post_rules = text or None
    await db.flush()
    return text or DEFAULT_POST_RULES


async def set_videos_per_week(db: AsyncSession, ws: uuid.UUID, count: int) -> int:
    """Save his number, and apply it to this week and every week already started
    after it: a week he is in the middle of follows the setting he just chose."""
    if not isinstance(count, int) or not MIN_VIDEOS_PER_WEEK <= count <= MAX_VIDEOS_PER_WEEK:
        raise LineupError(
            "bad_count",
            f"choose between {MIN_VIDEOS_PER_WEEK} and {MAX_VIDEOS_PER_WEEK} videos a week",
            status=400,
        )
    row = (
        await db.execute(select(EditorialSettings).where(EditorialSettings.workspace_id == ws))
    ).scalar_one_or_none()
    if row is None:
        db.add(EditorialSettings(workspace_id=ws, videos_per_week=count))
    else:
        row.videos_per_week = count
    weeks = await db.execute(
        select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws, WeeklyLineup.week_start >= week_start_for(None)
        )
    )
    for week in weeks.scalars().all():
        week.primary_slots = count
    await db.flush()
    return count


async def ensure_lineup(
    db: AsyncSession, ws: uuid.UUID, week_start: datetime
) -> WeeklyLineup:
    """Get or create this week's lineup. Idempotent under two simultaneous opens."""
    existing = await get_lineup(db, ws, week_start)
    if existing is not None:
        return existing
    row = WeeklyLineup(
        workspace_id=ws,
        week_start=week_start,
        status="draft",
        revision=1,
        primary_slots=await videos_per_week(db, ws),
    )
    try:
        # A savepoint, so losing the race undoes this insert and nothing else.
        # 28-Sep review: every reader of this week creates its row now (the voice
        # lookups, the typed conversation), and a full rollback here threw away
        # what the caller had already done: a brief seeded a moment before was
        # lost, and the next read of a topic it had loaded raised MissingGreenlet.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        if row in db:
            db.expunge(row)
        again = await get_lineup(db, ws, week_start)
        if again is None:  # pragma: no cover
            raise
        return again
    return row


# Take states that do not make a topic filmed. 28-Sep: a take only resting on the
# server ("uploaded", nothing run on it) is one he counts as "didn't film them
# yet"; a superseded one was replaced by a newer take and no longer says how far
# it got. Every state from transcribing to edited means he filmed it and the
# pipeline took it up.
_TAKE_NOT_FILMED = ("uploaded", "superseded")
# A step that stopped: it threw, the PC worker was away, the server restarted.
# The name says how the last step ended, not how far the take got (28-Sep
# review): a re-render of a finished edit that throws leaves "failed" on a take
# that still holds its transcript, its cut and its edited video. So a stopped
# take is filmed when the pipeline made something of it, and not when it
# stopped before a word was heard.
_TAKE_STOPPED = ("failed", "unavailable", "interrupted")


def _real_takes(ws: uuid.UUID, ids: list[uuid.UUID]) -> tuple[Any, ...]:
    """A take of his: one the Library still shows (not archived) of a topic that
    is not the pipeline's own synthetic test. "He has a take of it" and "he filmed
    it" both start from here, so the two can never disagree on what a take is."""
    return (
        RecordingUpload.workspace_id == ws,
        RecordingUpload.candidate_id.in_(ids),
        RecordingUpload.candidate_id.notin_(technical_candidate_ids(ws)),
        RecordingUpload.archived_at.is_(None),
    )


async def taken_candidate_ids(
    db: AsyncSession, ws: uuid.UUID, ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of these topics he has a take of, in any state, resting included.

    28-Sep, Ziv asked for this to be fixed: "Your 'need a decision' count may go
    up a little. Topics with only an unedited take now show there too." A take
    resting on the server is not filmed (the week still offers it for
    recording), but it is a decision already made: he stood in front of the
    camera for it. So an undecided topic with a take is not waiting for him. An
    archived take is one he set aside, and a synthetic test take was never his,
    so neither counts.
    """
    if not ids:
        return set()
    result = await db.execute(
        select(RecordingUpload.candidate_id).where(*_real_takes(ws, ids)).distinct()
    )
    return set(result.scalars())


async def filmed_candidate_ids(
    db: AsyncSession, ws: uuid.UUID, ids: list[uuid.UUID], *, since: datetime | None = None
) -> set[uuid.UUID]:
    """Which of these topics he has filmed. The one test for it.

    28-Sep: nothing marks a lineup item "recorded", and any upload marks the topic
    "recorded", even a take resting on the server, so neither status could say it.
    On the live week one topic had its captioned edit made and was still listed as
    planned, and another had only a resting take and was not filmed by his own
    word. Filmed means one of:

    - a take the Library still shows (not archived, not a synthetic pipeline
      test) that has moved past resting: transcribed, cut, in review or edited,
      or stopped on a step after the pipeline made something of it (a
      transcript, a cut, an edited video);
    - a take whose posts were written or went out, archived or not;
    - a topic marked published, which a post can only follow.

    The week, the carry into a new week, Today and the studio all ask this, so a
    filmed topic is never offered for recording again.

    With `since`, filmed from then on: only takes made since count, and a
    topic marked published does not by itself, since that mark carries no
    time. The tick asks this before saving a new script that was asked for
    earlier (status._filmed_since_asked).
    """
    if not ids:
        return set()
    technical = technical_candidate_ids(ws)
    after = (RecordingUpload.created_at >= since,) if since is not None else ()
    shown = (*_real_takes(ws, ids), *after)
    taken = await db.execute(
        select(RecordingUpload.candidate_id).where(
            *shown,
            RecordingUpload.status.notin_(_TAKE_NOT_FILMED + _TAKE_STOPPED),
        )
    )
    # Read in Python, not as IS NOT NULL: a JSON column can hold a JSON null,
    # and an empty transcript means nothing was heard. Stopped takes are few.
    stopped = await db.execute(
        select(
            RecordingUpload.candidate_id,
            RecordingUpload.transcript,
            RecordingUpload.edit_plan,
            RecordingUpload.edited_path,
        ).where(*shown, RecordingUpload.status.in_(_TAKE_STOPPED))
    )
    made_something = {
        row.candidate_id
        for row in stopped
        if row.transcript or row.edit_plan or row.edited_path
    }
    posted = await db.execute(
        select(RecordingUpload.candidate_id)
        .join(VideoPublication, VideoPublication.upload_id == RecordingUpload.id)
        .where(
            VideoPublication.workspace_id == ws,
            RecordingUpload.workspace_id == ws,
            RecordingUpload.candidate_id.in_(ids),
            RecordingUpload.candidate_id.notin_(technical),
            *after,
        )
    )
    published: set[uuid.UUID] = set()
    if since is None:
        published = set(
            (
                await db.execute(
                    select(TopicCandidate.id).where(
                        TopicCandidate.workspace_id == ws,
                        TopicCandidate.id.in_(ids),
                        TopicCandidate.id.notin_(technical),
                        TopicCandidate.status == "published",
                    )
                )
            ).scalars()
        )
    return set(taken.scalars()) | made_something | set(posted.scalars()) | published


# An item that stays behind when the week turns over: marked filmed or dropped.
_ITEM_STAYS_BEHIND = ("recorded", "dropped")


async def carry_forward(db: AsyncSession, ws: uuid.UUID, lineup: WeeklyLineup) -> int:
    """Bring the topics he chose and has not recorded into the week that just started.

    28-Sep: "tce is showing 0 scripts ready despite the fact that I has around 8
    topics chosen for this week and didnt film them yet". The week key is Monday
    in Israel time, so at 00:00 on Monday "this week" became a new, empty list,
    and Today, the week page, the studio and the voice call all read that list.
    A topic he chose is his until he records it or changes his mind; the calendar
    turning over is neither.

    Runs once per week (`carried_at` is the marker), and only into the week that
    is current now: a week he opens ahead of time is filled when it arrives, and
    an old week is history. The source is the most recent earlier week that was
    a real week, which itself carried from the one before, so a topic follows him
    week after week. Any read of a week's list creates its row, so an old week
    looked at by date is an empty row that says nothing; a real week has topics,
    or ran its own carry (then an empty one is a week he emptied himself, and the
    week before it must not come back through it).

    What comes over: every item not marked filmed or dropped, whose topic he has
    not filmed (`filmed_candidate_ids`: a take resting on the server is not
    filming), and that is still chosen for this week (or was listed before
    decisions were kept). A rejected topic stays behind. A topic the engine
    withdrew (a re-run of the week's selection, a stale news idea) comes over
    when he chose it for this week: his choice outranks the engine's, as in
    `voice_agent.chosen_and_listed`; one he put away himself is no longer chosen.
    Slot and order are kept, after anything already in the new week. The old
    week is not touched. One revision for the whole carry.

    Returns how many topics came over.
    """
    if lineup.carried_at is not None:
        return 0
    if lineup.week_start != week_start_for(None):
        return 0

    # Today and the studio can open together on Monday morning. Lock the week's
    # row and read the marker again, so the second read waits for the first and
    # then finds it done instead of copying the same topics twice. SQLite ignores
    # FOR UPDATE; the unique (lineup, topic) key is the backstop there.
    await db.execute(
        select(WeeklyLineup)
        .where(WeeklyLineup.workspace_id == ws, WeeklyLineup.id == lineup.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if lineup.carried_at is not None:
        return 0

    has_topics = (
        select(WeeklyLineupItem.id)
        .where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == WeeklyLineup.id,
        )
        .exists()
    )
    source = (
        await db.execute(
            select(WeeklyLineup)
            .where(
                WeeklyLineup.workspace_id == ws,
                WeeklyLineup.week_start < lineup.week_start,
                or_(has_topics, WeeklyLineup.carried_at.is_not(None)),
            )
            .order_by(WeeklyLineup.week_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    lineup.carried_at = datetime.now(UTC).replace(tzinfo=None)
    lineup.carried_from_lineup_id = source.id if source is not None else None
    if source is None:
        await db.flush()
        return 0

    old = await list_items(db, ws, source.id)
    here = await list_items(db, ws, lineup.id)
    listed = {i.candidate_id for i in here}
    next_rank = {slot: sum(1 for i in here if i.slot == slot) for slot in LINEUP_SLOTS}
    ids = [i.candidate_id for i in old]
    candidates = await _candidates_by_id(db, ws, ids)
    decisions: dict[uuid.UUID, str | None] = {}
    if ids:
        rows = await db.execute(
            select(TopicDecision).where(
                TopicDecision.workspace_id == ws, TopicDecision.candidate_id.in_(ids)
            )
        )
        decisions = {d.candidate_id: d.decision for d in rows.scalars()}
    filmed = await filmed_candidate_ids(db, ws, ids)

    carried = 0
    for item in old:  # already in slot, then rank, order
        candidate = candidates.get(item.candidate_id)
        if (
            item.candidate_id in listed
            or item.slot not in LINEUP_SLOTS
            or item.status in _ITEM_STAYS_BEHIND
            or candidate is None
            or candidate.status == "rejected"
            or item.candidate_id in filmed
            # Taken back, saved for later, marked to think about or put away since.
            or decisions.get(item.candidate_id, "this_week") != "this_week"
            # Withdrawn and never chosen in his own words: nothing outranks it.
            or (candidate.status == "withdrawn" and item.candidate_id not in decisions)
        ):
            continue
        next_rank[item.slot] += 1
        rank = next_rank[item.slot]
        db.add(
            WeeklyLineupItem(
                workspace_id=ws,
                lineup_id=lineup.id,
                candidate_id=item.candidate_id,
                packet_id=item.packet_id,
                rank=rank,
                slot=item.slot,
                lane=item.lane,
                # Written for its new place: "Record first because" belongs to
                # whichever topic is first in this week, not the one that was.
                reason=reason_for(candidate, rank=rank, slot=item.slot),
                status=item.status,
                added_by=item.added_by,
            )
        )
        listed.add(item.candidate_id)
        carried += 1
    if carried:
        lineup.revision += 1
        lineup.updated_by = "carried"
    await db.flush()
    return carried


async def current_lineup(db: AsyncSession, ws: uuid.UUID) -> WeeklyLineup:
    """This week's list, with last week's unrecorded topics in it.

    The one way to read "this week": Today, the week page, the studio queue, the
    voice call and the typed conversation all come through here, so none of them
    can show an empty week that the others would have filled. It writes on the
    first read of a new week, so a caller that only reads still commits.
    """
    lineup = await ensure_lineup(db, ws, week_start_for(None))
    await carry_forward(db, ws, lineup)
    return lineup


async def list_items(
    db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID
) -> list[WeeklyLineupItem]:
    result = await db.execute(
        select(WeeklyLineupItem)
        .where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup_id,
        )
        .order_by(WeeklyLineupItem.slot.asc(), WeeklyLineupItem.rank.asc())
    )
    return list(result.scalars().all())


async def _candidates_by_id(
    db: AsyncSession, ws: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, TopicCandidate]:
    if not ids:
        return {}
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(ids)
        )
    )
    return {c.id: c for c in result.scalars().all()}


async def _latest_packets(
    db: AsyncSession, ws: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RecordingPacket]:
    """Newest non-superseded packet per candidate, so the week can say 'script ready'."""
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(RecordingPacket)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id.in_(candidate_ids),
        )
        .order_by(RecordingPacket.version.asc())
    )
    newest: dict[uuid.UUID, RecordingPacket] = {}
    for packet in result.scalars().all():
        if packet.status == "superseded":
            continue
        newest[packet.candidate_id] = packet
    return newest


async def ready_script(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> RecordingPacket | None:
    """The topic's current script when it is ready to record, whatever week it is in.

    The same test the week uses for "script ready", for a topic he names from
    outside the week (the studio opens a topic he asks for by name).
    """
    packet = (await _latest_packets(db, ws, [candidate_id])).get(candidate_id)
    return packet if _script_state(packet) == "ready" else None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _check_revision(lineup: WeeklyLineup, expected: int | None) -> None:
    if expected is not None and expected != lineup.revision:
        raise LineupError(
            "conflict",
            (
                f"This week changed somewhere else (you had revision {expected}, it is "
                f"now {lineup.revision}). Nothing was moved."
            ),
            status=409,
            current_revision=lineup.revision,
        )


async def _renumber(db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID) -> None:
    """Keep ranks contiguous from 1 inside each slot.

    Gaps are how "Move up" starts behaving unpredictably three taps in, so they
    are closed after every mutation rather than tolerated.
    """
    for slot in LINEUP_SLOTS:
        result = await db.execute(
            select(WeeklyLineupItem)
            .where(
                WeeklyLineupItem.workspace_id == ws,
                WeeklyLineupItem.lineup_id == lineup_id,
                WeeklyLineupItem.slot == slot,
            )
            .order_by(WeeklyLineupItem.rank.asc(), WeeklyLineupItem.created_at.asc())
        )
        for index, item in enumerate(result.scalars().all(), start=1):
            if item.rank != index:
                item.rank = index
    await db.flush()


async def add_topic(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    candidate: TopicCandidate,
    *,
    slot: str = "primary",
    added_by: str | None = None,
    rank: int | None = None,
) -> WeeklyLineupItem:
    """Put a topic in the week, in the slot asked for.

    His number of videos a week is his usual week, not a wall (26-Sep: "I need to
    be able to promote more than the slots defined if I have a good week. nothing
    wrong with it."). A topic past that number goes into the week like any other;
    it used to be moved to reserve behind his back.

    `rank` puts it back at a known place (the one it was taken out of) instead of
    at the end, moving the ones below it down one. It is ignored when the topic
    overflows into reserve, because that place was in the other list.
    """
    if slot not in LINEUP_SLOTS:
        raise LineupError("bad_slot", f"unknown slot {slot}", status=400)

    existing = await db.execute(
        select(WeeklyLineupItem).where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup.id,
            WeeklyLineupItem.candidate_id == candidate.id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    items = await list_items(db, ws, lineup.id)
    wanted_slot = slot

    siblings = [i for i in items if i.slot == slot]
    at = len(siblings) + 1
    if rank is not None and slot == wanted_slot and 1 <= rank < at:
        for sibling in siblings:
            if sibling.rank >= rank:
                sibling.rank += 1
        at = rank
    item = WeeklyLineupItem(
        workspace_id=ws,
        lineup_id=lineup.id,
        candidate_id=candidate.id,
        rank=at,
        slot=slot,
        lane=lane_for(candidate),
        reason=reason_for(candidate, rank=at, slot=slot),
        status="planned",
        added_by=added_by,
    )
    db.add(item)
    lineup.revision += 1
    lineup.updated_by = added_by
    await db.flush()
    if at != len(siblings) + 1:
        await _renumber(db, ws, lineup.id)
    return item


async def remove_topic(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    candidate_id: uuid.UUID,
    *,
    removed_by: str | None = None,
) -> None:
    result = await db.execute(
        select(WeeklyLineupItem).where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup.id,
            WeeklyLineupItem.candidate_id == candidate_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return
    if item.status == "recorded":
        raise LineupError(
            "recorded",
            "that one is already recorded, so it stays in the week",
            status=409,
        )
    await db.delete(item)
    lineup.revision += 1
    lineup.updated_by = removed_by
    await db.flush()
    await _renumber(db, ws, lineup.id)


async def _live_candidate(
    db: AsyncSession, ws: uuid.UUID, candidate_id: Any
) -> TopicCandidate | None:
    """A topic that may be put (back) in a week: this workspace's, and neither
    rejected nor put away since."""
    try:
        cid = uuid.UUID(str(candidate_id))
    except (TypeError, ValueError):
        return None
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.id == cid,
            TopicCandidate.status.notin_(("rejected", "withdrawn")),
        )
    )
    return result.scalar_one_or_none()


async def apply_order(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    order: list[dict[str, Any]],
    *,
    create_missing: bool = False,
    added_by: str | None = None,
) -> None:
    """Set slot and rank for every named item. Unnamed items keep their place.

    Called by the change-set engine for `reorder_week` and by the direct reorder
    endpoint. It does not bump `revision`; the caller owns that, so one user
    action is one revision even when it moves three items.

    `create_missing` is for undo only: an order recorded before a topic was taken
    out names that topic, and putting the order back has to put the topic back
    too. Without it a named topic that is not in the week is skipped, which is
    what the direct reorder endpoint wants. A topic rejected or put away since is
    never brought back; the caller checks the result and says so.
    """
    items = {str(i.candidate_id): i for i in await list_items(db, ws, lineup.id)}
    for entry in order:
        if not isinstance(entry, dict):
            continue
        item = items.get(str(entry.get("candidate_id")))
        if item is None:
            if not create_missing:
                continue
            candidate = await _live_candidate(db, ws, entry.get("candidate_id"))
            if candidate is None:
                continue
            slot = entry.get("slot") if entry.get("slot") in LINEUP_SLOTS else "primary"
            rank = entry.get("rank")
            rank = rank if isinstance(rank, int) and rank > 0 else len(items) + 1
            item = WeeklyLineupItem(
                workspace_id=ws,
                lineup_id=lineup.id,
                candidate_id=candidate.id,
                rank=rank,
                slot=slot,
                lane=lane_for(candidate),
                reason=reason_for(candidate, rank=rank, slot=slot),
                status="planned",
                added_by=added_by,
            )
            db.add(item)
            items[str(candidate.id)] = item
            continue
        slot = entry.get("slot")
        if slot in LINEUP_SLOTS:
            item.slot = slot
        rank = entry.get("rank")
        if isinstance(rank, int) and rank > 0:
            item.rank = rank
    await db.flush()
    await _renumber(db, ws, lineup.id)


async def apply_move(
    db: AsyncSession, ws: uuid.UUID, lineup: WeeklyLineup, move: dict[str, Any]
) -> None:
    """One relative move: first / up / down / slot change / remove.

    Relative verbs exist because the phone has buttons, not a drag surface, and
    "Make first" has to mean the same thing whether the list has two items or
    seven.
    """
    if not isinstance(move, dict):
        return
    candidate_id = move.get("candidate_id")
    if not candidate_id:
        return
    items = await list_items(db, ws, lineup.id)
    target = next((i for i in items if str(i.candidate_id) == str(candidate_id)), None)
    if target is None:
        raise LineupError("not_in_week", "that topic is not in this week", status=404)

    action = move.get("action") or "rank"
    if action == "remove":
        await remove_topic(db, ws, lineup, target.candidate_id)
        return

    if action == "slot":
        slot = move.get("slot")
        if slot not in LINEUP_SLOTS:
            raise LineupError("bad_slot", f"unknown slot {slot}", status=400)
        if slot != target.slot:
            target.slot = slot
            target.rank = sum(1 for i in items if i.slot == slot) + 1
        await db.flush()
        await _renumber(db, ws, lineup.id)
        return

    siblings = sorted(
        (i for i in items if i.slot == target.slot), key=lambda i: i.rank
    )
    position = siblings.index(target)
    if action == "first":
        new_position = 0
    elif action == "up":
        new_position = max(0, position - 1)
    elif action == "down":
        new_position = min(len(siblings) - 1, position + 1)
    elif action == "rank":
        wanted = move.get("rank")
        if not isinstance(wanted, int):
            raise LineupError("bad_rank", "a position is required", status=400)
        new_position = max(0, min(len(siblings) - 1, wanted - 1))
    else:
        raise LineupError("bad_action", f"unknown move {action}", status=400)

    siblings.insert(new_position, siblings.pop(position))
    for index, item in enumerate(siblings, start=1):
        item.rank = index
    await db.flush()


async def move(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    move_spec: dict[str, Any],
    *,
    expected_revision: int | None = None,
    moved_by: str | None = None,
) -> WeeklyLineup:
    """Guarded single move: the endpoint path, with the conflict check."""
    _check_revision(lineup, expected_revision)
    await apply_move(db, ws, lineup, move_spec)
    lineup.revision += 1
    lineup.updated_by = moved_by
    await db.flush()
    return lineup


# ---------------------------------------------------------------------------
# The week follows the decision
# ---------------------------------------------------------------------------


async def follow_decision(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate: TopicCandidate,
    decision: TopicDecision | None,
    *,
    by: str | None = None,
) -> dict[str, Any]:
    """Keep this week's list in step with the topic's decision.

    Choosing a topic for this week and listing it are one act from his side, so
    un-choosing it (later, discuss, away, or back to undecided) takes it off the
    list as well; otherwise "saved for later" and "in this week" are both true at
    once. Where it stood is kept on the decision, so choosing it again this week
    (a restore, an undo) puts it back at that place rather than at the end.

    A recorded item stays: `remove_topic` refuses, and the caller's decision is
    refused with it, so nothing is half done.

    Returns {"placed": {slot, rank, revision} | None, "added": bool,
    "removed": {slot, rank} | None, "week_start": the week's date as text,
    "lineup_id": the list it changed or None}, so a caller that records the write
    can say later which week's list it touched.

    The week is read through `current_lineup`, so on the Monday a week turns over
    a topic still chosen from last week is found on the new list (and choosing it
    again is not an addition). A caller that changes the decision first should
    read the week before it does (the decide route does), or the topic it is
    taking off was never carried and its place is lost.
    """
    week_start = week_start_for(None)
    week_label = week_start.date().isoformat()
    now = decision.decision if decision is not None else None

    if now == "this_week":
        lineup = await current_lineup(db, ws)
        listed = {i.candidate_id for i in await list_items(db, ws, lineup.id)}
        place = dict((decision.week_place if decision is not None else None) or {})
        here = place.get("week_start") == week_label
        slot = place.get("slot") if here and place.get("slot") in LINEUP_SLOTS else "primary"
        rank = place.get("rank") if here and isinstance(place.get("rank"), int) else None
        item = await add_topic(db, ws, lineup, candidate, slot=slot, rank=rank, added_by=by)
        added = candidate.id not in listed
        if added and decision is not None:
            decision.week_place = None
            await db.flush()
        return {
            "placed": {"slot": item.slot, "rank": item.rank, "revision": lineup.revision},
            "added": added,
            "removed": None,
            "week_start": week_label,
            "lineup_id": str(lineup.id),
        }

    untouched = {
        "placed": None,
        "added": False,
        "removed": None,
        "week_start": week_label,
        "lineup_id": None,
    }
    lineup = await get_lineup(db, ws, week_start)
    if lineup is None:
        return untouched
    await carry_forward(db, ws, lineup)
    item = next(
        (i for i in await list_items(db, ws, lineup.id) if i.candidate_id == candidate.id),
        None,
    )
    if item is None:
        return untouched
    removed = {"slot": item.slot, "rank": item.rank}
    await remove_topic(db, ws, lineup, candidate.id, removed_by=by)
    if decision is not None:
        decision.week_place = {"week_start": week_label, **removed}
        await db.flush()
    return {**untouched, "removed": removed, "lineup_id": str(lineup.id)}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _item_to_json(
    item: WeeklyLineupItem,
    candidate: TopicCandidate | None,
    packet: RecordingPacket | None,
    *,
    filmed: bool = False,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": str(item.candidate_id),
        "packet_id": str(packet.id) if packet else None,
        "packet_version": packet.version if packet else None,
        "title": candidate.title if candidate else "(missing topic)",
        "big_idea": candidate.lesson if candidate else "",
        "rank": item.rank,
        "slot": item.slot,
        "lane": item.lane,
        "lane_label": LANE_LABELS.get(item.lane, item.lane),
        "reason": item.reason,
        "status": item.status,
        # The one thing the week has to be honest about: is there a script yet.
        "script_state": _script_state(packet),
        # A script asked for and not saved yet (status.packet_requests). With
        # "pending" it finishes by itself, so the card says when instead of
        # offering "Prepare the script" again (28-Sep-2026). Over a script he
        # already has, only a new one on its way (status.rewrite_request).
        "script_request": request,
        # Filmed already (`filmed_candidate_ids`). It stays in its week, so the
        # week shows what he did, and nothing offers to record it again.
        "filmed": filmed,
    }


def _script_state(packet: RecordingPacket | None) -> str:
    if packet is None:
        return "none"
    if packet.status in ("ready", "exported"):
        return "ready"
    return packet.status or "draft"


async def lineup_to_json(
    db: AsyncSession, ws: uuid.UUID, lineup: WeeklyLineup
) -> dict[str, Any]:
    items = await list_items(db, ws, lineup.id)
    candidate_ids = [i.candidate_id for i in items]
    candidates = await _candidates_by_id(db, ws, candidate_ids)
    packets = await _latest_packets(db, ws, candidate_ids)
    filmed = await filmed_candidate_ids(db, ws, candidate_ids)
    from tce.editorial import status as job_status

    requests = await job_status.packet_requests(db, ws, candidate_ids)

    rendered = [
        _item_to_json(
            item,
            candidates.get(item.candidate_id),
            packets.get(item.candidate_id),
            filmed=item.candidate_id in filmed,
            request=(
                requests.get(item.candidate_id)
                if item.candidate_id not in packets
                else job_status.rewrite_request(requests.get(item.candidate_id))
            ),
        )
        for item in items
    ]
    primary = [r for r in rendered if r["slot"] == "primary"]
    reserve = [r for r in rendered if r["slot"] == "reserve"]

    counts: dict[str, int] = {}
    for row in primary:
        counts[row["lane"]] = counts.get(row["lane"], 0) + 1
    mix = " · ".join(
        f"{count} {LANE_LABELS.get(lane, lane).lower()}" for lane, count in sorted(counts.items())
    )

    return {
        "lineup_id": str(lineup.id),
        "week_start": lineup.week_start.date().isoformat(),
        "status": lineup.status,
        "revision": lineup.revision,
        "primary_slots": lineup.primary_slots,
        # A good week: how many past his usual number. Shown, never refused.
        "over_by": max(0, len(primary) - lineup.primary_slots),
        "primary": primary,
        "reserve": reserve,
        # Information, not a rule. An unbalanced week is visible and allowed.
        "mix": mix,
        # Scripts waiting to be filmed: a filmed topic's script is used (28-Sep).
        "ready_count": sum(
            1 for r in primary if r["script_state"] == "ready" and not r["filmed"]
        ),
    }
