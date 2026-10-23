# ruff: noqa: E501 - the seed data (teaching lines, prompts) reads better unwrapped
"""Seed Connie Kadansky's three idea lanes (the `sales_coach` lane profile).

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  from_teaching  her own published pages and posts on exceptionalsales.com
                         (stored as curated_clip, the page's URL is the citation)
  lane B  practice_room  prompts about what she sees when people practice, questions
                         she answers from her own memory (story_seed)
  lane C  in_the_wild    negotiation in the news: sports, labor, business and pricing
                         feeds, plus standing facts about her work as the anchors

Also: the workspace strategy (English, replaces the owner strategy file) and
videos_per_week 3. Her creator, voice and brand profiles are seeded by SQL
(scripts/seed_connie_profiles.sql): those models carry no workspace column.

The three pillars are Ziv's (22-Oct-2026), run past Connie by email on 23-Oct with
5 ideas each ("15 video ideas for you to react to").

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python scripts/seed_connie_lanes.py                 # dry run
    PYTHONPATH=src python scripts/seed_connie_lanes.py --check         # fetch every feed and page
    PYTHONPATH=src python scripts/seed_connie_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python scripts/seed_connie_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime

CONNIE_WORKSPACE = "7247b8fa-d627-4357-b6e8-ca2a26cd4b14"
AUTHOR = "connie-lanes-seed"
VIDEOS_PER_WEEK = 3
TIMEZONE = "America/Phoenix"

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# Content strategy - Connie Kadansky, Exceptional Sales Performance

## Who it speaks to
Salespeople, sales managers and sales leaders, and coaches and consultants who sell \
their own services. People who know what to say on a call but hesitate to say it.

## Three lanes, 15 ideas a week (5 in each)
At least 3 videos recorded a week. More is welcome.

1. **From your teaching** (5 a week): one idea from Connie's own published teaching \
(Sales Call Reluctance, the Yielder, pleasing or leading, counterfeit yeses, \
prospecting without fear), said simply, the way she would tell a friend.
2. **From the practice room** (5 a week): what she sees when people practice, in her \
coaching and in the Dojo. Each idea is a question she answers from her own memory. \
Never an invented story.
3. **Negotiation in the wild** (5 a week): a real negotiation in the news (sports \
contracts, labor deals, business deals, price wars, a viral customer moment) and what \
it teaches a rep on a sales call. No politics, elections, war, crime or tragedy.

## Voice
Plain, warm, direct American English. Short sentences, like a friendly chat over \
coffee with a busy person, never a lecture. Her words: pleasing or leading, Sales Call \
Reluctance, the Yielder, name the feeling, sum it up, ask what or how, respectful \
tension, counterfeit yes.

## Never
- Invent stories, reps, clients, quotes or numbers.
- Name clients, their companies or their reps.
- Use Chris Voss's brand terms as hers (use her words instead).
- Her own fees or pricing.
- A call to action ("book a call", "DM me", "link in bio").
- Politics, elections, war, crime, tragedy.
"""

# --------------------------------------------------------------------------- lane C

# (name, url, kind, tier, vendor). Each answered and parsed on 23-Oct-2026
# (scripts/seed_connie_lanes.py --check). Tier 1b: citable trade and news press.
FEEDS: list[tuple[str, str, str, str, str | None]] = [
    ("Harvard PON negotiation blog", "https://www.pon.harvard.edu/feed/", "rss", "1b", "pon"),
    ("Front Office Sports (sports business)", "https://frontofficesports.com/feed/", "rss", "1b",
     "front office sports"),
    ("ESPN NBA", "https://www.espn.com/espn/rss/nba/news", "rss", "1b", "espn"),
    ("ESPN NFL", "https://www.espn.com/espn/rss/nfl/news", "rss", "1b", "espn"),
    ("ESPN MLB", "https://www.espn.com/espn/rss/mlb/news", "rss", "1b", "espn"),
    ("HR Dive (labor and pay)", "https://www.hrdive.com/feeds/news/", "rss", "1b", "hr dive"),
    ("Retail Dive (pricing and suppliers)", "https://www.retaildive.com/feeds/news/", "rss", "1b",
     "retail dive"),
    ("NPR Business", "https://feeds.npr.org/1006/rss.xml", "rss", "1b", "npr"),
    ("Fast Company", "https://www.fastcompany.com/latest/rss", "rss", "1b", "fast company"),
]

