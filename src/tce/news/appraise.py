"""Stage B: the eight questions, asked once, for an item that already matched.

This is the only place in the third lane that spends a model call, and it runs
only on items the deterministic matcher already let through. On a quiet day it
never runs at all, which is what makes daily discovery honest.

The prompt's job is not to find relevance - the matcher already did that, and the
anchors it found are handed over as facts rather than as a question. The prompt's
job is to decide whether Ziv has something to SAY, and to be willing to answer
no. `watch` and `reject` are first-class verdicts and the schema makes them as
easy to return as `publish`.

Three things are kept structurally apart rather than stylistically:
confirmed_facts (quoted from the announcement), ziv_interpretation (his reading)
and predictions (what he thinks happens next). A test asserts no string appears
in more than one list, because "separate them in the writing" is an instruction a
model can drift from and a column is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from tce.models.news import (
    NEWS_FORMATS,
    PERISHABILITY,
    STORY_WEIGHTS,
    VERDICTS,
)

PROMPT_VERSION = "news_appraisal.v1"
JOB_TYPE = "news_appraisal"
AGENT_NAME = "news_appraiser"

# How long a claim stays worth saying. `durable` is the confession that it was
# never news: the caller converts it to an ordinary evergreen idea instead.
EXPIRY_DAYS: dict[str, int | None] = {
    "hours": 2,
    "days": 5,
    "week": 10,
    "month": 35,
    "durable": None,
}

# Excerpt caps. The primary document is the evidence, but a 40k changelog would
# crowd out the anchors, which are the part the model most needs to see.
MAX_DOC_CHARS = 12000
MAX_ANCHOR_EXCERPT = 400

SYSTEM_PROMPT = """You are Ziv Raviv's editor, deciding whether an outside change is worth him
saying anything about.

Ziv is a business coach for independent coaches first, and for owner-led service businesses in the
events world second (entertainers, DJs, AV, decor, florals, venues). He also builds and runs AI
agent systems for those clients. He is not an AI commentator and has no interest in being one.

SOMETHING ALREADY MATCHED. You are shown the anchors that matched: repos he runs, systems Kivi
Media runs for clients, vendors he pays for, or recurring problems his clients keep bringing. That
part is settled and is not your decision. Your decision is whether he has something USEFUL AND
CREDIBLE to say.

Answer no when the honest answer is no. A verdict of "watch" (real, but nothing changes for his
audience yet) or "reject" is a good outcome and is expected most of the time. Do not reach.

THE RULES, IN ORDER OF HOW OFTEN THEY DECIDE IT

1. The announcement is never the idea. The idea is what Ziv did, changed or decided because of it.
If you cannot say what he would DO, reject.

2. A reader must be able to act this month. "Understand better" is not acting. If your
do_differently list is vague, the verdict is reject, not a vaguer list.

3. He must be able to say something a person who read the same announcement could not work out for
themselves. That comes from running these systems for real businesses. If anyone with the link
could write it, reject.

4. Confirmed facts must be QUOTED from the document you are given. If the document does not say
it, it is not a confirmed fact. Put your reading in ziv_interpretation and what you think happens
next in predictions. Never mix them.

5. Enterprise is out of scope. If the affected party has a procurement department, it is not for
this audience.

6. No manufactured urgency. No "before everyone else", no "the window is closing", no countdown.
If the story only works with urgency, reject.

7. Never invent an outcome. You may not claim anyone saved money, gained clients or saved time.
Nothing here measures anything.

8. Never name a client, a company he works for, or a money figure from his business.

CHOOSING A FORMAT

changes_my_product: it changes something in a product or repo he runs.
i_tested_it: ONLY if the evidence shows he actually ran it AFTER the announcement. Never choose
this on the strength of the announcement alone. If unsure, choose three_things_id_test.
solves_a_client_problem: a problem from a recent call.
coaches_will_misread_this: there is a specific, nameable misreading.
impressive_but_not_the_problem: name the small-business problem it does NOT solve.
changes_how_i_manage_agents: it changes how he runs his fleet.
three_things_id_test: the honest default when he has not run it yet.
without_an_engineering_team: what an owner with no developer should do.

