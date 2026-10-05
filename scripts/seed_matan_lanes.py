# ruff: noqa: E501 - the seed data (Hebrew prompts, clip lines) reads better unwrapped
"""Seed Matan's three idea lanes (a profiled workspace, see tce.editorial.lane_profile).

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  trend_reaction  event-industry feeds (US, UK/EU, Japan, Germany, magic press)
                          plus standing facts about his work, the only route by which a
                          world trend can be anchored to an Israeli event performer
  lane B  magic_clip      real, published clips by great magicians and mentalists
  lane C  behind_scenes   Hebrew story seeds he fills from his own memory

Also: the workspace strategy (Hebrew, replaces the owner strategy file) and
videos_per_week 5 (his minimum; more is allowed). Schedules are created through the
API, not here; the commands are printed. A feed taken out of FEEDS and listed in
RETIRED_FEEDS is switched off (enabled=false, the row and its items kept) by --apply.

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python scripts/seed_matan_lanes.py                 # dry run
    PYTHONPATH=src python scripts/seed_matan_lanes.py --check         # fetch every feed and clip
    PYTHONPATH=src python scripts/seed_matan_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python scripts/seed_matan_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime

MATAN_WORKSPACE = "40c0f179-7d5e-4397-b4de-b0b2f3e96fc2"
AUTHOR = "matan-lanes-seed"
# 5-Oct (Ziv): a minimum of five videos recorded a week; more is allowed, never capped.
VIDEOS_PER_WEEK = 5

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# אסטרטגיית תוכן - מתן, מנטליסט ואמן אירועים

## למי זה מדבר
ישראלים שמזמינים אירועים או מגיעים אליהם: זוגות לפני חתונה, הורים לבר ובת מצווה, \
מנהלות HR ומפיקי אירועי חברה, וכל מי שסקרן לגבי מנטליזם. גם קהלים דוברי אנגלית ותיירים.

## שלושה מסלולים, 15 רעיונות בשבוע (5 בכל מסלול)
מינימום 5 סרטונים מוקלטים בשבוע. יותר זה מצוין.

1. **טרנד מהעולם** (5 בשבוע): טרנד או אטרקציה אמיתיים מתעשיית האירועים בעולם \
(ארה"ב, יפן, גרמניה ועוד), ומתן מגיב כאמן אירועים ישראלי. חייב להיות קשור לאירועים \
בישראל או למנטליזם. טרנד בלי קשר כזה נפסל ("ביפן זורקים כדורי תפוחי אדמה - מה זה קשור אליי?"). \
מה שעובד: השתתפות של הקהל, אירועים קטנים ואינטימיים שבהם הקסם קרוב. \
מה שלא: טרנד של גאדג'ט או טכנולוגיה (רובוט שמצייר את האורחים, אפליקציה, AI) שלא קשור לאמן חי.
2. **קליפ של קוסם** (5 בשבוע): קליפ של קוסם או מנטליסט גדול. מה מתן חושב שקרה \
מנקודת המבט של הקהל, למה זה עובד על קהל, ומה הוא היה משנה לקהל ישראלי. \
**אף פעם לא חושפים שיטה**, לא רומזים ולא מנחשים איך זה נעשה. \
לא פעלולי מניפולציה פסיכולוגית גדולים (כמו השוד של דרן בראון) - זה לא הסגנון שלו.
3. **מאחורי הקלעים** (5 בשבוע): זרע של סיפור מהחיים של מנטליסט, כשאלה שמתן \
עונה עליה מהזיכרון האמיתי שלו. **אף פעם לא ממציאים אירוע** כאילו קרה לו. \
המסלול הכי חזק שלו: רגעים אמיתיים מהופעות.

## קול
עברית מדוברת, חמה, משחקית, הומור עצמי. קצר. בלי קופי שיווקי מתורגם.

## אסור
- לחשוף או להסביר שיטה של קסם.
- להמציא סיפורים, קהלים או מספרים.
- שמות או פרטים של לקוחות ולידים.
- ללעוג לקוסמים אחרים.
- מחירים, הנחות, קריאה לפעולה (בלי "תזמינו", "שלחו הודעה", "לינק בביו").
"""

# --------------------------------------------------------------------------- lane A

