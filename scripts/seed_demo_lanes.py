# ruff: noqa: E501 - the seed data (pages, prompts) reads better unwrapped
"""Seed the demo workspace's three idea lanes (the `wedding_coach` lane profile).

The creator is FICTIONAL, made so product pictures and demo videos never show a real
client's workspace. Nell Hartwick and Lark & Lantern Entertainment do not exist; her
standing facts, her voice and her prompts were written for this demo.

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  dance_floor_stories  prompts from her nights running wedding receptions,
                               questions she answers from her own memory (story_seed)
  lane B  wedding_news         weddings and the events business in the news, plus standing
                               facts about her own work as anchors
  lane C  party_craft          one real page on the craft of a party, told true to the page
                               (curated_clip)

Also: the workspace strategy (English, replaces the owner strategy file) and
videos_per_week 3. Her creator, voice and brand profiles are seeded by SQL
(scripts/seed_demo_profiles.sql): those models carry no workspace column.

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python3 scripts/seed_demo_lanes.py                 # dry run
    PYTHONPATH=src python3 scripts/seed_demo_lanes.py --check         # fetch every feed and page
    PYTHONPATH=src python3 scripts/seed_demo_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python3 scripts/seed_demo_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

DEMO_WORKSPACE = "6e9faea3-412b-4839-90e7-77b67f654808"
AUTHOR = "demo-lanes-seed"
VIDEOS_PER_WEEK = 3
TIMEZONE = "America/New_York"
PAGE_USER_AGENT = "TCE-seed/1.0 (https://kivimedia.co)"
PAGE_HOST = "en.wikipedia.org"

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# Content strategy - Nell Hartwick, wedding emcee and coach

## Who it speaks to
Wedding DJs, emcees and bands who want to run a better night. Also the wedding planners \
and couples who hire them.

## Three lanes, 15 ideas a week (5 in each)
3 videos posted a week. She plans the week once, then films each video on her phone in \
one place, in one take: one short line at a time. The editor cuts the gaps and keeps the \
best take.

1. **Stories from the Dance Floor** (5 a week): her nights running wedding receptions. \
Each idea is a question she answers from her own memory. Never an invented story.
2. **Weddings in the News** (5 a week): wedding trends and the events business in the \
news, and her take as the person who runs the room.
3. **The Craft of a Great Party** (5 a week): one real thing about the craft of a party \
(the first dance, the emcee, a line dance, beatmatching), and what it teaches about \
running the night.

## Voice
Warm, quick and direct, like someone who has held the microphone in a lot of rooms. Plain \
words, short lines. Concrete: who is on the floor, what the room looks like, what she says \
into the microphone.

## Never
- Invent stories, people, quotes or numbers.
- Prices, fees or money.
- A client's, a venue's or a guest's name.
- A call to action ("book me", "DM me", "link in bio").
- Politics, war, crime, tragedy or celebrity gossip.
"""

# --------------------------------------------------------------------------- lane B (news)

# (name, url, kind, tier, vendor). Each answered with 9 to 12 fresh items from the VPS on
# 06-Nov-2026. Quoted phrases: an unquoted "wedding DJ" brings back a retail chain's collapse
# and an unquoted "wedding band" brings back The Rings of Power. Date-ordered like Brant's,
# Tim's and Chris's (`qft=sortbydate="1"`); feeds.unwrap_click_tracker turns each link into
# the article.
_BING_BY_DATE = "&format=rss&qft=sortbydate%3d%221%22"


def _bing(name: str, query: str) -> tuple[str, str, str, str, str]:
    return (f"Bing News: {name}", f"https://www.bing.com/news/search?q={query}{_BING_BY_DATE}",
            "rss", "1b", "bing news")


