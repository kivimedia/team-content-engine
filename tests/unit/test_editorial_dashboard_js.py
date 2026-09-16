"""Editorial dashboard helpers, run in Node straight from dashboard.html. Synthetic values."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "src" / "tce" / "api" / "dashboard.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node not installed")


def _function(source: str, name: str) -> str:
    m = re.search(rf"^function {name}\(.*?^\}}\r?$", source, re.M | re.S)
    assert m, name
    return m.group(0)


def run_js(expr: str):
    source = HTML.read_text(encoding="utf-8")
    names = ("edHuman", "edDate", "edClock", "edMonday", "edIsoDate", "edParseWeek", "edErrorText")
    const = re.search(r"^const ED_PRIVATE_ACCESS_DETAIL = .*$", source, re.M).group(0)
    script = "\n".join([const, *(_function(source, n) for n in names)])
    script += f"\nprocess.stdout.write(JSON.stringify({expr}));"
    out = subprocess.run(
        [NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30
    ).stdout
    return json.loads(out)


def test_private_access_503_is_named_only_for_that_error():
    msg = run_js("edErrorText(503, {detail: 'Private access is not configured'}, '')")
    assert msg.startswith("Private access is not configured on the server")


def test_subscription_queue_503_is_not_blamed_on_private_access():
    body = {
        "detail": "Text generation is not available right now",
        "llm_status": "waiting_capacity",
        "llm_detail": "Subscription capacity is exhausted until the next window",
        "job_id": "00000000-0000-4000-8000-000000000001",
        "retry_at": None,
    }
    msg = run_js(f"edErrorText(503, {json.dumps(body)}, '')")
    assert "Private access" not in msg
    assert msg.startswith("Text generation is not available right now (subscription job")
    assert "waiting capacity" in msg and "capacity is exhausted" in msg


def test_other_503_and_proxy_timeout_say_what_happened():
    other = run_js("edErrorText(503, {detail: 'Queue unavailable'}, '')")
    assert other == "Queue unavailable (HTTP 503)"
    timeout = run_js("edErrorText(504, null, '<html><h1>504 Gateway Time-out</h1></html>')")
    assert "did not answer in time (HTTP 504)" in timeout and "Private access" not in timeout
    assert "<h1>" not in timeout


def test_week_parameter_validation():
    got = run_js(
        "['2026-09-07', '2026-09-09', '2026-02-30', '2026-9-7', 'drop table', '', null,"
        " '1999-12-27', '2026-09-07T00:00'].map(edParseWeek)"
    )
    assert got == ["2026-09-07", "2026-09-07", None, None, None, None, None, None, None]


async def test_root_redirect_keeps_the_week_query():
    import httpx
    from fastapi import FastAPI

    from tce.api import dashboard

    app = FastAPI()
    app.include_router(dashboard.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/?week=2026-09-07")
        assert r.status_code == 307 and r.headers["location"] == "/dashboard?week=2026-09-07"
        bare = await c.get("/")
        assert bare.headers["location"] == "/dashboard"
        evil = await c.get("/?week=//evil.example")
        assert evil.headers["location"].startswith("/dashboard?")
