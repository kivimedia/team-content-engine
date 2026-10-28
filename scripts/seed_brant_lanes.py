# ruff: noqa: E501 - the seed data (history lines, prompts) reads better unwrapped
"""Seed Brant Matthews's three idea lanes (the `fire_performer` lane profile).

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  sacred_flame     real myths, rituals and moments in the history of fire
                           (stored as curated_clip, the page's URL is the citation)
  lane B  keeper_of_flame  prompts from his 30 years as a fire performer, questions
                           he answers from his own memory (story_seed)
  lane C  taming_fire      records, stunts and daredevil feats in the news, plus
                           standing facts about his own record and shows as anchors

Also: the workspace strategy (English, replaces the owner strategy file) and
videos_per_week 3. His creator, voice and brand profiles are seeded by SQL
(scripts/seed_brant_profiles.sql): those models carry no workspace column.

The three pillars are Brant's own, chosen on his 21-Oct-2026 call with Ziv: the
sacred flame (the history of fire, myths and rituals), keeper of the flame (his 30
years of performing) and taming the fire (danger mastery, other number ones). His
facts come from his confirmed KM Hub business facts (Fire Guy Show).

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python scripts/seed_brant_lanes.py                 # dry run
    PYTHONPATH=src python scripts/seed_brant_lanes.py --check         # fetch every feed and page
    PYTHONPATH=src python scripts/seed_brant_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python scripts/seed_brant_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime

BRANT_WORKSPACE = "3844285d-f119-47e9-98e4-5691f0cbdb4b"
AUTHOR = "brant-lanes-seed"
VIDEOS_PER_WEEK = 3
TIMEZONE = "America/Toronto"
# Wikipedia answers a bare browser user agent from a datacenter with 403s; its policy
# asks for a named one.
PAGE_USER_AGENT = "TCE-seed/1.0 (https://kivimedia.co)"

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# Content strategy - Brant Matthews, the Fire Guy (Fire Guy Show)

## Who it speaks to
People who book live entertainment (wedding planners, festival and fair organizers, \
event and motorsport producers) and fans of fire, circus and daredevil feats.

## Three lanes, 15 ideas a week (5 in each)
At least 3 videos recorded a week. More is welcome. Walking and talking in different \
places, 2 to 3 minutes once edited.

1. **The Sacred Flame** (5 a week): what fire has meant to people. A real myth, ritual \
or moment in the history of fire, told simply, then his take as a fire performer.
2. **Keeper of the Flame** (5 a week): his 30 years of performing with fire. Each idea \
is a question he answers from his own memory. Never an invented story.
3. **Taming the Fire** (5 a week): other number ones. A real record, stunt or feat of \
danger mastery in the news and his take as a Guinness World Record holder: the control \
and the preparation behind it.

## Voice
Punchy and a little funny. Lead with the fire. Short sentences, concrete images over \
adjectives: what burns, what spins, what the crowd does. Confident without boasting: \
the record is a fact, so say it once, plainly. Keep it simple.

## Never
- Invent stories, shows, crowds, quotes or numbers.
- Teach how to do a fire or danger stunt, or dare anyone to try one.
- A death, an injury or a disaster as the subject. Politics, war, crime.
- Name clients, the venues that book him or their guests.
- Prices or fees.
- A call to action ("book me", "DM me", "link in bio").
- Gravity and other topics with no fire or danger in them.
"""

# --------------------------------------------------------------------------- lane C

