# ruff: noqa: E501 - the seed data (pages, prompts) reads better unwrapped
"""Seed Chris Gamble's three idea lanes (the `clown_poet` lane profile).

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  parent_artist      prompts about being a single parent and a working artist,
                             questions he answers from his own memory (story_seed)
  lane B  creative_life      creativity, play and the arts in the news, plus standing facts
                             about his own work as anchors
  lane C  typewriter_poetry  one real page on typewriters, poems for an occasion or a poem
                             form (curated_clip); he writes his own poem on the spot

Also: the workspace strategy (English, replaces the owner strategy file) and
videos_per_week 3. His creator, voice and brand profiles are seeded by SQL
(scripts/seed_chris_profiles.sql): those models carry no workspace column.

Sources (05-Nov-2026): the three pillars are his own words on his 05-Nov call with Ziv
(Fathom 890641634, 22:30-33:40): "parent as an artist, living a creative life, and
typewriter poetry". Format from the same call: walking videos, one line at a time, one
location, one take. Standing facts from that call and christophergamble.co.

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python3 scripts/seed_chris_lanes.py                 # dry run
    PYTHONPATH=src python3 scripts/seed_chris_lanes.py --check         # fetch every feed and page
    PYTHONPATH=src python3 scripts/seed_chris_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python3 scripts/seed_chris_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

CHRIS_WORKSPACE = "f34e9762-6b7f-4399-afcf-b674db1e28f5"
AUTHOR = "chris-lanes-seed"
VIDEOS_PER_WEEK = 3
# Calgary, Alberta.
TIMEZONE = "America/Edmonton"
PAGE_USER_AGENT = "TCE-seed/1.0 (https://kivimedia.co)"
PAGE_HOST = "en.wikipedia.org"

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# Content strategy - Christopher Gamble, clown and typewriter poet

## Who it speaks to
People who want more creativity and play in their own lives: hobby artists, parents who \
make things, fellow artists. Also the people who book live acts: festivals, schools, \
weddings and events.

## Three lanes, 15 ideas a week (5 in each)
3 videos posted a week. He plans the week once, then films each video as a walk-and-talk \
in one place, in one take: one short line, a pause, walk, breathe, the next line. The \
editor cuts the gaps and keeps the best take.

1. **Parent as an Artist** (5 a week): being a single parent and a working artist. Each \
idea is a question he answers from his own memory. Never an invented story.
2. **Living a Creative Life** (5 a week): creativity, play and the arts in the news, and \
his take: permission to play, and no guilt or pressure on the need to create.
3. **Typewriter Poetry** (5 a week): one real thing about typewriters, poems for an \
occasion or a poem form, then he writes a poem on the spot for something in front of him. \
The poem is always his own.

## Voice
Playful, warm and honest, a little absurd. Plain words, short lines. Concrete: what he \
sees on the walk, what the paper looks like, what a kid would ask.

## Never
- Invent stories, people, quotes or numbers.
- Write a poem for him.
- His children's names or private details, family conflict or anything legal.
- Prices, fees or money.
- A call to action ("book me", "DM me", "link in bio").
- Politics, war, crime or tragedy.
"""

# --------------------------------------------------------------------------- lane B (news)

# (name, url, kind, tier, vendor). Each answered with 10 to 12 fresh items from the VPS
# on 05-Nov-2026, newest inside the day. Date-ordered like Brant's and Tim's
# (`qft=sortbydate="1"`); feeds.unwrap_click_tracker turns each link into the article.
_BING_BY_DATE = "&format=rss&qft=sortbydate%3d%221%22"


def _bing(name: str, query: str) -> tuple[str, str, str, str, str]:
    return (f"Bing News: {name}", f"https://www.bing.com/news/search?q={query}{_BING_BY_DATE}",
            "rss", "1b", "bing news")


