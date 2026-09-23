"""What the voice agent is allowed to do, and how each thing is said back.

The voice agent is an Opus brain on a live call. It hears Ziv, reads a change
back to him, and then applies it at once (his decision, 23-Sep). That is only
safe because three things hold, and this module is where they hold:

  1. Every write is attributed. Change sets carry origin `voice`, decisions carry
     decided_by `voice`, so the workspace lists exactly what the call changed.
  2. Every write is undoable by id. `undo_change_set` builds the inverse of an
     applied change set as a NEW change set, never an edit in place, and refuses
     (with the text as it is now) when something changed after it.
  3. A stale read is caught. The brain passes the text it read back, and must
     when it replaces text that exists; if the script says something else by
     the time it applies, nothing is written and the fresh text comes back so it
     can read that instead.

The research job lives here too, because it is the agent's one long errand that
is not a script: it gathers what TCE already holds about an idea, adds a web
search when one is configured, and says plainly when it is not.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs
from tce.editorial import changes as change_service
from tce.editorial import inbox as inbox_service
from tce.editorial import lineup as lineup_service
from tce.editorial.common import open_session, packet_to_json
from tce.models.editorial import (
    EvidenceMoment,
    EvidenceSource,
    RecordingPacket,
    TopicCandidate,
)
from tce.models.editorial_workspace import (
    ACTORS,
    EditorialChangeOperation,
    EditorialChangeSet,
    IdeaResearch,
    TopicDecision,
    TopicDecisionChange,
    WeeklyLineup,
)
from tce.models.recording_session import RecordingSession

logger = structlog.get_logger()

# Mirrors packets.RECORDING_IN_PROGRESS_STATUSES; imported lazily there to keep
# this module light, so it is restated here and pinned by a test.
TAKE_IN_PROGRESS = ("recording", "finalizing")

BRIEF_LABELS = {
    "topic": "The topic",
    "audience": "Who it is for",
    "big_idea": "The big idea",
    "why_now": "Why now",
    "why_this_is_yours": "Why this is yours",
    "distinctive_perspective": "Your angle",
    "evidence": "The evidence",
    "claims_to_avoid": "Claims to avoid",
    "takeaway": "The takeaway",
    "cta": "The call to action",
}

PACKET_LABELS = {
    "facebook_post": "The Facebook post",
    "linkedin_post": "The LinkedIn post",
    "interviewer_prompt": "The interviewer prompt",
    "selected_hook_id": "The chosen opening",
}


class VoiceError(Exception):
    """Something the agent asked for cannot be done. Carries the spoken reason."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def check_actor(by: str | None) -> str:
    actor = by or "ziv"
    if actor not in ACTORS:
        raise VoiceError("bad_actor", f"unknown actor {actor}", status=400)
    return actor


def _clip(text: Any, limit: int = 140) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _same(a: Any, b: Any) -> bool:
    """Compare two texts the way a listener would: spacing and case do not count."""
    norm = lambda v: " ".join(str(v or "").split()).casefold()  # noqa: E731
    return norm(a) == norm(b)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def field_label(target_type: str, field: str | None) -> str:
    """ "bullets.2" -> "Point 3". The words he would use for the part that changed."""
    path = field or ""
    if target_type == "candidate_brief":
        return BRIEF_LABELS.get(path, path.replace("_", " "))
    name, _, index = path.partition(".")
    if name in ("bullets", "script_phrases") and index.isdigit():
        n = int(index)
        if name == "bullets":
            return f"Point {n + 1}"
        return "The opening line" if n == 0 else f"Script line {n + 1}"
    if name == "bullets":
        return "The points"
    if name == "script_phrases":
        return "The script"
    return PACKET_LABELS.get(path, path.replace("_", " "))


def describe_operation(target_type: str, op: dict[str, Any], titles: dict[str, str]) -> str:
    """One plain sentence for one applied operation."""
    kind = op.get("op")
    if kind in ("set_field", "replace_text"):
        label = field_label(target_type, op.get("field"))
        before = op.get("before")
        after = op.get("after")
        if before in (None, ""):
            return f'{label} now says "{_clip(after)}" (it was empty).'
        return f'{label} now says "{_clip(after)}" (it said "{_clip(before)}").'
    if kind == "choose_hook":
        return "A different opening was chosen."
    if kind == "move_topic":
        move = op.get("after") or {}
        title = titles.get(str(move.get("candidate_id")), "A topic")
        action = move.get("action") or "rank"
        return {
            "first": f"{title} moved to first in the week.",
            "up": f"{title} moved up one place in the week.",
            "down": f"{title} moved down one place in the week.",
            "remove": f"{title} was taken out of the week.",
            "slot": f"{title} moved to the {move.get('slot', 'other')} list.",
        }.get(action, f"{title} moved to place {move.get('rank')} in the week.")
    if kind == "reorder_week":
        return "The week went back to its earlier order."
    if kind == "restore_version":
        return "An earlier wording was restored."
    return f"{kind} was applied."


# ---------------------------------------------------------------------------
# Finding a topic by what he calls it
# ---------------------------------------------------------------------------

_ID_LIKE = re.compile(r"^[0-9a-f-]{4,36}$")


# Hebrew final letters are the same letter at the end of a word; compared as
# written, "משפך" and "משפכים" share no stem.
_HEBREW_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_HEBREW = re.compile(r"[\u0590-\u05ff]")
# One letter a Hebrew word can carry in front of it: the, in, to, and, that, from,
# as. "המשפך" is "the funnel"; compared whole it never matched "משפך" in a title.
_HEBREW_PREFIXES = "הבלושמכ"


def _norm(word: str) -> str:
    return word.casefold().translate(_HEBREW_FINALS)


def _bare(word: str) -> str:
    """The word without one Hebrew prefix letter, or the word itself."""
    if len(word) >= 3 and word[0] in _HEBREW_PREFIXES and _HEBREW.match(word):
        return word[1:]
    return word


def _variants(word: str) -> set[str]:
    """Every form of one word that counts as the same word when matching a title:
    as said, without one Hebrew prefix letter, and without a plural ending."""
    forms = {word, _bare(word)}
    for form in list(forms):
        if _HEBREW.match(form):
            if len(form) >= 5 and form.endswith(("ימ", "ות")):
                forms.add(form[:-2])
        elif len(form) >= 5 and form.endswith("s") and not form.endswith("ss"):
            forms.add(form[:-1])
    return forms


# Words that name no topic. "The one about the funnel" is one word of content;
# counted in, "the", "one" and "about" out-voted it and sent the edit to "The one
# thing I would never automate". So are the words titles are built from ("what
# nobody tells you about", "the one thing I would never"): counted in, "that thing
# I would never do with the funnel" landed on "The one thing I would never
# automate", and a misheard content word left only filler, which matched any title
# with a "the" in it.
FILLER = frozenset(
    _norm(w)
    for w in (
        # English: function words
        "the a an one ones about of to and or on in for with that this these those it its "
        "is are was were be been being my your our his her their me we you he she they i "
        "im ive id don dont isn aren wasn won from at by as so do does did doing done can "
        "could would should will just like if then than there here too very really "
        "actually also even still only all any some most more much many no not "
        # English: what he says while naming it, and the words titles are made of
        "thing things something nothing never ever always every everyone everybody "
        "anyone anybody someone somebody nobody what whats why how when where who which "
        "tell tells telling told say says said talk talked talking mention mentioned "
        "know knows need needs want wants get gets got make makes made way ways "
        "stop truth secret secrets mistake mistakes lesson lessons reason reasons "
        "them us him discuss discussed started just "
        # English: where it sits and when it was ("the first one", "the one from
        # last week"). They point at a place in a list, never at a title.
        "first second third fourth fifth last next previous before after earlier "
        "latest newest oldest recent other another same current top bottom new old good great "
        "week weeks today yesterday tomorrow ago two three four five"
    ).split()
    + (
        # Hebrew: function words, and "one", "thing", "never", "why", "how"
        "של על את זה זו זאת לא מה עם גם או כמו אני אתה את הוא היא אנחנו הם הן יש אין "
        "הזה הזאת הזו אחד אחת דבר דברים אף אף פעם פעם לעולם כל רק הכי למה איך מתי איפה "
        "מי אם כי אבל שלי שלך שלו שלה שלנו לי לך לו לה לנו לכם אומר אומרים אמר "
        # Hebrew: how he talks about it, as the English above ("the one we talked
        # about", "what I would never do", "what nobody tells you")
        "הייתי היית היה הייתה היו עושה עושים עשיתי עשינו לעשות דיברנו דיברתי דיברת "
        "מדבר מדברים אמרתי אמרנו אמרת עליו עליה עליהם עליהן עלינו עליך מספר מספרים "
        "סיפרתי רוצה צריך יודע תמיד כבר עוד "
        # Hebrew: where it sits and when it was
        "ראשון ראשונה שני שנייה שלישי אחרון אחרונה בא באה קודם קודמת לפני אחרי אחר "
        "אחרת עבר שעבר שעברה שבוע שבועות היום אתמול מחר עכשיו חדש חדשה ישן טוב"
    ).split()
)
# Words about the thing rather than its name ("the topic about pricing"). They
# count only when they are all he said, so "the topic" can still find "A topic".
META = frozenset(
    _norm(w)
    for w in (
        "topic topics idea ideas video videos script scripts post posts called named titled "
        "clip clips reel reels episode רעיון רעיונות נושא סרטון תסריט"
    ).split()
)


