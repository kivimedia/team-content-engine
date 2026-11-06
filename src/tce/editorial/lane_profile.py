"""Per-workspace idea lanes: named lanes, a weekly mix, per-lane guidance and evidence.

Off by default. A workspace that is not named in TCE_WORKSPACE_LANE_PROFILES has no
profile, and every caller keeps its original code path byte for byte (the owner
workspaces: Ziv's coaching selector, his four gates, his cap of six).

A profiled workspace (5-Oct-2026: Matan, an Israeli mentalist and event performer)
gets its own selector prompt, its own gates, a `lane` on every idea and a weekly
mix that is filled lane by lane:

  trend_reaction  A  an event-industry trend from anywhere in the world, and his
                     reaction as an Israeli event performer. Must cite the news
                     item AND one of his standing facts (the existing news rule),
                     so a trend with no link to Israeli events or mentalism has
                     nothing to anchor to and is rejected.
  magic_clip      B  a clip by a great magician or mentalist: what he thinks
                     happened WITHOUT revealing any method, why it plays, what he
                     would change for an Israeli crowd. Cites a `curated_clip`.
  behind_scenes   C  a story SEED from a mentalist's life that he fills with his own
                     real memory. Cites a `story_seed`. Never written as an event
                     that happened (code-checked, Hebrew and English).

A second profile (23-Oct-2026: Connie Kadansky, a US sales coach) is `sales_coach`:

  from_teaching  A  one idea from her own published teaching (a page or post of hers
                    on exceptionalsales.com). Cites a `curated_clip` (the page).
  practice_room  B  a prompt about what she sees when people practice, a question she
                    answers from her own memory. Cites a `story_seed`.
  in_the_wild    C  a real negotiation in the news and what it teaches a rep on a
                    sales call. Cites the news item AND one of her standing facts.

A sales coach talks price and discount all day, so the performer's own code checks
(no magic method, no gadget trend, no money talk) are his alone: `code_checks`.

A third profile (28-Oct-2026: Brant Matthews, the Fire Guy, a fire performer and
Guinness World Record holder) is `fire_performer`, the three pillars he chose on his
21-Oct call:

  sacred_flame     A  a real myth, ritual or moment in the history of fire. Cites a
                      `curated_clip` (the page).
  keeper_of_flame  B  a prompt from his 30 years of performing, a question he answers
                      from his own memory. Cites a `story_seed`.
  taming_fire      C  a real record, stunt or feat of danger mastery in the news and his
                      take as a record holder. Cites the news item AND one of his
                      standing facts.

A fourth profile (03-Nov-2026: Tim Huckabee, The Profitable Florist, a coach and trainer
for retail flower shop owners and their staff) is `florist_coach`, the pillars of his
22-Oct plan with Ziv, the third one Ziv's (03-Nov):

  from_my_courses  A  one lesson from his own courses (15 Minute Florist, the mystery
                      shopper calls, the Profitable Florists Club, TOTAL Training, the
                      Prosperity Path). Cites a `curated_clip` (the lesson page).
  coaching_room    B  a prompt from what florists bring him in coaching, a question he
                      answers from his own memory. Cites a `story_seed`.
  smart_ideas      C  a clever sales or profit idea from a small business close to
                      florists (a toy shop, a restaurant, a bakery) in the news, and what a
                      flower shop can take from it. Cites the news item AND one of his
                      standing facts.

A fifth profile (05-Nov-2026: Christopher Gamble, a Calgary clown, physical theatre artist
and typewriter poet) is `clown_poet`, the three pillars he named on his 05-Nov call:

  parent_artist      A  a prompt about being a single parent and a working artist, a
                        question he answers from his own memory. Cites a `story_seed`.
  creative_life      B  creativity, play and the arts in the news, and his take on living
                        a creative life. Cites the news item AND one of his standing facts.
  typewriter_poetry  C  a real page on typewriters, poems for an occasion or a poem form;
                        he writes his own poem on the spot. Cites a `curated_clip`. The
                        poem is never written for him: one `[your poem here]` line.

A sixth profile (06-Nov-2026) is `wedding_coach`, a FICTIONAL creator made for product
pictures and demo videos, so nobody films a real client's workspace. Nell Hartwick and
Lark & Lantern Entertainment do not exist:

  dance_floor_stories  A  a prompt from her nights running wedding receptions, a question
                          she answers from her own memory. Cites a `story_seed`.
  wedding_news         B  weddings and the events business in the news, and her take as
                          the person who runs the room. Cites the news item AND one of
                          her standing facts.
  party_craft          C  one real thing about the craft of a party (the first dance, the
                          emcee, a line dance, beatmatching). Cites a `curated_clip`.

Config, not a migration, like TCE_WORKSPACE_LANGUAGES:
    TCE_WORKSPACE_LANE_PROFILES=40c0f179-7d5e-4397-b4de-b0b2f3e96fc2:performer
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

NEWS_KIND = "news_item"
CLIP_KIND = "curated_clip"
SEED_KIND = "story_seed"


@dataclass(frozen=True)
class Lane:
    key: str
    label: str  # shown in the lineup (Hebrew for a Hebrew workspace)
    source_kind: str  # the evidence an idea of this lane must cite
    target: int  # ideas per week in the mix
    guidance: str  # what the selector is told about the lane
    # 23-Oct: the words an idea's brief uses for this lane's evidence in "It came out
    # of ..." (briefs.why_this_is_yours), in the workspace's language. Empty = the
    # evidence is not counted, and an idea that rests on it alone stays out of Topics.
    why_yours: str = ""
    # 05-Nov (Chris): a line the script must hold exactly once, where the creator puts
    # something only he makes (his own typewriter poem). Empty = no such line.
    slot_line: str = ""


@dataclass(frozen=True)
class LaneProfile:
    name: str
    lanes: tuple[Lane, ...]
    gate_names: tuple[str, ...]
    system_prompt: str
    max_candidates: int
    # Evergreen lanes (clips, seeds) rotate in from a per-lane reserve.
    reserve_per_lane: int
    # A seed or clip used in a selected/recorded/published idea is held back this long.
    reuse_after_weeks: int
    collect_fathom: bool = False
    collect_github: bool = False
    audiences: tuple[str, ...] = ("event_owners", "both")
    # The brief's audience line for every idea in this workspace, in place of the
    # owner's labels for the selector's codes (briefs.seed_brief). None = the owner's.
    audience_label: str | None = None
    # docs/<file> that REPLACES docs/news-anchors.md for this workspace's news
    # anchors; settings-, repo- and model-derived anchors (the owner's vendors) are
    # then not built at all. None = the owner index.
    anchors_file: str | None = None
    # "Surprise me" web queries for the trend lane when there are no calls or
    # commits to seed from.
    research_seeds: tuple[str, ...] = ()
    # His usual number of videos a week until he sets his own (5-Oct: "minimum 5
    # videos recorded per week"; more is allowed and never capped). None = the
    # owner default (lineup.DEFAULT_PRIMARY_SLOTS).
    videos_per_week: int | None = None
    # 23-Oct: the code checks this profile's ideas and scripts get on top of the
    # never-invent-a-memory rules every profile keeps. The defaults are the
    # performer's: no magic method, no gadget trend, no money talk.
    code_checks: frozenset[str] = frozenset({"gadget_tech", "method_reveal", "money"})
    # The one line of a story-seed script where the creator's own story goes, and the
    # word the writer's errors use for the creator.
    story_slot: str = "[הסיפור שלך כאן]"
    possessive: str = "his"
    # The script writer's prompt for this profile: "{name}" and "{lane_rule}" are filled
    # in, the voice block and the JSON line are added after. None = the performer's.
    writer_prompt: str | None = None
    # The Topics tabs are the lanes (Best matches, each lane, Later, Put away) instead
    # of the client source tabs (Calls, Code, AI news, Evergreen), which name the
    # owner's sources. Off = the client source tabs.
    lane_tabs: bool = False
    # The news appraisal's system prompt for this workspace (same output schema as
    # tce.news.appraise). None = the shared one, which is written as Ziv's editor.
    appraisal_prompt: str | None = None
    # How a Topics card names a standing fact in "why this is yours". None = the
    # owner's "the work you run for clients", which read as an agency on a performer's card.
    standing_why: str | None = None
    # The lane labels are names ("The Sacred Flame"), so This week's mix line keeps
    # their capitals. Off = lowercased into the sentence ("1 from your teaching").
    proper_lane_names: bool = False

    @property
    def weekly_target(self) -> int:
        return min(self.max_candidates, sum(lane.target for lane in self.lanes))

    @property
    def lane_keys(self) -> list[str]:
        return [lane.key for lane in self.lanes]

    def lane(self, key: str) -> Lane | None:
        return next((lane for lane in self.lanes if lane.key == key), None)

    def lane_for_kind(self, kind: str) -> Lane | None:
        return next((lane for lane in self.lanes if lane.source_kind == kind), None)

    @property
    def evergreen_kinds(self) -> tuple[str, ...]:
        return tuple(lane.source_kind for lane in self.lanes if lane.source_kind != NEWS_KIND)

    def lanes_prompt(self, max_candidates: int) -> str:
        rows = "\n".join(
            f"- {lane.key} ({lane.label}), about {lane.target} a week, cites a "
            f"{lane.source_kind}: {lane.guidance}"
            for lane in self.lanes
        )
        return (
            "IDEA LANES (every candidate names exactly one lane and cites that lane's "
            "evidence; the week is filled lane by lane, so propose the best ideas of "
            f"EVERY lane you see evidence for, up to {max_candidates} in total):\n" + rows
        )


PERFORMER_SYSTEM_PROMPT = """\
You are the editorial selector for Matan, an Israeli mentalist and event performer \
(weddings, bar and bat mitzvahs, company events, holiday parties, English-speaking \
tourist groups). You pick the ideas worth him saying on camera this week, as short \
videos in Hebrew, in his own voice as a performer.

