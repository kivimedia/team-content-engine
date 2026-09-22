"""The rules that decide whether a news idea reaches the recorder.

The one the whole lane rests on is tested twice on purpose: once as the hard
check, and once in the arithmetic, because a rule enforced in only one of those
places is a rule someone can relax without noticing.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tce.editorial.news_rules import (
    CODE_CEILING,
    CODE_FLOOR,
    CODE_MARGIN,
    DISPLACEMENT_MARGIN,
    FIRST_SLOT_FLOOR,
    SECOND_SLOT_FLOOR,
    STANDING_SUPPORT_CAP,
    anchor_support,
    apply_slot_rules,
    excluded_from_reserve,
    freshness_value,
    is_news_led,
    needs_anchor,
    score_news,
    should_convert_to_evergreen,
)

NOW = datetime(2026, 9, 22, 12, 0, 0)
PUBLISHED = datetime(2026, 9, 20, 12, 0, 0)
EXPIRES = datetime(2026, 9, 30, 12, 0, 0)


def cite(kind, claim="demonstrated", confidence="high"):
    return {"source_kind": kind, "claim_type": claim, "speaker_confidence": confidence}


NEWS = cite("news_item", "quoted")
COMMIT = cite("github_commit_group", "demonstrated")
CALL = cite("fathom_meeting", "paraphrased")
STANDING = cite("standing_fact", "demonstrated")


# ---------------------------------------------------------------------------
# The rule the lane rests on
# ---------------------------------------------------------------------------


def test_a_candidate_citing_only_the_announcement_is_rejected():
    assert needs_anchor([NEWS])
    assert needs_anchor([NEWS, NEWS])


@pytest.mark.parametrize("anchor", [COMMIT, CALL, STANDING])
def test_any_non_news_citation_satisfies_the_rule(anchor):
    assert not needs_anchor([NEWS, anchor])


def test_an_ordinary_candidate_is_untouched_by_the_rule():
    """Evergreen ideas never cite news and must not be caught by this."""
    assert not is_news_led([COMMIT, CALL])
    assert not needs_anchor([COMMIT, CALL])
    assert not needs_anchor([])


def test_the_arithmetic_agrees_with_the_hard_check():
    """Zero on the largest term, so the two enforcements cannot disagree."""
    assert anchor_support([NEWS]) == 0.0
    parts = score_news(
        citations=[NEWS],
        scores={"consequence_specificity": 5, "distinctiveness": 5, "owner_relevance": 5},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=NOW,
    )
    assert parts.anchor_support == 0.0
    assert parts.total < FIRST_SLOT_FLOOR, (
        "a candidate citing only the announcement cleared the floor with perfect "
        "scores everywhere else; the arithmetic is not carrying the rule"
    )


# ---------------------------------------------------------------------------
# Standing facts: possible, not comfortable
# ---------------------------------------------------------------------------


def test_a_standing_fact_supports_less_than_a_commit():
    assert anchor_support([NEWS, STANDING]) == STANDING_SUPPORT_CAP
    assert anchor_support([NEWS, COMMIT]) > anchor_support([NEWS, STANDING])


def test_standing_alone_needs_near_perfect_scores_to_publish():
    """Ziv's correction is honoured, and the easy path is still the honest one."""
    ordinary = score_news(
        citations=[NEWS, STANDING],
        scores={"consequence_specificity": 3, "distinctiveness": 3, "owner_relevance": 4},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=NOW,
    )
    assert ordinary.total < FIRST_SLOT_FLOOR, "ordinary scores on a standing fact got through"

    excellent = score_news(
        citations=[NEWS, STANDING],
        scores={"consequence_specificity": 5, "distinctiveness": 5, "owner_relevance": 5},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=NOW,
    )
    assert excellent.total >= FIRST_SLOT_FLOOR, (
        "a genuinely excellent idea anchored on a standing fact can never publish; "
        "the cap is a wall rather than a slope"
    )


def test_the_same_idea_on_a_commit_clears_comfortably():
    parts = score_news(
        citations=[NEWS, COMMIT],
        scores={"consequence_specificity": 4, "distinctiveness": 4, "owner_relevance": 4},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=NOW,
    )
    assert parts.total >= FIRST_SLOT_FLOOR


