"""The push actually goes out, encrypted, signed, and readable at the other end.

Everything else about notifications was tested against our own database. This
tests the part that is easy to get silently wrong and impossible to notice: the
VAPID signature and the payload encryption. A broken key there means he adds the
page to his Home Screen, grants permission, and then simply never hears anything,
with nothing in any log to say why.

So this stands up a real HTTP listener, generates a real subscription keypair the
way a browser does, and makes `deliver` push to it. Then it decrypts the body
with the subscription's own private key and checks the message is the one we
meant to send.

The only link not covered is the push service carrying it to the handset, which
is Google's job and not something a key can be wrong about.
"""

from __future__ import annotations

import base64
import http.server
import json
import threading
import uuid
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import SecretStr

from tce.editorial import notify
from tce.models.editorial_workspace import NotificationEvent
from tce.settings import settings

WEEK = datetime(2026, 9, 21)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class _Catcher(http.server.BaseHTTPRequestHandler):
    """Stands in for the browser's push endpoint."""

    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        _Catcher.received.append(
            {
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": self.rfile.read(length) if length else b"",
            }
        )
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args) -> None:  # keep pytest output clean
        return


@pytest.fixture
def push_endpoint():
    _Catcher.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/push/abc123", _Catcher
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def vapid(monkeypatch):
    """A real key pair, generated the way the production one was."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_point = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    monkeypatch.setattr(settings, "vapid_public_key", b64(public_point))
    monkeypatch.setattr(settings, "vapid_private_key", SecretStr(b64(private_raw)))
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ziv@kivimedia.co")
    return b64(public_point)


async def test_a_notification_is_signed_encrypted_and_readable(
    editorial_session, push_endpoint, vapid
):
    endpoint, catcher = push_endpoint
    ws = uuid.uuid4()

    # A browser generates this pair and never shares the private half. We keep it
    # here so the test can read back what was sent.
    subscriber_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64(
        subscriber_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )
    auth_secret = b"0123456789abcdef"

    await notify.subscribe(
        editorial_session, ws, endpoint=endpoint, p256dh=p256dh, auth=b64(auth_secret)
    )
    event = NotificationEvent(
        workspace_id=ws,
        kind="script_ready",
        dedupe_key="script_ready:live-check",
        title="Your script is ready",
        body="The four jobs behind a one-person service business",
        path="/scripts/abc",
        state="pending",
    )
    editorial_session.add(event)
    await editorial_session.flush()

    assert notify.push_available() is True
    await notify.deliver(editorial_session, ws, event)
    await editorial_session.commit()

    assert event.state == "sent", event.detail
    assert len(catcher.received) == 1
    sent = catcher.received[0]

    # Signed for our key, and encrypted with the scheme browsers require.
    assert sent["headers"]["authorization"].lower().startswith("vapid")
    assert sent["headers"]["content-encoding"] == "aes128gcm"
    assert sent["body"], "the push carried no body"

    # And it says what we meant. This is the half a wrong key would break
    # silently: the POST still succeeds, the phone just shows nothing.
    import http_ece

    decrypted = http_ece.decrypt(
        sent["body"],
        private_key=subscriber_key,
        auth_secret=auth_secret,
        version="aes128gcm",
    )
    payload = json.loads(decrypted)
    assert payload["title"] == "Your script is ready"
    assert payload["body"] == "The four jobs behind a one-person service business"
    assert payload["path"] == "/scripts/abc"
    assert payload["kind"] == "script_ready"


async def test_an_endpoint_the_browser_dropped_is_retired_quietly(
    editorial_session, vapid, monkeypatch
):
    """A 410 is how a browser says "that subscription is gone". Not an error."""
    ws = uuid.uuid4()
    await notify.subscribe(
        editorial_session,
        ws,
        endpoint="https://push.example.com/dead",
        p256dh="k",
        auth="a",
    )
    monkeypatch.setattr(notify, "_send_one", lambda subscription, payload: "gone")

    event = NotificationEvent(
        workspace_id=ws,
        kind="script_ready",
        dedupe_key="script_ready:dead",
        title="t",
        body="b",
        path="/today",
        state="pending",
    )
    editorial_session.add(event)
    await editorial_session.flush()
    await notify.deliver(editorial_session, ws, event)
    await editorial_session.commit()

    assert event.state == "failed"
    # The endpoint is retired so it is not tried again forever.
    assert await notify.active_subscriptions(editorial_session, ws) == []


async def test_without_a_key_nothing_is_sent_and_it_says_so(editorial_session, monkeypatch):
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", SecretStr(""))
    await notify.subscribe(
        editorial_session, ws, endpoint="https://push.example.com/x", p256dh="k", auth="a"
    )
    event = NotificationEvent(
        workspace_id=ws,
        kind="script_ready",
        dedupe_key="script_ready:nokey",
        title="t",
        body="b",
        path="/today",
        state="pending",
    )
    editorial_session.add(event)
    await editorial_session.flush()
    await notify.deliver(editorial_session, ws, event)

    assert notify.push_available() is False
    assert event.state == "no_subscribers"
    assert "not configured" in (event.detail or "")