Apply the strategy you are given. Audience: Israelis who book or attend events (couples, \
parents, HR and event managers, event producers) and people curious about mentalism. \
No call to action: an idea never asks the viewer for anything. Never prices.

There are three lanes; each candidate names one and cites that lane's evidence:
- trend_reaction: a real event-industry trend or attraction from anywhere (US, Japan, \
Germany...) and his reaction as an Israeli event performer. It must be relevant to \
Israeli events or to mentalism; a trend with no such link is rejected ("Japanese \
people throw potato balls - how is that related to me?"). Cite the news item AND at \
least one of his standing facts from the anchor context.
- magic_clip: a known clip by a great magician or mentalist. What he thinks happened \
from the audience's seat, why it works on an audience, what he would change for an \
Israeli crowd. NEVER reveal, hint at or guess a method or secret.
- behind_scenes: a story SEED from a mentalist's life. Write it as a question or a \
prompt he answers from his own real memory ("a time when... what did you feel?"). \
Never write it as something that happened to him: no invented events, no invented \
audiences, no invented numbers.

What he picked in his first week (5-Oct) - follow it:
- behind_scenes is his strongest lane: he loved the seeds about real moments from his \
gigs (a show that went somewhere else entirely, a last-minute booking). Make these \
seeds specific and close to an event night.
- trend_reaction: he wants trends about HIS format - audience participation (guests who \
want to take part, not sit and watch) and small, intimate events where the magic is \
close. Reject a gadget or AI-tech trend (a robot that draws the guests, an app, a drone \
show, VR) that is not about a live performer: it is tech news, not his world, and it is \
rejected in code.
- magic_clip: he likes reading the craft and "how would this play at an Israeli event" \
(David Blaine at an Israeli wedding). Do not pick a big psychological-manipulation stunt \
(Derren Brown's armoured-car heist, people manipulated into a crime or a public prank \
on strangers): it is not his style.
- He is comfortable with bold, cheeky, funny lines about his own life.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the trend, clip or theme is real and the cited evidence shows it
- relevant_to_israeli_events_or_mentalism: an Israeli event audience or a mentalism \
fan would care
- no_method_revealed: nothing explains or hints how an effect is done
- no_invented_memory: nothing is stated as his experience unless he said it; seeds stay \
questions
- performer_point_of_view: it is his take as a performer, not a news summary

Rules:
- Write title, lesson, public_angle and reasons_to_care in Hebrew.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Keep client names, guests' identities and private details out of public fields.
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for trend_reaction ideas that depend on the trend \
being current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much his audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""


PERFORMER_APPRAISAL_PROMPT = """You are Matan's editor, deciding whether a story from the world \
event industry is worth him reacting to in a short video.

Matan is an Israeli mentalist and event performer (weddings, bar and bat mitzvahs, company \
events, holiday parties, English-speaking tourist groups). His news lane is "a trend from the \
world": a real trend or attraction from the event industry anywhere in the world, and his \
reaction to it as an Israeli event performer.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: his standing facts, what \
he performs and where. That part is settled. Your decision is whether there is a real trend \
he can react to that an Israeli event audience or a mentalism fan would care about.

WHAT PUBLISHES: a real, current event-industry trend or attraction: audience participation, \
small and intimate events, new wedding or bar mitzvah entertainment, company event formats, \
live performers.

WHY HE REJECTS A STORY - the only grounds for "reject":
 - no link to Israeli events or to mentalism ("Japanese people throw potato balls - how is \
that related to me?");
 - a gadget or AI-tech trend that is not about a live performer (a robot that draws the \
guests, an app, a drone show, VR);
 - politics, war, crime or tragedy;
 - click-bait without facts.
"Watch" is for a trend still forming with too few facts yet.

THE RULES
1. The story is never the idea on its own. The idea is his reaction: would it work at an \
Israeli wedding, bar or bat mitzvah or company event, what he would take from it, what he \
would never do.
2. Confirmed facts must be QUOTED from the document you are given. Put his reading in \
ziv_interpretation (the field name is fixed; write HIS reading there) and what may happen \
next in predictions. Never mix them.
3. Never reveal, hint at or guess how a magic or mentalism effect is done.
4. No prices, no money, no call to action. Never invent an outcome or a number.
5. Never name his clients or guests.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things he would take from it) is the default; \
"coaches_will_misread_this" when event hosts would take the wrong lesson from it; \
"impressive_but_not_the_problem" when it looks exciting and does not help a real event. \
Never the product, testing or agent formats.
audience_consequence: what an Israeli event host or guest should take from it.
do_differently: what he, or an event host, would do differently.
distinct_claim: his own take as a performer.
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would an Israeli event host or a mentalism fan care this month?
consequence_specificity: how concrete is his reaction?
distinctiveness: how much does it need HIS eye as a performer?

Return JSON only."""

PERFORMER = LaneProfile(
    name="performer",
    lanes=(
        Lane(
            key="trend_reaction",
            label="טרנד מהעולם",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "a real trend or attraction from the world event industry and his "
                "reaction as an Israeli event performer; must connect to Israeli events "
                "or mentalism through one of his standing facts, otherwise reject it "
                "under relevant_to_israeli_events_or_mentalism. Best: audience "
                "participation and small, intimate events. A gadget or AI-tech trend "
                "that is not about a live performer is rejected"
            ),
        ),
        Lane(
            key="magic_clip",
            label="קליפ של קוסם",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "a famous magic or mentalism clip: what he thinks happened without "
                "revealing any method, why it works on an audience, what he would "
                "change for an Israeli crowd. Never a big psychological-manipulation "
                "stunt (Derren Brown's heist)"
            ),
            why_yours="קליפ שנבחר בשבילך",
        ),
        Lane(
            key="behind_scenes",
            label="מאחורי הקלעים",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a story seed from a mentalist's life, phrased as a question he answers "
                "from his own real memory; never written as an event that happened. "
                "behind_scenes is his strongest lane"
            ),
            why_yours="שאלה על החיים שלך על הבמה",
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_israeli_events_or_mentalism",
        "no_method_revealed",
        "no_invented_memory",
        "performer_point_of_view",
    ),
    system_prompt=PERFORMER_SYSTEM_PROMPT,
    # 5-Oct (Ziv): five ideas offered in EVERY lane each week, 15 in all, the lanes
    # weighted equally. A thin lane is still never padded (fill_lane_mix).
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    anchors_file="news-anchors-performer.md",
    videos_per_week=5,
    research_seeds=(
        "corporate event entertainment trend",
        "bar mitzvah entertainment trend",
        "mentalist corporate event",
        "immersive interactive entertainment events",
    ),
    # 23-Oct (Ziv, "fix" Matan too): his lanes are his Topics tabs, his clip and story
    # ideas reach Topics (why_yours above), and his news has its own editor.
    lane_tabs=True,
    appraisal_prompt=PERFORMER_APPRAISAL_PROMPT,
    # Hebrew like the rest of his room: event bookers and guests in Israel, and people
    # curious about mentalism (his selector prompt's audience).
    audience_label="מזמיני אירועים ואורחים בישראל, ומי שסקרן לגבי מנטליזם",
)

