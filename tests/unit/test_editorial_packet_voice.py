"""The packet writer receives Ziv's voice standard, and cannot ship against it.

Before this, the complete voice instruction the writer got was one clause and the
banned vocabulary was never checked anywhere on this path.
"""

from __future__ import annotations

import uuid

import pytest

from tce.editorial import packets
from tce.models.editorial import TopicCandidate
from tce.services.strategy_loader import load_effective_strategy
from tests.unit.test_editorial_packets import good_output  # noqa: F401 - shared fixture


@pytest.mark.parametrize(
    "field,value",
    [
        ("facebook_post", "This is a game-changer for coaches. Book a strategy session."),
        ("linkedin_post", "The window is closing on this. Book a strategy session."),
    ],
)
def test_a_banned_phrase_fails_the_packet(field, value):
    with pytest.raises(packets.PacketValidationError, match="banned vocabulary"):
        packets.validate_packet_output(good_output(**{field: value}))


def test_a_banned_phrase_in_a_bullet_fails():
    bullets = [
        "Start from what the person can do afterward",
        "Now more than ever, name the problems",
        "Put the problems in order",
        "Match each lesson to one problem",
        "Cut what does not help",
    ]
    with pytest.raises(packets.PacketValidationError, match="banned vocabulary"):
        packets.validate_packet_output(good_output(bullets=bullets))


def test_a_long_dash_fails():
    with pytest.raises(packets.PacketValidationError, match="banned vocabulary"):
        packets.validate_packet_output(
            good_output(linkedin_post="One thing — then another. Book a strategy session.")
        )


def test_a_banned_phrase_in_an_opening_fails():
    # The hook is where the default style shows first, so it is checked like the rest.
    out = good_output()
    out["hook_options"][0]["text"] = out["script_phrases"][0]
    out["hook_options"][1]["text"] = "Here is the paradigm shift nobody mentions."
    with pytest.raises(packets.PacketValidationError, match="banned vocabulary"):
        packets.validate_packet_output(out)


def test_a_clean_packet_still_passes():
    assert packets.validate_packet_output(good_output())["bullets"]


async def test_the_prompt_now_carries_his_voice_rules():
    # The regression that started all of this: include_voice defaulted to false and
    # nothing passed it, so the writer had never seen a single pattern.
    with_voice = await load_effective_strategy(None, None, include_voice=True)
    without = await load_effective_strategy(None, None)

    assert "ZIV'S VOICE AND WRITING STYLE" in with_voice.text
    assert "Banned vocabulary" in with_voice.text
    assert "Could this have been written by a peer" in with_voice.text  # the meta-rule
    assert any(s.get("includes_voice") for s in with_voice.sources)  # provenance says so
    assert "ZIV'S VOICE" not in without.text
    assert len(with_voice.text) > len(without.text)


def test_the_built_prompt_shows_the_writer_how_he_sounds():
    cand = TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        week_start=None,
        moment_ids=["m1"],
        title="Before you blame the marketing",
        lesson="Check the stage where people drop off.",
        audience="coaches",
        public_angle="Funnel stages.",
        gates={},
        citations_private=[{"moment_id": "m1", "excerpt_private": "the words"}],
    )
    voice_text = "## ZIV'S VOICE AND WRITING STYLE\n20. Hooks with real tension."

    prompt = packets.build_packet_prompt(voice_text, cand)

    assert "ZIV'S VOICE" in prompt
    assert "Hooks with real tension" in prompt
