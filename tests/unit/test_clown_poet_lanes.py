"""Chris Gamble's lane profile, `clown_poet` (05-Nov-2026).

Three lanes, the pillars he named on his 05-Nov call: parent_artist (prompts he answers
from his own life as a single parent and an artist), creative_life (creativity and play
in the news) and typewriter_poetry (a real page on typewriters or poem forms; he writes
his own poem). Matan's, Connie's, Brant's and Tim's behavior is unchanged (their own
suites). Synthetic data.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from tce.editorial import idea_lane, lane_packets, lane_profile, lineup
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
BRANT = uuid.UUID("3844285d-f119-47e9-98e4-5691f0cbdb4b")
TIM = uuid.UUID("34944494-e003-4852-bc69-de7607bcbdb0")
CHRIS = uuid.UUID("f34e9762-6b7f-4399-afcf-b674db1e28f5")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(
        settings,
        "workspace_lane_profiles",
        f"{MATAN}:performer,{BRANT}:fire_performer,{TIM}:florist_coach,{CHRIS}:clown_poet",
        raising=False,
    )
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)


def _seed():
    spec = importlib.util.spec_from_file_location("seed_chris_lanes", ROOT / "scripts" / "seed_chris_lanes.py")
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


PARENT_SCRIPT = [
    "Every parent who makes things asks me the same thing.",
    "When do you actually find the time?",
    "What does a show day look like with the kids at home?",
    "Who helps, and who never knows?",
    "[your story here]",
    "The time is not found.",
    "It is made, one small piece at a time.",
]

POEM_SCRIPT = [
    "A hundred years ago, a typist was called a typewriter.",
    "The person and the machine had the same name.",
    "That bench over there has no name at all.",
    "So I am going to write it a poem.",
    "[your poem here]",
    "A machine can write a poem.",
    "Only a person can write one for this bench, today.",
]


def test_chris_gets_clown_poet_and_the_others_keep_theirs(lanes):
    assert lane_profile.profile_for(CHRIS).name == "clown_poet"
    assert lane_profile.profile_for(CHRIS).lane_keys == ["parent_artist", "creative_life", "typewriter_poetry"]
    assert lane_profile.profile_for(TIM).name == "florist_coach"
    assert lane_profile.profile_for(BRANT).name == "fire_performer"
    assert lane_profile.profile_for(MATAN).name == "performer"


def test_lane_keys_stay_unique_across_profiles():
    keys = [k for p in lane_profile.PROFILES.values() for k in p.lane_keys]
    assert len(keys) == len(set(keys))
    assert lane_profile.profile_for_lane("typewriter_poetry").name == "clown_poet"


def test_his_lanes_are_his_pillars_with_a_writer_rule_each():
    for lane in lane_profile.CLOWN_POET.lanes:
        assert lane.key in lane_packets._LANE_RULES
        assert lineup.LANE_LABELS[lane.key] == lane.label
    assert [lane.label for lane in lane_profile.CLOWN_POET.lanes] == [
        "Parent as an Artist", "Living a Creative Life", "Typewriter Poetry",
    ]
    kinds = {lane.key: lane.source_kind for lane in lane_profile.CLOWN_POET.lanes}
    assert kinds == {"parent_artist": "story_seed", "creative_life": "news_item",
                     "typewriter_poetry": "curated_clip"}


def test_a_parent_prompt_never_narrates_his_memory():
    raw = {"lane": "parent_artist", "title": "I remember the day my kid saw my show", "lesson": "x",
           "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.CLOWN_POET, raw, ["story_seed"])
    assert hit is not None and hit[:2] == ("no_invented_memory", "invented_memory")


def test_a_lane_idea_cites_its_own_lane_evidence():
    raw = {"lane": "typewriter_poetry", "title": "The haiku", "lesson": "x", "public_angle": "y"}
    assert lane_profile.lane_check(lane_profile.CLOWN_POET, raw, ["curated_clip"]) is None
    hit = lane_profile.lane_check(lane_profile.CLOWN_POET, raw, ["news_item"])
    assert hit is not None and hit[1] == "lane_evidence"


def test_parent_script_needs_his_story_slot():
    ok = _clean(PARENT_SCRIPT, "What does a show day look like with the kids at home?")
    assert lane_packets.lane_errors(ok, "parent_artist") == []
    no_slot = _clean(
        [p if p != "[your story here]" else "Every family is different." for p in PARENT_SCRIPT],
        "What does a show day look like with the kids at home?",
    )
    errors = lane_packets.lane_errors(no_slot, "parent_artist")
    assert "a parent_artist script has exactly one line [your story here] where his own story goes" in errors


def test_his_poem_is_never_written_for_him():
    ok = _clean(POEM_SCRIPT)
    assert lane_packets.lane_errors(ok, "typewriter_poetry") == []
    written = _clean([p if p != "[your poem here]" else "Oh bench, you hold the tired." for p in POEM_SCRIPT])
    errors = lane_packets.lane_errors(written, "typewriter_poetry")
    assert any("[your poem here] where his own poem goes" in e for e in errors)
    twice = _clean([*POEM_SCRIPT, "[your poem here]"])
    assert any("exactly one line [your poem here]" in e for e in lane_packets.lane_errors(twice, "typewriter_poetry"))


def test_other_lanes_need_no_poem_slot():
    news = _clean(["A town painted its crosswalks with kids' drawings.", "Nobody asked them to be good.",
                   "They were asked to play.", "That is the whole lesson.", "Play first.", "Good comes later."])
    assert lane_packets.lane_errors(news, "creative_life") == []


def test_money_stays_out_of_his_scripts():
    assert lane_profile.CLOWN_POET.code_checks == frozenset({"money"})
    priced = _clean([*POEM_SCRIPT[:-1], "A poem like this costs 20 dollars, $20."])
    assert any(e.startswith("mentions money") for e in lane_packets.lane_errors(priced, "typewriter_poetry"))


def test_writer_prompt_is_his_for_his_lanes():
    his = lane_packets.system_prompt("typewriter_poetry", None)
    assert "a clown and typewriter poet" in his and "THIS IDEA'S LANE: typewriter_poetry" in his
    assert "Never write a poem for him" in his
    assert "Fire Guy" not in his and "flower shop" not in his and "Israeli" not in his


def test_chris_asks_research_by_his_lanes(lanes):
    assert idea_lane.kinds_for(CHRIS) == ("any", "parent_artist", "creative_life", "typewriter_poetry")
    assert idea_lane.resolve_kind(CHRIS, "news") == "creative_life"
    assert idea_lane.resolve_kind(TIM, "news") == "smart_ideas"
    assert idea_lane.KIND_SOURCES["parent_artist"] == ("story_seed",)
    assert idea_lane.KIND_SOURCES["typewriter_poetry"] == ("curated_clip",)


def test_his_topics_tabs_are_his_lanes(lanes):
    from tce.editorial import inbox

    keys, labels = inbox.filters_for(CHRIS, owner=False)
    assert keys == ("best", "parent_artist", "creative_life", "typewriter_poetry", "later", "away")
    assert [labels[k] for k in keys[1:4]] == [
        "Parent as an Artist", "Living a Creative Life", "Typewriter Poetry",
    ]


def _idea(kind: str, **kw):
    from types import SimpleNamespace

    base = dict(
        workspace_id=CHRIS, title="t", audience="both", lesson="l", public_angle="a",
        freshness_role="evergreen", citations_private=[{"source_kind": kind}],
        reasons_to_care=[], public_safety_notes="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_his_lane_ideas_reach_topics(lanes):
    from tce.editorial import briefs

    page = briefs.seed_brief(_idea("curated_clip"))
    assert page["why_this_is_yours"] == "It came out of the craft of your typewriter poems."
    assert briefs.is_inbox_eligible(page)
    seed = briefs.seed_brief(_idea("story_seed"))
    assert seed["why_this_is_yours"] == "It came out of a question about your own life as a parent and an artist."
    assert briefs.is_inbox_eligible(seed)


def test_his_news_card_names_his_creative_life(lanes):
    from tce.editorial import briefs

    news = _idea("news_item", freshness_role="news", citations_private=[
        {"source_kind": "news_item", "source_title": "Town paints crosswalks with kids' drawings"},
        {"source_kind": "standing_fact"},
    ])
    assert briefs.seed_brief(news)["why_this_is_yours"] == (
        "Town paints crosswalks with kids' drawings touches your own creative life."
    )


def test_his_briefs_name_his_audience(lanes):
    from tce.editorial import briefs

    for code in ("both", "event_owners", "coaches"):
        assert briefs.seed_brief(_idea("curated_clip", audience=code))["audience"] == (
            "People who want more creativity and play in their lives, and the people who book live acts"
        )


def test_his_week_line_keeps_his_pillar_names(lanes):
    counts = {"typewriter_poetry": 2, "parent_artist": 1}
    line = lineup.lane_mix(CHRIS, counts)
    assert "Parent as an Artist" in line and "Typewriter Poetry" in line


def test_his_news_has_his_own_editor(lanes):
    from tce.news import appraise
    from tce.news.appraise import AppraisalInput

    data = AppraisalInput(
        title="Hobby artists open a pop-up gallery", publisher="Example",
        published_at=None, primary_url="https://example.com/a", document="text",
        anchors=[{"kind": "client_solution", "term": "hobby artists"}], recent_evidence=[],
    )
    req = appraise.build_request(data, workspace_id=CHRIS, news_item_id=uuid.uuid4())
    assert req.system.startswith("You are Chris Gamble's editor")
    assert req.prompt_version == f"{appraise.PROMPT_VERSION}.clown_poet"


def _anchor_kinds() -> dict[str, str]:
    text = (ROOT / "docs" / "news-anchors-clown-poet.md").read_text(encoding="utf-8")
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


def test_no_bare_broad_word_is_an_anchor():
    kinds = _anchor_kinds()
    strong = {t for t, k in kinds.items() if k == "client_solution"}
    assert not strong & {"art", "arts", "artist", "artists", "festival", "creative", "poetry", "clown"}
    assert not set(kinds) & {"play", "kids", "children", "parents", "mental health", "money"}


def _anchors() -> list:
    from types import SimpleNamespace

    return [SimpleNamespace(kind=kind, term=term, id=None, weight=1.0) for term, kind in _anchor_kinds().items()]


@pytest.mark.parametrize("headline", [
    # 05-Nov feed probe: the kinds of items his lane is for.
    "OU med students turn pottery hobby into art therapy for hospitalized children",
    "Self-taught artist brings the old masters to life in new exhibition",
    "You can watch artists race against the clock at a live painting competition in Alberta",
    "Clowns on Ice ring in circus festival",
    "Typewriter poet writes verses for strangers at the farmers market",
])
def test_creativity_and_play_stories_are_his_news(headline):
    from tce.news import matcher

    assert matcher.match_item(title=headline, anchors=_anchors()).matched


@pytest.mark.parametrize("headline", [
    "Study projects up to $5.8 billion in yearly gains from rail merger",
    "Wall Street's rising stars say these skills matter more than ever",
    "Kids play in the snow as schools close for the day",
    "Parents push back on new school start times",
])
def test_business_school_and_sports_stay_out(headline):
    from tce.news import matcher

    assert not matcher.match_item(title=headline, anchors=_anchors()).matched


def test_his_bing_feeds_are_date_ordered():
    seed = _seed()
    bing = [url for _name, url, *_rest in seed.FEEDS if "bing.com" in url]
    assert bing and all("sortbydate" in url for url in bing)
    assert len({url for _name, url, *_rest in seed.FEEDS}) == len(seed.FEEDS)


def test_chris_seed_validates():
    seed = _seed()
    seed.validate_all()
    items = seed.lane_items()
    assert {i.kind for i in items} == {"curated_clip", "story_seed"}
    clips = [i for i in items if i.kind == "curated_clip"]
    assert len(clips) >= 25
    assert all(i.url.startswith("https://en.wikipedia.org/wiki/") for i in clips)
    assert all(i.lesson.rstrip().endswith("?") for i in items if i.kind == "story_seed")
    assert len({i.key for i in items}) == len(items)
    assert seed.TIMEZONE == "America/Edmonton"


def test_nothing_private_or_dashed_in_his_seed():
    seed = _seed()
    text = " ".join(f"{t} {lesson}" for _k, t, _u, lesson in seed.PAGES)
    text += " ".join(q for _k, q in seed.STORY_SEEDS)
    text += seed.STRATEGY_MD + " ".join(lesson for _k, _t, lesson in seed.STANDING_FACTS)
    sql = (ROOT / "scripts" / "seed_chris_profiles.sql").read_text(encoding="utf-8")
    # His profile rows, not the file's own comment lines (which name the call).
    profiles = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    for blob in (text, profiles):
        low = blob.lower()
        for word in ("arbitration", "lawyer", "retainer", "custody", "divorce", "court", " ex ", "ex-wife",
                     "ex-partner", "ziv", "angel"):
            assert word not in low, word
        assert "—" not in blob and "–" not in blob
    assert "--" not in text.replace("<!-- tce-strategy: replace -->", "")
    # No page about death or grief in a lane he films on a happy walk.
    assert not any(k in {"elegy", "epitaph"} for k, *_ in seed.PAGES)
