"""Agent talks, contract C4 (3-Oct): a filmed voice call with an agent, sent in pieces.

The three routes the KM BOT voice service calls, on the suite's SQLite database: the key,
a create sent twice, pieces sent twice or out of order, and the finish that joins them
into a library video ("Agent talk", source agent_talk) and starts its edit unless the
kill switch is off. The joins run real ffmpeg on tiny recordings made here: a WebM like
Chrome's recorder makes and a fragmented MP4 like Safari's. Synthetic data only.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from tce.api.routers import agent_talks as talk_routes
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial import inbox, library
from tce.editorial.common import ORIGIN_AGENT_TALK
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tce.production.media import probe_media
from tce.settings import settings

KEY = "test-agent-talk-key"
WS = uuid.UUID("aaaaaaaa-3333-4333-8333-333333333333")
OTHER_WS = uuid.UUID("bbbbbbbb-4444-4444-8444-444444444444")
AUTH = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(WS)}
BASE = "/api/v1/production/agent-talks"
# 14:52 in Israel on 3-Oct-2026 (UTC+3).
STARTED = "2026-10-03T11:52:07.120Z"

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def spawned(monkeypatch):
    """The edits the finish starts, captured instead of run."""
    out: list = []

    def keep(coro):
        out.append(coro)

    monkeypatch.setattr(prod, "_spawn", keep)
    yield out
    for coro in out:
        coro.close()


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch, tmp_path, spawned):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_auto_edit", True)
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)

    app = FastAPI()
    app.include_router(talk_routes.router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def _create_body(**over):
    body = {"agent": "atlas", "call_id": "call-0001", "started_at": STARTED, "mime": "video/webm;codecs=vp8,opus"}
    body.update(over)
    return body


async def _new_talk(client, **over) -> str:
    r = await client.post(BASE, headers=AUTH, json=_create_body(**over))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "recording"
    return r.json()["talk_id"]


def _split(data: bytes, cuts: int = 5) -> list[bytes]:
    """Uneven slices, the way a recorder's timeslices cut a stream (never on a boundary)."""
    step = max(1, len(data) // cuts)
    edges = [0] + [min(len(data), k * step + (k * 37) % 101) for k in range(1, cuts)] + [len(data)]
    return [data[a:b] for a, b in zip(edges, edges[1:], strict=False) if b > a]


def _record(path: Path, kind: str, seconds: float = 3.0) -> bytes:
    """A tiny selfie-shaped recording: portrait picture and a tone, like a phone records."""
    exe = shutil.which("ffmpeg")
    picture = ["-f", "lavfi", "-i", f"testsrc=size=180x320:rate=15:duration={seconds}"]
    tone = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000"]
    if kind == "webm":  # Chrome's recorder: VP8 and Opus, written live (no duration, no index)
        codec = ["-c:v", "libvpx", "-deadline", "realtime", "-b:v", "200k", "-c:a", "libopus", "-ac", "1",
                 "-f", "webm", "-live", "1"]
    else:  # Safari's recorder: H.264 and AAC in a fragmented MP4, a fragment a second
        codec = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "15",
                 "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                 "-frag_duration", "1000000", "-f", "mp4"]
    subprocess.run([exe, "-y", "-v", "error", *picture, *tone, *codec, str(path)], check=True)
    return path.read_bytes()


def _decodes(path: str) -> tuple[bool, bool]:
    exe = shutil.which("ffmpeg")
    picture = subprocess.run([exe, "-v", "error", "-i", path, "-map", "0:v", "-f", "null", "-"],
                             capture_output=True, text=True)
    sound = subprocess.run([exe, "-v", "error", "-i", path, "-map", "0:a", "-f", "null", "-"],
                           capture_output=True, text=True)
    return (picture.returncode == 0 and not picture.stderr.strip(),
            sound.returncode == 0 and not sound.stderr.strip())


# ---------------------------------------------------------------------------
# The key


async def test_every_route_needs_the_private_key(client, monkeypatch):
    talk = str(uuid.uuid4())
    no_key = {"X-Workspace-Id": str(WS)}
    wrong = {"Authorization": "Bearer not-the-key", "X-Workspace-Id": str(WS)}
    for method, url, kwargs in (
        ("post", BASE, {"json": _create_body()}),
        ("put", f"{BASE}/{talk}/chunks/0", {"content": b"x"}),
        ("post", f"{BASE}/{talk}/finish", {"json": {}}),
        ("get", f"{BASE}/{talk}", {}),
    ):
        for headers in (no_key, wrong):
            r = await getattr(client, method)(url, headers=headers, **kwargs)
            assert r.status_code == 401, (method, url, r.text)
    monkeypatch.setattr(settings, "private_access_key", SecretStr(""))
    r = await client.post(BASE, headers=AUTH, json=_create_body())
    assert r.status_code == 503  # fail closed when the key is not configured


async def test_a_talk_belongs_to_its_workspace(client):
    talk = await _new_talk(client)
    other = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(OTHER_WS)}
    assert (await client.put(f"{BASE}/{talk}/chunks/0", headers=other, content=b"abc")).status_code == 404
    assert (await client.post(f"{BASE}/{talk}/finish", headers=other, json={})).status_code == 404


