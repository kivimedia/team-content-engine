"""Connie Kadansky's lane profile, `sales_coach` (23-Oct-2026).

Three lanes: from_teaching (her own pages), practice_room (prompts she answers from her
own memory), in_the_wild (negotiation in the news). A sales coach talks price and
discount all day, so the performer's code checks (no magic method, no gadget trend, no
money) are his alone; the never-invent-a-memory rules hold for both. Matan's behavior is
unchanged. Synthetic data.
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
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(
        settings, "workspace_lane_profiles", f"{MATAN}:performer,{CONNIE}:sales_coach", raising=False
    )


def _clean(phrases: list[str], interviewer: str = "What would you say next?") -> dict:
    return {
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": phrases,
        "facebook_post": " ".join(phrases),
        "interviewer_prompt": interviewer,
        "hook_options": [{"id": f"h{i}", "text": phrases[0]} for i in range(1, 4)],
    }


PRICE_SCRIPT = [
    "Home builders just cut prices, and buyers still are not coming.",
    "That is the pleaser's discount, in the national news.",
    "A discount does not create a buyer.",
    "A leader asks what the buyer is comparing the price with.",
    "Then she gets curious about what is underneath it.",
    "Lower the price only when you know why.",
]

PRACTICE_SCRIPT = [
    "Reading the book is not the same as doing it.",
    "What happens when someone has to name a feeling out loud?",
    "Who was practicing, and what did they say first?",
    "[your story here]",
    "What changed after the pause?",
    "Naming the feeling gets easier only when you practice it out loud.",
]


def test_connie_gets_sales_coach_and_matan_keeps_performer(lanes):
    assert lane_profile.profile_for(CONNIE).name == "sales_coach"
    assert lane_profile.profile_for(CONNIE).lane_keys == ["from_teaching", "practice_room", "in_the_wild"]
    assert lane_profile.profile_for(MATAN).name == "performer"


def test_lane_keys_are_unique_across_profiles():
    keys = [k for p in lane_profile.PROFILES.values() for k in p.lane_keys]
    assert len(keys) == len(set(keys))
    assert lane_profile.profile_for_lane("in_the_wild").name == "sales_coach"
    assert lane_profile.profile_for_lane("magic_clip").name == "performer"
    assert lane_profile.profile_for_lane("coaching") is None


def test_every_sales_coach_lane_has_a_writer_rule_and_a_label():
    for lane in lane_profile.SALES_COACH.lanes:
        assert lane.key in lane_packets._LANE_RULES
        assert lineup.LANE_LABELS[lane.key] == lane.label


def test_connie_ideas_may_talk_price_and_how():
    raw = {
        "lane": "in_the_wild",
        "title": "Builders cut prices: the secret is explained by AI pricing",
        "lesson": "Here's how it's done: a discount does not create a buyer.",
        "public_angle": "price",
    }
    assert lane_profile.lane_check(lane_profile.SALES_COACH, raw, ["news_item"]) is None


def test_matan_ideas_still_refuse_a_method():
    raw = {"lane": "magic_clip", "title": "The secret is a gimmick", "lesson": "x", "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.PERFORMER, raw, ["curated_clip"])
    assert hit is not None and hit[1] == "method_revealed"


def test_connie_practice_prompt_never_narrates_her_memory():
    raw = {"lane": "practice_room", "title": "I remember a rep who froze", "lesson": "x", "public_angle": "y"}
    hit = lane_profile.lane_check(lane_profile.SALES_COACH, raw, ["story_seed"])
    assert hit is not None and hit[:2] == ("no_invented_memory", "invented_memory")


def test_connie_script_may_talk_price_matan_may_not():
    assert lane_packets.lane_errors(_clean(PRICE_SCRIPT), "in_the_wild") == []
    errors = lane_packets.lane_errors(_clean(PRICE_SCRIPT), "trend_reaction")
    assert any(e.startswith("mentions money") for e in errors)


def test_practice_room_script_needs_her_english_slot():
    ok = _clean(PRACTICE_SCRIPT, "Think of someone who froze the first time: what happened?")
    assert lane_packets.lane_errors(ok, "practice_room") == []
    no_slot = _clean(
        [p if p != "[your story here]" else "It happens to everyone." for p in PRACTICE_SCRIPT],
        "Think of someone who froze the first time: what happened?",
    )
    errors = lane_packets.lane_errors(no_slot, "practice_room")
    assert "a practice_room script has exactly one line [your story here] where her own story goes" in errors


def test_practice_room_script_refuses_a_narrated_memory():
    told = _clean([*PRACTICE_SCRIPT[:-1], "I remember the day it clicked."], "What happened?")
    errors = lane_packets.lane_errors(told, "practice_room")
    assert any("narrates an event as her" in e for e in errors)


def test_matan_seed_errors_word_for_word_unchanged():
    he_slot = "[הסיפור שלך כאן]"
    no_slot = _clean(["?א", "?ב", "ג", "ד", "ה", "ו"], "?ז")
    errors = lane_packets.lane_errors(no_slot, "behind_scenes")
    assert f"a behind_scenes script has exactly one line {he_slot} where his own story goes" in errors


def test_writer_prompt_is_hers_for_her_lanes_and_his_for_his():
    hers = lane_packets.system_prompt("in_the_wild", None)
    assert "She films herself" in hers and "THIS IDEA'S LANE: in_the_wild" in hers
    assert "Israeli" not in hers and "Price, discounts and negotiation are her subject" in hers
    his = lane_packets.system_prompt("magic_clip", None)
    assert "He films himself" in his and "Never prices, fees, budgets, money" in his


def test_connie_asks_research_by_her_lanes(lanes):
    assert idea_lane.kinds_for(CONNIE) == ("any", "in_the_wild", "from_teaching", "practice_room")
    assert idea_lane.resolve_kind(CONNIE, "news") == "in_the_wild"
    assert idea_lane.resolve_kind(MATAN, "news") == "trend_reaction"
    assert idea_lane.KIND_SOURCES["from_teaching"] == ("curated_clip",)
    assert idea_lane.KIND_SOURCES["practice_room"] == ("story_seed",)


def test_anchors_file_never_takes_a_bare_negotiation_as_strong():
    text = (ROOT / "docs" / "news-anchors-sales-coach.md").read_text(encoding="utf-8")
    strong = text.split("## client_solution", 1)[1].split("## problem_pattern", 1)[0]
    terms = {line[2:].strip() for line in strong.splitlines() if line.startswith("- ")}
    assert terms and not terms & {"negotiation", "negotiations", "talks", "deal", "deals"}


def _topic(ws, kind):
    from types import SimpleNamespace

    return SimpleNamespace(
        workspace_id=ws, status="candidate", citations_private=[{"source_kind": kind}],
        freshness_role="news" if kind == "news_item" else "evergreen", gates={},
    )


def test_connie_topics_tabs_are_her_lanes_matan_keeps_his(lanes):
    from tce.editorial import inbox

    keys, labels = inbox.filters_for(CONNIE, owner=False)
    assert keys == ("best", "from_teaching", "practice_room", "in_the_wild", "later", "away")
    assert [labels[k] for k in keys[1:4]] == [
        "From your teaching", "From the practice room", "Negotiation in the wild",
    ]
    assert inbox.filters_for(MATAN, owner=False) == (inbox.FILTERS, inbox.FILTER_LABELS)


def test_a_lane_tab_shows_that_lane_only(lanes):
    from tce.editorial import inbox

    seed = _topic(CONNIE, "story_seed")
    assert inbox._matches("practice_room", seed, None)
    assert not inbox._matches("from_teaching", seed, None)
    assert inbox._matches("in_the_wild", _topic(CONNIE, "news_item"), None)


def test_only_her_pages_carry_her_lane_tabs(lanes):
    from tce.api import dashboard

    head = dashboard._lane_tabs_head(CONNIE)
    assert head.startswith("<script>window.TCE_LANE_TABS = ") and "Negotiation in the wild" in head
    assert dashboard._lane_tabs_head(MATAN) == ""


def test_her_lane_ideas_reach_topics_matans_stay_as_they_were(lanes):
    from types import SimpleNamespace

    from tce.editorial import briefs

    def idea(ws, kind):
        return SimpleNamespace(
            workspace_id=ws, title="t", audience="coaches", lesson="l", public_angle="a",
            freshness_role="evergreen", citations_private=[{"source_kind": kind}],
            reasons_to_care=[], public_safety_notes="",
        )

    teaching = briefs.seed_brief(idea(CONNIE, "curated_clip"))
    assert teaching["why_this_is_yours"] == "It came out of your own teaching."
    assert briefs.is_inbox_eligible(teaching)
    practice = briefs.seed_brief(idea(CONNIE, "story_seed"))
    assert practice["why_this_is_yours"] == "It came out of a question about your own practice room."
    assert not briefs.is_inbox_eligible(briefs.seed_brief(idea(MATAN, "curated_clip")))


def test_every_strong_anchor_is_citable_and_kinds_agree():
    spec = importlib.util.spec_from_file_location("seed_connie_lanes", ROOT / "scripts" / "seed_connie_lanes.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    text = (ROOT / "docs" / "news-anchors-sales-coach.md").read_text(encoding="utf-8")
    kinds: dict[str, str] = {}
    kind = None
    for line in text.splitlines():
        if line.startswith("## "):
            kind = line[3:].strip()
        elif line.startswith("- ") and kind:
            kinds[line[2:].strip()] = kind
    facts = {term: k for k, term, _lesson in seed.STANDING_FACTS}
    assert all(kinds.get(term, k) == k for term, k in facts.items())
    missing = {"contract negotiations", "tentative agreement", "holdout", "bargaining table",
               "price cuts", "carriage dispute", "counteroffer"} - set(facts)
    assert not missing


def test_connie_seed_validates():
    spec = importlib.util.spec_from_file_location("seed_connie_lanes", ROOT / "scripts" / "seed_connie_lanes.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    seed.validate_all()
    kinds = {i.kind for i in seed.lane_items()}
    assert kinds == {"curated_clip", "story_seed"}
    assert all(i.url.startswith("https://exceptionalsales.com/") for i in seed.lane_items() if i.kind == "curated_clip")
