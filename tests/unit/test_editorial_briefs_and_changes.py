"""The review contract: nothing changes editorial content except an accepted proposal.

These are the plan's "Changes and history" acceptance tests. The failure they exist
to prevent is the one that makes an editorial assistant unusable: it rewrites your
topic because you were thinking out loud, and you cannot tell what it touched or
get the old wording back.

So: a proposal is inert until accepted, accepting writes a new version rather than
editing one, a proposal built against an old version cannot overwrite a newer one,
a recorded script is frozen, and private evidence never reaches a brief.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.editorial import briefs, changes
from tce.editorial.changes import ChangeError, OperationInput
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import CandidateBriefVersion

WEEK = datetime(2026, 9, 21)


def gates() -> dict:
    return {
        "small_service_business": {"pass": True, "reason": "yes"},
        "coach_or_event_owner_relevance": {"pass": True, "reason": "yes"},
        "concrete_supported_substance": {"pass": True, "reason": "yes"},
        "connects_to_ziv_work": {"pass": True, "reason": "yes"},
    }


def make_candidate(ws: uuid.UUID, **over) -> TopicCandidate:
    data = dict(
        workspace_id=ws,
        week_start=WEEK,
        moment_ids=[str(uuid.uuid4())],
        title="Your AI should know I will from I did",
        lesson="A progress report that mixes intention with completion is not a report.",
        audience="coaches",
        reasons_to_care=["they manage assistants the same way"],
        public_angle="Treat an agent like a person you manage.",
        gates=gates(),
        citations_private=[
            {
                "moment_id": str(uuid.uuid4()),
                "source_kind": "fathom_meeting",
                "title": "Call with a client",
                "url_private": "https://fathom.video/share/SECRET-TOKEN-123",
                "claim_type": "quoted",
            }
        ],
        status="proposed",
        origin="selector",
        freshness_role="evergreen",
    )
    data.update(over)
    return TopicCandidate(**data)


async def seeded(session, ws) -> tuple[TopicCandidate, CandidateBriefVersion]:
    candidate = make_candidate(ws)
    session.add(candidate)
    await session.flush()
    brief = await briefs.ensure_brief(session, ws, candidate)
    await session.commit()
    return candidate, brief


# ---------------------------------------------------------------- seeding


async def test_version_one_is_the_idea_rearranged_not_new_content(editorial_session):
    ws = uuid.uuid4()
    candidate, brief = await seeded(editorial_session, ws)

    assert brief.version == 1
    assert brief.origin == "seed"
    assert brief.parent_version is None
    # Every seeded value came off the candidate row.
    assert brief.brief["topic"] == candidate.title
    assert brief.brief["big_idea"] == candidate.lesson
    assert brief.brief["distinctive_perspective"] == candidate.public_angle


async def test_a_tokenized_source_url_never_reaches_the_brief(editorial_session):
    """A brief is editable text that can be exported. A Fathom share link is a credential."""
    ws = uuid.uuid4()
    _, brief = await seeded(editorial_session, ws)

    blob = "\n".join(str(v) for v in brief.brief.values())
    assert "SECRET-TOKEN-123" not in blob
    assert "fathom.video/share" not in blob
    # It still says where the idea came from, which is the part he reads.
    assert "your call" in brief.brief["evidence"]


async def test_seeding_twice_does_not_make_two_version_ones(editorial_session):
    """Two tabs opening the same topic room must not fork its history at version 1."""
    ws = uuid.uuid4()
    candidate, first = await seeded(editorial_session, ws)
    second = await briefs.ensure_brief(editorial_session, ws, candidate)
    await editorial_session.commit()

    assert first.id == second.id
    versions = await briefs.list_versions(editorial_session, ws, candidate.id)
    assert [v.version for v in versions] == [1]


async def test_a_topic_with_no_connection_to_his_work_is_not_inbox_eligible(editorial_session):
    """The plan's rule: if we cannot say why it belongs to him, it is not his topic."""
    ws = uuid.uuid4()
    candidate = make_candidate(ws, citations_private=[], reasons_to_care=[])
    editorial_session.add(candidate)
    await editorial_session.flush()
    brief = await briefs.ensure_brief(editorial_session, ws, candidate)

    assert brief.brief["why_this_is_yours"] == ""
    assert briefs.is_inbox_eligible(brief.brief) is False