# (name, url, kind, tier, vendor). Each answered and parsed on 28-Oct-2026
# (scripts/seed_brant_lanes.py --check). Tier 1b: citable news. The Bing News feeds
# link through a click tracker; feeds.unwrap_click_tracker turns each link into the
# article itself. Bing ranks by relevance unless asked for date order (`qft=
# sortbydate="1"`): ranked, 1 of 35 items was inside the 48-hour news window on
# 28-Oct; date-ordered, 20.
_BING_BY_DATE = "&format=rss&qft=sortbydate%3d%221%22"
FEEDS: list[tuple[str, str, str, str, str | None]] = [
    ("UPI Odd News (records and feats)", "https://rss.upi.com/news/odd_news.rss", "rss", "1b", "upi"),
    # The quoted "Guinness World Records" stayed weeks old even date-ordered; this one did not.
    ("Bing News: Guinness record breaks",
     f"https://www.bing.com/news/search?q=guinness+record+breaks{_BING_BY_DATE}", "rss", "1b",
     "bing news"),
    ("Bing News: daredevil stunts",
     f"https://www.bing.com/news/search?q=daredevil+stunt{_BING_BY_DATE}", "rss", "1b", "bing news"),
    # 28-Oct: the quoted phrase "world record attempt" answered 0 items; unquoted, 7.
    ("Bing News: world record attempts",
     f"https://www.bing.com/news/search?q=world+record+attempt{_BING_BY_DATE}", "rss", "1b",
     "bing news"),
    ("Bing News: world record stunts",
     f"https://www.bing.com/news/search?q=%22world+record%22+stunt{_BING_BY_DATE}", "rss", "1b",
     "bing news"),
    ("Bing News: high-wire walks",
     f"https://www.bing.com/news/search?q=highwire+walk{_BING_BY_DATE}", "rss", "1b", "bing news"),
    ("Outside Online (adventure feats)", "https://www.outsideonline.com/feed/", "rss", "1b", "outside"),
]

_RANKED = "relevance-ranked: weeks-old items, replaced by the date-ordered feed (28-Oct)"
RETIRED_FEEDS: dict[str, str] = {
    "https://www.bing.com/news/search?q=%22Guinness+World+Records%22&format=rss": _RANKED,
    "https://www.bing.com/news/search?q=daredevil+stunt&format=rss": _RANKED,
    "https://www.bing.com/news/search?q=world+record+attempt&format=rss": _RANKED,
    "https://www.bing.com/news/search?q=%22world+record%22+stunt&format=rss": _RANKED,
    "https://www.bing.com/news/search?q=highwire+walk&format=rss": _RANKED,
}


def retire_feeds(existing: dict) -> list[str]:
    """Switch off every enabled feed of the workspace that RETIRED_FEEDS names."""
    out = []
    for url, feed in existing.items():
        if url in RETIRED_FEEDS and getattr(feed, "enabled", False):
            feed.enabled = False
            out.append(feed.name)
    return out


# The anchors for lane C. A news item is only citable through a standing fact, so every
# strong term of docs/news-anchors-fire-performer.md has one here, with the SAME kind.
# Grouped: one lesson, several terms. Facts about Brant are his confirmed KM Hub facts.
_RECORD = "Brant holds the Guinness World Record for most torches extinguished by fire eating in one minute: 101, set at a state fair in 2018."
_FIRE_30 = "Brant has performed with fire for more than 30 years, and his world record is in fire eating."
_ONEWHEEL = "Brant's Burning Rubber show is fire juggling while riding a Onewheel, built for motorsport crowds."
_SAFE = "Brant calls himself a safe artist displaying a dangerous element: the risk the crowd feels is real, the risk to the event is not."
_OTHERS = "Taming the Fire looks at people who master danger in their own field and sets their control next to Brant's control of fire."
_CIRCUS = "Brant comes from the same live-danger tradition as circus acts: he has performed with fire for more than 30 years."

