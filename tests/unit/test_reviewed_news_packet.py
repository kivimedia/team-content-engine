"""In-session briefs still use the normal script, evidence and safety checks."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from tce.editorial import packets, selector
from tce.models.editorial import RecordingPacket
from tce.settings import settings
from tests.unit.test_editorial_packets import good_output
from tests.unit.test_news_recovery_policy import WS, _candidate, _reviewed_pool


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    return WS


async def prepared(session, owner):
    pool = await _reviewed_pool(session)
    candidate = await selector.save_reviewed_news_candidate(
        session, owner, _candidate([p.id for p in pool]), pool, "packet-review",
    )
    data = good_output()
    for hook in data["hook_options"]:
        hook["moment_ids"] = [p.id for p in pool]
    return candidate, data


@pytest.mark.asyncio
async def test_reviewed_packet_is_ready_idempotent_and_never_fabricates_a_job(
    editorial_session, owner,
):
    candidate, data = await prepared(editorial_session, owner)
    packet = await packets.save_reviewed_news_packet(
        editorial_session, owner, candidate.id, data, review_ref="packet-review",
    )
    again = await packets.save_reviewed_news_packet(
        editorial_session, owner, candidate.id, data, review_ref="packet-review",
    )
    assert packet.id == again.id and packet.status == "ready"
    assert packet.job_id is None
    assert packet.public_safety["editor_review"]["demo_tested"] is False
    assert len((await editorial_session.execute(select(RecordingPacket))).scalars().all()) == 1
    with pytest.raises(ValueError, match="already has a script"):
        await packets.save_reviewed_news_packet(
            editorial_session, owner, candidate.id, data, review_ref="another-review",
        )


@pytest.mark.asyncio
async def test_reviewed_packet_refuses_unselected_evidence_and_expiry(editorial_session, owner):
    candidate, data = await prepared(editorial_session, owner)
    forged = deepcopy(data)
    forged["hook_options"][0]["moment_ids"] = ["11111111-1111-1111-1111-111111111111"]
    with pytest.raises(ValueError, match="outside"):
        await packets.save_reviewed_news_packet(
            editorial_session, owner, candidate.id, forged, review_ref="packet-review",
        )
    candidate.expires_at = datetime.utcnow() - timedelta(days=1)
    with pytest.raises(ValueError, match="refreshed"):
        await packets.save_reviewed_news_packet(
            editorial_session, owner, candidate.id, data, review_ref="packet-review",
        )
    assert not (await editorial_session.execute(select(RecordingPacket))).scalars().all()
