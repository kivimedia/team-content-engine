"""The appraiser's checks, which are in code because a prompt can drift.

Everything here is about what happens to the model's ANSWER. The prompt asks for
quoted facts, three separated lists and an honest verdict; these tests are what
makes those requirements real rather than requests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.news.appraise import (
    JOB_TYPE,
    OUTPUT_SCHEMA,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    AppraisalInput,
    AppraisalInvalid,
    build_prompt,
    build_request,
    expires_at,
    validate_appraisal,
)

NOW = datetime(2026, 9, 22, 9, 0, 0)
PUBLISHED = datetime(2026, 9, 20, 8, 0, 0)
WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")

DOCUMENT = (
    "Starting 1 January 2027, conversation-based pricing is retired and every "
    "template message is billed individually. Businesses running automated "
    "follow-up sequences should review their monthly volumes."
)


def good(**over) -> dict:
    base = {
        "verdict": "publish",
        "verdict_reason": "It changes a bill for shops we run messaging for.",
        "what_happened": "Per-message billing replaces per-conversation billing.",
        "audience_consequence": "An owner with automated follow-up pays differently.",
        "distinct_claim": "I run these sequences for shops and can say what it does to them.",
        "do_differently": ["Count the template messages each sequence sends per customer."],
        "confirmed_facts": [
            {
                "claim": "Conversation pricing is retired",
                "quote": "conversation-based pricing is retired",
            }
        ],
        "ziv_interpretation": ["Most owners will not notice until the bill arrives."],
        "predictions": ["Sequence length becomes a cost decision."],
        "format": "changes_my_product",
        "perishability": "month",
        "story_weight": "small",
        "weight_reason": "",
        "scores": {
            "owner_relevance": 5,
            "consequence_specificity": 4,
            "distinctiveness": 4,
        },
    }
    base.update(over)
    return base


def validate(data, **kw):
    kw.setdefault("document", DOCUMENT)
    kw.setdefault("has_post_announcement_demonstration", False)
    kw.setdefault("now", NOW)
    kw.setdefault("published_at", PUBLISHED)
    return validate_appraisal(data, **kw)


# ---------------------------------------------------------------------------
# A confirmed fact has to be in the document
# ---------------------------------------------------------------------------


def test_a_quoted_fact_that_is_really_there_is_kept():
    out = validate(good())
    assert out["confirmed_facts"][0]["quote"] == "conversation-based pricing is retired"


def test_a_fact_the_document_does_not_contain_is_dropped():
    """The most damaging thing this lane could produce, so it is dropped."""
    with pytest.raises(AppraisalInvalid) as err:
        validate(
            good(
                confirmed_facts=[
                    {"claim": "Prices double", "quote": "prices will double in every region"}
                ]
            )
        )
    assert "could be verified" in str(err.value)


def test_quote_matching_ignores_case_but_not_content():
    out = validate(
        good(
            confirmed_facts=[
                {"claim": "Retired", "quote": "Conversation-Based Pricing Is Retired"}
            ]
        )
    )
    assert len(out["confirmed_facts"]) == 1


def test_publish_with_no_verifiable_fact_is_refused():
    with pytest.raises(AppraisalInvalid):
        validate(good(confirmed_facts=[]))


# ---------------------------------------------------------------------------
# The three lists stay three lists
# ---------------------------------------------------------------------------


def test_the_same_sentence_cannot_be_a_fact_and_an_opinion():
    with pytest.raises(AppraisalInvalid) as err:
        validate(
            good(
                ziv_interpretation=["Conversation pricing is retired"],
            )
        )
    assert "both a confirmed fact and an opinion" in str(err.value)


def test_the_same_sentence_cannot_be_interpretation_and_prediction():
    with pytest.raises(AppraisalInvalid):
        validate(
            good(
                ziv_interpretation=["Sequence length becomes a cost decision"],
                predictions=["sequence length becomes a cost decision"],
            )
        )


def test_distinct_lists_are_fine():
    out = validate(good())
    assert out["ziv_interpretation"] and out["predictions"]
    assert out["ziv_interpretation"] != out["predictions"]


# ---------------------------------------------------------------------------
# "I tested it" is the format that can be faked
# ---------------------------------------------------------------------------


def test_i_tested_it_is_downgraded_without_a_demonstration():
    out = validate(good(format="i_tested_it"), has_post_announcement_demonstration=False)
    assert out["format"] == "three_things_id_test"
    assert "downgraded" in out["verdict_reason"]


def test_i_tested_it_survives_when_he_really_ran_it():
    out = validate(good(format="i_tested_it"), has_post_announcement_demonstration=True)
    assert out["format"] == "i_tested_it"


def test_an_unknown_format_is_refused():
    with pytest.raises(AppraisalInvalid):
        validate(good(format="hot_take"))


# ---------------------------------------------------------------------------
# Verdicts other than publish are first-class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["watch", "reject"])
def test_a_watch_or_reject_needs_only_a_reason(verdict):
    out = validate(
        {
            "verdict": verdict,
            "verdict_reason": "Real, but nothing changes for his audience yet.",
            "what_happened": "A capability was added.",
            "audience_consequence": "",
            "distinct_claim": "",
            "do_differently": [],
            "confirmed_facts": [],
            "ziv_interpretation": [],
            "predictions": [],
        }
    )
    assert out["verdict"] == verdict
    assert out["format"] is None
    assert out["expires_at"] is None


def test_a_verdict_with_no_reason_is_refused():
    with pytest.raises(AppraisalInvalid):
        validate({"verdict": "reject", "verdict_reason": "  "})


def test_an_unknown_verdict_is_refused():
    with pytest.raises(AppraisalInvalid):
        validate(good(verdict="maybe"))


def test_publish_with_nothing_to_do_is_a_summary_not_an_idea():
    with pytest.raises(AppraisalInvalid) as err:
        validate(good(do_differently=[]))
    assert "summary, not an idea" in str(err.value)


# ---------------------------------------------------------------------------
# Perishability and story weight
# ---------------------------------------------------------------------------


def test_expiry_is_measured_from_publication_not_from_appraisal():
    """An item found three days late is already three days stale."""
    when = expires_at("days", PUBLISHED, now=NOW)
    assert when == datetime(2026, 9, 25, 8, 0, 0)
    assert when < NOW.replace(day=26)


def test_durable_has_no_expiry_because_it_is_not_news():
    assert expires_at("durable", PUBLISHED, now=NOW) is None
    out = validate(good(perishability="durable"))
    assert out["expires_at"] is None
    assert out["perishability"] == "durable"


def test_an_unknown_perishability_is_refused():
    with pytest.raises(AppraisalInvalid):
        validate(good(perishability="eventually"))


def test_major_without_a_reason_is_downgraded_not_trusted():
    """Major opens a second news slot in a week, so it must name its test."""
    out = validate(good(story_weight="major", weight_reason=""))
    assert out["story_weight"] == "small"
    assert "no reason given" in out["weight_reason"]


def test_major_with_a_reason_is_kept():
    out = validate(
        good(story_weight="major", weight_reason="Touches the receptionist and the coaching CRM.")
    )
    assert out["story_weight"] == "major"


def test_scores_are_clamped_to_the_stated_range():
    out = validate(
        good(scores={"owner_relevance": 99, "consequence_specificity": -4,
                     "distinctiveness": "nonsense"})
    )
    assert out["scores"] == {
        "owner_relevance": 5.0,
        "consequence_specificity": 0.0,
        "distinctiveness": 0.0,
    }


# ---------------------------------------------------------------------------
# The prompt and the request
# ---------------------------------------------------------------------------


def _input(**over) -> AppraisalInput:
    base = dict(
        title="WhatsApp Business Platform moves to per-message pricing",
        publisher="Meta",
        published_at=PUBLISHED,
        primary_url="https://developers.example/changelog/pricing",
        document=DOCUMENT,
        anchors=[
            {"kind": "vendor", "term": "whatsapp business", "origin_ref": "settings"},
            {
                "kind": "client_solution",
                "term": "automated follow-up messaging to a client's leads",
                "origin_kind": "manual",
            },
        ],
        recent_evidence=[
            {
                "source_kind": "github_commit_group",
                "occurred_at": "2026-09-18",
                "claim_type": "demonstrated",
                "lesson_summary": "Reworked the follow-up sequence scheduler.",
            }
        ],
    )
    base.update(over)
    return AppraisalInput(**base)


def test_the_prompt_hands_over_the_anchors_as_settled():
    prompt = build_prompt(_input())
    assert "already established, not your decision" in prompt
    assert "whatsapp business" in prompt
    assert "automated follow-up messaging" in prompt


def test_the_prompt_says_when_he_has_not_touched_it_recently():
    """Removes the temptation to claim he tested something."""
    prompt = build_prompt(_input(recent_evidence=[]))
    assert "nothing in the window" in prompt
    assert "'i_tested_it' is not available" in prompt


def test_a_long_document_is_truncated_visibly():
    prompt = build_prompt(_input(document="x" * 40000))
    assert "[truncated]" in prompt
    assert len(prompt) < 20000


def test_the_request_is_one_subscription_job_with_a_stable_key():
    item = uuid.uuid4()
    first = build_request(_input(), workspace_id=WS, news_item_id=item)
    second = build_request(_input(), workspace_id=WS, news_item_id=item)
    assert first.job_type == JOB_TYPE
    assert first.prompt_version == PROMPT_VERSION
    assert first.output_schema is OUTPUT_SCHEMA
    assert first.idempotency_key == second.idempotency_key, (
        "the same item must not be appraised twice"
    )
    assert str(item) in first.idempotency_key


def test_the_request_names_no_model_and_no_provider():
    """Model choice and billing belong to the subscription worker, not here."""
    request = build_request(_input(), workspace_id=WS, news_item_id=uuid.uuid4())
    assert request.requested_model is None


def test_the_system_prompt_states_the_rules_that_are_not_enforced_in_code():
    for rule in (
        "never the idea",
        "procurement department",
        "manufactured urgency",
        "Never invent an outcome",
        "Never name a client",
    ):
        assert rule in SYSTEM_PROMPT, f"the prompt stopped saying: {rule}"


def test_the_schema_allows_saying_no():
    """A schema that only fits a yes is a schema that manufactures yeses."""
    assert set(OUTPUT_SCHEMA["properties"]["verdict"]["enum"]) == {
        "publish",
        "watch",
        "reject",
    }


# ---------------------------------------------------------------------------
# The integration trap: a source nobody can read is selected forever
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_news_sources_are_never_offered_to_the_moment_extractor(editorial_session):
    """`_jobs_for_source` returns [] for an unknown kind, which is a silent loop.

    A source that is eligible for extraction but yields no moments never gets
    `moments_extracted_for` set and never has an active moment, so it is picked
    again on every run, forever, and nothing anywhere says so. The two news-lane
    kinds are filtered out at the query instead.
    """
    from tce.evidence.moments import EXTRACTABLE_KINDS, sources_needing_extraction
    from tce.models.editorial import EvidenceSource

    for kind in ("fathom_meeting", "news_item", "standing_fact"):
        editorial_session.add(
            EvidenceSource(
                id=uuid.uuid4(),
                workspace_id=WS,
                source_kind=kind,
                external_id=f"{kind}-1",
                version_hash=f"h-{kind}",
                occurred_at=PUBLISHED,
                fetch_status="ok",
                payload_private={"turns": [{"index": 0, "text": "hello"}]},
            )
        )
    await editorial_session.flush()

    selected = await sources_needing_extraction(editorial_session, WS, None, None)
    kinds = {s.source_kind for s in selected}
    assert kinds == {"fathom_meeting"}, f"extractor was offered {kinds - set(EXTRACTABLE_KINDS)}"
    assert "news_item" not in EXTRACTABLE_KINDS
    assert "standing_fact" not in EXTRACTABLE_KINDS