def _tokens(text: str) -> list[str]:
    # \w is Unicode-aware, so a Hebrew title is matched on its own words rather
    # than normalised away to nothing.
    return [_norm(t) for t in re.findall(r"\w+", text or "") if len(t) >= 2]


def _is(word: str, words: frozenset[str]) -> bool:
    return word in words or _bare(word) in words


def _content(words: list[str]) -> list[str]:
    """The words that can name a topic, each once, in the order he said them."""
    out: list[str] = []
    for w in words:
        if not _is(w, FILLER) and not _is(w, META) and w not in out:
            out.append(w)
    if not out:
        out = [w for w in dict.fromkeys(words) if not _is(w, FILLER)]
    return out


def _exact(word: str) -> set[str]:
    """The word as said, and without "the" (ה) in front: the same word, exactly."""
    forms = {word}
    if len(word) >= 3 and word[0] == "ה" and _HEBREW.match(word):
        forms.add(word[1:])
    return forms


# What a word counts for when it matches only once a prefix letter or a plural
# ending is stripped. Stripping turns real words into other words ("הספר", the
# book, is "מספר", tells, without its first letter; "מחשבות", thoughts, is
# "מחשב", computer, without its ending), so such a match is a hint to offer
# back, never enough on its own to pick a title.
STRIPPED = 0.5


def _match(needle: str, title: str) -> tuple[float, int]:
    """(how well his words name this title, how many of his content words are in it).

    The score is 0.0 when no word that means anything matches, 1.0 when every
    content word he said is in the title as he said it (or with "the" in front),
    and above 1.0 when he said a run of the title's words in order. A word found
    only once a letter is stripped counts STRIPPED, so it cannot reach 1.0 alone.
    Filler never counts for or against. A run made only of filler (three words
    or more, "what nobody tells you") may point at a title, with 0 content words,
    so it is offered back and never picked.
    """
    words = _tokens(needle)
    content = _content(words)
    title_words = _tokens(title)
    # A run of his words in the title, on whole-word boundaries ("the fun" is not
    # in "the funnel"), is the strongest sign. Filler may be part of the run.
    haystack = f" {' '.join(title_words)} "
    phrase = " ".join(words)
    run = bool(words) and f" {phrase} " in haystack
    run_score = 1.0 + min(len(phrase) / max(len(haystack.strip()), 1), 1.0) * 0.5
    if not content:
        return (run_score, 0) if run and len(words) >= 3 else (0.0, 0)
    exact: set[str] = set()
    have: set[str] = set()
    for w in title_words:
        exact |= _exact(w)
        have |= _variants(w)
    weights = [
        1.0 if _exact(w) & exact else STRIPPED if _variants(w) & have else 0.0 for w in content
    ]
    matched = sum(1 for weight in weights if weight > 0)
    if not matched:
        return 0.0, 0
    if run:
        return run_score, matched
    return sum(weights) / len(content), matched


def _score(needle: str, title: str) -> float:
    """How well his words name this title (see _match)."""
    return _match(needle, title)[0]


async def _week_ids(db: AsyncSession, ws: uuid.UUID) -> set[str]:
    lineup = await lineup_service.get_lineup(db, ws, lineup_service.week_start_for(None))
    if lineup is None:
        return set()
    return {str(i.candidate_id) for i in await lineup_service.list_items(db, ws, lineup.id)}


async def find_topics(
    db: AsyncSession, ws: uuid.UUID, query: str, *, strict: bool = False
) -> dict[str, Any]:
    """Resolve an id, a short id or a title fragment to one topic, or say which ones.

    Put-away ideas are included on purpose: "bring back the one about invoices"
    has to find an idea that is no longer in any list.

    `strict` is for the tools that write, which apply at once: a topic is "found"
    only when it is the clear winner. Reading may also take the only title that
    matches more than half of his words.
    """
    q = (query or "").strip()
    if not q:
        raise VoiceError("empty", "say which topic", status=400)
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.origin.notin_(inbox_service.HIDDEN_ORIGINS),
            TopicCandidate.status != "rejected",
        )
    )
    rows = list(result.scalars().all())

    if _ID_LIKE.match(q.lower()):
        hits = [c for c in rows if str(c.id).startswith(q.lower())]
        if len(hits) == 1:
            return {"status": "found", "candidate": hits[0], "candidates": []}

    in_week = await _week_ids(db, ws)
    # (match, named, rank, candidate): `match` is how well the words name it,
    # `named` how many of his content words are in it; `rank` only breaks ties,
    # towards what he is working on and then towards what is still live. Every
    # title that shares one content word with what he said is kept: dropping the
    # weak ones first made the only survivor look like a sure match, while the
    # title he meant (one word of three) was never even offered.
    scored: list[tuple[float, int, float, TopicCandidate]] = []
    for c in rows:
        match, named = _match(q, c.title)
        if match <= 0:
            continue
        rank = match + (0.02 if str(c.id) in in_week else 0.0)
        rank += 0.01 if c.status != "withdrawn" else 0.0
        scored.append((match, named, rank, c))
    scored.sort(key=lambda row: row[2], reverse=True)

    if not scored:
        return {"status": "none", "candidate": None, "candidates": []}
    top, named, _, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    # A topic is "found" only when a word that means something names it and
    # nothing else comes close:
    # - all of his content words are in the title (or a run of them), and no
    #   other title does as well: the clear winner, the only kind a write takes;
    # - for reading only: it is the only title sharing any of his words, and it
    #   has more than half of them.
    # Anything weaker comes back as candidates, and the agent asks which.
    clear = named > 0 and top >= 1.0 and (second < 1.0 or top - second >= 0.34)
    alone = named > 0 and len(scored) == 1 and top > 0.5
    if clear or (alone and not strict):
        return {"status": "found", "candidate": best, "candidates": []}
    return {
        "status": "ambiguous",
        "candidate": None,
        "candidates": [c for _, _, _, c in scored[:5]],
    }


def candidate_brief_json(c: TopicCandidate) -> dict[str, Any]:
    return {
        "candidate_id": str(c.id),
        "short_id": str(c.id)[:8],
        "title": c.title,
        "status": c.status,
    }


# ---------------------------------------------------------------------------
# A write names its topic by id
# ---------------------------------------------------------------------------

# What the brain is told to do instead of naming a topic in words for a write.
FIND_FIRST = "Find the topic with tce_topic, read its title back to him, then pass its id."

# A whole id, or the short id the tools read out (its first 8 characters) or more.
_TOPIC_ID = re.compile(r"^[0-9a-f]{8}[0-9a-f-]{0,28}$")


def _id_text(raw: Any) -> str:
    """ "id 1a2b3c4d", "(1a2b3c4d)" -> "1a2b3c4d": the id as the brain may pass it."""
    text = str(raw or "").strip().lower()
    text = re.sub(r"^(?:short\s+)?id[\s:]+", "", text)
    return text.strip(" ()[]\"'.")


async def topic_by_id(db: AsyncSession, ws: uuid.UUID, raw: Any) -> TopicCandidate:
    """The one topic an id or a short id names. Words are refused, never matched.

    Every voice write applies at once, so it may only land on a topic whose title
    was read back to him: the brain finds it with words through tce_topic (which
    offers candidates when the words are not a clear winner), reads the title,
    and then writes by the id that came with it. A filler or position word ("the
    first one") can therefore at worst make a read offer candidates; it can never
    steer a write.
    """
    text = _id_text(raw)
    if not text:
        raise VoiceError(
            "id_required", f"No topic id was given. {FIND_FIRST} Nothing was changed.", status=400
        )
    if not _TOPIC_ID.match(text):
        raise VoiceError(
            "id_required",
            f'"{_clip(raw, 60)}" is not a topic id: a change names its topic by id, never by '
            f"words. {FIND_FIRST} Nothing was changed.",
            status=400,
        )
    try:
        whole: uuid.UUID | None = uuid.UUID(text)
    except ValueError:
        whole = None
    if whole is not None:
        row = (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws, TopicCandidate.id == whole
                )
            )
        ).scalar_one_or_none()
        hits = [row] if row is not None else []
    else:
        rows = (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.origin.notin_(inbox_service.HIDDEN_ORIGINS),
                    TopicCandidate.status != "rejected",
                )
            )
        ).scalars()
        hits = [c for c in rows if str(c.id).startswith(text)]
    if not hits:
        raise VoiceError(
            "unknown_topic",
            f'No topic has the id "{text}". {FIND_FIRST} Nothing was changed.',
            status=404,
        )
    if len(hits) > 1:
        raise VoiceError(
            "ambiguous_id",
            f'More than one topic has an id starting "{text}". Use its whole id. '
            "Nothing was changed.",
            status=409,
            candidates=[candidate_brief_json(c) for c in hits[:5]],
        )
    return hits[0]


# ---------------------------------------------------------------------------
# Reading one topic
# ---------------------------------------------------------------------------


async def current_packet(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> RecordingPacket | None:
    result = await db.execute(
        select(RecordingPacket)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id == candidate_id,
        )
        .order_by(RecordingPacket.version.desc())
    )
    return next((p for p in result.scalars().all() if p.status != "superseded"), None)


