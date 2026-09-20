"""The idea list must not show the same lesson twice.

Every idea below is a real row from Ziv's live list on 20-Sep-2026. The pair he
complained about is in there, and so is every idea that merely sounds adjacent to
another one - because the cost of a false positive is an idea he never sees.
"""

from __future__ import annotations

from tce.editorial import dedupe

# The pair he reported: two runs, two weeks, one lesson.
BLAME = {
    "title": "Before you blame the marketing, find the stage where people actually drop off",
    "lesson": (
        "When sales are low, check conversion at each step separately (page to sign-up, "
        "sign-up to sale). If a healthy share of visitors sign up but very few sign-ups "
        "buy, the marketing is doing its job and the fix belongs to the next stage."
    ),
}
LEAK = {
    "title": "Before you fix the marketing, find the stage that is actually leaking",
    "lesson": (
        "Check conversion at each stage of the funnel separately. If a healthy share of "
        "page visitors sign up for the webinar but very few sign-ups buy, the bottleneck "
        "is after the sign-up, not in the ads, even though the ads are what gets blamed."
    ),
}

# The rest of the live list, including the pairs that share an opening or a subject
# and are nonetheless different ideas.
OTHERS = [
    {
        "title": "Before you give your team AI accounts, decide how they run out.",
        "lesson": (
            "Set a hard ceiling before you hand AI to the team: turn off pay-as-you-go "
            "extra usage on every account so the worst case is hitting a limit, not a "
            "surprise bill."
        ),
    },
    {
        "title": "Before you hand over the phone, decide what happens when the AI goes down.",
        "lesson": (
            "Ask about the failure path before celebrating the demo: transfer, voicemail "
            "and visible follow-up are part of the service."
        ),
    },
    {
        "title": "Make your AI prove it, not tell you",
        "lesson": (
            "Do not accept 'it's done' from an AI agent. Build a proof step into the "
            "process: after any change, the agent opens the real system, tests the change "
            "and shows you screenshots."
        ),
    },
    {
        "title": "Your AI should know the difference between 'I will' and 'I did.'",
        "lesson": (
            "A coaching tool can report progress that never happened if it mistakes a plan "
            "for completed work; preserve that distinction so the coach can trust the "
            "summary."
        ),
    },
    {
        "title": "Your AI knows your industry. It does not know your business.",
        "lesson": (
            "Treat a new AI assistant exactly like a new hire on day one: it may know the "
            "general trade, but it does not know your prices, your rules or how you sound "
            "in writing."
        ),
    },
    {
        "title": "The four jobs behind a one-person service business",
        "lesson": (
            "Split your business into four jobs - marketing, sales you actually track, "
            "delivery, and keeping past clients - and work on the weakest one."
        ),
    },
    {
        "title": "If the leads are cheap and converting, would you double the spend?",
        "lesson": (
            "When the lead numbers say the marketing machine is working, ask the owner "
            "whether they would double the budget tomorrow; the hesitation tells you where "
            "the real constraint sits."
        ),
    },
    {
        "title": "Your minimum price belongs in your own file, not in the document you hand out",
        "lesson": (
            "Keep your floor price internal and replace it in the outgoing document with an "
            "invitation to talk when the budget is tight."
        ),
    },
    {
        "title": "Put the follow-up call inside the deal, not in a favour you ask for later",
        "lesson": (
            "Decide how you work with a client at the moment of closing: one short page "
            "naming the prep call, the job itself, and a follow-up call after it."
        ),
    },
    {
        "title": "A differentiator is something you do, not something you say",
        "lesson": (
            "Take the one thing customers quietly fear about your category and answer it "
            "with a mechanism they can picture."
        ),
    },
    {
        "title": "The client told you exactly what they wanted. Build that first.",
        "lesson": (
            "When a client asks for something in a specific form, deliver it in that form "
            "before you offer your better idea."
        ),
    },
    {
        "title": "Event ads: open with the experience they want, not the problem they have.",
        "lesson": (
            "The first line of an event ad has to tell the reader it is for them and "
            "describe the memorable experience they want."
        ),
    },
    {
        "title": "Your homepage has one job: show what you offer in one glance.",
        "lesson": (
            "On a service business homepage, visitors want to see all your core services at "
            "the same time, side by side, in plain words."
        ),
    },
    {
        "title": "Selling is the first step of the transformation, not a detour from it",
        "lesson": (
            "Coaches resist selling because they picture the salesperson as sneaky; the fix "
            "is closing that identity gap."
        ),
    },
    {
        "title": "You ask your clients to be coachable. Are you coachable about selling?",
        "lesson": (
            "Apply the openness you expect from your own clients to learning how to invite "
            "someone to work with you."
        ),
    },
    {
        "title": "Good results will not save a bad relationship",
        "lesson": (
            "When a client asks for something small, listen for the need underneath it: a "
            "request to see work before it goes out is usually a request for control."
        ),
    },
    {
        "title": "You fixed it in minutes. The client thinks you ignored him.",
        "lesson": (
            "When a client gives you a correction, the damage is in the silence afterwards. "
            "Close the loop twice."
        ),
    },
    {
        "title": "Your assistant drafts. You send. Urgency doesn't change that.",
        "lesson": (
            "When you delegate client communication, the deliverable is a draft plus the "
            "reason behind it, handed to you. Only the owner authorizes what reaches a "
            "client."
        ),
    },
    {
        "title": "If your client did not read your update, the update is the problem",
        "lesson": (
            "When a client admits they have not read your progress updates, do not fix the "
            "client, fix the update."
        ),
    },
    {
        "title": "When a client trips over your wording, ask what they would call it",
        "lesson": (
            "When a client hesitates over a word you chose, stop defending the choice and "
            "ask them what they would call it instead."
        ),
    },
]