HOW FAST IT GOES STALE

hours: an outage or a pulled release. days: a launch everyone will cover. week: a pricing change
taking effect. month: a deprecation with a dated deadline. durable: it is not news at all and the
lesson would be just as true next year - say so honestly, it is a useful answer.

HOW BIG A STORY IT IS

"major" only if at least one is true, and weight_reason must say which:
 - it touches two or more of his products, repos or client systems (count them from
   the anchors given, do not assert it),
 - it carries a dated deadline someone has to act on,
 - consequence and distinctiveness are both 5.

Otherwise "small". Most stories are small.

SCORING, 0 to 5

owner_relevance: would a coach or event-business owner care this month?
consequence_specificity: how concrete is the thing to do differently? 5 means a named action; 1
means "keep an eye on it".
distinctiveness: how much does this need HIS experience? 5 means only someone running these
systems could say it; 1 means anyone could.

Return JSON only."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "verdict",
        "verdict_reason",
        "what_happened",
        "audience_consequence",
        "distinct_claim",
        "do_differently",
        "confirmed_facts",
        "ziv_interpretation",
        "predictions",
        "format",
        "perishability",
        "story_weight",
        "weight_reason",
        "scores",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "verdict_reason": {"type": "string"},
        "what_happened": {"type": "string"},
        "audience_consequence": {"type": "string"},
        "distinct_claim": {"type": "string"},
        "do_differently": {"type": "array", "items": {"type": "string"}},
        "confirmed_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "quote"],
                "properties": {
                    "claim": {"type": "string"},
                    "quote": {
                        "type": "string",
                        "description": "verbatim from the document, so it can be checked",
                    },
                },
            },
        },
        "ziv_interpretation": {"type": "array", "items": {"type": "string"}},
        "predictions": {"type": "array", "items": {"type": "string"}},
        "format": {"type": "string", "enum": list(NEWS_FORMATS)},
        "perishability": {"type": "string", "enum": list(PERISHABILITY)},
        "story_weight": {"type": "string", "enum": list(STORY_WEIGHTS)},
        "weight_reason": {"type": "string"},
        "anchors_used": {"type": "array", "items": {"type": "string"}},
        "scores": {
            "type": "object",
            "required": [
                "owner_relevance",
                "consequence_specificity",
                "distinctiveness",
            ],
            "properties": {
                "owner_relevance": {"type": "number"},
                "consequence_specificity": {"type": "number"},
                "distinctiveness": {"type": "number"},
            },
        },
    },
}


class AppraisalInvalidError(ValueError):
    """The model's answer cannot be stored, with the reason."""


@dataclass(frozen=True)
class AppraisalInput:
    """Everything the appraiser is allowed to see."""

    title: str
    publisher: str | None
    published_at: datetime | None
    primary_url: str | None
    document: str
    anchors: list[dict[str, Any]]
    recent_evidence: list[dict[str, Any]]