# ---------------------------------------------------------------------------
# Create


async def test_a_create_sent_twice_is_the_same_talk(client, editorial_sessionmaker):
    first = await _new_talk(client)
    again = await client.post(BASE, headers=AUTH, json=_create_body())
    assert again.status_code == 200 and again.json()["talk_id"] == first
    # A second recording in the same call starts later: its own talk.
    later = await client.post(BASE, headers=AUTH, json=_create_body(started_at="2026-10-03T11:58:00Z"))
    assert later.status_code == 201 and later.json()["talk_id"] != first
    assert later.json()["title"] == "Talk with Atlas, 3 Oct"
    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(AgentTalk).where(AgentTalk.workspace_id == WS))).scalars().all()
    assert len(rows) == 2 and {r.file_extension for r in rows} == {"webm"}
    assert rows[0].started_at.tzinfo is None  # stored as naive UTC like every other time


async def test_create_refuses_what_it_cannot_join(client):
    r = await client.post(BASE, headers=AUTH, json=_create_body(mime="video/ogg"))
    assert r.status_code == 415
    r = await client.post(BASE, headers=AUTH, json=_create_body(started_at="yesterday"))
    assert r.status_code == 400
    r = await client.post(BASE, headers=AUTH, json={"agent": "atlas"})
    assert r.status_code == 422
    # A fragmented MP4 (Safari, newer Chrome) is accepted as well as WebM.
    r = await client.post(BASE, headers=AUTH, json=_create_body(call_id="call-mp4", mime="video/mp4"))
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Pieces


async def test_pieces_are_idempotent_per_sequence_number(client, tmp_path):
    talk = await _new_talk(client)
    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=b"first-piece")
    assert r.status_code == 200 and r.json() == {
        "ok": True, "bytes_total": 11, "seq": 0, "pieces": 1, "duplicate": False,
    }
    # The relay retried: the same bytes again change nothing.
    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=b"first-piece")
    assert r.status_code == 200 and r.json()["bytes_total"] == 11 and r.json()["duplicate"] is True
    r = await client.put(f"{BASE}/{talk}/chunks/1", headers=AUTH, content=b"second")
    assert r.json()["bytes_total"] == 17 and r.json()["pieces"] == 2
    # Different bytes under a number that already arrived would splice two recordings.
    r = await client.put(f"{BASE}/{talk}/chunks/1", headers=AUTH, content=b"other!")
    assert r.status_code == 409
    assert (await client.put(f"{BASE}/{talk}/chunks/-1", headers=AUTH, content=b"x")).status_code in (400, 422)
    assert (await client.put(f"{BASE}/{talk}/chunks/2", headers=AUTH, content=b"")).status_code == 400
    status = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert status["pieces"] == 2 and status["bytes_total"] == 17 and status["status"] == "recording"
    assert "2 pieces here" in status["detail"]


