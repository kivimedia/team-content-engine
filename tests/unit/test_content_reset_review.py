"""Independent integration review regressions for the content reset.

Synthetic data only. These checks exercise risks found while reviewing the four
Claude work packages; they are not production implementation or pilot fixtures.
"""

import ast
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from tce.api import private_access
from tce.api.routers import pipeline
from tce.db.workspace_filter import set_workspace_context
from tce.evidence.fathom import FathomClient
from tce.evidence.moments import validate_meeting_moment
from tce.llm import queue
from tce.llm.provider import LLMPolicyError, LLMRequest, compute_idempotency_key
from tce.llm.queue import verify_receipt
from tce.models.editorial import EvidenceMoment, EvidenceSource, RecordingPacket, TopicCandidate
from tce.production.retakes import plan_edit
from tce.services.repo_service import RepoService


def test_application_and_maintenance_scripts_do_not_construct_metered_text_clients():
    root = Path(__file__).resolve().parents[2]
    found = []
    for folder in (root / "src", root / "scripts"):
        for path in folder.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in {"AsyncAnthropic", "Anthropic"}:
                    found.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not found, "Direct metered text clients remain: " + ", ".join(found)


async def test_proxy_authenticated_editor_cannot_choose_another_workspace(monkeypatch):
    own_workspace = uuid.uuid4()
    monkeypatch.setattr(private_access.settings, "private_access_key", SecretStr("synthetic-key"))
    monkeypatch.setattr(private_access.settings, "editor_default_workspace_id", str(own_workspace))
    try:
        try:
            resolved = await private_access.require_private_workspace(
                authorization=None,
                x_tce_editor_key="synthetic-key",
                x_workspace_id=str(uuid.uuid4()),
            )
        except HTTPException as exc:
            assert exc.status_code in {400, 403}
        else:
            assert resolved == own_workspace, (
                "The proxy editor key must bind the browser to its configured workspace"
            )
    finally:
        set_workspace_context(None)


@pytest.mark.parametrize("legacy_feature_enabled", [False, True])
async def test_unverified_cutsense_pipeline_cannot_bypass_subscription_policy(
    monkeypatch, legacy_feature_enabled
):
    monkeypatch.setattr(pipeline.settings, "llm_provider", "subscription")
    monkeypatch.setattr(pipeline.settings, "weekly_walking_pipeline", legacy_feature_enabled)

    def discard_background(coroutine):
        coroutine.close()
        return None

    monkeypatch.setattr(pipeline.asyncio, "create_task", discard_background)
    try:
        await pipeline.trigger_pipeline(
            pipeline.PipelineRunRequest(workflow="weekly_walking_split_edit"), db=None
        )
    except HTTPException as exc:
        assert exc.status_code in {403, 409, 503}
    else:
        pytest.fail("The legacy pipeline admitted unverified downstream CutSense LLM use")


@pytest.mark.parametrize("delete_working_file", [False, True])
async def test_legacy_repo_snippet_reads_the_requested_commit(tmp_path, delete_working_file):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    source = tmp_path / "example.py"
    source.write_text("# Historical committed behavior\n", encoding="utf-8")
    git("add", "example.py")
    git(
        "-c",
        "user.name=Synthetic Review",
        "-c",
        "user.email=review@example.test",
        "commit",
        "-m",
        "Synthetic provenance fixture",
    )
    commit = git("rev-parse", "HEAD")
    if delete_working_file:
        source.unlink()
    else:
        source.write_text(
            "# Uncommitted behavior that did not exist at that SHA\n", encoding="utf-8"
        )
    result = await RepoService(cache_dir=tmp_path / "cache").snippet_for_commit(tmp_path, commit)
    assert result is not None
    assert result["commit_sha"] == commit
    assert result["excerpt"] == "# Historical committed behavior"


def test_distinct_complete_ideas_are_not_silently_deleted_as_retakes():
    first = "I coach small business owners to make better decisions."
    second = "I coach small business owners to build better teams."
    plan = plan_edit(
        [
            {"start_s": 0, "end_s": 4, "text": first},
            {"start_s": 5, "end_s": 9, "text": second},
        ],
        [first],
    )
    silently_deleted = bool(plan["dropped"]) and plan["meaning_check"]["status"] == "ok"
    assert not silently_deleted, "Distinct substance was removed while meaning was marked preserved"


