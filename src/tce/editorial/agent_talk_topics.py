"""The topic row a filmed talk with an agent hangs on (3-Oct, contract C4).

Every library video belongs to a topic row (recording_uploads.candidate_id is NOT NULL),
and the library names a video by its topic's title. A voice call with an agent he filmed
has no idea behind it, so it gets a row of its own kind: origin "agent_talk", status
"recorded", the title "Talk with <Agent>, <d Mon>", no evidence, no lesson.

This is the only module besides the selector and the calibration writer that creates
topic rows (tests/unit/test_no_ungated_topic_source.py). It can write nothing else: the
origin and status are pinned here, and every list of ideas (the inbox, the week's
candidates, the selector's "already on his list") leaves that origin out, so no topic
reaches him through this door.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tce.editorial.common import ORIGIN_AGENT_TALK
from tce.models.editorial import TopicCandidate
from tce.production import agent_talks


def talk_topic(workspace_id: uuid.UUID, agent: str, started_at: datetime) -> TopicCandidate:
    """A new topic row naming one filmed talk; the caller adds and flushes it."""
    name = agent_talks.display_name(agent)
    return TopicCandidate(
        workspace_id=workspace_id,
        week_start=agent_talks.week_label(started_at),
        moment_ids=[],
        title=agent_talks.talk_title(agent, started_at),
        lesson="",
        audience="both",
        reasons_to_care=[],
        public_angle="",
        gates={},
        citations_private=[],
        status="recorded",
        origin=ORIGIN_AGENT_TALK,
        editor_notes=f"A voice call with {name}, filmed on the call's page.",
    )