async def take_in_progress(db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID) -> int | None:
    row = (
        await db.execute(
            select(RecordingSession.packet_version).where(
                RecordingSession.workspace_id == ws,
                RecordingSession.candidate_id == candidate_id,
                RecordingSession.status.in_(TAKE_IN_PROGRESS),
            )
        )
    ).first()
    return None if row is None else int(row[0] or 0)


def script_json(packet: RecordingPacket | None) -> dict[str, Any] | None:
    if packet is None:
        return None
    data = packet_to_json(packet)
    hooks = []
    for n, h in enumerate(data["hook_options"], start=1):
        hooks.append(
            {
                "n": n,
                "id": h.get("id"),
                "text": h.get("text"),
                "chosen": h.get("id") == data["selected_hook_id"],
            }
        )
    phrases = data["script_phrases"]
    return {
        "packet_id": data["id"],
        "version": data["version"],
        "status": data["status"],
        "opening": phrases[0] if phrases else None,
        "points": data["bullets"],
        "script_phrases": phrases,
        "hooks": hooks,
        "google_doc_url": data["google_doc_url"],
    }


async def latest_research(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> IdeaResearch | None:
    result = await db.execute(
        select(IdeaResearch)
        .where(IdeaResearch.workspace_id == ws, IdeaResearch.candidate_id == candidate_id)
        .order_by(IdeaResearch.created_at.desc())
    )
    return result.scalars().first()


async def topic_detail(
    db: AsyncSession, ws: uuid.UUID, candidate: TopicCandidate
) -> dict[str, Any]:
    brief = await briefs.ensure_brief(db, ws, candidate)
    decision = await inbox_service.get_decision(db, ws, candidate.id)
    packet = await current_packet(db, ws, candidate.id)
    research = await latest_research(db, ws, candidate.id)
    in_week = str(candidate.id) in await _week_ids(db, ws)
    return {
        **candidate_brief_json(candidate),
        "decision": decision.decision if decision else None,
        "in_this_week": in_week,
        "put_away": candidate.status == "withdrawn",
        "brief": {
            "version": brief.version,
            "values": dict(brief.brief or {}),
            "labels": BRIEF_LABELS,
        },
        "script": script_json(packet),
        "research": research_to_json(research) if research else None,
    }


# ---------------------------------------------------------------------------
# Changing: propose and apply in one step
# ---------------------------------------------------------------------------


def _resolve_hook(packet: RecordingPacket, wanted: Any) -> dict[str, Any]:
    options = list(packet.hook_options or [])
    if not options:
        raise VoiceError(
            "no_hooks", "this script has no opening options to choose from", status=409
        )
    text = str(wanted or "").strip()
    if text.isdigit():
        n = int(text)
        if 1 <= n <= len(options):
            return options[n - 1]
    found = next((o for o in options if str(o.get("id")) == text), None)
    if found is None:
        raise VoiceError(
            "unknown_hook",
            f"there is no opening {text}; this script has {len(options)} options",
            status=404,
        )
    return found


def _script_being_written(ws: uuid.UUID, candidate_id: uuid.UUID) -> bool:
    from tce.editorial import status as job_status

    return job_status.is_running(ws, "packet", str(candidate_id))


def _refuse_while_writing(ws: uuid.UUID, candidate: TopicCandidate) -> None:
    """A change to a script a rewrite is about to replace would be replaced with it."""
    if _script_being_written(ws, candidate.id):
        raise VoiceError(
            "still_writing",
            f'A new script for "{candidate.title}" is being written right now. When it is '
            "ready it replaces the current one, so a change made now would be replaced with "
            "it. Nothing was written. Wait until it is finished (tce_jobs says when), then "
            "change the new one.",
            status=409,
        )


async def _fresh(
    db: AsyncSession, ws: uuid.UUID, target_type: str, target_id: uuid.UUID, fields: list[str]
) -> dict[str, Any]:
    """The current text of the fields a failed change was about."""
    try:
        state = await change_service.load_target(db, ws, target_type, target_id)
    except change_service.ChangeError:
        return {}
    out: dict[str, Any] = {"version": state.version}
    for f in fields:
        _, value = change_service._resolve_path(state.values, f)
        out[f] = value
    return out


async def apply_change(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    candidate_id: uuid.UUID,
    target: str,
    operations: list[dict[str, Any]],
    summary: str,
    by: str = "voice",
) -> dict[str, Any]:
    """Propose and apply at once, attributed to the caller.

    `target` is what he talks about: "brief", "script" or "week". Each operation
    is {op, field, after, expect}. `expect` is the text the agent read back as
    the current one; if the stored text is different by now, nothing is written.

    The read-back is not optional. Replacing text that exists without saying
    what was read is refused with the text as it is now, because the version the
    brain read may be minutes old (a script rewritten in the background, a tap on
    the phone). For choose_hook, `expect` is the opening he heard, and it is
    required: the options are renumbered when a script is rewritten, so "option
    2" alone can name a text he never heard.

    While a new script for the topic is being written, the script is not
    changed at all: the new one would replace the change a few minutes later.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    if not operations:
        raise VoiceError("empty", "no change was asked for", status=400)

    ops_in: list[change_service.OperationInput] = []
    expectations: list[tuple[str, Any]] = []

    if target == "brief":
        target_type, target_id = "candidate_brief", candidate.id
    elif target == "script":
        packet = await current_packet(db, ws, candidate.id)
        if packet is None:
            raise VoiceError(
                "no_script",
                f'"{candidate.title}" has no script yet. Ask for one first.',
                status=404,
            )
        taking = await take_in_progress(db, ws, candidate.id)
        if taking is not None:
            raise VoiceError(
                "recording",
                "A take is being recorded on this script right now, so it stays as it is "
                "until that recording is finished.",
                status=409,
            )
        _refuse_while_writing(ws, candidate)
        target_type, target_id = "packet", packet.id
    elif target == "week":
        lineup = await lineup_service.ensure_lineup(db, ws, lineup_service.week_start_for(None))
        target_type, target_id = "lineup", lineup.id
    else:
        raise VoiceError("bad_target", f"unknown target {target}", status=400)

    for raw in operations:
        op = str(raw.get("op") or "set_field")
        if op == "choose_hook":
            if target_type != "packet":
                raise VoiceError("bad_target", "an opening belongs to the script", status=400)
            hook = _resolve_hook(packet, raw.get("after"))
            heard = raw.get("expect")
            options_now = [
                {"n": n, "text": o.get("text")}
                for n, o in enumerate(packet.hook_options or [], start=1)
            ]
            if heard is None or not str(heard).strip():
                raise VoiceError(
                    "expect_required",
                    "The choice did not say which opening you read him, so it could be one "
                    "he never heard. Nothing was written. Read him the options as they are "
                    "now and send the text of the one he picks.",
                    status=409,
                    current=options_now,
                    version=packet.version,
                )
            if not _same(hook.get("text"), heard):
                raise VoiceError(
                    "changed",
                    "The opening options changed since you read them. Nothing was written. "
                    "Read him the options as they are now.",
                    status=409,
                    current=options_now,
                    version=packet.version,
                )
            ops_in.append(change_service.OperationInput(op="choose_hook", after=str(hook["id"])))
            phrases = list(packet.script_phrases or [])
            hook_text = str(hook.get("text") or "").strip()
            if phrases and hook_text and phrases[0] != hook_text:
                ops_in.append(
                    change_service.OperationInput(
                        op="set_field", field="script_phrases.0", after=hook_text
                    )
                )
            continue
        if op == "move_topic":
            move = dict(raw.get("after") or {})
            move.setdefault("candidate_id", str(candidate.id))
            ops_in.append(change_service.OperationInput(op="move_topic", after=move))
            continue
        field = str(raw.get("field") or "")
        ops_in.append(change_service.OperationInput(op=op, field=field, after=raw.get("after")))
        if raw.get("expect") is not None or op in ("set_field", "replace_text"):
            expectations.append((field, raw.get("expect")))

    state = await change_service.load_target(db, ws, target_type, target_id)
    for field, expected in expectations:
        exists, value = change_service._resolve_path(state.values, field)
        if expected is None:
            if exists and str(value or "").strip():
                raise VoiceError(
                    "expect_required",
                    f"{field_label(target_type, field)} already says something, and the "
                    "change did not say what you read him. Nothing was written.",
                    status=409,
                    field=field,
                    current=value,
                    version=state.version,
                )
            continue
        if exists and not _same(value, expected):
            raise VoiceError(
                "changed",
                f"{field_label(target_type, field)} was changed since you read it. "
                "Nothing was written.",
                status=409,
                field=field,
                current=value,
                version=state.version,
            )

    change_set = await change_service.propose(
        db,
        ws,
        target_type=target_type,
        target_id=target_id,
        base_version=state.version,
        operations=ops_in,
        summary=summary or "Changed by voice",
        origin="voice",
    )
    issues = (change_set.validation or {}).get("issues") or []
    if change_set.state == "invalid":
        blocking = next(
            (i for i in issues if i["code"] in ("unknown_op", "unknown_field", "bad_value")),
            issues[0] if issues else {"message": "that cannot be changed"},
        )
        raise VoiceError("invalid", blocking["message"], status=400)

    try:
        result = await change_service.apply(db, ws, change_set.id, decided_by=actor)
    except (change_service.ChangeError, lineup_service.LineupError) as error:
        if change_set.state == "proposed":
            # It failed while applying (a topic not in the week, a recorded one),
            # not on a version conflict, which already marked it superseded. Close
            # it, or it waits forever as a change "for a yes or no" that nobody
            # asked for. reject() also resets the operations apply() had marked.
            await change_service.reject(db, ws, change_set.id, decided_by=actor)
        fresh = await _fresh(db, ws, target_type, target_id, [o.field for o in ops_in if o.field])
        raise VoiceError(error.code, error.message, status=error.status, current=fresh) from error

    ops = await change_service.load_operations(db, ws, change_set.id)
    titles = {str(candidate.id): candidate.title}
    rendered = [change_service.operation_to_json(o) for o in ops]
    return {
        "change_set_id": str(change_set.id),
        "short_id": str(change_set.id)[:8],
        "target_type": target_type,
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "version": result["version"],
        "said": [describe_operation(target_type, o, titles) for o in rendered],
        "changes": [
            {
                "field": o["field"],
                "label": field_label(target_type, o["field"]) if o["field"] else o["op"],
                "before": o["before"],
                "after": o["after"],
            }
            for o in rendered
        ],
        # Not blocking, but worth saying out loud before he records it.
        "warnings": [i["message"] for i in issues if i["code"] == "safety"],
    }


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def _undo_key(change_set_id: uuid.UUID) -> str:
    return f"undo:{change_set_id}"


async def _undone_by(
    db: AsyncSession, ws: uuid.UUID, change_set_ids: list[uuid.UUID]
) -> dict[str, str]:
    """{original change set id: the applied change set that undid it}."""
    if not change_set_ids:
        return {}
    keys = {_undo_key(i) for i in change_set_ids}
    result = await db.execute(
        select(EditorialChangeSet).where(
            EditorialChangeSet.workspace_id == ws,
            EditorialChangeSet.state == "applied",
            EditorialChangeSet.idempotency_key.like("undo:%"),
        )
    )
    out: dict[str, str] = {}
    for row in result.scalars().all():
        base = ":".join((row.idempotency_key or "").split(":")[:2])
        if base in keys:
            out[base.removeprefix("undo:")] = str(row.id)
    return out


async def _packet_for_change(
    db: AsyncSession, ws: uuid.UUID, change_set: EditorialChangeSet
) -> RecordingPacket:
    row = (
        await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id == change_set.target_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise VoiceError("not_found", "that script is no longer here", status=404)
    return row


async def _check_week_is_back(
    db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID, before_order: list[Any]
) -> None:
    """Say "Undone" only when every topic of the earlier order is in the week again.

    A topic taken out and then put away or rejected is not brought back into the
    week behind his back; the undo is refused instead, and the caller rolls back.
    """
    now = await change_service.load_target(db, ws, "lineup", lineup_id)
    present = {str(e.get("candidate_id")) for e in now.values.get("order") or []}
    missing = [
        str(e.get("candidate_id"))
        for e in before_order
        if isinstance(e, dict) and str(e.get("candidate_id")) not in present
    ]
    if not missing:
        return
    ids: list[uuid.UUID] = []
    for value in missing:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    titles = {
        str(c.id): c.title
        for c in (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    }
    named = ", ".join(f'"{titles.get(m, "a topic")}"' for m in missing)
    raise VoiceError(
        "not_restored",
        f"{named} cannot go back in the week, because it was put away or dropped since. "
        "Nothing was written.",
        status=409,
        missing=missing,
    )


async def undo_change_set(
    db: AsyncSession, ws: uuid.UUID, change_set_id: uuid.UUID, *, by: str = "voice"
) -> dict[str, Any]:
    """Write the inverse of an applied change set as a new, applied change set.

    Refuses rather than overwrites: if the part it changed has been changed again
    since, the current text comes back and nothing is written.
    """
    actor = check_actor(by)
    try:
        original = await change_service.get_change_set(db, ws, change_set_id)
    except change_service.ChangeError as error:
        raise VoiceError(error.code, error.message, status=error.status) from error
    if original.state != "applied":
        raise VoiceError(
            "not_applied",
            f"That change was never applied (it is {original.state}), so there is nothing to undo.",
            status=409,
        )
    already = (await _undone_by(db, ws, [original.id])).get(str(original.id))
    if already:
        return {
            "change_set_id": already,
            "undid": str(original.id),
            "already": True,
            "said": f'"{original.summary}" was already undone.',
        }

    ops = [
        o for o in await change_service.load_operations(db, ws, original.id) if o.state == "applied"
    ]
    if not ops:
        raise VoiceError("empty", "that change has nothing to undo", status=409)

    inverse: list[change_service.OperationInput] = []
    target_type = original.target_type
    changed_since = lambda label, now: VoiceError(  # noqa: E731
        "changed",
        f"{label} was changed again after that, so undoing it would lose the newer "
        "change. Nothing was written.",
        status=409,
        current=now,
    )

    if target_type == "candidate_brief":
        target_id = original.target_id
        state = await change_service.load_target(db, ws, target_type, target_id)
        values = dict(state.values)
        for op in ops:
            before = (op.before or {}).get("value")
            after = (op.after or {}).get("value")
            if op.op in ("set_field", "replace_text"):
                if not _same(values.get(op.field or ""), after):
                    raise changed_since(
                        field_label(target_type, op.field), values.get(op.field or "")
                    )
                if before is None:
                    values.pop(op.field or "", None)
                else:
                    values[op.field or ""] = before
            elif op.op == "restore_version":
                if state.version != original.applied_version:
                    raise changed_since("The brief", state.values)
                earlier = await briefs.get_version(db, ws, target_id, original.base_version)
                values = dict(earlier.brief or {}) if earlier else values
        inverse.append(
            change_service.OperationInput(
                op="restore_version", after=values, rationale="Undo a change made by voice."
            )
        )
    elif target_type == "packet":
        applied_packet = await _packet_for_change(db, ws, original)
        packet = await current_packet(db, ws, applied_packet.candidate_id)
        if packet is None:
            raise VoiceError("not_found", "that script is no longer here", status=404)
        if await take_in_progress(db, ws, packet.candidate_id) is not None:
            raise VoiceError(
                "recording",
                "A take is being recorded on this script right now, so it cannot change until "
                "that recording is finished.",
                status=409,
            )
        _refuse_while_writing(ws, await inbox_service.get_candidate(db, ws, packet.candidate_id))
        target_id = packet.id
        state = await change_service.load_target(db, ws, target_type, target_id)
        for op in ops:
            before = (op.before or {}).get("value")
            after = (op.after or {}).get("value")
            if op.op in ("set_field", "replace_text"):
                exists, now = change_service._resolve_path(state.values, op.field or "")
                if not exists or not _same(now, after):
                    raise changed_since(field_label(target_type, op.field), now)
                inverse.append(
                    change_service.OperationInput(
                        op="set_field", field=op.field, after="" if before is None else before
                    )
                )
            elif op.op == "choose_hook":
                if state.values.get("selected_hook_id") != after:
                    raise changed_since("The chosen opening", state.values.get("selected_hook_id"))
                if before:
                    inverse.append(change_service.OperationInput(op="choose_hook", after=before))
            elif op.op == "restore_version":
                # A script put back (restore_script_version) or a rewrite: undoing
                # it puts back the script it replaced, if nothing was changed on
                # top since. The openings count: they are part of what comes back,
                # and more openings asked for after it would be dropped.
                now_script = _script_values(packet)
                if not isinstance(after, dict) or not _same_text(now_script, after):
                    raise changed_since("The script", state.values.get("bullets"))
                if not _same_hooks(now_script, after):
                    raise VoiceError(
                        "changed",
                        "Opening options were added or changed after that, so putting the "
                        "earlier script back would drop them. Nothing was written.",
                        status=409,
                        current=[
                            {"n": n, "text": h.get("text")}
                            for n, h in enumerate(now_script["hook_options"], start=1)
                        ],
                    )
                if not isinstance(before, dict):
                    raise VoiceError(
                        "no_before",
                        "the script before that was not recorded, so it cannot be undone",
                        status=409,
                    )
                inverse.append(
                    change_service.OperationInput(
                        op="restore_version",
                        after=before,
                        rationale="Undo putting an earlier script back.",
                    )
                )
    elif target_type == "lineup":
        target_id = original.target_id
        state = await change_service.load_target(db, ws, target_type, target_id)
        if state.version != original.applied_version:
            raise changed_since("The week", state.values.get("order"))
        before_order = next(
            (
                (o.before or {}).get("value")
                for o in ops
                if isinstance((o.before or {}).get("value"), list)
            ),
            None,
        )
        if before_order is None:
            raise VoiceError(
                "no_before",
                "the order before that move was not recorded, so it cannot be undone",
                status=409,
            )
        inverse.append(change_service.OperationInput(op="reorder_week", after=before_order))
    else:
        raise VoiceError("unsupported", f"cannot undo a {target_type} change", status=400)

    if not inverse:
        raise VoiceError("empty", "there is nothing to put back", status=409)

    undo_set = await change_service.propose(
        db,
        ws,
        target_type=target_type,
        target_id=target_id,
        base_version=state.version,
        operations=inverse,
        summary=f"Undo: {original.summary}",
        rationale=f"Undoes change {str(original.id)[:8]}.",
        origin="undo",
        idempotency_key=f"{_undo_key(original.id)}:{uuid.uuid4().hex[:8]}",
    )
    if target_type == "packet" and any(o.op == "restore_version" for o in inverse):
        await _record_script_before(db, ws, undo_set.id, packet)
    if undo_set.state == "invalid":
        issues = (undo_set.validation or {}).get("issues") or []
        raise VoiceError(
            "invalid", issues[0]["message"] if issues else "that cannot be undone", status=409
        )
    result = await change_service.apply(db, ws, undo_set.id, decided_by=actor)
    if target_type == "lineup":
        await _check_week_is_back(db, ws, target_id, inverse[0].after)
    said = f'Undone: "{original.summary}".'
    if _is_rewrite(original):
        title = (await inbox_service.get_candidate(db, ws, packet.candidate_id)).title
        said = (
            f'The script of "{title}" is back to the one the new script replaced '
            f"(now version {result['version']})."
        )
    return {
        "change_set_id": str(undo_set.id),
        "undid": str(original.id),
        "already": False,
        "version": result["version"],
        "said": said,
    }


# ---------------------------------------------------------------------------
# Putting back a script that a rewrite replaced
# ---------------------------------------------------------------------------

# What a script is, for putting one back: its text and its openings.
SCRIPT_FIELDS = (
    "bullets",
    "script_phrases",
    "facebook_post",
    "linkedin_post",
    "interviewer_prompt",
    "selected_hook_id",
    "beats",
)


def _script_values(packet: RecordingPacket) -> dict[str, Any]:
    return {
        "bullets": list(packet.bullets or []),
        "script_phrases": list(packet.script_phrases or []),
        "facebook_post": packet.facebook_post,
        "linkedin_post": packet.linkedin_post,
        "interviewer_prompt": packet.interviewer_prompt,
        "selected_hook_id": packet.selected_hook_id,
        "beats": list(packet.beats or []) if packet.beats else None,
        # Openings too: the chosen one must exist in the list it is chosen from.
        "hook_options": list(packet.hook_options or []),
    }


def _same_text(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The same script text. The openings are compared apart (see _same_hooks)."""
    return all((a.get(f) or None) == (b.get(f) or None) for f in SCRIPT_FIELDS)


def _hooks_key(hooks: Any) -> list[tuple[str, str]]:
    return [
        (str(h.get("id")), " ".join(str(h.get("text") or "").split()))
        for h in hooks or []
        if isinstance(h, dict)
    ]


def _same_hooks(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The same opening options, ids and text. A record written before openings
    were kept with the script (no `hook_options` key) says nothing about them."""
    if "hook_options" not in a or "hook_options" not in b:
        return True
    return _hooks_key(a["hook_options"]) == _hooks_key(b["hook_options"])


async def _record_script_before(
    db: AsyncSession, ws: uuid.UUID, change_set_id: uuid.UUID, packet: RecordingPacket
) -> None:
    """Keep the whole script a restore replaces on the operation, so it can be undone.

    `propose` records no `before` for restore_version (a brief keeps its versions
    and does not need one); a script put back over another does.
    """
    for op in await change_service.load_operations(db, ws, change_set_id):
        if op.op == "restore_version":
            op.before = {"value": _script_values(packet)}
    await db.flush()


async def restore_script_version(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    version: int,
    *,
    by: str = "voice",
) -> dict[str, Any]:
    """Make an earlier script version current again, as an attributed, undoable change.

    A rewrite (tce_write_script with replace) supersedes the script he had, edits
    included. The old version stays in the database; this is how it comes back.
    It is written as a new version, never by un-superseding the old row, so the
    history stays append-only and the change can be undone by id like any other.
    """
    from tce.editorial import status as job_status

    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    if job_status.is_running(ws, "packet", str(candidate.id)):
        raise VoiceError(
            "still_writing",
            f'The new script for "{candidate.title}" is still being written. When it is '
            "ready it replaces the current one; put the old one back after that.",
            status=409,
        )
    wanted = (
        await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id == candidate.id,
                RecordingPacket.version == version,
            )
        )
    ).scalar_one_or_none()
    if wanted is None:
        raise VoiceError(
            "not_found", f'"{candidate.title}" has no script version {version}.', status=404
        )
    current = await current_packet(db, ws, candidate.id)
    if current is None:
        raise VoiceError("no_script", f'"{candidate.title}" has no script now.', status=404)
    base = {
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "from_version": version,
    }
    if current.version == wanted.version:
        return {
            **base,
            "restored": False,
            "version": current.version,
            "said": f'Version {version} is already the current script of "{candidate.title}".',
        }
    if await take_in_progress(db, ws, candidate.id) is not None:
        raise VoiceError(
            "recording",
            "A take is being recorded on this script right now, so it stays as it is "
            "until that recording is finished.",
            status=409,
        )
    try:
        change_set = await change_service.propose(
            db,
            ws,
            target_type="packet",
            target_id=current.id,
            base_version=current.version,
            operations=[
                change_service.OperationInput(
                    op="restore_version",
                    after=_script_values(wanted),
                    rationale=f"Put back script version {version}.",
                )
            ],
            summary=f'Put back script version {version} of "{candidate.title}"',
            origin="voice" if actor == "voice" else "quick_action",
        )
        await _record_script_before(db, ws, change_set.id, current)
        result = await change_service.apply(db, ws, change_set.id, decided_by=actor)
    except change_service.ChangeError as error:
        raise VoiceError(error.code, error.message, status=error.status) from error
    return {
        **base,
        "restored": True,
        "change_set_id": str(change_set.id),
        "short_id": str(change_set.id)[:8],
        "replaced_version": current.version,
        "version": result["version"],
        "said": (
            f'Script version {version} of "{candidate.title}" is back as the current script '
            f"(now version {result['version']}). Undo takes it back to version {current.version}."
        ),
    }


# ---------------------------------------------------------------------------
# A rewrite, recorded when it is saved
# ---------------------------------------------------------------------------

# The idempotency key of the change set that records a rewrite. Its id is the
# rewrite id the start answered with, so the call can undo it by that id.
REWRITE_KEY = "rewrite:"


def _is_rewrite(change_set: EditorialChangeSet) -> bool:
    return (change_set.idempotency_key or "").startswith(REWRITE_KEY)


async def record_rewrite(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    rewrite_id: uuid.UUID,
    by: str,
    candidate: TopicCandidate,
    replaced: RecordingPacket,
    packet: RecordingPacket,
    job_id: uuid.UUID | None = None,
) -> EditorialChangeSet:
    """Write a rewrite down as an applied change set, in the transaction that saves it.

    `replaced` is the script that was current at SAVE time, not when the rewrite
    was asked for: an edit typed on the phone while it was written is part of
    what it replaced, and undoing the rewrite brings that edited script back,
    from which the edit itself is one more undo. Recording it at the start
    brought back the version from before the edit, and the edit was lost.

    Listed with the voice changes, undoable by its id like any other change (the
    inverse is the whole script it replaced, openings included).
    """
    actor = check_actor(by)
    now = _now()
    change_set = EditorialChangeSet(
        id=rewrite_id,
        workspace_id=ws,
        target_type="packet",
        target_id=packet.id,
        base_version=replaced.version,
        summary=f'New script for "{candidate.title}" (it replaced version {replaced.version})',
        rationale="A new script was written when he asked for one.",
        state="applied",
        validation={"ok": True, "issues": []},
        origin="voice" if actor == "voice" else "quick_action",
        applied_version=packet.version,
        applied_at=now,
        decided_by=actor,
        decided_at=now,
        idempotency_key=f"{REWRITE_KEY}{rewrite_id}",
        job_id=job_id,
        created_at=now,
    )
    db.add(change_set)
    await db.flush()
    db.add(
        EditorialChangeOperation(
            workspace_id=ws,
            change_set_id=change_set.id,
            seq=1,
            op="restore_version",
            field=None,
            before={"value": _script_values(replaced)},
            after={"value": _script_values(packet)},
            rationale="The new script replaced this one.",
            state="applied",
            depends_on=[],
        )
    )
    await db.flush()
    return change_set


async def rewrite_record(
    db: AsyncSession, ws: uuid.UUID, rewrite_id: uuid.UUID
) -> EditorialChangeSet | None:
    """The change set a rewrite was recorded as when it was saved, or None."""
    return (
        await db.execute(
            select(EditorialChangeSet).where(
                EditorialChangeSet.workspace_id == ws,
                EditorialChangeSet.id == rewrite_id,
                EditorialChangeSet.idempotency_key == f"{REWRITE_KEY}{rewrite_id}",
            )
        )
    ).scalar_one_or_none()


async def undo_rewrite(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    rewrite_id: uuid.UUID,
    *,
    replaced_version: int | None = None,
    by: str = "voice",
) -> dict[str, Any]:
    """Put back the script a rewrite replaced, by the id its start answered with.

    `replaced_version` is the version the call was told the rewrite replaces. With
    no record of the rewrite, that is what says whether "the script he had is still
    the current one" is true: a rewrite left waiting and finished after a restart
    is saved without its record, and the script has moved on.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    if _script_being_written(ws, candidate.id):
        raise VoiceError(
            "still_writing",
            f'The new script for "{candidate.title}" is still being written. When it is '
            "ready it replaces the current one; undo it after that.",
            status=409,
        )
    record = await rewrite_record(db, ws, rewrite_id)
    if record is None:
        current = await current_packet(db, ws, candidate.id)
        if (
            current is not None
            and replaced_version is not None
            and (current.version != replaced_version)
        ):
            earlier = (
                await db.execute(
                    select(RecordingPacket.version).where(
                        RecordingPacket.workspace_id == ws,
                        RecordingPacket.candidate_id == candidate.id,
                        RecordingPacket.version < current.version,
                    )
                )
            ).scalars()
            previous = max(earlier, default=None)
            raise VoiceError(
                "replaced_since",
                f'The new script for "{candidate.title}" was not recorded under this change, '
                f"and the script is not the one it was asked over: it is now version "
                f"{current.version}, not version {replaced_version}. It may have been "
                "finished after a restart, or changed since. Nothing was undone. Earlier "
                f"versions are kept: version {previous} is the one just before the current "
                f"script, and version {replaced_version} is the one he had when he asked. "
                "Either can be put back by its number.",
                status=409,
                current_version=current.version,
                previous_version=previous,
                asked_version=replaced_version,
            )
        raise VoiceError(
            "not_saved",
            f'The new script for "{candidate.title}" was never saved (it stopped before it '
            "finished), so the script he had is still the current one. There is nothing "
            "to undo.",
            status=409,
        )
    result = await undo_change_set(db, ws, record.id, by=actor)
    return {**result, "candidate_id": str(candidate.id), "title": candidate.title}


# ---------------------------------------------------------------------------
# Putting an idea away and bringing it back
# ---------------------------------------------------------------------------


# The word the decide route takes, and answers with as `previous_decision`, for
# "no decision". Undoing a first decision is then one more decide call, like
# undoing any other: decide the previous one.
UNDECIDED = "undecided"


async def clear_decision(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> TopicDecision | None:
    """Take a decision back to undecided. The row, and the note on it, stay.

    Deleting the row was how "undecided" used to be written, and it took the
    note he wrote while deciding with it. `previous_decision` keeps what it was.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    row = await inbox_service.get_decision(db, ws, candidate_id)
    if row is not None and row.decision is not None:
        row.previous_decision = row.decision
        row.decision = None
        row.decided_by = actor
        row.decided_at = _now()
    if candidate.status == "withdrawn":
        candidate.status = "proposed"
    await db.flush()
    return row


def _no_decision(value: str | None) -> str | None:
    return None if value in (None, "", UNDECIDED) else value


async def record_decision_change(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    before: str | None,
    after: str | None,
    by: str | None,
    week: dict[str, Any] | None = None,
) -> TopicDecisionChange | None:
    """Write one decision write down under its own id, or nothing when it changed nothing.

    `week` is what lineup.follow_decision answered (or the same shape): whether the
    write put the topic on a week's list or took it off, and which list. "Approve
    it" twice changes nothing the second time, so it leaves no row, and "undo"
    then reaches the approval that did it.
    """
    week = week or {}
    before, after = _no_decision(before), _no_decision(after)
    added = bool(week.get("added"))
    removed = week.get("removed")
    if before == after and not added and not removed:
        return None
    last = (
        await db.execute(
            select(func.max(TopicDecisionChange.seq)).where(
                TopicDecisionChange.workspace_id == ws,
                TopicDecisionChange.candidate_id == candidate_id,
            )
        )
    ).scalar()
    where = {"week_start": week.get("week_start"), "lineup_id": week.get("lineup_id")}
    placed = week.get("placed") or {}
    row = TopicDecisionChange(
        workspace_id=ws,
        candidate_id=candidate_id,
        seq=int(last or 0) + 1,
        before=before,
        after=after,
        decided_by=by,
        decided_at=_now(),
        week={
            "added": {**where, "slot": placed.get("slot"), "rank": placed.get("rank")}
            if added
            else None,
            "removed": {**where, **removed} if removed else None,
        },
    )
    db.add(row)
    await db.flush()
    return row


async def restore_topic(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> dict[str, Any]:
    """Bring a put-away idea back to where it was before it was put away.

    Where it was includes its place in this week's list, when putting it away
    took it off that list. Bringing it back is a decision write of its own, with
    its own change id, so the call can take it back like any other.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    decision = await inbox_service.get_decision(db, ws, candidate_id)
    back_to: str | None = None
    placed: dict[str, Any] | None = None
    change: TopicDecisionChange | None = None
    if decision is not None and decision.decision == "away":
        previous = decision.previous_decision
        if previous and previous != "away":
            decision = await inbox_service.decide(
                db, ws, candidate_id, decision=previous, decided_by=actor
            )
            back_to = previous
        else:
            # It was never decided before it went away: back to undecided,
            # keeping the row and the note on it.
            decision = await clear_decision(db, ws, candidate_id, by=actor)
        week = await lineup_service.follow_decision(db, ws, candidate, decision, by=actor)
        placed = week["placed"]
        change = await record_decision_change(
            db,
            ws,
            candidate.id,
            before="away",
            after=decision.decision if decision is not None else None,
            by=actor,
            week=week,
        )
    elif candidate.status != "withdrawn":
        return {
            "candidate_id": str(candidate.id),
            "title": candidate.title,
            "restored": False,
            "change_id": None,
            "said": f'"{candidate.title}" is not put away.',
        }
    if candidate.status == "withdrawn":
        candidate.status = "proposed"
    await db.flush()
    in_week = "back in this week's list"
    if placed is not None:
        in_week += ", in reserve" if placed["slot"] == "reserve" else f", place {placed['rank']}"
    where = {
        "this_week": in_week,
        "discuss": "back, marked to think about",
        "later": "back in saved for later",
    }.get(back_to or "", "back with the ideas waiting for a decision")
    return {
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "restored": True,
        "decision": back_to,
        "placed": placed,
        "change_id": str(change.id) if change is not None else None,
        "said": f'"{candidate.title}" is {where}.',
    }


_DECISION_WORDS = {
    "this_week": "chosen for this week",
    "discuss": "marked to think about",
    "later": "saved for later",
    "away": "put away",
    UNDECIDED: "waiting for a decision",
}


def _decision_words(value: str | None) -> str:
    return _DECISION_WORDS.get(value or UNDECIDED, value or UNDECIDED)


def _list_words(week_start: str | None) -> str:
    """ "this week's list", or the list of the week it was, named."""
    current = lineup_service.week_start_for(None).date().isoformat()
    if not week_start or week_start[:10] == current:
        return "this week's list"
    day = datetime.fromisoformat(week_start[:10])
    return f"the list for the week of {day.day} {day:%B}"


async def _lineup_of(db: AsyncSession, ws: uuid.UUID, where: dict[str, Any]) -> WeeklyLineup | None:
    """The week's list a decision write touched: by its id, else by its week."""
    try:
        lineup_id = uuid.UUID(str(where.get("lineup_id")))
    except ValueError:
        lineup_id = None
    if lineup_id is not None:
        row = (
            await db.execute(
                select(WeeklyLineup).where(
                    WeeklyLineup.workspace_id == ws, WeeklyLineup.id == lineup_id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    if where.get("week_start"):
        return await lineup_service.get_lineup(
            db, ws, lineup_service.week_start_for(str(where["week_start"])[:10])
        )
    return None


async def undo_decision(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    change_id: Any,
    by: str = "voice",
) -> dict[str, Any]:
    """Take one decision write back, by its own change id, and the week with it.

    What the write replaced and what it did to a week's list are on its row, so
    the undo needs nothing else: an approval that put the topic on a list comes
    off THAT list, in whichever week it was (an approval on Sunday night, undone
    after the Monday rollover, is still on the old week's list).

    Refused, with nothing changed, when anyone decided again after it and that
    decision still stands: it compares the history, not only the value, so a
    voice approval that he later changed on the phone and then chose again
    himself is his decision now, and the reply says so.
    """
    actor = check_actor(by)
    if change_id in (None, ""):
        raise VoiceError(
            "change_id_required",
            "The undo did not say which decision to take back (its change id). "
            "Nothing was changed.",
            status=400,
        )
    try:
        wanted = uuid.UUID(str(change_id))
    except ValueError:
        wanted = None
    entry = None
    if wanted is not None:
        entry = (
            await db.execute(
                select(TopicDecisionChange).where(
                    TopicDecisionChange.workspace_id == ws,
                    TopicDecisionChange.id == wanted,
                    TopicDecisionChange.candidate_id == candidate_id,
                )
            )
        ).scalar_one_or_none()
    if entry is None:
        raise VoiceError(
            "unknown_change",
            f"There is no decision change {str(change_id)[:8]} on that topic, so there is "
            "nothing to take back. Nothing was changed.",
            status=404,
        )
    candidate = await inbox_service.get_candidate(db, ws, entry.candidate_id)
    title = candidate.title
    base = {"candidate_id": str(candidate.id), "title": title, "change_id": str(entry.id)}
    if entry.undone_at is not None:
        return {
            **base,
            "already": True,
            "said": f'That decision on "{title}" was already taken back. Nothing more to undo.',
        }

    later = list(
        (
            await db.execute(
                select(TopicDecisionChange)
                .where(
                    TopicDecisionChange.workspace_id == ws,
                    TopicDecisionChange.candidate_id == candidate.id,
                    TopicDecisionChange.seq > entry.seq,
                    TopicDecisionChange.undone_at.is_(None),
                )
                .order_by(TopicDecisionChange.seq)
            )
        ).scalars()
    )
    row = await inbox_service.get_decision(db, ws, candidate.id)
    now = row.decision if row is not None else None
    if later or now != entry.after:
        his = [c for c in later if c.decided_by != "voice"]
        newest = later[-1] if later else None
        if his:
            message = (
                f'"{title}" was changed after that by Ziv himself (it is now '
                f"{_decision_words(now)}), so taking the call's decision back would undo "
                "his. Nothing was changed."
            )
        elif newest is not None:
            message = (
                f'"{title}" was decided again after that in the call (it is now '
                f"{_decision_words(now)}; change {str(newest.id)[:8]}). Undo that one first "
                "to go further back. Nothing was changed."
            )
        else:
            message = (
                f'"{title}" was changed since (it is now {_decision_words(now)}), so taking '
                "that decision back would lose the newer one. Nothing was changed."
            )
        raise VoiceError(
            "changed",
            message,
            status=409,
            decision_now=now or UNDECIDED,
            later_change_id=str(newest.id) if newest is not None else None,
            changed_by=(his[-1] if his else newest).decided_by if later else None,
        )

    back = entry.before
    if back is None:
        row = await clear_decision(db, ws, candidate.id, by=actor)
    else:
        row = await inbox_service.decide(db, ws, candidate.id, decision=back, decided_by=actor)

    week = entry.week or {}
    off: dict[str, Any] | None = None
    placed: dict[str, Any] | None = None
    if week.get("added"):
        # Only the place this write gave it, in the week it gave it; a place it
        # had anywhere before stays whatever it was.
        lineup = await _lineup_of(db, ws, week["added"])
        items = await lineup_service.list_items(db, ws, lineup.id) if lineup else []
        item = next((i for i in items if i.candidate_id == candidate.id), None)
        if lineup is not None and item is not None:
            off = {
                "week_start": lineup.week_start.date().isoformat(),
                "slot": item.slot,
                "rank": item.rank,
            }
            await lineup_service.remove_topic(db, ws, lineup, candidate.id, removed_by=actor)
    elif back != "this_week" or week.get("removed"):
        # Back to this week puts it back at the place the write took it from;
        # anything else takes it off the list if it is somehow on it.
        moved = await lineup_service.follow_decision(db, ws, candidate, row, by=actor)
        placed = moved["placed"]
        if moved["removed"]:
            off = {"week_start": moved["week_start"], **moved["removed"]}
    entry.undone_at = _now()
    entry.undone_by = actor
    await db.flush()

    if back == "this_week":
        if off:
            said = (
                f'"{title}" is off {_list_words(off["week_start"])} again, as it was before '
                "(still chosen for this week)."
            )
        elif placed:
            said = f'"{title}" is back in this week\'s list, place {placed["rank"]}.'
        else:
            said = f'"{title}" is back where it was (chosen for this week).'
    else:
        said = f'"{title}" is {_decision_words(back)} again' + (
            f", and off {_list_words(off['week_start'])}." if off else "."
        )
    return {
        **base,
        "already": False,
        "decision": row.decision if row is not None else None,
        "removed_from_week": off,
        "placed": placed,
        "said": said,
    }


# ---------------------------------------------------------------------------
# What the voice agent changed
# ---------------------------------------------------------------------------


async def activity(db: AsyncSession, ws: uuid.UUID, *, hours: int = 24) -> dict[str, Any]:
    """Everything the voice agent wrote in the window, newest first, in plain words."""
    since = _now() - timedelta(hours=hours)
    result = await db.execute(
        select(EditorialChangeSet).where(
            EditorialChangeSet.workspace_id == ws,
            EditorialChangeSet.state == "applied",
            EditorialChangeSet.created_at >= since,
        )
    )
    sets = [
        cs
        for cs in result.scalars().all()
        if cs.origin == "voice" or (cs.origin == "undo" and cs.decided_by == "voice")
    ]
    undone = await _undone_by(db, ws, [cs.id for cs in sets])

    # Each decision write by voice, under its own change id (not the topic's one
    # decision row, which every write to it shares).
    decisions = list(
        (
            await db.execute(
                select(TopicDecisionChange).where(
                    TopicDecisionChange.workspace_id == ws,
                    TopicDecisionChange.decided_by == "voice",
                    TopicDecisionChange.decided_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )

    # Titles for every topic mentioned, in one query.
    packet_ids = [cs.target_id for cs in sets if cs.target_type == "packet"]
    packet_to_candidate: dict[str, uuid.UUID] = {}
    if packet_ids:
        rows = await db.execute(
            select(RecordingPacket.id, RecordingPacket.candidate_id).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id.in_(packet_ids)
            )
        )
        packet_to_candidate = {str(pid): cid for pid, cid in rows}
    ops_by: dict[str, list[dict[str, Any]]] = {}
    wanted: set[uuid.UUID] = {d.candidate_id for d in decisions}
    for cs in sets:
        ops = [
            change_service.operation_to_json(o)
            for o in await change_service.load_operations(db, ws, cs.id)
        ]
        ops = [o for o in ops if o["state"] == "applied"]
        ops_by[str(cs.id)] = ops
        if cs.target_type == "candidate_brief":
            wanted.add(cs.target_id)
        elif cs.target_type == "packet" and str(cs.target_id) in packet_to_candidate:
            wanted.add(packet_to_candidate[str(cs.target_id)])
        for o in ops:
            if o["op"] == "move_topic" and isinstance(o["after"], dict):
                try:
                    wanted.add(uuid.UUID(str(o["after"].get("candidate_id"))))
                except ValueError:
                    pass
    titles: dict[str, str] = {}
    statuses: dict[str, str] = {}
    if wanted:
        rows = await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(list(wanted))
            )
        )
        for c in rows.scalars().all():
            titles[str(c.id)] = c.title
            statuses[str(c.id)] = c.status

    items: list[dict[str, Any]] = []
    for cs in sets:
        if cs.target_type == "candidate_brief":
            cid = str(cs.target_id)
        elif cs.target_type == "packet":
            cid = str(packet_to_candidate.get(str(cs.target_id)) or "") or None
        else:
            cid = None
        ops = ops_by[str(cs.id)]
        when = cs.applied_at or cs.created_at
        is_undo = cs.origin == "undo"
        title = titles.get(cid or "", "This week" if cs.target_type == "lineup" else "")
        lines = [describe_operation(cs.target_type, o, titles) for o in ops]
        if _is_rewrite(cs):
            lines = [
                f'A new script was written for "{title}", replacing version {cs.base_version}.'
            ]
        items.append(
            {
                "kind": "change",
                "id": str(cs.id),
                "short_id": str(cs.id)[:8],
                "at": when.isoformat() if when else None,
                "summary": cs.summary,
                "target_type": cs.target_type,
                "candidate_id": cid,
                "title": title,
                "lines": lines,
                "is_undo": is_undo,
                "undone": str(cs.id) in undone,
                "can_undo": str(cs.id) not in undone,
            }
        )
    for d in decisions:
        cid = str(d.candidate_id)
        title = titles.get(cid, "An idea")
        words = {
            "this_week": f'Put "{title}" in this week.',
            "discuss": f'Marked "{title}" to think about.',
            "later": f'Saved "{title}" for later.',
            "away": f'Put "{title}" away.',
            None: f'Put "{title}" back with the ideas waiting for a decision.',
        }.get(d.after, f'Decided "{title}": {d.after}.')
        undone = d.undone_at is not None
        items.append(
            {
                "kind": "decision",
                "id": str(d.id),
                "short_id": str(d.id)[:8],
                "at": d.decided_at.isoformat() if d.decided_at else None,
                "candidate_id": cid,
                "title": title,
                "decision": d.after,
                "lines": [words],
                "undone": undone,
                "can_undo": not undone,
                "can_restore": (
                    d.after == "away" and not undone and statuses.get(cid) == "withdrawn"
                ),
            }
        )
    items.sort(key=lambda i: i["at"] or "", reverse=True)
    return {"hours": hours, "items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Research, in the background
# ---------------------------------------------------------------------------


def make_searcher() -> Any:
    """The web search, or None. Replaced in tests; never called at import time."""
    from tce.services.web_search import WebSearchService

    return WebSearchService()


def research_to_json(row: IdeaResearch) -> dict[str, Any]:
    return {
        "research_id": str(row.id),
        "short_id": str(row.id)[:8],
        "candidate_id": str(row.candidate_id),
        "state": row.state,
        "requested_by": row.requested_by,
        "query": row.query,
        "web_status": row.web_status,
        "summary": row.summary,
        "detail": row.detail,
        "evidence": list(row.evidence or []),
        "web": list(row.web or []),
        "started_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


# Research is one evidence query and one web search with a 15 second timeout, so
# a row still "running" after this long belongs to a process that died (a deploy
# restart, a crash) and will never finish. Left alone, it answered "already
# running" to every later request for that idea, for good.
RESEARCH_STALE_AFTER = timedelta(minutes=5)

INTERRUPTED_SUMMARY = (
    "The research stopped before it finished, because TCE restarted. Ask again to run it."
)
STALE_SUMMARY = (
    "The research stopped before it finished and never reported back, so it was started again."
)


def _mark_interrupted(row: IdeaResearch, detail: str, summary: str = INTERRUPTED_SUMMARY) -> None:
    row.state = "failed"
    row.detail = detail
    row.summary = summary
    row.finished_at = _now()


async def mark_interrupted_research(sm: Any) -> int:
    """At startup: research left running by the previous process is dead. Say so.

    The job runs as an in-process BackgroundTask, so nothing survives a restart to
    finish it. Returns how many rows were marked.
    """
    async with open_session(sm) as db:
        rows = (
            (await db.execute(select(IdeaResearch).where(IdeaResearch.state == "running")))
            .scalars()
            .all()
        )
        for row in rows:
            _mark_interrupted(row, "interrupted by server restart")
        await db.commit()
        return len(rows)


async def start_research(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> tuple[IdeaResearch, bool]:
    """Start research, or return the one already running. (row, created)."""
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    running = (
        (
            await db.execute(
                select(IdeaResearch).where(
                    IdeaResearch.workspace_id == ws,
                    IdeaResearch.candidate_id == candidate.id,
                    IdeaResearch.state == "running",
                )
            )
        )
        .scalars()
        .all()
    )
    now = _now()
    for row in running:
        started = row.created_at
        if started is not None and started.tzinfo is not None:
            started = started.astimezone(UTC).replace(tzinfo=None)
        if started is not None and now - started < RESEARCH_STALE_AFTER:
            return row, False
        # Started too long ago to still be alive: close it and start a new one.
        _mark_interrupted(
            row,
            f"no result after {int(RESEARCH_STALE_AFTER.total_seconds() // 60)} minutes; "
            "started again",
            STALE_SUMMARY,
        )
    row = IdeaResearch(
        workspace_id=ws,
        candidate_id=candidate.id,
        state="running",
        requested_by=actor,
        query=candidate.title[:500],
        evidence=[],
        web=[],
        web_status="skipped",
        # On the same clock the staleness check reads (naive UTC), rather than the
        # database's own now(), which follows the server's time zone.
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row, True


async def gather_evidence(
    db: AsyncSession, ws: uuid.UUID, candidate: TopicCandidate, *, limit: int = 12
) -> list[dict[str, Any]]:
    """His own calls and commits behind the idea, most specific first."""
    raw_ids = list(candidate.moment_ids or []) + [
        c.get("moment_id") for c in (candidate.citations_private or []) if isinstance(c, dict)
    ]
    ids: list[uuid.UUID] = []
    for value in raw_ids:
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError):
            continue
        if parsed not in ids:
            ids.append(parsed)
    found: list[dict[str, Any]] = []
    if ids:
        rows = await db.execute(
            select(EvidenceMoment, EvidenceSource)
            .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
            .where(EvidenceMoment.workspace_id == ws, EvidenceMoment.id.in_(ids))
        )
        for moment, source in rows.all():
            found.append(
                {
                    "moment_id": str(moment.id),
                    "source_kind": source.source_kind,
                    "title": source.title,
                    "occurred_at": source.occurred_at.isoformat() if source.occurred_at else None,
                    "excerpt": _clip(moment.excerpt_private, 300),
                    "lesson": _clip(moment.lesson_summary, 200),
                }
            )
    if not found:
        # The moments may have been pruned; the citations still say where it came from.
        for c in candidate.citations_private or []:
            if isinstance(c, dict):
                found.append(
                    {
                        "moment_id": c.get("moment_id"),
                        "source_kind": c.get("source_kind"),
                        "title": c.get("title"),
                        "occurred_at": None,
                        "excerpt": _clip(c.get("span"), 300),
                        "lesson": "",
                    }
                )
    return found[:limit]


def web_failure(error: BaseException) -> tuple[str, str]:
    """(what he hears, what is kept for whoever fixes it) for a web search that failed.

    A refused key and a spent quota cost money and need someone to act, so they
    are named as such rather than folded into "the search failed".
    """
    import httpx

    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            words = "the search key was refused"
        elif code in (402, 429):
            words = "the search is over its quota or rate limit"
        elif code >= 500:
            words = "the search service had an error"
        else:
            words = "the search answered with an error"
        return f"{words}, HTTP {code}", f"web search HTTP {code}"
    if isinstance(error, httpx.TimeoutException):
        return "the search did not answer in time", f"web search timeout: {type(error).__name__}"
    if isinstance(error, httpx.TransportError):
        return (
            "the search service could not be reached",
            f"web search unreachable: {type(error).__name__}",
        )
    return "", f"web search error: {type(error).__name__}: {_clip(error, 200)}"


def _summary(
    title: str,
    evidence: list[dict[str, Any]],
    web: list[dict[str, Any]],
    web_status: str,
    web_failed_because: str = "",
) -> str:
    calls = sum(
        1
        for e in evidence
        if "meeting" in str(e.get("source_kind") or "") or "call" in str(e.get("source_kind") or "")
    )
    commits = sum(
        1
        for e in evidence
        if "commit" in str(e.get("source_kind") or "")
        or "github" in str(e.get("source_kind") or "")
    )
    other = len(evidence) - calls - commits
    parts = []
    if calls:
        parts.append(f"{calls} from your calls")
    if commits:
        parts.append(f"{commits} from your commits")
    if other:
        parts.append(f"{other} other")
    own = (
        f"{len(evidence)} pieces of your own evidence ({', '.join(parts)})"
        if evidence
        else "none of your own evidence (TCE holds no calls or commits linked to it)"
    )
    web_words = {
        "searched": f"{len(web)} web results",
        "no_key": "no web search, because web search is not set up on TCE (no search key), "
        "so this is your own evidence only",
        "failed": "no web results, because the web search failed this time"
        + (f" ({web_failed_because})" if web_failed_because else "")
        + ", so this is your own evidence only",
        "skipped": "no web search",
    }[web_status]
    return f'Research on "{title}" is ready: {own}, and {web_words}.'


async def run_research(sm: Any, ws: uuid.UUID, research_id: uuid.UUID) -> None:
    """The background half. Never raises, and never leaves the row running.

    A failure inside the work is written onto the row with the result. A failure
    around it (the session will not open, the final commit fails) is written by
    a second, fresh session, because a row left "running" answers "already
    running" to the next request for this idea.
    """
    try:
        await _run_research(sm, ws, research_id)
    except Exception as error:
        logger.exception("voice.research_crashed", research_id=str(research_id))
        try:
            async with open_session(sm) as db:
                row = (
                    await db.execute(
                        select(IdeaResearch).where(
                            IdeaResearch.workspace_id == ws, IdeaResearch.id == research_id
                        )
                    )
                ).scalar_one_or_none()
                if row is not None and row.state == "running":
                    row.state = "failed"
                    row.detail = f"{type(error).__name__}: {_clip(error, 300)}"
                    row.summary = "The research stopped with an error. Nothing else was changed."
                    row.finished_at = _now()
                    await db.commit()
        except Exception:
            logger.exception("voice.research_not_closed", research_id=str(research_id))


async def _run_research(sm: Any, ws: uuid.UUID, research_id: uuid.UUID) -> None:
    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(IdeaResearch).where(
                    IdeaResearch.workspace_id == ws, IdeaResearch.id == research_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return
        # Nothing is written onto `row` itself: the result goes in with one UPDATE
        # that only touches a row still "running" (below).
        values: dict[str, Any]
        try:
            candidate = await inbox_service.get_candidate(db, ws, row.candidate_id)
            evidence = await gather_evidence(db, ws, candidate)
            web: list[dict[str, Any]] = []
            failed_because = ""
            detail = row.detail
            searcher = make_searcher()
            if searcher is None or not getattr(searcher, "api_key", None):
                web_status = "no_key"
            else:
                try:
                    # raise_errors: a refused key or a spent quota must read as a
                    # failed search, not as a search that found nothing.
                    hits = await searcher.search(
                        row.query or candidate.title, count=5, raise_errors=True
                    )
                    web = [
                        {
                            "title": h.get("title"),
                            "url": h.get("url"),
                            "description": _clip(h.get("description"), 300),
                            "age": h.get("age"),
                        }
                        for h in hits or []
                    ]
                    web_status = "searched"
                except Exception as error:  # the web half must not sink the evidence half
                    logger.warning("voice.research_web_failed", error=type(error).__name__)
                    web_status = "failed"
                    failed_because, detail = web_failure(error)
            values = {
                "evidence": evidence,
                "web": web,
                "web_status": web_status,
                "detail": detail,
                "summary": _summary(candidate.title, evidence, web, web_status, failed_because),
                "state": "done",
            }
        except Exception as error:
            logger.exception("voice.research_failed", research_id=str(research_id))
            values = {
                "state": "failed",
                "detail": f"{type(error).__name__}: {_clip(error, 300)}",
                "summary": "The research stopped with an error. Nothing else was changed.",
            }
        values["finished_at"] = _now()
        # A search that hung past RESEARCH_STALE_AFTER was retired meanwhile (its
        # row marked failed, a new run started). Coming back late, it must not
        # turn that row into "done" over the retirement.
        written = await db.execute(
            update(IdeaResearch)
            .where(
                IdeaResearch.workspace_id == ws,
                IdeaResearch.id == research_id,
                IdeaResearch.state == "running",
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if written.rowcount == 0:
            logger.info("voice.research_retired_meanwhile", research_id=str(research_id))
            await db.rollback()
            return
        await db.commit()