def build_prompt(data: AppraisalInput) -> str:
    """The user message. The anchors arrive as findings, not as a question."""
    when = data.published_at.strftime("%Y-%m-%d") if data.published_at else "unknown date"
    lines = [
        f"ANNOUNCEMENT: {data.title}",
        f"PUBLISHER: {data.publisher or 'unknown'}",
        f"PUBLISHED: {when}",
        f"PRIMARY SOURCE: {data.primary_url or '(none captured)'}",
        "",
        "WHAT IT MATCHED IN HIS WORK (already established, not your decision):",
    ]
    if data.anchors:
        for anchor in data.anchors:
            kind = anchor.get("kind", "?")
            term = anchor.get("term", "?")
            where = anchor.get("origin_ref") or anchor.get("origin_kind") or ""
            lines.append(f"  - [{kind}] {term}" + (f"  (from {where})" if where else ""))
    else:  # pragma: no cover - the matcher does not pass unmatched items here
        lines.append("  (none, which should not happen; reject)")

    if data.recent_evidence:
        lines += [
            "",
            "FROM HIS RECENT CALLS AND COMMITS (private; for judging what he can say,",
            "never to quote in public):",
        ]
        for item in data.recent_evidence:
            occurred = item.get("occurred_at") or "?"
            kind = item.get("source_kind", "?")
            claim = item.get("claim_type", "?")
            summary = str(item.get("lesson_summary", ""))[:MAX_ANCHOR_EXCERPT]
            lines.append(f"  - [{kind} {occurred} / {claim}] {summary}")
    else:
        lines += [
            "",
            "FROM HIS RECENT CALLS AND COMMITS: nothing in the window.",
            "He has not touched this recently, so 'i_tested_it' is not available.",
        ]

    document = data.document or ""
    truncated = len(document) > MAX_DOC_CHARS
    lines += [
        "",
        "THE ANNOUNCEMENT ITSELF (quote confirmed facts from here, and only here):",
        document[:MAX_DOC_CHARS] + ("\n[truncated]" if truncated else ""),
    ]
    return "\n".join(lines)


def expires_at(
    perishability: str, published_at: datetime | None, *, now: datetime
) -> datetime | None:
    """When the claim stops being worth saying.

    Measured from publication, not from appraisal: an announcement found three
    days late is already three days stale, and pretending otherwise would give
    the freshness term in the score a number it has not earned.
    """
    days = EXPIRY_DAYS.get(perishability)
    if days is None:
        return None
    start = published_at or now
    return start + timedelta(days=days)


def _clean_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text[:600])
    return out[:limit]


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(5.0, number))