RETIRED_FEEDS: dict[str, str] = {}


def retire_feeds(existing: dict) -> list[str]:
    """Switch off every enabled feed of the workspace that RETIRED_FEEDS names."""
    out = []
    for url, feed in existing.items():
        if url in RETIRED_FEEDS and getattr(feed, "enabled", False):
            feed.enabled = False
            out.append(feed.name)
    return out


# The anchors for lane C, in categories, never client names. (anchor_kind, anchor_term,
# lesson). The full matching list is docs/news-anchors-sales-coach.md.
STANDING_FACTS: list[tuple[str, str, str]] = [
    ("client_solution", "sales call reluctance", "Connie coaches salespeople past Sales Call Reluctance, the emotional hesitation to prospect and self-promote."),
    ("client_solution", "negotiation", "Connie teaches salespeople to negotiate on a sales call: name the feeling, sum it up, ask what or how."),
    ("client_solution", "sales coaching", "Connie coaches salespeople, sales managers and coaches, one on one and in groups."),
    ("client_solution", "prospecting", "Connie helps salespeople prospect every week without fear of rejection."),
    ("client_solution", "contract talks", "Real contract talks show reps how a leader handles tension instead of pleasing the other side."),
    ("problem_pattern", "discount", "Pleasers discount to keep the buyer comfortable instead of getting curious about what is underneath."),
    ("problem_pattern", "price", "Buyers push back on price; a leader asks what they are comparing it with."),
    ("problem_pattern", "deadline", "A decision with no real deadline drifts."),
    ("problem_pattern", "walk away", "A rep who can walk away negotiates differently from one who needs the deal."),
    ("problem_pattern", "counteroffer", "A counteroffer is a moment to get curious, not to give in."),
    ("problem_pattern", "on hold", "When a buyer puts a deal on hold, it is a move in the negotiation, not the end."),
    ("problem_pattern", "customer service", "A calm reply to an upset customer shows naming the feeling under pressure."),
]

# --------------------------------------------------------------------------- lane A