# ------------------------------------------------- proposing and applying


async def test_a_proposal_changes_nothing_until_it_is_accepted(editorial_session):
    ws = uuid.uuid4()
    candidate, brief = await seeded(editorial_session, ws)

    await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=brief.version,
        operations=[
            OperationInput(op="set_field", field="big_idea", after="Something else entirely.")
        ],
        summary="Change the central lesson",
    )
    await editorial_session.commit()

    current = await briefs.latest_version(editorial_session, ws, candidate.id)
    assert current.version == 1
    assert current.brief["big_idea"] == candidate.lesson


async def test_applying_writes_a_new_version_and_leaves_the_old_one_readable(editorial_session):
    ws = uuid.uuid4()
    candidate, brief = await seeded(editorial_session, ws)
    original = brief.brief["big_idea"]

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[
            OperationInput(
                op="set_field",
                field="big_idea",
                after="It is about managing people and agents the same way.",
                rationale="The point is management, not AI accuracy.",
            )
        ],
        summary="Change the central lesson",
    )
    result = await changes.apply(editorial_session, ws, change_set.id, decided_by="ziv")
    await editorial_session.commit()

    assert result["version"] == 2
    v1 = await briefs.get_version(editorial_session, ws, candidate.id, 1)
    v2 = await briefs.get_version(editorial_session, ws, candidate.id, 2)
    assert v1.brief["big_idea"] == original
    assert v2.brief["big_idea"] == "It is about managing people and agents the same way."
    assert v2.parent_version == 1
    assert v2.change_set_id == change_set.id


async def test_one_field_changes_without_rewriting_the_others(editorial_session):
    ws = uuid.uuid4()
    candidate, brief = await seeded(editorial_session, ws)
    untouched = brief.brief["distinctive_perspective"]

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="takeaway", after="Open the result.")],
        summary="Add the takeaway",
    )
    await changes.apply(editorial_session, ws, change_set.id)
    await editorial_session.commit()

    v2 = await briefs.get_version(editorial_session, ws, candidate.id, 2)
    assert v2.brief["takeaway"] == "Open the result."
    assert v2.brief["distinctive_perspective"] == untouched
    assert v2.brief["big_idea"] == brief.brief["big_idea"]


async def test_a_stale_proposal_cannot_overwrite_a_newer_version(editorial_session):
    """Two devices, one topic. The loser sees the newer state, it does not win silently."""
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    stale = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="takeaway", after="From the phone.")],
        summary="From the phone",
    )
    other = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="takeaway", after="From the desk.")],
        summary="From the desk",
    )
    await changes.apply(editorial_session, ws, other.id)
    await editorial_session.commit()

    with pytest.raises(ChangeError) as caught:
        await changes.apply(editorial_session, ws, stale.id)

    assert caught.value.code == "conflict"
    assert caught.value.extra["current_version"] == 2
    current = await briefs.latest_version(editorial_session, ws, candidate.id)
    assert current.brief["takeaway"] == "From the desk."


async def test_rejecting_keeps_the_proposal_and_changes_nothing(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="cta", after="Book a session.")],
        summary="Add a CTA",
    )
    await changes.reject(editorial_session, ws, change_set.id, decided_by="ziv")
    await editorial_session.commit()

    again = await changes.get_change_set(editorial_session, ws, change_set.id)
    ops = await changes.load_operations(editorial_session, ws, change_set.id)
    assert again.state == "rejected"
    assert [o.state for o in ops] == ["rejected"]
    current = await briefs.latest_version(editorial_session, ws, candidate.id)
    assert current.version == 1