FEEDS: list[tuple[str, str, str, str, str | None]] = [
    _bing("wedding trends", "%22wedding+trends%22"),
    _bing("wedding planners", "%22wedding+planners%22"),
    _bing("wedding planner trends", "%22wedding+planner%22+trends"),
    _bing("wedding DJs", "%22wedding+DJ%22"),
    _bing("wedding industry", "%22wedding+industry%22"),
    _bing("wedding guests", "%22wedding+guests%22"),
    _bing("micro weddings", "%22micro-wedding%22"),
    _bing("wedding venues", "%22wedding+venue%22"),
    _bing("wedding playlists", "%22wedding+playlist%22"),
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
# term of docs/news-anchors-wedding-coach.md has one here, with the SAME kind. Grouped: one
# fact, several terms. The creator is fictional; these facts were written for the demo.
_ROOM = "Nell runs the room at weddings as an emcee and DJ: she says a great reception is not a playlist, it is a host who reads the room and moves people from one moment to the next."
_FLOOR = "Nell coaches wedding DJs and emcees to treat the dance floor as the measure of the night: who is on it, who is not, and what will bring the next person up."
_COUPLE = "Nell starts every wedding by asking the couple what they want their guests to feel, then builds the night backward from that answer."
_TEAM = "Nell tells entertainers to treat the planner, the caterer and the photographer as one team: a timeline only works when everyone hears it the same way."
_SMALL = "Nell runs small weddings and big ones the same way: fewer guests make every moment louder, so the host matters more, not less."

_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    ("client_solution", ("wedding trend", "wedding trends", "wedding entertainment", "wedding industry"), _ROOM),
    ("client_solution", ("wedding dj", "wedding djs", "wedding singer", "wedding playlist", "first dance"), _FLOOR),
    ("client_solution", ("wedding guest", "wedding guests", "wedding toast", "wedding speech", "wedding speeches"), _COUPLE),
    ("client_solution", ("wedding planner", "wedding planners", "wedding venue", "wedding venues", "wedding season"), _TEAM),
    ("client_solution", ("micro wedding", "micro weddings", "destination wedding", "destination weddings"), _SMALL),
    ("problem_pattern", ("wedding", "weddings"), _COUPLE),
    ("problem_pattern", ("dj", "djs", "emcee", "emcees", "playlist", "live music", "dance floor"), _FLOOR),
]

STANDING_FACTS: list[tuple[str, str, str]] = [
    (kind, term, lesson) for kind, terms, lesson in _GROUPS for term in terms
]

# --------------------------------------------------------------------------- lanes A and C