def validate_appraisal(
    data: Any,
    *,
    document: str,
    has_post_announcement_demonstration: bool,
    now: datetime | None = None,
    published_at: datetime | None = None,
) -> dict[str, Any]:
    """Turn the model's answer into a row, or refuse it with a reason.

    Everything checkable is checked in code rather than trusted to the prompt.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(data, dict):
        raise AppraisalInvalidError("the appraiser did not return an object")

    verdict = str(data.get("verdict", "")).strip()
    if verdict not in VERDICTS:
        raise AppraisalInvalidError(f"verdict must be one of {VERDICTS}, got {verdict!r}")

    out: dict[str, Any] = {
        "verdict": verdict,
        "verdict_reason": str(data.get("verdict_reason", "")).strip()[:2000],
        "what_happened": str(data.get("what_happened", "")).strip()[:2000],
        "audience_consequence": str(data.get("audience_consequence", "")).strip()[:2000],
        "distinct_claim": str(data.get("distinct_claim", "")).strip()[:2000],
        "do_differently": _clean_list(data.get("do_differently")),
        "ziv_interpretation": _clean_list(data.get("ziv_interpretation")),
        "predictions": _clean_list(data.get("predictions")),
    }

    if verdict != "publish":
        # Nothing below matters for a watch or a reject, and demanding a full
        # answer for one is how a model gets pushed into inventing a story.
        out.update(
            {
                "confirmed_facts": [],
                "format": None,
                "perishability": None,
                "expires_at": None,
                "story_weight": "small",
                "weight_reason": None,
                "scores": {},
            }
        )
        if not out["verdict_reason"]:
            raise AppraisalInvalidError(f"a {verdict} verdict must say why")
        return out

    # --- publish: every claim has to survive a check ---------------------
    facts = []
    haystack = (document or "").casefold()
    for entry in data.get("confirmed_facts") or []:
        if not isinstance(entry, dict):
            continue
        claim = str(entry.get("claim", "")).strip()
        quote = str(entry.get("quote", "")).strip()
        if not claim or not quote:
            continue
        # The quote must actually be in the document. A confirmed fact that is
        # not in the source is the single most damaging thing this lane could
        # produce, so it is dropped rather than softened.
        if quote.casefold() not in haystack:
            continue
        facts.append({"claim": claim[:600], "quote": quote[:600]})
    if not facts:
        raise AppraisalInvalidError(
            "no confirmed fact could be verified against the document; a publish "
            "verdict needs at least one quote that is really there"
        )
    out["confirmed_facts"] = facts[:8]

    fmt = str(data.get("format", "")).strip()
    if fmt not in NEWS_FORMATS:
        raise AppraisalInvalidError(f"format must be one of {NEWS_FORMATS}, got {fmt!r}")
    if fmt == "i_tested_it" and not has_post_announcement_demonstration:
        # The most valuable format and the easiest to fake. Downgraded rather
        # than rejected: the honest version of the same idea is still useful.
        fmt = "three_things_id_test"
        out["verdict_reason"] = (
            out["verdict_reason"]
            + " [format downgraded: no demonstrated evidence dated after the announcement]"
        ).strip()
    out["format"] = fmt

    perishability = str(data.get("perishability", "")).strip()
    if perishability not in PERISHABILITY:
        raise AppraisalInvalidError(
            f"perishability must be one of {PERISHABILITY}, got {perishability!r}"
        )
    out["perishability"] = perishability
    out["expires_at"] = expires_at(perishability, published_at, now=now)

    weight = str(data.get("story_weight", "small")).strip()
    if weight not in STORY_WEIGHTS:
        weight = "small"
    reason = str(data.get("weight_reason", "")).strip()
    if weight == "major" and not reason:
        # "Major" opens a second news slot in a week. It must name its test.
        weight = "small"
        reason = "downgraded: major was claimed with no reason given"
    out["story_weight"] = weight
    out["weight_reason"] = reason[:1000] or None

    scores = data.get("scores") or {}
    out["scores"] = {
        "owner_relevance": _score(scores.get("owner_relevance")),
        "consequence_specificity": _score(scores.get("consequence_specificity")),
        "distinctiveness": _score(scores.get("distinctiveness")),
    }

    if not out["do_differently"]:
        raise AppraisalInvalidError(
            "a publish verdict with nothing to do differently is a summary, not an idea"
        )

    overlap = _overlapping(out)
    if overlap:
        raise AppraisalInvalidError(
            "the same statement appears as both a confirmed fact and an opinion: "
            + "; ".join(overlap[:3])
        )

    return out


def _overlapping(out: dict[str, Any]) -> list[str]:
    """Facts, interpretation and prediction must not be the same sentence.

    Keeping them in three columns is only worth anything if nothing is in two of
    them, which a model will do when it is pleased with a line.
    """
    def norm(text: str) -> str:
        return " ".join(str(text).casefold().split())

    facts = {norm(f["claim"]) for f in out.get("confirmed_facts", [])}
    interpretation = {norm(i) for i in out.get("ziv_interpretation", [])}
    predictions = {norm(p) for p in out.get("predictions", [])}

    clashes = []
    for label, left, right in (
        ("fact/interpretation", facts, interpretation),
        ("fact/prediction", facts, predictions),
        ("interpretation/prediction", interpretation, predictions),
    ):
        for shared in left & right:
            clashes.append(f"{label}: {shared[:80]}")
    return clashes


def build_request(
    data: AppraisalInput,
    *,
    workspace_id: uuid.UUID,
    news_item_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
) -> Any:
    """One subscription job. Never a metered client: `tce.llm` enforces that."""
    from tce.llm import LLMRequest

    return LLMRequest(
        job_type=JOB_TYPE,
        agent_name=AGENT_NAME,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(data)}],
        output_schema=OUTPUT_SCHEMA,
        max_tokens=4096,
        prompt_version=PROMPT_VERSION,
        workspace_id=workspace_id,
        run_id=run_id,
        idempotency_key=f"news_appraisal:{workspace_id}:{news_item_id}:{PROMPT_VERSION}",
    )


# The N818 suffix is the lint rule; the short name is what reads in a traceback.
AppraisalInvalid = AppraisalInvalidError
