"""Doc export access verification: intended editors, nothing else. Synthetic only."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from tce.production.export import export_packet, verify_restricted

OWNER = {"type": "user", "role": "owner", "emailAddress": "owner@example.invalid"}
TEAM = ["editor@example.invalid", "second@example.invalid"]


def editor(email, role="writer", ptype="user"):
    return {"type": ptype, "role": role, "emailAddress": email}


def test_all_configured_editors_present_is_verified():
    ok, detail = verify_restricted([OWNER, editor(TEAM[0]), editor(TEAM[1].upper())], TEAM)
    assert ok is True and "all 2 configured team editor(s)" in detail


@pytest.mark.parametrize(
    "perms",
    [
        [OWNER],  # nobody shared
        [OWNER, editor(TEAM[0])],  # one editor missing
        [OWNER, editor(TEAM[0]), editor(TEAM[1], "reader")],
        [OWNER, editor(TEAM[0]), editor(TEAM[1], "commenter")],
    ],
)
def test_missing_or_non_editor_team_access_fails(perms):
    ok, detail = verify_restricted(perms, TEAM)
    assert ok is False and detail


@pytest.mark.parametrize(
    "extra",
    [
        {"type": "anyone", "role": "reader"},
        {"type": "domain", "role": "reader", "domain": "example.invalid"},
        editor("stranger@example.invalid"),
        editor("group@example.invalid", "reader", "group"),
    ],
)
def test_unintended_access_fails_even_with_all_editors(extra):
    ok, _ = verify_restricted([OWNER, editor(TEAM[0]), editor(TEAM[1]), extra], TEAM)
    assert ok is False


def test_owner_only_is_valid_only_for_an_empty_team_and_is_labelled():
    ok, detail = verify_restricted([OWNER], [])
    assert ok is True and "owner only (no team editors are configured)" in detail
    ok, _ = verify_restricted([OWNER], [" ", ""])
    assert ok is True
    assert verify_restricted([editor(TEAM[0])], [TEAM[0]])[0] is False  # no owner


class ReaderOnlyDrive:
    """Shares succeed but Drive reports the team member as reader."""

    async def available(self):
        return True, "fake"

    async def create_document(self, title):
        return {"id": "doc-1", "url": "https://docs.example.invalid/doc-1"}

    async def write_blocks(self, document_id, blocks):
        return None

    async def share_with_user(self, document_id, email, role):
        return None

    async def list_permissions(self, document_id):
        return [OWNER, editor(TEAM[0], "reader")]


async def test_failed_access_does_not_mark_packet_exported(tmp_path):
    packet = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        bullets=["b"],
        script_phrases=["p"],
        facebook_post=None,
        linkedin_post=None,
        status="ready",
        google_doc_id=None,
        google_doc_url=None,
        google_doc_access=None,
    )
    result = await export_packet(
        packet,
        None,
        client=ReaderOnlyDrive(),
        docx_dir=tmp_path,
        docx_url="/x",
        team_emails=[TEAM[0]],
    )
    assert result["status"] == "access_problem"
    assert packet.status == "ready"
    assert packet.google_doc_access["verified"] is False
    assert "not editor" in packet.google_doc_access["detail"]
    assert "1 team editor(s)" in packet.google_doc_access["intended"]
