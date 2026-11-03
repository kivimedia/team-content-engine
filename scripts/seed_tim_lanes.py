# ruff: noqa: E501 - the seed data (lessons, prompts) reads better unwrapped
"""Seed Tim Huckabee's three idea lanes (the `florist_coach` lane profile).

Dry run by default: prints every row it would write and writes nothing. Idempotent:
running it twice with --apply writes nothing the second time.

  lane A  from_my_courses  one lesson from his own courses (15 Minute Florist, the
                           mystery shopper calls, the Profitable Florists Club, TOTAL
                           Training, the Prosperity Path); stored as curated_clip, the
                           lesson page on theprofitableflorist.com is the citation
  lane B  coaching_room    prompts from what florists bring him in coaching, questions
                           he answers from his own memory (story_seed)
  lane C  smart_ideas      clever sales ideas of small businesses close to florists in
                           the news, plus standing facts about his own teaching as anchors

Also: the workspace strategy (English, replaces the owner strategy file) and
videos_per_week 3. His creator, voice and brand profiles are seeded by SQL
(scripts/seed_tim_profiles.sql): those models carry no workspace column.

Sources (03-Nov-2026): the lessons come from his course library as CourseIQ captured
it for Riley (BloomLine KB, global florist sources, May 2026); the prompts from the
themes of his 21 Prosperity Path group coaching sessions (Oct 2025 to Mar 2026), never
naming a shop; lanes A and B are the pillars of his 22-Oct plan with Ziv, lane C is
Ziv's third pillar (03-Nov: "smart business ideas on micro niches that are close to
florists"). Ivy's archive of 1:1 session transcripts can add prompts later.

Usage (on the VPS, from the app directory):
    PYTHONPATH=src python scripts/seed_tim_lanes.py                 # dry run
    PYTHONPATH=src python scripts/seed_tim_lanes.py --check         # fetch every feed and page
    PYTHONPATH=src python scripts/seed_tim_lanes.py --sample-week   # what a week would draw on
    PYTHONPATH=src python scripts/seed_tim_lanes.py --apply         # write
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

TIM_WORKSPACE = "34944494-e003-4852-bc69-de7607bcbdb0"
AUTHOR = "tim-lanes-seed"
VIDEOS_PER_WEEK = 3
# His coaching hour and his buyers run on New York time (plan v6, 22-Oct).
TIMEZONE = "America/New_York"
PAGE_USER_AGENT = "TCE-seed/1.0 (https://kivimedia.co)"
# His lesson pages are for members: a visitor is sent to the login page (302), which
# still proves the lesson is his and is live.
SITE_HOST = "theprofitableflorist.com"
COURSE_PAGE = "https://theprofitableflorist.com/course/15-minute-florist-classes/"

# --------------------------------------------------------------------------- strategy

STRATEGY_MD = """<!-- tce-strategy: replace -->
# Content strategy - Tim Huckabee, The Profitable Florist

## Who it speaks to
Flower shop owners, managers and the people who take their orders, on the phone and \
at the counter. Also owners of other small shops who want the same results.

## Three lanes, 15 ideas a week (5 in each)
3 videos posted a week. He films 6 scripts every two weeks on his phone, reading each \
batch aloud first. One to two minutes once edited.

1. **From your courses** (5 a week): one lesson from his own courses (15 Minute \
Florist first), said simply with one plain example of what the person taking the \
order says or does.
2. **From the coaching room** (5 a week): what florists bring him in coaching. Each \
idea is a question he answers from his own memory. Never an invented story.
3. **Smart ideas from other shops** (5 a week): a clever sales or profit idea a small \
business outside the flower trade used (a toy shop, a restaurant, a bakery), and what \
a flower shop can take from it this week. It shows him as an expert in selling and \
running a small shop, not only in flowers.

## Voice
Direct, warm and practical, a seasoned shop owner talking to another one across the \
counter. Plain words, short sentences, a little dry humor. Concrete: what the customer \
says, what the person on the phone says back, what goes in the arrangement.

