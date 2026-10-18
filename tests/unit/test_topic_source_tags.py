"""Every idea says where it came from: a Fathom call, code, AI news.

14-Oct, Ziv: "tce must be able to tell which idea is related to code or related to
ai news or related to fathom". The lane said "Build" or "Coaching" (coaching is
read off the audience, not off a call), and the provenance line under every card
was empty because it read `title` from citations that store `source_title`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tce.editorial.inbox import _provenance, _row_to_json
from tce.editorial.lineup import source_tags
from tce.models.editorial import TopicCandidate

NOW = datetime(2026, 10, 14, 12, 0, 0)

CALL = {"source_kind": "fathom_meeting", "source_title": "Impromptu Zoom Meeting"}
COMMIT = {"source_kind": "github_commit_group", "source_title": "kivimedia/boards: fix the board"}
NEWS = {"source_kind": "news_item", "source_title": "Skills arrive in Gemini"}
STANDING = {"source_kind": "standing_fact", "source_title": "Standing facts about the business"}
SPOKEN = {"source_kind": "spoken_idea", "source_title": "Coaching runs on a spectrum"}


def cand(cites, *, role="evergreen") -> TopicCandidate:
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
        status="proposed",
    )


def test_provenance_names_the_sources_it_cites():
    """Reproduction: before the fix this was "" for every selector idea."""
    assert _provenance(cand([CALL, COMMIT])) == (
        "From Impromptu Zoom Meeting and kivimedia/boards: fix the board"
    )


def test_provenance_never_names_the_standing_facts_list():
    assert _provenance(cand([NEWS, STANDING], role="news")) == "From Skills arrive in Gemini"


def test_a_call_idea_says_fathom_call():
    assert source_tags(cand([CALL])) == ["Fathom call"]


def code_cand(cites, **kw):
    c = cand(cites, **kw)
    c.title = "Ship the bug fix before the feature"
    return c


def test_a_code_idea_says_code():
    assert source_tags(code_cand([COMMIT])) == ["Code"]


def test_a_news_idea_says_ai_news_first_and_keeps_its_anchor():
    assert source_tags(code_cand([STANDING, COMMIT, NEWS], role="news")) == ["AI news", "Code"]


def test_a_mixed_idea_names_every_source_once():
    assert source_tags(code_cand([COMMIT, CALL, CALL])) == ["Fathom call", "Code"]


def test_a_spoken_idea_says_so():
    assert source_tags(cand([SPOKEN])) == ["Your idea"]


def test_the_card_carries_the_tags():
    row = _row_to_json(code_cand([CALL, COMMIT]), {}, None, 0)
    assert row["source_tags"] == ["Fathom call", "Code"]
