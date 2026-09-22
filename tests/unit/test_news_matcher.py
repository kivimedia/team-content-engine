"""The test that proves the corporate-topic failure cannot come back.

TCE used to have a second topic source, `trend_scout`, whose hardcoded feeds were
TechCrunch funding and VentureBeat enterprise AI, whose ranking was Reddit
comments per hour, and whose prompt demanded "minimum 15, aim for 20-25" trends
per run. It was deleted on 21-Sep-2026. These tests are what stops its output
shape from returning through the new lane.

The assertion that matters is not "no candidate". It is **no candidate AND no
model call**. If a rejection required a model call, the gate would be the model's
judgement, and a model's judgement drifts between versions. The gate must be the
matcher, and the matcher must be deterministic.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from tce.news.matcher import blocked_shape, match_item

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "news"


def _load(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


NEGATIVES = _load("corporate_negatives.jsonl")
POSITIVES = _load("positives.jsonl")


@dataclass
class FakeAnchor:
    """Stands in for a NewsAnchor row without needing a database."""

    kind: str
    term: str
    weight: float = 1.0
    id: uuid.UUID = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = uuid.uuid4()

    @property
    def normalized_term(self) -> str:
        from tce.news.anchors import normalize

        return normalize(self.term)


# A stand-in for the real index: the shape it has in production, not its size.
# Deliberately includes things the negatives mention (Anthropic, OpenAI) so the
# negatives are rejected on SHAPE rather than on Ziv happening not to know the
# company. That is the harder and more honest test.
INDEX = [
    FakeAnchor("vendor", "anthropic"),
    FakeAnchor("vendor", "openai"),
    FakeAnchor("vendor", "twilio"),
    FakeAnchor("vendor", "stripe"),
    FakeAnchor("vendor", "supabase"),
    FakeAnchor("vendor", "vercel"),
    FakeAnchor("vendor", "whatsapp business"),
    FakeAnchor("vendor", "retell"),
    FakeAnchor("vendor", "fathom"),
    FakeAnchor("dependency", "kmhub", 0.9),
    FakeAnchor("dependency", "km-florist-receptionist", 1.0),
    FakeAnchor("dependency", "coach-crm", 0.5),
    FakeAnchor("model_id", "claude-opus-4-7"),
    FakeAnchor("model_id", "claude-sonnet-5"),
    FakeAnchor("capability", "prompt caching"),
    FakeAnchor("capability", "computer use"),
    FakeAnchor("capability", "model context protocol"),
    FakeAnchor("capability", "realtime voice"),
    FakeAnchor("client_solution", "an AI receptionist answering a shop's phone"),
    FakeAnchor("client_solution", "automated follow-up messaging to a client's leads"),
    FakeAnchor("problem_pattern", "leads come in, sit there, and nobody ever gets back to them"),
    FakeAnchor("problem_pattern", "they never go back to the people who already paid them"),
    FakeAnchor("problem_pattern", "they will not raise their price"),
    FakeAnchor("problem_pattern", "nobody picks up the phone once the office closes"),
]


# ---------------------------------------------------------------------------
# The headline test
# ---------------------------------------------------------------------------


def test_every_corporate_negative_is_rejected():
    """All 25, each with a specific reason. No exceptions, no near misses."""
    survivors = []
    for item in NEGATIVES:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=INDEX
        )
        if result.matched:
            survivors.append(f"{item['id']} ({item['shape']}): {item['title']}")
    assert not survivors, "corporate stories got through the gate:\n  " + "\n  ".join(
        survivors
    )


def test_rejecting_them_costs_no_model_call():
    """The gate is the matcher, not a model, so it cannot drift with a version.

    `match_item` is a pure function over the item and the index. If anyone ever
    makes it reach for an LLM, this import-level guarantee is the thing that
    should have to be deleted first, deliberately.
    """
    import ast
    import inspect

    from tce.news import matcher

    tree = ast.parse(inspect.getsource(matcher))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.startswith("tce."):
                imported.add(node.module)

    forbidden = {"httpx", "requests", "urllib", "anthropic", "openai", "tce.llm"}
    assert not (imported & forbidden), (
        f"the matcher imports {sorted(imported & forbidden)}; the gate must stay "
        "deterministic and offline, or it becomes a model's judgement that drifts"
    )


def test_each_negative_names_why_it_was_dropped():
    """A silent drop is indistinguishable from a broken feed."""
    for item in NEGATIVES:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=INDEX
        )
        assert result.reason, f"{item['id']} was dropped with no reason"
        assert result.reason != "unknown"


def test_the_shape_list_catches_what_it_claims_to():
    """Each shaped negative is caught by shape, not by accident of vocabulary."""
    shaped = [i for i in NEGATIVES if i["shape"] not in ("enterprise", "demo_hype")]
    for item in shaped:
        found = blocked_shape(f"{item['title']} {item.get('summary', '')}")
        assert found is not None, f"{item['id']} was not caught by any shape rule"


def test_enterprise_and_demo_items_are_dropped_by_the_anchor_rule():
    """Not every bad item has a tell in its wording.

    A ServiceNow platform launch is grammatically identical to a real release
    notice. Nothing catches it except that none of it is Ziv's, which is why the
    anchor requirement has to carry the load rather than the blocklist.
    """
    for item in [i for i in NEGATIVES if i["shape"] in ("enterprise", "demo_hype")]:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=INDEX
        )
        assert not result.matched
        assert result.blocked_shape is None, "expected the anchor rule, not the shape list"
        assert "anchor" in result.reason or "capability" in result.reason


# ---------------------------------------------------------------------------
# The positives, so the gate is not simply "reject everything"
# ---------------------------------------------------------------------------


def test_stack_relevant_announcements_qualify():
    missed = []
    for item in POSITIVES:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=INDEX
        )
        if not result.matched:
            missed.append(f"{item['id']}: {item['title']} -> {result.reason}")
    assert not missed, "real announcements were rejected:\n  " + "\n  ".join(missed)


def test_positives_qualify_for_the_stated_reason():
    for item in POSITIVES:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=INDEX
        )
        assert result.reason == item["expect"], (
            f"{item['id']} qualified via {result.reason!r}, expected {item['expect']!r}"
        )


def test_a_match_can_name_itself():
    """The recorder needs 'because your receptionist runs on this', not 'relevant'."""
    result = match_item(
        title="Twilio changes how programmable voice handles call forwarding",
        anchors=INDEX,
    )
    assert result.matched
    assert "twilio" in result.why().lower()


# ---------------------------------------------------------------------------
# The load-bearing properties
# ---------------------------------------------------------------------------


def test_an_empty_index_rejects_everything():
    """Proves the anchor requirement is load-bearing, not decorative."""
    for item in POSITIVES:
        result = match_item(
            title=item["title"], summary=item.get("summary"), anchors=[]
        )
        assert not result.matched
        assert result.reason in ("no anchor", "blocked shape: acquisition")


def test_stop_terms_alone_never_qualify():
    """The exact move that let the old system call anything relevant."""
    result = match_item(
        title="A new AI agent platform automates business workflows",
        summary="The automation tool uses an LLM model for data integration.",
        anchors=[
            FakeAnchor("capability", "ai"),
            FakeAnchor("dependency", "agent"),
            FakeAnchor("vendor", "automation"),
        ],
    )
    assert not result.matched
    assert result.reason == "no anchor"


def test_one_client_problem_is_not_enough():
    result = match_item(
        title=(
            "A tool for businesses where leads come in, sit there, and nobody "
            "ever gets back to them"
        ),
        anchors=INDEX,
    )
    assert not result.matched
    assert "single broad pattern" in result.reason


def test_two_client_problems_qualify():
    result = match_item(
        title="Re-engagement for dormant contacts",
        summary=(
            "For businesses where leads come in, sit there, and nobody ever gets back "
            "to them, and where they never go back to the people who already paid them."
        ),
        anchors=INDEX,
    )
    assert result.matched
    assert result.reason == "two independent client problems"


def test_a_capability_alone_is_not_a_connection():
    """'Prompt caching got cheaper' matters when it touches something he runs."""
    result = match_item(
        title="A guide to prompt caching",
        summary="How caching works in modern model APIs.",
        anchors=[FakeAnchor("capability", "prompt caching")],
    )
    assert not result.matched
    assert "capability" in result.reason


def test_a_vendor_he_uses_being_acquired_is_the_one_exception():
    """Blocked shape, rescued because it is a dependency changing hands."""
    result = match_item(
        title="Retell is being acquired and will sunset its current voice API",
        summary="Existing customers have ninety days to migrate.",
        anchors=INDEX,
    )
    assert result.matched, "a vendor he runs being switched off is a real consequence"


def test_an_unrelated_acquisition_stays_blocked():
    result = match_item(
        title="Figma acquires a design tooling startup",
        summary="Terms were not disclosed.",
        anchors=INDEX,
    )
    assert not result.matched
    assert result.blocked_shape == "acquisition"


def test_a_funding_round_mentioning_his_vendor_is_still_a_funding_round():
    """Shape beats anchor. Anthropic raising money changes nothing for a florist."""
    result = match_item(
        title="Anthropic raises $3.5 billion at a $61.5 billion valuation",
        anchors=INDEX,
    )
    assert not result.matched
    assert result.blocked_shape == "funding"


def test_substring_collisions_do_not_match():
    """'arc' inside 'search' is how a demo looks clever and production looks mad."""
    result = match_item(
        title="Improving search relevance with declarative configuration",
        anchors=[FakeAnchor("dependency", "arc"), FakeAnchor("vendor", "clara")],
    )
    assert not result.matched


@pytest.mark.parametrize("field", ["title", "summary", "body"])
def test_an_anchor_is_found_in_any_field(field):
    kwargs = {"title": "Something happened", "summary": None, "body": None}
    kwargs[field] = "Twilio changed programmable voice"
    result = match_item(anchors=INDEX, **kwargs)
    assert result.matched


def test_matching_is_deterministic():
    """Same inputs, same verdict, every time. No ordering or set iteration leaks."""
    first = match_item(
        title=POSITIVES[0]["title"], summary=POSITIVES[0]["summary"], anchors=INDEX
    )
    for _ in range(5):
        again = match_item(
            title=POSITIVES[0]["title"], summary=POSITIVES[0]["summary"], anchors=INDEX
        )
        assert again.matched == first.matched
        assert again.reason == first.reason
        assert [m.term for m in again.matches] == [m.term for m in first.matches]
