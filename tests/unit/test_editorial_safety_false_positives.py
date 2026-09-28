"""Public-safety scan false positives that parked real scripts as drafts (28-Sep-2026).

Three packets were written, scanned and saved as "draft" instead of "ready", so
the week said "0 scripts ready" while he had eight topics waiting to be scripted.
The scanner flagged lines that DISCLAIM a guarantee, and it took "The" from a
participant's company name ("Tim Hollis - In The Box Events") as a person's name.

The scanner must stay conservative: a real promise and a real name still flag.
"""

from __future__ import annotations

import pytest

from tce.editorial.safety import scan_public_text

PARTICIPANT = "Tim Hollis - In The Box Events"


def kinds(result: dict) -> set[str]:
    return {issue["kind"] for issue in result["issues"]}


# ------------------------------------------------------------- guarantees


@pytest.mark.parametrize(
    "line",
    [
        # The three live sentences, verbatim.
        "It's not a guarantee, it's a starting point.",
        "This isn't a guarantee",
        "it's a rule of thumb, not a guarantee",
        # The same hedge in the other ways a script says it.
        "This isn’t a guarantee, it's a place to start.",
        "There are no guarantees here.",
        "I can't guarantee it will work for you.",
        "Nothing is guaranteed.",
        "It is not guaranteed to work the first time.",
    ],
)
def test_a_line_that_disclaims_a_guarantee_is_not_flagged(line):
    result = scan_public_text({"script_phrases": [line]})
    assert "absolute_guarantee" not in kinds(result), result["issues"]


@pytest.mark.parametrize(
    "line",
    [
        "guaranteed results",
        "I guarantee you'll double revenue",
        "100% guarantee",
        "It's not a trick, I guarantee it works.",
        "Not only do I guarantee results, I deliver them.",
        "Every client gets a 30-day money-back guarantee.",
        "This is guaranteed to work.",
        "It's risk-free.",
    ],
)
def test_a_real_promise_is_still_flagged(line):
    result = scan_public_text({"script_phrases": [line]})
    assert "absolute_guarantee" in kinds(result), line


# ------------------------------------------------------------- participant names


@pytest.mark.parametrize(
    "line",
    [
        # The two live sentences, verbatim.
        "The first draft asked if a call would help.",
        "The same thing works for a coach.",
        # Other words from the company part of his display name.
        "Mix the two lists together.",
        "Events like this one take a week to plan.",
    ],
)
def test_company_words_in_a_display_name_do_not_flag_ordinary_sentences(line):
    result = scan_public_text({"script_phrases": [line]}, participants=[PARTICIPANT, "Ziv Raviv"])
    assert "participant_name" not in kinds(result), result["issues"]


@pytest.mark.parametrize(
    "line",
    [
        "Tim asked me about pricing.",
        "I spoke with Hollis last week.",
        "Tim Hollis told me this.",
        "That was Tim's idea, not mine.",
        # The business as a whole still identifies the client.
        "In The Box Events runs a tight ship.",
    ],
)
def test_the_participants_real_name_is_still_flagged(line):
    result = scan_public_text({"script_phrases": [line]}, participants=[PARTICIPANT])
    assert "participant_name" in kinds(result), line


@pytest.mark.parametrize(
    "display",
    [
        "Tim Hollis (In The Box Events)",
        "In The Box Events | Tim Hollis",
        "Tim Hollis, In The Box Events",
        "Tim Hollis – In The Box Events",  # an en dash, as Zoom sometimes writes it
    ],
)
def test_other_display_name_shapes_keep_the_name_and_drop_the_company_words(display):
    ordinary = scan_public_text(
        {"script_phrases": ["The same thing works for a coach."]}, participants=[display]
    )
    assert "participant_name" not in kinds(ordinary), (display, ordinary["issues"])
    named = scan_public_text({"script_phrases": ["Tim asked me about it."]}, participants=[display])
    assert "participant_name" in kinds(named), display