# (name, url, kind, tier, vendor). Each was fetched and parsed on 5-Oct-2026
# (scripts/seed_matan_lanes.py --check). Tier 1b: citable trade press.
FEEDS: list[tuple[str, str, str, str, str | None]] = [
    ("BizBash (US events)", "https://www.bizbash.com/rss.xml", "rss", "1b", "bizbash"),
    ("Special Events (US)", "https://www.specialevents.com/rss.xml", "rss", "1b", "special events"),
    ("Skift Meetings (US)", "https://meetings.skift.com/feed/", "rss", "1b", "skift"),
    ("Smart Meetings (US)", "https://www.smartmeetings.com/feed", "rss", "1b", "smart meetings"),
    ("PCMA Convene (US)", "https://www.pcma.org/feed/", "rss", "1b", "pcma"),
    ("Green Wedding Shoes (US weddings)", "https://greenweddingshoes.com/feed/", "rss", "1b",
     "green wedding shoes"),
    ("Event Industry News (UK/EU)", "https://www.eventindustrynews.com/feed", "rss", "1b",
     "event industry news"),
    ("Blooloop (attractions, worldwide)", "https://blooloop.com/feed/", "rss", "1b", "blooloop"),
    ("SoraNews24 (Japan trends)", "https://soranews24.com/feed/", "rss", "1b", "soranews24"),
    ("event partner (Germany)", "https://www.event-partner.de/feed/", "rss", "1b",
     "event partner"),
]

# Feeds taken out of the seed; --apply switches each off (enabled=false). The row and
# the items it already brought in are kept for history.
RETIRED_FEEDS: dict[str, str] = {
    # 5-Oct (Ziv): Genii's items are trick reviews, not event-industry trends.
    "https://geniimagazine.com/feed/": "trick-review items, not event-industry trends",
}


def retire_feeds(existing: dict) -> list[str]:
    """Switch off every enabled feed of the workspace that RETIRED_FEEDS names.
    Returns the names switched off (none when they already are)."""
    out = []
    for url, feed in existing.items():
        if url in RETIRED_FEEDS and getattr(feed, "enabled", False):
            feed.enabled = False
            out.append(feed.name)
    return out

# The anchors for lane A, in categories, never client names. English terms, because
# the feeds are English and German trade press and the matcher reads their words.
# (anchor_kind, anchor_term, lesson)
STANDING_FACTS: list[tuple[str, str, str]] = [
    ("client_solution", "mentalism show", "Matan performs mentalism (mind reading) shows at events."),
    ("client_solution", "strolling magic", "Matan does close-up strolling magic between guests at events."),
    ("client_solution", "wedding entertainment", "Matan entertains guests at Israeli weddings."),
    ("client_solution", "bar mitzvah", "Matan performs at bar and bat mitzvah celebrations."),
    ("client_solution", "corporate event", "Matan performs at company events and team days."),
    ("client_solution", "holiday party", "Matan performs at Hanukkah and Purim company parties."),
    ("client_solution", "english-speaking audiences", "Matan performs for English-speaking audiences and tourist groups in Israel."),
    ("client_solution", "stage show", "Matan performs on stage as well as table to table."),
    ("problem_pattern", "guest experience", "Event hosts want every guest, not only the front row, to feel part of the show."),
    ("problem_pattern", "last-minute booking", "Clients often book entertainment at the last minute, over WhatsApp."),
    ("problem_pattern", "event entertainment", "Hosts look for entertainment that makes an event memorable and different."),
    ("problem_pattern", "interactive experience", "Audiences now expect interactive experiences, not only a show to watch."),
    ("problem_pattern", "skeptical audience", "Some guests arrive skeptical about mind reading and magic."),
    ("problem_pattern", "family celebration", "Family celebrations mix ages, from children to grandparents, in one room."),
    ("problem_pattern", "event trends", "Event planners follow world event trends to keep their events fresh."),
]

# --------------------------------------------------------------------------- lane B