def test_low_speaker_confidence_reduces_support():
    assert anchor_support([NEWS, cite("fathom_meeting", "quoted", "low")]) < anchor_support(
        [NEWS, cite("fathom_meeting", "quoted", "high")]
    )


# ---------------------------------------------------------------------------
# Freshness decays, never spikes
# ---------------------------------------------------------------------------


def test_freshness_is_full_at_publication_and_gone_at_expiry():
    assert freshness_value(PUBLISHED, EXPIRES, now=PUBLISHED) == 1.0
    assert freshness_value(PUBLISHED, EXPIRES, now=EXPIRES) == 0.0


def test_freshness_decays_rather_than_rewarding_urgency():
    """A bonus near expiry would be the system inventing urgency."""
    early = freshness_value(PUBLISHED, EXPIRES, now=datetime(2026, 9, 21, 12, 0, 0))
    late = freshness_value(PUBLISHED, EXPIRES, now=datetime(2026, 9, 29, 12, 0, 0))
    assert early > late


def test_an_expired_item_scores_zero_freshness_not_negative():
    assert freshness_value(PUBLISHED, EXPIRES, now=datetime(2026, 10, 5)) == 0.0


def test_durable_has_no_freshness_and_becomes_evergreen():
    assert freshness_value(PUBLISHED, None, now=NOW) == 0.0
    assert should_convert_to_evergreen("durable")
    for other in ("hours", "days", "week", "month", None):
        assert not should_convert_to_evergreen(other)


def test_freshness_is_only_a_tenth_of_the_score():
    """His strategy file says freshness is a small bonus. He did not correct it."""
    fresh = score_news(
        citations=[NEWS, COMMIT],
        scores={"consequence_specificity": 3, "distinctiveness": 3, "owner_relevance": 3},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=PUBLISHED,
    )
    stale = score_news(
        citations=[NEWS, COMMIT],
        scores={"consequence_specificity": 3, "distinctiveness": 3, "owner_relevance": 3},
        published_at=PUBLISHED,
        expires_at=EXPIRES,
        now=EXPIRES,
    )
    assert abs(fresh.total - stale.total - 0.10) < 0.001


# ---------------------------------------------------------------------------
# The slot rules
# ---------------------------------------------------------------------------


class Cand:
    def __init__(self, name, news=False, score=0.9, weight="small"):
        self.name, self.news, self.score, self.weight = name, news, score, weight

    def __repr__(self):  # pragma: no cover - test output only
        return self.name


def run(ranked, **kw):
    return apply_slot_rules(
        ranked,
        is_news=lambda c: c.news,
        score_of=lambda c: c.score,
        story_weight_of=lambda c: c.weight,
        **kw,
    )


def test_one_news_idea_gets_through_and_the_rest_do_not():
    out = run(
        [
            Cand("evergreen1", score=0.60),
            Cand("news1", news=True, score=0.90),
            Cand("news2", news=True, score=0.85),
            Cand("news3", news=True, score=0.82),
        ]
    )
    assert [c.name for c in out.kept] == ["evergreen1", "news1"]
    assert {code for _c, code, _r in out.rejected} == {CODE_CEILING}


def test_a_second_news_idea_needs_to_be_major_and_clear_the_higher_floor():
    major_high = run(
        [
            Cand("evergreen1", score=0.50),
            Cand("news1", news=True, score=0.90, weight="major"),
            Cand("news2", news=True, score=0.85, weight="major"),
        ]
    )
    assert [c.name for c in major_high.kept] == ["evergreen1", "news1", "news2"]

    major_low = run(
        [
            Cand("evergreen1", score=0.50),
            Cand("news1", news=True, score=0.90, weight="major"),
            Cand("news2", news=True, score=0.79, weight="major"),
        ]
    )
    assert [c.name for c in major_low.kept] == ["evergreen1", "news1"]
    assert major_low.rejected[0][1] == CODE_FLOOR

    not_major = run(
        [
            Cand("evergreen1", score=0.50),
            Cand("news1", news=True, score=0.90, weight="major"),
            Cand("news2", news=True, score=0.88, weight="small"),
        ]
    )
    assert [c.name for c in not_major.kept] == ["evergreen1", "news1"]
    assert not_major.rejected[0][1] == CODE_CEILING


