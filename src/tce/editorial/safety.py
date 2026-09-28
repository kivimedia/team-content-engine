"""Deterministic public-safety scan for public drafts (editorial redaction).

This is not a client-permission workflow. It flags things that must not reach a
public draft: contact details, money figures, revenue-tied percentages, tokenized
URLs, names of other participants from the cited sources, customer-quote markers,
credential-like strings and absolute guarantees. It never rewrites text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])")
_MONEY = re.compile(
    r"(?:[$€£₪]\s?\d[\d,.]*\s*[kKmM]?)"
    r"|(?:\b\d[\d,.]*\s*[kKmM]?\s*(?:usd|eur|gbp|ils|nis|dollars?|euros?|pounds|shekels?)\b)"
    r"|(?:\b\d[\d,.]*\s*[kKmM]\s*(?:/|per|a)\s*(?:mo|month|year|yr|week)\b)",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b)", re.IGNORECASE)
_REVENUE_WORDS = re.compile(
    r"\b(revenue|sales|profit|income|margin|bookings?|conversion|clients?|customers?|roi|"
    r"turnover|earnings|leads?|deals?|close rate|pipeline)\b",
    re.IGNORECASE,
)
_TOKEN_URL = re.compile(
    r"https?://\S+?[?&](?:token|key|api_key|apikey|sig|signature|auth|access_token|code|"
    r"s|t|secret|password|session)=\S+",
    re.IGNORECASE,
)
_QUOTE_MARKERS = re.compile(
    r"\b(?:(?:my|a|one|our|the)\s+(?:client|customer|caller|bride|guest)\s+"
    r"(?:said|told me|wrote|texted|emailed|put it)|in (?:her|his|their) (?:own )?words|"
    r"testimonial|quote from (?:a|my|one) (?:client|customer))\b",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|"
    r"AKIA[0-9A-Z]{12,}|xox[abpr]-[A-Za-z0-9-]{8,}|sbp_[A-Za-z0-9]{10,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})"
    r"|(?:\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*\S+)"
    r"|(?:\bbearer\s+[A-Za-z0-9._-]{16,})"
    r"|(?:\b[a-f0-9]{32,}\b)",
    re.IGNORECASE,
)
_GUARANTEE = re.compile(
    r"\b(?:guarantee[ds]?|100\s*%\s*(?:sure|certain|guaranteed)|always works|never fails|"
    r"risk[- ]free|zero risk|will definitely|proven to (?:double|triple|work)|"
    r"works every time|no matter what)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")

# A guarantee that is denied is a disclaimer, not a promise. "It's not a guarantee,
# it's a starting point." and "it's a rule of thumb, not a guarantee" parked real
# scripts as drafts on 28-Sep-2026. The denial has to sit right before the phrase,
# on the same line, with at most two small words between ("not a", "can't"), so
# "Not only do I guarantee results", "It's not a trick, I guarantee it" and a
# dramatic "It's not\n\nGuaranteed bookings..." still flag. "Nobody" and "no one"
# deny only with a verb of their own ("No one can guarantee"): "Nobody guarantees
# results like we do" is a boast (review, 28-Sep-2026).
_DENIAL_GAP = (
    r"(?:[ \t]+(?:a|an|any|the|is|are|was|be|been|ever|really|actually|necessarily|"
    r"always|can|could|will|would)){0,2}"
)
_DENIED_BEFORE = re.compile(
    r"(?:"
    rf"(?:\b(?:no[ \t]+such[ \t]+thing[ \t]+as|not|no|never|without|cannot)|n['\u2019]t)"
    rf"{_DENIAL_GAP}"
    r"|\b(?:nothing|nobody|no[ \t]+one)(?:['\u2019]s|"
    r"(?:[ \t]+(?:is|are|was|were|can|could|will|would|should|ever|really|truly|be|been))+)"
    rf"{_DENIAL_GAP}"
    r")[ \t]+$",
    re.IGNORECASE,
)
# "...guaranteed like this system", "guarantees results the way we do": a denial
# in front of a comparison is still a claim that this one guarantees it.
_COMPARED_AFTER = re.compile(
    r"(?:[ \t]+[^\W\d_]+){0,3}?[ \t]+(?:like|the[ \t]+way|as)[ \t]+"
    r"(?:we|us|our|ours|this|mine|my|i)\b",
    re.IGNORECASE,
)
# "Why not guaranteed results?", "Is this not guaranteed?": asked like this, the
# denial is an offer. A tag question ("It's not a guarantee, is it?") still hedges.
_ASKED = re.compile(
    r"\s*[\"'\u201c\u2018(*-]*\s*(?:why|is|are|was|were|isn['\u2019]t|aren['\u2019]t|"
    r"wasn['\u2019]t|weren['\u2019]t|don['\u2019]t|doesn['\u2019]t|didn['\u2019]t|"
    r"wouldn['\u2019]t|won['\u2019]t)\b",
    re.IGNORECASE,
)
# "You'll never be without a guarantee": two denials make a promise.
_NEGATION = re.compile(r"\b(?:never|not|no)\b|n['\u2019]t\b", re.IGNORECASE)

# Speaker labels that are not names
_GENERIC_SPEAKERS = {
    "speaker",
    "unknown",
    "participant",
    "host",
    "guest",
    "me",
    "you",
    "team",
    "bot",
}
_OWNER_TOKENS = ("ziv",)

# Display names carry more than a name: "Tim Hollis - In The Box Events",
# "Tim (In The Box)", "In The Box | Tim", "Tim's iPhone". Splitting the whole
# string into words made "The" a participant, so every sentence that opened with
# "The" was flagged as naming a client (28-Sep-2026). The name is looked for; the
# words around it are not. The split keeps its separators: a part after "/" can
# be a second person ("Tim / Sarah"), a part in brackets or after a dash is extra.
_DISPLAY_SPLIT = re.compile(
    r"(\s*[|()\[\]{}/,\u2022\u00b7\u2013\u2014]\s*|\s+-\s*|\s*-\s+|\s+@\s+|\s+(?:from|at|of)\s+)"
)
# "Sarah and Mike", "Sarah & Mike Cohen": two people in one invite, each a name.
_PEOPLE_SPLIT = re.compile(r"\s+(?:and|&|\+)\s+", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*")
_POSSESSIVE = re.compile(r"['\u2019]s$", re.IGNORECASE)
# "Tim Hollis he/him" (no brackets): the pronouns trail the name.
_TRAILING_PRONOUNS = re.compile(
    r"(?:[\s/]+(?:he|him|his|she|her|hers|they|them|their|theirs|xe|xem|ze|zir|hir|"
    r"pronouns))+\s*$",
    re.IGNORECASE,
)
# A digit or a joined "&" makes a brand, whatever its words: "B&B Events",
# "Studio 54", "DJ 360", "A1 Sound".
_BRAND_MARK = re.compile(r"\d|[^\W\d_]&|&[^\W\d_]")
# Punctuation that sits on a display name's words but is not part of the name.
_TOKEN_TRIM = ".,;:!?\"'\u201c\u201d\u2018\u2019"

# Small words: never a name, and a part of a display name that has one ("In The
# Mix") is a business, not a person. Pronouns are here because Zoom shows them in
# the name ("Tim Hollis (he/him)"), and "He" opens half the sentences he says.
_SMALL_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by",
        "from", "as", "is", "it", "its", "this", "that", "our", "your", "my", "his", "her",
        "their", "we", "you", "me", "us", "not", "no", "all", "new", "just", "only",
        "he", "him", "she", "hers", "they", "them", "theirs", "xe", "xem", "ze", "zir",
        "hir", "pronouns",
    }
)

# Never a name either, but they sit beside one ("Dr Dana Lee", "Tim's iPhone",
# "DJ Tim", "Tim Hollis - Owner").
_LABEL_WORDS = frozenset(
    {
        # titles
        "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "rev", "jr", "sr",
        # roles a person puts beside their own name
        "dj", "djs", "mc", "emcee", "owner", "founder", "cofounder", "ceo", "coo", "cto",
        "cfo", "president", "director", "manager", "coach", "consultant", "assistant",
        "producer", "editor", "planner", "coordinator", "entertainer", "magician",
        "officiant", "intern", "vp", "svp", "evp", "chief", "officer", "executive", "exec",
        "head", "lead", "senior", "sales", "booking", "bookings", "operations", "ops",
        "growth", "support", "partner", "pro", "specialist", "rep", "account", "accounts",
        "finance", "billing", "hr",
        # devices and meeting labels
        "iphone", "ipad", "android", "galaxy", "pixel", "phone", "mobile", "laptop",
        "macbook", "desktop", "pc", "zoom", "user", "admin", "office", "room",
        "speaker", "unknown", "participant", "host", "guest", "team", "bot", "notetaker",
        "recorder", "fathom", "otter",
    }
)

# A word like these marks a part of a display name as a business, not a person.
_COMPANY_WORDS = frozenset(
    {
        "events", "event", "llc", "inc", "ltd", "limited", "co", "corp", "corporation",
        "company", "group", "studio", "studios", "media", "agency", "consulting",
        "consultants", "solutions", "services", "productions", "entertainment", "club",
        "academy", "marketing", "design", "designs", "photography", "photo", "films",
        "film", "video", "digital", "labs", "lab", "partners", "associates", "enterprises",
        "international", "global", "hq", "official", "music", "sound",
        "sounds", "band", "weddings", "wedding", "rentals", "catering", "decor", "florist",
        "florals", "flowers", "balloons", "parties", "party", "coaching", "fitness",
        "realty", "properties", "capital", "ventures", "holdings", "systems", "software",
        "tech", "technologies", "network", "institute", "foundation", "school",
        "university", "college", "church", "center", "centre", "clinic", "shop", "store",
        "boutique", "bakery", "cafe", "restaurant", "hotel", "salon", "spa", "magic", "kids",
    }
)

# "Anna van der Berg", "Maria del Carmen": part of the full name, never a name on
# their own ("Van rentals are pricey."). Only past the first word: "Del Smith".
_PARTICLES = frozenset(
    {"van", "von", "der", "den", "de", "da", "di", "du", "del", "della", "la", "le", "bin",
     "ibn", "al", "el"}
)

_NOT_A_NAME = _SMALL_WORDS | _LABEL_WORDS | _COMPANY_WORDS

# Everyday words that make up business names ("Big Fun Parties", "Premier
# Entertainment") and surnames ("Sarah Price", "Tom Long") but are not given names.
# They open ordinary sentences all the time ("Fun fact:", "Price is the first
# thing they ask", "Long story short"), so on their own they flag only
# mid-sentence ("I asked Price"). The full name still flags anywhere. Given names
# stay OUT of this list: "Grace asked about pricing." has to flag (28-Sep-2026).
_COMMON_WORDS = frozenset(
    {
        # business-name words
        "big", "fun", "little", "happy", "best", "better", "good", "great", "top", "first",
        "prime", "royal", "golden", "gold", "silver", "elite", "premier", "total",
        "ultimate", "dream", "dreams", "star", "stars", "bright", "smart", "simple",
        "true", "pure", "blue", "red", "green", "black", "white", "brown", "gray", "grey",
        "north", "south", "east", "west", "city", "urban", "modern", "classic", "perfect",
        "mix", "master", "masters", "beat", "beats", "rhythm", "groove", "vibe", "vibes",
        "dance", "light", "lights", "fresh", "wild", "free", "easy", "next", "one", "high",
        "live", "loud", "sweet", "epic", "luxe", "luxury", "premium", "custom", "creative",
        "united", "local", "coast", "bay", "valley", "hour", "moment", "moments",
        "forever", "ever", "after", "touch", "spark", "shine", "glow", "style", "vision",
        "focus", "motion", "capture", "bloom", "peak", "summit", "key", "core", "bold",
        "express", "quick", "day", "days", "night", "nights", "level", "life", "time",
        "world", "house", "home", "heart", "soul",
        # surnames that are everyday words
        "young", "long", "short", "strong", "sharp", "stone", "wood", "hill", "park",
        "hall", "bell", "price", "king", "love", "rice", "ward", "cook", "baker", "fox",
        "wolf", "bird", "bush",
    }
)

# Given names that are also a word which opens sentences: "Will this work?",
# "Mark each problem.", "May I ask?". The first fix made these (and ~130 more,
# Nick, Grace, Max among them) flag only mid-sentence, so "Grace asked about
# pricing." went out as ready (review, 28-Sep-2026). Now they flag at the start of
# a sentence too, unless the next word makes them the ordinary word.
_SUBJECTS = frozenset(
    {
        "i", "you", "we", "they", "he", "she", "it", "this", "that", "these", "those",
        "there", "the", "a", "an", "your", "my", "our", "their", "his", "her", "its",
        "any", "anyone", "anybody", "anything", "someone", "somebody", "something",
        "everyone", "everybody", "everything", "people", "all", "every", "each", "no",
        "nobody", "nothing",
    }
)
_OBJECTS = frozenset(
    {
        "the", "a", "an", "it", "this", "that", "these", "those", "them", "him", "her",
        "me", "us", "you", "your", "my", "our", "their", "his", "every", "each", "all",
        "one", "down", "up", "off",
    }
)
_WORD_NAMES: dict[str, frozenset[str]] = {
    "will": _SUBJECTS,
    "may": _SUBJECTS | {"be"},
    "mark": _OBJECTS | {"which", "whatever", "today"},
    "grant": _OBJECTS | {"yourself", "access", "permission"},
    "chase": _OBJECTS
    | {"after", "leads", "payments", "invoices", "deposits", "referrals", "clients",
       "customers", "people"},
    "bill": _OBJECTS
    | {"for", "by", "per", "hourly", "monthly", "weekly", "upfront", "more", "less",
       "clients", "customers"},
    "hope": frozenset(
        {"you", "this", "that", "it", "so", "not", "for", "alone", "we", "i", "they",
         "everyone", "everybody", "all", "your"}
    ),
}

# What can sit between a sentence's end and its first word: space, quotes, a bullet.
_OPENERS = " \t\"'\u201c\u2018(*-\u2013\u2014"
_SENTENCE_ENDS = ".!?:;\n\u2026"
# A period after these does not end a sentence: "I asked Dr. Frank", "e.g. Tim".
_ABBREVIATION = re.compile(
    r"(?:^|[^\w.])(?:dr|mr|mrs|ms|mx|prof|rev|st|jr|sr|vs|etc|approx|e\.g|i\.e)\.$",
    re.IGNORECASE,
)
_NEXT_WORD = re.compile(r"[ \t]+([^\W\d_]+)")


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - 20) : min(len(text), end + 20)].strip()


def _is_denied(text: str, start: int, end: int) -> bool:
    """True when the guarantee phrase at `start`..`end` is being denied, not made."""
    window_start = max(0, start - 80)
    denial = _DENIED_BEFORE.search(text[window_start:start])
    if not denial:
        return False
    if _COMPARED_AFTER.match(text, end):
        return False
    opens = max(text.rfind(ch, 0, start) for ch in ".!?\n") + 1
    closes = min((i for i in (text.find(ch, end) for ch in ".!?\n") if i >= 0), default=-1)
    if closes >= 0 and text[closes] == "?" and _ASKED.match(text, opens):
        return False
    denied_at = window_start + denial.start()
    if denial.group(0).lower().startswith("without") and _NEGATION.search(
        text, opens, max(opens, denied_at)
    ):
        return False
    return True


def _name_from_email(raw: str) -> str | None:
    """The person in an email-shaped display name, when there is one to find.

    "Tim Hollis <tim@x.com>" keeps the name beside the address; "tim.hollis@x.com"
    reads as Tim Hollis. A bare mailbox ("info@", "thollis@") names nobody for
    certain, so it is left out, as every email was before 28-Sep-2026.
    """
    beside = _EMAIL.sub(" ", raw).strip(" <>\"'")
    if _WORD.search(beside):
        return " ".join(beside.split())
    match = _EMAIL.search(raw)
    if not match:
        return None
    parts = [p for p in re.split(r"[._-]+", match.group(0).split("@")[0]) if p]
    if len(parts) < 2 or not all(p.isalpha() and len(p) >= 2 for p in parts):
        return None
    return " ".join(p.capitalize() for p in parts)


def participant_names(names: Iterable[str | None]) -> list[str]:
    """Normalize participant names from sources, dropping Ziv and generic labels."""
    out: list[str] = []
    for raw in names:
        if not raw or not isinstance(raw, str):
            continue
        name = raw.strip()
        if "@" in name:
            name = _name_from_email(name) or ""
        low = name.lower()
        if not name:
            continue
        if any(tok in low.split() or low.startswith(tok) for tok in _OWNER_TOKENS):
            continue
        first = low.split()[0].rstrip("0123456789 ")
        if first in _GENERIC_SPEAKERS:
            continue
        if name not in out:
            out.append(name)
    return out


def _words_of(text: str) -> list[str]:
    return [w for w in (_POSSESSIVE.sub("", w) for w in _WORD.findall(text)) if w]


def _is_company(segment: str, words: list[str]) -> bool:
    """True when this part of a display name is a business, not a person.

    A business ends in a business word ("Smith Coaching", "In The Box Events"),
    carries a digit or a joined "&" ("Studio 54", "B&B Events"), or has a small
    word in it ("In The Box"). Only the END counts for a business word, so "Magic
    Mike" is a person. A small word counts past the first word, or as "The": a
    given name can be a small word ("An Nguyen", "My Tran"), and a first fix that
    missed this lost "Nguyen" altogether (review, 28-Sep-2026). Length alone is not
    a sign: "Maria del Carmen Lopez Garcia" is one person.
    """
    lowered = [w.lower() for w in words]
    if _BRAND_MARK.search(segment) or lowered[-1] in _COMPANY_WORDS:
        return True
    return len(words) > 1 and any(
        w in _SMALL_WORDS and (i > 0 or w == "the") for i, w in enumerate(lowered)
    )


def _is_role(words: list[str]) -> bool:
    """A part made only of roles and business words: "Sales", "Wedding DJ", "VP Sales"."""
    return all(w.lower() in _NOT_A_NAME for w in words)


def _spellings(tokens: list[str]) -> set[tuple[str, ...]]:
    """How a name is written in a sentence: capitalized, or as the display had it.

    "tim hollis" is written "Tim Hollis"; "McDonald" stays "McDonald".
    """
    first = tuple([tokens[0][:1].upper() + tokens[0][1:], *tokens[1:]])
    each = tuple(t[:1].upper() + t[1:] for t in tokens)
    out = {first, each}
    if all(t.isupper() for t in tokens) and len("".join(tokens)) > 1:
        out.add(tuple(t.capitalize() for t in tokens))
    return out


def _starts_sentence(text: str, start: int) -> bool:
    before = text[:start].rstrip(_OPENERS)
    if not before:
        return True
    if before[-1] not in _SENTENCE_ENDS:
        return False
    return not (before[-1] == "." and _ABBREVIATION.search(before))


@dataclass(frozen=True)
class _NamePattern:
    """One thing to look for, and what a capital at the start of a sentence proves."""

    name: str
    pattern: re.Pattern[str]
    # An everyday word ("Fun", "Price"): at the start of a sentence it is the word.
    mid_only: bool = False
    # A given name that is also a word ("Will"): at the start of a sentence it is
    # the word only when one of these follows ("Will this work?").
    ordinary_next: frozenset[str] | None = None

    def names_someone(self, text: str, m: re.Match[str]) -> bool:
        if not (self.mid_only or self.ordinary_next) or not _starts_sentence(text, m.start()):
            return True
        if self.mid_only:
            return False
        assert self.ordinary_next is not None
        nxt = _NEXT_WORD.match(text, m.end())
        return not (nxt and nxt.group(1).lower() in self.ordinary_next)


def _name_patterns(names: list[str]) -> list[_NamePattern]:
    """Everything to look for, per display name.

    The person's full name and each name word; a business as its whole name, as
    written ("B&B Events"), and without its trailing business words ("In The
    Mix"); roles, titles and places beside the name ("Sales", "Head of Growth",
    "(Chicago)") not at all, because each one flagged ordinary sentences
    ("Sales went up", review 28-Sep-2026). Case-sensitive: names are capitalized,
    and "will" is not "Will".
    """
    pats: list[_NamePattern] = []
    seen: set[tuple[Any, ...]] = set()

    def add(
        name: str,
        tokens: list[str] | tuple[str, ...],
        *,
        mid_only: bool = False,
        ordinary_next: frozenset[str] | None = None,
    ) -> None:
        for spelled in _spellings(list(tokens)):
            key = (spelled, mid_only, ordinary_next)
            if key in seen:
                continue
            seen.add(key)
            body = r"\s+".join(re.escape(t) for t in spelled)
            # A possessive or a spoken contraction still names ("Tim's idea",
            # "Tim'll tell you"); only "n't" makes another word ("Don't").
            pats.append(
                _NamePattern(
                    name,
                    re.compile(rf"(?<!\w){body}(?!\w)(?!['\u2019]t\b)"),
                    mid_only,
                    ordinary_next,
                )
            )

    def add_person(name: str, words: list[str], *, in_business: bool = False) -> None:
        """A person's name: the full name anywhere, and each name word.

        A one-word name is the only name there is, so it is never "mid-sentence
        only", even when it is an everyday word. In front of a business word
        ("Big Fun Parties") an everyday word is not a name for sure.
        """
        words = [w for w in words if w.lower() not in _LABEL_WORDS]  # "Dr", "DJ"
        if not words:
            return
        if len(words) > 1:
            # The full name ("Tim Hollis") is never an ordinary phrase.
            add(name, words)
        lone = len(words) == 1 and not in_business
        shortest = 2 if len(words) == 1 else 3
        for index, word in enumerate(words):
            # "Smith-Jones" is also said as "Smith".
            for part in dict.fromkeys([word, *word.split("-")]):
                low = part.lower()
                if len(part) < shortest or low in _NOT_A_NAME:
                    continue
                if index > 0 and low in _PARTICLES:
                    continue
                add(
                    name,
                    [part],
                    mid_only=low in _COMMON_WORDS and not lone,
                    ordinary_next=_WORD_NAMES.get(low),
                )

    def add_business(name: str, segment: str) -> None:
        """A business as written, plus an owner's name in front of it.

        "Tim Hollis In The Box Events" and "Sarah Smith Coaching" put a person's
        name in front of the business words. Those words flag anywhere, as a name
        does, unless they are everyday words ("Big Fun Parties"): a first fix
        flagged them only mid-sentence, so "Sarah raised her prices." went out as
        ready (review, 28-Sep-2026).
        """
        tokens = [t for t in (t.strip(_TOKEN_TRIM) for t in segment.split()) if t]
        if not tokens:
            return

        def phrase(part: list[str]) -> None:
            if len(part) > 1 or (part and _BRAND_MARK.search(part[0])):
                add(name, part)
            # Said without "Events"/"LLC": "the team at In The Box".
            short = list(part)
            while short and short[-1].lower() in _COMPANY_WORDS:
                short.pop()
            if len(short) > 1 and short != part:
                add(name, short)

        phrase(tokens)
        start = 0
        while start < len(tokens) and tokens[start].lower() in (_LABEL_WORDS | {"the"}):
            start += 1  # "DJ Tim Hollis Events", "The DJ Tim"
        run: list[str] = []
        end = start
        for token in tokens[start:]:
            words = _words_of(token)
            if _BRAND_MARK.search(token) or not words:
                break
            if any(w.lower() in _NOT_A_NAME for w in words):
                break
            run.extend(words)
            end += 1
        if not run:
            return
        add_person(name, run, in_business=True)
        # The business without the owner's name in front: "In The Box Events".
        phrase(tokens[end:])

    for name in names:
        pieces = _DISPLAY_SPLIT.split(name)
        # (part, what joined it to the part before)
        parts: list[tuple[str, str]] = []
        for index in range(0, len(pieces), 2):
            joined_by = pieces[index - 1].strip() if index else ""
            segment = _TRAILING_PRONOUNS.sub("", pieces[index])
            words = _words_of(segment)
            # "Sarah and Mike" is two people; "Smith and Sons Events" is one business.
            if not words or _BRAND_MARK.search(segment) or words[-1].lower() in _COMPANY_WORDS:
                parts.append((segment, joined_by))
                continue
            for n, part in enumerate(_PEOPLE_SPLIT.split(segment)):
                parts.append((part, joined_by if n == 0 else "/"))

        # Which part is the person. Businesses and roles never are. Of the rest,
        # the first that is not all everyday words ("Mix Masters | Tim" names Tim).
        kept: list[tuple[str, str, list[str], str]] = []
        for segment, joined_by in parts:
            words = _words_of(segment)
            if not words:
                continue
            if _is_company(segment, words):
                add_business(name, segment)
                kind = "business"
            else:
                kind = "role" if _is_role(words) else "maybe"
            kept.append((segment, joined_by, words, kind))
        maybes = [item for item in kept if item[3] == "maybe"]
        primary = None
        if maybes:
            primary = next(
                (item for item in maybes if not all(w.lower() in _COMMON_WORDS for w in item[2])),
                maybes[0],
            )

        # The words of the part just before, when it was a person. After "/" or
        # "and" a second person can follow ("Tim / Sarah"); after a comma, a lone
        # first name after a lone surname is the same person ("Hollis, Tim").
        previous: list[str] | None = None
        for item in kept:
            segment, joined_by, words, kind = item
            before, previous = previous, None
            if kind != "maybe":
                continue
            everyday = all(w.lower() in _COMMON_WORDS for w in words)
            another = before is not None and (
                joined_by == "/"
                or (
                    joined_by == ","
                    and len(before) == 1
                    and len(words) <= 2
                    and not any(w.lower() in _COMMON_WORDS for w in words)
                )
            )
            # "Chicago - Tim Hollis": a one-word part first, a full name after it.
            full_name_after = (
                primary is not None
                and item is not primary
                and len(primary[2]) == 1
                and len(words) > 1
                and not everyday
            )
            if item is primary or another or full_name_after:
                add_person(name, words)
                previous = words
                continue
            # A place, a nickname or a tagline beside the name ("(Chicago)",
            # "(Best Man)"): only its whole phrase names anyone.
            if len(words) > 1:
                add(name, words)
    return pats


def scan_public_text(
    fields: dict[str, Any], *, participants: Iterable[str | None] = ()
) -> dict[str, Any]:
    """Scan public fields. `fields` maps field name -> str or list[str].

    Returns {"checked": True, "status": "clean"|"issues", "issues": [...]} where each
    issue is {"field", "kind", "match"}.
    """
    issues: list[dict[str, Any]] = []
    name_pats = _name_patterns(participant_names(participants))

    def add(field: str, kind: str, text: str, m: re.Match[str]) -> None:
        issues.append({"field": field, "kind": kind, "match": _snippet(text, m.start(), m.end())})

    for field, value in fields.items():
        texts = value if isinstance(value, list) else [value]
        for idx, text in enumerate(texts):
            if not isinstance(text, str) or not text:
                continue
            label = f"{field}[{idx}]" if isinstance(value, list) else field
            for kind, pat in (
                ("email", _EMAIL),
                ("token_url", _TOKEN_URL),
                ("credential", _CREDENTIAL),
                ("money", _MONEY),
                ("customer_quote", _QUOTE_MARKERS),
                ("absolute_guarantee", _GUARANTEE),
            ):
                for m in pat.finditer(text):
                    if kind == "absolute_guarantee" and _is_denied(text, m.start(), m.end()):
                        continue
                    add(label, kind, text, m)
            for m in _PHONE.finditer(text):
                if sum(ch.isdigit() for ch in m.group(0)) >= 9:
                    add(label, "phone", text, m)
            for sentence in _SENTENCE_SPLIT.split(text):
                if _PERCENT.search(sentence) and _REVENUE_WORDS.search(sentence):
                    m = _PERCENT.search(sentence)
                    assert m is not None
                    add(label, "revenue_percentage", sentence, m)
            for name_pat in name_pats:
                if any(name_pat.names_someone(text, m) for m in name_pat.pattern.finditer(text)):
                    issues.append(
                        {"field": label, "kind": "participant_name", "match": name_pat.name}
                    )
    # de-duplicate identical issues
    unique: list[dict[str, Any]] = []
    for issue in issues:
        if issue not in unique:
            unique.append(issue)
    return {"checked": True, "status": "issues" if unique else "clean", "issues": unique}