async def test_undo_restores_old_wording_as_a_new_version(editorial_session):
    """History stays append-only, so undoing the undo is an ordinary move."""
    ws = uuid.uuid4()
    candidate, brief = await seeded(editorial_session, ws)
    original = brief.brief["big_idea"]

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="big_idea", after="A worse sentence.")],
        summary="Rewrite the lesson",
    )
    await changes.apply(editorial_session, ws, change_set.id)
    await editorial_session.commit()

    result = await changes.undo(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        to_version=1,
        decided_by="ziv",
    )
    await editorial_session.commit()

    assert result["version"] == 3
    v3 = await briefs.get_version(editorial_session, ws, candidate.id, 3)
    assert v3.brief["big_idea"] == original
    assert v3.origin == "undo"
    # Nothing was destroyed on the way.
    assert [v.version for v in await briefs.list_versions(editorial_session, ws, candidate.id)] == [
        1,
        2,
        3,
    ]


async def test_undo_removes_a_block_the_change_had_added(editorial_session):
    """Restore replaces the content; it does not merge over what is there now.

    The earlier undo test changed a block that existed in both versions, so a
    merge looked identical to a replace and the bug hid. Adding a block and then
    restoring is the case that separates them: `takeaway` has to be gone again,
    not left behind under a label saying version 1.
    """
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="takeaway", after="Open the result.")],
        summary="Add a takeaway",
    )
    await changes.apply(editorial_session, ws, change_set.id)
    await editorial_session.commit()

    await changes.undo(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        to_version=1,
        decided_by="ziv",
    )
    await editorial_session.commit()

    v3 = await briefs.get_version(editorial_session, ws, candidate.id, 3)
    assert v3.brief.get("takeaway", "") == ""
    # And version 2 still says what it said, because history is append-only.
    v2 = await briefs.get_version(editorial_session, ws, candidate.id, 2)
    assert v2.brief["takeaway"] == "Open the result."


async def test_partial_approval_applies_only_what_was_accepted(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[
            OperationInput(op="set_field", field="takeaway", after="Keep this one."),
            OperationInput(op="set_field", field="cta", after="Not this one."),
        ],
        summary="Two changes",
    )
    result = await changes.apply(editorial_session, ws, change_set.id, accept_seqs=[1])
    await editorial_session.commit()

    assert result["applied"] == [1]
    assert result["skipped"] == [2]
    v2 = await briefs.get_version(editorial_session, ws, candidate.id, 2)
    assert v2.brief["takeaway"] == "Keep this one."
    assert v2.brief.get("cta", "") == ""


async def test_accepting_an_operation_pulls_in_what_it_depends_on(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[
            OperationInput(op="set_field", field="big_idea", after="The new lesson."),
            OperationInput(
                op="set_field",
                field="takeaway",
                after="Follows from the new lesson.",
                depends_on=[1],
            ),
        ],
        summary="A bundle",
    )
    result = await changes.apply(editorial_session, ws, change_set.id, accept_seqs=[2])
    await editorial_session.commit()

    assert sorted(result["applied"]) == [1, 2]
    v2 = await briefs.get_version(editorial_session, ws, candidate.id, 2)
    assert v2.brief["big_idea"] == "The new lesson."


async def test_a_field_that_is_not_editable_makes_the_proposal_invalid(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="gates", after="nope")],
        summary="Try to edit the gates",
    )
    await editorial_session.commit()

    assert change_set.state == "invalid"
    assert change_set.validation["ok"] is False
    with pytest.raises(ChangeError) as caught:
        await changes.apply(editorial_session, ws, change_set.id)
    assert caught.value.code == "not_proposed"


async def test_applying_the_same_proposal_twice_does_not_double_write(editorial_session):
    """A retried tap on a slow connection must not create version 3."""
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="cta", after="Book a session.")],
        summary="Add a CTA",
    )
    first = await changes.apply(editorial_session, ws, change_set.id)
    second = await changes.apply(editorial_session, ws, change_set.id)
    await editorial_session.commit()

    assert first["version"] == 2
    assert second["version"] == 2
    assert second["already"] is True
    versions = await briefs.list_versions(editorial_session, ws, candidate.id)
    assert [v.version for v in versions] == [1, 2]