def test_a_news_idea_below_the_first_floor_never_enters():
    out = run([Cand("evergreen1", score=0.40), Cand("news1", news=True, score=0.69)])
    assert [c.name for c in out.kept] == ["evergreen1"]
    assert out.rejected[0][1] == CODE_FLOOR
    assert "0.70 floor" in out.rejected[0][2]


def test_a_near_tie_goes_to_his_own_work():
    """The anti-drift rule: it must BEAT his own material, not merely match it."""
    out = run(
        [
            Cand("evergreen1", score=0.88),
            Cand("news1", news=True, score=0.90),  # only 0.02 above
        ]
    )
    assert [c.name for c in out.kept] == ["evergreen1"]
    assert out.rejected[0][1] == CODE_MARGIN


def test_a_clear_win_does_displace():
    out = run(
        [
            Cand("evergreen1", score=0.80),
            Cand("news1", news=True, score=0.80 + DISPLACEMENT_MARGIN + 0.01),
        ]
    )
    assert "news1" in [c.name for c in out.kept]


def test_the_margin_compares_against_the_weakest_of_his_own_ideas():
    out = run(
        [
            Cand("strong", score=0.95),
            Cand("weak", score=0.60),
            Cand("news1", news=True, score=0.72),
        ]
    )
    assert "news1" in [c.name for c in out.kept], (
        "the margin was measured against the strongest evergreen idea instead of "
        "the one it would actually replace"
    )


def test_a_week_with_no_evergreen_ideas_still_applies_the_floor():
    out = run([Cand("news1", news=True, score=0.69)])
    assert out.kept == []
    assert out.rejected[0][1] == CODE_FLOOR

    out = run([Cand("news1", news=True, score=0.71)])
    assert [c.name for c in out.kept] == ["news1"]


def test_an_explicit_override_lifts_the_ceiling_for_that_week_only():
    out = run(
        [
            Cand("news1", news=True, score=0.90),
            Cand("news2", news=True, score=0.85),
            Cand("news3", news=True, score=0.84),
        ],
        ceiling_override=3,
    )
    assert len(out.kept) == 3


def test_zero_news_is_a_normal_week():
    out = run([Cand("a", score=0.9), Cand("b", score=0.8)])
    assert len(out.kept) == 2
    assert out.rejected == []


def test_every_rejection_says_why_in_words():
    out = run(
        [
            Cand("evergreen1", score=0.88),
            Cand("news1", news=True, score=0.90),
            Cand("news2", news=True, score=0.50),
        ]
    )
    for _candidate, code, reason in out.rejected:
        assert code and reason
        assert len(reason) > 20, "a rejection reason too short to act on"


# ---------------------------------------------------------------------------
# The reserve
# ---------------------------------------------------------------------------


def test_news_and_standing_facts_never_enter_the_evergreen_reserve():
    """A news card resurfacing weeks later through 'more ideas' is a defect."""
    assert excluded_from_reserve("news_item")
    assert excluded_from_reserve("standing_fact")
    assert not excluded_from_reserve("fathom_meeting")
    assert not excluded_from_reserve("github_commit_group")


def test_the_floors_are_ordered_as_documented():
    assert SECOND_SLOT_FLOOR > FIRST_SLOT_FLOOR
    assert 0 < DISPLACEMENT_MARGIN < 0.5


def test_an_override_lifts_the_ceiling_but_not_the_floor_or_the_margin():
    """Asking for more news is not asking for weaker news."""
    weak = run(
        [
            Cand("evergreen1", score=0.40),
            Cand("news1", news=True, score=0.90),
            Cand("news2", news=True, score=0.60),  # below the 0.80 second floor
        ],
        ceiling_override=3,
    )
    assert [c.name for c in weak.kept] == ["evergreen1", "news1"]
    assert weak.rejected[0][1] == CODE_FLOOR

    crowding = run(
        [
            Cand("evergreen1", score=0.88),
            Cand("news1", news=True, score=0.89),  # inside the margin
        ],
        ceiling_override=3,
    )
    assert [c.name for c in crowding.kept] == ["evergreen1"]
    assert crowding.rejected[0][1] == CODE_MARGIN
