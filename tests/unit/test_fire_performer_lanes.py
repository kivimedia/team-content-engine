"""Brant Matthews's lane profile, `fire_performer` (28-Oct-2026).

Three lanes he chose on his 21-Oct call: sacred_flame (the history of fire, its myths
and rituals), keeper_of_flame (prompts he answers from his own 30 years of
performing), taming_fire (records, stunts and danger mastery in the news). Matan's
and Connie's behavior is unchanged (their own suites). Synthetic data.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from tce.editorial import idea_lane, lane_packets, lane_profile, lineup
from tce.news import feeds
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
CONNIE = uuid.UUID("7247b8fa-d627-4357-b6e8-ca2a26cd4b14")
BRANT = uuid.UUID("3844285d-f119-47e9-98e4-5691f0cbdb4b")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(
        settings,
        "workspace_lane_profiles",
        f"{MATAN}:performer,{CONNIE}:sales_coach,{BRANT}:fire_performer",
        raising=False,
    )
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)


def _seed():
    spec = importlib.util.spec_from_file_location("seed_brant_lanes", ROOT / "scripts" / "seed_brant_lanes.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    return seed


def _clean(phrases: list[str], interviewer: str = "What would you say next?") -> dict:
    return {
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": phrases,
        "facebook_post": " ".join(phrases),
        "interviewer_prompt": interviewer,
        "hook_options": [{"id": f"h{i}", "text": phrases[0]} for i in range(1, 4)],
    }


KEEPER_SCRIPT = [
    "Every fire performer has a ritual before the torches light.",
    "What happens in your last five minutes before a show?",
    "Who is around you, and what do you check?",
    "[your story here]",
    "Why does that ritual still matter after all these years?",
    "The ritual is how the fire knows you are ready.",
]

TAMING_SCRIPT = [
    "A man just walked a high wire over a canyon.",
    "No net, and the wind never stopped.",
    "People call that fearless.",
    "[your story here]",
    "Fearless is the wrong word.",
    "Control is the right one.",
]


def test_brant_gets_fire_performer_and_the_others_keep_theirs(lanes):
    assert lane_profile.profile_for(BRANT).name == "fire_performer"
    assert lane_profile.profile_for(BRANT).lane_keys == ["sacred_flame", "keeper_of_flame", "taming_fire"]
    assert lane_profile.profile_for(CONNIE).name == "sales_coach"
    assert lane_profile.profile_for(MATAN).name == "performer"


def test_lane_keys_stay_unique_across_profiles():
    keys = [k for p in lane_profile.PROFILES.values() for k in p.lane_keys]
    assert len(keys) == len(set(keys))
    assert lane_profile.profile_for_lane("taming_fire").name == "fire_performer"


def test_every_fire_performer_lane_has_a_writer_rule_and_his_pillar_name():
    for lane in lane_profile.FIRE_PERFORMER.lanes:
        assert lane.key in lane_packets._LANE_RULES
        assert lineup.LANE_LABELS[lane.key] == lane.label
    assert [lane.label for lane in lane_profile.FIRE_PERFORMER.lanes] == [
        "The Sacred Flame", "Keeper of the Flame", "Taming the Fire",
    ]


def test_keeper_prompt_never_narrates_his_memory():
    raw = {"lane": "keeper_of_flame", "title": "I remember my first fire show", "lesson": "x", "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.FIRE_PERFORMER, raw, ["story_seed"])
    assert hit is not None and hit[:2] == ("no_invented_memory", "invented_memory")


def test_a_lane_idea_cites_its_own_lane_evidence():
    raw = {"lane": "sacred_flame", "title": "Prometheus", "lesson": "x", "public_angle": "y"}
    assert lane_profile.lane_check(lane_profile.FIRE_PERFORMER, raw, ["curated_clip"]) is None
    hit = lane_profile.lane_check(lane_profile.FIRE_PERFORMER, raw, ["news_item"])
    assert hit is not None and hit[1] == "lane_evidence"


def test_keeper_script_needs_his_english_slot_and_refuses_a_told_memory():
    ok = _clean(KEEPER_SCRIPT, "What do you do in the last minutes before a show?")
    assert lane_packets.lane_errors(ok, "keeper_of_flame") == []
    no_slot = _clean(
        [p if p != "[your story here]" else "It is different for everyone." for p in KEEPER_SCRIPT],
        "What do you do in the last minutes before a show?",
    )
    errors = lane_packets.lane_errors(no_slot, "keeper_of_flame")
    assert "a keeper_of_flame script has exactly one line [your story here] where his own story goes" in errors
    told = _clean([*KEEPER_SCRIPT[:-1], "I remember the night the wind turned."], "What happened?")
    assert any("narrates an event as his" in e for e in lane_packets.lane_errors(told, "keeper_of_flame"))


def test_taming_script_may_leave_his_record_day_to_him_and_never_talks_money():
    assert lane_packets.lane_errors(_clean(TAMING_SCRIPT), "taming_fire") == []
    paid = _clean([*TAMING_SCRIPT[:-1], "He got a fee of a million for it."])
    assert any(e.startswith("mentions money") for e in lane_packets.lane_errors(paid, "taming_fire"))


def test_writer_prompt_is_his_for_his_lanes():
    his = lane_packets.system_prompt("taming_fire", None)
    assert "the Fire Guy" in his and "THIS IDEA'S LANE: taming_fire" in his
    assert "Never teach how to do a fire or danger stunt" in his
    assert "Israeli" not in his and "She films herself" not in his


def test_brant_asks_research_by_his_lanes(lanes):
    assert idea_lane.kinds_for(BRANT) == ("any", "taming_fire", "sacred_flame", "keeper_of_flame")
    assert idea_lane.resolve_kind(BRANT, "news") == "taming_fire"
    assert idea_lane.resolve_kind(CONNIE, "news") == "in_the_wild"
    assert idea_lane.KIND_SOURCES["sacred_flame"] == ("curated_clip",)
    assert idea_lane.KIND_SOURCES["keeper_of_flame"] == ("story_seed",)


def test_his_topics_tabs_are_his_pillars(lanes):
    from tce.editorial import inbox

    keys, labels = inbox.filters_for(BRANT, owner=False)
    assert keys == ("best", "sacred_flame", "keeper_of_flame", "taming_fire", "later", "away")
    assert [labels[k] for k in keys[1:4]] == ["The Sacred Flame", "Keeper of the Flame", "Taming the Fire"]


def test_his_lane_ideas_reach_topics(lanes):
    from types import SimpleNamespace

    from tce.editorial import briefs

    def idea(kind):
        return SimpleNamespace(
            workspace_id=BRANT, title="t", audience="both", lesson="l", public_angle="a",
            freshness_role="evergreen", citations_private=[{"source_kind": kind}],
            reasons_to_care=[], public_safety_notes="",
        )

    history = briefs.seed_brief(idea("curated_clip"))
    assert history["why_this_is_yours"] == "It came out of the history of the fire you perform with."
    assert briefs.is_inbox_eligible(history)
    keeper = briefs.seed_brief(idea("story_seed"))
    assert keeper["why_this_is_yours"] == "It came out of a question about your own 30 years with fire."


def test_his_news_has_his_own_editor(lanes):
    from tce.news import appraise
    from tce.news.appraise import AppraisalInput

    data = AppraisalInput(
        title="Daredevil sets a world record on a high wire", publisher="Example",
        published_at=None, primary_url="https://example.com/a", document="text",
        anchors=[{"kind": "client_solution", "term": "high wire"}], recent_evidence=[],
    )
    req = appraise.build_request(data, workspace_id=BRANT, news_item_id=uuid.uuid4())
    assert req.system.startswith("You are Brant Matthews's editor")
    assert req.prompt_version == f"{appraise.PROMPT_VERSION}.fire_performer"


def _anchor_kinds() -> dict[str, str]:
    text = (ROOT / "docs" / "news-anchors-fire-performer.md").read_text(encoding="utf-8")
    kinds: dict[str, str] = {}
    kind = None
    for line in text.splitlines():
        if line.startswith("## "):
            kind = line[3:].strip()
        elif line.startswith("- ") and kind:
            kinds[line[2:].strip()] = kind
    return kinds


def test_every_anchor_is_citable_with_the_same_kind():
    facts = {term: k for k, term, _lesson in _seed().STANDING_FACTS}
    kinds = _anchor_kinds()
    assert kinds and set(kinds) <= set(facts)
    assert all(facts[term] == kind for term, kind in kinds.items())


def test_no_bare_fire_or_record_anchor():
    # "wildfire", "house fire", "record heat" and "record jackpot" are never his lane.
    assert not set(_anchor_kinds()) & {"fire", "fires", "flame", "record", "records", "talks"}


def test_brant_seed_validates():
    seed = _seed()
    seed.validate_all()
    items = seed.lane_items()
    assert {i.kind for i in items} == {"curated_clip", "story_seed"}
    assert all(i.url.startswith("https://en.wikipedia.org/wiki/") for i in items if i.kind == "curated_clip")
    assert all(i.lesson.rstrip().endswith("?") for i in items if i.kind == "story_seed")


BING_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Bing</title>
<item><title>Juggler sets a world record</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid={tid}&amp;url=https%3a%2f%2fwww.guinnessworldrecords.com%2fnews%2f2026%2f10%2fjuggler&amp;c=1</link>
<description>A record.</description></item></channel></rss>"""


def test_a_bing_news_link_is_the_article_and_stays_the_same_item():
    first = feeds.parse_atom_or_rss(BING_RSS.replace("{tid}", "aaa"))
    again = feeds.parse_atom_or_rss(BING_RSS.replace("{tid}", "bbb"))
    assert first[0].url == "https://www.guinnessworldrecords.com/news/2026/10/juggler"
    assert first[0].external_id == again[0].external_id == first[0].url


def test_other_links_pass_through_untouched():
    assert feeds.unwrap_click_tracker("https://example.com/a?url=https://b.com") == "https://example.com/a?url=https://b.com"
    assert feeds.unwrap_click_tracker("https://www.bing.com/news/apiclick.aspx?url=javascript:x") == (
        "https://www.bing.com/news/apiclick.aspx?url=javascript:x"
    )