async def test_the_same_idempotency_key_reuses_one_proposal(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)

    kwargs = dict(
        target_type="candidate_brief",
        target_id=candidate.id,
        base_version=1,
        operations=[OperationInput(op="set_field", field="cta", after="Book a session.")],
        summary="Add a CTA",
        idempotency_key="abc-123",
    )
    first = await changes.propose(editorial_session, ws, **kwargs)
    await editorial_session.commit()
    second = await changes.propose(editorial_session, ws, **kwargs)
    await editorial_session.commit()

    assert first.id == second.id


# -------------------------------------------------------------- packets


async def make_packet(session, ws, candidate, **over) -> RecordingPacket:
    data = dict(
        workspace_id=ws,
        candidate_id=candidate.id,
        version=1,
        bullets=["Split it into four jobs", "Work the weakest one"],
        script_phrases=["Most owners work on the job they enjoy.", "Not the one losing money."],
        facebook_post="A post.",
        linkedin_post="Another post.",
        status="ready",
        citations_private=[],
        public_safety={"checked": True, "status": "clean", "issues": []},
    )
    data.update(over)
    packet = RecordingPacket(**data)
    session.add(packet)
    await session.flush()
    return packet


async def test_changing_one_script_line_creates_a_new_packet_version(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)
    packet = await make_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="packet",
        target_id=packet.id,
        base_version=1,
        operations=[
            OperationInput(
                op="set_field",
                field="script_phrases.1",
                after="Not the one that is quietly losing them money.",
            )
        ],
        summary="Make the second line easier to say",
    )
    result = await changes.apply(editorial_session, ws, change_set.id)
    await editorial_session.commit()

    assert result["version"] == 2
    await editorial_session.refresh(packet)
    assert packet.status == "superseded"
    assert packet.script_phrases[1] == "Not the one losing money."


async def test_a_recorded_script_is_frozen(editorial_session):
    """The video and the script must never disagree with nothing to say which was true."""
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)
    packet = await make_packet(editorial_session, ws, candidate)
    editorial_session.add(
        RecordingUpload(
            workspace_id=ws,
            candidate_id=candidate.id,
            packet_id=packet.id,
            original_filename="take.mp4",
            storage_path="/tmp/take.mp4",
            sha256="a" * 64,
            status="uploaded",
        )
    )
    await editorial_session.commit()

    with pytest.raises(ChangeError) as caught:
        await changes.propose(
            editorial_session,
            ws,
            target_type="packet",
            target_id=packet.id,
            base_version=1,
            operations=[
                OperationInput(op="set_field", field="facebook_post", after="Rewritten.")
            ],
            summary="Rewrite the post",
        )
    assert caught.value.code == "immutable"


async def test_an_unsafe_proposed_line_is_flagged_before_it_can_be_accepted(editorial_session):
    ws = uuid.uuid4()
    candidate, _ = await seeded(editorial_session, ws)
    packet = await make_packet(editorial_session, ws, candidate)
    await editorial_session.commit()

    change_set = await changes.propose(
        editorial_session,
        ws,
        target_type="packet",
        target_id=packet.id,
        base_version=1,
        operations=[
            OperationInput(
                op="set_field",
                field="facebook_post",
                after="Email me at someone@example.com and I guarantee you will double revenue.",
            )
        ],
        summary="Rewrite the post",
    )
    await editorial_session.commit()

    codes = {i["code"] for i in change_set.validation["issues"]}
    assert "safety" in codes


async def test_an_internal_moment_id_never_reaches_a_block_he_reads(editorial_session):
    """He asked never to see phrase ids: "useless and distracting".

    The selector writes real instructions with a uuid embedded. The instruction is
    worth reading; the id is noise.
    """
    ws = uuid.uuid4()
    candidate = make_candidate(
        ws,
        public_safety_notes=(
            "Translation (English adaptation from Hebrew) for moment "
            "45586105-e117-45a9-b968-20ccbd682576: paraphrase, do not quote."
        ),
    )
    editorial_session.add(candidate)
    await editorial_session.flush()
    brief = await briefs.ensure_brief(editorial_session, ws, candidate)
    await editorial_session.commit()

    claims = brief.brief["claims_to_avoid"]
    assert "45586105" not in claims
    assert "moment" not in claims.lower()
    # The instruction itself survives intact.
    assert "paraphrase, do not quote" in claims