FEEDS: list[tuple[str, str, str, str, str | None]] = [
    _bing("hobby artists", "hobby+artist"),
    _bing("amateur artists", "amateur+artists"),
    _bing("community art projects", "community+art+project"),
    _bing("public art projects", "public+art+project"),
    _bing("Calgary arts", "Calgary+arts"),
    _bing("Alberta artists", "Alberta+artist"),
    _bing("clown and circus festivals", "clown+festival"),
    _bing("poetry festivals", "poetry+festival"),
    _bing("typewriter poets", "typewriter+poet"),
    _bing("art therapy", "art+therapy"),
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


# The anchors for lane B. A news item is only citable through a standing fact, so every
# term of docs/news-anchors-clown-poet.md has one here, with the SAME kind. Grouped: one
# fact, several terms. Facts about Chris are his own words (05-Nov call) and his own site.
_LIFE = "Chris took the words \"living a creative life\" from Calgary Arts Development: the question is not how to be an artist, but how to live as a creator without censoring yourself (his 05-Nov-2026 call)."
_GUILT = "Chris tells hobby artists to drop the guilt and the pressure they put on their need to create: a studio should be a place you love even if you never make a painting in it (his 05-Nov-2026 call)."
_CLOWN = "Chris is a Calgary clown and physical theatre artist: he took his first clown workshop at age 10, co-founded NoBones Theatre in 2005 and says clown gives people permission to be silly, curious and brave (christophergamble.co)."
_POET = "Chris writes poems on the spot for anyone who stops, on his grandfather's 1934 typewriter, at festivals, markets, weddings and private events (christophergamble.co)."
_COMMUNITY = "Chris makes shows where the audience helps it happen: he says people need places where they can laugh, take part, loosen up and connect with each other (christophergamble.co)."

_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    ("client_solution", ("creativity", "creative life", "creative block", "unstructured play", "free play",
                         "imaginative play", "playfulness", "calgary arts development"), _LIFE),
    ("client_solution", ("hobby artist", "hobby artists", "amateur artist", "amateur artists",
                         "self-taught artist", "art class", "art classes", "live painting", "art therapy"), _GUILT),
    ("client_solution", ("clowning", "clown school", "physical theatre", "street performer", "street performers",
                         "busker", "buskers", "fringe festival"), _CLOWN),
    ("client_solution", ("typewriter", "typewriters", "typewriter poet", "typewriter poetry", "poet laureate",
                         "poetry reading", "poetry festival", "open mic"), _POET),
    ("client_solution", ("community art", "community arts", "community art project", "public art",
                         "public art project"), _COMMUNITY),
    ("problem_pattern", ("artist", "artists", "art", "arts", "exhibition", "creative", "imagination"), _COMMUNITY),
    ("problem_pattern", ("painting", "painter", "studio", "hobby"), _GUILT),
    ("problem_pattern", ("clown", "clowns", "circus", "theatre", "theater", "festival"), _CLOWN),
    ("problem_pattern", ("poem", "poems", "poetry", "poet"), _POET),
]

STANDING_FACTS: list[tuple[str, str, str]] = [
    (kind, term, lesson) for kind, terms, lesson in _GROUPS for term in terms
]

# --------------------------------------------------------------------------- lanes A and C

