"""Deterministic public-safety scan for public drafts (editorial redaction).

This is not a client-permission workflow. It flags things that must not reach a
public draft: contact details, money figures, revenue-tied percentages, tokenized
URLs, names of other participants from the cited sources, customer-quote markers,
credential-like strings and absolute guarantees. It never rewrites text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
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


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - 20) : min(len(text), end + 20)].strip()


def participant_names(names: Iterable[str | None]) -> list[str]:
    """Normalize participant names from sources, dropping Ziv and generic labels."""
    out: list[str] = []
    for raw in names:
        if not raw or not isinstance(raw, str):
            continue
        name = raw.strip()
        low = name.lower()
        if not name or "@" in name:
            continue
        if any(tok in low.split() or low.startswith(tok) for tok in _OWNER_TOKENS):
            continue
        first = low.split()[0].rstrip("0123456789 ")
        if first in _GENERIC_SPEAKERS:
            continue
        if name not in out:
            out.append(name)
    return out


def _name_patterns(names: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    pats: list[tuple[str, re.Pattern[str]]] = []
    seen: set[str] = set()
    for name in names:
        tokens = [name] + [t for t in name.split() if len(t) >= 3]
        for tok in tokens:
            if tok in seen:
                continue
            seen.add(tok)
            # case-sensitive: names are capitalized; avoids matching common words
            pats.append((name, re.compile(rf"(?<!\w){re.escape(tok)}(?!\w)")))
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
                    add(label, kind, text, m)
            for m in _PHONE.finditer(text):
                if sum(ch.isdigit() for ch in m.group(0)) >= 9:
                    add(label, "phone", text, m)
            for sentence in _SENTENCE_SPLIT.split(text):
                if _PERCENT.search(sentence) and _REVENUE_WORDS.search(sentence):
                    m = _PERCENT.search(sentence)
                    assert m is not None
                    add(label, "revenue_percentage", sentence, m)
            for name, pat in name_pats:
                m = pat.search(text)
                if m:
                    issues.append({"field": label, "kind": "participant_name", "match": name})
    # de-duplicate identical issues
    unique: list[dict[str, Any]] = []
    for issue in issues:
        if issue not in unique:
            unique.append(issue)
    return {"checked": True, "status": "issues" if unique else "clean", "issues": unique}
