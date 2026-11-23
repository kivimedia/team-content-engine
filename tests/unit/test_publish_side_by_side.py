"""Post goes out on every platform at once, from an upload copy made ahead of the tap
(23-Nov-2026, wait-less item B10, part 1). Synthetic data; the schedule-* skills are faked and
no post, schedule or paid call is made.

Pinned here: the platforms of one tap run side by side; each is posted once (a platform out
already is never posted again, on a retry, a second run or a restart); one failing or breaking
never touches the others; the rows are written one at a time, each in its own session. The
upload copy made ahead is used only when it was made from the very edit being posted, and a
missing, stale, partial or failed one sends the tap down the old encode.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload, VideoPublication
from tce.production import publishing
from tce.settings import settings
from tests.unit.test_publishing import app_client, h, seed  # noqa: F401 - `app_client` is a fixture

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

OK = {
    "instagram": (0, "Published: db_id=11111111-2222 ig_media=5 ig_post=178"),
    "facebook": (0, "Published: db_id=x fb_post_id=984_1 at=now"),
    "youtube": (0, "Published: video id=YT1"),
    "linkedin": (0, "Published: post_id=9f0e1d2c-aaaa linkedin_post_id=urn:li:share:7 at=x"),
}


async def _rows(sm, uid) -> dict[str, VideoPublication]:
    async with sm() as s:
        return {p.platform: p for p in (await s.execute(
            VideoPublication.__table__.select().where(VideoPublication.upload_id == uid))).all()}


def _counting_sessions(monkeypatch, sm) -> dict[str, int]:
    """Counts the sessions open at the same moment while posts run."""
    seen = {"open": 0, "most": 0}

    @asynccontextmanager
    async def counted():
        seen["open"] += 1
        seen["most"] = max(seen["most"], seen["open"])
        try:
            async with sm() as s:
                yield s
        finally:
            seen["open"] -= 1

    monkeypatch.setattr(prod, "session_factory", lambda: counted)
    return seen


async def _tap(client, ws, uid, platforms, monkeypatch):
    """His tap on Post, and the posting it starts (run by the test itself)."""
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", spawned.append)
    r = await client.post(f"/api/v1/production/uploads/{uid}/publishing/publish",
                          json={"platforms": platforms}, headers=h(ws))
    return r, (spawned[0] if spawned else None)


# ------------------------------------------------------------ side by side
async def test_every_platform_goes_out_at_once_each_once_and_one_session_at_a_time(app_client, monkeypatch):
    client, sm, _ran, _asked = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)
    started: list[str] = []
    all_in = asyncio.Event()

    async def run(platform, argv):
        started.append(platform)
        if len(started) == len(publishing.PLATFORMS):
            all_in.set()
        try:
            await asyncio.wait_for(all_in.wait(), 5)
        except TimeoutError:
            return 1, "Error: the platforms were posted one after another"
        return OK[platform]

    monkeypatch.setattr(prod, "run_platform", run)
    r, posting = await _tap(client, ws, uid, list(publishing.PLATFORMS), monkeypatch)
    assert r.status_code == 202
    seen = _counting_sessions(monkeypatch, sm)
    await posting
    assert sorted(started) == sorted(publishing.PLATFORMS), "each platform once"
    pubs = await _rows(sm, uid)
    assert {p: pubs[p].status for p in pubs} == {
        "instagram": "posted", "facebook": "posted", "youtube": "posted", "linkedin": "scheduled",
    }
    assert pubs["instagram"].url.endswith("/reel/178/") and pubs["youtube"].url == "https://youtube.com/shorts/YT1"
    assert seen["most"] == 1, "no two posts ever share a moment in the database"


async def test_one_platform_failing_is_tried_again_alone_and_the_others_never_go_out_twice(app_client, monkeypatch):
    client, sm, _ran, _asked = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)
    ran: list[str] = []
    answers = {**OK, "instagram": (1, "Error: the session expired")}

    async def run(platform, argv):
        ran.append(platform)
        await asyncio.sleep(0.05)
        return answers[platform]

    monkeypatch.setattr(prod, "run_platform", run)
    r, posting = await _tap(client, ws, uid, list(publishing.PLATFORMS), monkeypatch)
    await posting
    pubs = await _rows(sm, uid)
    assert pubs["instagram"].status == "failed" and "session expired" in pubs["instagram"].detail
    assert [pubs[p].status for p in ("facebook", "youtube")] == ["posted", "posted"]
    # Asking again with one that is out already is refused, as it always was.
    again = await client.post(f"/api/v1/production/uploads/{uid}/publishing/publish",
                              json={"platforms": ["instagram", "facebook"]}, headers=h(ws))
    assert again.status_code == 409
    # Instagram alone goes out on the retry; nothing else is sent.
    answers["instagram"] = OK["instagram"]
    r, posting = await _tap(client, ws, uid, ["instagram"], monkeypatch)
    assert r.status_code == 202
    await posting
    assert sorted(ran) == sorted([*publishing.PLATFORMS, "instagram"])
    assert (await _rows(sm, uid))["instagram"].status == "posted"
    # Even a caller that names every platform posts none of them again.
    await prod.publish_video(uid, ws, list(publishing.PLATFORMS), None)
    assert sorted(ran) == sorted([*publishing.PLATFORMS, "instagram"])


async def test_a_restart_mid_post_picks_up_only_what_never_left(app_client, monkeypatch):
    client, sm, _ran, _asked = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)
    async with sm() as s:
        pubs = await prod._publications(s, ws, uid)
        pubs["instagram"].status, pubs["instagram"].url = "posted", "https://www.instagram.com/reel/1/"
        pubs["facebook"].status, pubs["facebook"].detail = "posting", "Posting on Facebook Page now"
        pubs["youtube"].status, pubs["youtube"].detail = "posting", "Queued"
        pubs["linkedin"].status, pubs["linkedin"].detail = "posting", "Making the upload copy of the video"
        await s.commit()
    ran: list[str] = []

    async def run(platform, argv):
        ran.append(platform)
        return OK[platform]

    monkeypatch.setattr(prod, "run_platform", run)
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", spawned.append)
    monkeypatch.setattr(settings, "production_auto_edit", True)
    await prod.resume_auto_work()
    for coro in spawned:
        if coro.__name__ == "publish_video":
            await coro
        else:
            coro.close()
    assert sorted(ran) == ["linkedin", "youtube"], "the one mid-upload and the one out are never sent again"
    pubs = await _rows(sm, uid)
    assert pubs["facebook"].status == "failed" and "may already be live" in pubs["facebook"].detail
    assert pubs["instagram"].status == "posted" and pubs["youtube"].status == "posted"
    assert pubs["linkedin"].status == "scheduled"


async def test_two_runs_for_the_same_platform_post_it_once(app_client, monkeypatch):
    client, sm, _ran, _asked = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)
    ran: list[str] = []

    async def run(platform, argv):
        ran.append(platform)
        await asyncio.sleep(0.2)
        return OK[platform]

    monkeypatch.setattr(prod, "run_platform", run)
    r, posting = await _tap(client, ws, uid, ["facebook"], monkeypatch)
    await asyncio.gather(posting, prod.publish_video(uid, ws, ["facebook", "facebook"], None))
    assert ran == ["facebook"]
    assert (await _rows(sm, uid))["facebook"].status == "posted"


async def test_one_platform_breaking_never_stops_the_others(app_client, monkeypatch):
    client, sm, _ran, _asked = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)

    async def run(platform, argv):
        if platform == "youtube":
            raise RuntimeError("the skill folder is gone")
        return OK[platform]

    monkeypatch.setattr(prod, "run_platform", run)
    r, posting = await _tap(client, ws, uid, list(publishing.PLATFORMS), monkeypatch)
    await posting
    pubs = await _rows(sm, uid)
    assert [pubs[p].status for p in ("instagram", "facebook", "linkedin")] == ["posted", "posted", "scheduled"]
    # Its row keeps the line written before its skill started, so a restart never posts it blind.
    assert pubs["youtube"].status == "posting" and pubs["youtube"].detail.endswith(" now")
    assert prod._posting_now == {}, "nothing stays claimed after the run"


# ------------------------------------------------------------ the upload copy made ahead
def _video(path: Path, color: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=10:d=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


@pytest.fixture
async def edited(editorial_sessionmaker, monkeypatch, tmp_path):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(settings, "production_social_preencode", True)
    path = _video(tmp_path / "walk-edited.mp4", "red")
    ws, uid = await seed(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingUpload, uid)
        row.edited_path = str(path)
        await s.commit()
    return ws, uid, path


def _social(path: Path) -> Path:
    return path.with_name(f"{path.stem}-social.mp4")


@needs_ffmpeg
async def test_the_copy_made_ahead_is_the_one_posted_for_that_very_edit(edited):
    ws, uid, path = edited
    await prod._pre_encode_social(uid, ws)
    ready, stamp = prod._social_ready(path)
    assert ready.exists() and stamp.exists()
    told = prod._ready_stamp(path)
    assert told["made_from"]["edit_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    made = ready.stat().st_ino
    out = await prod._social_copy(uid, ws)
    assert out == _social(path) and out.stat().st_ino == made, "the tap took it; nothing was encoded again"
    assert not ready.exists() and not stamp.exists()
    assert not list(path.parent.glob("*.part*")), "no half-made file is left beside the edit"


@needs_ffmpeg
async def test_a_copy_made_from_an_earlier_edit_is_never_posted(edited, tmp_path):
    ws, uid, path = edited
    await prod._pre_encode_social(uid, ws)
    ready, _stamp = prod._social_ready(path)
    stale = ready.stat().st_ino
    # He asks for a change and the edit is made again at the same place.
    _video(tmp_path / "next.mp4", "blue").replace(path)
    out = await prod._social_copy(uid, ws)
    assert out.exists() and out.stat().st_ino != stale, "encoded again from the edit on disk now"
    assert ready.exists(), "the copy of the earlier edit was left unused"


@needs_ffmpeg
@pytest.mark.parametrize("damage", ["no stamp", "cut short"])
async def test_a_partial_copy_sends_the_tap_down_the_old_encode(edited, damage):
    ws, uid, path = edited
    await prod._pre_encode_social(uid, ws)
    ready, stamp = prod._social_ready(path)
    if damage == "no stamp":
        stamp.unlink()  # a restart between the copy landing and its stamp
    else:
        ready.write_bytes(ready.read_bytes()[:500])
    before = ready.stat().st_ino
    out = await prod._social_copy(uid, ws)
    assert out.stat().st_ino != before and out.stat().st_size > 500


@needs_ffmpeg
async def test_a_failed_copy_leaves_nothing_and_the_tap_says_why_as_before(edited):
    ws, uid, path = edited
    path.write_bytes(b"not a video")
    await prod._pre_encode_social(uid, ws)
    ready, stamp = prod._social_ready(path)
    assert not ready.exists() and not stamp.exists() and not list(path.parent.glob("*.part*"))
    with pytest.raises(RuntimeError, match="could not make the upload copy"):
        await prod._social_copy(uid, ws)


@needs_ffmpeg
async def test_the_copy_is_not_made_where_he_posts_by_hand_or_while_it_is_switched_off(edited, monkeypatch):
    ws, uid, path = edited
    monkeypatch.setattr(prod, "_posts_from_tce", lambda *_a: False)
    await prod._pre_encode_social(uid, ws)
    assert not prod._social_ready(path)[0].exists()
    monkeypatch.setattr(prod, "_posts_from_tce", lambda *_a: True)
    monkeypatch.setattr(settings, "production_social_preencode", False)
    await prod._pre_encode_social(uid, ws)
    assert not prod._social_ready(path)[0].exists()


async def test_an_edit_that_ends_ready_starts_its_copy(monkeypatch):
    started: list = []

    def keep(coro):
        started.append(coro.__name__)
        coro.close()

    async def no_posts(*_a, **_k):
        return None

    monkeypatch.setattr(prod, "_spawn", keep)
    monkeypatch.setattr(prod, "draft_posts", no_posts)
    await prod._draft_posts_said(uuid.uuid4(), uuid.uuid4(), rewrite=False)
    assert started == ["_pre_encode_social"]