# (key, title, url, lesson). Real pages on typewriters, poems for an occasion and poem
# forms. Each answered on 05-Nov-2026, and every lesson says only what the page's own
# summary says. Never a page about death or grief (no elegy, no epitaph).
PAGES: list[tuple[str, str, str, str]] = [
    ("typewriter", "When a typist was called a typewriter",
     "https://en.wikipedia.org/wiki/Typewriter",
     "A typewriter makes each letter by striking an inked ribbon against the paper, and by the end of the 19th century the person who used one was also called a typewriter."),
    ("sholes-and-glidden", "The first typewriter that sold",
     "https://en.wikipedia.org/wiki/Sholes_and_Glidden_typewriter",
     "The Sholes and Glidden typewriter, designed mainly by Christopher Latham Sholes from 1867, was the first commercially successful typewriter; E. Remington and Sons took it on in 1873."),
    ("qwerty", "Why the keys say QWERTY",
     "https://en.wikipedia.org/wiki/QWERTY",
     "QWERTY is named for the first six keys on the top letter row, and the layout grew out of quick typing of English on typewriters."),
    ("underwood", "Five million Underwoods",
     "https://en.wikipedia.org/wiki/Underwood_Typewriter_Company",
     "Underwood made what is considered the first widely successful modern typewriter, and by 1939 it had produced five million machines."),
    ("royal", "Royal, a typewriter company from 1904",
     "https://en.wikipedia.org/wiki/Royal_Typewriter_Company",
     "Royal was founded in January 1904 as a maker of typewriters."),
    ("ink-ribbon", "The ink ribbon",
     "https://en.wikipedia.org/wiki/Ink_ribbon",
     "An ink ribbon carries the ink to the paper when a key strikes it; they were used so widely on typewriters that people called them typewriter ribbons."),
    ("carriage-return", "The carriage return",
     "https://en.wikipedia.org/wiki/Carriage_return",
     "A carriage return sends the typing position back to the beginning of the line."),
    ("dead-key", "The key that types nothing on its own",
     "https://en.wikipedia.org/wiki/Dead_key",
     "A dead key on a typewriter prints no full character by itself: it adds an accent to the letter typed right after it."),
    ("occasional-poetry", "Poems written for one occasion",
     "https://en.wikipedia.org/wiki/Occasional_poetry",
     "Occasional poetry is poetry written for a particular occasion, and it is often studied together with performance and with the people who asked for it."),
    ("ekphrasis", "A poem about a work of art",
     "https://en.wikipedia.org/wiki/Ekphrasis",
     "Ekphrasis is writing that describes a work of art, real or imagined, and poets have used it since classical antiquity to stir strong feelings with vivid words."),
    ("apostrophe", "Talking to a thing that cannot answer",
     "https://en.wikipedia.org/wiki/Apostrophe_(figure_of_speech)",
     "An apostrophe is a figure of speech where the speaker turns and talks to someone absent or to an object, often starting with \"O\"; poets talk to love, time, or anything that cannot answer back."),
    ("haiku", "The haiku",
     "https://en.wikipedia.org/wiki/Haiku",
     "Haiku is a short form of poetry from Japan; the traditional pattern is three phrases of 5, 7 and 5 sounds, with a cutting word and a nod to the season."),
    ("haiku-in-english", "Haiku in English",
     "https://en.wikipedia.org/wiki/Haiku_in_English",
     "Haiku in English grew from the early 20th century, kept the focus on nature, the seasons and images, and changed to fit the rhythm of English."),
    ("limerick", "The limerick",
     "https://en.wikipedia.org/wiki/Limerick_(poetry)",
     "A limerick is a five-line verse from England in the early 18th century: lines one, two and five rhyme, and lines three and four are shorter and share their own rhyme."),
    ("acrostic", "The acrostic, a poem that spells a word",
     "https://en.wikipedia.org/wiki/Acrostic",
     "In an acrostic, the first letter of each line spells out a word or a message, and it can help people remember."),
    ("sonnet", "The sonnet",
     "https://en.wikipedia.org/wiki/Sonnet",
     "A sonnet is a fourteen-line poem with a set rhyme scheme; it started in 13th century Sicily, mostly about romantic love, and later any subject was welcome."),
    ("found-poetry", "Found poetry",
     "https://en.wikipedia.org/wiki/Found_poetry",
     "Found poetry takes words and phrases from other places and gives them new meaning by changing the lines and the spacing, or by adding and taking away words."),
    ("spoken-word", "Spoken word",
     "https://en.wikipedia.org/wiki/Spoken_word",
     "Spoken word is poetry performed out loud, carrying on an ancient oral tradition, where the poet's live voice and timing matter as much as the words."),
    ("improvisation", "Improvisation, making it up on the spot",
     "https://en.wikipedia.org/wiki/Improvisation",
     "Improvisation is making or doing something not planned beforehand, with whatever is at hand; the word comes from the Latin for unforeseen."),
    ("poetry-slam", "The poetry slam",
     "https://en.wikipedia.org/wiki/Poetry_slam",
     "A poetry slam is a competition where poets perform spoken-word poetry in front of a live audience and judges."),
    ("ode", "The ode, a poem of praise",
     "https://en.wikipedia.org/wiki/Ode",
     "An ode is a lyric poem from ancient Greece that praises an event or a person, or describes nature with both thought and feeling."),
    ("villanelle", "The villanelle and its two refrains",
     "https://en.wikipedia.org/wiki/Villanelle",
     "A villanelle is a nineteen-line poem of five three-line stanzas and a final four-line one, with two lines that keep coming back as refrains."),
    ("concrete-poetry", "Concrete poetry, a poem you look at",
     "https://en.wikipedia.org/wiki/Concrete_poetry",
     "In concrete poetry the way the words are laid out on the page carries the meaning, often shaped like the thing the poem is about."),
    ("lipogram", "The lipogram, writing without a letter",
     "https://en.wikipedia.org/wiki/Lipogram",
     "A lipogram is a kind of word game where the writer leaves out a letter on purpose, and ancient Greek texts without the letter sigma are the earliest examples."),
    ("renga", "Renga, a poem written by many poets",
     "https://en.wikipedia.org/wiki/Renga",
     "Renga is Japanese poetry written together: poets take turns adding linked stanzas, and it later gave birth to haiku."),
    ("exquisite-corpse", "Exquisite corpse",
     "https://en.wikipedia.org/wiki/Exquisite_corpse",
     "Exquisite corpse is a game where each person adds to a piece of writing or a picture in turn, seeing only the end of what the last person added."),
    ("light-verse", "Light verse, poems that make you laugh",
     "https://en.wikipedia.org/wiki/Light_poetry",
     "Light verse is poetry that tries to be funny: usually short, about silly or serious things, full of puns, bold rhymes and word play."),
    ("nonsense-verse", "Nonsense verse",
     "https://en.wikipedia.org/wiki/Nonsense_verse",
     "Nonsense verse uses strong rhythm and rhyme, and it is often whimsical and funny."),
    ("couplet", "The couplet",
     "https://en.wikipedia.org/wiki/Couplet",
     "A couplet is a pair of lines in a row that rhyme and share the same rhythm."),
    ("street-performance", "Street performance goes back to antiquity",
     "https://en.wikipedia.org/wiki/Street_performance",
     "Street performance, or busking, is performing in public places, is practiced all over the world and dates back to antiquity."),
    ("poet-laureate", "A poet for special occasions",
     "https://en.wikipedia.org/wiki/Poet_laureate",
     "A poet laureate is a poet appointed to write poems for special events and occasions; the English royal office dates from John Dryden in 1668."),
]