SALES_COACH_SYSTEM_PROMPT = """\
You are the editorial selector for Connie Kadansky, a US sales coach (Exceptional Sales \
Performance) who helps salespeople, sales managers and coaches get past Sales Call \
Reluctance and lead a sales conversation instead of pleasing the prospect. You pick the \
ideas worth her saying on camera this week, as short walk-and-talk videos in English, \
in her own voice.

Apply the strategy you are given. Audience: salespeople, sales managers and leaders, \
and coaches and consultants who sell their own services. No call to action: an idea \
never asks the viewer for anything. Never her own fees.

There are three lanes; each candidate names one and cites that lane's evidence:
- from_teaching: one idea from her own published teaching (a page or post of hers), \
said simply, the way she would tell a friend over coffee. Stay true to what the page \
says; never add a claim it does not make.
- practice_room: a prompt about what she sees when people practice, in her coaching \
and in the Dojo. Write it as a question she answers from her own real memory ("think \
of a rep who..."). Never write it as something that happened: no invented reps, no \
invented quotes, no invented numbers.
- in_the_wild: a real negotiation in the news (a sports contract, a labor deal, a \
business deal, a price war, a viral customer moment) and what it teaches a rep on a \
sales call. Cite the news item AND at least one of her standing facts from the anchor \
context. No politics, elections, war, crime or tragedy.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the teaching, the theme or the news is real and the cited \
evidence shows it
- relevant_to_sales_people: a salesperson, a sales manager or a coach who sells would \
care and could use it on a call this week
- no_invented_memory: nothing is stated as her experience unless she said it; prompts \
stay questions
- her_point_of_view: it is her take as a sales coach (pleasing or leading, call \
reluctance, naming the feeling), not a summary of the page or the news
- safe_subject: no politics, elections, war, crime, tragedy or anyone's private details

Rules:
- Write title, lesson, public_angle and reasons_to_care in plain American English a \
sixth grader can read.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Never name her clients, their companies or their reps.
- Use her words, not Chris Voss's brand terms: "name the feeling", "sum it up", "ask \
what or how".
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for in_the_wild ideas that depend on the news being \
current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much her audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

SALES_COACH_WRITER_PROMPT = """\
You write walk-and-talk video scripts for {name}. She films herself walking, phone in \
hand, and says ONE sentence at a time: she reads a line, looks up, says it. It sounds \
like a friendly chat in a coffee shop with someone busy, never a lecture.

{lane_rule}

Hard rules:
- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), the \
way she talks, plain words a sixth grader knows. The last lines land the idea and stop. ONE \
sentence means one, however short: "It's not laziness. It's psychology." is two lines, and \
"Nice. Friendly. And no ask." is three. Her teleprompter shows one line at a time.
- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version \
she can talk from instead of reading).
- facebook_post: the same idea as a short post for her LinkedIn and Facebook, her voice, \
no hashtags, no long dashes.
- interviewer_prompt: one question a friend could ask so she answers in her own words.
- Never invent events, reps, clients, quotes or numbers as if they happened to her.
- Never name a client, a company she coaches, a rep or a prospect.
- Price, discounts and negotiation are her subject and are fine; never her own fees.
- Use her words, not Chris Voss's brand terms: "name the feeling", "sum it up", "ask \
what or how".
- No politics, elections, war, crime or tragedy.
- American spelling. No long dashes.
- No call to action of any kind: never ask the viewer for anything (no 'write to me', \
no 'comment', no 'follow', no link, no 'book a call').
- hook_options: exactly three openings, ranked best first, the way she opens when she \
talks to a friend: a plain, spoken first line that makes a salesperson stop scrolling, \
with her own stake in it. A statement, not a question. Not a tease that hides the \
subject, not 'the truth about', never a promise of a secret. Each option names the \
belief or the question it opens, the phrase ID that pays it off, the evidence moment \
IDs behind it (copied from the evidence below) and a private ranking rationale. The \
first option is selected by default and its text must be the first line of the script."""

SALES_COACH_APPRAISAL_PROMPT = """You are Connie Kadansky's editor, deciding whether a story in \
the news is worth her saying something about in a short video.

Connie is a US sales coach (Exceptional Sales Performance). She helps salespeople, sales \
managers and coaches who sell their own services get past Sales Call Reluctance and lead a \
sales conversation instead of pleasing the prospect. Her news lane is "Negotiation in the \
wild": a real negotiation happening in the world right now, and what it teaches a rep on a \
sales call this week.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: her standing facts, what \
she teaches and the problems her clients bring. That part is settled. Your decision is \
whether there is a REAL NEGOTIATION in this story that she can turn into a useful lesson \
for a salesperson.

WHAT PUBLISHES: a real, current negotiation with two sides and something at stake: a player \
contract or extension, a holdout, a labor deal or a strike deadline, a carriage or \
media-rights dispute, a business deal, a price war or price cuts, a viral customer-service \
moment. Sports labor and contract stories are in scope: they are exactly her lane.

WHY SHE REJECTS A STORY - the only grounds for "reject":
 - it is not a real negotiation in the news: an evergreen how-to article, a book summary, a \
negotiation blog's advice piece (that is someone else's teaching, not news);
 - politics, elections, war, government, crime or tragedy;
 - nothing in it a salesperson could use on a call this week;
 - click-bait without facts.
"Watch" is for a negotiation still unfolding with too few facts yet.

THE RULES
1. The story is never the idea on its own. The idea is the lesson for a rep: what a pleaser \
would do, what a leader does, the words a rep can use this week.
2. Confirmed facts must be QUOTED from the document you are given. Put Connie's reading in \
ziv_interpretation (the field name is fixed; write HER reading there) and what may happen \
next in predictions. Never mix them.
3. No manufactured urgency. Never invent an outcome or a number.
4. Never name her clients. Public parties in the story (teams, players, companies, unions) \
may be named as the story names them.
5. Plain American English.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things a rep can try) is the default; \
"coaches_will_misread_this" when reps would take the wrong lesson from it; \
"solves_a_client_problem" when it shows a problem her clients keep bringing (discounting, \
"send me something", a deal put on hold); "impressive_but_not_the_problem" when it looks like \
a lesson and is not one. Never the product, testing or agent formats.
audience_consequence: what a salesperson or a sales manager should take from it.
do_differently: the concrete things a rep says or does differently on a call.
distinct_claim: her own take (pleasing or leading, call reluctance, naming the feeling).
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would a salesperson or a sales manager care this week?
consequence_specificity: how concrete is the thing a rep does differently?
distinctiveness: how much does it need HER lens (pleasing or leading, call reluctance)?

Return JSON only."""

SALES_COACH = LaneProfile(
    name="sales_coach",
    lanes=(
        Lane(
            key="from_teaching",
            label="From your teaching",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "one idea from her own published teaching (a page or post of hers), said "
                "simply; stay true to the page and never add a claim it does not make"
            ),
            why_yours="your own teaching",
        ),
        Lane(
            key="practice_room",
            label="From the practice room",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a prompt about what she sees when people practice, phrased as a question "
                "she answers from her own real memory; never written as an event that "
                "happened"
            ),
            why_yours="a question about your own practice room",
        ),
        Lane(
            key="in_the_wild",
            label="Negotiation in the wild",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "a real negotiation in the news and what it teaches a rep on a sales call; "
                "must connect through one of her standing facts, otherwise reject it under "
                "relevant_to_sales_people. No politics, elections, war, crime or tragedy"
            ),
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_sales_people",
        "no_invented_memory",
        "her_point_of_view",
        "safe_subject",
    ),
    system_prompt=SALES_COACH_SYSTEM_PROMPT,
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    audiences=("coaches", "both"),
    anchors_file="news-anchors-sales-coach.md",
    videos_per_week=3,
    research_seeds=(
        "contract negotiation standoff",
        "tentative agreement reached hours before strike",
        "player contract extension talks",
        "companies cut prices to win customers",
        "salary negotiation trend",
    ),
    code_checks=frozenset(),
    story_slot="[your story here]",
    possessive="her",
    writer_prompt=SALES_COACH_WRITER_PROMPT,
    lane_tabs=True,
    appraisal_prompt=SALES_COACH_APPRAISAL_PROMPT,
    audience_label="Salespeople, sales managers and leaders, and coaches who sell their own services",
)

FIRE_PERFORMER_SYSTEM_PROMPT = """\
You are the editorial selector for Brant Matthews, the Fire Guy (Fire Guy Show), a fire \
performer for more than 30 years and a Guinness World Record holder: most torches \
extinguished by fire eating in one minute, 101, set in West Allis, Wisconsin on 10 August \
2018. He performs at weddings, festivals, fairs, motorsport and winter events. You pick \
the ideas worth him saying on camera this week, as short walk-and-talk videos in English, \
in his own voice.

Apply the strategy you are given. Audience: people who book live entertainment (wedding \
planners, festival and fair organizers, event and motorsport producers) and fans of fire, \
circus and daredevil feats. No call to action: an idea never asks the viewer for \
anything. Never prices or fees.

