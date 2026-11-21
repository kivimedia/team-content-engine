"""New backgrounds, the app's side: the engine runs in stages only for a video that has the
switch on (and exactly as before for every other video), the step can never fail a render, the
key never rides on a command line, and the per-video switch is offered only where it can work."""

from __future__ import annotations

import json

import pytest

from tce.api.routers import production as prod
from tce.editorial import library
from tce.production import autoedit
from tce.production.backdrop import config as backdrop_config
from tce.production.backdrop import looks
from tce.production.creatorz import reels
from tce.settings import settings
from tests.unit.test_creatorz_style import (  # noqa: F401 - `client` and `wired` are fixtures
    AUTH,
    KEEP,
    WORDS,
    WS,
    client,
    edited_file,
    fake_engine,
    load,
    seed,
    wired,
)

ENGINE = """
import json, os, sys
stage, plan = sys.argv[1], json.load(open(sys.argv[2], encoding="utf8"))
work = plan["work"]
open(os.path.join(work, "stages.txt"), "a").write(stage + "\\n")
if stage == os.environ.get("FAIL_STAGE"):
    print("Traceback (most recent call last):")
    print("RuntimeError: the masks broke")
    sys.exit(1)
if stage in ("cut", "all"):
    print("cut: 2 shots, 6.5 s")
    json.dump({"fps": 30, "shots": [{}, {}]}, open(os.path.join(work, "edit.json"), "w"))
    open(os.path.join(work, "voice.wav"), "wb").write(b"v")
    open(os.path.join(work, "base.mp4"), "wb").write(b"base")
if stage in ("compose", "all"):
    json.dump({"captions": []}, open(os.path.join(work, "events.json"), "w"))
if stage in ("mix", "all"):
    picture = open(os.path.join(work, "base.mp4"), "rb").read()
    open(os.path.join(work, "reel.mp4"), "wb").write(b"reel:" + picture)
if stage in ("measure", "all"):
    json.dump([["PASS", "x", "y"]], open(os.path.join(work, "checklist.json"), "w"))
    print("PASS  x: y")
"""

STEP = """
import json, os, sys
plan = json.load(open(sys.argv[1], encoding="utf8"))
cfg = json.load(open(sys.argv[2], encoding="utf8"))
work = plan["work"]
open(os.path.join(work, "stages.txt"), "a").write("backdrop\\n")
if cfg.get("crash"):
    print("Traceback (most recent call last):")
    sys.exit(3)
print("backdrop: 4 scenes, 2 to change")
print("backdrop: scene 1/2 look lane sent (try 1, 5.0 s)")
print("backdrop: scene 1/2 ok")
print("backdrop: joined 2/2, $1.07")
open(os.path.join(work, "base.mp4"), "wb").write(b"new-base")
json.dump({
    "asked": 2, "changed": 2, "cost_usd": 1.07, "note": "", "scenes": [],
    "key_in_env": os.environ.get("TCE_BACKDROP_KEY") == "SECRET-KEY",
    "key_in_argv": any("SECRET" in a for a in sys.argv),
    "key_in_cfg": "SECRET" in json.dumps(cfg),
    "engine_dir": cfg.get("engine_dir"),
}, open(os.path.join(work, "backdrop.json"), "w"))
"""


@pytest.fixture
def staged(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "reel.py").write_text(ENGINE)
    cli = tmp_path / "step.py"
    cli.write_text(STEP)
    monkeypatch.setattr(reels, "ENGINE_DIR", engine)
    monkeypatch.setattr(reels, "_wrapper", lambda: [])
    monkeypatch.setattr(backdrop_config, "CLI", cli)
    monkeypatch.setattr(settings, "production_creatorz_python", "")
    monkeypatch.setattr(settings, "production_backdrop_key", "SECRET-KEY")
    said: list[str] = []

    async def status(text):
        said.append(text)

    async def render(backdrop=None):
        return await reels.render_reel(
            src=tmp_path / "raw.mp4",
            words=reels.engine_words(WORDS),
            keep=KEEP,
            lang="en",
            work=tmp_path / "work",
            moments=[],
            punchline=None,
            bed=None,
            on_status=status,
            backdrop=backdrop,
        )

    stages = lambda: (tmp_path / "work" / "stages.txt").read_text().split()  # noqa: E731
    return render, stages, said, tmp_path / "work"