## Never
- Invent stories, shops, owners, customers, quotes or numbers.
- Name the shops he coaches, their owners, their staff or their customers.
- His own fees.
- A call to action ("book a call", "DM me", "link in bio").
- Politics, elections, war, crime or tragedy.
"""

# --------------------------------------------------------------------------- lane C

# (name, url, kind, tier, vendor). Each answered with fresh items on 03-Nov-2026
# (7 to 12 items, most of them inside 48 hours). Date-ordered like Brant's
# (`qft=sortbydate="1"`); feeds.unwrap_click_tracker turns each link into the article.
_BING_BY_DATE = "&format=rss&qft=sortbydate%3d%221%22"


def _bing(name: str, query: str) -> tuple[str, str, str, str, str]:
    return (f"Bing News: {name}", f"https://www.bing.com/news/search?q={query}{_BING_BY_DATE}",
            "rss", "1b", "bing news")


FEEDS: list[tuple[str, str, str, str, str | None]] = [
    _bing("small business owner ideas", "small+business+owner+idea+customers"),
    _bing("toy store owners", "toy+store+owner"),
    _bing("bakery owners", "bakery+owner+customers"),
    _bing("restaurant owner ideas", "restaurant+owner+idea+customers"),
    _bing("gift shop owners", "gift+shop+owner"),
    _bing("boutique owners", "boutique+owner+customers"),
    _bing("coffee shop owner ideas", "coffee+shop+owner+idea"),
    _bing("local shop sales", "local+shop+owner+sales"),
    _bing("small business holiday sales", "small+business+holiday+sales"),
    _bing("Small Business Saturday", "small+business+saturday"),
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


# The anchors for lane C. A news item is only citable through a standing fact, so every
# term of docs/news-anchors-florist-coach.md has one here, with the SAME kind. Grouped:
# one lesson, several terms. Facts about Tim are his own words and his own courses.
_THIRTY = "Tim has worked with flower shops for 30 years (his words on his 21-Oct-2026 call: \"I've been doing this for 30 years\"), and he coaches shop owners across the US and Canada."
_REPEAT = "Tim teaches florists that the next sale comes from customers who already bought: reminder calls for last year's birthdays and anniversaries, follow-up calls and their own subscription service."
_ADDON = "Tim teaches florists to recommend a price point by size, never to ask for a budget, and to offer a finishing touch on every order."
_DISPLAY = "Tim calls the cooler a store within a store: what customers see in it and in the shop decides what they buy."
_HOLIDAY = "Tim teaches florists to plan every holiday months ahead, with Valentine's Day, Mother's Day, Thanksgiving and Christmas sales tips in his 15 Minute Florist classes."
_SERVICE = "Tim's mystery shopper calls grade how a shop answers: listen to the customer's need, not just their words."
_OTHERS = "Smart ideas from other shops looks at small businesses outside the flower trade and asks what a flower shop could copy this week."

_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    ("client_solution", ("loyalty program", "loyalty programs", "loyalty card", "loyalty cards",
                         "punch card", "punch cards", "rewards program"), _REPEAT),
    ("client_solution", ("subscription box", "subscription boxes", "subscription service"), _REPEAT),
    ("client_solution", ("repeat customers", "regular customers"), _REPEAT),
    ("client_solution", ("pop-up shop", "pop-up shops", "holiday open house", "small business saturday",
                         "shop small", "shop local"), _HOLIDAY),
    ("client_solution", ("window display", "window displays", "foot traffic"), _DISPLAY),
    ("client_solution", ("upsell", "upselling"), _ADDON),
    ("client_solution", ("independent retailer", "independent retailers", "independent bookstore",
                         "independent toy store"), _OTHERS),
    ("client_solution", ("toy store owner", "toy shop owner", "bakery owner", "cafe owner",
                         "coffee shop owner", "restaurant owner", "restaurant owners", "gift shop owner",
                         "boutique owner", "bookstore owner", "garden center owner"), _OTHERS),
    ("problem_pattern", ("toy store", "toy shop", "bakery", "bakeries", "restaurant", "restaurants", "cafe",
                         "coffee shop", "gift shop", "boutique", "bookstore", "garden center"), _OTHERS),
    ("problem_pattern", ("small business", "small businesses", "small business owner",
                         "small business owners", "local business", "local businesses", "shop owner",
                         "shop owners", "store owner", "store owners", "business owner", "business owners"),
     _THIRTY),
    ("problem_pattern", ("customers",), _SERVICE),
    ("problem_pattern", ("holiday sales", "holiday shoppers"), _HOLIDAY),
    ("problem_pattern", ("add-on", "add-ons", "bundle", "bundles"), _ADDON),
]

STANDING_FACTS: list[tuple[str, str, str]] = [
    (kind, term, lesson) for kind, terms, lesson in _GROUPS for term in terms
]

# --------------------------------------------------------------------------- lanes A and B

# (key, title, url, lesson, course). Lessons from his own courses, each one a single idea
# true to the course text in the BloomLine KB (CourseIQ, May 2026).
LESSONS: list[tuple[str, str, str, str, str]] = [
    ("never-ask-what-they-want-to-spend", "Never ask what they want to spend",
     "https://theprofitableflorist.com/lesson/never-ask-for-a-customers-budget/",
     "Tim says never ask \"How much do you want to spend?\" Listen to the customer, suggest a design that fits the occasion, and if the price does not work, let them tell you and then offer something smaller.",
     "15 Minute Florist"),
    ("describe-the-design-then-the-price", "Describe the arrangement, then say the price",
     "https://theprofitableflorist.com/lesson/never-ask-for-a-customers-budget/",
     "Describe the size, the design style and the colors first, and put the price last. For example, a large vase of garden flowers in bright summer colors that is the right size for a dining room table.",
     "15 Minute Florist"),
    ("make-three-sizes-clearly-different", "Make your three sizes clearly different",
     "https://theprofitableflorist.com/lesson/never-ask-for-a-customers-budget/",
     "Offer small, medium and large, and keep the price gaps big enough that each size looks different to the customer. Three prices that sit close together look like the same arrangement.",
     "15 Minute Florist"),
    ("take-the-card-message-first", "Take the card message before the flowers",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Ask what the customer wants the card to say before you talk about the product. The card shows you the occasion, how many people are sending it, and clues about how big the order can be.",
     "15 Minute Florist"),
    ("offer-a-finishing-touch-dont-ask", "Offer a finishing touch, do not ask",
     "https://theprofitableflorist.com/lesson/upselling-101/",
     "Skip \"Do you want to add anything else?\" Say \"As a finishing touch, I can attach an I love you balloon to her roses,\" and always say the price so the customer can decide on the spot.",
     "15 Minute Florist"),
    ("listen-for-big-order-cues", "Listen for cues that call for a bigger arrangement",
     "https://theprofitableflorist.com/lesson/upselling-101/",
     "Clues like a \"huge birthday,\" a milestone anniversary, \"I can't be there,\" or many names on the card tell you to start with the large size. If the customer says no, do not push twice.",
     "15 Minute Florist"),
    ("call-the-funeral-home-every-time", "Call the funeral home every time",
     "https://theprofitableflorist.com/lesson/selling-sympathy-101/",
     "On every sympathy order, call the funeral home or church to confirm the service time and details, even if the family just came from there. Also check the spelling of every name and read the card back.",
     "15 Minute Florist"),
    ("sell-a-color-and-season-out-of-town", "Sell a color and season on out-of-town orders",
     "https://theprofitableflorist.com/lesson/selling-outgoing-orders/",
     "When an order goes to a shop in another city, sell an open order. Pick the color scheme and the season, and let that shop's florist use its best flowers instead of promising certain flowers or containers.",
     "15 Minute Florist"),
    ("answer-a-picture-request", "How to answer a request for a picture",
     "https://theprofitableflorist.com/lesson/when-customers-want-you-to-send-a-picture/",
     "If your shop sends pictures, say it goes out as the flowers leave and confirm the email address. If you do not offer it, say so kindly and remind the customer the flowers will be fresh and look just like you described.",
     "15 Minute Florist"),
    ("when-the-caller-wants-the-owner", "When a caller asks for the owner",
     "https://theprofitableflorist.com/lesson/when-customers-must-speak-with-the-owner/",
     "Say the owner is not available but you can help. Pull the caller up in the system, mention how long they have shopped with you, and promise to take great care of the order.",
     "15 Minute Florist"),
    ("answer-a-bad-review-in-three-sentences", "Answer a bad review in three sentences",
     "https://theprofitableflorist.com/lesson/when-customers-leave-bad-reviews/",
     "Wait at least 30 minutes before you write. Then say you understand they were unhappy, give the facts, and invite them to call. You are writing for future readers, not to change the reviewer's mind.",
     "15 Minute Florist"),
    ("close-every-call-with-a-recap", "Close every call with a four-part recap",
     "https://theprofitableflorist.com/lesson/pos-tips-for-making-quicker-bigger-sales/",
     "Finish with the total, what they ordered, who it goes to, and when it arrives. Say \"total\" by itself, because it already means everything. The recap also catches mistakes, like a wrong delivery date.",
     "15 Minute Florist"),
    ("call-last-years-thanksgiving-buyers", "Call last year's Thanksgiving customers",
     "https://theprofitableflorist.com/lesson/thanksgiving-sales-tips/",
     "Run a delivery report from last year's holiday week and call those customers two to four weeks ahead. Leave a voicemail with their old order number so you can pull up their details fast.",
     "15 Minute Florist"),
    ("use-warm-2700k-bulbs", "Use warm 2700K bulbs in your shop",
     "https://theprofitableflorist.com/lesson/visual-merchandising-101/",
     "Bright daylight bulbs look blue and make flowers look bad. Use 2700K bulbs in the shop, and LED track lights for window displays.",
     "15 Minute Florist"),
    ("customers-buy-colors-not-flowers", "Customers buy colors, not flowers",
     "https://theprofitableflorist.com/lesson/smart-substitutions/",
     "If one flower in a mixed design is missing, swap in one with a similar shape and color and keep the spirit of the design. Only call the customer when the order is all one flower, and then offer two or three specific choices.",
     "15 Minute Florist"),
    ("make-corsages-in-batches", "Make corsages in batches",
     "https://theprofitableflorist.com/lesson/speedy-corsages/",
     "Build the wrist bands first, lay out the flowers for 5 to 10 corsages, and put cold floral adhesive on both surfaces. Wait until the glue looks like earwax, not snot, before you press the pieces together.",
     "15 Minute Florist"),
    ("react-to-the-customers-big-news", "React to the customer's big news",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "When a caller shares news like twins or a graduation, answer with real interest, such as \"How exciting is this? Is this her first child?\" It builds a connection with the customer.",
     "Mystery Shopper Live Calls"),
    ("dont-split-the-price-range", "Do not split the difference on a price range",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "If a customer gives you a price range, do not enter the middle number. Say that the closer you get to the top, the more beautiful flowers your designers can add. It is a gentle way to help, and it is still their decision.",
     "Mystery Shopper Live Calls"),
    ("who-are-we-remembering", "On a funeral call, ask who are we remembering",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Tell the caller you are sorry first, then ask \"Who are we remembering?\" instead of \"What was her name?\" Turn your energy down a notch and give the caller a little extra time.",
     "Mystery Shopper Live Calls"),
    ("delivery-goes-on-top", "Do not lead with the delivery fee",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Tim says you sell two things, the arrangement and the delivery. Build the order first and add delivery on top, instead of bringing up the fee at the start of the call.",
     "Mystery Shopper Live Calls"),
    ("five-to-seven-day-freshness-promise", "Teach a five to seven day freshness promise",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "When a customer says the flowers did not last, start with \"I'm so sorry to hear that.\" At a shop where Tim worked, the promise was five to seven days, as long as the flowers were kept away from heat and sun. A three-day promise is too short.",
     "Mystery Shopper Live Calls"),
    ("compare-sales-by-channel", "Compare web, phone and walk-in order totals",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Pull your average order value for the website, the phone and walk-ins for the last six months. Tim says the gap is your first opportunity, because a website that beats your phone points to staff underselling.",
     "Profitable Florists Club"),
    ("try-the-dumpster-design", "Try the dumpster design test",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Build an arrangement out of yesterday's discarded flowers and show it to your design team the next morning. It proves how much good product is going in the trash.",
     "Profitable Florists Club"),
    ("write-recipes-with-time-targets", "Write fixed recipes with time targets",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Write a recipe for each of your top sellers that says how long it should take, not just how many stems to use. It helps stop overstuffing and keeps your designers on pace.",
     "Profitable Florists Club"),
    ("plan-christmas-in-june", "Start your Christmas plan in June",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Order hard goods early and ask your supplier for an early-bird discount. Tim's plan also has you set staffing, a marketing calendar, add-on extras and sales goals months ahead.",
     "Profitable Florists Club"),
    ("hold-a-monthly-staff-meeting", "Hold a monthly staff meeting with an agenda",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Put a staff meeting on the calendar every month, with phones off and a written agenda. Cover your order totals, how well add-ons are selling, the next holiday timeline, and one idea from your team.",
     "Profitable Florists Club"),
    ("ask-the-two-part-question", "Start with a two-part question",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Open the product talk by asking, \"Do you have a design in mind, or would you like a suggestion?\" Then give one suggestion at a time and ask fewer questions.",
     "TOTAL Training"),
    ("customer-remembers-the-fix", "The customer remembers the fix, not the problem",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "When a customer is upset, pull up the order before you react. Then agree with their feelings, say \"I don't blame you, I'd be angry too,\" and offer one fix instead of asking what they want.",
     "TOTAL Training"),
    ("mothers-day-other-special-ladies", "At Mother's Day, ask about other special ladies",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Before the call ends, ask \"Are there any other special ladies you want to remember?\" Tim also teaches using the word \"celebrate\" to support an upgrade.",
     "TOTAL Training"),
    ("valentines-small-upgrade", "Offer one small upgrade on Valentine's orders",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "After the customer picks an arrangement, offer to add three lilies or another premium touch for one set amount more. It is a small, clear upgrade that is easy to say yes to.",
     "TOTAL Training"),
    ("walk-the-cooler-each-morning", "Walk the cooler every morning",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "At the start of each shift, walk the cooler and pick three ready-made designs to sell hard that day. Sell what you already have.",
     "TOTAL Training"),
    ("call-last-years-birthday-buyers", "Call last year's birthday and anniversary customers",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Run a point of sale report of next week's deliveries from last year and read the card messages to find birthdays and anniversaries. Call them and ask if they want to recreate or update that design, and leave a message if they do not pick up.",
     "The Prosperity Path"),
    ("use-the-celebrate-line", "Use the \"to celebrate\" line for big moments",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "For a birthday, anniversary, graduation, retirement or new home, say that to celebrate it you suggest one of your large designs. It reminds the customer that this is a big deal.",
     "The Prosperity Path"),
    ("say-our-most-popular-size", "Say \"our most popular size is our medium\"",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Do not open with \"our arrangements start at.\" Say that your most popular size is the medium. If a customer insists on a small budget, tell them it will be gorgeous and name the right spot for it, like a desk or bedside table.",
     "The Prosperity Path"),
    ("add-a-luxury-anchor-to-the-cooler", "Add a luxury anchor to your cooler",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Put one luxury design in the cooler priced at least 25 percent above your average order, and tag it \"Our Showstopper of the Week.\" Let the cooler do some of the selling for you.",
     "The Prosperity Path"),
    ("ask-for-reviews-after-delivery", "Ask for reviews one or two days after delivery",
     "https://theprofitableflorist.com/course/15-minute-florist-classes/",
     "Wait one to two days after delivery before you ask for a review, so the flowers have been enjoyed and the sender has heard back. Ask warmly, and pick one day each week to send your requests.",
     "The Prosperity Path"),
]

# Coaching-room SEEDS: questions he answers from his own memory, never events. Each
# from a theme that comes up again and again in the 21 Prosperity Path sessions.
STORY_SEEDS: list[tuple[str, str]] = [
    ("price-points-spaced-too-close", "Think of a florist whose website options all sit ten dollars apart. What do you tell her about spacing the price points, and when did you first see how much that matters?"),
    ("markup-when-costs-spike", "When wholesale costs jump, some florists quietly shrink their markup so prices still feel reasonable. What do you say to them, and what have you seen happen to shops that do it?"),
    ("valentines-price-fear", "Think of an owner who is afraid to charge more for a dozen roses on Valentine's Day because she thinks she will be priced out by the grocery store. What do you tell her?"),
    ("never-ask-the-budget", "Why do you tell florists never to ask a caller \"How much would you like to spend?\", and what do you have them say instead? Where did you first learn that?"),
    ("noisy-shop-on-the-phone", "Picture calling a flower shop and hearing a loud shop behind the person who answers. What does a caller conclude, and what do you tell owners to change first?"),
    ("outbound-calls-staff-pushback", "Think of a florist whose team refuses to make reminder calls for birthdays and anniversaries. What do you tell her, and what does that resistance usually mean?"),
    ("out-of-town-orders-build-loyalty", "Many shops treat out-of-town orders as a hassle. Why do you push florists to promote them, and what did you see in your own years in the trade that convinced you?"),
    ("three-roses-add-on", "What is the simplest add-on you have ever seen a shop start offering that paid off right away, and how do you teach a team to say it without sounding pushy?"),
    ("cooler-store-within-a-store", "You call the cooler a store within a store. Think of a shop with a half-empty cooler: what does the customer decide in the first few seconds, and what do you tell the owner to do?"),
    ("sympathy-calls", "Sympathy orders carry the most emotion of any call. What do you tell florists about how to handle that call, and where did you learn it?"),
    ("valentines-battle-plan", "When Valentine's Day lands on a Saturday, what should an owner decide first about buying, the website, the designers and the drivers? Which of those do most shops get wrong?"),
    ("last-minute-christmas-moves", "It is a few days before Christmas and orders are slowing down. What are the cheap, quick moves you tell a florist to make to squeeze out the last orders?"),
    ("branding-hot-mess", "Think of a shop with one logo on the order form, another on the website and none on the van. What does that cost the owner, and what do you tell her to fix first?"),
    ("marketing-budget-percent", "How much of gross sales should a small flower shop put into marketing, and how do you tell the difference between spending that works and spending that only feels good?"),
    ("hiring-designers-red-flags", "Finding designers is the struggle you hear about most. What red flags do you tell owners to look for in a resume and an interview, and what is the peacocking trap?"),
    ("milking-the-clock", "Think of a designer who slows down whenever the shop is slow and speeds up only at holidays. What do you tell the owner to look at, and what part of this is a management problem rather than a people problem?"),
    ("owner-cannot-step-away", "Many owners feel the store is always on fire and they can never leave. What do you tell them about building a shop that runs when they are gone, and where do they start?"),
    ("angry-caller-solution-first", "Think of an employee who explains to an angry customer why the problem happened. What do you tell her to do instead, and why does explaining usually make it worse?"),
    ("not-the-shop-for-you-today", "Is the customer always right? When have you told a florist it is fine to politely turn a customer away, and what words do you give her so the door stays open?"),
    ("review-replies-with-personality", "What do most florists get wrong when they reply to a bad online review, and how do you coach them to answer with a little personality without getting defensive?"),
    ("labor-cost-and-payroll-sense", "What is a healthy labor cost for a flower shop, and what simple question do you ask an owner to find out whether her payroll still makes sense if sales drop?"),
    ("dumpster-arrangement-waste", "You have owners build an arrangement from what the designers threw away. Why does that exercise work on a team, and what do you hope the designers feel when the bottom shell drops?"),
    ("sops-become-wallpaper", "Think of a shop with beautiful procedures taped to the wall that nobody follows. Why does that happen, and what do you tell the owner to do so the rules actually get used?"),
    ("goals-baby-steps", "When an owner is excited in a coaching session but nothing changes by the next one, what do you tell her about baby steps and follow-through, and what is the first number you have her track?"),
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
            meta={"course_lesson": True, "course": course, "site": SITE_HOST},
        )
        for key, title, url, lesson, course in LESSONS
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
    for _key, _title, url, _lesson, _course in LESSONS:
        if urlsplit(url).hostname != SITE_HOST:
            raise SystemExit(f"a lesson must cite his own site: {url}")
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
    print(f"\n[news_feeds] {len(FEEDS)} feeds (lane C, smart_ideas)")
    for name, url, kind, tier, _v in FEEDS:
        print(f"  [{tier}] {name}  {url}  ({kind})")
    print(f"\n[standing facts] {len(STANDING_FACTS)} (lane C anchors)")
    for kind, term, lesson in STANDING_FACTS:
        print(f"  {kind:16} {term:24} {lesson}")
    print(f"\n[curated_clip] {len(LESSONS)} course lessons (lane A, from_my_courses)")
    for _key, title, url, _lesson, course in LESSONS:
        print(f"  [{course}] {title}  {url}")
    print(f"\n[story_seed] {len(STORY_SEEDS)} prompts (lane B, coaching_room)")
    for key, question in STORY_SEEDS:
        print(f"  {key:32} {question}")
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
    print(f"  PYTHONPATH=src python scripts/build_anchor_index.py --workspace {ws} --dry-run")


# --------------------------------------------------------------------------- network


def page_answered(status: int, location: str | None) -> bool:
    """200, or a members-only lesson sending a visitor to a login page on his own site."""
    if status == 200:
        return True
    if status in (301, 302, 303, 307, 308) and location:
        host = urlsplit(location).hostname
        return host is None or host == SITE_HOST or host.endswith("." + SITE_HOST)
    return False


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
    pages = sorted({url for _key, _title, url, _lesson, _course in LESSONS})
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False,
                                 headers={"user-agent": PAGE_USER_AGENT}) as client:
        for url in pages:
            await asyncio.sleep(1.0)  # one page a second: his site is a small WordPress
            try:
                r = await client.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL  page {url}: {type(exc).__name__}")
                bad += 1
                continue
            if not page_answered(r.status_code, r.headers.get("location")):
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
    from tce.editorial.lane_profile import FLORIST_COACH

    week = str(current_week_start())[:10]
    print(f"SAMPLE WEEK {week} - evidence offered to the selector, lane by lane")
    print("target mix: " + ", ".join(f"{lane.key} {lane.target}" for lane in FLORIST_COACH.lanes))
    lessons = sorted(LESSONS, key=lambda c: _rotation(c[0], week))[: FLORIST_COACH.reserve_per_lane]
    seeds = sorted(STORY_SEEDS, key=lambda s: _rotation(s[0], week))[: FLORIST_COACH.reserve_per_lane]
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
        print("\nC smart_ideas - recent feed items that touch his anchors (top 10; the "
              "matcher and the gates decide):")
        for _n, name, title, hits in found[:10]:
            print(f"  [{name}] {title[:90]}  <- {', '.join(hits)}")
    else:
        print("\nC smart_ideas - add --network to read the feeds")
    print(f"\nA from_my_courses - {len(lessons)} lessons rotated in this week:")
    for _key, title, url, lesson, course in lessons:
        print(f"  [{course}] {title} {url}\n      {lesson}")
    print(f"\nB coaching_room - {len(seeds)} prompts rotated in this week:")
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
                                          label="Tim florist coach lanes"))
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
        print(f"course lessons and prompts: {counts}")
        await session.commit()

        settings_row_count = await lineup.set_videos_per_week(session, ws, VIDEOS_PER_WEEK)
        await session.commit()
        print(f"videos_per_week: {VIDEOS_PER_WEEK} ({settings_row_count})")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=TIM_WORKSPACE)
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
