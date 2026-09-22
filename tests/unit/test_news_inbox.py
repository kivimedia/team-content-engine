"""What a news idea looks like when it reaches Ziv's topic list."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from tce.editorial.briefs import _why_this_is_yours, is_inbox_eligible, seed_brief
from tce.editorial.inbox import freshness_note_for
from tce.editorial.lineup import LANE_LABELS, lane_for
from tce.models.editorial import TopicCandidate

NOW = datetime(2026, 9, 22, 12, 0, 0)  # a Tuesday


def cand(cites, *, role="news", expires=None, **kw) -> TopicCandidate:
    return TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        week_start=NOW,
        moment_ids=[],
        title="An idea",
        lesson="A lesson",
        audience="both",
        reasons_to_care=[],
        public_angle="An angle",
        gates={},
        freshness_role=role,
        citations_private=cites,
        expires_at=expires,
        **kw,
    )


NEWS = {"source_kind": "news_item", "source_title": "WhatsApp pricing change"}
STANDING = {"source_kind": "standing_fact"}
COMMIT = {"source_kind": "github_commit_group"}


# --- the invisible-card bug ---------------------------------------------------


def test_a_news_idea_on_a_standing_fact_is_not_invisible():
    """Reproduction: before the fix this sentence was empty, and an empty sentence
    kept the idea out of the inbox entirely - it passed every gate and was never
    shown. This is the route Ziv's 21-Sep correction opened, so losing it silently
    would have undone the correction in exactly the place he would look."""
    idea = cand([NEWS, STANDING])
    assert _why_this_is_yours(idea), "a standing-fact news idea produced no reason"
    assert is_inbox_eligible(seed_brief(idea))


def test_the_why_line_leads_with_his_work_and_names_what_changed():
    line = _why_this_is_yours(cand([NEWS, COMMIT]))
    assert line.startswith("WhatsApp pricing change touches")
    assert "something you built" in line


def test_an_evergreen_why_line_is_unchanged():
    line = _why_this_is_yours(cand([COMMIT], role="evergreen"))
    assert line == "It came out of something you built."


def test_news_citing_nothing_of_his_still_has_no_reason():
    """The selector already rejects this; the inbox must not rescue it."""
    assert _why_this_is_yours(cand([NEWS])) == ""


# --- the expiry note ----------------------------------------------------------


def test_the_note_is_a_date_not_a_countdown():
    note = freshness_note_for(cand([NEWS], expires=NOW + timedelta(days=4)), now=NOW)
    assert note == "Worth saying until Saturday 26 September"


def test_inside_two_days_it_says_record_this_one_first():
    note = freshness_note_for(cand([NEWS], expires=NOW + timedelta(hours=30)), now=NOW)
    assert note.endswith("· record this one first")


def test_an_expired_idea_says_it_went_stale():
    note = freshness_note_for(cand([NEWS], expires=NOW - timedelta(days=1)), now=NOW)
    assert note.startswith("Went stale on Monday 21 September")


def test_a_legacy_news_flag_without_expiry_stays_plain():
    assert freshness_note_for(cand([NEWS], expires=None), now=NOW) == "Timely"


def test_evergreen_ideas_carry_no_note():
    assert freshness_note_for(cand([COMMIT], role="evergreen"), now=NOW) == ""


def test_no_leading_zero_in_the_day():
    note = freshness_note_for(
        cand([NEWS], expires=datetime(2026, 10, 3, 12, 0)), now=NOW
    )
    assert "3 October" in note and "03" not in note


# --- the lane name ------------------------------------------------------------


def test_the_lane_carries_ziv_s_own_name():
    assert lane_for(cand([NEWS, COMMIT])) == "ai_news"
    assert LANE_LABELS["ai_news"] == "News that excites Ziv"