_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    ("client_solution", ("guinness world record", "guinness world records", "world record holder",
                         "world record attempt"), _RECORD),
    # A plain "X breaks world record" headline hits only the weak "world record"; these
    # phrases say a person set one ("record heat" and "record jackpot" never say them).
    ("client_solution", ("breaks world record", "breaks the world record", "broke the world record",
                         "sets world record", "sets a world record", "set a world record",
                         "new world record"), _RECORD),
    ("client_solution", ("fire breather", "fire breathing", "fire eater", "fire eating"), _FIRE_30),
    ("client_solution", ("fire performer", "fire performers", "fire dancer", "fire show"), _FIRE_30),
    ("client_solution", ("fire juggler", "fire juggling"), _ONEWHEEL),
    ("client_solution", ("daredevil", "daredevils", "stuntman", "stuntwoman", "stunt performer",
                         "stunt performers"), _SAFE),
    ("client_solution", ("stunt rider", "motorcycle jump", "wall of death"), _ONEWHEEL),
    ("client_solution", ("tightrope walker", "tightrope walk", "high wire", "highwire", "wingsuit",
                         "base jumper", "base jumping", "free solo", "free soloist"), _OTHERS),
    ("client_solution", ("human cannonball", "sword swallower", "escape artist", "circus performer"),
     _CIRCUS),
    ("problem_pattern", ("world record",), _RECORD),
    ("problem_pattern", ("stunt", "stunts", "jump"),
     "A stunt that looks wild is built on preparation and control; Brant treats safety as assumed on his side."),
    ("problem_pattern", ("danger", "dangerous", "daring", "fearless"), _SAFE),
    ("problem_pattern", ("feat", "feats"), _OTHERS),
    ("problem_pattern", ("flames",), _FIRE_30),
    ("problem_pattern", ("circus", "acrobat", "acrobats"), _CIRCUS),
    ("problem_pattern", ("juggler", "juggling"), _ONEWHEEL),
]

STANDING_FACTS: list[tuple[str, str, str]] = [
    (kind, term, lesson) for kind, terms, lesson in _GROUPS for term in terms
]

# --------------------------------------------------------------------------- lane A

# (key, title, url, lesson). Real pages on the history of fire, its myths and rituals.
# Each answered on 28-Oct-2026, and every lesson says only what the page's own summary
# says.
HISTORY: list[tuple[str, str, str, str]] = [
    ("control-of-fire", "How early humans learned to control fire",
     "https://en.wikipedia.org/wiki/Control_of_fire_by_early_humans",
     "Fire gave early humans warmth, light, protection from predators, better hunting tools and cooked food, and those advances helped humans spread across the world."),
    ("prometheus", "Prometheus, the Titan who stole fire",
     "https://en.wikipedia.org/wiki/Prometheus",
     "In Greek mythology the Titan Prometheus defied the Olympian gods by stealing fire from them and giving it to humanity."),
    ("agni", "Agni, the Hindu god of fire",
     "https://en.wikipedia.org/wiki/Agni",
     "Agni is the Hindu god of fire, and in classical Hindu thought fire is one of the five elements, with sky, water, air and earth."),
    ("hestia", "Hestia, goddess of the hearth",
     "https://en.wikipedia.org/wiki/Hestia",
     "In ancient Greek religion Hestia is the goddess of the hearth and the home, and one of the twelve Olympians."),
    ("vestal-virgins", "The Vestal Virgins, keepers of Rome's sacred flame",
     "https://en.wikipedia.org/wiki/Vestal_Virgin",
     "In ancient Rome the Vestal Virgins were priestesses of Vesta, goddess of Rome's sacred hearth and its flame."),
    ("phoenix", "The phoenix that rises from its own ashes",
     "https://en.wikipedia.org/wiki/Phoenix_(mythology)",
     "The phoenix is a legendary bird from Greek mythology, with versions in Egyptian and Persian myth, that gets new life by rising from the ashes of the one before it."),
    ("pele", "Pele, Hawaiian goddess of volcanoes and fire",
     "https://en.wikipedia.org/wiki/Pele_(deity)",
     "In Hawaiian religion Pele is the goddess of volcanoes and fire and the creator of the Hawaiian Islands, still called Madame Pele as a sign of respect."),
    ("hephaestus", "Hephaestus, the god at the forge",
     "https://en.wikipedia.org/wiki/Hephaestus",
     "Hephaestus is the Greek god of blacksmiths, craftsmen, fire, metalworking and volcanoes."),
    ("atash-behram", "India's oldest sacred fire",
     "https://en.wikipedia.org/wiki/Iranshah_Atash_Behram",
     "The Iranshah Atash Behram in Udvada, India, is a sacred Zoroastrian fire in the oldest fire temple in India, dated to the eighth century."),
    ("olympic-flame", "The Olympic flame",
     "https://en.wikipedia.org/wiki/Olympic_flame",
     "The Olympic flame is lit at Olympia in Greece, carried in the torch relay, and burns in the cauldron for the whole Games until the closing ceremony."),
    ("eternal-flame", "Eternal flames",
     "https://en.wikipedia.org/wiki/Eternal_flame",
     "An eternal flame burns for an indefinite time; most are lit and tended on purpose, and some natural ones, fed by gas or coal, have burned for hundreds or thousands of years."),
    ("up-helly-aa", "Up Helly Aa, Shetland's fire festival",
     "https://en.wikipedia.org/wiki/Up_Helly_Aa",
     "Up Helly Aa is a fire festival in Shetland, Scotland, with a torchlit procession of costumed squads that ends with the burning of an imitation Viking galley."),
    ("st-johns-eve", "Midsummer bonfires on Saint John's Eve",
     "https://en.wikipedia.org/wiki/Saint_John%27s_Eve",
     "Saint John's Eve, on 23 June, is tied to Midsummer in Europe, with traditions that include bonfires, feasting and processions."),
    ("fallas", "Las Fallas, the festival that burns its own monuments",
     "https://en.wikipedia.org/wiki/Fallas",
     "In Valencia, Spain, the Fallas festival builds Falla monuments and burns them during the celebration; it joined UNESCO's list of intangible cultural heritage in 2016."),
    ("firewalking", "Firewalking, a test of courage",
     "https://en.wikipedia.org/wiki/Firewalking",
     "Firewalking, walking barefoot over hot embers or stones, goes back at least to Iron Age India around 1200 BCE and has been used as a rite of passage, a test of courage and a test of faith."),
    ("fire-knife", "The Samoan fire knife dance",
     "https://en.wikipedia.org/wiki/Fire_knife",
     "The fire knife is a traditional Samoan implement used in ceremonial dances: performers twirl it with its wrapped ends on fire while doing acrobatic stunts."),
    ("fire-performance", "Fire performance as an art",
     "https://en.wikipedia.org/wiki/Fire_performance",
     "Fire performance is a group of performance arts that manipulate fire, usually with equipment built to hold a flame big enough to make a visual effect."),
    ("burning-man", "Burning Man and the burning of the Man",
     "https://en.wikipedia.org/wiki/Burning_Man",
     "Burning Man is a week-long desert event in Nevada named for its ceremony: the burning of a large wooden effigy called the Man."),
    ("arti", "Arti, the ritual of the waved flame",
     "https://en.wikipedia.org/wiki/Arti_(Hinduism)",
     "Arti is a Hindu ritual in which light from a flame is waved clockwise to honor the deities, with hymns sung as the light is offered."),
]