# (key, title, url, lesson). Her own pages on exceptionalsales.com: each answered 200
# on 23-Oct-2026, and the title and lesson come from the page's own title and summary.
TEACHING: list[tuple[str, str, str, str]] = [
    ("what-is-scr", "What is Sales Call Reluctance?",
     "https://exceptionalsales.com/what-is-sales-call-reluctance/",
     "Sales Call Reluctance is an emotional hesitation to prospect and promote, despite having the skills, knowledge and incentives to do so. It is not incompetence."),
    ("scr-nothing-embarrassing", "Sales Call Reluctance is nothing to be embarrassed about",
     "https://exceptionalsales.com/sales-call-reluctance-nothing-embarrassed-living-needlessly/",
     "Sales Call Reluctance is nothing to be embarrassed about. Allowing it to persist needlessly is."),
    ("scr-self-promotion", "Sales Call Reluctance is fear of self-promotion at the core",
     "https://exceptionalsales.com/sales-call-reluctance-is-fear-of-self-promotion-at-the-core/",
     "At its core, call reluctance is a fear of self-promotion: the job is to get your ask in gear."),
    ("yielder-costly", "Yielder Call Reluctance is very costly",
     "https://exceptionalsales.com/yielder-call-reluctance-is-very-costly/",
     "Wanting to be liked is a learned behavior, so a salesperson can unlearn it with conscious effort and good coaching."),
    ("counterfeit-yes", "How to stop getting counterfeit yeses from prospects",
     "https://exceptionalsales.com/how-to-stop-getting-counterfeit-yeses-from-prospects/",
     "A rep leaves a great first meeting feeling positive, then gets no-shows and last-minute cancels at the second one: the first yes was counterfeit."),
    ("too-nice", "Are you too nice to close the deal?",
     "https://exceptionalsales.com/nice-close-deal/",
     "Reps who are afraid to look pushy or to stir up conflict skip the discovery questions, and the deal does not close."),
    ("managers-contaminate", "Are you contaminating your salespeople with Sales Call Reluctance?",
     "https://exceptionalsales.com/sales-managers-are-you-contaminating-your-salespeople-with-sales-call-reluctance/",
     "A sales manager whose salespeople hesitate to prospect should check whether the manager has Sales Call Reluctance too."),
    ("biggest-carriers", "Who are the biggest carriers of Sales Call Reluctance?",
     "https://exceptionalsales.com/ever-wonder-who-are-the-biggest-carriers-of-sales-call-reluctance/",
     "According to George Dudley and Shannon Goodson, the biggest carriers of Sales Call Reluctance are sales trainers and sales managers."),
    ("stop-fibbing", "Stop fibbing to prospects!",
     "https://exceptionalsales.com/stop-fibbing-to-prospects/",
     "Build a selling proposition that says your real value, and say it with confidence, so there is nothing to fib about."),
    ("gloss-over", "Do you gloss over what prospects say?",
     "https://exceptionalsales.com/do-you-gloss-over-what-prospects-say-and-it-comes-back-to-haunt-you-later/",
     "Gliding past what a prospect says comes back to haunt the rep later: listen, and ask a better question."),
    ("strategic-questions", "Forget what to say, focus on what strategic questions you can ask",
     "https://exceptionalsales.com/forget-about-what-to-say-and-focus-on-what-strategic-questions-can-i-ask/",
     "Stop scripting what to say; plan the strategic questions you can ask instead."),
    ("anticipatory-anxiety", "Anticipatory anxiety: the invisible barrier in sales prospecting",
     "https://exceptionalsales.com/anticipatory-anxiety-the-invisible-barrier-in-sales-prospecting/",
     "The dread a salesperson feels before a prospecting call is an invisible barrier, and Sales Call Reluctance costs big bucks."),
    ("decision-fatigue", "Prospects have decision fatigue",
     "https://exceptionalsales.com/prospects-have-decision-fatigue-how-can-you-guide-them-to-solutions/",
     "When a prospect's decisions get worse from mental exhaustion, the rep's job is to guide them to a solution."),
    ("values-conflict", "Are you call reluctant, or are your values in conflict?",
     "https://exceptionalsales.com/are-you-call-reluctant-or-are-your-values-in-conflict-in-some-way/",
     "Sometimes a rep hesitates to prospect because they doubt the product or the service behind it, not because of call reluctance."),
    ("stop-fooling-yourself", "Stop fooling yourself: your prospect knows you are a salesperson",
     "https://exceptionalsales.com/stop-fooling-yourself-your-prospect-knows-that-you-are-a-salesperson/",
     "Reconnect with your value and the benefits you bring, and shift how you see selling, instead of hiding that you sell."),
    ("role-play", "Role play, role play, role play",
     "https://exceptionalsales.com/want-to-improve-your-sales-role-play-role-play-role-play/",
     "To become a top salesperson, practice out loud: role play, role play, role play."),
    ("master-negotiation", "Unlock your potential: negotiation in sales",
     "https://exceptionalsales.com/unlock-your-potential-master-negotiation/",
     "Negotiation techniques from several negotiation experts, brought into everyday sales conversations."),
    ("inner-critic", "Tips for overcoming Sales Call Reluctance",
     "https://exceptionalsales.com/services/workshop-training/sales-call-reluctance-faq/",
     "A powerful technique to overcome call reluctance is to capture what the self-critical inner voice is saying to you."),
]