# (key, title, url, lesson). Real pages on the craft of a party. Each answered on 06-Nov-2026,
# and every lesson says only what the page's own summary says. No page about money, and none
# with a history that does not belong in a happy video about a party.
PAGES: list[tuple[str, str, str, str]] = [
    ("wedding-reception", "Why it is called a reception",
     "https://en.wikipedia.org/wiki/Wedding_reception",
     "A wedding reception is a party usually held after the marriage ceremony; the name comes from the couple receiving family and friends for the first time as a married couple."),
    ("first-dance", "The first dance opens the floor",
     "https://en.wikipedia.org/wiki/First_dance",
     "The first dance is an element in a number of traditions: it opens a dance function such as a ball, a prom or a wedding."),
    ("bridal-chorus", "Here Comes the Bride came from an opera",
     "https://en.wikipedia.org/wiki/Bridal_Chorus",
     "The Bridal Chorus comes from Wagner's 1850 opera Lohengrin; it is now played for the bride's entrance at many formal weddings and is known in English-speaking countries as Here Comes the Bride."),
    ("mendelssohn-wedding-march", "The other wedding march",
     "https://en.wikipedia.org/wiki/Wedding_March_(Mendelssohn)",
     "Mendelssohn's Wedding March, written in 1842, comes from his music for Shakespeare's A Midsummer Night's Dream, and it is one of the most used wedding marches."),
    ("disc-jockey", "What the disc in disc jockey meant",
     "https://en.wikipedia.org/wiki/Disc_jockey",
     "A disc jockey is a person who plays recorded music for an audience; the disc first meant shellac and later vinyl records, and DJ now covers music from other recording media too."),
    ("master-of-ceremonies", "The master of ceremonies",
     "https://en.wikipedia.org/wiki/Master_of_ceremonies",
     "A master of ceremonies is in charge of staged events and parties, and is responsible for introducing speakers or performers and making announcements."),
    ("toast", "What a toast really is",
     "https://en.wikipedia.org/wiki/Toast_(honor)",
     "A toast is a ritual where a drink is taken as an expression of honor or goodwill; a person can be the toast of the evening, and someone proposes a toast to congratulate them."),
    ("hora", "The hora, a circle dance",
     "https://en.wikipedia.org/wiki/Hora_(dance)",
     "The hora is a type of circle dance from Southeast Europe; similar dances are found in Bulgaria, Romania, Moldova, North Macedonia, Greece and Turkey, and among Ashkenazi and Sephardic Jews and the Roma."),
    ("conga-line", "The conga line",
     "https://en.wikipedia.org/wiki/Conga_line",
     "The conga line is a novelty line dance derived from a Cuban carnival dance and popular in the US in the 1930s to the 1950s: a long line of dancers that usually turns into a circle."),
    ("electric-slide", "The Electric Slide",
     "https://en.wikipedia.org/wiki/Electric_Slide",
     "The Electric is a four-wall line dance, and choreographer and dancer Ric Silver claims to have created it in 1976."),
    ("chicken-dance", "The Chicken Dance",
     "https://en.wikipedia.org/wiki/Chicken_Dance",
     "The Chicken Dance is an oom-pah song from 1957."),
    ("macarena", "The Macarena",
     "https://en.wikipedia.org/wiki/Macarena",
     "Macarena is a song by the Spanish pop duo Los del Rio, first recorded for a 1993 album; a remix by the Bayside Boys added English lyrics and expanded its popularity."),
    ("ymca", "Y.M.C.A.",
     "https://en.wikipedia.org/wiki/Y.M.C.A._(song)",
     "Y.M.C.A. is a song by the American disco group Village People, released in October 1978, and it reached No. 2 on the Billboard Hot 100 in early 1979."),
    ("cha-cha-slide", "The song that tells you the steps",
     "https://en.wikipedia.org/wiki/Cha_Cha_Slide",
     "Cha Cha Slide is a line dance song by DJ Casper, released as a single in August 2000, and four years later it topped the UK Singles Chart."),
    ("cupid-shuffle", "The Cupid Shuffle",
     "https://en.wikipedia.org/wiki/Cupid_Shuffle",
     "Cupid Shuffle is a song by Cupid from his 2007 album; it spawned a popular line dance and has drawn comparisons to the Cha Cha Slide."),
    ("shout", "Shout",
     "https://en.wikipedia.org/wiki/Shout_(Isley_Brothers_song)",
     "Shout is a song written and first recorded by the Isley Brothers in 1959, and later versions include a cover by Lulu."),
    ("wedding-cake", "The wedding cake",
     "https://en.wikipedia.org/wiki/Wedding_cake",
     "A wedding cake is the traditional cake served at wedding receptions following dinner, usually on display and then served to guests at the reception."),
    ("wedding-planner", "The wedding planner",
     "https://en.wikipedia.org/wiki/Wedding_planner",
     "A wedding planner is an event planner who helps with the design, planning and management of a client's wedding; other names include wedding coordinator and wedding director."),
    ("wedding-photography", "Wedding photography",
     "https://en.wikipedia.org/wiki/Wedding_photography",
     "Wedding photography is a specialty focused on the events and activities of a wedding, and it can include an engagement session before the wedding day."),
    ("beatmatching", "Beatmatching",
     "https://en.wikipedia.org/wiki/Beatmatching",
     "Beatmatching is a DJ technique of shifting an upcoming track so its tempo matches the track that is playing and the beats line up."),
    ("fade", "The fade",
     "https://en.wikipedia.org/wiki/Fade_(audio_engineering)",
     "In audio engineering a fade is a gradual increase or decrease in the level of a signal; the term is also used for film and theater lighting."),
    ("ceilidh", "The ceilidh, which just means a visit",
     "https://en.wikipedia.org/wiki/C%C3%A8ilidh",
     "A ceilidh is a traditional Scottish and Irish social gathering; in its most basic form it means a social visit, and today it usually involves dancing and Gaelic folk music."),
    ("tarantella", "The tarantella",
     "https://en.wikipedia.org/wiki/Tarantella",
     "Tarantella is a group of southern Italian folk dances with a fast upbeat tempo, usually accompanied by tambourines."),
    ("polka", "The polka",
     "https://en.wikipedia.org/wiki/Polka",
     "Polka is a dance style and genre of dance music from nineteenth-century Bohemia, now part of the Czech Republic, and it is popular throughout Europe and the Americas."),
    ("second-line", "The second line",
     "https://en.wikipedia.org/wiki/Second_line_(parades)",
     "The second line is a New Orleans parade tradition: the people who follow the brass band to enjoy the music."),
    ("line-dance", "The line dance",
     "https://en.wikipedia.org/wiki/Line_dance",
     "A line dance is a choreographed dance where a group repeats a sequence of steps in lines, without touching, and each dance is usually named for a specific song."),
    ("waltz", "The waltz",
     "https://en.wikipedia.org/wiki/Waltz",
     "The waltz is a ballroom and folk dance in triple time, performed primarily in closed position, from German-speaking regions of Europe in the 18th century."),
    ("best-man", "How a groom picks the best man",
     "https://en.wikipedia.org/wiki/Groomsman",
     "A groomsman is one of the groom's male attendants, usually a close friend or relative, and from them the groom usually chooses one to serve as best man."),
    ("rehearsal-dinner", "The rehearsal dinner",
     "https://en.wikipedia.org/wiki/Rehearsal_dinner",
     "A rehearsal dinner is a traditional pre-wedding event in the United States, usually held after the wedding rehearsal, the night before the ceremony."),
    ("cover-band", "The cover band",
     "https://en.wikipedia.org/wiki/Cover_band",
     "A cover band plays songs recorded by someone else, sometimes copying the original and sometimes changing it, and such bands also perform at private events like weddings."),
    ("stage-lighting", "Stage lighting",
     "https://en.wikipedia.org/wiki/Stage_lighting",
     "Stage lighting is the craft of lighting for theater, dance and other performing arts, and it can include special effects such as lasers and fog machines."),
    ("disco-ball", "The disco ball",
     "https://en.wikipedia.org/wiki/Disco_ball",
     "A disco ball is a roughly spherical object covered in hundreds or thousands of mirrored facets that reflects light in many directions, usually mounted above people's heads and rotating."),
    ("sock-hop", "The sock hop",
     "https://en.wikipedia.org/wiki/Sock_hop",
     "A sock hop was an informal dance event for teenagers in mid-20th-century North America, featuring popular music."),
    ("photo-booth", "The photo booth",
     "https://en.wikipedia.org/wiki/Photo_booth",
     "A photo booth is a kiosk with an automated camera and film processor, and today the vast majority of them are digital."),
    ("karaoke", "Karaoke",
     "https://en.wikipedia.org/wiki/Karaoke",
     "Karaoke is interactive entertainment where people sing along to pre-recorded accompaniment using a microphone."),
    ("confetti", "Why it is called confetti",
     "https://en.wikipedia.org/wiki/Confetti",
     "Confetti are small pieces of paper or other material thrown at celebrations like parties, parades and weddings, and the word comes from the Italian for a small sweet."),
    ("audio-feedback", "The squeal in the microphone",
     "https://en.wikipedia.org/wiki/Audio_feedback",
     "Audio feedback happens when sound from a loudspeaker gets back into the microphone, is amplified again and goes out through the loudspeaker again."),
    ("tempo", "Tempo",
     "https://en.wikipedia.org/wiki/Tempo",
     "Tempo, measured in beats per minute, is the speed or pace of a piece of music and often indicates its character or atmosphere."),
    ("sound-system", "What a sound system actually is",
     "https://en.wikipedia.org/wiki/Sound_reinforcement_system",
     "A sound reinforcement system combines microphones, signal processors, amplifiers and loudspeakers, controlled by a mixing console, to make sounds louder and reach a larger audience."),
]

