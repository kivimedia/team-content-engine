"""The news block: stored on the packet, carried through every new version, shown
in the Doc with facts, reading and guesses kept apart."""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tce.editorial.packets import news_block_for
from tce.models.editorial import TopicCandidate
from tce.models.news import NewsAppraisal, NewsItem
from tce.production.export import news_blocks, packet_blocks

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 9, 22, 12, 0, 0)
SRC = Path(__file__).resolve().parents[2] / "src" / "tce"

BLOCK = {
    "what_happened": "Per-message billing replaces per-conversation billing.",
    "primary_url": "https://vendor.example/r/1",
    "publisher": "Vendor",
    "published_at": "2026-09-21T08:00:00",
    "expires_at": "2026-09-26T08:00:00",
    "confirmed_facts": [{"claim": "Pricing is retired", "quote": "pricing is retired"}],
    "ziv_interpretation": ["Owners will notice at the invoice."],
    "predictions": ["Sequence length becomes a cost decision."],
}


def _texts(blocks):
    return [(b.kind, b.text) for b in blocks]


# --- the Doc ------------------------------------------------------------------


def test_an_evergreen_packet_gets_no_news_section():
    assert news_blocks(None) == []
    assert news_blocks({}) == []


def test_the_three_lists_are_three_separate_headings_in_order():
    headings = [t for k, t in _texts(news_blocks(BLOCK)) if k == "heading"]
    assert headings == [
        "The news, before you record",
        "What is actually confirmed",
        "Your reading of it (say this as yours, not as fact)",
        "What you expect next (say this as a guess)",
    ]


def test_a_confirmed_fact_is_shown_with_its_quote():
    bullets = [t for k, t in _texts(news_blocks(BLOCK)) if k == "bullet"]
    assert 'Pricing is retired ("pricing is retired")' in bullets


def test_the_doc_carries_a_date_not_a_countdown():
    bodies = [t for k, t in _texts(news_blocks(BLOCK)) if k == "body"]
    assert "Worth saying until Saturday 26 September." in bodies
    assert any(b.startswith("Source: Vendor, Monday 21 September") for b in bodies)


def test_private_anchors_never_reach_the_shared_doc():
    """The Doc is shared with the team. Which call or commit earned the idea stays
    private, even if it somehow ended up in the block."""
    leaky = {**BLOCK, "anchors": [{"kind": "client_solution", "term": "PRIVATE CLIENT"}]}
    assert "PRIVATE CLIENT" not in " ".join(t for _k, t in _texts(news_blocks(leaky)))


def test_the_news_section_comes_before_the_bullets():
    packet = SimpleNamespace(
        version=2, bullets=["b1"], script_phrases=["p1"], facebook_post="",
        linkedin_post="", news_block=BLOCK,
    )
    headings = [b.text for b in packet_blocks(packet) if b.kind == "heading"]
    assert headings.index("The news, before you record") < headings.index("Walking bullets")


def test_an_evergreen_packets_doc_is_unchanged():
    packet = SimpleNamespace(
        version=1, bullets=["b1"], script_phrases=["p1"], facebook_post="",
        linkedin_post="", news_block=None,
    )
    headings = [b.text for b in packet_blocks(packet) if b.kind == "heading"]
    assert headings == ["Walking bullets", "Script, one phrase per line"]


# --- carried through every new version ----------------------------------------


def test_every_packet_clone_carries_the_news_block_forward():
    """Choosing another opening, asking for more, or a voice pass each make a new
    packet version by cloning. A clone that forgot these fields would silently drop
    the news block the first time he switched openings."""
    tree = ast.parse((SRC / "editorial" / "packets.py").read_text(encoding="utf-8"))
    constructions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RecordingPacket"
    ]
    assert len(constructions) >= 4, "fewer packet constructions than expected; update this test"
    for node in constructions:
        keywords = {kw.arg for kw in node.keywords}
        assert {"news_block", "format"} <= keywords, (
            f"RecordingPacket(...) at packets.py:{node.lineno} does not carry the news block"
        )


# --- built from the verified appraisal, nothing else --------------------------


async def _seed(session, verdict="publish"):
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="r1", url="https://vendor.example/r/1",
        title="Pricing moves", publisher="Vendor", published_at=NOW - timedelta(days=1),
        source_tier="1a",
    )
    session.add(item)
    session.add(
        NewsAppraisal(
            id=uuid.uuid4(), workspace_id=WS, news_item_id=item.id, verdict=verdict,
            what_happened="Per-message billing.", format="changes_my_product",
            confirmed_facts=BLOCK["confirmed_facts"], ziv_interpretation=["mine"],
            predictions=["guess"], expires_at=NOW + timedelta(days=4), anchors=[],
            scores={}, do_differently=[],
        )
    )
    cand = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[], title="t",
        lesson="l", audience="both", reasons_to_care=[], public_angle="a", gates={},
        news_item_id=item.id,
    )
    session.add(cand)
    await session.flush()
    return cand


@pytest.mark.asyncio
async def test_the_block_comes_from_the_published_appraisal(editorial_session):
    cand = await _seed(editorial_session)
    block, fmt = await news_block_for(editorial_session, WS, cand)
    assert fmt == "changes_my_product"
    assert block["confirmed_facts"] == BLOCK["confirmed_facts"]
    assert block["publisher"] == "Vendor"


@pytest.mark.asyncio
async def test_a_watched_appraisal_never_becomes_a_block(editorial_session):
    cand = await _seed(editorial_session, verdict="watch")
    assert await news_block_for(editorial_session, WS, cand) == (None, None)


@pytest.mark.asyncio
async def test_an_evergreen_candidate_has_no_block(editorial_session):
    cand = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[], title="t",
        lesson="l", audience="both", reasons_to_care=[], public_angle="a", gates={},
    )
    assert await news_block_for(editorial_session, WS, cand) == (None, None)