# --------------------------------------------------------------------------- lane B

# Practice-room SEEDS: questions she answers from her own memory, never events.
STORY_SEEDS: list[tuple[str, str]] = [
    ("read-the-book-froze", "Think of someone who had read the negotiation book but froze the first time they had to name a feeling out loud. What happened, and what did you tell them?"),
    ("first-habit", "When someone practices with you for the first time, what is the first habit you notice that keeps them pleasing the prospect?"),
    ("dont-want-to-bother", "Think of a rep who said 'I don't want to bother them.' What was really underneath it, and how did you help them see it?"),
    ("too-expensive-reply", "In practice, what does a rep usually say right after a buyer says 'That's too expensive'? What do you wish they said instead?"),
    ("feeling-landed", "Think of a practice moment when a rep finally named the feeling and the buyer opened up. What changed in the rep's voice?"),
    ("easy-until-out-loud", "Which skill do reps think is easy until they have to do it out loud? Why do you think that is?"),
    ("manager-carrier", "Think of a sales manager you coached who carried call reluctance without knowing it. How did it show up in the team?"),
    ("counterfeit-yes-practice", "What counterfeit yes do reps fall for most often in practice, and how do you help them hear it?"),
    ("discount-reflex", "Think of a rep who offered a discount the moment a buyer pushed back. What do you think they were protecting?"),
    ("the-pause", "What happens the first time you ask someone to pause after they name the feeling? What do they do with the silence?"),
    ("one-skill-week", "Think of someone whose practice changed after a week of working on only one skill. What did you notice?"),
    ("polite-giveaway", "Which polite line do you hear reps use that quietly gives the call away? Why do they reach for it?"),
    ("practice-feels-fake", "Think of someone who said practice felt fake. What changed their mind?"),
    ("pleaser-to-leader", "Think of a rep who made the switch from pleasing to leading. What was the first sign you saw?"),
    ("coach-asking", "Think of a coach who sells their own services and found it hard to ask for the business. What made it hard for them?"),
    ("send-me-something", "When a rep tells you 'They said send me something, so it went well,' what question do you ask them?"),
]


# --------------------------------------------------------------------------- building


def lane_items() -> list:
    from tce.editorial.lane_seeds import LaneItem

    items = [
        LaneItem(
            kind="curated_clip",
            key=key,
            title=title,
            lesson=lesson,
            url=url,
            language="en",
            meta={"teaching_page": True, "site": "exceptionalsales.com"},
        )
        for key, title, url, lesson in TEACHING
    ]
    items += [
        LaneItem(
            kind="story_seed",
            key=key,
            title=question[:120],
            lesson=question,
            language="en",
            meta={"seed": True, "she_fills_in": True},
        )
        for key, question in STORY_SEEDS
    ]
    return items


def standing_facts() -> list:
    from tce.news.standing import StandingFact

    return [StandingFact(anchor_kind=k, anchor_term=t, lesson=lesson) for k, t, lesson in STANDING_FACTS]


def validate_all() -> None:
    from tce.news.feeds import is_blocked_host

    for name, url, _k, _t, _v in FEEDS:
        if is_blocked_host(url):
            raise SystemExit(f"refusing a blocked host: {name} ({url})")
    for item in lane_items():
        item.validate()
    for fact in standing_facts():
        fact.validate()
    if not STRATEGY_MD.startswith("<!-- tce-strategy: replace -->"):
        raise SystemExit("the strategy must replace the owner strategy file")


def print_plan(ws: str) -> None:
    print(f"workspace {ws}")
    print("\n[workspace_strategies] 1 row, replaces the owner strategy file "
          f"({len(STRATEGY_MD)} chars, English)")
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane C, in_the_wild)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane C anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:24} {lesson}")
    print(f"\n[curated_clip] {len(TEACHING)} teaching pages (lane A, from_teaching)")
    for _key, title, url, _lesson in TEACHING:
        print(f"  {title}  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} prompts (lane B, practice_room)")
    for key, question in STORY_SEEDS:
        print(f"  {key:24} {question}")
    print(f"\n[editorial_settings] videos_per_week -> {VIDEOS_PER_WEEK}")


