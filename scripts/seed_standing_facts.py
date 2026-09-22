"""Seed the standing facts: what Kivi Media runs, and what its owners keep bringing.

These are the two anchor kinds a machine cannot derive, and they are the routes
Ziv's 21-Sep correction opened into the third lane: AI is in scope when it makes
sense for the owners he coaches, or when it applies to Kivi Media's clients or
solutions.

WHERE THE PROBLEMS CAME FROM
Not invented, and not asked for. They were read out of the voice corpus on
21-Sep-2026: 7,829 mini speeches, 1,040,181 words, 554 calls, 25 March to 16
September. Five readers went through the whole corpus independently in five
separate two-month slices, and the ranking below is how many of those five
slices found each problem. Four or five means it recurs across six months and
many clients rather than one loud week.

The wording is Ziv's, pulled from how he actually says it on calls. It is
deliberately not tidied into consultant language, because these strings are what
an announcement gets matched against: the words are the mechanism, not the
presentation. Correct them here when he corrects them.

TWO KNOWN LIMITS, RECORDED SO THEY ARE NOT REDISCOVERED AS BUGS
1. Eleven of the twelve are event-owner problems. Only one is coach-specific.
   The settled positioning is coaches first, so this list currently skews the
   lane toward the existing base. Ziv was shown this and can add coach-side
   rows; until he does, that skew is real and intended to be visible.
2. English only. Another 459,791 words across 388 calls are in Hebrew and were
   not read for this. If those calls carry different clients, this list is blind
   to them.

No client names, no company names, no money figures: the write path runs the
public-safety scan at entry and refuses anything specific.

Usage:
    PYTHONPATH=src python scripts/seed_standing_facts.py --dry-run
    PYTHONPATH=src python scripts/seed_standing_facts.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from tce.news.standing import StandingFact, seed_standing_facts

# What Kivi Media runs for clients, in CATEGORIES. A category is what an
# announcement can land on; a client name would be both useless for matching and
# a leak. Derived from the repos with live commit activity, and owed a review by
# Ziv (open question K4 in the plan).
CLIENT_SOLUTIONS = [
    StandingFact(
        "client_solution",
        "an AI receptionist answering a shop's phone",
        "Kivi Media runs voice reception for small retail and service shops, including "
        "the after-hours calls the owner used to take personally.",
    ),
    StandingFact(
        "client_solution",
        "a booking and talent hub for event businesses",
        "Kivi Media runs the enquiry-to-booking system for entertainers, DJs and AV "
        "companies, including quotes, follow-up and the calendar.",
    ),
    StandingFact(
        "client_solution",
        "a coaching CRM that tracks clients between sessions",
        "Kivi Media runs client tracking, check-ins and messaging for coaches, so the "
        "work between sessions is visible rather than remembered.",
    ),
    StandingFact(
        "client_solution",
        "a bridge syncing a client's existing CRM",
        "Kivi Media runs integrations against CRMs the client already pays for, moving "
        "enquiries, bookings and documents without replacing their system.",
    ),
    StandingFact(
        "client_solution",
        "an agency board running marketing work for clients",
        "Kivi Media runs the campaign, content and reporting workflow that its own "
        "delivery team works out of.",
    ),
    StandingFact(
        "client_solution",
        "automated follow-up messaging to a client's leads",
        "Kivi Media runs the sequences that chase enquiries and past customers on the "
        "owner's behalf, across email and messaging apps.",
    ),
]

# The twelve, ordered by how many of the five independent corpus slices found
# each one. The comment on each is the recurrence evidence, kept so nobody
# reorders them on taste later.
CLIENT_PROBLEMS = [
    StandingFact(
        "problem_pattern",
        "they will not raise their price, and they fold the moment someone pushes",
        "A stuck number, often years old, plus pricing off whatever a cheap competitor "
        "publishes and discounting by habit when challenged.",
        "5 of 5 slices, March through September. The most consistent thing in the corpus.",
    ),
    StandingFact(
        "problem_pattern",
        "the owner is the bottleneck and everything waits on them to approve it",
        "Work is finished and sits unsent because one person has to look at it first.",
        "5 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "leads come in, sit there, and nobody ever gets back to them",
        "Enquiries they already paid for going cold, sometimes because a form quietly "
        "broke months earlier.",
        "4 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "it is finished and they still will not put it out",
        "Perfectionism holding a launch hostage over something nobody would notice.",
        "5 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "they never go back to the people who already paid them",
        "No list, no referrals, no reviews, no rebooking, with hundreds of past clients "
        "and no way to reach them.",
        "5 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "they do a handful of reps, get nothing, and decide it does not work",
        "Killing a channel on a sample far too small to tell them anything.",
        "5 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "their website and their quote look cheap next to the work",
        "Thin pages and plain documents arriving after a good first impression, which "
        "shows up later as an argument about price.",
        "4 of 5 slices, April through September.",
    ),
    StandingFact(
        "problem_pattern",
        "they paid for it, it works, and they never switched it on",
        "The system is delivered and operational and nobody started using it.",
        "4 of 5 slices, April through August.",
    ),
    StandingFact(
        "problem_pattern",
        "nobody picks up the phone once the office closes",
        "Calls dying in voicemail after hours, or nobody free to answer during them.",
        "3 of 5 slices, May through September.",
    ),
    StandingFact(
        "problem_pattern",
        "they have no decent photos or video of their own work",
        "The proof on the page is small, dark or missing entirely.",
        "4 of 5 slices, April through September.",
    ),
    StandingFact(
        "problem_pattern",
        "they cannot hire or keep anyone, so it all lands back on the owner",
        "Interviews drag, the seat stays empty, and work is taken back because it was "
        "not done the owner's way.",
        "4 of 5 slices, March through September.",
    ),
    StandingFact(
        "problem_pattern",
        "the coach's teaching model has stopped selling, and selling feels dirty to them",
        "Nobody wants the course, the ebook or the email sequence any more, and the "
        "coach is unwilling to sell the thing that would replace it.",
        "4 of 5 slices, May through September. The only strongly coach-specific one.",
    ),
]

ALL_FACTS = CLIENT_SOLUTIONS + CLIENT_PROBLEMS


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print, write nothing",
    )
    parser.add_argument("--workspace", default=os.environ.get("TCE_EDITOR_DEFAULT_WORKSPACE_ID"))
    args = parser.parse_args()

    by_kind: dict[str, int] = {}
    for fact in ALL_FACTS:
        fact.validate()  # raises with a readable reason
        by_kind[fact.anchor_kind] = by_kind.get(fact.anchor_kind, 0) + 1

    print(f"{len(ALL_FACTS)} standing facts validated: " + ", ".join(
        f"{k} {v}" for k, v in sorted(by_kind.items())
    ))
    for fact in ALL_FACTS:
        print(f"  [{fact.anchor_kind}] {fact.anchor_term}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    if not args.workspace:
        print(
            "\nNo workspace. Pass --workspace or set TCE_EDITOR_DEFAULT_WORKSPACE_ID.",
            file=sys.stderr,
        )
        return 2

    from tce.db.session import async_session

    async with async_session() as session:
        result = await seed_standing_facts(session, args.workspace, ALL_FACTS)
        await session.commit()
    print("\n" + result["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
