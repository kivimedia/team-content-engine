"""Push notifications for work that finished while he was not looking.

Four things are worth a buzz, and they are all the same shape: he asked for
something, it takes minutes, and today it ends with a line on a page he is not
looking at. A twelve-minute script wait currently finishes by telling him to come
back later.

    script_ready      a packet he asked for is ready to record
    edit_ready        a recording finished rendering
    needs_review      the planned cut would change what he said
    upload_recovery   an interrupted upload needs him to open the studio

Nothing else. This is not an announcement channel, and anything that is merely
interesting can wait for him to open Today.

How it finds them: a reconciler compares current state against
`notification_events` once a minute. That is deliberately not a hook inside the
packet writer or the renderer - those run as background tasks that can die, and a
missed hook is a notification that never arrives with nothing to show why. A
reconciler that re-reads state cannot miss a transition, only notice it late.

`dedupe_key` carries the object AND the state it reached, so the same packet
reaching `ready` is one event forever, while the same upload reaching `edited`
later is a different one.

Delivery is best-effort by design. No subscribers, no VAPID key, or a browser
that dropped its subscription are all normal and none of them is an error worth
showing him.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import NotificationEvent, NotificationSubscription

logger = structlog.get_logger()

# How long after the fact something is still worth saying. A script that became
# ready two days ago is not news, and buzzing about it on restart is worse than
# silence.
FRESH_SECONDS = 6 * 60 * 60


class NotifyError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def vapid_public_key() -> str | None:
    from tce.settings import settings

    return getattr(settings, "vapid_public_key", None) or None


def _vapid_private_key() -> str | None:
    from tce.settings import settings

    key = getattr(settings, "vapid_private_key", None)
    if key is None:
        return None
    # Settings may hold it as a SecretStr.
    return key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)


def push_available() -> bool:
    return bool(vapid_public_key() and _vapid_private_key())


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


async def subscribe(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
) -> NotificationSubscription:
    """Store or refresh one browser's endpoint. Idempotent per browser."""
    if not endpoint or not p256dh or not auth:
        raise NotifyError("incomplete", "that subscription is missing its keys", status=400)

    digest = endpoint_hash(endpoint)
    result = await db.execute(
        select(NotificationSubscription).where(
            NotificationSubscription.workspace_id == ws,
            NotificationSubscription.endpoint_hash == digest,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = NotificationSubscription(
            workspace_id=ws,
            endpoint_hash=digest,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(user_agent or "")[:300] or None,
            status="active",
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:  # pragma: no cover - two tabs registering at once
            await db.rollback()
            again = await db.execute(
                select(NotificationSubscription).where(
                    NotificationSubscription.workspace_id == ws,
                    NotificationSubscription.endpoint_hash == digest,
                )
            )
            row = again.scalar_one()
    else:
        # A browser can rotate its keys on the same endpoint.
        row.endpoint = endpoint
        row.p256dh = p256dh
        row.auth = auth
        row.status = "active"
        row.failure_count = 0
        if user_agent:
            row.user_agent = user_agent[:300]
        await db.flush()
    return row


async def unsubscribe(db: AsyncSession, ws: uuid.UUID, *, endpoint: str) -> bool:
    result = await db.execute(
        select(NotificationSubscription).where(
            NotificationSubscription.workspace_id == ws,
            NotificationSubscription.endpoint_hash == endpoint_hash(endpoint),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def active_subscriptions(
    db: AsyncSession, ws: uuid.UUID
) -> list[NotificationSubscription]:
    result = await db.execute(
        select(NotificationSubscription).where(
            NotificationSubscription.workspace_id == ws,
            NotificationSubscription.status == "active",
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Finding what is worth saying
# ---------------------------------------------------------------------------


def _fresh(moment: datetime | None) -> bool:
    if moment is None:
        return False
    age = (datetime.now(UTC).replace(tzinfo=None) - moment).total_seconds()
    return 0 <= age <= FRESH_SECONDS


async def collect_events(db: AsyncSession, ws: uuid.UUID) -> list[dict[str, Any]]:
    """What has happened that he has not been told about. Reads only."""
    events: list[dict[str, Any]] = []

    # A script he asked for is ready to record.
    packets = await db.execute(
        select(RecordingPacket, TopicCandidate.title)
        .join(TopicCandidate, TopicCandidate.id == RecordingPacket.candidate_id)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.status.in_(("ready", "exported")),
            TopicCandidate.origin != ORIGIN_TECHNICAL_VALIDATION,
        )
        .order_by(RecordingPacket.created_at.desc())
        .limit(20)
    )
    for packet, title in packets.all():
        if not _fresh(packet.created_at):
            continue
        events.append(
            {
                "kind": "script_ready",
                "dedupe_key": f"script_ready:{packet.id}:{packet.version}",
                "title": "Your script is ready",
                "body": title,
                "path": f"/scripts/{packet.id}",
            }
        )

    uploads = await db.execute(
        select(RecordingUpload, TopicCandidate.title)
        .join(TopicCandidate, TopicCandidate.id == RecordingUpload.candidate_id)
        .where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.status.in_(("edited", "needs_review", "failed")),
            TopicCandidate.origin != ORIGIN_TECHNICAL_VALIDATION,
        )
        .order_by(RecordingUpload.updated_at.desc())
        .limit(20)
    )
    for upload, title in uploads.all():
        if not _fresh(upload.updated_at):
            continue
        if upload.status == "edited":
            events.append(
                {
                    "kind": "edit_ready",
                    "dedupe_key": f"edit_ready:{upload.id}",
                    "title": "Your edit is ready",
                    "body": title,
                    "path": "/library",
                }
            )
        elif upload.status == "needs_review":
            events.append(
                {
                    "kind": "needs_review",
                    "dedupe_key": f"needs_review:{upload.id}",
                    "title": "A cut needs your eyes",
                    "body": f"The planned cut of “{title}” would change what you said.",
                    "path": "/library",
                }
            )
        else:
            events.append(
                {
                    "kind": "upload_recovery",
                    "dedupe_key": f"upload_recovery:{upload.id}",
                    "title": "A recording needs you",
                    "body": f"“{title}” did not finish. The original is safe.",
                    "path": "/library",
                }
            )

    return events


async def record_event(
    db: AsyncSession, ws: uuid.UUID, event: dict[str, Any]
) -> NotificationEvent | None:
    """Claim an event. Returns None when it has already been recorded.

    The unique constraint is the claim, so two reconcilers racing cannot both
    send the same buzz.
    """
    row = NotificationEvent(
        workspace_id=ws,
        kind=event["kind"],
        dedupe_key=event["dedupe_key"],
        title=event["title"],
        body=event["body"],
        path=event.get("path") or "/today",
        state="pending",
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None
    return row


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _send_one(subscription: NotificationSubscription, payload: dict[str, Any]) -> str:
    """Blocking push to one endpoint. Returns 'sent' | 'gone' | 'failed:<why>'."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return "failed:pywebpush is not installed"

    private_key = _vapid_private_key()
    if not private_key:
        return "failed:no VAPID key configured"

    from tce.settings import settings

    claims = {"sub": getattr(settings, "vapid_subject", None) or "mailto:ziv@kivimedia.co"}
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims=claims,
            timeout=10,
        )
        return "sent"
    except WebPushException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        # 404/410 mean the browser dropped this subscription. Normal, not a fault.
        if status in (404, 410):
            return "gone"
        return f"failed:{status or error}"
    except Exception as error:  # pragma: no cover - network shapes vary
        return f"failed:{error}"


async def deliver(
    db: AsyncSession, ws: uuid.UUID, event: NotificationEvent
) -> NotificationEvent:
    """Send one event to every live subscription for the workspace."""
    import asyncio

    subscriptions = await active_subscriptions(db, ws)
    if not subscriptions:
        event.state = "no_subscribers"
        event.detail = "Nothing is subscribed to notifications yet."
        await db.flush()
        return event
    if not push_available():
        event.state = "no_subscribers"
        event.detail = "Push is not configured on this server."
        await db.flush()
        return event

    payload = {"title": event.title, "body": event.body, "path": event.path,
               "kind": event.kind}
    sent = 0
    problems: list[str] = []
    for subscription in subscriptions:
        # pywebpush is synchronous; keep the event loop free.
        outcome = await asyncio.to_thread(_send_one, subscription, payload)
        if outcome == "sent":
            sent += 1
            subscription.last_sent_at = datetime.now(UTC).replace(tzinfo=None)
            subscription.failure_count = 0
        elif outcome == "gone":
            subscription.status = "gone"
        else:
            subscription.failure_count += 1
            problems.append(outcome)
            if subscription.failure_count >= 5:
                subscription.status = "gone"

    if sent:
        event.state = "sent"
        event.sent_at = datetime.now(UTC).replace(tzinfo=None)
        event.detail = None
    else:
        event.state = "failed"
        event.detail = "; ".join(problems)[:500] or "no endpoint accepted it"
    await db.flush()
    return event


async def reconcile(sessionmaker: Any, ws: uuid.UUID) -> int:
    """One pass: find, claim, send. Returns how many were sent."""
    from tce.editorial.common import open_session

    sent = 0
    async with open_session(sessionmaker) as db:
        try:
            events = await collect_events(db, ws)
        except Exception:
            logger.exception("notify.collect_failed")
            return 0
        for event in events:
            claimed = await record_event(db, ws, event)
            if claimed is None:
                continue
            try:
                await deliver(db, ws, claimed)
                if claimed.state == "sent":
                    sent += 1
            except Exception:  # pragma: no cover
                logger.exception("notify.deliver_failed")
                claimed.state = "failed"
        await db.commit()
    return sent


async def poll(sessionmaker: Any) -> None:  # pragma: no cover - a loop
    """Background reconciler. Same shape as the content-run schedule poller."""
    import asyncio

    from tce.settings import settings

    ws_raw = getattr(settings, "editor_default_workspace_id", None)
    if not ws_raw:
        return
    try:
        ws = uuid.UUID(str(ws_raw))
    except ValueError:
        return

    while True:
        try:
            if push_available():
                await reconcile(sessionmaker, ws)
        except Exception:
            # A failed pass is retried. Dedupe keys prevent duplicates.
            logger.exception("notify.poll_failed")
        await asyncio.sleep(60)