async def test_a_video_without_the_switch_runs_the_engine_in_one_go_as_before(staged):
    render, stages, said, work = staged
    made = await render()
    assert stages() == ["all"]
    assert made.backdrop is None and made.out.read_bytes() == b"reel:base"
    assert not (work / "backdrop.cfg.json").exists()
    assert not any("backgrounds" in s for s in said)


async def test_with_the_switch_the_step_runs_between_the_cut_and_everything_drawn_on_it(staged):
    render, stages, said, work = staged
    made = await render({"looks_dir": "x", "max_usd": 8.0})
    assert stages() == ["cut", "backdrop", "masks", "compose", "mix", "measure"]
    assert made.out.read_bytes() == b"reel:new-base"  # the later stages read the changed picture
    assert made.backdrop["changed"] == 2 and made.shots == 2
    # the key reaches the step by the environment only
    assert made.backdrop["key_in_env"] is True
    assert made.backdrop["key_in_argv"] is False and made.backdrop["key_in_cfg"] is False
    assert made.backdrop["engine_dir"] == str(reels.ENGINE_DIR)
    assert (
        "Creatorz style: new backgrounds, drawing scene 1 of 2 (about a minute and a half each)"
        in said
    )
    assert (
        "Creatorz style: new backgrounds on 2 of 2 scenes, putting the picture back together"
        in said
    )


async def test_a_step_that_crashes_never_fails_the_render(staged):
    render, stages, said, work = staged
    made = await render({"crash": True})
    assert stages() == ["cut", "backdrop", "masks", "compose", "mix", "measure"]
    assert made.out.read_bytes() == b"reel:base" and made.backdrop is None
    assert "Creatorz style: the new backgrounds could not be made, keeping the real ones" in said


async def test_a_stage_that_crashes_stops_a_staged_render_like_it_stops_a_whole_one(
    staged, monkeypatch
):
    render, stages, said, work = staged
    monkeypatch.setenv("FAIL_STAGE", "masks")
    with pytest.raises(reels.CreatorzFailed) as failed:
        await render({"looks_dir": "x"})
    assert "the masks broke" in str(failed.value)
    assert stages() == ["cut", "backdrop", "masks"]  # nothing is drawn on a picture with no masks


def test_progress_lines_for_the_step():
    say = reels.progress_sentence
    assert "scene 3 of 6 is already drawn" in say(
        "backdrop: scene 3/6 look pine-path from an earlier render"
    )
    assert "drawing it once more" in say("backdrop: scene 3/6 look pine-path sent (try 2, 6.0 s)")
    assert "scene 3 of 6 keeps its real background" in say(
        "backdrop: scene 3/6 kept real (a vehicle in the frame)"
    )
    assert say("backdrop: scene 3/6 ok") is None and say("backdrop: 13 scenes, 6 to change") is None


# ------------------------------------------------------------------ the switch
@pytest.fixture
def offered(tmp_path, monkeypatch):
    """A server with a key and a set of looks for the test workspace."""
    root = tmp_path / "looks"
    folder = root / str(WS)
    folder.mkdir(parents=True)
    (folder / looks.FILE).write_text(
        json.dumps({"looks": [{"id": "lane", "place": "They walk down a lane."}]})
    )
    monkeypatch.setattr(settings, "production_backdrop_dir", str(root))
    monkeypatch.setattr(settings, "production_backdrop_key", "SECRET-KEY")
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    backdrop_config._sets.clear()
    return folder