def test_pronouns_in_a_display_name_are_not_names():
    # Zoom puts pronouns in the name; "He" opens half the sentences he says.
    display = "Tim Hollis (he/him)"
    for line in ("He said the same thing.", "Him too, in the end.", "They asked twice."):
        result = scan_public_text({"script_phrases": [line]}, participants=[display])
        assert "participant_name" not in kinds(result), (line, result["issues"])
    named = scan_public_text({"script_phrases": ["Tim asked me."]}, participants=[display])
    assert "participant_name" in kinds(named)


def test_two_people_in_one_display_name_are_both_looked_for():
    for line in ("Sarah asked me about it.", "Then Mike called me."):
        result = scan_public_text({"script_phrases": [line]}, participants=["Sarah and Mike"])
        assert "participant_name" in kinds(result), line
    ordinary = scan_public_text(
        {"script_phrases": ["And then it worked."]}, participants=["Sarah and Mike"]
    )
    assert "participant_name" not in kinds(ordinary), ordinary["issues"]


def test_a_name_run_into_the_business_name_is_still_caught():
    # No separator at all: the name at the front is still a name, and the
    # business words behind it still are not.
    display = "Tim Hollis In The Box Events"
    for line in ("I asked Tim about it.", "Tim Hollis told me this.", "So Hollis said no."):
        result = scan_public_text({"script_phrases": [line]}, participants=[display])
        assert "participant_name" in kinds(result), line
    for line in ("The first draft asked if a call would help.", "Mix the two lists together."):
        result = scan_public_text({"script_phrases": [line]}, participants=[display])
        assert "participant_name" not in kinds(result), (line, result["issues"])


def test_a_role_beside_the_name_is_not_a_name():
    for display in ("DJ Tim Hollis", "Tim Hollis - Owner"):
        named = scan_public_text({"script_phrases": ["Tim asked me."]}, participants=[display])
        assert "participant_name" in kinds(named), display
        role = scan_public_text(
            {"script_phrases": ["Owner or not, DJ or not, it works."]}, participants=[display]
        )
        assert "participant_name" not in kinds(role), (display, role["issues"])


def test_a_business_only_display_name_flags_the_business_not_its_words():
    display = "Big Fun Parties"
    ordinary = scan_public_text(
        {"script_phrases": ["Fun fact: nobody reads the second line."]}, participants=[display]
    )
    assert "participant_name" not in kinds(ordinary), ordinary["issues"]
    named = scan_public_text(
        {"script_phrases": ["I booked Big Fun Parties for it."]}, participants=[display]
    )
    assert "participant_name" in kinds(named)


def test_a_long_name_is_one_person_not_a_business():
    result = scan_public_text(
        {"script_phrases": ["Carmen asked me about pricing."]},
        participants=["Maria del Carmen Lopez Garcia"],
    )
    assert "participant_name" in kinds(result)


def test_a_first_last_email_still_names_the_person():
    # An email as the display name used to be dropped whole, so the person behind
    # it was never looked for. first.last is a name; a bare mailbox is not.
    result = scan_public_text(
        {"script_phrases": ["Tim asked me about it."]},
        participants=["tim.hollis@inthemix.example"],
    )
    assert "participant_name" in kinds(result)
    clean = scan_public_text(
        {"script_phrases": ["Info matters more than you think."]},
        participants=["info@inthemix.example"],
    )
    assert "participant_name" not in kinds(clean)


def test_a_single_name_is_still_flagged():
    result = scan_public_text(
        {"script_phrases": ["Dana told me it worked."]}, participants=["Dana"]
    )
    assert "participant_name" in kinds(result)


def test_a_name_that_is_also_a_word_flags_mid_sentence_but_not_as_the_opening_word():
    people = ["Will Porter - Porter Events", "Don Smith"]
    for line in ("Will this work for you?", "Don't start with the lessons."):
        result = scan_public_text({"script_phrases": [line]}, participants=people)
        assert "participant_name" not in kinds(result), (line, result["issues"])
    for line in ("I asked Will about it.", "Porter said the same.", "Then Don called me."):
        result = scan_public_text({"script_phrases": [line]}, participants=people)
        assert "participant_name" in kinds(result), line


def test_ziv_is_never_his_own_participant():
    result = scan_public_text(
        {"script_phrases": ["Ziv here, with one idea."]},
        participants=["Ziv Raviv - Kivi Media", "ziv.raviv@example.com"],
    )
    assert "participant_name" not in kinds(result), result["issues"]