# (key, performer, title, year, url, why it plays). Each URL answered YouTube oEmbed
# 200 on 5-Oct-2026; official channels preferred. `year` is the performance year
# where it is documented in the clip's own title, otherwise the upload year
# (marked "upload"). No method text is stored anywhere.
CLIPS: list[tuple[str, str, str, str, str, str]] = [
    ("shin-lim-fool-us", "Shin Lim", "Penn & Teller: Fool Us", "2015",
     "https://www.youtube.com/watch?v=EAN-PwRfJcA",
     "קלפים בלי מילה אחת, רק מוזיקה ותנועה - הוכחה שקסם יכול לעבוד בלי טקסט בכלל."),
    ("shin-lim-agt-audition", "Shin Lim", "America's Got Talent audition", "2018",
     "https://www.youtube.com/watch?v=LiUpSgSrUts",
     "קלוז-אפ מול שופטים ומיליוני צופים - איך קסם קטן של שולחן מחזיק במה ענקית."),
    ("blaine-levitation", "David Blaine", "Levitation (Street Magic)", "1997",
     "https://www.youtube.com/watch?v=w6CNvFnlPL0",
     "הקסם הוא בכלל התגובות של האנשים ברחוב - בלייז הפך את הקהל לכוכבי הסרטון."),
    ("copperfield-flying", "David Copperfield", "Flying - Live the Dream", "1992",
     "https://www.youtube.com/watch?v=8CehjowD-Xw",
     "אשליה ענקית עם סיפור רגשי של חלום לעוף - מראה כמה הסיפור חשוב יותר מהאפקט."),
    ("dynamo-thames", "Dynamo", "Walks across the River Thames", "2011",
     "https://www.youtube.com/watch?v=5rYvc86rCJU",
     "רגע ציבורי מול עוברים ושבים ואוטובוס תיירים - קסם שהופך לאירוע תקשורתי."),
    ("suchard-corden", "Lior Suchard", "Bends Harry Connick Jr. and Alice Eve's minds (Late Late Show)",
     "2017 upload", "https://www.youtube.com/watch?v=J94uO-urSTg",
     "מנטליסט ישראלי באולפן אמריקאי - הומור, קצב ומשחק עם סלבס שמשתפים פעולה."),
    ("suchard-ellen", "Lior Suchard", "Wows Ellen with emojis", "2020 upload",
     "https://www.youtube.com/watch?v=nCtR9T0wKms",
     "מנטליזם עם משהו יומיומי כמו אימוג'י - קריאת מחשבות שמרגישה עכשווית."),
    ("geller-carson", "Uri Geller", "The Tonight Show with Johnny Carson", "1973",
     "https://www.youtube.com/watch?v=zD7OgAdCObs",
     "ההופעה הישראלית הכי מפורסמת בטלוויזיה האמריקאית - ומה קורה כשרגע לא מצליח מול קהל."),
    ("oz-pearlman-agt", "Oz Pearlman", "America's Got Talent", "2015",
     "https://www.youtube.com/watch?v=SqY7zmDYPK4",
     "מנטליסט שקורא את השופטים עצמם - הקהל מרגיש שזה קורה לאנשים שהוא מכיר."),
    ("clairvoyants-agt", "The Clairvoyants", "America's Got Talent audition", "2016",
     "https://www.youtube.com/watch?v=RvyK-HTNJL8",
     "צמד מנטליזם עם דרמה וקצב - איך זוג על הבמה יוצר מתח שאי אפשר ליצור לבד."),
    ("eric-chien-fism", "Eric Chien", "FISM Grand Prix act", "2018",
     "https://www.youtube.com/watch?v=CvzMqIQLiXE",
     "מופע תחרותי ברמה עולמית - דיוק, אסתטיקה ואיך קסם נראה כשהוא כמו מחול."),
    ("ricky-jay-conan", "Ricky Jay", "Cards as weapons with Conan and Jackie Chan", "2021 upload",
     "https://www.youtube.com/watch?v=4F93VCA_TCQ",
     "אגדת קלפים בתוכנית אירוח - כריזמה, סיפור והיסטוריה של המקצוע."),
    ("darcy-oake-bgt", "Darcy Oake", "Dove illusions, Britain's Got Talent", "2014",
     "https://www.youtube.com/watch?v=gO_KyTtJg10",
     "אחד הקליפים הנצפים בעולם - פתיחה חזקה שתופסת את הקהל בשניות הראשונות."),
    ("richard-jones-bgt-final", "Richard Jones", "Britain's Got Talent grand final", "2016",
     "https://www.youtube.com/watch?v=K786WSkT0xU",
     "קוסם חייל שמספר סיפור אישי דרך קסם - רגש מנצח במה גדולה."),
    ("colin-cloud-agt", "Colin Cloud", "Real-life Sherlock Holmes, America's Got Talent", "2017",
     "https://www.youtube.com/watch?v=R5uZQxEUyMc",
     "מנטליסט עם דמות ברורה - איך פרסונה חזקה עושה את קריאת המחשבות לבלתי נשכחת."),
    ("mat-franco-agt", "Mat Franco", "America's Got Talent audition", "2014",
     "https://www.youtube.com/watch?v=5-uZsYGFJMk",
     "קסם קלפים שמספר סיפור אישי - הקהל זוכר את הסיפור יותר מהקלפים."),
    ("marc-spelmann-bgt", "Marc Spelmann", "Golden Buzzer audition, Britain's Got Talent", "2018",
     "https://www.youtube.com/watch?v=Q3jege0p0dQ",
     "מנטליזם רגשי מאוד - איך מופע קטן יכול לרגש אולם שלם."),
    ("tommy-cooper-glass-bottle", "Tommy Cooper", "Glass bottle, bottle glass", "2023 upload",
     "https://www.youtube.com/watch?v=FgMnbgikxXU",
     "קוסם שהכישלון הוא הבדיחה - הומור עצמי כחלק מהמופע."),
    ("teller-shadows", "Penn & Teller", "Shadows (Penn & Teller: Fool Us)", "2015",
     "https://www.youtube.com/watch?v=P8e_1v8mAGY",
     "קטע שקט ופואטי בלי מילה - איך יוצרים אווירה ולא רק 'וואו'."),
    ("tamariz-1989", "Juan Tamariz", "The Best of Magic", "1989",
     "https://www.youtube.com/watch?v=alfwdvQaLIE",
     "אחד מגדולי קסם הקלפים - אנרגיה מטורפת ושליטה מלאה בקהל."),
    ("max-maven-esp", "Max Maven", "Stand-up ESP", "2018 upload",
     "https://www.youtube.com/watch?v=uJLTnoGCkng",
     "מנטליזם קלאסי לכל הקהל בבת אחת - כל אחד באולם מרגיש שזה קרה לו."),
]

