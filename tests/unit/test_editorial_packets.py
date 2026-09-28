"""Recording packets: validation, CTA, public-safety scan, versioning, waiting state."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import packets
from tce.editorial.safety import scan_public_text
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import EvidenceSource, RecordingPacket, TopicCandidate


def good_output(**over) -> dict:
    data = {
        "bullets": [
            "Start from what the person can do afterward",
            "Name the problems in the way",
            "Put the problems in order",
            "Match each lesson to one problem",
            "Cut what does not help",
            "Let AI challenge the sequence",
        ],
        "script_phrases": [
            "When a coach asks me what lessons to put in a course,",
            "I go back one step.",
            "What will someone be able to do when they finish?",
            "Name the problems first.",
            "Put them in order.",
            "Then decide what each lesson is for.",
            "The lessons come last,",
            "because now you know what they are for.",
        ],
        "facebook_post": "A question before you plan a course: what can they do at the end?",
        "linkedin_post": "Plan the course from the problems, and the lessons follow.",
        "interviewer_prompt": "What do you ask before discussing lessons?",
        "hook_options": [
            {
                "id": "hook-1",
                "text": "When a coach asks me what lessons to put in a course,",
                "question": "Why start somewhere other than the lessons?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "Opens on the familiar mistake and pays it off quickly.",
            },
            {
                "id": "hook-2",
                "text": "The best course outline does not begin with lessons.",
                "question": "What should it begin with?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "A direct tension statement.",
            },
            {
                "id": "hook-3",
                "text": "I used to start course planning one step too late.",
                "question": "What was the missing first step?",
                "payoff_phrase_id": "p003",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "Personal and honest.",
            },
        ],
        "selected_hook_id": "hook-1",
        "beats": [
            {
                "id": "b01",
                "label": "Outcome",
                "bullet_index": 0,
                "start_phrase_id": "p001",
                "end_phrase_id": "p002",
            },
            {
                "id": "b02",
                "label": "Question",
                "bullet_index": 1,
                "start_phrase_id": "p003",
                "end_phrase_id": "p003",
            },
            {
                "id": "b03",
                "label": "Problems",
                "bullet_index": 2,
                "start_phrase_id": "p004",
                "end_phrase_id": "p004",
            },
            {
                "id": "b04",
                "label": "Order",
                "bullet_index": 3,
                "start_phrase_id": "p005",
                "end_phrase_id": "p005",
            },
            {
                "id": "b05",
                "label": "Lessons",
                "bullet_index": 4,
                "start_phrase_id": "p006",
                "end_phrase_id": "p006",
            },
            {
                "id": "b06",
                "label": "Invitation",
                "bullet_index": 5,
                "start_phrase_id": "p007",
                "end_phrase_id": "p008",
            },
        ],
        "self_check": {"one_lesson": True, "cta_is_strategy_session": True},
    }
    data.update(over)
    if "script_phrases" in over and "hook_options" not in over:
        data["hook_options"][0]["text"] = data["script_phrases"][0]
    if ("bullets" in over or "script_phrases" in over) and "beats" not in over:
        count = len(data["bullets"])
        phrase_count = len(data["script_phrases"])
        data["beats"] = []
        for index, label in enumerate(data["bullets"]):
            start = 1 + (index * phrase_count // count)
            end = max(start, ((index + 1) * phrase_count // count))
            data["beats"].append(
                {
                    "id": f"b{index + 1:02d}",
                    "label": label,
                    "bullet_index": index,
                    "start_phrase_id": f"p{start:03d}",
                    "end_phrase_id": f"p{end:03d}",
                }
            )
    return data


async def make_candidate(session, ws, status="selected", speaker="Dana Example"):
    src = EvidenceSource(
        workspace_id=ws,
        source_kind="fathom_meeting",
        external_id=str(uuid.uuid4()),
        version_hash="a" * 64,
        payload_private={
            "turns": [
                {"speaker": speaker, "text": "synthetic"},
                {"speaker": "Ziv Raviv", "text": "synthetic"},
            ]
        },
    )
    session.add(src)
    await session.flush()
    c = TopicCandidate(
        workspace_id=ws,
        week_start=datetime(2026, 9, 7),
        moment_ids=["11111111-1111-1111-1111-111111111111"],
        title="Build the course around problems solved",
        lesson="Order problems first.",
        audience="coaches",
        public_angle="angle",
        gates={},
        status=status,
        citations_private=[
            {
                "source_id": str(src.id),
                "speaker": "Ziv Raviv",
                "claim_type": "paraphrased",
                "excerpt_private": "synthetic",
            }
        ],
    )
    session.add(c)
    await session.commit()
    return c


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"output": good_output(), "raise": None, "calls": []}

    async def fake_complete(req, *, wait_timeout_s=None):
        state["calls"].append(req)
        if state["raise"]:
            raise state["raise"]
        return LLMResult(
            job_id=uuid.uuid4(), text="", structured=state["output"], model="claude-opus-5"
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


@pytest.mark.parametrize("count", [4, 8])
def test_bullets_outside_5_to_7_rejected(count):
    with pytest.raises(packets.PacketValidationError, match="bullets"):
        packets.validate_packet_output(good_output(bullets=[f"b{i}" for i in range(count)]))


@pytest.mark.parametrize("count", [5, 7])
def test_bullets_within_range_accepted(count):
    out = packets.validate_packet_output(good_output(bullets=[f"b{i}" for i in range(count)]))
    assert len(out["bullets"]) == count


def test_script_that_ends_on_the_lesson_is_accepted():
    # His rule (27-Sep-2026): no call to action, so no invitation is required.
    out = packets.validate_packet_output(good_output(), forbid_asks=True)
    assert out["script_phrases"][-1] == "because now you know what they are for."


@pytest.mark.parametrize(
    "field,value",
    [
        ("script_phrases", "book a strategy session."),
        ("script_phrases", "DM me and we will talk."),
        ("facebook_post", "Plan it this way. Book a call with me."),
        ("linkedin_post", "Plan it this way. Follow for more."),
        ("facebook_post", "The full plan is at the link in bio."),
    ],
)
def test_fresh_packet_that_asks_for_something_is_refused(field, value):
    out = good_output()
    if field == "script_phrases":
        out["script_phrases"] = out["script_phrases"] + [value]
    else:
        out[field] = value
    with pytest.raises(packets.PacketValidationError, match="no call to action"):
        packets.validate_packet_output(out, forbid_asks=True)


def test_packet_written_before_the_rule_still_revalidates():
    # A new opening or a voice pass re-validates an old packet; the old invitation
    # ending must not make it unusable.
    old = good_output()
    old["script_phrases"] = old["script_phrases"] + ["book a strategy session."]
    old["facebook_post"] = "A question before you plan a course. Book a strategy session."
    assert packets.validate_packet_output(old)["script_phrases"][-1] == "book a strategy session."


def test_packet_prompt_carries_his_post_rules():
    cand = packets.TopicCandidate(title="t", lesson="l", citations_private=[], moment_ids=[])
    prompt = packets.build_packet_prompt("STRAT", cand, post_rules="No call to action, ever.")
    assert "HIS POST RULES" in prompt and "No call to action, ever." in prompt
    assert "No call to action of any kind" in packets.SYSTEM_PROMPT
    assert "invite the viewer to book" not in packets.SYSTEM_PROMPT


def test_idea_picker_follows_the_no_call_to_action_rule():
    from tce.editorial import selector

    assert "The only call to action is a strategy session" not in selector.SYSTEM_PROMPT
    assert "No call to action" in selector.SYSTEM_PROMPT


def test_giveaway_cta_rejected():
    with pytest.raises(packets.PacketValidationError, match="giveaway"):
        packets.validate_packet_output(
            good_output(facebook_post="Comment GUIDE and I will send the free guide.")
        )


def test_safety_scan_catches_money_email_participant_and_token_url():
    result = scan_public_text(
        {
            "script_phrases": [
                "My client paid $4,500 for this.",
                "Email me at someone@example.com",
                "Dana told me it worked.",
                "See https://example.com/report?token=abc123",
                "Revenue went up 30% that month.",
                "Call 054-123-4567 today.",
                "This is guaranteed to work.",
                "My client said it changed everything.",
            ]
        },
        participants=["Dana Example", "Ziv Raviv", "Speaker 2"],
    )
    kinds = {i["kind"] for i in result["issues"]}
    assert result["status"] == "issues"
    assert {
        "money",
        "email",
        "participant_name",
        "token_url",
        "revenue_percentage",
        "phone",
        "absolute_guarantee",
        "customer_quote",
    } <= kinds
    # Ziv himself and generic speaker labels are not flagged
    assert all(i["match"] != "Ziv Raviv" for i in result["issues"])


def test_safety_scan_clean_text():
    result = scan_public_text(good_output(), participants=["Dana Example"])
    assert result == {"checked": True, "status": "clean", "issues": []}


async def test_build_packet_persists_clean_packet_with_no_call_to_action_and_no_price(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.status == "ready"
    p = out.packet
    assert p["version"] == 1 and p["public_safety"]["status"] == "clean"
    assert "strategy session" not in " ".join(p["script_phrases"]).lower()
    assert "$" not in " ".join(p["script_phrases"] + p["bullets"])
    req = fake_llm["calls"][0]
    assert (req.job_type, req.prompt_version) == ("recording_packet", "recording_packet.v3")
    # His post rules (the Settings default here) ride in the writer's request.
    from tce.production.publishing import DEFAULT_POST_RULES

    assert DEFAULT_POST_RULES in req.messages[0]["content"]


def test_hook_and_beat_contract_rejects_unknown_payoff_and_wrong_opening():
    bad = good_output()
    bad["hook_options"][0]["payoff_phrase_id"] = "p999"
    with pytest.raises(packets.PacketValidationError, match="payoff"):
        packets.validate_packet_output(bad)
    bad = good_output()
    bad["hook_options"][0]["text"] = "Different from the spoken opening"
    with pytest.raises(packets.PacketValidationError, match="first spoken"):
        packets.validate_packet_output(bad)


async def test_packet_with_participant_name_and_price_flags_issues(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    phrases = ["Dana asked me about pricing.", "I charge $900 a session."] + good_output()[
        "script_phrases"
    ]
    fake_llm["output"] = good_output(script_phrases=phrases)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.status == "issues"
    kinds = {i["kind"] for i in out.packet["public_safety"]["issues"]}
    assert {"participant_name", "money"} <= kinds
    assert out.packet["status"] == "draft"


async def test_a_script_with_only_false_positives_is_saved_ready(editorial_sessionmaker, fake_llm):
    # 28-Sep-2026: three scripts were saved as drafts for a disclaimed guarantee
    # and for "The" out of a client's company name. The writer's own scan decides.
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws, speaker="Tim Hollis - In The Box Events")
    phrases = good_output()["script_phrases"] + [
        "It's not a guarantee, it's a starting point.",
        "The same thing works for a coach.",
    ]
    fake_llm["output"] = good_output(script_phrases=phrases)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.packet["public_safety"]["issues"] == []
    assert (out.status, out.packet["status"]) == ("ready", "ready")


async def test_the_writer_still_catches_the_participants_real_name(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws, speaker="Tim Hollis - In The Box Events")
    phrases = ["Tim asked me where to start."] + good_output()["script_phrases"]
    fake_llm["output"] = good_output(script_phrases=phrases)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert "participant_name" in {i["kind"] for i in out.packet["public_safety"]["issues"]}
    assert out.packet["status"] == "draft"


async def test_versions_increment_and_older_superseded(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    await packets.build_packet(editorial_sessionmaker, ws, c.id)
    second = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert second.packet["version"] == 2
    async with editorial_sessionmaker() as s:
        rows = (
            (await s.execute(select(RecordingPacket).order_by(RecordingPacket.version)))
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["superseded", "ready"]


async def test_choose_hook_creates_immutable_packet_version(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        candidate = await make_candidate(s, ws)
    built = await packets.build_packet(editorial_sessionmaker, ws, candidate.id)
    original_id = uuid.UUID(built.packet["id"])
    original_opening = built.packet["script_phrases"][0]

    async with editorial_sessionmaker() as s:
        clone = await packets.choose_hook(s, ws, original_id, "hook-2")
        await s.commit()
        clone_id = clone.id

    async with editorial_sessionmaker() as s:
        rows = list(
            (await s.execute(select(RecordingPacket).order_by(RecordingPacket.version)))
            .scalars()
            .all()
        )
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].id == original_id and rows[0].script_phrases[0] == original_opening
    assert rows[1].id == clone_id and rows[1].selected_hook_id == "hook-2"
    assert rows[1].script_phrases[0] == "The best course outline does not begin with lessons."


# ------------------------------------------------------------ a new version's own verdict
#
# Ziv, 28-Sep-2026, asked to fix "Switching a script's opening line keeps the old
# safety result". choose_hook copied the old version's scan and status, so a ready
# script whose new opening made a promise stayed ready and reached the recording
# list, and a draft whose only flag was the old opening stayed a draft after he
# chose a clean one. More openings and the voice pass copied them the same way.


def with_opening(index: int, text: str, **over) -> dict:
    data = good_output(**over)
    data["hook_options"][index]["text"] = text
    return data


async def choose(sm, ws, packet_id, hook_id):
    async with sm() as s:
        clone = await packets.choose_hook(s, ws, packet_id, hook_id)
        await s.commit()
        return clone


async def stored_versions(sm, ws):
    async with sm() as s:
        return list(
            (
                await s.execute(
                    select(RecordingPacket)
                    .where(RecordingPacket.workspace_id == ws)
                    .order_by(RecordingPacket.version)
                )
            )
            .scalars()
            .all()
        )


def flags(safety) -> set[tuple[str, str]]:
    return {(issue["field"], issue["kind"]) for issue in (safety or {}).get("issues") or []}


async def test_choosing_an_opening_that_makes_a_promise_turns_a_ready_script_draft(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    fake_llm["output"] = with_opening(1, "This course plan works every time, guaranteed.")
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert built.packet["status"] == "ready"

    await choose(editorial_sessionmaker, ws, uuid.UUID(built.packet["id"]), "hook-2")

    rows = await stored_versions(editorial_sessionmaker, ws)
    assert rows[1].script_phrases[0] == "This course plan works every time, guaranteed."
    assert ("script_phrases[0]", "absolute_guarantee") in flags(rows[1].public_safety)
    assert rows[1].public_safety["status"] == "issues"
    assert rows[1].status == "draft"


async def test_choosing_a_clean_opening_turns_a_draft_ready(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    phrases = good_output()["script_phrases"]
    fake_llm["output"] = good_output(
        script_phrases=["I guarantee this fixes your course.", *phrases[1:]]
    )
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    # The only flag is on the opening he is about to replace.
    assert built.packet["status"] == "draft"
    assert {f for f, _ in flags(built.packet["public_safety"])} == {"script_phrases[0]"}

    await choose(editorial_sessionmaker, ws, uuid.UUID(built.packet["id"]), "hook-2")

    rows = await stored_versions(editorial_sessionmaker, ws)
    assert rows[1].script_phrases[0] == "The best course outline does not begin with lessons."
    assert rows[1].public_safety["status"] == "clean"
    assert rows[1].status == "ready"


async def test_choosing_an_opening_on_an_exported_script_follows_an_accepted_edit(
    editorial_sessionmaker, fake_llm
):
    # The rule an accepted edit follows: the new version is ready (never
    # "exported"; only the export marks the version it sent), and the version it
    # was made from is superseded.
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingPacket, uuid.UUID(built.packet["id"]))
        row.status = "exported"
        await s.commit()

    await choose(editorial_sessionmaker, ws, uuid.UUID(built.packet["id"]), "hook-2")

    rows = await stored_versions(editorial_sessionmaker, ws)
    assert [(r.version, r.status) for r in rows] == [(1, "superseded"), (2, "ready")]


async def test_an_opening_that_names_a_meeting_participant_is_caught(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws, speaker="Dana Example")
    fake_llm["output"] = with_opening(1, "Dana asked me where a course should start.")
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert built.packet["status"] == "ready"

    await choose(editorial_sessionmaker, ws, uuid.UUID(built.packet["id"]), "hook-2")

    rows = await stored_versions(editorial_sessionmaker, ws)
    assert ("script_phrases[0]", "participant_name") in flags(rows[1].public_safety)
    assert rows[1].status == "draft"


async def test_an_opening_chosen_on_a_replaced_version_writes_nothing(
    editorial_sessionmaker, fake_llm
):
    # History still opens old versions, and each has its openings tab. Choosing
    # there built the new version from the OLD text: it silently undid everything
    # after that version and, scanned clean, went straight to the recording list.
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    first = uuid.UUID(built.packet["id"])
    await choose(editorial_sessionmaker, ws, first, "hook-2")

    with pytest.raises(packets.PacketValidationError, match="version 2"):
        await choose(editorial_sessionmaker, ws, first, "hook-3")

    rows = await stored_versions(editorial_sessionmaker, ws)
    assert [(r.version, r.status, r.selected_hook_id) for r in rows] == [
        (1, "superseded", "hook-1"),
        (2, "ready", "hook-2"),
    ]


async def test_an_edit_left_open_on_the_old_version_cannot_bring_the_old_opening_back(
    editorial_sessionmaker, fake_llm
):
    # Why choosing an opening marks the version it was made from superseded, as an
    # accepted edit does: the workshop and its Talk thread stay on the row they
    # opened, and an accepted edit refuses a proposal only when its row is marked
    # replaced. Left "ready", a line fix proposed before the choice went through
    # after it and wrote a newer version from the OLD text: the chosen opening was
    # gone, and the scan made that version ready (28-Sep-2026).
    from tce.editorial import changes
    from tce.editorial.changes import ChangeError, OperationInput

    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    built = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    first = uuid.UUID(built.packet["id"])
    async with editorial_sessionmaker() as s:
        proposal = await changes.propose(
            s,
            ws,
            target_type="packet",
            target_id=first,
            base_version=1,
            operations=[
                OperationInput(op="set_field", field="script_phrases.3", after="Name them first.")
            ],
            summary="Fix one line",
        )
        await s.commit()

    await choose(editorial_sessionmaker, ws, first, "hook-2")

    async with editorial_sessionmaker() as s:
        with pytest.raises(ChangeError) as caught:
            await changes.apply(s, ws, proposal.id)
        await s.commit()
    assert caught.value.code == "conflict"
    rows = await stored_versions(editorial_sessionmaker, ws)
    assert [(r.version, r.status) for r in rows] == [(1, "superseded"), (2, "ready")]
    assert rows[1].selected_hook_id == "hook-2"
    assert rows[1].script_phrases[0] == "The best course outline does not begin with lessons."


async def test_invalid_output_and_unavailable_persist_nothing(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    fake_llm["output"] = good_output(bullets=["only one"])
    bad = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert bad.status == "failed" and bad.packet is None and bad.errors

    fake_llm["raise"] = LLMUnavailable("waiting_capacity", "limit", job_id=uuid.uuid4())
    waiting = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert waiting.status == "waiting_capacity" and waiting.packet is None
    async with editorial_sessionmaker() as s:
        assert (await s.execute(select(RecordingPacket))).scalars().all() == []


async def test_other_workspace_candidate_not_found(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, uuid.uuid4())
    with pytest.raises(LookupError):
        await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert fake_llm["calls"] == []


def test_packet_prompt_lists_the_moment_ids_the_validator_requires():
    """20-Sep-2026: the prompt omitted moment_id, the model answered "ev1",
    and every packet was rejected as citing evidence outside the idea."""
    cand = TopicCandidate(
        workspace_id=uuid.uuid4(),
        week_start=datetime(2026, 9, 7),
        moment_ids=["11111111-1111-1111-1111-111111111111"],
        title="t",
        lesson="l",
        audience="coaches",
        public_angle="a",
        gates={},
        citations_private=[
            {
                "moment_id": "11111111-1111-1111-1111-111111111111",
                "claim_type": "paraphrased",
                "excerpt_private": "synthetic",
            }
        ],
    )
    prompt = packets.build_packet_prompt("strategy", cand)
    assert '"moment_id": "11111111-1111-1111-1111-111111111111"' in prompt
    assert "copied verbatim from the moment_id values below" in prompt


def test_packet_prompt_falls_back_to_candidate_moment_ids():
    cand = TopicCandidate(
        workspace_id=uuid.uuid4(),
        week_start=datetime(2026, 9, 7),
        moment_ids=["22222222-2222-2222-2222-222222222222"],
        title="t",
        lesson="l",
        audience="coaches",
        public_angle="a",
        gates={},
        citations_private=[{"claim_type": "quoted", "excerpt_private": "older citation row"}],
    )
    assert "22222222-2222-2222-2222-222222222222" in packets.build_packet_prompt("s", cand)


def _hook(n, text, payoff="p004", moment="11111111-1111-1111-1111-111111111111"):
    return {
        "id": f"h{n}",
        "text": text,
        "question": f"Q{n}",
        "payoff_phrase_id": payoff,
        "moment_ids": [moment],
        "rationale": f"R{n}",
    }


def test_merge_keeps_what_is_usable_and_says_what_it_dropped():
    existing = [_hook(1, "Opening one.")]
    fresh = [
        {**_hook(9, "A different angle."), "id": "model-made-up-id"},
        _hook(9, "Opening one."),  # same text as the one already there
        _hook(9, "Pays off nowhere.", payoff="p099"),
        {**_hook(9, "No evidence."), "moment_ids": []},
    ]
    merged, dropped = packets.merge_hook_options(existing, fresh, phrase_count=8)
    assert [h["text"] for h in merged] == ["Opening one.", "A different angle."]
    # Ids are ours: a model id never overwrites an opening someone may be reading.
    assert merged[1]["id"] == "h2"
    assert len(dropped) == 3
    assert any("same as an opening already there" in d for d in dropped)
    assert any("payoff phrase is not in this script" in d for d in dropped)


def test_merge_stops_at_the_maximum():
    existing = [_hook(n, f"Opening {n}.") for n in range(1, packets.MAX_HOOK_OPTIONS + 1)]
    merged, dropped = packets.merge_hook_options(existing, [_hook(99, "One more.")], 8)
    assert len(merged) == packets.MAX_HOOK_OPTIONS
    assert merged == existing


def test_more_hooks_prompt_shows_the_existing_openings_and_the_ids_to_cite():
    from types import SimpleNamespace

    packet = SimpleNamespace(
        hook_options=[_hook(1, "Opening one.")],
        script_phrases=["Opening one.", "Second line.", "Third.", "Payoff line."],
    )
    cand = SimpleNamespace(
        title="t",
        lesson="l",
        citations_private=[
            {
                "moment_id": "11111111-1111-1111-1111-111111111111",
                "claim_type": "quoted",
                "excerpt_private": "synthetic",
            }
        ],
    )
    prompt = packets.build_more_hooks_prompt(packet, cand, 3)
    assert "WRITE 3 NEW OPENING(S)." in prompt
    assert "do not repeat or reword these" in prompt
    assert '"text": "Opening one."' in prompt
    assert '"phrase_id": "p004"' in prompt
    assert "11111111-1111-1111-1111-111111111111" in prompt


async def test_more_hooks_adds_a_version_and_keeps_the_opening_in_use(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        cand = await make_candidate(session, ws)
        fake_llm["output"] = good_output()
        first = await packets.build_packet(editorial_sessionmaker, ws, cand.id)
    assert first.packet is not None
    fake_llm["output"] = {
        "hook_options": [
            {
                "id": "whatever",
                "text": "Nobody tells a coach the sale is the first lesson.",
                "question": "Why would the sale teach anything?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "Starts on the belief, not the tactic.",
            }
        ]
    }
    outcome = await packets.more_hook_options(editorial_sessionmaker, ws, first.packet["id"])
    assert outcome.status == "ok", outcome.detail
    assert outcome.detail.startswith("1 new opening")
    packet = outcome.packet
    assert packet["version"] == first.packet["version"] + 1
    assert len(packet["hook_options"]) == 4
    # The opening in use does not move under someone who is reading it.
    assert packet["selected_hook_id"] == first.packet["selected_hook_id"]
    assert packet["script_phrases"] == first.packet["script_phrases"]
    assert packet["bullets"] == first.packet["bullets"]


def one_more_opening() -> dict:
    return {
        "hook_options": [
            {
                "id": "whatever",
                "text": "Nobody tells a coach the sale is the first lesson.",
                "question": "Why would the sale teach anything?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "Starts on the belief, not the tactic.",
            }
        ]
    }


async def test_more_openings_on_an_exported_script_make_a_ready_version(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        cand = await make_candidate(session, ws)
    first = await packets.build_packet(editorial_sessionmaker, ws, cand.id)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingPacket, uuid.UUID(first.packet["id"]))
        row.status = "exported"
        await s.commit()
    fake_llm["output"] = one_more_opening()

    outcome = await packets.more_hook_options(editorial_sessionmaker, ws, first.packet["id"])

    assert outcome.status == "ok", outcome.detail
    rows = await stored_versions(editorial_sessionmaker, ws)
    assert [(r.version, r.status) for r in rows] == [(1, "superseded"), (2, "ready")]


async def test_more_openings_rescan_the_script_instead_of_carrying_its_old_verdict(
    editorial_sessionmaker, fake_llm
):
    # A verdict stored before the scan looked for names says "clean" over a line
    # that names a participant. Carrying it to the next version kept it "ready".
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        cand = await make_candidate(session, ws, speaker="Dana Example")
    first = await packets.build_packet(editorial_sessionmaker, ws, cand.id)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingPacket, uuid.UUID(first.packet["id"]))
        phrases = list(row.script_phrases)
        phrases[3] = "Dana asked me the same thing."
        row.script_phrases = phrases
        await s.commit()
    fake_llm["output"] = one_more_opening()

    outcome = await packets.more_hook_options(editorial_sessionmaker, ws, first.packet["id"])

    assert outcome.status == "ok", outcome.detail
    assert ("script_phrases[3]", "participant_name") in flags(outcome.packet["public_safety"])
    assert outcome.packet["status"] == "draft"


async def test_more_hooks_refuses_evidence_from_another_idea(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        cand = await make_candidate(session, ws)
        fake_llm["output"] = good_output()
        first = await packets.build_packet(editorial_sessionmaker, ws, cand.id)
    fake_llm["output"] = {
        "hook_options": [
            {
                "id": "x",
                "text": "Borrowed from somewhere else.",
                "question": "?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["99999999-9999-9999-9999-999999999999"],
                "rationale": "r",
            }
        ]
    }
    outcome = await packets.more_hook_options(editorial_sessionmaker, ws, first.packet["id"])
    assert outcome.status == "failed"
    assert "outside this idea" in outcome.detail


async def test_a_finished_job_is_applied_instead_of_paid_for_twice(
    editorial_sessionmaker, fake_llm, monkeypatch
):
    """20-Sep: a deploy restarted the API while the worker was writing openings.
    The answer arrived, was billed, and nobody applied it - twice."""
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        cand = await make_candidate(session, ws)
        fake_llm["output"] = good_output()
        first = await packets.build_packet(editorial_sessionmaker, ws, cand.id)
    assert first.packet is not None

    # A hook job that already succeeded on the worker, its result unapplied.
    from tce.models.llm_job import LLMJob

    answer = {
        "hook_options": [
            {
                "id": "from-the-worker",
                "text": "If asking for money makes you flinch, stop charging.",
                "question": "Why would a coach tell someone to work for free?",
                "payoff_phrase_id": "p004",
                "moment_ids": ["11111111-1111-1111-1111-111111111111"],
                "rationale": "Opens on the prescription, not the discomfort.",
            }
        ]
    }
    job_id = uuid.uuid4()
    async with editorial_sessionmaker() as session:
        session.add(
            LLMJob(
                id=job_id,
                workspace_id=ws,
                job_type=packets.MORE_HOOKS_JOB_TYPE,
                agent_name=packets.MORE_HOOKS_AGENT,
                run_id=cand.id,
                status="succeeded",
                idempotency_key=f"more-hooks:{ws}:{uuid.uuid4()}",
                input_hash="x" * 64,
                prompt_version=packets.MORE_HOOKS_PROMPT_VERSION,
                requested_model="claude-opus-5",
                policy_model="claude-opus-5",
                request_json={},
                result_json=answer,
                completed_at=datetime(2026, 9, 20, 17, 45),
            )
        )
        await session.commit()

    calls = len(fake_llm["calls"])
    outcome = await packets.more_hook_options(editorial_sessionmaker, ws, first.packet["id"])
    assert outcome.status == "ok", outcome.detail
    assert len(fake_llm["calls"]) == calls, "the finished answer must not be paid for again"
    assert outcome.packet["version"] == first.packet["version"] + 1
    assert any(h["text"].startswith("If asking for money") for h in outcome.packet["hook_options"])
    assert outcome.job_id == job_id