# ------------------------------------------------------------- review of the fix (28-Sep-2026)
#
# A review of the first fix found it had traded false positives for missed names:
# a first name that is also a word ("Nick", "Grace") went quiet at the start of a
# sentence, a name run into a business name flagged only mid-sentence, and a
# business with a digit or "&" in it was never found. Each bullet is scanned on
# its own, so a bullet that opens with the name always opens a sentence.


@pytest.mark.parametrize(
    ("participants", "line"),
    [
        (["Nick"], "Nick doubled his bookings after raising prices."),
        (["Nick Alvarez"], "Nick told me the price was too high."),
        (["Jack Miller"], "Jack said the same thing on our call."),
        (["Grace Lee"], "Grace asked about pricing."),
        (["Max"], "Max booked three weddings in a week."),
        (["Frank Russo"], "Frank, a DJ in Ohio, told me his close rate."),
        (["Drew Carter"], "Drew runs a photo booth company."),
        (["Holly Park"], "Holly raised prices twice."),
        (["Rob Stone"], "Rob told me he was fully booked."),
        (["Mark Cohen"], "Mark told me he was fully booked."),
        (["Dean"], "Dean's story: he stopped discounting."),
        (["Nick Alvarez"], '"Nick, raise your prices," I said.'),
        (["Dr. Frank Lee"], "I asked Dr. Frank about it."),
        (["Will Porter"], "Will told me the same thing."),
        # A one-word speaker label is the only name there is.
        (["Will"], "Will told me the same thing."),
    ],
)
def test_a_first_name_at_the_start_of_a_sentence_is_still_a_name(participants, line):
    result = scan_public_text({"bullets": [line]}, participants=participants)
    assert "participant_name" in kinds(result), (participants, line)


@pytest.mark.parametrize(
    ("participants", "line"),
    [
        (["Will Porter"], "Will this work for you?"),
        (["Will"], "Will you raise prices this year?"),
        (["Mark Cohen"], "Mark each problem before you fix it."),
        (["May Chen"], "May I ask you something?"),
        (["Chase Miller"], "Chase the deposit the same day."),
        (["Bill Evans"], "Bill for your time, not for the hours."),
        (["Hope Davis"], "Hope you had a good weekend."),
        # A surname that is an everyday word, with the rest of the name flagged.
        (["Sarah Price"], "Price is the first thing they ask about."),
        (["Sarah Long"], "Long story short, it worked."),
    ],
)
def test_a_name_used_as_the_ordinary_word_at_the_start_is_not_flagged(participants, line):
    result = scan_public_text({"bullets": [line]}, participants=participants)
    assert "participant_name" not in kinds(result), (participants, line, result["issues"])


@pytest.mark.parametrize(
    ("display", "line"),
    [
        # No separator between the name and the business.
        ("Tim Hollis In The Box Events", "Tim asked me about it."),
        ("Tim Hollis In The Box Events", "Hollis said no."),
        ("Sarah Smith Coaching", "Sarah raised her prices."),
        ("Sarah Smith Photography", "Smith's calendar was empty."),
        # Pronouns with no parentheses around them.
        ("Tim Hollis he/him", "Tim said this works."),
        ("Tim Hollis he/him", "Hollis said this works."),
        # A given name that is also a small word.
        ("An Nguyen", "Nguyen told me the same thing."),
        ("An Nguyen", "I asked Nguyen about it."),
        ("My Tran", "So Tran said no."),
        # A surname that is also a business word.
        ("Sarah Church", "Sarah said the same thing."),
        # "Last, First", as a work calendar writes it.
        ("Hollis, Tim", "Tim asked me about it."),
    ],
)
def test_a_name_beside_business_words_or_pronouns_is_still_a_name(display, line):
    result = scan_public_text({"bullets": [line]}, participants=[display])
    assert "participant_name" in kinds(result), (display, line)