def print_live_steps(ws: str) -> None:
    print("\nAfter --apply, create the schedules through the API (not SQL), as ziv on the VPS:")
    for name, cadence, at, final in (
        ("weekly-content", "weekly", "07:30", "drafting"),
        ("daily-evidence", "daily", "07:15", "extracting"),
    ):
        body = (
            f'{{"enabled":true,"cadence":"{cadence}","weekday":0,"local_time":"{at}",'
            f'"timezone":"{TIMEZONE}","catchup_days":7,"final_stage":"{final}","window_days":7}}'
        )
        print(
            f"  curl -s -X PUT http://127.0.0.1:8200/api/v1/content-runs/schedule/{name} "
            f'-H "Authorization: Bearer $TCE_PRIVATE_ACCESS_KEY" -H "X-Workspace-Id: {ws}" '
            f"-H 'Content-Type: application/json' -d '{body}'"
        )
    print(f"  PYTHONPATH=src python scripts/build_anchor_index.py --workspace {ws} --dry-run")


# --------------------------------------------------------------------------- network


async def check_network() -> int:
    import httpx

    from tce.news.feeds import parse_feed

    bad = 0
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers={"user-agent": "tce-news/1.0"}
    ) as client:
        for name, url, kind, tier, _v in FEEDS:
            try:
                r = await client.get(url)
                items = parse_feed(kind, r.text) if r.status_code < 400 else []
            except Exception as exc:  # noqa: BLE001 - report every failure, keep going
                print(f"  FAIL  feed {name}: {type(exc).__name__}")
                bad += 1
                continue
            if r.status_code >= 400 or not items:
                print(f"  FAIL  feed {name}: HTTP {r.status_code}, {len(items)} items")
                bad += 1
                continue
            print(f"  ok    feed [{tier}] {name}: HTTP {r.status_code}, {len(items)} items | "
                  f"{items[0].title[:60]}")
        for _key, title, url, _lesson in TEACHING:
            try:
                r = await client.get(url, headers={"user-agent": "Mozilla/5.0"})
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL  page {title}: {type(exc).__name__}")
                bad += 1
                continue
            if r.status_code != 200:
                print(f"  FAIL  page {title}: HTTP {r.status_code}")
                bad += 1
                continue
            print(f"  ok    page {title}: HTTP 200")
    total = len(FEEDS) + len(TEACHING)
    print(f"\n{total - bad}/{total} feeds and pages answered")
    return 1 if bad else 0


# --------------------------------------------------------------------------- sample


def _rotation(key: str, week: str) -> str:
    return hashlib.sha256(f"{week}:{key}".encode()).hexdigest()


async def sample_week(network: bool) -> None:
    """The evidence a coming week would draw on, per lane. Not the model's ideas:
    those need the subscription worker (the live LLM queue), which this never calls."""
    from tce.editorial.common import current_week_start
    from tce.editorial.lane_profile import SALES_COACH

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in SALES_COACH.lanes))
    pages = sorted(TEACHING, key=lambda c: _rotation(c[0], week))[: SALES_COACH.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: SALES_COACH.reserve_per_lane]
    if network:
        import httpx

        from tce.news.feeds import parse_feed

        terms = [t.lower() for _k, t, _l in STANDING_FACTS] + [
            "negotiat", "contract", "extension", "holdout", "tentative agreement", "strike",
            "offer", "price cut", "discount", "deal",
        ]
        found = []
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                     headers={"user-agent": "tce-news/1.0"}) as client:
            for name, url, kind, _t, _v in FEEDS:
                try:
                    r = await client.get(url)
                    items = parse_feed(kind, r.text)
                except Exception:  # noqa: BLE001
                    continue
                for it in items[:20]:
                    text = f"{it.title} {getattr(it, 'summary', '') or ''}".lower()
                    hits = [t for t in terms if t in text]
                    if hits:
                        found.append((len(hits), name, it.title, hits[:3]))
        found.sort(reverse=True)
        print("\nC in_the_wild - recent feed items that touch her anchors (top 10; the "
              "matcher and the gates decide):")
        for _n, name, title, hits in found[:10]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nC in_the_wild - add --network to read the feeds")
    print(f"\nA from_teaching - {len(pages)} pages rotated in this week:")
    for _key, title, url, lesson in pages:
        print(f"  {title} {url}\n      {lesson}")
    print(f"\nB practice_room - {len(seeds)} prompts rotated in this week:")
    for _key, question in seeds:
        print(f"  {question}")