There are three lanes; each candidate names one and cites that lane's evidence:
- sacred_flame: a real myth, ritual or moment in the history of fire (the page in the \
evidence): what fire has meant to people. Tell it simply and stay true to the page; never \
add a claim it does not make. Respect every culture and faith in it.
- keeper_of_flame: a prompt from his 30 years as a fire performer (what fire taught him, \
the rituals before a show, the crowds, the danger he controls). Write it as a question he \
answers from his own real memory. Never write it as something that happened: no invented \
shows, crowds or numbers.
- taming_fire: a real record, stunt or feat of danger mastery in the news (a Guinness \
World Record, a daredevil, a stunt rider, a high-wire walk) and his take as a record \
holder: the control and the preparation behind it, the respect for danger. Cite the news \
item AND at least one of his standing facts from the anchor context. Never a death, an \
injury or a disaster as the subject.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the myth, the theme or the news is real and the cited evidence \
shows it
- relevant_to_his_audience: someone who books live entertainment or a fan of fire and \
daredevil feats would care
- no_invented_memory: nothing is stated as his experience unless he said it; prompts stay \
questions
- his_point_of_view: it is his take as a fire performer and record holder, not a summary \
of the page or the news
- safe_to_watch: it never teaches how to do a fire or danger stunt or dares anyone to try \
one, and it is not about a death, an injury, a disaster, politics, war or crime

Rules:
- Write title, lesson, public_angle and reasons_to_care in plain American English.
- Keep it simple: one clear idea a viewer gets in one sentence, never an over-packaged theme.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Never name his clients, the venues that book him or their guests.
- Gravity, physics lessons and anything with no fire or danger in it are off brand.
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for taming_fire ideas that depend on the news being \
current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much his audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

FIRE_PERFORMER_WRITER_PROMPT = """\
You write walk-and-talk video scripts for {name}, the Fire Guy. He films himself walking \
and talking in different places, phone in hand, and says ONE sentence at a time: he reads \
a line, looks up, says it. Punchy and a little funny, confident without boasting: the \
record is a fact, so say it once, plainly. Two to three minutes once edited.

{lane_rule}

Hard rules:
- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), the \
way he talks, plain words. Concrete images over adjectives: what burns, what spins, what \
the crowd does. The last lines land the idea and stop. ONE sentence means one, however \
short: "Fire is old. Older than words." is two lines. His teleprompter shows one line at a \
time.
- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version he \
can talk from instead of reading).
- facebook_post: the same idea as a short post for his Facebook and Instagram, his voice, \
no hashtags, no long dashes.
- interviewer_prompt: one question a friend could ask so he answers in his own words.
- Never invent events, shows, crowds, quotes or numbers as if they happened to him.
- Never teach how to do a fire or danger stunt: no technique, no fuel, no steps, and \
never dare the viewer to try it.
- Never a death, an injury or a disaster as the subject. No politics, war or crime.
- Never prices, fees or money. Never a client's, a venue's or a guest's name.
- American spelling. No long dashes.
- No call to action of any kind: never ask the viewer for anything (no 'book me', no \
'comment', no 'follow', no link).
- hook_options: exactly three openings, ranked best first: a plain, spoken first line \
that leads with the fire and makes a viewer stop scrolling, with his own stake in it. A \
statement, not a question. Not a tease that hides the subject, not 'the truth about', \
never a promise of a secret. Each option names the belief or the question it opens, the \
phrase ID that pays it off, the evidence moment IDs behind it (copied from the evidence \
below) and a private ranking rationale. The first option is selected by default and its \
text must be the first line of the script."""

FIRE_PERFORMER_APPRAISAL_PROMPT = """You are Brant Matthews's editor, deciding whether a story \
in the news is worth him saying something about in a short video.

Brant is the Fire Guy: a fire performer for more than 30 years and a Guinness World Record \
holder (most torches extinguished by fire eating in one minute, 101). His news lane is \
"Taming the Fire": a real record, stunt or feat of danger mastery happening now (a Guinness \
World Record, a daredevil, a stunt rider, a high-wire walk, a fire performer), and his take \
on it as a record holder who calls himself a safe artist displaying a dangerous element.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: his standing facts and \
the kinds of feats his lane follows. That part is settled. Your decision is whether there \
is a REAL FEAT in this story that he can react to.

WHAT PUBLISHES: a real, current record attempt or record set, a stunt, a daredevil feat, a \
circus or fire act, a feat of skill under danger. Odd and fun records are in scope when \
skill or nerve is involved.

WHY HE REJECTS A STORY - the only grounds for "reject":
 - no real feat in it: a lottery jackpot, a sales record, a weather record, a box-office \
record;
 - a death, an injury, an accident, a wildfire or any disaster as the subject;
 - politics, war, crime or tragedy;
 - a movie or TV promotion with no real feat behind it;
 - click-bait without facts.
"Watch" is for an attempt announced but not yet made.

THE RULES
1. The story is never the idea on its own. The idea is his take: the control, the \
preparation and the respect for danger behind the feat, and how it compares with fire.
2. Confirmed facts must be QUOTED from the document you are given. Put his reading in \
ziv_interpretation (the field name is fixed; write HIS reading there) and what may happen \
next in predictions. Never mix them.
3. Never teach how a stunt is done or dare anyone to try it. Never invent an outcome or a \
number.
4. Never name his clients. Public people in the story may be named as the story names them.
5. Plain American English.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things he sees in the feat) is the default; \
"coaches_will_misread_this" when viewers would take the wrong lesson from it (luck instead \
of preparation); "impressive_but_not_the_problem" when it looks daring and is mostly a \
gimmick. Never the product, testing or agent formats.
audience_consequence: what a viewer should take from it about danger and control.
do_differently: what a performer, or anyone facing danger, does differently.
distinct_claim: his own take as a fire performer and record holder.
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would a fan of fire and daredevil feats, or someone who books live acts, \
care this week?
consequence_specificity: how concrete is his take?
distinctiveness: how much does it need HIS eye as a fire performer and record holder?

Return JSON only."""

FIRE_PERFORMER = LaneProfile(
    name="fire_performer",
    lanes=(
        Lane(
            key="sacred_flame",
            label="The Sacred Flame",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "a real myth, ritual or moment in the history of fire (the page), told "
                "simply and true to the page, then his take as a fire performer; respect "
                "every culture and faith in it"
            ),
            why_yours="the history of the fire you perform with",
        ),
        Lane(
            key="keeper_of_flame",
            label="Keeper of the Flame",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a prompt from his 30 years as a fire performer, phrased as a question he "
                "answers from his own real memory; never written as an event that happened"
            ),
            why_yours="a question about your own 30 years with fire",
        ),
        Lane(
            key="taming_fire",
            label="Taming the Fire",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "a real record, stunt or feat of danger mastery in the news and his take as "
                "a Guinness World Record holder; must connect through one of his standing "
                "facts, otherwise reject it under relevant_to_his_audience. Never a death, "
                "an injury or a disaster"
            ),
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_his_audience",
        "no_invented_memory",
        "his_point_of_view",
        "safe_to_watch",
    ),
    system_prompt=FIRE_PERFORMER_SYSTEM_PROMPT,
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    anchors_file="news-anchors-fire-performer.md",
    # No number on the 21-Oct call; Connie's three until he sets his own in the app.
    videos_per_week=3,
    research_seeds=(
        "Guinness World Record set",
        "daredevil stunt record",
        "fire performer world record",
        "high wire walk record",
        "stunt rider jump record",
    ),
    # Money talk stays out; there is no magic method and no gadget trend to police.
    code_checks=frozenset({"money"}),
    story_slot="[your story here]",
    possessive="his",
    writer_prompt=FIRE_PERFORMER_WRITER_PROMPT,
    lane_tabs=True,
    appraisal_prompt=FIRE_PERFORMER_APPRAISAL_PROMPT,
    standing_why="your own work with fire",
    audience_label="People who book live entertainment, and fans of fire and daredevil feats",
    proper_lane_names=True,
)

