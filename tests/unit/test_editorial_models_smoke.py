import uuid
from datetime import datetime

from sqlalchemy import select

from tce.models.editorial import EvidenceSource, TopicCandidate
from tce.models.llm_job import LLMJob
from tests.editorial_db import editorial_session, editorial_sessionmaker  # noqa: F401


async def test_tables_roundtrip(editorial_session):
    ws = uuid.uuid4()
    src = EvidenceSource(
        workspace_id=ws, source_kind="fathom_meeting", external_id="m1",
        version_hash="a" * 64, payload_private={"turns": []},
    )
    editorial_session.add(src)
    editorial_session.add(TopicCandidate(
        workspace_id=ws, week_start=datetime(2026, 9, 7), moment_ids=[], title="t",
        lesson="l", audience="coaches", public_angle="a", gates={},
    ))
    editorial_session.add(LLMJob(
        workspace_id=ws, job_type="t", agent_name="a", idempotency_key="k",
        request_json={"messages": []}, policy_model="claude-opus-5", input_hash="h",
    ))
    await editorial_session.commit()
    rows = (await editorial_session.execute(select(EvidenceSource))).scalars().all()
    assert rows[0].payload_private == {"turns": []}
    job = (await editorial_session.execute(select(LLMJob))).scalar_one()
    assert job.status == "queued" and job.attempt_count == 0
