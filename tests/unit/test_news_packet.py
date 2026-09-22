"""The script rules that make a news idea sound like Ziv rather than a feed."""

from __future__ import annotations

import pytest

from tce.editorial.news_packet import (
    forbidden_terms_for,
    news_errors,
    opening_problems,
    urgency_hit,
)
from tce.editorial.packets import PacketValidationError, validate_packet_output

TERMS = ["WhatsApp Business", "Meta"]


def packet(**over) -> dict:
    """A cleaned packet shape, as validate_packet_output returns it."""
    base = {
        "bullets": ["b1", "b2", "b3", "b4", "b5"],
        "script_phrases": [
            "Most florists find out about a price change from the invoice.",
            "That is a bad way to find out.",
            "WhatsApp Business is moving to per-message pricing.",
            "So every follow-up in a sequence now has its own cost.",
            "Count what each sequence sends before the bill does it for you.",
            "If you want help with that, book a strategy session.",
        ],
        "facebook_post": "A post about owners and their sequences.",
        "linkedin_post": "A post about owners and their sequences.",
        "hook_options": [
            {"id": "h1", "text": "Most florists find out about a price change from the invoice."},
            {"id": "h2", "text": "Your follow-up sequence has a cost you have never counted."},
        ],
        "beats": [
            {"start_phrase_id": "p001", "end_phrase_id": "p002"},
            {"start_phrase_id": "p003", "end_phrase_id": "p004"},
            {"start_phrase_id": "p005", "end_phrase_id": "p006"},
        ],
    }
    base.update(over)
    return base


def test_a_well_formed_news_packet_passes():
    assert news_errors(packet(), TERMS) == []


# --- 1. the opening -----------------------------------------------------------


@pytest.mark.parametrize(
    "opening, why",
    [
        ("WhatsApp Business just changed its pricing.", "names 'WhatsApp Business'"),
        ("Meta changed something you pay for.", "names 'Meta'"),
        ("On 1 January your messages get more expensive.", "carries a date"),
        ("Last week a pricing change landed.", "carries a date"),
        ("Three things changed in your follow-ups.", "carries a number"),
        ("Your costs could rise 40% overnight.", "carries a number"),
    ],
)
def test_an_opening_that_sounds_like_a_news_account_is_refused(opening, why):
    assert why in opening_problems(opening, TERMS)


def test_an_owners_situation_is_a_fine_opening():
    assert opening_problems("Most florists find out from the invoice.", TERMS) == []


def test_a_news_headline_as_a_hook_fails_the_packet():
    bad = packet(
        hook_options=[
            {"id": "h1", "text": "Most florists find out about a price change from the invoice."},
            {"id": "h2", "text": "WhatsApp Business just moved to per-message pricing."},
        ]
    )
    errors = news_errors(bad, TERMS)
    assert any("news opening h2" in e for e in errors)


def test_matching_is_whole_word_so_a_substring_is_not_a_name():
    """'Metaphor' is not 'Meta'."""
    assert opening_problems("There is a metaphor owners use for this.", ["Meta"]) == []


# --- 2. the news waits for beat two -------------------------------------------


def test_naming_the_vendor_in_the_first_beat_fails():
    early = packet(
        script_phrases=[
            "Most florists find out about a price change from the invoice.",
            "Meta is the one changing it.",  # beat 1 names the vendor
            "WhatsApp Business is moving to per-message pricing.",
            "So every follow-up in a sequence now has its own cost.",
            "Count what each sequence sends.",
            "If you want help with that, book a strategy session.",
        ]
    )
    assert any("first beat names 'Meta'" in e for e in news_errors(early, TERMS))


def test_naming_it_in_beat_two_is_exactly_right():
    assert not any("first beat" in e for e in news_errors(packet(), TERMS))


# --- 3. no manufactured urgency -----------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    ["Breaking: the pricing changed.", "They just announced it.",
     "Act now before it's too late.", "Everyone is talking about this."],
)
def test_urgency_is_refused_anywhere(phrase):
    assert urgency_hit([phrase])
    assert any("manufactured urgency" in e for e in news_errors(packet(facebook_post=phrase), TERMS))


def test_ordinary_words_are_not_mistaken_for_urgency():
    assert urgency_hit(["Now is a good week to count your sequences."]) is None


# --- which names are forbidden ------------------------------------------------


def test_forbidden_terms_are_the_vendor_side_not_the_owner_side():
    """The opening is SUPPOSED to be about the owner's situation, so client
    solutions and problem patterns must stay usable in it."""
    terms = forbidden_terms_for(
        {"publisher": "Meta"},
        [
            {"kind": "vendor", "term": "whatsapp business"},
            {"kind": "model_id", "term": "claude-opus-5"},
            {"kind": "client_solution", "term": "an AI receptionist answering a shop's phone"},
            {"kind": "problem_pattern", "term": "leads go cold"},
        ],
    )
    assert "Meta" in terms and "whatsapp business" in terms and "claude-opus-5" in terms
    assert not any("receptionist" in t or "leads go cold" in t for t in terms)


# --- the evergreen path is untouched ------------------------------------------


def _raw_packet(first_phrase: str) -> dict:
    phrases = [
        first_phrase,
        "phrase two",
        "phrase three",
        "phrase four",
        "phrase five",
        "If you want help with that, book a strategy session.",
    ]
    return {
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": phrases,
        "facebook_post": "fb",
        "linkedin_post": "li",
        "interviewer_prompt": "ask",
        "hook_options": [
            {"id": f"h{i}", "text": first_phrase if i == 1 else f"alt {i}",
             "question": "q", "payoff_phrase_id": "p002", "rationale": "r",
             "moment_ids": ["m1"]}
            for i in (1, 2, 3)
        ],
        "selected_hook_id": "h1",
        "beats": [
            {"bullet_index": i, "start_phrase_id": f"p{i + 1:03d}",
             "end_phrase_id": f"p{i + 1:03d}"}
            for i in range(5)
        ],
    }


def test_an_evergreen_packet_may_open_with_a_number_as_before():
    """news_terms=None must mean exactly the validation that existed before."""
    raw = _raw_packet("Three questions I ask every coach.")
    validate_packet_output(raw)  # no news_terms: passes as it always did


def test_the_same_opening_fails_once_it_is_a_news_idea():
    raw = _raw_packet("Three questions I ask every coach.")
    with pytest.raises(PacketValidationError, match="carries a number"):
        validate_packet_output(raw, news_terms=[])
