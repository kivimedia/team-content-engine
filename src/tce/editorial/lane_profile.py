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
)

PROFILES: dict[str, LaneProfile] = {PERFORMER.name: PERFORMER}


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
    if lane.source_kind == NEWS_KIND:
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
    hit = _METHOD_REVEAL.search(public)
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