# Dance floor SEEDS: questions she answers from her own memory, never events.
STORY_SEEDS: list[tuple[str, str]] = [
    ("empty-dance-floor", "What do you do when the dance floor is empty ten minutes into open dancing? Where did you learn that?"),
    ("longest-toast", "What is the longest toast you ever had to rescue? How do you end one kindly?"),
    ("first-time-on-the-mic", "What do you remember about the first time you held the microphone at a wedding? What would you tell yourself now?"),
    ("timeline-fell-apart", "When did a reception timeline last fall apart on you? What did you do in the first minute?"),
    ("oldest-guests", "How do you get the oldest guests onto the dance floor? Who taught you that?"),
    ("nervous-best-man", "How do you calm a nervous best man five minutes before the speech? What do you say?"),
    ("one-question-for-couples", "What is the one question you always ask a couple before the wedding? What has the answer changed?"),
    ("song-too-early", "Is there a song you have learned never to play too early in the night? How did you learn that?"),
    ("reading-the-room", "How do you read a room in the first ten minutes? What are you looking at?"),
    ("sound-goes-out", "What is your plan when the sound goes out in the middle of the night? Have you ever had to use it?"),
    ("favorite-planner", "What makes a wedding planner great to work with? What did one teach you?"),
    ("last-song", "How do you choose the last song of the night? What do you want people to feel walking out?"),
    ("new-dj-mistake", "What is the mistake you see most when you coach new wedding DJs? When did you last make it yourself?"),
    ("the-moment-it-clicked", "When did someone you coach finally get it? What changed for them?"),
    ("saying-no", "When did you last say no to a couple's request? How did you say it?"),
    ("before-the-grand-entrance", "What goes through your head in the quiet moment just before the couple walks in?"),
    ("two-families", "How do you bring two families who have never met onto one dance floor?"),
    ("outdoor-weddings", "What have you learned from outdoor weddings? What do you pack now that you never packed before?"),
    ("why-lark-and-lantern", "Why did you start Lark & Lantern? What were you hoping for?"),
    ("drive-home", "What do you think about on the drive home after a great wedding?"),
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
            meta={"craft_page": True, "site": "wikipedia.org"},
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
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane B, wedding_news)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane B anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:24} {lesson[:90]}")
    print(f"\n[curated_clip] {len(PAGES)} party craft pages (lane C, party_craft)")
    for _key, title, url, _lesson in PAGES:
        print(f"  {title}  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} prompts (lane A, dance_floor_stories)")
    for key, question in STORY_SEEDS:
        print(f"  {key:28} {question}")
    print(f"\n[editorial_settings] videos_per_week -> {VIDEOS_PER_WEEK}")


