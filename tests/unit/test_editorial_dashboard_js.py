"""Editorial dashboard helpers, run in Node straight from dashboard.html. Synthetic values."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
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
    names = (
        "edHuman",
        "edDate",
        "edClock",
        "edMonday",
        "edIsoDate",
        "edParseWeek",
        "edErrorText",
        "edCount",
        "edJobLabel",
        "edSelectAction",
        "edPacketAction",
    )
    consts = [
        re.search(rf"^const {c} = .*$", source, re.M).group(0)
        for c in ("ED_PRIVATE_ACCESS_DETAIL", "ED_IN_FLIGHT")
    ]
    script = "\n".join([*consts, *(_function(source, n) for n in names)])
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


def test_dashboard_script_blocks_parse():
    """A duplicate declaration anywhere in the page kills the whole Editorial area."""
    source = HTML.read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", source, re.S)
    assert blocks, "no inline script blocks found"
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "dashboard-inline.js"
        js.write_text("\n".join(blocks), encoding="utf-8")  # the page holds non-ASCII copy
        out = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-600:]


def test_resume_labels_name_what_the_server_will_do():
    idle = run_js("edSelectAction(null, 6)")
    assert idle["label"] == "Select ideas" and idle["resume"] is False
    queued = run_js(
        "edSelectAction({source:'durable', state:'interrupted', resumable:true,"
        " job_counts:{succeeded:1, queued:1}, max_candidates:6}, 6)"
    )
    assert queued["label"] == "Resume selection (1 job still queued or running)"
    assert queued["resume"] is True and "No new jobs are created" in queued["note"]
    waiting = run_js(
        "edSelectAction({source:'durable', state:'waiting', resumable:true,"
        " job_counts:{waiting_capacity:2}, max_candidates:6}, 6)"
    )
    assert waiting["label"] == "Resume selection (2 jobs still waiting for capacity)"
    unsaved = run_js(
        "edSelectAction({source:'durable', state:'interrupted', resumable:true,"
        " job_counts:{succeeded:2}, max_candidates:null}, 6)"
    )
    assert unsaved["label"] == "Resume: save the finished selection"
    assert "without new model calls" in unsaved["note"]
    # shards done, global ranking never ran: resuming DOES make one more model call
    unranked = run_js(
        "edSelectAction({source:'durable', state:'interrupted', resumable:true,"
        " job_counts:{succeeded:2}, max_candidates:6, shards:[{shard:1},{shard:2}],"
        " rank:null}, 6)"
    )
    assert unranked["label"] == "Resume: rank the finalists and save"
    assert "without new model calls" not in unranked["note"]
    assert "global ranking job" in unranked["note"]
    ranked = run_js(
        "edSelectAction({source:'durable', state:'interrupted', resumable:true,"
        " job_counts:{succeeded:3}, max_candidates:6, shards:[{shard:1},{shard:2}],"
        " rank:{stage:'rank', status:'succeeded'}}, 6)"
    )
    assert ranked["label"] == "Resume: save the finished selection"
    failed = run_js(
        "edSelectAction({source:'durable', state:'failed', resumable:true,"
        " job_counts:{succeeded:1, failed:1}, max_candidates:6}, 6)"
    )
    assert failed["label"] == "Retry 1 failed selection job"
    dead = run_js("edSelectAction({source:'durable', state:'failed', resumable:false}, 6)")
    assert dead["label"] == "Start new selection" and dead["resume"] is False
    # A run of a different size cannot be resumed by the server, so it is not offered
    other = run_js(
        "edSelectAction({source:'durable', state:'interrupted', resumable:true,"
        " job_counts:{queued:1}, max_candidates:4}, 6)"
    )
    assert other["label"] == "Start new selection" and "asked for 4 ideas" in other["note"]
    done = run_js("edSelectAction({source:'durable', state:'done', resumable:false}, 6)")
    assert done["label"] == "Select ideas again"
    running = run_js("edSelectAction({state:'running', current_activity:'x'}, 6)")
    assert running["disabled"] is True


def test_packet_resume_labels():
    assert run_js("edPacketAction(null, false)")["label"] == "Build recording packet"
    assert run_js("edPacketAction(null, true)")["label"] == "Rebuild recording packet"
    written = run_js(
        "edPacketAction({source:'durable', state:'interrupted', resumable:true,"
        " job:{status:'succeeded'}}, false)"
    )
    assert written["label"] == "Resume: save the written packet" and written["resume"] is True
    queued = run_js(
        "edPacketAction({source:'durable', state:'interrupted', resumable:true,"
        " job:{status:'waiting_capacity'}}, false)"
    )
    assert queued["label"] == "Resume packet job (waiting capacity)"
    not_resumable = run_js(
        "edPacketAction({source:'durable', state:'failed', resumable:false,"
        " job:{status:'failed'}}, true)"
    )
    assert not_resumable["label"] == "Rebuild recording packet"


def test_durable_job_row_labels():
    assert run_js("edJobLabel({kind:'select', shard:2, shards:3})") == "Shard 2 of 3"
    assert run_js("edJobLabel({kind:'select', shards:1})") == "Selection job"
    assert run_js("edJobLabel({kind:'packet'})") == "Packet job"
    # The editorial worker's global rank job is labelled, not shown as a bare shard
    assert run_js("edJobLabel({kind:'select', stage:'rank'})") == "Global ranking"
    assert run_js("edJobLabel({kind:'select', stage:'merge_shards'})") == "merge shards"