def test_quote_cannot_be_attributed_to_someone_else_who_also_speaks_in_the_span():
    turns = [
        {
            "speaker": "Host",
            "start_s": 0,
            "end_s": 5,
            "text": "Let us examine the decision you made.",
            "speaker_confidence": "high",
        },
        {
            "speaker": "Guest",
            "start_s": 5,
            "end_s": 10,
            "text": "My customer changed her plans.",
            "speaker_confidence": "high",
        },
    ]
    fields, _ = validate_meeting_moment(
        {
            "span_start_s": 0,
            "span_end_s": 10,
            "speaker": "Host",
            "excerpt_private": "My customer changed her plans.",
            "lesson_summary": "Respond to changing plans.",
            "claim_type": "quoted",
        },
        turns,
    )
    assert fields is None, "The quote belongs to Guest, even though Host also speaks in this span"


def test_explicit_job_keys_are_scoped_to_the_workspace():
    def request(workspace):
        return LLMRequest(
            job_type="packet",
            agent_name="review",
            messages=[{"role": "user", "content": "x"}],
            workspace_id=workspace,
            idempotency_key="weekly-packet-1",
        )

    assert compute_idempotency_key(request(uuid.uuid4())) != compute_idempotency_key(
        request(uuid.uuid4())
    ), "Two workspaces must never reuse one another's explicitly named job"


async def test_reusing_a_job_key_with_changed_input_reports_a_conflict(editorial_session):
    workspace = uuid.uuid4()
    first = LLMRequest(
        job_type="packet",
        agent_name="review",
        workspace_id=workspace,
        messages=[{"role": "user", "content": "First source passage"}],
        idempotency_key="one-request",
    )
    await queue.enqueue(editorial_session, first)
    await editorial_session.commit()
    changed = LLMRequest(
        job_type="packet",
        agent_name="review",
        workspace_id=workspace,
        messages=[{"role": "user", "content": "A materially different source passage"}],
        idempotency_key="one-request",
    )
    try:
        await queue.enqueue(editorial_session, changed)
    except (LLMPolicyError, queue.QueueError, ValueError):
        return
    pytest.fail("Changed input silently reused an earlier request instead of reporting a conflict")


async def test_enqueue_recovers_when_another_request_wins_the_insert_race(
    editorial_sessionmaker, monkeypatch
):
    request = LLMRequest(
        job_type="packet",
        agent_name="review",
        workspace_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "One shared request"}],
    )
    async with editorial_sessionmaker() as first_session:
        first = await queue.enqueue(first_session, request)
        await first_session.commit()
        winner_id = first.id

    original_lookup = queue._get_by_key
    first_read = True

    async def initially_missing(session, key):
        nonlocal first_read
        if first_read:
            # Simulate the first read happening just before the other request commits.
            first_read = False
            return None
        return await original_lookup(session, key)

    monkeypatch.setattr(queue, "_get_by_key", initially_missing)
    async with editorial_sessionmaker() as second_session:
        reused = await queue.enqueue(second_session, request)
        assert reused.id == winner_id


async def test_source_collection_recovers_when_another_run_inserts_the_same_source(
    editorial_sessionmaker, monkeypatch
):
    from tce.evidence.collect import upsert_source

    workspace = uuid.uuid4()
    data = {
        "external_id": "synthetic/repo@one-business-change",
        "version_hash": "a" * 64,
        "payload": {"summary": "Synthetic source"},
    }
    async with editorial_sessionmaker() as winner_session:
        _, winner = await upsert_source(
            winner_session, workspace, "github_commit_group", data, uuid.uuid4()
        )
        await winner_session.commit()
        winner_id = winner.id

    async with editorial_sessionmaker() as retry_session:
        execute = retry_session.execute
        first_read = True

        class MissingBeforeConcurrentCommit:
            def scalar_one_or_none(self):
                return None

        async def initially_missing(statement, *args, **kwargs):
            nonlocal first_read
            if first_read:
                first_read = False
                return MissingBeforeConcurrentCommit()
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(retry_session, "execute", initially_missing)
        state, reused = await upsert_source(
            retry_session, workspace, "github_commit_group", data, uuid.uuid4()
        )
        await retry_session.commit()
        assert reused.id == winner_id
        assert state == "unchanged"


