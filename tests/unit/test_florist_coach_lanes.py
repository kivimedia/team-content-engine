"""Tim Huckabee's lane profile, `florist_coach` (03-Nov-2026).

Three lanes: from_my_courses (one lesson from his own courses), coaching_room (prompts
he answers from his own memory of coaching florists) and smart_ideas (clever sales
ideas of small businesses close to florists, in the news). Matan's, Connie's and
Brant's behavior is unchanged (their own suites). Synthetic data.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from tce.editorial import idea_lane, lane_packets, lane_profile, lineup
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
CONNIE = uuid.UUID("7247b8fa-d627-4357-b6e8-ca2a26cd4b14")
BRANT = uuid.UUID("3844285d-f119-47e9-98e4-5691f0cbdb4b")
TIM = uuid.UUID("34944494-e003-4852-bc69-de7607bcbdb0")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(
        settings,
        "workspace_lane_profiles",
        f"{MATAN}:performer,{CONNIE}:sales_coach,{BRANT}:fire_performer,{TIM}:florist_coach",
        raising=False,
    )
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)


def _seed():
    spec = importlib.util.spec_from_file_location("seed_tim_lanes", ROOT / "scripts" / "seed_tim_lanes.py")
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


COACHING_SCRIPT = [
    "Every owner I coach says the same thing about Valentine's Day.",
    "They are scared to charge more for a dozen roses.",
    "What do you tell an owner who thinks the grocery store will win?",
    "And what does she do the week after?",
    "[your story here]",
    "Your roses are not grocery store roses.",
    "Price them like they are yours.",
]

SMART_SCRIPT = [
    "A toy shop just gave every kid a birthday card in the mail.",
    "Half of them came back with a parent and a wallet.",
    "Your shop knows every birthday on every card message.",
    "Use it.",
    "Call them a week before, and offer to make it again.",
    "That is a sale you already earned last year.",
]


def test_tim_gets_florist_coach_and_the_others_keep_theirs(lanes):
    assert lane_profile.profile_for(TIM).name == "florist_coach"
    assert lane_profile.profile_for(TIM).lane_keys == ["from_my_courses", "coaching_room", "smart_ideas"]
    assert lane_profile.profile_for(BRANT).name == "fire_performer"
    assert lane_profile.profile_for(CONNIE).name == "sales_coach"
    assert lane_profile.profile_for(MATAN).name == "performer"


def test_lane_keys_stay_unique_across_profiles():
    keys = [k for p in lane_profile.PROFILES.values() for k in p.lane_keys]
    assert len(keys) == len(set(keys))
    assert lane_profile.profile_for_lane("smart_ideas").name == "florist_coach"


def test_every_florist_coach_lane_has_a_writer_rule_and_its_label():
    for lane in lane_profile.FLORIST_COACH.lanes:
        assert lane.key in lane_packets._LANE_RULES
        assert lineup.LANE_LABELS[lane.key] == lane.label
    assert [lane.label for lane in lane_profile.FLORIST_COACH.lanes] == [
        "From your courses", "From the coaching room", "Smart ideas from other shops",
    ]


def test_coaching_prompt_never_narrates_his_memory():
    raw = {"lane": "coaching_room", "title": "I remember a shop that tripled sales", "lesson": "x",
           "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.FLORIST_COACH, raw, ["story_seed"])
    assert hit is not None and hit[:2] == ("no_invented_memory", "invented_memory")


def test_a_lane_idea_cites_its_own_lane_evidence():
    raw = {"lane": "from_my_courses", "title": "Never ask for a budget", "lesson": "x", "public_angle": "y"}
    assert lane_profile.lane_check(lane_profile.FLORIST_COACH, raw, ["curated_clip"]) is None
    hit = lane_profile.lane_check(lane_profile.FLORIST_COACH, raw, ["news_item"])
    assert hit is not None and hit[1] == "lane_evidence"


def test_coaching_script_needs_his_slot_and_refuses_a_told_memory():
    ok = _clean(COACHING_SCRIPT, "What do you tell an owner who is scared to charge more?")
    assert lane_packets.lane_errors(ok, "coaching_room") == []
    no_slot = _clean(
        [p if p != "[your story here]" else "Every shop is different." for p in COACHING_SCRIPT],
        "What do you tell an owner who is scared to charge more?",
    )
    errors = lane_packets.lane_errors(no_slot, "coaching_room")
    assert "a coaching_room script has exactly one line [your story here] where his own story goes" in errors
    told = _clean([*COACHING_SCRIPT[:-1], "I remember the owner who doubled her roses."], "What happened?")
    assert any("narrates an event as his" in e for e in lane_packets.lane_errors(told, "coaching_room"))


def test_price_talk_is_his_subject():
    # Price points and add-ons are what he teaches: no money check, like Connie's.
    assert lane_profile.FLORIST_COACH.code_checks == frozenset()
    priced = _clean([*SMART_SCRIPT[:-1], "Offer the 75 dollar arrangement before the 50."])
    assert not any(e.startswith("mentions money") for e in lane_packets.lane_errors(priced, "smart_ideas"))


def test_writer_prompt_is_his_for_his_lanes():
    his = lane_packets.system_prompt("smart_ideas", None)
    assert "a coach for flower shop owners" in his and "THIS IDEA'S LANE: smart_ideas" in his
    assert "never his own fees" in his
    assert "Fire Guy" not in his and "Israeli" not in his and "She films herself" not in his


def test_tim_asks_research_by_his_lanes(lanes):
    assert idea_lane.kinds_for(TIM) == ("any", "smart_ideas", "from_my_courses", "coaching_room")
    assert idea_lane.resolve_kind(TIM, "news") == "smart_ideas"
    assert idea_lane.resolve_kind(BRANT, "news") == "taming_fire"
    assert idea_lane.KIND_SOURCES["from_my_courses"] == ("curated_clip",)
    assert idea_lane.KIND_SOURCES["coaching_room"] == ("story_seed",)


def test_his_topics_tabs_are_his_lanes(lanes):
    from tce.editorial import inbox

    keys, labels = inbox.filters_for(TIM, owner=False)
    assert keys == ("best", "from_my_courses", "coaching_room", "smart_ideas", "later", "away")
    assert [labels[k] for k in keys[1:4]] == [
        "From your courses", "From the coaching room", "Smart ideas from other shops",
    ]


def test_his_lane_ideas_reach_topics(lanes):
    from types import SimpleNamespace

    from tce.editorial import briefs

    def idea(kind):
        return SimpleNamespace(
            workspace_id=TIM, title="t", audience="both", lesson="l", public_angle="a",
            freshness_role="evergreen", citations_private=[{"source_kind": kind}],
            reasons_to_care=[], public_safety_notes="",
        )

    course = briefs.seed_brief(idea("curated_clip"))
    assert course["why_this_is_yours"] == "It came out of your own courses."
    assert briefs.is_inbox_eligible(course)
    coaching = briefs.seed_brief(idea("story_seed"))
    assert coaching["why_this_is_yours"] == "It came out of a question about your own coaching."


def test_his_news_card_names_his_shops_not_client_work(lanes):
    from types import SimpleNamespace

    from tce.editorial import briefs

    news = SimpleNamespace(
        workspace_id=TIM, title="t", audience="both", lesson="l", public_angle="a",
        freshness_role="news", reasons_to_care=[], public_safety_notes="",
        citations_private=[
            {"source_kind": "news_item", "source_title": "Toy shop mails every kid a birthday card"},
            {"source_kind": "standing_fact"},
        ],
    )
    assert briefs.seed_brief(news)["why_this_is_yours"] == (
        "Toy shop mails every kid a birthday card touches your own work with flower shops."
    )


def test_his_week_line_reads_as_a_sentence(lanes):
    # Sorted by lane key, labels lowercased into the sentence (his are not proper names).
    counts = {"from_my_courses": 2, "coaching_room": 1}
    assert lineup.lane_mix(TIM, counts) == "1 from the coaching room · 2 from your courses"


def test_his_news_has_his_own_editor(lanes):
    from tce.news import appraise
    from tce.news.appraise import AppraisalInput

    data = AppraisalInput(
        title="Toy store owner starts a birthday club", publisher="Example",
        published_at=None, primary_url="https://example.com/a", document="text",
        anchors=[{"kind": "client_solution", "term": "toy store owner"}], recent_evidence=[],
    )
    req = appraise.build_request(data, workspace_id=TIM, news_item_id=uuid.uuid4())
    assert req.system.startswith("You are Tim Huckabee's editor")
    assert req.prompt_version == f"{appraise.PROMPT_VERSION}.florist_coach"


def _anchor_kinds() -> dict[str, str]:
    text = (ROOT / "docs" / "news-anchors-florist-coach.md").read_text(encoding="utf-8")
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


def test_no_bare_shop_or_sales_word_is_a_strong_anchor():
    strong = {t for t, k in _anchor_kinds().items() if k == "client_solution"}
    assert not strong & {"sales", "shop", "store", "owner", "business", "flowers", "customers",
                         "restaurant", "bakery", "deal"}


def _anchors() -> list:
    from types import SimpleNamespace

    return [SimpleNamespace(kind=kind, term=term, id=None, weight=1.0) for term, kind in _anchor_kinds().items()]


@pytest.mark.parametrize("headline", [
    # 03-Nov feed probe: the kinds of items his lane is for.
    "Boise toy store owner starts a birthday club for regulars",
    "Local bakery brings customers back with a punch card",
    "Fulton County chamber promotes Small Business Saturday",
    "Coffee shop owner turns a slow Tuesday into a tasting night",
])
def test_a_small_shops_selling_move_is_his_news(headline):
    from tce.news import matcher

    assert matcher.match_item(title=headline, anchors=_anchors()).matched


@pytest.mark.parametrize("headline", [
    "Five Below hires 50,000 seasonal workers",
    "Storied Paris department store receives bankruptcy protection",
    "New sales tax takes effect in January",
])
def test_chains_and_tax_stay_out(headline):
    from tce.news import matcher

    assert not matcher.match_item(title=headline, anchors=_anchors()).matched


def test_his_bing_feeds_are_date_ordered():
    seed = _seed()
    bing = [url for _name, url, *_rest in seed.FEEDS if "bing.com" in url]
    assert bing and all("sortbydate" in url for url in bing)
    assert len({url for _name, url, *_rest in seed.FEEDS}) == len(seed.FEEDS)


def test_tim_seed_validates():
    seed = _seed()
    seed.validate_all()
    items = seed.lane_items()
    assert {i.kind for i in items} == {"curated_clip", "story_seed"}
    clips = [i for i in items if i.kind == "curated_clip"]
    assert len(clips) >= 30
    assert all(i.url.startswith("https://theprofitableflorist.com/") for i in clips)
    assert all(i.lesson.rstrip().endswith("?") for i in items if i.kind == "story_seed")
    assert len({i.key for i in items}) == len(items)


def test_a_members_only_lesson_page_counts_as_answered():
    seed = _seed()
    assert seed.page_answered(200, None)
    assert seed.page_answered(302, "https://theprofitableflorist.com/login/?redirect_to=x")
    assert seed.page_answered(302, "/my-account/")
    assert not seed.page_answered(302, "https://elsewhere.example/parked")
    assert not seed.page_answered(404, None)


def test_his_briefs_name_flower_shop_owners_as_the_audience(lanes):
    from types import SimpleNamespace

    from tce.editorial import briefs

    def idea(ws, audience):
        return SimpleNamespace(
            workspace_id=ws, title="t", audience=audience, lesson="l", public_angle="a",
            freshness_role="evergreen", citations_private=[{"source_kind": "curated_clip"}],
            reasons_to_care=[], public_safety_notes="",
        )

    # The selector's audience codes are the owner's (coaches / event owners); 3-Nov
    # his room said "Coaches, and the service owners they work with".
    for code in ("both", "event_owners", "coaches"):
        assert briefs.seed_brief(idea(TIM, code))["audience"] == "Flower shop owners and their teams"
    # Connie's and Brant's come from their own selector prompts (3-Nov, Ziv "labels").
    assert briefs.seed_brief(idea(CONNIE, "both"))["audience"] == (
        "Salespeople, sales managers and leaders, and coaches who sell their own services"
    )
    assert briefs.seed_brief(idea(BRANT, "both"))["audience"] == (
        "People who book live entertainment, and fans of fire and daredevil feats"
    )
    # Matan's (Hebrew) and the owner's keep the owner's wording.
    assert briefs.seed_brief(idea(MATAN, "both"))["audience"] == "Coaches, and the service owners they work with"
    owner = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
    assert briefs.seed_brief(idea(owner, "event_owners"))["audience"] == "Event and service business owners"


def test_no_shop_or_person_is_named_in_his_lessons_or_prompts():
    seed = _seed()
    text = " ".join(f"{t} {lesson}" for _k, t, _u, lesson, _c in seed.LESSONS)
    text += " ".join(q for _k, q in seed.STORY_SEEDS)
    for name in ("Rebekah", "Rebecca", "Ivy", "Casey", "Kath", "Ziv"):
        assert name not in text
    assert "—" not in text and "–" not in text and "--" not in text