# Parent-and-artist SEEDS: questions he answers from his own memory, never events. Never his
# children's names, family conflict or anything legal.
STORY_SEEDS: list[tuple[str, str]] = [
    ("how-you-get-it-done", "When other parents hear how you raise your kids on your own and still make art, their eyes get big. What do you tell them about how you actually get it done?"),
    ("show-day-at-home", "What does a show day look like when you are the only parent at home? What makes it work?"),
    ("when-do-you-create", "When do you really get to create these days: late at night, early in the morning, or in the car? What does that hour look like?"),
    ("what-parenting-changed", "What did becoming a parent change in how you make art?"),
    ("kids-taught-you-play", "What have your kids taught you about play that no clown teacher ever did?"),
    ("kids-see-the-clown", "What do your kids think of your job as a clown? What is the funniest thing they have said about it?"),
    ("kids-at-work", "Have your kids ever come to work with you, at a festival or a school show? What did they notice that you did not?"),
    ("house-rule-from-clown", "Is there a rule in your house that came straight from clown? Where did it come from?"),
    ("school-pickup", "How do you explain your job to other parents at school pickup? What do they ask you?"),
    ("what-kids-learn", "What do you hope your kids learn about living as an artist, just from watching you?"),
    ("small-ritual", "What is one small creative thing you do with your kids, just for fun? How did it start?"),
    ("head-full-of-a-show", "How do you stay present with your kids when your head is full of a show you are building?"),
    ("ordinary-tuesday", "What does an ordinary Tuesday look like for a single parent who makes art? What is the part nobody sees?"),
    ("best-advice", "What is the best advice you ever got about being a parent and an artist? Who gave it to you?"),
    ("art-guilt", "When did you last feel guilty for choosing your art over something else? What did you tell yourself?"),
    ("slow-sunday", "What does play look like in your home on a slow Sunday?"),
    ("typewriter-and-kids", "What do your kids make of the old typewriter? Have they ever typed on it?"),
    ("wait-until-grown", "What would you say to a parent who thinks they have to wait until the kids are grown to make art again?"),
    ("tired-and-funny", "How do you stay funny on the days you are tired? Where does the play come from then?"),
    ("asking-for-help", "Your circus show is about a ringmaster who cannot do it alone. Where in your own life as a parent have you had to ask for help?"),
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
            meta={"poetry_page": True, "site": "wikipedia.org"},
        )
        for key, title, url, lesson in PAGES
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
    for _key, _title, url, _lesson in PAGES:
        if urlsplit(url).hostname != PAGE_HOST:
            raise SystemExit(f"a page must be a real reference page: {url}")
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
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane B, creative_life)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane B anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:24} {lesson[:90]}")
    print(f"\n[curated_clip] {len(PAGES)} typewriter and poem pages (lane C, typewriter_poetry)")
    for _key, title, url, _lesson in PAGES:
        print(f"  {title}  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} prompts (lane A, parent_artist)")
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
            f'"timezone":"{TIMEZONE}","catchup_days":2,"final_stage":"{final}","window_days":7}}'
        )
        print(
            f"  curl -s -X PUT http://127.0.0.1:8200/api/v1/content-runs/schedule/{name} "
            f'-H "Authorization: Bearer $TCE_PRIVATE_ACCESS_KEY" -H "X-Workspace-Id: {ws}" '
            f"-H 'Content-Type: application/json' -d '{body}'"
        )
    print(f"  PYTHONPATH=src python3 scripts/build_anchor_index.py --workspace {ws} --dry-run")


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
    pages = sorted({url for _key, _title, url, _lesson in PAGES})
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                 headers={"user-agent": PAGE_USER_AGENT}) as client:
        for url in pages:
            await asyncio.sleep(1.0)  # one page a second (Wikipedia 403s a burst)
            try:
                r = await client.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL  page {url}: {type(exc).__name__}")
                bad += 1
                continue
            if r.status_code != 200:
                print(f"  FAIL  page {url}: HTTP {r.status_code}")
                bad += 1
                continue
            print(f"  ok    page {url}: HTTP {r.status_code}")
    total = len(FEEDS) + len(pages)
    print(f"\n{total - bad}/{total} feeds and pages answered")
    return 1 if bad else 0