async def test_finish_without_piece_zero_waits_for_it(client):
    talk = await _new_talk(client)
    await client.put(f"{BASE}/{talk}/chunks/1", headers=AUTH, content=b"a later piece")
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    assert r.status_code == 409 and "Piece 0" in r.json()["detail"]
    nothing = await _new_talk(client, call_id="call-empty")
    r = await client.post(f"{BASE}/{nothing}/finish", headers=AUTH, json={})
    assert r.status_code == 409
    # Neither became a failed talk: the pieces may still come.
    assert (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()["status"] == "recording"


# ---------------------------------------------------------------------------
# Finish: the join, the upload, the edit

TRANSCRIPT = [
    {"who": "ziv", "text": "Let us go through the open sessions.", "t_ms": 200},
    {"who": "agent", "text": "Sure. Two are waiting for you.", "t_ms": 1500},
]


async def _send(client, talk: str, data: bytes, *, shuffle: bool = True) -> int:
    pieces = _split(data)
    order = list(range(len(pieces)))
    if shuffle:  # the relay sends in parallel: they land out of order, one twice
        order = order[1:] + order[:1] + [order[-1]]
    for seq in order:
        r = await client.put(f"{BASE}/{talk}/chunks/{seq}", headers=AUTH, content=pieces[seq])
        assert r.status_code == 200, r.text
    return len(pieces)


@needs_ffmpeg
@pytest.mark.parametrize("kind,mime", [("webm", "video/webm;codecs=vp8,opus"), ("mp4", "video/mp4;codecs=avc1,mp4a")])
async def test_finish_joins_the_pieces_without_re_encoding_and_starts_the_edit(
    client, editorial_sessionmaker, tmp_path, spawned, kind, mime
):
    data = _record(tmp_path / f"source.{kind}", kind)
    talk = await _new_talk(client, call_id=f"call-{kind}", mime=mime)
    count = await _send(client, talk, data)
    r = await client.post(
        f"{BASE}/{talk}/finish",
        headers=AUTH,
        json={"ended_at": "2026-10-03T11:52:11Z", "duration_ms": 3100, "transcript": TRANSCRIPT},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "uploaded" and body["edit_started"] is True
    assert body["title"] == "Talk with Atlas, 3 Oct" and body["missing_pieces"] == []

    async with editorial_sessionmaker() as s:
        upload = (await s.execute(select(RecordingUpload).where(
            RecordingUpload.id == uuid.UUID(body["upload_id"])))).scalar_one()
        cand = await s.get(TopicCandidate, upload.candidate_id)
        row = await s.get(AgentTalk, uuid.UUID(talk))
    assert upload.source == "agent_talk" and upload.agent_name == "Atlas"
    assert upload.call_transcript == [{**line, "t_ms": float(line["t_ms"])} for line in TRANSCRIPT]
    assert upload.workspace_id == WS and upload.packet_id is None
    assert cand.title == "Talk with Atlas, 3 Oct" and cand.origin == ORIGIN_AGENT_TALK
    assert cand.status == "recorded" and cand.week_start == datetime(2026, 9, 28)
    assert row.status == "finished" and row.upload_id == upload.id and row.join_meta["pieces"] == count
    assert "Jennifer starts the edit now" in upload.status_detail

    # One file, every byte of the recording rewrapped: it plays, picture and sound.
    path = Path(upload.storage_path)
    assert path.exists() and path.suffix == f".{kind}"
    proof = await probe_media(path)
    assert proof["has_video"] and proof["has_audio"]
    assert abs((upload.duration_s or 0) - 3.0) < 0.5, upload.duration_s
    assert _decodes(str(path)) == (True, True)
    # Same codecs as recorded: a remux, never a second lossy encode.
    codecs = {s["codec"] for s in proof["streams"]}
    assert codecs == ({"vp8", "opus"} if kind == "webm" else {"h264", "aac"})
    # The pieces are gone once the video holds them.
    assert not list(path.parent.glob("pieces/*.part")) and not list(path.parent.glob("talk.raw.*"))

    # The edit was started for this video (kill switch on).
    assert len(spawned) == 1 and spawned[0].__name__ == "auto_edit"
    assert spawned[0].cr_frame.f_locals["upload_id"] == upload.id

    # Finishing again is the same video, and a late piece is refused.
    again = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    assert again.status_code == 200 and again.json()["upload_id"] == body["upload_id"]
    assert len(spawned) == 1  # no second edit
    late = await client.put(f"{BASE}/{talk}/chunks/{count}", headers=AUTH, content=b"late")
    assert late.status_code == 409


@needs_ffmpeg
async def test_the_kill_switch_keeps_the_talk_but_starts_no_edit(client, editorial_sessionmaker, tmp_path,
                                                                 spawned, monkeypatch):
    monkeypatch.setattr(settings, "production_auto_edit", False)
    data = _record(tmp_path / "source.webm", "webm", seconds=2.0)
    talk = await _new_talk(client, call_id="call-off")
    await _send(client, talk, data, shuffle=False)
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"transcript": TRANSCRIPT})
    assert r.status_code == 200 and r.json()["edit_started"] is False
    assert spawned == []
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(r.json()["upload_id"]))
    assert upload.status == "uploaded" and "switched off" in upload.status_detail