@pytest.mark.parametrize("model", [EvidenceSource, EvidenceMoment, TopicCandidate, RecordingPacket])
def test_private_evidence_workspace_is_required_in_database(model):
    assert model.__table__.c.workspace_id.nullable is False


@pytest.mark.parametrize("team_permission", [None, "reader"])
def test_doc_export_requires_intended_team_editor_access(team_permission):
    from tce.production.export import verify_restricted

    permissions = [{"type": "user", "role": "owner", "emailAddress": "owner@example.invalid"}]
    if team_permission:
        permissions.append(
            {"type": "user", "role": team_permission, "emailAddress": "editor@example.invalid"}
        )
    verified, _ = verify_restricted(permissions, ["editor@example.invalid"])
    assert verified is False, "Intended team editor access was not established"


@pytest.mark.parametrize("other_workspace", [False, True])
async def test_publication_receipt_cannot_attach_another_candidates_packet(
    editorial_session, other_workspace
):
    from fastapi import HTTPException
    from tce.api.routers.production import PublicationCreate, create_publication

    own = uuid.uuid4()
    other = uuid.uuid4() if other_workspace else own
    fields = dict(
        moment_ids=[],
        lesson="Synthetic lesson",
        audience="coaches",
        public_angle="Synthetic angle",
        gates={},
    )
    candidate = TopicCandidate(
        workspace_id=own, week_start=datetime(2000, 1, 3), title="Synthetic own topic", **fields
    )
    foreign_candidate = TopicCandidate(
        workspace_id=other, week_start=datetime(2000, 1, 3), title="Synthetic other topic", **fields
    )
    editorial_session.add_all([candidate, foreign_candidate])
    await editorial_session.flush()
    foreign_packet = RecordingPacket(
        workspace_id=other,
        candidate_id=foreign_candidate.id,
        bullets=["Synthetic bullet"] * 5,
        script_phrases=["Synthetic script"],
    )
    editorial_session.add(foreign_packet)
    await editorial_session.commit()
    body = PublicationCreate(
        platform="linkedin", external_post_id="synthetic-unit-receipt", packet_id=foreign_packet.id
    )
    try:
        await create_publication(candidate.id, body, own, editorial_session)
    except HTTPException as exc:
        assert exc.status_code in {403, 404, 422}
        return
    pytest.fail("Receipt accepted a packet belonging to another candidate or workspace")


@pytest.mark.parametrize("missing", ["auth_method", "api_provider"])
def test_subscription_receipt_requires_authentication_proof(missing):
    receipt = {
        "api_key_source": "none",
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "models": {"claude-opus-5": {"output_tokens": 5}},
    }
    receipt.pop(missing)
    assert verify_receipt(receipt) is not None, "Missing authentication proof must fail closed"


async def test_weekly_listing_finds_recordings_created_more_than_three_days_late():
    start = datetime(2026, 8, 1, tzinfo=UTC)
    end = datetime(2026, 8, 8, tzinfo=UTC)
    created = datetime(2026, 8, 20, tzinfo=UTC)
    late = {
        "recording_id": "synthetic-late-recording",
        "recording_start_time": "2026-08-04T10:00:00Z",
        "created_at": "2026-08-20T10:00:00Z",
        "transcript": [],
    }

    def respond(request):
        upper = request.url.params.get("created_before")
        excluded = upper and datetime.fromisoformat(upper.replace("Z", "+00:00")) < created
        return httpx.Response(200, json={"items": [] if excluded else [late], "next_cursor": None})

    async with FathomClient(
        "synthetic-test-key", "https://fathom.invalid", transport=httpx.MockTransport(respond)
    ) as client:
        listing = await client.list_meetings(start, end)
    assert any(m["recording_id"] == late["recording_id"] for m in listing.meetings), (
        "A past week must remain reconcilable when its recordings arrive much later"
    )