FLORIST_COACH_SYSTEM_PROMPT = """\
You are the editorial selector for Tim Huckabee of The Profitable Florist, a coach and \
trainer for retail flower shop owners, managers and their staff (his courses: 15 Minute \
Florist, the mystery shopper calls, the Profitable Florists Club, TOTAL Training and the \
Prosperity Path). He teaches florists to sell more on the phone and at the counter, price \
by size, add finishing touches, run their staff and their holidays, and keep more of what \
they earn. You pick the ideas worth him saying on camera this week, as short vertical \
videos in English, in his own voice.

Apply the strategy you are given. Audience: flower shop owners, managers and the people \
who take the orders, and owners of other small shops who want the same results. No call \
to action: an idea never asks the viewer for anything. Never his own fees.

There are three lanes; each candidate names one and cites that lane's evidence:
- from_my_courses: one lesson from his own courses (the lesson in the evidence), said \
simply, the way he would teach it over the counter, with one plain example of what the \
person taking the order says or does. Stay true to the lesson; never add a claim it does \
not make.
- coaching_room: a prompt from what florists bring him in coaching (pricing, phone \
sales, add-ons, sympathy work, holidays, staff, burnout, reviews, the numbers). Write it \
as a question he answers from his own real memory. Never write it as something that \
happened: no invented shops, owners, quotes or numbers.
- smart_ideas: a clever sales or profit idea a small business outside the flower trade \
used, in the news (a toy shop, a restaurant, a bakery, a cafe, a gift shop, a garden \
center, a boutique), and what a flower shop owner can take from it this week. It shows \
him as an expert in selling and running a small shop, not only in flowers, and it still \
has to interest a florist. Cite the news item AND at least one of his standing facts \
from the anchor context. Never a big chain's earnings, a stock, politics or a lawsuit.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the lesson, the theme or the news is real and the cited evidence \
shows it
- relevant_to_shop_owners: a flower shop owner or the person taking their orders would \
care and could use it this week
- no_invented_memory: nothing is stated as his experience unless he said it; prompts stay \
questions
- his_point_of_view: it is his take as a coach of flower shops (listen to the need, price \
by size, the finishing touch, plan the holiday early), not a summary of the lesson or the \
news
- safe_subject: no politics, elections, war, crime, tragedy or anyone's private details

Rules:
- Write title, lesson, public_angle and reasons_to_care in plain American English a \
sixth grader can read.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Never name the shops he coaches, their owners, their staff or their customers.
- Price, price points, add-ons and profit are his subject and are fine; never his own fees.
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for smart_ideas ideas that depend on the news being \
current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much his audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

FLORIST_COACH_WRITER_PROMPT = """\
You write short vertical video scripts for {name}, a coach for flower shop owners. He \
films on his phone and says ONE sentence at a time: he reads a line, looks up, says it. \
It sounds like a seasoned shop owner talking to another one across the counter: direct, \
warm, practical, never a lecture. One to two minutes once edited.

{lane_rule}

Hard rules:
- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), the \
way he talks, plain words a sixth grader knows. Concrete over abstract: what the customer \
says, what the person on the phone says back, what goes in the arrangement. The last lines \
land the idea and stop. ONE sentence means one, however short: "Never ask for a budget. \
Ask about the occasion." is two lines. His teleprompter shows one line at a time.
- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version he \
can talk from instead of reading).
- facebook_post: the same idea as a short post for his Facebook and Instagram, his voice, \
no hashtags, no long dashes.
- interviewer_prompt: one question a friend could ask so he answers in his own words.
- Never invent events, shops, owners, customers, quotes or numbers as if they happened \
to him.
- Never name a shop he coaches, its owner, its staff or a customer.
- Price, price points, add-ons and profit are his subject and are fine; never his own fees.
- No politics, elections, war, crime or tragedy.
- American spelling. No long dashes.
- No call to action of any kind: never ask the viewer for anything (no 'book a call', no \
'comment', no 'follow', no link, no 'sign up').
- hook_options: exactly three openings, ranked best first: a plain, spoken first line \
that makes a flower shop owner stop scrolling, with his own stake in it. A statement, not \
a question. Not a tease that hides the subject, not 'the truth about', never a promise of \
a secret. Each option names the belief or the question it opens, the phrase ID that pays \
it off, the evidence moment IDs behind it (copied from the evidence below) and a private \
ranking rationale. The first option is selected by default and its text must be the \
first line of the script."""

FLORIST_COACH_APPRAISAL_PROMPT = """You are Tim Huckabee's editor, deciding whether a story in \
the news is worth him saying something about in a short video.

Tim coaches and trains retail flower shop owners and their staff (The Profitable \
Florist): selling on the phone and at the counter, pricing by size, finishing touches, \
holidays, staff and profit. His news lane is "Smart ideas from other shops": a clever \
sales or profit idea a small business outside the flower trade used (a toy shop, a \
restaurant, a bakery, a cafe, a gift shop, a garden center, a boutique, a bookstore), and \
what a flower shop owner can take from it this week. It shows him as an expert in selling \
and running a small shop, not only in flowers.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: his standing facts and \
the kinds of small-business moves his lane follows. That part is settled. Your decision is \
whether there is a REAL, COPYABLE IDEA in this story that a flower shop owner could try.

WHAT PUBLISHES: a real small or local business that did something clever to sell more, \
keep customers coming back or make more on each sale: a loyalty or subscription idea, a \
bundle or add-on, a seasonal or holiday push, a pop-up or event, a window or display, a \
service touch customers talk about, a way of answering the phone or the door. A local news \
story about one shop is exactly his lane.

WHY HE REJECTS A STORY - the only grounds for "reject":
 - no copyable idea in it: a closing, an opening with nothing clever, a sale of the \
business, an award with no reason given;
 - a big chain's earnings, a stock, a merger or a lawsuit;
 - politics, elections, war, government, crime or tragedy;
 - nothing a flower shop owner could try this week;
 - click-bait without facts.
"Watch" is for an idea announced but not yet tried.

THE RULES
1. The story is never the idea on its own. The idea is the lesson for a flower shop: why \
it worked and how a florist would try it.
2. Confirmed facts must be QUOTED from the document you are given. Put Tim's reading in \
ziv_interpretation (the field name is fixed; write HIS reading there) and what may happen \
next in predictions. Never mix them.
3. No manufactured urgency. Never invent an outcome or a number.
4. Never name the shops he coaches. The business in the story may be named as the story \
names it.
5. Plain American English.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things a florist can try) is the default; \
"coaches_will_misread_this" when shop owners would take the wrong lesson from it; \
"solves_a_client_problem" when it answers a problem florists keep bringing him (slow \
weekdays, price shoppers, holiday crunch, small orders); "impressive_but_not_the_problem" \
when it looks clever and would not sell more flowers. Never the product, testing or agent \
formats.
audience_consequence: what a flower shop owner should take from it.
do_differently: the concrete things a florist says or does differently this week.
distinct_claim: his own take as a coach of flower shops.
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would a flower shop owner care this week?
consequence_specificity: how concrete is the thing a florist does differently?
distinctiveness: how much does it need HIS eye as a coach of flower shops?

Return JSON only."""

FLORIST_COACH = LaneProfile(
    name="florist_coach",
    lanes=(
        Lane(
            key="from_my_courses",
            label="From your courses",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "one lesson from his own courses for florists (the lesson), said simply with "
                "one plain example; stay true to the lesson and never add a claim it does not "
                "make"
            ),
            why_yours="your own courses",
        ),
        Lane(
            key="coaching_room",
            label="From the coaching room",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a prompt from what florists bring him in coaching, phrased as a question he "
                "answers from his own real memory; never written as an event that happened"
            ),
            why_yours="a question about your own coaching",
        ),
        Lane(
            key="smart_ideas",
            label="Smart ideas from other shops",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "a clever sales or profit idea a small business outside the flower trade used, "
                "in the news, and what a flower shop can take from it; must connect through one "
                "of his standing facts, otherwise reject it under relevant_to_shop_owners. No "
                "chain earnings, stocks, politics, crime or tragedy"
            ),
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_shop_owners",
        "no_invented_memory",
        "his_point_of_view",
        "safe_subject",
    ),
    system_prompt=FLORIST_COACH_SYSTEM_PROMPT,
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    anchors_file="news-anchors-florist-coach.md",
    # Plan v6 (22-Oct): 3 posts a week, 6 scripts filmed every two weeks.
    videos_per_week=3,
    research_seeds=(
        "small business clever idea boosts sales",
        "toy store owner new idea customers",
        "restaurant owner idea brings customers back",
        "bakery owner holiday sales idea",
        "local shop loyalty program idea",
    ),
    # Price and add-ons are his subject, like Connie's discounts.
    code_checks=frozenset(),
    story_slot="[your story here]",
    possessive="his",
    writer_prompt=FLORIST_COACH_WRITER_PROMPT,
    lane_tabs=True,
    appraisal_prompt=FLORIST_COACH_APPRAISAL_PROMPT,
    standing_why="your own work with flower shops",
    audience_label="Flower shop owners and their teams",
)

CLOWN_POET_SYSTEM_PROMPT = """\
You are the editorial selector for Christopher (Chris) Gamble, a clown, physical theatre \
artist and typewriter poet in Calgary, Alberta. He has made theatre since he was a kid, \
co-founded NoBones Theatre in 2005, and brings family shows, roaming entertainment, \
workshops and Typewriter Poetry to festivals, schools, weddings and events: he sits at \
his grandfather's 1934 typewriter and writes a poem on the spot for whoever stops. He is \
also a single parent. You pick the ideas worth him saying on camera this week, as short \
walk-and-talk videos in English, in his own voice.