def test_the_switch_is_offered_only_where_it_can_work(offered, monkeypatch):
    assert backdrop_config.offered(WS)
    assert not backdrop_config.offered("bbbbbbbb-2222-4222-8222-222222222222")  # no set of looks
    assert not backdrop_config.offered(None)
    monkeypatch.setattr(settings, "production_backdrop_key", "")
    assert not backdrop_config.offered(WS)  # no key for the paid model
    monkeypatch.setattr(settings, "production_backdrop_key", "SECRET-KEY")
    (offered / looks.FILE).write_text("{}")
    backdrop_config._sets.clear()
    assert not backdrop_config.offered(WS)  # a set with nothing usable in it
    monkeypatch.setattr(settings, "production_backdrop_dir", "")
    assert not backdrop_config.offered(WS)


def test_a_render_is_told_nothing_unless_this_video_has_it_on(offered, tmp_path):
    src = tmp_path / "s" / "walk.mp4"
    uid = "0a1b2c3d-0000-4000-8000-000000000001"
    assert backdrop_config.for_render(WS, uid, src, {"overrides": {"style": "creatorz"}}) is None
    told = backdrop_config.for_render(
        WS, uid, src, {"overrides": {"style": "creatorz", "backdrop": "on"}}
    )
    assert told["looks_dir"] == str(offered) and told["cache_dir"] == str(
        tmp_path / "s" / ".walk-backdrop"
    )
    assert told["max_usd"] == 8.0 and told["day_usd"] == 25.0 and told["resolution"] == "1080p"
    assert told["start_look"] == int("0a1b2c", 16)
    assert "SECRET" not in json.dumps(told)  # the key is never written into what the step is told
    assert (
        backdrop_config.for_render(
            "bbbbbbbb-2222-4222-8222-222222222222", uid, src, {"overrides": {"backdrop": "on"}}
        )
        is None
    )


def test_what_the_card_says_about_the_step():
    assert backdrop_config.said(None) == ""
    done = backdrop_config.said({"asked": 6, "changed": 6, "cost_usd": 3.71})
    assert done == ". New backgrounds on 6 of 6 scenes ($3.71)"
    part = backdrop_config.said({"asked": 6, "changed": 4, "cost_usd": 4.2})
    assert "4 of 6 scenes, 2 kept the real one after failing the check" in part
    assert "nothing new to pay" in backdrop_config.said({"asked": 6, "changed": 6, "cost_usd": 0})
    none = backdrop_config.said(
        {"asked": 0, "changed": 0, "note": "there is no set of looks for this workspace"}
    )
    assert "were not made: there is no set of looks" in none


def test_a_later_note_keeps_the_switch():
    old = {"cut": [], "restore": [], "style": "creatorz", "backdrop": "on"}
    assert autoedit.merge_overrides(old, [[1.0, 2.0]], [])["backdrop"] == "on"
    assert "backdrop" not in autoedit.merge_overrides({"style": "creatorz"}, [], [])


async def test_the_card_carries_the_switch_only_where_it_is_offered(
    offered, editorial_sessionmaker, tmp_path, monkeypatch
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker,
        src,
        edited=str(out),
        status="edited",
        overrides={"style": "creatorz"},
    )
    row = await load(editorial_sessionmaker, uid)
    style = next(a for a in library._actions(row, 0) if a["key"] == "style")
    assert style["backdrop"] == {
        "on": False,
        "about_usd": 0.5,
        "max_usd": 8.0,
    }  # 6.55 s kept, half of it drawn
    monkeypatch.setattr(settings, "production_backdrop_key", "")
    style = next(a for a in library._actions(row, 0) if a["key"] == "style")
    assert style["backdrop"] is None


async def test_switching_it_on_saves_it_and_starts_a_render(
    offered, client, editorial_sessionmaker, tmp_path
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker,
        src,
        edited=str(out),
        status="edited",
        overrides={"style": "creatorz"},
    )
    r = await client.post(
        f"/api/v1/production/uploads/{uid}/backdrop", json={"on": True}, headers=AUTH
    )
    assert r.status_code == 202, r.text
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"] == {"style": "creatorz", "backdrop": "on"}
    assert (
        row.status == "rendering"
        and "new backgrounds" in row.status_detail
        and len(client.spawned) == 1
    )