# --------------------------------------------------------------------------- sample


def _rotation(key: str, week: str) -> str:
    return hashlib.sha256(f"{week}:{key}".encode()).hexdigest()


async def sample_week(network: bool) -> None:
    """The evidence a coming week would draw on, per lane. Not the model's ideas:
    those need the subscription worker (the live LLM queue), which this never calls."""
    from tce.editorial.common import current_week_start
    from tce.editorial.lane_profile import CLOWN_POET

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in CLOWN_POET.lanes))
    pages = sorted(PAGES, key=lambda c: _rotation(c[0], week))[: CLOWN_POET.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: CLOWN_POET.reserve_per_lane]
    print(f"\nA parent_artist - {len(seeds)} prompts rotated in this week:")
    for _key, question in seeds:
        print(f"  {question}")
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
        print("\nB creative_life - recent feed items that touch his anchors (top 10; the "
              "matcher and the gates decide):")
        for _n, name, title, hits in found[:10]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nB creative_life - add --network to read the feeds")
    print(f"\nC typewriter_poetry - {len(pages)} pages rotated in this week:")
    for _key, title, url, lesson in pages:
        print(f"  {title} {url}\n      {lesson}")


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
                                          label="Chris clown poet lanes"))
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
        print(f"pages and prompts: {counts}")
        await session.commit()

        settings_row_count = await lineup.set_videos_per_week(session, ws, VIDEOS_PER_WEEK)
        await session.commit()
        print(f"videos_per_week: {VIDEOS_PER_WEEK} ({settings_row_count})")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=CHRIS_WORKSPACE)
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
