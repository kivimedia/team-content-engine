"""The packet (script) writer of a workspace with idea lanes (5-Oct, Matan).

The owner's writer (packets.SYSTEM_PROMPT) is Ziv's: English, coaching, "tell it from
Ziv's own first-person experience". Run for a performer it would put invented stories
in his mouth, so a lane workspace stopped at ranking. This writer is its own:

- built from the idea's lane and from his own profile (persona.voice_block()),
- a walk-and-talk script, ONE sentence a line, a bullet version, and three openings,
- behind_scenes: questions and prompts around HIS memory with the slot
  [הסיפור שלך כאן] where his real story goes; never a first-person event (code-checked),
- magic_clip: never explains, hints at or guesses a method (code-checked, every lane),
- no money, no call to action, no invented events in any lane (code-checked).

packets.build_packet sends a lane workspace here and never builds its own prompt for
one. The packet is an ordinary RecordingPacket (same job type, same nonce header), so
the recording list, the scheduler's resume and choosing an opening work unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Any

PROMPT_VERSION = "lane_packet.v1"
SLOT = "[הסיפור שלך כאן]"
MAX_WORDS_PER_LINE = 16

_LANE_RULES = {
    "trend_reaction": (
        "THIS IDEA'S LANE: trend_reaction. A real trend or attraction from the world event "
        "industry and HIS reaction to it as an Israeli event performer. Say what the trend is "
        "in one plain line, then react: would it work at an Israeli wedding, bar or bat "
        "mitzvah or company event, what he would take from it, what he would never do. "
        "Opinions and reactions only. Never a story about a show he did, a guest he met or "
        "something he saw happen: you do not know his memories."
    ),
    "magic_clip": (
        "THIS IDEA'S LANE: magic_clip. A famous clip by a great magician or mentalist. Say what "
        "the audience saw, from the audience's seat; why it plays so well on a crowd; what he "
        "would change for an Israeli crowd. NEVER explain, hint at or guess how it is done, "
        "never name a method, a gimmick or a secret, and never say it is 'easy' or 'simple'. "
        "Respect the performer: never mock him."
    ),
    "behind_scenes": (
        "THIS IDEA'S LANE: behind_scenes. A moment from a mentalist's life that HE will tell from "
        "his OWN memory. You do not know what happened to him, so you never write it. Write the "
        "frame around his story instead: a line that opens the moment as a question, short "
        "prompts that help him remember (who was there, what he felt, what the crowd did, what "
        "he learned), one line that is exactly " + SLOT + " where his real story goes, and a "
        "closing thought phrased as a question or a general truth, never as an event. Never a "
        "first-person past tense sentence (no 'I once', 'I remember', 'at one wedding I'), no "
        "invented audiences, no invented numbers. interviewer_prompt is the one memory question "
        "he answers on camera."
    ),
    # 23-Oct: the sales_coach profile (Connie). Her slot and her checks come from the
    # profile (lane_profile.SALES_COACH): price and discount talk is her subject.
    "from_teaching": (
        "THIS IDEA'S LANE: from_teaching. One idea from her own published teaching (the page "
        "in the evidence). Say it simply, the way she would explain it to a friend, with one "
        "plain example of what a rep says or does on a call. Stay true to the page: never add "
        "a claim, a number or a study it does not make."
    ),
    "practice_room": (
        "THIS IDEA'S LANE: practice_room. A moment from practice (her coaching sessions or the "
        "Dojo) that SHE will tell from her OWN memory. You do not know what happened, so you "
        "never write it. Write the frame around her story instead: a line that opens the "
        "moment, short prompts that help her remember (who was practicing, what they said, "
        "what she noticed, what changed), one line that is exactly [your story here] where her "
        "real story goes, and a closing lesson for any rep phrased as a general truth, never as "
        "an event. Never a first-person past tense sentence (no 'I once', 'I remember'), no "
        "invented reps, quotes or numbers. interviewer_prompt is the one memory question she "
        "answers on camera."
    ),
    "in_the_wild": (
        "THIS IDEA'S LANE: in_the_wild. A real negotiation in the news and what it teaches a "
        "rep on a sales call. Say what happened in one plain line, using only what the news "
        "item says, then the lesson: what a pleaser would do, what a leader does, the words a "
        "rep can use this week. Opinions and lessons only. Never a story about a client or a "
        "call she had: you do not know her memories."
    ),
    # 28-Oct: the fire_performer profile (Brant). His slot and his checks come from the
    # profile (lane_profile.FIRE_PERFORMER).
    "sacred_flame": (
        "THIS IDEA'S LANE: sacred_flame. A real myth, ritual or moment in the history of fire "
        "(the page in the evidence). Tell it simply, the way he would tell it to a crowd before "
        "he lights up, using only what the page says, then his take as a fire performer of 30 "
        "years: what that story means to someone who works with fire every week. Never add a "
        "date, a number or a detail the page does not give. Respect every culture and faith in "
        "it: never mock a ritual."
    ),
    "keeper_of_flame": (
        "THIS IDEA'S LANE: keeper_of_flame. A moment from his 30 years as a fire performer that "
        "HE will tell from his OWN memory. You do not know what happened, so you never write it. "
        "Write the frame around his story instead: a line that opens the moment, short prompts "
        "that help him remember (where he was, what the fire did, what the crowd did, what he "
        "learned), one line that is exactly [your story here] where his real story goes, and a "
        "closing thought phrased as a general truth about fire or performing, never as an event. "
        "Never a first-person past tense sentence (no 'I once', 'I remember'), no invented "
        "shows, crowds or numbers. interviewer_prompt is the one memory question he answers on "
        "camera."
    ),
    "taming_fire": (
        "THIS IDEA'S LANE: taming_fire. A real record, stunt or feat of danger mastery in the "
        "news and his take on it as a Guinness World Record holder (101 torches extinguished by "
        "fire eating in one minute). Say what happened in one plain line, using only what the "
        "news item says, then his take: the control, the preparation and the respect for danger "
        "behind it. Where his own record day would compare, put one line that is exactly "
        "[your story here]; never write what that day was like for him. Never a story about a "
        "show he did: you do not know his memories."
    ),
}

_HOOK_RULE = (
    "- hook_options: exactly three openings, ranked best first, the way he opens when he "
    "talks to a friend: a plain, spoken first line that makes a viewer at an event stop "
    "scrolling. Not a tease that hides the subject, not 'the truth about', never a promise of "
    "a secret. Each option names the belief or the question it opens, the phrase ID that pays "
    "it off, the evidence moment IDs behind it (copied from the evidence below) and a private "
    "ranking rationale. The first option is selected by default and its text must be the first "
    "line of the script."
)


def system_prompt(lane: str, persona: Any) -> str:
    from tce.editorial.lane_profile import profile_for_lane

    profile = profile_for_lane(lane)
    voice = persona.voice_block() if persona is not None else ""
    if profile is not None and profile.writer_prompt is not None:
        name = getattr(persona, "name", "") or "the creator"
        return (
            profile.writer_prompt.replace("{name}", name).replace("{lane_rule}", _LANE_RULES[lane])
            + "\n- beats: one beat for each bullet. Use stable phrase IDs p001, p002 and so on and "
            "map every beat to an ordered inclusive phrase range.\n"
            "- self_check: report honestly whether each rule holds.\n\n"
            + (voice + "\n\n" if voice else "")
            + "Return only JSON matching the schema."
        )
    name = getattr(persona, "name", "") or "the performer"
    return (
        f"You write walk-and-talk video scripts for {name}. He films himself walking, phone in "
        "hand, and says ONE sentence at a time: he reads a line, looks up, says it.\n\n"
        + _LANE_RULES[lane]
        + "\n\nHard rules:\n"
        "- script_phrases: the FULL script, one spoken sentence per line, short (3-14 words), "
        "the way he talks, never written or translated language. The last lines land the idea "
        "and stop.\n"
        "- bullets: 5 to 7 short bullets, the same video as talking points (the bullet version "
        "he can talk from instead of reading).\n"
        "- facebook_post: the same idea as a short post for his Facebook page, his voice, no "
        "hashtags, no long dashes.\n"
        "- interviewer_prompt: one question a friend could ask so he answers in his own words.\n"
        "- Never invent events, audiences, quotes or numbers as if they happened to him.\n"
        "- Never explain, hint at or guess how any effect is done.\n"
        "- Never prices, fees, budgets, money, debts. Never a client's, a lead's or a guest's "
        "name. Never mock another magician or mentalist.\n"
        "- No call to action of any kind: never ask the viewer for anything (no 'write to me', "
        "no 'comment', no 'follow', no link, no WhatsApp).\n"
        + _HOOK_RULE
        + "\n- beats: one beat for each bullet. Use stable phrase IDs p001, p002 and so on and map "
        "every beat to an ordered inclusive phrase range.\n"
        "- self_check: report honestly whether each rule holds.\n\n"
        + (voice + "\n\n" if voice else "")
        + "Return only JSON matching the schema."
    )


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 7},
        "script_phrases": {"type": "array", "items": {"type": "string"}, "minItems": 6},
        "facebook_post": {"type": "string"},
        "interviewer_prompt": {"type": "string"},
        "hook_options": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["id", "text", "question", "payoff_phrase_id", "moment_ids", "rationale"],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "question": {"type": "string"},
                    "payoff_phrase_id": {"type": "string"},
                    "moment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "rationale": {"type": "string"},
                },
            },
        },
        "selected_hook_id": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "label", "bullet_index", "start_phrase_id", "end_phrase_id"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "bullet_index": {"type": "integer"},
                    "start_phrase_id": {"type": "string"},
                    "end_phrase_id": {"type": "string"},
                },
            },
        },
        "self_check": {
            "type": "object",
            "properties": {
                "one_idea": {"type": "boolean"},
                "no_method_revealed": {"type": "boolean"},
                "no_invented_memory": {"type": "boolean"},
                "no_money": {"type": "boolean"},
                "no_names": {"type": "boolean"},
                "no_call_to_action": {"type": "boolean"},
                "notes": {"type": "string"},
            },
        },
    },
    "required": [
        "bullets",
        "script_phrases",
        "facebook_post",
        "interviewer_prompt",
        "hook_options",
        "selected_hook_id",
        "beats",
        "self_check",
    ],
}


def build_prompt(cand: Any, lane: str, post_rules: str = "") -> str:
    evidence = [
        {
            "moment_id": str(c.get("moment_id") or ""),
            "source_kind": c.get("source_kind"),
            "excerpt_private": (c.get("excerpt_private") or "")[:800],
        }
        for c in (cand.citations_private or [])
        if isinstance(c, dict)
    ]
    allowed = [str(v) for v in (cand.moment_ids or [])]
    for item, fallback in zip(evidence, allowed, strict=False):
        if not item["moment_id"]:
            item["moment_id"] = fallback
    parts = []
    if post_rules:
        parts.append("HIS POST RULES (they always win):\n" + post_rules)
    parts.append(f"LANE: {lane}")
    parts.append(
        "SELECTED IDEA:\n"
        + json.dumps(
            {
                "title": cand.title,
                "lesson": cand.lesson,
                "public_angle": cand.public_angle,
                "reasons_to_care": cand.reasons_to_care,
                "editor_notes": cand.editor_notes,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    parts.append(
        "EVIDENCE (for accuracy only; a story seed is a QUESTION for him, never his memory). "
        "Every hook's moment_ids must be copied verbatim from the moment_id values below:\n"
        + json.dumps(evidence, ensure_ascii=False, indent=1)
    )
    return "\n\n".join(parts)


# A narrated event in any lane: unambiguous first-person past tense openers. Narrower
# than lane_profile._INVENTED_MEMORY so "what I would change" (magic_clip) stays legal.
_INVENTED_EVENT = re.compile(
    r"(?:\b(?:I once|I remember|happened to me|last (?:week|month|year) I|"
    r"at (?:a|one) (?:wedding|event|show) I)\b|"
    r"(?<![֐-׿])(?:קרה לי|זכור לי|אני זוכר|פעם אחת|באחת ההופעות|בהופעה אחת|"
    r"בחתונה אחת|באירוע אחד|הופעתי)(?![֐-׿]))",
    re.IGNORECASE,
)
# Hebrew words take one-letter prefixes (ה, ב, ל, ו, כ, ש, מ): "המחיר", "בתקציב".
_MONEY = re.compile(
    r"(?:₪|\$|\b(?:price|prices|budget|fee|fees|discount)\b|"
    r"(?<![֐-׿])[הבלוכשמ]?(?:שקלים|ש\"ח|מחיר|מחירים|תקציב|חובות|תזרים|משכורת)(?![֐-׿]))",
    re.IGNORECASE,
)
_ASK_HE = re.compile(
    r"(?<![֐-׿])ו?(?:כתבו לי|תכתבו לי|שלחו לי|תשלחו לי|כתבו בתגובות|תכתבו בתגובות|"
    r"תגיבו|עקבו|תעקבו|הירשמו|תירשמו|לינק בביו|קישור בביו|דברו איתי)(?![֐-׿])"
)

# Review 5-Oct: Hebrew glues one-letter prefixes onto a word ("כשהופעתי", "והסוד",
# "וראיתי"), and the bare-word checks above and in lane_profile missed every one. The
# writer's checks take up to three prefix letters.
_HE_PREFIX = r"(?<![֐-׿])[ובכלמשה]{0,3}"


def _he_words(*words: str) -> re.Pattern[str]:
    return re.compile(_HE_PREFIX + "(?:" + "|".join(re.escape(w) for w in words) + r")(?![֐-׿])")


_EVENT_HE = _he_words(
    "קרה לי", "זכור לי", "אני זוכר", "פעם אחת", "באחת ההופעות", "בהופעה אחת",
    "בחתונה אחת", "באירוע אחד", "הופעתי",
)
_MEMORY_HE = _he_words(
    "הופעתי", "הייתי", "קרה לי", "זכור לי", "אני זוכר", "פעם אחת", "באחת ההופעות",
    "בהופעה אחת", "בחתונה אחת", "באירוע אחד", "ראיתי", "אמרתי", "עשיתי", "ניחשתי",
    "גיליתי", "פגשתי",
)
_METHOD_HE = _he_words(
    "הסוד", "השיטה", "חשיפת", "חושף", "נחשף", "ככה עושים", "איך עושים את",
    "הפתרון של הטריק", "הטריק הוא", "הטריק פה", "הטריק כאן", "גימיק", "גימיקים",
)


def method_hit(text: str) -> re.Match[str] | None:
    """Talk about how an effect is done, English or (prefixed) Hebrew."""
    from tce.editorial.lane_profile import _METHOD_REVEAL

    return _METHOD_REVEAL.search(text) or _METHOD_HE.search(text)


def lane_errors(clean: dict[str, Any], lane: str) -> list[str]:
    """What breaks a lane rule in code. Empty = the packet may be saved."""
    from tce.editorial.lane_profile import _INVENTED_MEMORY, PERFORMER, SEED_KIND, profile_for_lane

    profile = profile_for_lane(lane) or PERFORMER
    checks = profile.code_checks
    slot = profile.story_slot
    lane_def = profile.lane(lane)
    errors: list[str] = []
    phrases = list(clean.get("script_phrases") or [])
    public = [
        *clean.get("bullets", []),
        *phrases,
        str(clean.get("facebook_post") or ""),
        str(clean.get("interviewer_prompt") or ""),
        *[str(o.get("text") or "") for o in clean.get("hook_options") or []],
    ]
    for i, line in enumerate(phrases, 1):
        if slot in line:
            continue
        if re.search(r"[.!?…]\s+\S", line.strip()):
            errors.append(f"script line {i} holds more than one sentence: one sentence a line")
        if len(line.split()) > MAX_WORDS_PER_LINE:
            errors.append(f"script line {i} is too long to say in one breath ({len(line.split())} words)")
    for text in public if "method_reveal" in checks else []:
        hit = method_hit(text)
        if hit:
            errors.append(f"talks about how an effect is done ('{hit.group(0)}'); never reveal a method")
            break
    who = "he" if profile.possessive == "his" else "she"
    for text in public:
        bare = text.replace(slot, " ")
        hit = _INVENTED_EVENT.search(bare) or _EVENT_HE.search(bare)
        if hit:
            errors.append(
                f"narrates an event as {profile.possessive} ('{hit.group(0)}'); only {who} knows "
                "what happened"
            )
            break
    for text in public if "money" in checks else []:
        hit = _MONEY.search(text)
        if hit:
            errors.append(f"mentions money ('{hit.group(0)}'); never money or prices")
            break
    for text in public:
        hit = _ASK_HE.search(text)
        if hit:
            errors.append(f"no call to action is allowed: '{hit.group(0)}'")
            break
    if lane_def is not None and lane_def.source_kind == SEED_KIND:
        own = profile.possessive
        slots = [i for i, p in enumerate(phrases) if slot in p]
        if len(slots) != 1:
            errors.append(f"a {lane} script has exactly one line {slot} where {own} own story goes")
        for text in public:
            bare = text.replace(slot, " ")
            hit = _INVENTED_MEMORY.search(bare) or _MEMORY_HE.search(bare)
            if hit:
                errors.append(
                    f"narrates an event as {own} ('{hit.group(0)}'); a story seed stays questions "
                    f"around {own} own memory"
                )
                break
        if sum(1 for p in phrases if "?" in p) < 2:
            errors.append(f"a {lane} script is built from questions: at least two lines ask")
        if "?" not in str(clean.get("interviewer_prompt") or ""):
            errors.append(f"interviewer_prompt must be the memory question {who} answers")
    # One error per rule is enough to refuse; keep the list short and readable.
    return list(dict.fromkeys(errors))


def validate(data: Any, lane: str, *, news_terms: list[str] | None = None) -> dict[str, Any]:
    """The owner's shape rules (no LinkedIn post), then the lane's own rules."""
    from tce.editorial.packets import PacketValidationError, validate_packet_output

    clean = validate_packet_output(
        data, news_terms=news_terms, forbid_asks=True, require_linkedin=False
    )
    problems = lane_errors(clean, lane)
    if problems:
        raise PacketValidationError("; ".join(problems))
    return clean
