"""'Saved' the storage word is not an outcome (T-22611, 18-Nov).

The claims check rejects any idea whose public words state an outcome without a
measured moment. It read the bare word "saved" as an outcome, so an idea about
saving a record was rejected as an invented result: 22 of the 49 invented_outcome
rejections of the last 45 days named "saved", nearly all in the storage sense. On
18-Nov the same AI news idea (ChatGPT for Sales: "a person approves each one before
anything is sent or saved") died on it three times.

The check must still fail on a real saving claim; the planted outcomes below are the
proof that it can.
"""

from __future__ import annotations

import pytest

from tce.editorial.selector import _OUTCOME_LANGUAGE

# Storage sense, taken from real rejected ideas (wording kept, names removed).
STORAGE = [
    "A person approves each one before anything is sent or saved.",
    "Saved is not the same as confirmed",
    "'Saved successfully' is a claim, not proof",
    "'Saved' isn't done until you open the real thing",
    "Answers were saved where nobody looked.",
    "Read back the saved page settings before you call it live.",
    "He had the agent turn the correction into a saved business rule.",
    "The business had already saved its opening hours and delivery cut-offs.",
    "A client request could be saved and then reach no one.",
    "Update every place staff read them after the order is saved.",
]

# Real saving claims. Each must still be caught.
OUTCOMES = [
    "It saved 40% of admin time",
    "This saved him five hours a week",
    "The new form saved time on every booking",
    "Automating the reminders saved us a weekend",
    "That one change saved the client money",
    "Hours saved every month",
    "It saved them three days of chasing",
    "The checklist saved the deal",
    "One question before I move to goals has saved many conversations",
    "The follow-up saved two clients",
]


@pytest.mark.parametrize("text", STORAGE)
def test_saved_in_the_storage_sense_is_not_an_outcome(text):
    assert _OUTCOME_LANGUAGE.search(text) is None, _OUTCOME_LANGUAGE.search(text)


@pytest.mark.parametrize("text", OUTCOMES)
def test_a_real_saving_claim_is_still_an_outcome(text):
    assert _OUTCOME_LANGUAGE.search(text) is not None