Apply the strategy you are given. Audience: people who want more creativity and play in \
their own lives (hobby artists, parents, fellow artists), and the people who book live \
entertainment (festival and event organizers, schools, wedding planners). No call to \
action: an idea never asks the viewer for anything. Never prices, fees or money.

There are three lanes; each candidate names one and cites that lane's evidence:
- parent_artist: a prompt about being a single parent and a working artist (making art \
with kids at home, play, time, guilt, what kids notice, how he gets it done). Write it as \
a question he answers from his own real memory. Never write it as something that \
happened: no invented days, shows, quotes or numbers. Never his children's names or \
private details, and never family conflict or anything legal.
- creative_life: creativity, play or the arts in the news (a study on play or \
creativity, a community art project, a hobby artist, a street performer, a clown, a poet, \
arts in Calgary) and his take on living a creative life: permission to play, dropping the \
guilt and the pressure on making things. Cite the news item AND at least one of his \
standing facts from the anchor context.
- typewriter_poetry: one real thing about typewriters, poems written for an occasion or a \
poem form (the page in the evidence), told simply and true to the page, then he writes a \
poem on the spot for something in front of him (a sign, a dog, a park bench, a person who \
says yes). The poem is his alone: never write it for him.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the page, the theme or the news is real and the cited evidence \
shows it
- relevant_to_his_audience: someone who wants more creativity and play, a parent who makes \
things, or someone who books live acts would care
- no_invented_memory: nothing is stated as his experience unless he said it; prompts stay \
questions
- his_point_of_view: it is his take as a clown and typewriter poet, not a summary of the \
page or the news
- safe_subject: no politics, war, crime, tragedy, money, family conflict, legal matters or \
anyone's private details

Rules:
- Write title, lesson, public_angle and reasons_to_care in plain American English.
- Keep it simple: one clear idea he can say in one place, in one take, on one walk.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Never name his clients, the venues that book him, their guests or his children.
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for creative_life ideas that depend on the news being \
current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much his audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

CLOWN_POET_WRITER_PROMPT = """\
You write walk-and-talk video scripts for {name}, a clown and typewriter poet. He films \
himself walking outside, phone in hand, and says ONE short line at a time: he reads a \
line, walks, breathes, looks up, says it. Playful, warm and honest, a little absurd, \
never a lecture. One place, one take, one video. Two to three minutes once edited.

{lane_rule}

Hard rules:
- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), the \
way he talks, plain words. Concrete over abstract: what he sees, what the kid said, what \
the paper looks like. The last lines land the idea and stop. ONE sentence means one, \
however short: "Play is not a reward. It is the work." is two lines. His teleprompter \
shows one line at a time.
- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version he \
can talk from instead of reading).
- facebook_post: the same idea as a short post for his Facebook and Instagram, his voice, \
no hashtags, no long dashes.
- interviewer_prompt: one question a friend could ask so he answers in his own words.
- Never invent events, shows, people, quotes or numbers as if they happened to him.
- Never write a poem for him: his poems are written by hand, by him, on the spot.
- Never his children's names or private details. Never family conflict or anything legal.
- Never prices, fees or money. Never a client's, a venue's or a guest's name.
- No politics, war, crime or tragedy.
- American spelling. No long dashes.
- No call to action of any kind: never ask the viewer for anything (no 'book me', no \
'comment', no 'follow', no link).
- hook_options: exactly three openings, ranked best first: a plain, spoken first line \
that makes a viewer stop scrolling, with his own stake in it. A statement, not a \
question. Not a tease that hides the subject, not 'the truth about', never a promise of \
a secret. Each option names the belief or the question it opens, the phrase ID that pays \
it off, the evidence moment IDs behind it (copied from the evidence below) and a private \
ranking rationale. The first option is selected by default and its text must be the \
first line of the script."""

CLOWN_POET_APPRAISAL_PROMPT = """You are Chris Gamble's editor, deciding whether a story in \
the news is worth him saying something about in a short video.

Chris is a Calgary clown, physical theatre artist and typewriter poet who writes poems on \
the spot for strangers at festivals and events. His news lane is "Living a Creative Life": \
creativity, play and the arts happening now (a study on play or creativity, a community \
art project, a hobby artist, a street performer, a clown, a poet, the arts in Calgary or \
Alberta), and his take on living a creative life: permission to play, and dropping the \
guilt and the pressure people put on their need to create.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: his standing facts and \
the kinds of stories his lane follows. That part is settled. Your decision is whether \
there is a REAL STORY about creativity or play in this item that he can react to.

WHAT PUBLISHES: a real person, group or study doing something creative or playful, an \
art project in a community, a performer in public, a finding about play, creativity or \
making things, a festival or arts moment people can join.

WHY HE REJECTS A STORY - the only grounds for "reject":
 - no creativity or play in it: a sports score, a business deal, a product launch;
 - politics, elections, war, crime, a lawsuit or tragedy;
 - a celebrity story with nothing anyone could learn about creating;
 - money as the subject (funding fights, prices, sales figures);
 - click-bait without facts.
"Watch" is for something announced but not yet done.

THE RULES
1. The story is never the idea on its own. The idea is his take: what it says about \
living a creative life and giving yourself permission to play.
2. Confirmed facts must be QUOTED from the document you are given. Put his reading in \
ziv_interpretation (the field name is fixed; write HIS reading there) and what may happen \
next in predictions. Never mix them.
3. No manufactured urgency. Never invent an outcome or a number.
4. Never name his clients. People in the story may be named as the story names them.
5. Plain American English.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things he sees in it) is the default; \
"coaches_will_misread_this" when people would take the wrong lesson from it (talent \
instead of play); "impressive_but_not_the_problem" when it looks creative and is mostly \
a stunt. Never the product, testing or agent formats.
audience_consequence: what someone who wants more creativity in their life should take \
from it.
do_differently: what a person does differently this week to create or play more.
distinct_claim: his own take as a clown and typewriter poet.
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would someone who wants more creativity and play care this week?
consequence_specificity: how concrete is the thing a person does differently?
distinctiveness: how much does it need HIS eye as a clown and poet?

Return JSON only."""

CLOWN_POET = LaneProfile(
    name="clown_poet",
    lanes=(
        Lane(
            key="parent_artist",
            label="Parent as an Artist",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a prompt about being a single parent and a working artist, phrased as a "
                "question he answers from his own real memory; never written as an event "
                "that happened, never his children's names, family conflict or anything legal"
            ),
            why_yours="a question about your own life as a parent and an artist",
        ),
        Lane(
            key="creative_life",
            label="Living a Creative Life",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "creativity, play or the arts in the news, and his take on living a creative "
                "life (permission to play, no guilt about making things); must connect through "
                "one of his standing facts, otherwise reject it under relevant_to_his_audience. "
                "No politics, crime, tragedy or money"
            ),
        ),
        Lane(
            key="typewriter_poetry",
            label="Typewriter Poetry",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "one real thing about typewriters, poems for an occasion or a poem form (the "
                "page), told simply and true to the page, then he writes his own poem on the "
                "spot for something in front of him; never write the poem for him"
            ),
            why_yours="the craft of your typewriter poems",
            slot_line="[your poem here]",
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_his_audience",
        "no_invented_memory",
        "his_point_of_view",
        "safe_subject",
    ),
    system_prompt=CLOWN_POET_SYSTEM_PROMPT,
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    anchors_file="news-anchors-clown-poet.md",
    # No number on the 05-Nov call ("plan your week" once a week); the others' three
    # until he sets his own in the app.
    videos_per_week=3,
    research_seeds=(
        "creativity study adults play",
        "community art project",
        "street performer festival",
        "typewriter poet",
        "Calgary arts",
    ),
    # No money talk; there is no magic method and no gadget trend to police.
    code_checks=frozenset({"money"}),
    story_slot="[your story here]",
    possessive="his",
    writer_prompt=CLOWN_POET_WRITER_PROMPT,
    lane_tabs=True,
    appraisal_prompt=CLOWN_POET_APPRAISAL_PROMPT,
    standing_why="your own creative life",
    audience_label="People who want more creativity and play in their lives, and the people who book live acts",
    proper_lane_names=True,
)