def test_the_pair_he_reported_is_caught():
    hit = dedupe.find_duplicate(LEAK, [*OTHERS, BLAME])
    assert hit is not None
    row, score = hit
    assert row["title"] == BLAME["title"]
    assert score.repeat
    assert "already on the list" in score.reason(row["title"])
    assert BLAME["title"] in score.reason(row["title"])


def test_it_is_caught_from_either_side():
    assert dedupe.find_duplicate(BLAME, [LEAK]) is not None


def test_nothing_else_on_the_live_list_is_called_a_repeat():
    # Each real idea against every other real idea: exactly zero flags. An idea
    # wrongly dropped is an idea he never gets offered, so this is the test that
    # sets the thresholds.
    for i, idea in enumerate(OTHERS):
        others = OTHERS[:i] + OTHERS[i + 1 :]
        hit = dedupe.find_duplicate(idea, others)
        assert hit is None, f"{idea['title']!r} was wrongly called a repeat of {hit and hit[0]}"


def test_two_ideas_that_share_only_an_opening_are_different_ideas():
    # "Before you give your team AI accounts..." and "Before you hand over the
    # phone..." both open the same way and both mention AI. They teach nothing
    # alike, and the opening must not be what decides it.
    accounts = next(o for o in OTHERS if "AI accounts" in o["title"])
    phone = next(o for o in OTHERS if "hand over the phone" in o["title"])
    assert not dedupe.compare(
        accounts["title"], accounts["lesson"], phone["title"], phone["lesson"]
    ).repeat


def test_an_idea_is_not_a_repeat_of_itself_when_the_list_is_empty():
    assert dedupe.find_duplicate(BLAME, []) is None


def test_the_closest_match_is_the_one_reported():
    # Two rows would both flag; he should be told about the one he would recognise.
    near = dict(BLAME)
    weaker = {
        "title": "Before you fix the marketing, look at the stage",
        "lesson": BLAME["lesson"],
    }
    hit = dedupe.find_duplicate(LEAK, [weaker, near])
    assert hit is not None and hit[0]["title"] == BLAME["title"]


def test_two_short_titles_sharing_one_word_are_not_a_repeat():
    # A ratio alone calls these identical: one shared word out of two each.
    a = {"title": "Weakest of the three", "lesson": "Work on the weakest job."}
    b = {"title": "Strongest of the three", "lesson": "Lean on the strongest job."}
    assert dedupe.compare(a["title"], a["lesson"], b["title"], b["lesson"]).title >= 0.5
    assert dedupe.find_duplicate(a, [b]) is None


def test_stop_words_alone_never_make_a_repeat():
    a = {"title": "You should do the thing", "lesson": "It is what you do."}
    b = {"title": "You should do the other", "lesson": "It is what they do."}
    assert dedupe.find_duplicate(a, [b]) is None


def test_orm_style_rows_work_too():
    class Row:
        title = BLAME["title"]
        lesson = BLAME["lesson"]

    assert dedupe.find_duplicate(LEAK, [Row()]) is not None


def test_empty_or_missing_text_is_never_a_repeat():
    assert dedupe.find_duplicate({"title": "", "lesson": ""}, [BLAME]) is None
    assert dedupe.find_duplicate({}, [BLAME]) is None