# --------------------------------------------------------------------------- lane C

# Story SEEDS: questions he answers from his own memory, never events. Derived from
# his voice profile's recurring themes and values (live row, 4-Oct-2026).
STORY_SEEDS: list[tuple[str, str]] = [
    ("first-time-mentalist", "מה אנשים עושים ברגע שהם שומעים שאתה מנטליסט? איזו תגובה הכי מצחיקה קיבלת?"),
    ("new-dad-shows", "איך נראה ערב הופעה מאז שנהיית אבא טרי? מה השתנה ברגע שאתה יוצא מהבית?"),
    ("whatsapp-last-minute", "ספר על הזמנה של רגע אחרון בוואטסאפ שזכורה לך. מה עבר לך בראש כשקראת את ההודעה?"),
    ("skeptic-to-fan", "תחשוב על סקפטי שהפך למעריץ באמצע הופעה. מה ראית על הפנים שלו ברגע שזה קרה?"),
    ("aunt-rivka", "מי ה'דודה רבקה' שיושבת בצד באירועים שלך, ומה אתה עושה כדי שגם היא תרגיש שהקסם קרה לה?"),
    ("hanukkah-party", "מה מיוחד בהופעה במסיבת חנוכה של חברה, לעומת חתונה? איזה רגע מחנוכה נשאר איתך?"),
    ("purim-costumes", "איך זה להופיע מול קהל שכולו בתחפושות פורים? מה הכי הפתיע אותך שם?"),
    ("english-audience", "מה שונה כשאתה מופיע מול קהל דובר אנגלית או קבוצת תיירים? מה עובד אחרת?"),
    ("audience-face", "תחשוב על פרצוף של קהל שאתה זוכר: מה הרגע שבשבילו אתה עושה את כל זה?"),
    ("stage-vs-table", "במה גדולה או שולחן קרוב - איפה אתה מרגיש הכי אתה, ולמה?"),
    ("before-show-ritual", "מה אתה עושה בחצי השעה לפני שאתה עולה להופיע? יש לך טקס קבוע?"),
    ("what-didnt-work", "תחשוב על רגע שקטע לא עבד כמו שתכננת. מה עשית ברגע עצמו, ומה למדת?"),
    ("first-show", "איך נראתה ההופעה הראשונה שלך בתשלום? מה אתה זוכר ממנה?"),
    ("why-mentalism", "למה דווקא מנטליזם ולא קסם רגיל? מתי הבנת שזה הכיוון שלך?"),
    ("kids-at-events", "מה קורה כשילדים מגיעים להופעה שתוכננה למבוגרים? איך אתה מתאים את עצמך?"),
    ("did-you-really-read", "מה אתה עונה כשמישהו שואל אותך אחרי הופעה אם אתה באמת קורא מחשבות?"),
    ("anniversary-guests", "איך זה להופיע בחגיגה של זוג מבוגר, כמו יום נישואין? מה אתה מרגיש מול דורות שלמים בחדר?"),
    ("road-between-events", "מה עובר לך בראש בנסיעה הביתה אחרי אירוע מוצלח? ואחרי אירוע קשה?"),
    ("family-reaction", "איך המשפחה שלך הגיבה כשסיפרת שאתה הולך להיות מנטליסט? זה השתנה עם הזמן?"),
    ("no-pressure-booking", "איך אתה מדבר עם מישהו שמתלבט אם להזמין אותך, בלי ללחוץ עליו?"),
]


# --------------------------------------------------------------------------- building