# --------------------------------------------------------------------------- lane B

# Keeper-of-the-flame SEEDS: questions he answers from his own memory, never events.
STORY_SEEDS: list[tuple[str, str]] = [
    ("pre-show-ritual", "What do you do in the last minutes before every fire show? Why does that ritual matter to you?"),
    ("first-flame", "Think back to the first time you worked with fire in front of people. Who taught you, and what did you feel?"),
    ("respect", "When did fire first teach you to respect it? What changed in how you work after that?"),
    ("record-day", "What went through your head in the minute you set the Guinness World Record? What did the crowd do?"),
    ("street-years", "Think of your years performing on the street. What did a street crowd teach you that a stage never could?"),
    ("safe-artist", "You call yourself a safe artist displaying a dangerous element. When did that line become true for you?"),
    ("crowd-gasp", "What is the moment in your show when the crowd always gasps? Why do you think it lands every time?"),
    ("weather", "Think of a show where the weather fought you: wind, rain or cold. What did you change on the spot?"),
    ("venue-check", "When you arrive at a venue, what is the first thing you check before you light anything? Why that first?"),
    ("walked-away", "Think of a booking you turned down because the client did not take fire seriously. What told you to walk away?"),
    ("kids-ask", "What do kids ask you after a show? Which question surprised you most?"),
    ("onewheel", "How did the idea of juggling fire on a Onewheel start? What was the hardest part of learning it?"),
    ("winter-fire", "What is different about performing fire in the snow at a winter festival? What does the cold change?"),
    ("keeper", "Who was the keeper of the flame in your life, the person who taught you or looked out for you? What did they give you?"),
    ("thirty-years", "What has changed most about fire performing in your 30 years? What has not changed at all?"),
    ("fear", "Are you still afraid of fire after 30 years? What does that fear do for you on stage?"),
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
            meta={"history_page": True, "site": "wikipedia.org"},
        )
        for key, title, url, lesson in HISTORY
    ]
    items += [
        LaneItem(
            kind="story_seed",
            key=key,
            title=question[:120],
            lesson=question,
            language="en",
            meta={"seed": True, "he_fills_in": True},
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
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane C, taming_fire)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane C anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:24} {lesson}")
    print(f"\n[curated_clip] {len(HISTORY)} fire history pages (lane A, sacred_flame)")
    for _key, title, url, _lesson in HISTORY:
        print(f"  {title}  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} prompts (lane B, keeper_of_flame)")
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
                  f"{items[0].title[:60]} | {items[0].url[:70]}")
        for _key, title, url, _lesson in HISTORY:
            await asyncio.sleep(1.0)  # one page a second: Wikipedia throttles bursts
            try:
                r = await client.get(url, headers={"user-agent": PAGE_USER_AGENT})
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL  page {title}: {type(exc).__name__}")
                bad += 1
                continue
            if r.status_code != 200:
                print(f"  FAIL  page {title}: HTTP {r.status_code}")
                bad += 1
                continue
            print(f"  ok    page {title}: HTTP 200")
    total = len(FEEDS) + len(HISTORY)
    print(f"\n{total - bad}/{total} feeds and pages answered")
    return 1 if bad else 0


