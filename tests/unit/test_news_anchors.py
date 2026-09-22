"""The anchor index is the gate, so it is tested like one.

The third lane's whole precision claim rests on this module: an announcement
reaches Ziv only by matching a row built here, and that decision is made with no
model call so it cannot drift between model versions. These tests pin the
properties that keep it honest.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import NewsAnchor
from tce.news.anchors import (
    STOP_TERMS,
    STRONG_KINDS,
    DerivedAnchor,
    build_anchor_index,
    model_ids_from_settings,
    normalize,
    parse_curated_file,
    repos_from_commit_evidence,
    tokens,
    vendors_from_settings,
)
from tce.news.standing import StandingFact, StandingFactRejected, seed_standing_facts

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 9, 21, 12, 0, 0)

HEBREW = "שיחה עם לקוח"
MIXED = "article - ישראל היום"


# ---------------------------------------------------------------------------
# Normalisation: the bug that has already cost this stack real time
# ---------------------------------------------------------------------------


def test_hebrew_survives_normalisation():
    """An ASCII normaliser empties this, which reads downstream as 'absent'."""
    out = normalize(HEBREW)
    assert out, "Hebrew normalised to nothing; the anchor would read as absent"
    assert len(out.split()) == 3


def test_mixed_script_keeps_both_halves():
    """A Latin-only fold collapses this to 'article' and matches the wrong thing."""
    out = normalize(MIXED)
    assert out.startswith("article")
    assert out != "article", "the Hebrew half was dropped"
    assert len(out.split()) == 3


def test_normalisation_is_idempotent_and_case_folded():
    assert normalize("Claude-Opus-5 / MCP!") == "claude opus 5 mcp"
    assert normalize(normalize("Claude-Opus-5")) == normalize("Claude-Opus-5")
    assert normalize(None) == ""
    assert tokens("  a--b  ") == {"a", "b"}


# ---------------------------------------------------------------------------
# What may and may not become an anchor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("term", sorted(STOP_TERMS)[:8])
def test_a_bare_stop_word_is_never_an_anchor(term):
    """Matching on the category name is a coincidence, not a connection."""
    assert not DerivedAnchor("capability", term, "manual").usable()


def test_a_phrase_containing_a_stop_word_is_fine():
    """'prompt caching' earns its place even though 'caching' alone would not."""
    assert DerivedAnchor("capability", "ai gateway pricing", "manual").usable()
    assert DerivedAnchor("capability", "prompt caching", "manual").usable()


@pytest.mark.parametrize(
    ("kind", "term"), [("vendor", "search"), ("dependency", "boards"), ("dependency", "clara")]
)
def test_his_names_that_are_ordinary_words_are_not_anchors(kind, term):
    """Found in the first production dry run: these would match Pinterest boards."""
    assert not DerivedAnchor(kind, term, "env").usable()


def test_very_short_terms_are_rejected():
    assert not DerivedAnchor("vendor", "ab", "manual").usable()


def test_unknown_kind_or_origin_is_a_programming_error():
    with pytest.raises(ValueError):
        DerivedAnchor("nonsense", "a term", "manual")
    with pytest.raises(ValueError):
        DerivedAnchor("vendor", "a term", "nonsense")


def test_problem_pattern_is_not_a_strong_kind():
    """One problem pattern must never qualify an item on its own (phase 3 needs two)."""
    assert "problem_pattern" not in STRONG_KINDS
    assert {"vendor", "dependency", "model_id", "client_solution"} == set(STRONG_KINDS)


# ---------------------------------------------------------------------------
# Derivation from things TCE already has
# ---------------------------------------------------------------------------


class _FakeSettings:
    model_fields = {
        "fathom_api_key": None,
        "github_pat": None,
        "elevenlabs_api_key": None,
        "default_model": None,
        "opus_model": None,
        "news_lane": None,
    }
    fathom_api_key = "secret"
    elevenlabs_api_key = "secret"
    default_model = "claude-sonnet-5"
    opus_model = "claude-opus-4-7"
    news_lane = False


def test_vendors_come_from_env_key_names_not_values():
    anchors = vendors_from_settings(_FakeSettings())
    terms = {a.normalized for a in anchors}
    assert "fathom" in terms
    assert "elevenlabs" in terms
    assert all(a.kind == "vendor" and a.origin_kind == "env" for a in anchors)
    # The secret itself must never become an anchor term.
    assert not any("secret" in a.normalized for a in anchors)


def test_model_ids_are_picked_up_for_deprecation_notices():
    anchors = model_ids_from_settings(_FakeSettings())
    terms = {a.normalized for a in anchors}
    assert "claude sonnet 5" in terms
    assert "claude opus 4 7" in terms


def test_curated_file_parses_kinds_and_ignores_prose(tmp_path):
    path = tmp_path / "news-anchors.md"
    path.write_text(
        "# Title\n\nSome prose that is not a term.\n\n"
        "## capability\n- prompt caching\n- computer use  # why it is here\n\n"
        "## vendor\n- twilio\n\n"
        "## not_a_kind\n- should be ignored\n",
        encoding="utf-8",
    )
    anchors = parse_curated_file(path)
    by_kind = {(a.kind, a.normalized) for a in anchors}
    assert ("capability", "prompt caching") in by_kind
    assert ("capability", "computer use") in by_kind, "trailing comment broke the term"
    assert ("vendor", "twilio") in by_kind
    assert not [a for a in anchors if "ignored" in a.normalized]


def test_missing_curated_file_is_not_an_error(tmp_path):
    assert parse_curated_file(tmp_path / "absent.md") == []


@pytest.mark.asyncio
async def test_repos_come_from_recent_commit_evidence_and_are_weighted(editorial_session):
    async def add_commit_group(repo: str, when: datetime, n: int) -> None:
        for i in range(n):
            editorial_session.add(
                EvidenceSource(
                    id=uuid.uuid4(),
                    workspace_id=WS,
                    source_kind="github_commit_group",
                    external_id=f"{repo}@{when.date()}#{i}",
                    version_hash=f"h{repo}{i}",
                    occurred_at=when,
                    payload_private={"repo": repo, "commits": []},
                )
            )

    await add_commit_group("kivimedia/busy-repo", NOW - timedelta(days=5), 4)
    await add_commit_group("kivimedia/quiet-repo", NOW - timedelta(days=5), 1)
    await add_commit_group("kivimedia/abandoned-repo", NOW - timedelta(days=400), 9)
    await editorial_session.flush()

    anchors = await repos_from_commit_evidence(editorial_session, WS, now=NOW)
    by_term = {a.normalized: a for a in anchors}

    assert "abandoned repo" not in by_term, "a repo untouched for a year still pulled news"
    assert by_term["busy repo"].weight > by_term["quiet repo"].weight
    assert by_term["quiet repo"].weight >= 0.4, "a quiet repo should still count"
    assert by_term["busy repo"].origin_ref == "kivimedia/busy-repo"


# ---------------------------------------------------------------------------
# Standing facts: the constraints are the feature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standing_facts_are_written_and_are_citable(editorial_session):
    facts = [
        StandingFact(
            "client_solution",
            "an AI receptionist answering a shop's phone",
            "Kivi Media runs voice reception for small shops.",
        ),
        StandingFact(
            "problem_pattern",
            "they will not raise their price",
            "A stuck number, often years old.",
        ),
    ]
    result = await seed_standing_facts(editorial_session, WS, facts, now=NOW)
    assert result["written"] == 2

    moments = (
        (
            await editorial_session.execute(
                select(EvidenceMoment).where(EvidenceMoment.workspace_id == WS)
            )
        )
        .scalars()
        .all()
    )
    assert len(moments) == 2
    for moment in moments:
        # The constraint that keeps this honest: no model wrote it.
        assert moment.extraction_job_id is None
        assert moment.news_ref["standing"] is True
        assert moment.news_ref["anchor_kind"] in ("client_solution", "problem_pattern")
    # A standing fact can never support an outcome claim.
    assert {m.claim_type for m in moments} == {"demonstrated", "paraphrased"}
    assert "measured" not in {m.claim_type for m in moments}


@pytest.mark.asyncio
async def test_a_standing_fact_naming_a_person_is_refused(editorial_session):
    """Caught when it is typed, not three steps later inside a public draft."""
    with pytest.raises(StandingFactRejected) as err:
        await seed_standing_facts(
            editorial_session,
            WS,
            [
                StandingFact(
                    "client_solution",
                    "a receptionist for ziv@kivimedia.co",
                    "Runs the phone.",
                )
            ],
            now=NOW,
        )
    assert "categories" in str(err.value)


@pytest.mark.asyncio
async def test_seeding_twice_with_the_same_list_changes_nothing(editorial_session):
    facts = [StandingFact("problem_pattern", "leads go cold", "Nobody follows up.")]
    first = await seed_standing_facts(editorial_session, WS, facts, now=NOW)
    second = await seed_standing_facts(editorial_session, WS, facts, now=NOW)
    assert first["written"] == 1
    assert second["unchanged"] is True
    assert second["written"] == 0


@pytest.mark.asyncio
async def test_a_corrected_list_retires_the_old_one_without_deleting_it(editorial_session):
    await seed_standing_facts(
        editorial_session,
        WS,
        [StandingFact("problem_pattern", "leads go cold", "Nobody follows up.")],
        now=NOW,
    )
    result = await seed_standing_facts(
        editorial_session,
        WS,
        [StandingFact("problem_pattern", "leads go cold and nobody chases them", "Reworded.")],
        now=NOW,
    )
    assert result["retired"] == 1
    statuses = {
        m.status
        for m in (
            await editorial_session.execute(
                select(EvidenceMoment).where(EvidenceMoment.workspace_id == WS)
            )
        )
        .scalars()
        .all()
    }
    assert statuses == {"active", "stale"}, "the old wording was deleted instead of retired"


@pytest.mark.asyncio
async def test_the_same_anchor_twice_is_refused(editorial_session):
    with pytest.raises(StandingFactRejected):
        await seed_standing_facts(
            editorial_session,
            WS,
            [
                StandingFact("problem_pattern", "leads go cold", "a"),
                StandingFact("problem_pattern", "Leads  go  COLD", "b"),
            ],
            now=NOW,
        )


# ---------------------------------------------------------------------------
# The build itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(editorial_session, tmp_path):
    curated = tmp_path / "a.md"
    curated.write_text("## capability\n- prompt caching\n", encoding="utf-8")
    result, anchors = await build_anchor_index(
        editorial_session,
        WS,
        settings_obj=_FakeSettings(),
        curated_path=curated,
        dry_run=True,
        now=NOW,
    )
    assert result.dry_run is True
    assert anchors, "a dry run should still show what it would build"
    rows = (
        (await editorial_session.execute(select(NewsAnchor))).scalars().all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_build_is_idempotent_and_retires_vanished_anchors(editorial_session, tmp_path):
    curated = tmp_path / "a.md"
    curated.write_text("## capability\n- prompt caching\n- computer use\n", encoding="utf-8")

    first, _ = await build_anchor_index(
        editorial_session, WS, settings_obj=_FakeSettings(), curated_path=curated, now=NOW
    )
    assert first.created > 0

    second, _ = await build_anchor_index(
        editorial_session, WS, settings_obj=_FakeSettings(), curated_path=curated, now=NOW
    )
    assert second.created == 0, "a second run created duplicate anchors"
    assert second.updated > 0

    # Drop one term from the curated file: it should be deactivated, not deleted.
    curated.write_text("## capability\n- prompt caching\n", encoding="utf-8")
    third, _ = await build_anchor_index(
        editorial_session, WS, settings_obj=_FakeSettings(), curated_path=curated, now=NOW
    )
    assert third.deactivated == 1

    gone = (
        (
            await editorial_session.execute(
                select(NewsAnchor).where(NewsAnchor.normalized_term == "computer use")
            )
        )
        .scalars()
        .one()
    )
    assert gone.active is False, "a vanished anchor was deleted instead of deactivated"


@pytest.mark.asyncio
async def test_standing_facts_become_citable_anchors(editorial_session, tmp_path):
    """The point of standing facts: the anchor carries the moment that proves it."""
    curated = tmp_path / "a.md"
    curated.write_text("## capability\n- prompt caching\n", encoding="utf-8")
    await seed_standing_facts(
        editorial_session,
        WS,
        [
            StandingFact(
                "client_solution",
                "an AI receptionist answering a shop's phone",
                "Kivi Media runs voice reception for small shops.",
            )
        ],
        now=NOW,
    )
    await build_anchor_index(
        editorial_session, WS, settings_obj=_FakeSettings(), curated_path=curated, now=NOW
    )

    anchor = (
        (
            await editorial_session.execute(
                select(NewsAnchor).where(NewsAnchor.kind == "client_solution")
            )
        )
        .scalars()
        .one()
    )
    assert anchor.standing_moment_id is not None, (
        "a client_solution anchor with no citable moment cannot satisfy the "
        "non-news citation rule, which is the rule the lane rests on"
    )
    moment = await editorial_session.get(EvidenceMoment, anchor.standing_moment_id)
    assert moment is not None and moment.status == "active"