@needs_ffmpeg
async def test_a_transcript_that_comes_with_a_later_finish_is_kept(client, editorial_sessionmaker, tmp_path):
    """The sweeper finishes an idle talk without the call's transcript; the page's own
    finish brings it a moment later. The video keeps it for its next plan."""
    data = _record(tmp_path / "source.webm", "webm", seconds=2.0)
    talk = await _new_talk(client, call_id="call-swept")
    await _send(client, talk, data, shuffle=False)
    first = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    later = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"transcript": TRANSCRIPT})
    assert later.json()["upload_id"] == first.json()["upload_id"]
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(first.json()["upload_id"]))
    assert [line["text"] for line in upload.call_transcript] == [line["text"] for line in TRANSCRIPT]


@needs_ffmpeg
async def test_the_library_shows_an_agent_talk_and_the_idea_lists_do_not(client, editorial_sessionmaker,
                                                                          tmp_path):
    data = _record(tmp_path / "source.webm", "webm", seconds=2.0)
    talk = await _new_talk(client, call_id="call-lib")
    await _send(client, talk, data, shuffle=False)
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"transcript": TRANSCRIPT})
    upload_id = r.json()["upload_id"]
    async with editorial_sessionmaker() as s:
        items = (await library.list_library(s, WS))["items"]
        topics = await inbox.list_topics(s, WS, filter_key="best")
    card = next(i for i in items if i["upload_id"] == upload_id)
    assert card["title"] == "Talk with Atlas, 3 Oct"
    assert card["source"] == "agent_talk" and card["source_label"] == "Agent talk" and card["agent"] == "Atlas"
    assert card["source_line"].startswith("Agent talk with Atlas: a voice call you filmed.")
    assert card["state_sentence"]  # what is happening to it, in words
    # Nothing to record again: it was a conversation, not a script.
    assert "re_record" not in [a["key"] for a in card["actions"]]
    # Its topic row only names the video: never an idea to decide on.
    assert ORIGIN_AGENT_TALK in inbox.HIDDEN_ORIGINS
    assert "Talk with Atlas, 3 Oct" not in [t["title"] for t in topics["topics"]]
    # The upload's own JSON says where it came from.
    got = await client.get(f"/api/v1/production/uploads/{upload_id}", headers=AUTH)
    assert got.json()["source"] == "agent_talk" and got.json()["agent_name"] == "Atlas"


# ---------------------------------------------------------------------------
# The pure parts


def test_names_and_titles_read_like_his_own():
    assert agent_talks.display_name("atlas") == "Atlas"
    assert agent_talks.display_name("ai-news") == "AI News"
    assert agent_talks.display_name("tce") == "TCE"
    assert agent_talks.display_name("Atlas Two") == "Atlas Two"
    # His clock, not the server's: 23:30 UTC on 2-Oct is already 3-Oct in Israel.
    assert agent_talks.talk_title("atlas", datetime(2026, 10, 2, 23, 30)) == "Talk with Atlas, 3 Oct"
    assert agent_talks.parse_instant("2026-10-03T11:52:07.120Z") == datetime(2026, 10, 3, 11, 52, 7, 120000)
    assert agent_talks.parse_instant("2026-10-03T14:52:07+03:00") == datetime(2026, 10, 3, 11, 52, 7)
    with pytest.raises(agent_talks.TalkError):
        agent_talks.container_for("video/ogg")
    assert agent_talks.container_for("video/webm;codecs=vp9,opus") == "webm"
    assert agent_talks.container_for("video/mp4") == "mp4"


@needs_ffmpeg
async def test_a_piece_missing_in_the_middle_is_named_and_the_rest_is_joined(tmp_path):
    """Fragmented MP4 pieces cut on fragment boundaries: one lost fragment leaves a skip,
    and the join says which number never came."""
    data = _record(tmp_path / "source.mp4", "mp4", seconds=4.0)
    # Cut on 'moof' boxes so a missing piece is one whole fragment.
    marks = [i - 4 for i in range(len(data)) if data[i:i + 4] == b"moof"]
    edges = [0, *marks, len(data)]
    pieces = [data[a:b] for a, b in zip(edges, edges[1:], strict=False) if b > a]
    assert len(pieces) >= 4, len(pieces)
    folder = tmp_path / "talk"
    for seq, piece in enumerate(pieces):
        if seq != 2:
            agent_talks.store_piece(folder, seq, piece)
    joined = await agent_talks.join(folder, "mp4")
    assert joined.missing == [2] and joined.pieces == len(pieces) - 1
    assert joined.proof["has_video"] and joined.proof["has_audio"]
    # A finish that stopped after the join (a restart before the video's row) finds the
    # joined file the next time: the pieces are gone, the talk is not.
    again = await agent_talks.join(folder, "mp4")
    assert again.path == joined.path and again.pieces == 0 and again.proof["has_audio"]