# --------------------------------------------------------------------------- sample


def _rotation(key: str, week: str) -> str:
    return hashlib.sha256(f"{week}:{key}".encode()).hexdigest()


async def sample_week(network: bool) -> None:
    """The evidence a coming week would draw on, per lane. Not the model's ideas:
    those need the subscription worker (the live LLM queue), which this never calls."""
    from tce.editorial.common import current_week_start
    from tce.editorial.lane_profile import FIRE_PERFORMER

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in FIRE_PERFORMER.lanes))
    pages = sorted(HISTORY, key=lambda c: _rotation(c[0], week))[: FIRE_PERFORMER.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: FIRE_PERFORMER.reserve_per_lane]
    if network:
        import httpx

        from tce.news.feeds import parse_feed

        terms = [t.lower() for _k, t, _l in STANDING_FACTS]
        found = []
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                     headers={"user-agent": "tce-news/1.0"}) as client:
            for name, url, kind, _t, _v in FEEDS:
                try:
                    r = await client.get(url)
                    items = parse_feed(kind, r.text)
                except Exception:  # noqa: BLE001
                    continue
                for it in items[:25]:
                    text = f"{it.title} {getattr(it, 'summary', '') or ''}".lower()
                    hits = [t for t in terms if t in text]
                    if hits:
                        found.append((len(hits), name, it.title, hits[:3]))
        found.sort(reverse=True)
        print("\nC taming_fire - recent feed items that touch his anchors (top 10; the "
              "matcher and the gates decide):")
        for _n, name, title, hits in found[:10]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nC taming_fire - add --network to read the feeds")
    print(f"\nA sacred_flame - {len(pages)} pages rotated in this week:")
    for _key, title, url, lesson in pages:
        print(f"  {title} {url}\n      {lesson}")
    print(f"\nB keeper_of_flame - {len(seeds)} prompts rotated in this week:")
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
                                          label="Brant fire performer lanes"))
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
        print(f"history pages and prompts: {counts}")
        await session.commit()

        settings_row_count = await lineup.set_videos_per_week(session, ws, VIDEOS_PER_WEEK)
        await session.commit()
        print(f"videos_per_week: {VIDEOS_PER_WEEK} ({settings_row_count})")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=BRANT_WORKSPACE)
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
