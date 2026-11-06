"""The demo workspace's lane profile, `wedding_coach` (06-Nov-2026).

A FICTIONAL creator, so product pictures and demo videos never show a real client's
workspace. Three lanes: dance_floor_stories (prompts she answers from her own memory),
wedding_news (weddings in the news) and party_craft (a real page on the craft of a party).
Every other profile's behavior is unchanged (their own suites). Synthetic data.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from tce.editorial import idea_lane, lane_packets, lane_profile, lineup
from tce.settings import settings

CHRIS = uuid.UUID("f34e9762-6b7f-4399-afcf-b674db1e28f5")
DEMO = uuid.UUID("6e9faea3-412b-4839-90e7-77b67f654808")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(
        settings,
        "workspace_lane_profiles",
        f"{CHRIS}:clown_poet,{DEMO}:wedding_coach",
        raising=False,
    )


def _seed():
    spec = importlib.util.spec_from_file_location("seed_demo_lanes", ROOT / "scripts" / "seed_demo_lanes.py")
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


STORY_SCRIPT = [
    "Every wedding DJ knows this feeling.",
    "The floor is empty and the couple is looking at you.",
    "Where were you standing?",
    "What did you say into the microphone?",
    "[your story here]",
    "An empty floor is information.",
    "It tells you what to play next.",
]


def test_the_demo_gets_wedding_coach_and_chris_keeps_his(lanes):
    assert lane_profile.profile_for(DEMO).name == "wedding_coach"
    assert lane_profile.profile_for(DEMO).lane_keys == ["dance_floor_stories", "wedding_news", "party_craft"]
    assert lane_profile.profile_for(CHRIS).name == "clown_poet"


def test_lane_keys_stay_unique_across_profiles():
    keys = [k for p in lane_profile.PROFILES.values() for k in p.lane_keys]
    assert len(keys) == len(set(keys))
    assert lane_profile.profile_for_lane("party_craft").name == "wedding_coach"


def test_her_lanes_have_a_writer_rule_each():
    for lane in lane_profile.WEDDING_COACH.lanes:
        assert lane.key in lane_packets._LANE_RULES
        assert lineup.LANE_LABELS[lane.key] == lane.label
    assert [lane.label for lane in lane_profile.WEDDING_COACH.lanes] == [
        "Stories from the Dance Floor", "Weddings in the News", "The Craft of a Great Party",
    ]
    kinds = {lane.key: lane.source_kind for lane in lane_profile.WEDDING_COACH.lanes}
    assert kinds == {"dance_floor_stories": "story_seed", "wedding_news": "news_item",
                     "party_craft": "curated_clip"}


def test_a_dance_floor_prompt_never_narrates_her_memory():
    raw = {"lane": "dance_floor_stories", "title": "I remember the night the sound went out",
           "lesson": "x", "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.WEDDING_COACH, raw, ["story_seed"])
    assert hit is not None and hit[:2] == ("no_invented_memory", "invented_memory")


def test_a_lane_idea_cites_its_own_lane_evidence():
    raw = {"lane": "party_craft", "title": "The first dance", "lesson": "x", "public_angle": "y"}
    assert lane_profile.lane_check(lane_profile.WEDDING_COACH, raw, ["curated_clip"]) is None
    hit = lane_profile.lane_check(lane_profile.WEDDING_COACH, raw, ["news_item"])
    assert hit is not None and hit[1] == "lane_evidence"


def test_her_story_script_needs_her_story_slot():
    ok = _clean(STORY_SCRIPT, "What did you say into the microphone?")
    assert lane_packets.lane_errors(ok, "dance_floor_stories") == []
    no_slot = _clean(
        [p if p != "[your story here]" else "Every room is different." for p in STORY_SCRIPT],
        "What did you say into the microphone?",
    )
    errors = lane_packets.lane_errors(no_slot, "dance_floor_stories")
    assert "a dance_floor_stories script has exactly one line [your story here] where her own story goes" in errors


def test_other_lanes_need_no_story_slot():
    craft = _clean(["A master of ceremonies introduces people.", "That is the whole job on paper.",
                    "In the room it is more than that.", "You are the one who moves people.",
                    "So say their names right.", "Then get out of the way."])
    assert lane_packets.lane_errors(craft, "party_craft") == []


def test_money_stays_out_of_her_scripts():
    assert lane_profile.WEDDING_COACH.code_checks == frozenset({"money"})
    priced = _clean([*STORY_SCRIPT[:-1], "A night like this costs 2000 dollars, $2000."])
    assert any(e.startswith("mentions money") for e in lane_packets.lane_errors(priced, "dance_floor_stories"))


def test_writer_prompt_is_hers_for_her_lanes():
    hers = lane_packets.system_prompt("party_craft", None)
    assert "a wedding emcee, DJ and coach" in hers and "THIS IDEA'S LANE: party_craft" in hers
    assert "Fire Guy" not in hers and "flower shop" not in hers and "typewriter" not in hers


def test_she_asks_research_by_her_lanes(lanes):
    assert idea_lane.kinds_for(DEMO) == ("any", "dance_floor_stories", "wedding_news", "party_craft")
    assert idea_lane.resolve_kind(DEMO, "news") == "wedding_news"
    assert idea_lane.resolve_kind(CHRIS, "news") == "creative_life"
    assert idea_lane.KIND_SOURCES["dance_floor_stories"] == ("story_seed",)
    assert idea_lane.KIND_SOURCES["party_craft"] == ("curated_clip",)


def test_her_topics_tabs_are_her_lanes(lanes):
    from tce.editorial import inbox

    keys, labels = inbox.filters_for(DEMO, owner=False)
    assert keys == ("best", "dance_floor_stories", "wedding_news", "party_craft", "later", "away")
    assert [labels[k] for k in keys[1:4]] == [
        "Stories from the Dance Floor", "Weddings in the News", "The Craft of a Great Party",
    ]


def _idea(kind: str, **kw):
    from types import SimpleNamespace

    base = dict(
        workspace_id=DEMO, title="t", audience="both", lesson="l", public_angle="a",
        freshness_role="evergreen", citations_private=[{"source_kind": kind}],
        reasons_to_care=[], public_safety_notes="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_her_lane_ideas_reach_topics(lanes):
    from tce.editorial import briefs

    page = briefs.seed_brief(_idea("curated_clip"))
    assert page["why_this_is_yours"] == "It came out of the craft you teach."
    assert briefs.is_inbox_eligible(page)
    seed = briefs.seed_brief(_idea("story_seed"))
    assert seed["why_this_is_yours"] == "It came out of a question about your own nights on the dance floor."
    assert briefs.is_inbox_eligible(seed)


def test_her_news_card_names_how_she_runs_a_wedding(lanes):
    from tce.editorial import briefs

    news = _idea("news_item", freshness_role="news", citations_private=[
        {"source_kind": "news_item", "source_title": "2027 wedding trends revealed"},
        {"source_kind": "standing_fact"},
    ])
    assert briefs.seed_brief(news)["why_this_is_yours"] == (
        "2027 wedding trends revealed touches the way you run a wedding."
    )


def test_her_briefs_name_her_audience(lanes):
    from tce.editorial import briefs

    for code in ("both", "event_owners", "coaches"):
        assert briefs.seed_brief(_idea("curated_clip", audience=code))["audience"] == (
            "Wedding DJs, emcees and bands, and the planners and couples who hire them"
        )


def test_her_week_line_keeps_her_lane_names(lanes):
    counts = {"party_craft": 2, "dance_floor_stories": 1}
    line = lineup.lane_mix(DEMO, counts)
    assert "Stories from the Dance Floor" in line and "The Craft of a Great Party" in line


def test_her_news_has_her_own_editor(lanes):
    from tce.news import appraise
    from tce.news.appraise import AppraisalInput

    data = AppraisalInput(
        title="Wedding planners say guests want smaller receptions", publisher="Example",
        published_at=None, primary_url="https://example.com/a", document="text",
        anchors=[{"kind": "client_solution", "term": "wedding planners"}], recent_evidence=[],
    )
    req = appraise.build_request(data, workspace_id=DEMO, news_item_id=uuid.uuid4())
    assert req.system.startswith("You are Nell Hartwick's editor")
    assert req.prompt_version == f"{appraise.PROMPT_VERSION}.wedding_coach"


def _anchor_kinds() -> dict[str, str]:
    text = (ROOT / "docs" / "news-anchors-wedding-coach.md").read_text(encoding="utf-8")
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
    assert not strong & {"wedding", "weddings", "dj", "playlist", "bride", "groom"}
    assert not set(kinds) & {"wedding reception", "bride", "brides", "groom", "grooms", "band", "money"}


def _anchors() -> list:
    from types import SimpleNamespace

    return [SimpleNamespace(kind=kind, term=term, id=None, weight=1.0) for term, kind in _anchor_kinds().items()]


@pytest.mark.parametrize("headline", [
    # 06-Nov feed probe: the kinds of items her lane is for.
    "2027 wedding trends revealed: From noughties nostalgia to the groom bouquet",
    "5 yacht rock songs that belong on every wedding playlist",
    "A colorful Austin micro wedding celebrates Jared and Shanice",
    "Wedding planners say couples want a shorter night",
    "Bride's heartfelt bouquet toss moves wedding guests",
    "The DJ who keeps every wedding on the dance floor",
])
def test_wedding_stories_are_her_news(headline):
    from tce.news import matcher

    assert matcher.match_item(title=headline, anchors=_anchors()).matched


@pytest.mark.parametrize("headline", [
    "The Sparkliest Jewelry to Wear and Gift This Holiday Season",
    "Really sad: DJs shoppers devastated over retail giant's collapse",
    "Patrick McKay sets The Rings of Power Season 3 release date",
    "Highway closure, increased traffic for Queenstown event",
])
def test_retail_and_tv_stay_out(headline):
    from tce.news import matcher

    assert not matcher.match_item(title=headline, anchors=_anchors()).matched


def test_her_bing_feeds_are_date_ordered():
    seed = _seed()
    bing = [url for _name, url, *_rest in seed.FEEDS if "bing.com" in url]
    assert bing and all("sortbydate" in url for url in bing)
    assert len({url for _name, url, *_rest in seed.FEEDS}) == len(seed.FEEDS)


def test_the_demo_seed_validates():
    seed = _seed()
    seed.validate_all()
    items = seed.lane_items()
    assert {i.kind for i in items} == {"curated_clip", "story_seed"}
    clips = [i for i in items if i.kind == "curated_clip"]
    assert len(clips) >= 25
    assert all(i.url.startswith("https://en.wikipedia.org/wiki/") for i in clips)
    assert all(i.lesson.rstrip().endswith("?") for i in items if i.kind == "story_seed")
    assert len({i.key for i in items}) == len(items)
    assert seed.TIMEZONE == "America/New_York"


def test_no_real_person_or_dash_in_the_demo_seed():
    """A demo that names a real client, or a Kivi person, is exactly what it exists to prevent."""
    seed = _seed()
    text = " ".join(f"{t} {lesson}" for _k, t, _u, lesson in seed.PAGES)
    text += " ".join(q for _k, q in seed.STORY_SEEDS)
    text += seed.STRATEGY_MD + " ".join(lesson for _k, _t, lesson in seed.STANDING_FACTS)
    sql = (ROOT / "scripts" / "seed_demo_profiles.sql").read_text(encoding="utf-8")
    profiles = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    for blob in (text, profiles):
        low = blob.lower()
        for word in ("ziv", "kivi", "huckabee", "gamble", "kadansky", "brant", "matan", "connie", "yaron",
                     "devi", "daily cookie"):
            assert word not in low, word
        assert "—" not in blob and "–" not in blob
    assert "--" not in text.replace("<!-- tce-strategy: replace -->", "")
    # The page's real history does not belong in a happy video about a party.
    assert not any(k in {"jumping-the-broom"} for k, *_ in seed.PAGES)