def lane_items() -> list:
    from tce.editorial.lane_seeds import LaneItem

    items = [
        LaneItem(
            kind="curated_clip",
            key=key,
            title=f"{performer} - {title} ({year})",
            lesson=why,
            url=url,
            language="he",
            meta={"performer": performer, "clip_title": title, "year": year},
        )
        for key, performer, title, year, url, why in CLIPS
    ]
    items += [
        LaneItem(
            kind="story_seed",
            key=key,
            title=question[:120],
            lesson=question,
            language="he",
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
          f"({len(STRATEGY_MD)} chars, Hebrew)")
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane A)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    for url, why in RETIRED_FEEDS.items():
        print(f"  [retired, switched off by --apply] {url}  ({why})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane A anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:28} {lesson}")
    print(f"\n[curated_clip] {len(CLIPS)} clips (lane B)")
    for _key, performer, title, year, url, _why in CLIPS:
        print(f"  {performer} - {title} ({year})  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} seeds (lane C)")
    for key, question in STORY_SEEDS:
        print(f"  {key:22} {question}")
    print(f"\n[editorial_settings] videos_per_week -> {VIDEOS_PER_WEEK}")


def print_live_steps(ws: str) -> None:
    print("\nAfter --apply, create the schedules through the API (not SQL), as ziv on the VPS:")
    for name, cadence, at, final in (
        # 5-Oct: his scripts are written by his own lane writer, so the week runs on to
        # drafting (exporting stays refused for a lane workspace).
        ("weekly-content", "weekly", "07:30", "drafting"),
        ("daily-evidence", "daily", "07:15", "extracting"),
    ):
        body = (
            f'{{"enabled":true,"cadence":"{cadence}","weekday":0,"local_time":"{at}",'
            f'"timezone":"Asia/Jerusalem","catchup_days":7,"final_stage":"{final}","window_days":7}}'
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
        for _key, performer, title, _year, url, _why in CLIPS:
            r = await client.get(
                "https://www.youtube.com/oembed", params={"url": url, "format": "json"}
            )
            if r.status_code != 200:
                print(f"  FAIL  clip {performer} - {title}: oEmbed HTTP {r.status_code}")
                bad += 1
                continue
            data = r.json()
            print(f"  ok    clip {performer} - {title}: \"{data.get('title', '')[:60]}\" "
                  f"by {data.get('author_name')}")
    total = len(FEEDS) + len(CLIPS)
    print(f"\n{total - bad}/{total} feeds and clips answered")
    return 1 if bad else 0


# --------------------------------------------------------------------------- sample


def _rotation(key: str, week: str) -> str:
    return hashlib.sha256(f"{week}:{key}".encode()).hexdigest()


async def sample_week(network: bool) -> None:
    """The evidence a coming week would draw on, per lane. Not the model's ideas:
    those need the subscription worker (the live LLM queue), which this never calls."""
    from tce.editorial.common import current_week_start
    from tce.editorial.lane_profile import PERFORMER

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in PERFORMER.lanes))
    clips = sorted(CLIPS, key=lambda c: _rotation(c[0], week))[: PERFORMER.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: PERFORMER.reserve_per_lane]
    if network:
        import httpx

        from tce.news.feeds import parse_feed

        terms = [t.lower() for _k, t, _l in STANDING_FACTS] + [
            "wedding", "magic", "magician", "mentalis", "entertain", "party", "show",
            "immersive", "interactive", "guest", "festival", "attraction",
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
                for it in items[:15]:
                    text = f"{it.title} {getattr(it, 'summary', '') or ''}".lower()
                    hits = [t for t in terms if t in text]
                    if hits:
                        found.append((len(hits), name, it.title, hits[:3]))
        found.sort(reverse=True)
        print("\nA trend_reaction - recent feed items that touch his anchors (top 8; the "
              "matcher and the relevance gate decide):")
        for _n, name, title, hits in found[:8]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nA trend_reaction - add --network to read the feeds")
    print(f"\nB magic_clip - {len(clips)} clips rotated in this week:")
    for _key, performer, title, year, url, why in clips:
        print(f"  {performer} - {title} ({year}) {url}\n      {why}")
    print(f"\nC behind_scenes - {len(seeds)} seeds rotated in this week:")
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
                                          label="Matan performer lanes"))
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
        print(f"clips and seeds: {counts}")
        await session.commit()

        settings_row_count = await lineup.set_videos_per_week(session, ws, VIDEOS_PER_WEEK)
        await session.commit()
        print(f"videos_per_week: {VIDEOS_PER_WEEK} ({settings_row_count})")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=MATAN_WORKSPACE)
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="the default; kept explicit")
    parser.add_argument("--check", action="store_true", help="fetch every feed and clip")
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
