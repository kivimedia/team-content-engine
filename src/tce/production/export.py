"""Recording-doc export: Google Doc when a server-side connection exists, else a private .docx.

The document is a large-type walking script: bullets first, then one script phrase
per paragraph, then the Facebook and LinkedIn adaptations. Citations are private
editor material and are NEVER written into the document.

Access policy: packets are unpublished drafts, so the Doc stays restricted to the
owner (plus explicitly configured team emails). Nothing ever adds an `anyone` or
`domain` permission, and the result is only called verified after the permissions
are read back from Drive.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import ExportIntent


@dataclass
class DocBlock:
    kind: str  # title | heading | bullet | phrase | body
    text: str


def _day(value: Any) -> str:
    """"Saturday 26 September" from an ISO string, or the raw value if it will not parse."""
    if not value:
        return ""
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return f"{parsed:%A %d %B}".replace(" 0", " ")


def news_blocks(block: dict[str, Any] | None) -> list[DocBlock]:
    """The news section of a Doc, or nothing for an evergreen packet.

    Three headings for three lists, in this order and never merged, because the
    whole point of keeping them apart in the data is that he can see, while
    recording, which sentence is the announcement's and which is his. The private
    anchors (which call, which commit) are deliberately absent: this Doc is shared
    with the team, and the anchor's job is to earn the right to speak, privately.
    """
    if not block:
        return []
    out: list[DocBlock] = []
    source = ", ".join(
        part
        for part in (block.get("publisher"), _day(block.get("published_at")))
        if part
    )
    out.append(DocBlock("heading", "The news, before you record"))
    if block.get("what_happened"):
        out.append(DocBlock("body", str(block["what_happened"])))
    if source or block.get("primary_url"):
        out.append(
            DocBlock(
                "body",
                "Source: " + (source or "the announcement")
                + (f" - {block['primary_url']}" if block.get("primary_url") else ""),
            )
        )
    if block.get("expires_at"):
        out.append(DocBlock("body", f"Worth saying until {_day(block['expires_at'])}."))

    facts = block.get("confirmed_facts") or []
    if facts:
        out.append(DocBlock("heading", "What is actually confirmed"))
        for fact in facts:
            claim = str(fact.get("claim") or "").strip()
            quote = str(fact.get("quote") or "").strip()
            if claim:
                out.append(DocBlock("bullet", f'{claim} ("{quote}")' if quote else claim))
    reading = block.get("ziv_interpretation") or []
    if reading:
        out.append(DocBlock("heading", "Your reading of it (say this as yours, not as fact)"))
        out += [DocBlock("bullet", str(r)) for r in reading if str(r).strip()]
    ahead = block.get("predictions") or []
    if ahead:
        out.append(DocBlock("heading", "What you expect next (say this as a guess)"))
        out += [DocBlock("bullet", str(p)) for p in ahead if str(p).strip()]
    return out


def packet_blocks(packet: Any, candidate: Any | None = None) -> list[DocBlock]:
    title = (getattr(candidate, "title", None) or "Recording packet").strip()
    blocks = [DocBlock("title", f"{title} (v{getattr(packet, 'version', 1)})")]
    blocks += news_blocks(getattr(packet, "news_block", None))
    blocks.append(DocBlock("heading", "Walking bullets"))
    blocks += [DocBlock("bullet", b) for b in (packet.bullets or []) if str(b).strip()]
    blocks.append(DocBlock("heading", "Script, one phrase per line"))
    blocks += [DocBlock("phrase", p) for p in (packet.script_phrases or []) if str(p).strip()]
    if packet.facebook_post:
        blocks.append(DocBlock("heading", "Facebook adaptation"))
        blocks += [
            DocBlock("body", para) for para in packet.facebook_post.split("\n") if para.strip()
        ]
    if packet.linkedin_post:
        blocks.append(DocBlock("heading", "LinkedIn adaptation"))
        blocks += [
            DocBlock("body", para) for para in packet.linkedin_post.split("\n") if para.strip()
        ]
    return blocks


def build_docx(blocks: list[DocBlock], out_path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    sizes = {"title": 30, "heading": 24, "bullet": 22, "phrase": 26, "body": 16}
    for block in blocks:
        para = doc.add_paragraph(style="List Bullet" if block.kind == "bullet" else None)
        run = para.add_run(block.text)
        run.font.size = Pt(sizes[block.kind])
        run.bold = block.kind in {"title", "heading"}
        para.paragraph_format.space_after = Pt(14 if block.kind == "phrase" else 8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


class GoogleDocsClient(Protocol):
    async def available(self) -> tuple[bool, str]: ...
    async def create_document(self, title: str) -> dict[str, str]: ...
    async def write_blocks(self, document_id: str, blocks: list[DocBlock]) -> None: ...
    async def list_permissions(self, document_id: str) -> list[dict[str, Any]]: ...
    async def share_with_user(self, document_id: str, email: str, role: str) -> None: ...
    async def find_document_by_marker(self, marker: str) -> dict[str, str] | None: ...


def _doc_requests(blocks: list[DocBlock]) -> list[dict[str, Any]]:
    """Google Docs batchUpdate requests, inserted at the end of the body in order."""
    sizes = {"title": 30, "heading": 24, "bullet": 22, "phrase": 26, "body": 16}
    requests: list[dict[str, Any]] = []
    index = 1
    for block in blocks:
        text = block.text.replace("\n", " ") + "\n"
        requests.append({"insertText": {"location": {"index": index}, "text": text}})
        end = index + len(text)
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": index, "endIndex": end - 1},
                    "textStyle": {
                        "fontSize": {"magnitude": sizes[block.kind], "unit": "PT"},
                        "bold": block.kind in {"title", "heading"},
                    },
                    "fields": "fontSize,bold",
                }
            }
        )
        if block.kind == "bullet":
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": index, "endIndex": end - 1},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )
        index = end
    return requests


class GwsDocsClient:
    """Google Docs via the `gws` CLI already authenticated on the server host."""

    def __init__(self, binary: str = "gws") -> None:
        self.binary = binary

    async def _run(self, *args: str) -> Any:
        exe = shutil.which(self.binary)
        if not exe:
            raise RuntimeError("gws CLI not found")
        proc = await asyncio.create_subprocess_exec(
            exe, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            # stderr can echo request bodies; keep only the first line and cap it
            first = (err.decode(errors="replace").strip().splitlines() or ["no output"])[0]
            raise RuntimeError(f"gws {args[0]} {args[1]} {args[2]} failed: {first[:200]}")
        text = out.decode(errors="replace").strip()
        return json.loads(text) if text else {}

    async def available(self) -> tuple[bool, str]:
        if not shutil.which(self.binary):
            return False, "gws CLI is not installed on the TCE server"
        return True, "gws CLI present"

    async def create_document(self, title: str) -> dict[str, str]:
        body = {"name": title, "mimeType": "application/vnd.google-apps.document"}
        data = await self._run(
            "drive",
            "files",
            "create",
            "--json",
            json.dumps(body),
            "--params",
            json.dumps({"fields": "id,webViewLink"}),
        )
        doc_id = data["id"]
        return {
            "id": doc_id,
            "url": data.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    async def find_document_by_marker(self, marker: str) -> dict[str, str] | None:
        data = await self._run(
            "drive",
            "files",
            "list",
            "--params",
            json.dumps(
                {
                    "q": f"name contains '{marker}' and trashed = false",
                    "fields": "files(id,name,webViewLink)",
                    "pageSize": 10,
                }
            ),
        )
        matches = [item for item in (data.get("files") or []) if marker in item.get("name", "")]
        if len(matches) > 1:
            raise RuntimeError(f"multiple Google Docs match export marker {marker}")
        if not matches:
            return None
        item = matches[0]
        return {
            "id": item["id"],
            "url": item.get("webViewLink")
            or f"https://docs.google.com/document/d/{item['id']}/edit",
        }

    async def write_blocks(self, document_id: str, blocks: list[DocBlock]) -> None:
        await self._run(
            "docs",
            "documents",
            "batchUpdate",
            "--params",
            json.dumps({"documentId": document_id}),
            "--json",
            json.dumps({"requests": _doc_requests(blocks)}),
        )

    async def list_permissions(self, document_id: str) -> list[dict[str, Any]]:
        data = await self._run(
            "drive",
            "permissions",
            "list",
            "--params",
            json.dumps(
                {
                    "fileId": document_id,
                    "fields": "permissions(id,type,role,emailAddress,domain)",
                }
            ),
        )
        return list(data.get("permissions") or [])

    async def share_with_user(self, document_id: str, email: str, role: str) -> None:
        await self._run(
            "drive",
            "permissions",
            "create",
            "--params",
            json.dumps({"fileId": document_id, "sendNotificationEmail": False}),
            "--json",
            json.dumps({"type": "user", "role": role, "emailAddress": email}),
        )


# Drive roles that let a team member edit the Doc.
EDITOR_ROLES = frozenset({"writer", "organizer", "fileOrganizer", "owner"})


def verify_restricted(
    permissions: list[dict[str, Any]], team_emails: list[str]
) -> tuple[bool, str]:
    """True only when the read-back permissions are exactly what was intended.

    Intended = one owner, every configured team email as an editor, nobody else, no
    `anyone`/`domain` access. An empty team list means owner only, and says so.
    """
    intended = {e.strip().lower() for e in team_emails if e and e.strip()}
    problems = []
    editors: set[str] = set()
    for perm in permissions:
        ptype = perm.get("type")
        role = perm.get("role")
        email = (perm.get("emailAddress") or "").lower()
        if ptype in {"anyone", "domain"}:
            problems.append(f"{ptype} permission present ({role})")
        elif role == "owner":
            continue
        elif ptype in {"user", "group"} and email in intended:
            if role in EDITOR_ROLES:
                editors.add(email)
            else:
                problems.append(f"team member has {role} access, not editor")
        else:
            problems.append(f"unexpected {ptype} permission ({role})")
    owners = [p for p in permissions if p.get("role") == "owner"]
    if not owners:
        problems.append("no owner permission returned")
    missing = intended - editors
    if missing:
        problems.append(
            f"{len(missing)} of {len(intended)} configured team editor(s) have no editor access"
        )
    if problems:
        return False, "; ".join(problems)
    if not intended:
        return True, (
            f"Read back {len(permissions)} permission(s): owner only (no team editors are "
            "configured); no link sharing"
        )
    return True, (
        f"Read back {len(permissions)} permission(s): owner plus all {len(intended)} configured "
        "team editor(s); no link sharing"
    )


async def export_packet(
    packet: Any,
    candidate: Any | None,
    *,
    client: GoogleDocsClient | None,
    docx_dir: Path,
    docx_url: str,
    team_emails: list[str] | None = None,
) -> dict[str, Any]:
    """Export and return a result dict. Mutates packet google_doc_* fields."""
    team_emails = [e.strip() for e in (team_emails or []) if e.strip()]
    intended = (
        f"restricted: owner and {len(team_emails)} team editor(s)"
        if team_emails
        else "restricted: owner only (no team editors configured)"
    ) + ", no link sharing"
    blocks = packet_blocks(packet, candidate)

    reason = "No Google connection is configured for the TCE server"
    if client is not None:
        ok, detail = await client.available()
        if ok:
            doc = await client.create_document(blocks[0].text)
            packet.google_doc_id = doc["id"]
            packet.google_doc_url = doc["url"]
            await client.write_blocks(doc["id"], blocks)
            for email in team_emails:
                await client.share_with_user(doc["id"], email, "writer")
            perms = await client.list_permissions(doc["id"])
            verified, vdetail = verify_restricted(perms, team_emails)
            packet.google_doc_access = {
                "intended": intended,
                "verified": verified,
                "detail": vdetail,
                "status": "exported" if verified else "access_problem",
            }
            if verified:
                # an unverified Doc is not an export: the packet keeps its prior status
                packet.status = "exported"
            return {
                "status": "exported" if verified else "access_problem",
                "google_doc_id": doc["id"],
                "google_doc_url": doc["url"],
                "access": packet.google_doc_access,
            }
        reason = detail

    filename = f"packet-{packet.id}-v{packet.version}.docx"
    build_docx(blocks, docx_dir / filename)
    packet.google_doc_access = {
        "intended": intended,
        "verified": False,
        "detail": f"Not exported to Google: {reason}. A private .docx was generated instead.",
        "status": "not_connected",
        "docx_url": docx_url,
    }
    return {
        "status": "not_connected",
        "reason": reason,
        "docx_url": docx_url,
        "access": packet.google_doc_access,
    }


async def export_packet_durable(
    session: AsyncSession,
    packet: Any,
    candidate: Any | None,
    *,
    client: GoogleDocsClient | None,
    docx_dir: Path,
    docx_url: str,
    team_emails: list[str] | None = None,
) -> dict[str, Any]:
    """Export with a durable identity written before external side effects.

    The document id is committed immediately after discovery or creation. A restart
    therefore resumes sharing and access readback instead of creating another Doc.
    """
    marker = f"TCE-{packet.id}-v{packet.version}"
    intent = (
        await session.execute(
            select(ExportIntent).where(
                ExportIntent.workspace_id == packet.workspace_id,
                ExportIntent.packet_id == packet.id,
                ExportIntent.packet_version == packet.version,
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        intent = ExportIntent(
            workspace_id=packet.workspace_id,
            packet_id=packet.id,
            packet_version=packet.version,
            marker=marker,
            status="pending",
        )
        session.add(intent)
        await session.commit()
    if intent.status == "verified" and intent.document_id:
        packet.google_doc_id = intent.document_id
        packet.google_doc_url = intent.document_url
        access = intent.access_readback
        if client is not None:
            ok, _ = await client.available()
            if ok:
                emails = [e.strip() for e in (team_emails or []) if e.strip()]
                permissions = await client.list_permissions(intent.document_id)
                verified, detail = verify_restricted(permissions, emails)
                access = {
                    "intended": (
                        f"restricted: owner and {len(emails)} team editor(s)"
                        if emails
                        else "restricted: owner only (no team editors configured)"
                    )
                    + ", no link sharing",
                    "verified": verified,
                    "detail": detail,
                    "status": "exported" if verified else "access_problem",
                }
                intent.access_readback = access
                intent.status = "verified" if verified else "access_problem"
                await session.commit()
        packet.google_doc_access = access
        if (access or {}).get("verified"):
            packet.status = "exported"
        return {
            "status": "exported" if (access or {}).get("verified") else "access_problem",
            "google_doc_id": intent.document_id,
            "google_doc_url": intent.document_url,
            "access": access,
            "resumed": True,
        }
    intent.attempt_count = int(intent.attempt_count or 0) + 1
    intent.status = "running"
    await session.commit()

    if client is None:
        result = await export_packet(
            packet,
            candidate,
            client=None,
            docx_dir=docx_dir,
            docx_url=docx_url,
            team_emails=team_emails,
        )
        intent.status = "not_connected"
        intent.access_readback = result.get("access")
        await session.commit()
        return result

    ok, detail = await client.available()
    if not ok:
        return await export_packet_durable(
            session,
            packet,
            candidate,
            client=None,
            docx_dir=docx_dir,
            docx_url=docx_url,
            team_emails=team_emails,
        )

    try:
        doc = None
        if intent.document_id:
            doc = {"id": intent.document_id, "url": intent.document_url}
        else:
            finder = getattr(client, "find_document_by_marker", None)
            if finder is not None:
                doc = await finder(marker)
            if doc is None:
                title = packet_blocks(packet, candidate)[0].text
                doc = await client.create_document(f"{title} [{marker}]")
            intent.document_id = doc["id"]
            intent.document_url = doc["url"]
            intent.status = "created"
            await session.commit()

        blocks = packet_blocks(packet, candidate)
        await client.write_blocks(doc["id"], blocks)
        emails = [e.strip() for e in (team_emails or []) if e.strip()]
        for email in emails:
            await client.share_with_user(doc["id"], email, "writer")
        permissions = await client.list_permissions(doc["id"])
        verified, readback = verify_restricted(permissions, emails)
        access = {
            "intended": (
                f"restricted: owner and {len(emails)} team editor(s)"
                if emails
                else "restricted: owner only (no team editors configured)"
            )
            + ", no link sharing",
            "verified": verified,
            "detail": readback,
            "status": "exported" if verified else "access_problem",
        }
        intent.access_readback = access
        intent.status = "verified" if verified else "access_problem"
        packet.google_doc_id = doc["id"]
        packet.google_doc_url = doc["url"]
        packet.google_doc_access = access
        if verified:
            packet.status = "exported"
        await session.commit()
        return {
            "status": "exported" if verified else "access_problem",
            "google_doc_id": doc["id"],
            "google_doc_url": doc["url"],
            "access": access,
        }
    except Exception as exc:
        intent.status = "failed"
        intent.error_detail = f"{type(exc).__name__}: {exc}"[:1000]
        await session.commit()
        raise