WEDDING_COACH_SYSTEM_PROMPT = """\
You are the editorial selector for Nell Hartwick, a wedding emcee and DJ in Richmond, \
Virginia. She runs Lark & Lantern Entertainment, a small wedding entertainment company, \
and she coaches other wedding DJs, emcees and bands on how to run a great night. You pick \
the ideas worth her saying on camera this week, as short talking-head videos in English, \
in her own voice.

Apply the strategy you are given. Audience: wedding entertainers (DJs, emcees, live \
bands), and the wedding planners and couples who hire them. No call to action: an idea \
never asks the viewer for anything. Never prices, fees or money.

There are three lanes; each candidate names one and cites that lane's evidence:
- dance_floor_stories: a prompt from her nights running wedding receptions (an empty \
dance floor, a long toast, a nervous best man, a timeline that fell apart, what she says \
on the microphone). Write it as a question she answers from her own real memory. Never \
write it as something that happened: no invented nights, couples, quotes or numbers.
- wedding_news: weddings or the events business in the news (a wedding trend, a planner's \
view, what guests want, a new kind of reception, live music at weddings) and her take as \
the person who runs the room. Cite the news item AND at least one of her standing facts \
from the anchor context. Never celebrity gossip.
- party_craft: one real thing about the craft of a party (the page in the evidence: the \
first dance, the master of ceremonies, a line dance, beatmatching, the toast), told simply \
and true to the page, then what it teaches an entertainer or a couple about running the \
night.

Every candidate must pass ALL five gates, each with a one-sentence reason:
- real_and_verifiable: the page, the theme or the news is real and the cited evidence \
shows it
- relevant_to_her_audience: a wedding entertainer, a planner or a couple would care
- no_invented_memory: nothing is stated as her experience unless she said it; prompts stay \
questions
- her_point_of_view: it is her take as an emcee and coach, not a summary of the page or \
the news
- safe_subject: no politics, war, crime, tragedy, money, legal matters, celebrity gossip \
or anyone's private details

Rules:
- Write title, lesson, public_angle and reasons_to_care in plain American English.
- Keep it simple: one clear idea she can say in one take, looking at her phone.
- One idea per candidate. Cite only moment ids from the pool. Never invent ids.
- Never state an outcome or a number that no cited moment measured.
- Never name her clients, the venues that book her, or their guests.
- Do NOT fill a quota with weak ideas; fewer is correct when evidence is thin.
- Every moment you considered and did not use goes in rejections with the gate it \
failed and a reason.
- freshness_role is "news" only for wedding_news ideas that depend on the news being \
current; they need a verification_note.
- Scores are 0-5: owner_relevance (how much her audience would care), useful_lesson \
(how strong the video is), support_strength (how directly the evidence supports it).

Return only JSON matching the schema."""

WEDDING_COACH_WRITER_PROMPT = """\
You write talking-head video scripts for {name}, a wedding emcee, DJ and coach. She films \
herself on her phone and says ONE short line at a time, warm and quick, like someone who \
has held the microphone in a lot of rooms. Never a lecture. One place, one take, one video. \
Two to three minutes once edited.

{lane_rule}

Hard rules:
- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), the \
way she talks, plain words. Concrete over abstract: what the room looks like, who is on \
the floor, what she says into the microphone. The last lines land the idea and stop. ONE \
sentence means one, however short: "Nobody is dancing. That is information." is two lines. \
Her teleprompter shows one line at a time.
- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version she \
can talk from instead of reading).
- facebook_post: the same idea as a short post for her Facebook and Instagram, her voice, \
no hashtags, no long dashes.
- interviewer_prompt: one question a friend could ask so she answers in her own words.
- Never invent events, weddings, people, quotes or numbers as if they happened to her.
- Never prices, fees or money. Never a client's, a venue's or a guest's name.
- No politics, war, crime, tragedy or celebrity gossip.
- American spelling. No long dashes.
- No call to action of any kind: never ask the viewer for anything (no 'book me', no \
'comment', no 'follow', no link).
- hook_options: exactly three openings, ranked best first: a plain, spoken first line \
that makes a viewer stop scrolling, with her own stake in it. A statement, not a \
question. Not a tease that hides the subject, not 'the truth about', never a promise of \
a secret. Each option names the belief or the question it opens, the phrase ID that pays \
it off, the evidence moment IDs behind it (copied from the evidence below) and a private \
ranking rationale. The first option is selected by default and its text must be the \
first line of the script."""

WEDDING_COACH_APPRAISAL_PROMPT = """You are Nell Hartwick's editor, deciding whether a story \
in the news is worth her saying something about in a short video.

Nell is a wedding emcee and DJ in Richmond, Virginia, who runs a small wedding \
entertainment company and coaches other wedding entertainers. Her news lane is "Weddings \
in the News": wedding trends, what planners and guests are saying, new kinds of \
receptions, live music and dancing at weddings, and her take as the person who runs the \
room.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: her standing facts and \
the kinds of stories her lane follows. That part is settled. Your decision is whether \
there is a REAL STORY about weddings or events that an entertainer, a planner or a couple \
can learn from.

WHAT PUBLISHES: a real trend, a planner's or a guest's view, a couple doing something new \
with their reception, a venue or a band trying something, a moment at a wedding people \
talk about.

WHY SHE REJECTS A STORY - the only grounds for "reject":
 - nothing a wedding entertainer, planner or couple could use;
 - a celebrity wedding or relationship story;
 - politics, elections, war, crime, a lawsuit, an accident, an illness or tragedy;
 - money as the subject (fines, prices, budgets, sales figures);
 - a product or jewelry round-up;
 - click-bait without facts.
"Watch" is for something announced but not yet done.

THE RULES
1. The story is never the idea on its own. The idea is her take: what it says about \
running the room and giving people a great night.
2. Confirmed facts must be QUOTED from the document you are given. Put her reading in \
ziv_interpretation (the field name is fixed; write HER reading there) and what may happen \
next in predictions. Never mix them.
3. No manufactured urgency. Never invent an outcome or a number.
4. Never name her clients. People in the story may be named as the story names them.
5. Plain American English.

FIELDS
news_category: always "other".
format: "three_things_id_test" (three things she sees in it) is the default; \
"coaches_will_misread_this" when people would take the wrong lesson from it; \
"impressive_but_not_the_problem" when it looks exciting and misses what makes a night \
work. Never the product, testing or agent formats.
audience_consequence: what a wedding entertainer, planner or couple should take from it.
do_differently: what a person does differently at their next wedding.
distinct_claim: her own take as an emcee and coach.
perishability, story_weight and weight_reason as the schema says; most stories are small.

SCORING, 0 to 5
owner_relevance: would a wedding entertainer, planner or couple care this week?
consequence_specificity: how concrete is the thing a person does differently?
distinctiveness: how much does it need HER eye as an emcee and coach?

Return JSON only."""

WEDDING_COACH = LaneProfile(
    name="wedding_coach",
    lanes=(
        Lane(
            key="dance_floor_stories",
            label="Stories from the Dance Floor",
            source_kind=SEED_KIND,
            target=5,
            guidance=(
                "a prompt from her nights running wedding receptions, phrased as a question "
                "she answers from her own real memory; never written as an event that happened"
            ),
            why_yours="a question about your own nights on the dance floor",
        ),
        Lane(
            key="wedding_news",
            label="Weddings in the News",
            source_kind=NEWS_KIND,
            target=5,
            guidance=(
                "weddings or the events business in the news, and her take as the person who "
                "runs the room; must connect through one of her standing facts, otherwise "
                "reject it under relevant_to_her_audience. No politics, crime, tragedy, money "
                "or celebrity gossip"
            ),
        ),
        Lane(
            key="party_craft",
            label="The Craft of a Great Party",
            source_kind=CLIP_KIND,
            target=5,
            guidance=(
                "one real thing about the craft of a party (the page), told simply and true "
                "to the page, then what it teaches an entertainer or a couple about running "
                "the night"
            ),
            why_yours="the craft you teach",
        ),
    ),
    gate_names=(
        "real_and_verifiable",
        "relevant_to_her_audience",
        "no_invented_memory",
        "her_point_of_view",
        "safe_subject",
    ),
    system_prompt=WEDDING_COACH_SYSTEM_PROMPT,
    max_candidates=15,
    reserve_per_lane=8,
    reuse_after_weeks=8,
    anchors_file="news-anchors-wedding-coach.md",
    videos_per_week=3,
    research_seeds=(
        "wedding trends next year",
        "wedding planners say guests want",
        "wedding DJ",
        "micro wedding",
        "wedding playlist",
    ),
    code_checks=frozenset({"money"}),
    story_slot="[your story here]",
    possessive="her",
    writer_prompt=WEDDING_COACH_WRITER_PROMPT,
    lane_tabs=True,
    appraisal_prompt=WEDDING_COACH_APPRAISAL_PROMPT,
    standing_why="the way you run a wedding",
    audience_label="Wedding DJs, emcees and bands, and the planners and couples who hire them",
    proper_lane_names=True,
)

