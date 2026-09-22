"""The three script rules that make a news idea sound like Ziv, not a news account.

All three are hard failures on the packet, not warnings, and all three apply only
to news-led candidates. An evergreen packet never reaches this module.

1. The opening may not name the vendor, the product, a date or a number. This is
   the rule that separates the lane from a feed: a news account opens with "OpenAI
   just released"; Ziv opens with the owner's situation. If the opening needs the
   news to be interesting, the idea is not his. Checked on every hook option and
   on the first script phrase, because the first phrase IS the chosen hook.

2. The news fact may not appear before the second beat. The first beat belongs to
   the owner's situation; the announcement arrives as the reason something
   changed, not as the headline.

3. No urgency vocabulary anywhere. "Breaking", "just announced", "everyone is
   talking about", "before it's too late" - the manufactured urgency the
   editorial rules forbid. The shared banned-vocabulary list still applies on top.
"""

from __future__ import annotations

import re
from typing import Any

# Matched on a casefolded, whitespace-normalised copy of each text.
_URGENCY = re.compile(
    r"\b(breaking|just (announced|released|dropped|launched)|everyone is talking about"
    r"|before it'?s too late|act now|don'?t miss|right now,? before|while you still can"
    r"|game.?changer|the clock is ticking|urgent(ly)?)\b"
)

# A date in any of the forms a script would say it.
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE = re.compile(
    rf"\b(\d{{1,2}}(st|nd|rd|th)?\s+({_MONTHS})|({_MONTHS})\s+\d{{1,2}}(st|nd|rd|th)?"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(/\d{2,4})?|(19|20)\d{2}"
    r"|(yesterday|today|tomorrow|this (morning|week|month)|last (week|month|night)))\b"
)
# Any digit at all, and number words a hook would lean on.
_NUMBER = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand"
    r"|million|billion|percent|half|double|triple)\b"
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _term_hit(term: str, text: str) -> bool:
    t = _norm(term)
    return bool(t) and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text) is not None


def opening_problems(text: str, forbidden_terms: list[str]) -> list[str]:
    """Why this opening line would sound like a news account, if it would."""
    low = _norm(text)
    problems = [f"names '{t}'" for t in forbidden_terms if _term_hit(t, low)]
    if _DATE.search(low):
        problems.append("carries a date")
    if _NUMBER.search(low):
        problems.append("carries a number")
    return problems


def urgency_hit(texts: list[str]) -> str | None:
    for text in texts:
        m = _URGENCY.search(_norm(text))
        if m:
            return m.group(0)
    return None


def news_errors(
    packet: dict[str, Any],
    forbidden_terms: list[str],
) -> list[str]:
    """All three rules, as validation errors in the packet validator's own voice.

    `packet` is the cleaned output of validate_packet_output. `forbidden_terms` is
    the vendor, publisher and product names the announcement is about.
    """
    errors: list[str] = []
    terms = [t for t in dict.fromkeys(forbidden_terms or []) if str(t).strip()]
    phrases: list[str] = packet.get("script_phrases") or []

    # 1. The opening, on every hook and on the first spoken phrase.
    for option in packet.get("hook_options") or []:
        found = opening_problems(option.get("text", ""), terms)
        if found:
            errors.append(
                f"news opening {option.get('id')} {', '.join(found)}; open with the "
                "owner's situation, not the announcement"
            )
    if phrases:
        found = opening_problems(phrases[0], terms)
        if found and not any("news opening" in e for e in errors):
            errors.append(f"the first spoken phrase {', '.join(found)}")

    # 2. The news fact waits for the second beat.
    beats = packet.get("beats") or []
    if beats and phrases and terms:
        first = beats[0]
        ids = [f"p{i:03d}" for i in range(1, len(phrases) + 1)]
        try:
            start = ids.index(first["start_phrase_id"])
            end = ids.index(first["end_phrase_id"])
        except (KeyError, ValueError):
            start, end = 0, -1
        for phrase in phrases[start : end + 1]:
            low = _norm(phrase)
            hit = next((t for t in terms if _term_hit(t, low)), None)
            if hit:
                errors.append(
                    f"the first beat names '{hit}'; the news belongs in beat two or later"
                )
                break

    # 3. No manufactured urgency, anywhere a viewer or reader would see it.
    public = [
        *(packet.get("bullets") or []),
        *phrases,
        str(packet.get("facebook_post") or ""),
        str(packet.get("linkedin_post") or ""),
        *[str(o.get("text") or "") for o in packet.get("hook_options") or []],
    ]
    urgent = urgency_hit(public)
    if urgent:
        errors.append(f"manufactured urgency is not allowed in a news idea: '{urgent}'")

    return errors


def forbidden_terms_for(
    news_ref: dict[str, Any] | None, anchors: list[dict[str, Any]]
) -> list[str]:
    """The names an opening must not use: publisher, and the vendor/model anchors.

    Client solutions and problem patterns are NOT forbidden: they describe the
    owner's situation, which is exactly what the opening is supposed to be about.
    """
    terms: list[str] = []
    ref = news_ref or {}
    if ref.get("publisher"):
        terms.append(str(ref["publisher"]))
    for anchor in anchors or []:
        if anchor.get("kind") in ("vendor", "model_id", "dependency", "capability"):
            terms.append(str(anchor.get("term") or ""))
    return [t for t in terms if t.strip()]