def print_live_steps(ws: str) -> None:
    print("\nAfter --apply, create the schedule through the API (not SQL), as ziv on the VPS.")
    print("Weekly only: a demo workspace gets no daily evidence run, so it costs nothing on a quiet day.")
    body = (
        '{"enabled":true,"cadence":"weekly","weekday":0,"local_time":"07:30",'
        f'"timezone":"{TIMEZONE}","catchup_days":2,"final_stage":"drafting","window_days":7}}'
    )
    print(
        "  curl -s -X PUT http://127.0.0.1:8200/api/v1/content-runs/schedule/weekly-content "
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
    from tce.editorial.lane_profile import WEDDING_COACH

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in WEDDING_COACH.lanes))
    pages = sorted(PAGES, key=lambda c: _rotation(c[0], week))[: WEDDING_COACH.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: WEDDING_COACH.reserve_per_lane]
    print(f"\nA dance_floor_stories - {len(seeds)} prompts rotated in this week:")
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
        print("\nB wedding_news - recent feed items that touch her anchors (top 10; the "
              "matcher and the gates decide):")
        for _n, name, title, hits in found[:10]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nB wedding_news - add --network to read the feeds")
    print(f"\nC party_craft - {len(pages)} pages rotated in this week:")
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
                                          label="Demo wedding coach lanes"))
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
    parser.add_argument("--workspace", default=DEMO_WORKSPACE)
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