# --------------------------------------------------------------------------- write


async def apply(ws_text: str) -> None:
    from sqlalchemy import select

    from tce.db.session import async_session
    from tce.editorial import lineup
    from tce.editorial.lane_seeds import seed_lane_items
    from tce.models.news import NewsFeed
    from tce.models.workspace_context import WorkspaceStrategy
    from tce.news.standing import seed_standing_facts

    ws = uuid.UUID(ws_text)
    now = datetime.now(UTC).replace(tzinfo=None)
    async with async_session() as session:
        row = (
            await session.execute(select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == ws))
        ).scalar_one_or_none()
        if row is None:
            session.add(WorkspaceStrategy(workspace_id=ws, markdown=STRATEGY_MD,
                                          label="Connie sales coach lanes"))
            print("strategy: written")
        elif row.markdown == STRATEGY_MD:
            print("strategy: unchanged")
        else:
            row.markdown = STRATEGY_MD
            print("strategy: updated")

        existing = {
            f.url: f
            for f in (await session.execute(select(NewsFeed).where(NewsFeed.workspace_id == ws))).scalars()
        }
        added = changed = 0
        for name, url, kind, tier, vendor in FEEDS:
            f = existing.get(url)
            if f is None:
                session.add(NewsFeed(id=uuid.uuid4(), workspace_id=ws, name=name, url=url,
                                     kind=kind, tier=tier, vendor=vendor, enabled=True))
                added += 1
            elif (f.name, f.kind, f.tier, f.vendor) != (name, kind, tier, vendor):
                f.name, f.kind, f.tier, f.vendor = name, kind, tier, vendor
                changed += 1
        print(f"feeds: {added} added, {changed} updated, "
              f"{len(FEEDS) - added - changed} unchanged")
        retired = retire_feeds(existing)
        print(f"retired feeds switched off: {', '.join(retired) if retired else 'none'}")

        facts = await seed_standing_facts(session, ws, standing_facts(), author=AUTHOR, now=now)
        print(f"standing facts: {facts['detail']}")
        counts = await seed_lane_items(session, ws, lane_items(), author=AUTHOR, now=now)
        print(f"teaching pages and prompts: {counts}")
        await session.commit()

        settings_row_count = await lineup.set_videos_per_week(session, ws, VIDEOS_PER_WEEK)
        await session.commit()
        print(f"videos_per_week: {VIDEOS_PER_WEEK} ({settings_row_count})")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=CONNIE_WORKSPACE)
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="the default; kept explicit")
    parser.add_argument("--check", action="store_true", help="fetch every feed and page")
    parser.add_argument("--sample-week", action="store_true")
    parser.add_argument("--network", action="store_true", help="with --sample-week: read feeds")
    args = parser.parse_args()
    uuid.UUID(args.workspace)
    validate_all()

    if args.check:
        return await check_network()
    if args.sample_week:
        await sample_week(args.network)
        return 0
    print_plan(args.workspace)
    if not args.apply or args.dry_run:
        print("\ndry run: nothing written (pass --apply to write)")
        print_live_steps(args.workspace)
        return 0
    await apply(args.workspace)
    print_live_steps(args.workspace)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
