"""Operator command to create a workspace and email a one-use onboarding link.

No invitation token or password is printed or stored in plaintext.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from tce.db.session import async_session
from tce.standalone.auth import hash_password, new_token, token_hash
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneInvite,
    StandaloneMembership,
    StandaloneWorkspace,
)


def _public_url() -> str:
    raw = os.environ.get("TCE_STANDALONE_PUBLIC_URL", "").rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("TCE_STANDALONE_PUBLIC_URL must be a clean HTTPS origin")
    return raw


def invitation_message(from_email: str, email: str, name: str, link: str, public_url: str) -> dict:
    """Build the client-facing invitation without sending it."""
    safe_name = html.escape(name.strip())
    safe_link = html.escape(link, quote=True)
    safe_guide = html.escape(f"{public_url}/guide", quote=True)
    return {
        "from": from_email,
        "to": [email],
        "subject": f"Your {name.strip()} content studio is ready",
        "html": (
            f"<p>Hi {safe_name},</p>"
            "<p>Your private TCE studio is ready. It helps you find ideas in your own material, "
            "shape scripts in your voice, record and review video, "
            "and take the finished file with you. "
            "The studio does not publish on your behalf.</p>"
            f'<p><a href="{safe_link}">Activate your private studio</a>. '
            "This one-time link expires in seven days. "
            "Set a password of at least 16 characters.</p>"
            "<p>Onboarding asks for three idea sources and a filter and comments for each. "
            "You can upload book or course material and examples of your voice, "
            "then choose your AI connections. "
            "Everything in onboarding can be changed later in Settings.</p>"
            f'<p><a href="{safe_guide}">Read the setup and recording guide</a> before you begin. '
            "You can use the studio in a browser on your computer or phone. "
            "For the first recording, allow camera and microphone access "
            "and make a short test take.</p>"
            "<p>After recording, download your selected video. "
            "Email delivery to your own verified address will be available "
            "once the studio sender is enabled. The guide explains terminal delivery too.</p>"
            "<p>For the pilot, please reply after a short test with your device and browser, "
            "whether camera and microphone permission worked, "
            "whether the test take played with sound, and whether your "
            "download opened outside the studio. If you use email delivery, "
            "include whether the message "
            "and video arrived. Please do not send us your password or API keys.</p>"
            "<p>Reply to this email if you need help with setup.</p>"
        ),
    }


async def invite_client(email: str, name: str, slug: str, timezone: str) -> None:
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid client email")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?", slug):
        raise ValueError("Workspace slug must use lowercase letters, numbers and hyphens")
    if not name.strip() or len(name) > 160:
        raise ValueError("Workspace name is required and must be under 160 characters")
    ZoneInfo(timezone)
    public_url = _public_url()
    api_key = os.environ.get("TCE_STANDALONE_RESEND_API_KEY")
    from_email = os.environ.get("TCE_STANDALONE_FROM_EMAIL")
    if not api_key or not from_email:
        raise ValueError("Configure Resend key and verified sender before inviting clients")

    raw = new_token()
    now = datetime.now(UTC)
    async with async_session() as db:
        workspace = (
            await db.execute(select(StandaloneWorkspace).where(StandaloneWorkspace.slug == slug))
        ).scalar_one_or_none()
        if workspace is None:
            workspace = StandaloneWorkspace(name=name.strip(), slug=slug, timezone=timezone)
            db.add(workspace)
            await db.flush()
        account = (
            await db.execute(select(StandaloneAccount).where(StandaloneAccount.email == email))
        ).scalar_one_or_none()
        if account is None:
            account = StandaloneAccount(email=email, password_hash=hash_password(new_token()))
            db.add(account)
            await db.flush()
        elif account.email_verified_at is not None:
            raise ValueError("This account is already active. Use its existing sign-in.")
        membership = (
            await db.execute(
                select(StandaloneMembership).where(
                    StandaloneMembership.workspace_id == workspace.id,
                    StandaloneMembership.account_id == account.id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            db.add(
                StandaloneMembership(workspace_id=workspace.id, account_id=account.id, role="owner")
            )
        invites = (
            await db.execute(
                select(StandaloneInvite).where(
                    StandaloneInvite.workspace_id == workspace.id,
                    StandaloneInvite.account_id == account.id,
                    StandaloneInvite.consumed_at.is_(None),
                )
            )
        ).scalars()
        for old in invites:
            old.consumed_at = now
        invite = StandaloneInvite(
            workspace_id=workspace.id,
            account_id=account.id,
            token_hash=token_hash(raw),
            expires_at=now + timedelta(days=7),
        )
        db.add(invite)
        await db.commit()
        invite_id = invite.id

    link = f"{public_url}/app#invite={raw}"
    body = invitation_message(from_email, email, name, link, public_url)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Idempotency-Key": f"tce-invite-{invite_id}",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            "Invitation email provider is unavailable; reissue the invitation"
        ) from exc
    if response.status_code not in {200, 201, 202}:
        raise RuntimeError(f"Invitation email failed with HTTP {response.status_code}; reissue it")
    print(f"Invitation accepted by email provider for {email} in workspace {slug}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Email a private TCE onboarding invitation")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--timezone", default="UTC")
    args = parser.parse_args()
    import asyncio

    try:
        asyncio.run(invite_client(args.email, args.name, args.slug, args.timezone))
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
