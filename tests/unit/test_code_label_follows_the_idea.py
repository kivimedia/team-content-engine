"""A coaching lesson mined from a commit is not a Code topic (T-13812).

18-Oct, Ziv saw a topic labelled Code that had nothing to do with code. Eleven live
Code topics were coaching lessons the engine wrote after reading a commit, so the
cited commit group said where the idea began, not what it is about.
"""

from __future__ import annotations

from types import SimpleNamespace

from tce.editorial.inbox import CATEGORY_FILTERS, _matches
from tce.editorial.lineup import is_code_topic, lane_for, source_tags
from tests.unit.test_topic_source_tags import CALL, COMMIT, cand


def coaching(cites):
    c = cand(cites)
    c.title = "A no and a not now need different follow-up"
    c.lesson = "Tell the lead which one you heard and when you will ask again."
    c.public_angle = "Follow-up is a promise."
    return c


def codey(cites):
    c = cand(cites)
    c.title = "Ship the bug fix before the new feature"
    return c


def decided(value):
    return SimpleNamespace(decision=value)


def test_a_coaching_lesson_from_a_commit_is_not_code():
    c = coaching([COMMIT])
    assert not is_code_topic(c)
    assert "Code" not in source_tags(c)
    assert lane_for(c) == "coaching"
    assert not _matches("code", c, None)


def test_a_build_idea_from_a_commit_is_still_code():
    c = cand([COMMIT])
    c.title = "Ship the bug fix before the new feature"
    assert is_code_topic(c)
    assert source_tags(c) == ["Code"]
    assert lane_for(c) == "build"
    assert _matches("code", c, None)


def test_calls_still_follow_the_cited_call():
    assert _matches("calls", coaching([CALL, COMMIT]), None)


def test_category_chips_include_topics_already_in_the_week():
    for key in CATEGORY_FILTERS:
        assert key in ("calls", "code", "news")
    assert _matches("calls", cand([CALL]), decided("this_week"))
    assert _matches("code", codey([COMMIT]), decided("this_week"))
    assert _matches("news", cand([CALL], role="news"), decided("this_week"))


def test_put_away_and_later_stay_out_of_the_category_chips():
    assert not _matches("code", codey([COMMIT]), decided("away"))
    assert not _matches("calls", cand([CALL]), decided("later"))


def test_best_and_evergreen_still_exclude_the_week():
    assert not _matches("best", cand([CALL]), decided("this_week"))
    assert not _matches("evergreen", cand([CALL]), decided("this_week"))