@pytest.mark.parametrize(
    ("display", "line"),
    [
        ("Tim Hollis - B&B Events", "B&B Events raised prices."),
        ("Tim Hollis - 4Ever Events", "4Ever Events raised prices."),
        ("Tim Hollis - Studio 54 Events", "Studio 54 Events raised prices."),
        ("Tim Hollis - A1 Sound", "A1 Sound raised prices."),
        ("Tim Hollis - DJ 360", "DJ 360 raised prices."),
        ("Tim Hollis - Club 21", "Club 21 raised prices."),
        # The business without its "Events" still names it.
        ("Tim Hollis - In The Box Events", "The team at In The Box raised prices."),
        ("Tim Hollis In The Box Events", "In The Box Events runs a tight ship."),
    ],
)
def test_a_business_is_found_as_it_is_written(display, line):
    result = scan_public_text({"bullets": [line]}, participants=[display])
    assert "participant_name" in kinds(result), (display, line)


@pytest.mark.parametrize(
    "line",
    [
        # A promise after a line break is still a promise.
        "Most DJs will tell you it's luck. It's not\n\nGuaranteed bookings come from a system.",
        "Luck? No\nGuaranteed bookings come from a system.",
        "Cold calls? Never\nRisk-free referrals instead.",
        # "Nobody does it like us" is a claim, not a disclaimer.
        "Nobody guarantees results like we do.",
        "No one guarantees results the way this program does.",
        "Nothing is guaranteed like this system.",
        # Asked, or denied twice, the denial is the offer.
        "Why not guaranteed results? You get them here.",
        "Is this not guaranteed? It is.",
        "You'll never be without a guarantee with us.",
    ],
)
def test_a_promise_that_only_looks_denied_is_still_flagged(line):
    result = scan_public_text({"script_phrases": [line]})
    assert "absolute_guarantee" in kinds(result), line


@pytest.mark.parametrize(
    "line",
    [
        "No one can guarantee results.",
        "Nobody can promise that, and nobody is guaranteed a booking.",
        "It's not a guarantee, is it?",
        "Nothing's guaranteed in this business.",
    ],
)
def test_no_one_can_guarantee_is_still_a_disclaimer(line):
    result = scan_public_text({"script_phrases": [line]})
    assert "absolute_guarantee" not in kinds(result), (line, result["issues"])


@pytest.mark.parametrize(
    "line",
    [
        "Tim'll tell you the same.",
        "As Tim'd say, raise prices.",
        "I think Tim’ll say yes.",
        "Hollis'll agree.",
    ],
)
def test_a_name_with_a_spoken_contraction_is_still_a_name(line):
    result = scan_public_text({"script_phrases": [line]}, participants=["Tim Hollis"])
    assert "participant_name" in kinds(result), line


@pytest.mark.parametrize(
    ("display", "line"),
    [
        ("Tim Hollis - Sales", "Sales went up after the change."),
        ("Tim Hollis - Booking Manager", "Booking a DJ is hard."),
        ("Tim Hollis - Head of Growth", "Head to your calendar."),
        ("Tim Hollis - Head of Growth", "Growth is slow in winter."),
        ("Tim Hollis, VP Sales", "Sales calls are hard."),
        ("Tim Hollis | Wedding DJ | In The Box", "Wedding DJ pricing is hard."),
        ("Tim Hollis (Chicago)", "Chicago winters are slow."),
        ("Tim Hollis (Pro)", "Pro tip: raise prices."),
        ("Tim Hollis - Premier Entertainment", "Premier events are big."),
        ("Anna van der Berg", "Van rentals are pricey."),
    ],
)
def test_a_role_title_or_place_beside_the_name_is_not_a_name(display, line):
    result = scan_public_text({"script_phrases": [line]}, participants=[display])
    assert "participant_name" not in kinds(result), (display, line, result["issues"])
    named = scan_public_text({"script_phrases": ["Tim asked me."]}, participants=[display])
    if display.startswith("Tim"):
        assert "participant_name" in kinds(named), display


def test_two_people_joined_by_a_slash_are_both_looked_for():
    for line in ("Tim asked me about it.", "Sarah asked me about it."):
        result = scan_public_text({"script_phrases": [line]}, participants=["Tim / Sarah"])
        assert "participant_name" in kinds(result), line
