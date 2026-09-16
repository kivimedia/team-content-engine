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


@dataclass
class DocBlock:
    kind: str  # title | heading | bullet | phrase | body
    text: str


def packet_blocks(packet: Any, candidate: Any | None = None) -> list[DocBlock]:
    title = (getattr(candidate, "title", None) or "Recording packet").strip()
    blocks = [DocBlock("title", f"{title} (v{getattr(packet, 'version', 1)})")]
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


def verify_restricted(
    permissions: list[dict[str, Any]], team_emails: list[str]
) -> tuple[bool, str]:
    allowed = {e.lower() for e in team_emails}
    problems = []
    for perm in permissions:
        ptype = perm.get("type")
        if ptype in {"anyone", "domain"}:
            problems.append(f"{ptype} permission present ({perm.get('role')})")
        elif ptype in {"user", "group"} and perm.get("role") != "owner":
            email = (perm.get("emailAddress") or "").lower()
            if email not in allowed:
                problems.append(f"unexpected {ptype} permission ({perm.get('role')})")
    owners = [p for p in permissions if p.get("role") == "owner"]
    if not owners:
        problems.append("no owner permission returned")
    if problems:
        return False, "; ".join(problems)
    shared = len([p for p in permissions if p.get("role") != "owner"])
    return True, f"Read back {len(permissions)} permission(s): owner only" + (
        f" plus {shared} team member(s)" if shared else ""
    ) + "; no link sharing"


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
    intended = "restricted: owner" + (" and team" if team_emails else " only") + ", no link sharing"
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