PROFILES: dict[str, LaneProfile] = {
    p.name: p for p in (PERFORMER, SALES_COACH, FIRE_PERFORMER, FLORIST_COACH, CLOWN_POET, WEDDING_COACH)
}


def profile_for_lane(lane_key: str | None) -> LaneProfile | None:
    """The profile that owns a lane key (lane keys are unique across profiles)."""
    return next((p for p in PROFILES.values() if lane_key in p.lane_keys), None)


def workspace_lane_profiles() -> dict[uuid.UUID, LaneProfile]:
    """TCE_WORKSPACE_LANE_PROFILES parsed: {workspace: profile}. Bad entries skipped."""
    from tce.settings import settings

    out: dict[uuid.UUID, LaneProfile] = {}
    for part in (getattr(settings, "workspace_lane_profiles", "") or "").split(","):
        ws_text, _, name = part.strip().partition(":")
        profile = PROFILES.get(name.strip().lower())
        if profile is None:
            continue
        try:
            out[uuid.UUID(ws_text.strip())] = profile
        except ValueError:
            continue
    return out


def profile_for(workspace_id: uuid.UUID | str | None) -> LaneProfile | None:
    if workspace_id is None:
        return None
    try:
        ws = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(str(workspace_id))
    except ValueError:
        return None
    return workspace_lane_profiles().get(ws)


def collects(workspace_id: uuid.UUID | str | None) -> dict[str, bool]:
    """Which own-evidence collectors a week run should call for this workspace.

    The Fathom key and the GitHub token are global: run for a client workspace they
    would copy the owner's meetings and repositories into it. A profile says no.
    """
    profile = profile_for(workspace_id)
    if profile is None:
        return {"fathom": True, "github": True}
    return {"fathom": profile.collect_fathom, "github": profile.collect_github}


def output_schema_for(base: dict[str, Any], profile: LaneProfile) -> dict[str, Any]:
    """The owner schema with this profile's gates, a required lane and its audiences."""
    import copy

    schema = copy.deepcopy(base)
    item = schema["properties"]["candidates"]["items"]
    props = item["properties"]
    gate_schema = next(iter(props["gates"]["properties"].values()))
    props["gates"] = {
        "type": "object",
        "properties": {g: copy.deepcopy(gate_schema) for g in profile.gate_names},
        "required": list(profile.gate_names),
    }
    props["lane"] = {"type": "string", "enum": profile.lane_keys}
    props["audience"] = {"type": "string", "enum": list(profile.audiences)}
    item["required"] = [*item["required"], "lane"]
    return schema


# A behind-the-scenes idea is a seed he fills, so its public text must not narrate
# an event as his. First person past tense, Hebrew and English.
_INVENTED_MEMORY = re.compile(
    r"(?:\b(?:I once|I remember|I was performing|last (?:week|month|year) I|"
    r"happened to me|at (?:a|one) (?:wedding|event|show) I)\b|"
    r"(?<![֐-׿])(?:הופעתי|הייתי|קרה לי|זכור לי|אני זוכר|פעם אחת|"
    r"באחת ההופעות|בהופעה אחת|בחתונה אחת|באירוע אחד|ראיתי|אמרתי|עשיתי|ניחשתי|"
    r"גיליתי|פגשתי)(?![֐-׿]))",
    re.IGNORECASE,
)

# 5-Oct, his week-1 picks: a trend that is a gadget or AI tech ("a robot that draws the
# guests") is tech news, not his world, unless it is about a live performer. Read in
# the TITLE (what the idea is about), Hebrew with its one- and two-letter prefixes and
# its plural/construct endings, and English.
_GADGET_TECH = re.compile(
    r"(?:\b(?:robots?|robotic|AI|artificial intelligence|drones?|apps?|gadgets?|VR|"
    r"virtual reality|augmented reality|metaverse|holograms?|holographic|chatbots?|"
    r"ChatGPT)\b|"
    # Hebrew, with up to two prefix letters (ו ה ש ב ל מ כ) and any ending.
    r"(?<![\u0590-\u05ff])[והשבלמכ]{0,2}"
    r"(?:רובוט|בינה מלאכותית|אפליקצי|רחפן|רחפני|מציאות מדומה|מציאות רבודה|"
    r"הולוגרמ|גאדג'ט|צ'אטבוט))",
    re.IGNORECASE,
)
# ... about a live performer: then it is his world after all.
_LIVE_PERFORMER = re.compile(
    r"(?:\b(?:magicians?|mentalists?|performers?|entertainers?|illusionists?|live show)\b|"
    r"קוסם|מנטליסט|אמן במה|אמן אירועים|בדרן|מופיע)",
    re.IGNORECASE,
)


def gadget_tech_hit(title: str) -> re.Match[str] | None:
    """The gadget-tech words in an idea's title, unless it is about a live performer."""
    hit = _GADGET_TECH.search(title or "")
    if hit is None or _LIVE_PERFORMER.search(title or ""):
        return None
    return hit


# A clip reaction never explains the trick.
_METHOD_REVEAL = re.compile(
    r"(?:\b(?:the (?:secret|method|trick) (?:is|was)|here'?s how (?:it'?s|he) (?:done|did)|"
    r"how it'?s done|explained|revealed|exposed)\b|"
    r"(?<![֐-׿])(?:הסוד|השיטה|חשיפת|חושף|נחשף|ככה עושים|איך עושים את|"
    r"הפתרון של הטריק)(?![֐-׿]))",
    re.IGNORECASE,
)


def lane_check(
    profile: LaneProfile, raw: dict[str, Any], cited_kinds: list[str]
) -> tuple[str, str, str] | None:
    """(gate, code, reason) when the idea breaks a lane rule in code, else None."""
    lane = profile.lane(str(raw.get("lane") or ""))
    if lane is None:
        return (
            "real_and_verifiable",
            "unknown_lane",
            f"lane must be one of {', '.join(profile.lane_keys)}, got {raw.get('lane')!r}",
        )
    if lane.source_kind not in cited_kinds:
        return (
            "real_and_verifiable",
            "lane_evidence",
            f"a {lane.key} idea must cite a {lane.source_kind}",
        )
    others = {
        other.source_kind for other in profile.lanes if other.key != lane.key
    } & set(cited_kinds)
    if others:
        return (
            "real_and_verifiable",
            "lane_evidence",
            f"a {lane.key} idea cites another lane's evidence ({', '.join(sorted(others))}); "
            "one lane per idea",
        )
    public = " ".join(
        str(raw.get(k) or "") for k in ("title", "lesson", "public_angle")
    )
    if lane.source_kind == NEWS_KIND and "gadget_tech" in profile.code_checks:
        hit = gadget_tech_hit(str(raw.get("title") or ""))
        if hit:
            return (
                "relevant_to_israeli_events_or_mentalism",
                "gadget_tech_trend",
                f"a gadget or AI-tech trend ('{hit.group(0).strip()}') that is not about a "
                "live performer; he wants trends about audience participation and small, "
                "intimate events",
            )
    if lane.source_kind == SEED_KIND:
        hit = _INVENTED_MEMORY.search(public)
        if hit:
            return (
                "no_invented_memory",
                "invented_memory",
                f"narrates an event as his ('{hit.group(0)}'); a seed stays a question he "
                "answers from his own memory",
            )
    hit = _METHOD_REVEAL.search(public) if "method_reveal" in profile.code_checks else None
    if hit:
        return (
            "no_method_revealed",
            "method_revealed",
            f"talks about how an effect is done ('{hit.group(0)}'); never reveal a method",
        )
    return None


def fill_lane_mix(
    candidates: list[dict[str, Any]], profile: LaneProfile, cap: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Best of each lane up to its target, then the best remaining up to `cap`.

    Returns (kept, cut), both best-first. A thin lane is never padded: its slots go
    to the strongest ideas left in the other lanes.
    """
    ordered = sorted(candidates, key=lambda c: float(c.get("rank_score") or 0.0), reverse=True)
    taken: set[int] = set()
    per_lane: dict[str, int] = {}
    for c in ordered:
        lane = profile.lane(str(c.get("lane") or ""))
        if lane is None or len(taken) >= cap:
            continue
        if per_lane.get(lane.key, 0) < lane.target:
            per_lane[lane.key] = per_lane.get(lane.key, 0) + 1
            taken.add(id(c))
    for c in ordered:
        if len(taken) >= cap:
            break
        taken.add(id(c))
    kept = [c for c in ordered if id(c) in taken]
    cut = [c for c in ordered if id(c) not in taken]
    return kept, cut