async def test_switching_it_off_takes_it_out_and_renders_the_real_one(
    offered, client, editorial_sessionmaker, tmp_path
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker,
        src,
        edited=str(out),
        status="edited",
        overrides={"style": "creatorz", "backdrop": "on"},
    )
    r = await client.post(
        f"/api/v1/production/uploads/{uid}/backdrop", json={"on": False}, headers=AUTH
    )
    assert r.status_code == 202
    row = await load(editorial_sessionmaker, uid)
    assert (
        row.edit_plan["overrides"] == {"style": "creatorz"}
        and "real backgrounds" in row.status_detail
    )
    assert len(client.spawned) == 1


async def test_the_choice_it_already_has_starts_nothing(
    offered, client, editorial_sessionmaker, tmp_path
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker,
        src,
        edited=str(out),
        status="edited",
        overrides={"style": "creatorz", "backdrop": "on"},
    )
    r = await client.post(
        f"/api/v1/production/uploads/{uid}/backdrop", json={"on": True}, headers=AUTH
    )
    assert r.status_code == 202 and client.spawned == []
    assert (await load(editorial_sessionmaker, uid)).status == "edited"


async def test_a_pill_video_is_told_to_choose_creatorz_first(
    offered, client, editorial_sessionmaker, tmp_path
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(
        f"/api/v1/production/uploads/{uid}/backdrop", json={"on": True}, headers=AUTH
    )
    assert r.status_code == 409 and "Creatorz" in r.json()["detail"]
    assert (
        client.spawned == []
        and "overrides" not in (await load(editorial_sessionmaker, uid)).edit_plan
    )


async def test_a_workspace_with_no_set_of_looks_has_no_such_switch(
    client, editorial_sessionmaker, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "production_backdrop_dir", str(tmp_path / "nothing"))
    monkeypatch.setattr(settings, "production_backdrop_key", "SECRET-KEY")
    backdrop_config._sets.clear()
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker,
        src,
        edited=str(out),
        status="edited",
        overrides={"style": "creatorz"},
    )
    r = await client.post(
        f"/api/v1/production/uploads/{uid}/backdrop", json={"on": True}, headers=AUTH
    )
    assert r.status_code == 404 and client.spawned == []


async def test_the_render_hands_the_step_its_orders_and_the_card_says_what_it_did(
    offered, wired, tmp_path, monkeypatch
):
    fake_engine(monkeypatch, wired)
    real_reel = reels.render_reel

    async def reel_with_report(**kw):
        made = await real_reel(**kw)
        made.backdrop = {
            "asked": 2,
            "changed": 2,
            "cost_usd": 1.07,
            "note": "",
            "scenes": [
                {"start_s": 0.0, "end_s": 4.0, "result": "real", "why": "opening", "look": None},
                {
                    "start_s": 4.0,
                    "end_s": 8.0,
                    "result": "new",
                    "look": "lane",
                    "cached": False,
                    "attempts": [{"try": 1}],
                },
            ],
        }
        return made

    monkeypatch.setattr(reels, "render_reel", reel_with_report)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz", "backdrop": "on"})
    await prod._run_render(uid, WS, attempt, "cut")
    told = wired["calls"]["reel"][0]["backdrop"]
    assert told["looks_dir"] == str(offered) and told["label"] == f"{WS}:{uid}"
    row = await load(wired["sm"], uid)
    assert (
        row.status == "edited" and "New backgrounds on 2 of 2 scenes ($1.07)" in row.status_detail
    )
    side = prod._read_render_sidecar(row.edited_path)["backdrop"]
    assert side["changed"] == 2 and side["cost_usd"] == 1.07
    assert side["scenes"][1] == {
        "start_s": 4.0,
        "end_s": 8.0,
        "result": "new",
        "look": "lane",
        "cached": False,
    }


async def test_a_creatorz_video_without_the_switch_tells_the_engine_nothing(
    offered, wired, tmp_path, monkeypatch
):
    fake_engine(monkeypatch, wired)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    assert wired["calls"]["reel"][0]["backdrop"] is None
    row = await load(wired["sm"], uid)
    assert "backgrounds" not in row.status_detail
    assert "backdrop" not in prod._read_render_sidecar(row.edited_path)
