"""Pictures for the Creatorz style (11-Nov-2026, Ziv: "pictures").

He attaches real pictures or screenshots to a recording, each with a short note saying what it
shows, and the Creatorz writer cuts away to one when he talks about that thing. The files sit on
disk next to the recording; the list lives in the edit's overrides, so his notes keep it."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from PIL import Image

from tce.api.routers import production as prod
from tce.editorial import library
from tce.production import autoedit
from tce.production.creatorz import reels
from tce.settings import settings
from tests.unit.test_creatorz_style import (  # noqa: F401  (fixtures are used by name)
    AUTH,
    KEEP,
    OTHER_WS,
    WORDS,
    WS,
    at,
    card,
    client,
    edited_file,
    fake_engine,
    load,
    seed,
    shots,
    wired,
)

P1 = {"id": "p1", "file": "p1.png", "note": "the delivery van", "w": 40, "h": 70}
P2 = {"id": "p2", "file": "p2.jpg", "note": "a screenshot of the price list", "w": 30, "h": 90}


def image_bytes(fmt="PNG", size=(40, 70)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 40, 200)).save(buf, format=fmt)
    return buf.getvalue()


def post_picture(client, uid, data, *, ctype="image/png", name="van.PNG", note="the delivery van", headers=AUTH):
    return client.post(
        f"/api/v1/production/uploads/{uid}/pictures", files={"file": (name, data, ctype)},
        data={"note": note} if note is not None else {}, headers=headers,
    )


# ---------------------------------------------------------------- the list survives his notes
def test_a_later_note_keeps_the_pictures():
    merged = autoedit.merge_overrides({"style": "creatorz", "pictures": [P1], "cut": []}, [[3.0, 4.0]], [])
    assert merged["pictures"] == [P1]
    assert "pictures" not in autoedit.merge_overrides({"cut": []}, [], [])


# ---------------------------------------------------------------- the API
async def test_a_picture_is_stored_next_to_the_recording(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, image_bytes())
    assert r.status_code == 201, r.text
    got = r.json()["pictures"]
    assert got == [{"id": "p1", "note": "the delivery van", "w": 40, "h": 70,
                    "url": f"/api/v1/production/uploads/{uid}/pictures/p1"}]
    stored = tmp_path / ".walk-pictures" / "p1.png"  # the original extension, lower-case
    assert stored.read_bytes() == image_bytes()
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"]["pictures"] == [{**P1}]
    assert client.spawned == []  # adding one does not start a render; he picks when to restyle
    r2 = await post_picture(client, uid, image_bytes("JPEG", (30, 90)), ctype="image/jpeg", name="list.jpg",
                            note="a screenshot of the price list")
    assert [p["id"] for p in r2.json()["pictures"]] == ["p1", "p2"]
    assert (tmp_path / ".walk-pictures" / "p2.jpg").exists()


async def test_a_picture_needs_a_short_note(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    assert (await post_picture(client, uid, image_bytes(), note=None)).status_code == 422
    assert (await post_picture(client, uid, image_bytes(), note="   ")).status_code == 422
    assert (await post_picture(client, uid, image_bytes(), note="x" * 121)).status_code == 422
    assert "pictures" not in ((await load(editorial_sessionmaker, uid)).edit_plan.get("overrides") or {})


async def test_only_pictures_are_taken(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, b"GIF89a....", ctype="image/gif", name="a.gif")
    assert r.status_code == 415
    # the bytes have to be the picture they say they are
    fake = await post_picture(client, uid, b"\x89PNG\r\n\x1a\nnot really a png at all", name="a.png")
    assert fake.status_code == 400 and "picture" in fake.json()["detail"]
    liar = await post_picture(client, uid, image_bytes("JPEG"), ctype="image/png", name="a.png")
    assert liar.status_code == 400
    assert not (tmp_path / ".walk-pictures").exists() or not list((tmp_path / ".walk-pictures").iterdir())


async def test_a_picture_too_big_is_refused(client, editorial_sessionmaker, tmp_path, monkeypatch):
    monkeypatch.setattr(prod, "PICTURE_MAX_BYTES", 500)
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, image_bytes(size=(400, 400)) + b"\0" * 2000)
    assert r.status_code == 413
    assert prod.PICTURE_MAX_BYTES == 500 and prod.PICTURE_TYPES == {"image/png", "image/jpeg", "image/webp"}


def test_the_real_limit_is_15_mb():
    assert prod.PICTURE_MAX_BYTES == 15 * 1024 * 1024 and reels.MAX_PICTURES == 8


async def test_a_ninth_picture_is_refused(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    eight = [{"id": f"p{n}", "file": f"p{n}.png", "note": f"n{n}", "w": 1, "h": 1} for n in range(1, 9)]
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited", overrides={"pictures": eight})
    r = await post_picture(client, uid, image_bytes())
    assert r.status_code == 409 and "8" in r.json()["detail"]


async def test_another_workspaces_video_is_not_found(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    # a real picture on the other workspace's video, so a 404 can only come from the scoping
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited", ws=OTHER_WS,
                        overrides={"pictures": [P1]})
    stored = stored_p1(tmp_path)
    assert (await post_picture(client, uid, image_bytes())).status_code == 404
    assert (await client.get(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 404
    assert (await client.delete(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 404
    assert stored.exists()


async def test_a_workspace_not_listed_has_no_pictures(client, editorial_sessionmaker, tmp_path, monkeypatch):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited", overrides={"pictures": [P1]})
    stored = stored_p1(tmp_path)
    assert (await client.get(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 200
    monkeypatch.setattr(settings, "production_creatorz_workspaces", "")
    assert (await post_picture(client, uid, image_bytes())).status_code == 404
    assert (await client.get(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 404
    assert (await client.delete(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 404
    assert stored.exists()


def stored_p1(tmp_path) -> Path:
    folder = tmp_path / ".walk-pictures"
    folder.mkdir(exist_ok=True)
    stored = folder / "p1.png"
    stored.write_bytes(image_bytes())
    return stored


async def test_no_picture_changes_while_the_video_is_being_made(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="rendering")
    r = await post_picture(client, uid, image_bytes())
    assert r.status_code == 409


async def test_a_picture_is_served_and_removed(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    await post_picture(client, uid, image_bytes())
    got = await client.get(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content == image_bytes()
    assert (await client.get(f"/api/v1/production/uploads/{uid}/pictures/p9", headers=AUTH)).status_code == 404
    gone = await client.delete(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)
    assert gone.status_code == 200 and gone.json()["pictures"] == []
    assert not (tmp_path / ".walk-pictures" / "p1.png").exists()
    assert (await load(editorial_sessionmaker, uid)).edit_plan["overrides"].get("pictures", []) == []
    assert (await client.delete(f"/api/v1/production/uploads/{uid}/pictures/p1", headers=AUTH)).status_code == 404
    assert client.spawned == []


# ---------------------------------------------------------------- the writer
def test_the_prompt_lists_the_pictures_only_when_there_are_some():
    with_pics = reels.moments_prompt(shots(), "en", [P1, P2])
    assert "Pictures he added (show each one at most once, when he talks about what it shows):" in with_pics
    assert "[p1] the delivery van" in with_pics and "[p2] a screenshot of the price list" in with_pics
    assert with_pics.index("Lines:") < with_pics.index("Pictures he added")
    assert "Picture" not in reels.moments_prompt(shots(), "en") and "picture" not in reels.moments_prompt(shots(), "en", [])
    assert "- insert: picture (an id from the pictures list)" in reels.MOMENTS_SYSTEM
    assert "insert" in reels.MOMENTS_SCHEMA["properties"]["moments"]["items"]["properties"]["type"]["enum"]
    assert reels.PROMPT_VERSION == "creatorz-moments-5"


def test_a_good_insert_is_kept_and_an_invented_src_never_reaches_the_engine():
    raw = [{"type": "insert", "picture": "p1", "at": at(0, "count"), "src": "/etc/passwd", "hold": 9}]
    moments, problems = reels.clean_moments(raw, shots(), "en", [P1])
    assert moments == [{"type": "insert", "picture": "p1", "at": at(0, "count")}] and problems == []


def test_an_unknown_or_repeated_picture_is_named_for_the_writer():
    raw = [
        {"type": "insert", "picture": "p1", "at": at(0, "count")},
        {"type": "insert", "picture": "p7", "at": at(1, "came")},
        {"type": "insert", "picture": "p1", "at": at(2, "number")},
        {"type": "insert", "src": "/tmp/x.png", "at": at(2, "job.")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en", [P1])
    assert [m["picture"] for m in moments] == ["p1"]
    assert any("p7" in p and "no picture" in p for p in problems)
    assert any("p1" in p and "once" in p for p in problems)
    assert any("moment 3" in p and "picture" in p for p in problems)
    assert len(problems) == 3


def test_an_insert_on_a_video_with_no_pictures_is_refused():
    moments, problems = reels.clean_moments([{"type": "insert", "picture": "p1", "at": at(0, "count")}], shots(), "en")
    assert moments == [] and "no pictures" in problems[0]


async def test_get_moments_hands_the_pictures_to_the_writer_and_the_check():
    prompts: list[str] = []

    async def ask(prompt, system, schema, attempt):
        prompts.append(prompt)
        return {"moments": [{"type": "insert", "picture": "p1", "at": at(0, "count")},
                            {"type": "tag", "text": "x", "at": at(2, "number")}], "punchline": None}

    got = await reels.get_moments(shots(), "en", ask, pictures=[P1])
    assert "[p1] the delivery van" in prompts[0]
    assert got["moments"][0] == {"type": "insert", "picture": "p1", "at": at(0, "count")}


def test_the_moments_key_changes_when_a_picture_is_added_or_its_note_changes():
    words = reels.engine_words(WORDS)
    none = reels.moments_key(KEEP, words)
    assert none == reels.moments_key(KEEP, words, [])
    one = reels.moments_key(KEEP, words, [P1])
    assert one != none
    assert reels.moments_key(KEEP, words, [{**P1, "note": "the red van"}]) != one
    assert reels.moments_key(KEEP, words, [{**P1, "w": 999}]) == one  # only what the writer reads


# ---------------------------------------------------------------- the render
def test_picture_ids_become_files_for_the_engine_and_a_missing_one_is_dropped(tmp_path):
    folder = tmp_path / ".walk-pictures"
    folder.mkdir()
    (folder / "p1.png").write_bytes(image_bytes())
    moments = [
        {"type": "headline", "text": "A", "place": "top", "at": at(0, "count")},
        {"type": "insert", "picture": "p2", "at": at(1, "came")},
        {"type": "insert", "picture": "p1", "at": at(0, "owners")},
        {"type": "strike", "target": 0, "at": at(2, "number")},
    ]
    out, missing = reels.with_picture_files(moments, [P1, P2], folder)
    assert missing == ["p2"]
    assert [m["type"] for m in out] == ["headline", "insert", "strike"]
    assert out[1]["src"] == str(folder / "p1.png") and Path(out[1]["src"]).is_absolute()
    assert out[2]["target"] == 0
    assert "src" not in moments[2]  # the saved moments keep the id only


async def test_the_render_hands_the_engine_real_files_and_keeps_the_ids(wired, tmp_path, monkeypatch, caplog):
    fake_engine(monkeypatch, wired)
    seen: dict = {}

    async def moments_with_pictures(shots_, lang, ask, pictures=(), **_kw):
        seen["pictures"] = list(pictures)
        return {"moments": [{"type": "tag", "text": "x", "at": at(0, "count")},
                            {"type": "insert", "picture": "p1", "at": at(1, "came")},
                            {"type": "insert", "picture": "p2", "at": at(2, "number")}], "punchline": None}

    monkeypatch.setattr(reels, "get_moments", moments_with_pictures)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    folder = tmp_path / ".walk-pictures"
    folder.mkdir()
    (folder / "p1.png").write_bytes(image_bytes())  # p2's file is gone
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz", "pictures": [P1, P2]})
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    assert row.status == "edited" and row.status_detail.startswith("Creatorz style ready")
    assert [p["id"] for p in seen["pictures"]] == ["p1", "p2"]
    sent = wired["calls"]["reel"][0]["moments"]
    assert [m["type"] for m in sent] == ["tag", "insert"] and sent[1]["src"] == str(folder / "p1.png")
    saved = row.edit_plan["creatorz"]
    assert [m.get("picture") for m in saved["moments"]] == [None, "p1", "p2"]
    assert all("src" not in m for m in saved["moments"])
    assert saved["pictures"] == [["p1", "the delivery van"], ["p2", "a screenshot of the price list"]]
    assert "p2" in caplog.text


# ---------------------------------------------------------------- the card
def test_the_card_carries_the_pictures_and_says_when_creatorz_is_out_of_date(monkeypatch):
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    uid = uuid.uuid4()
    plain = next(a for a in library._actions(card(id=uid), 0) if a["key"] == "style")
    assert plain["pictures"] == [] and plain["stale"] is False
    plan = {"overrides": {"style": "creatorz", "pictures": [P1]}, "creatorz": {"pictures": []}}
    action = next(a for a in library._actions(card(id=uid, edit_plan=plan), 0) if a["key"] == "style")
    assert action["pictures"] == [{"id": "p1", "note": "the delivery van", "w": 40, "h": 70,
                                   "url": f"/api/v1/production/uploads/{uid}/pictures/p1"}]
    assert action["stale"] is True
    plan["creatorz"]["pictures"] = [["p1", "the delivery van"]]
    assert next(a for a in library._actions(card(id=uid, edit_plan=plan), 0) if a["key"] == "style")["stale"] is False


async def test_creatorz_again_after_a_picture_changed_makes_a_new_version(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited",
                        overrides={"style": "creatorz", "pictures": [P1]}, extra={"creatorz": {"pictures": []}})
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 202 and len(client.spawned) == 1


def test_the_page_offers_pictures_and_every_new_button_is_tappable():
    js = (Path(prod.__file__).parents[1] / "workspace.js").read_text(encoding="utf-8")
    he = (Path(prod.__file__).parents[1] / "i18n-he.js").read_text(encoding="utf-8")
    for attr in ("pictures-toggle", "picture-add", "picture-remove"):
        assert f"data-{attr}=" in js and f'"{attr}"' in js
    for text in ("Pictures", "Add a picture", "Remove", "What does this picture show? One short line.",
                 "Picture added. Make the Creatorz version again to use it."):
        assert f'"{text}":' in he, text
    assert "Pictures \\((\\d+)\\)" in he


@pytest.mark.parametrize("ctype", ["image/png", "image/jpeg", "image/webp"])
def test_each_picture_type_is_read_by_its_bytes(ctype):
    fmt = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[ctype]
    assert prod.picture_size(image_bytes(fmt), ctype) == (40, 70)
    with pytest.raises(ValueError):
        prod.picture_size(b"nope", ctype)


# ---------------------------------------------------------------- review fixes (11-Nov)
async def test_a_phone_photo_with_more_than_one_frame_is_a_jpeg(client, editorial_sessionmaker, tmp_path):
    # Many phone and camera JPEGs carry an MPF segment; Pillow names them MPO, they are still JPEGs.
    buf = io.BytesIO()
    Image.new("RGB", (40, 70), "red").save(buf, "MPO", save_all=True, append_images=[Image.new("RGB", (40, 70), "blue")])
    assert buf.getvalue()[:3] == b"\xff\xd8\xff"
    assert prod.picture_size(buf.getvalue(), "image/jpeg") == (40, 70)
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, buf.getvalue(), ctype="image/jpeg", name="IMG_0001.JPG")
    assert r.status_code == 201, r.text


async def test_a_cut_off_jpeg_is_refused_at_the_upload(client, editorial_sessionmaker, tmp_path):
    buf = io.BytesIO()
    Image.effect_noise((400, 400), 50).convert("RGB").save(buf, "JPEG")
    half = buf.getvalue()[: len(buf.getvalue()) // 2]
    with pytest.raises(ValueError):
        prod.picture_size(half, "image/jpeg")
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    assert (await post_picture(client, uid, half, ctype="image/jpeg", name="a.jpg")).status_code == 400


async def test_a_sideways_phone_photo_is_stored_upright(client, editorial_sessionmaker, tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6  # stored landscape, shown upright
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), (200, 40, 20)).save(buf, "JPEG", exif=exif)
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, buf.getvalue(), ctype="image/jpeg", name="IMG.jpg")
    assert r.status_code == 201, r.text
    assert (r.json()["pictures"][0]["w"], r.json()["pictures"][0]["h"]) == (30, 60)
    with Image.open(tmp_path / ".walk-pictures" / "p1.jpg") as stored:
        assert stored.size == (30, 60) and stored.format == "JPEG"
        assert stored.getexif().get(0x0112, 1) == 1


async def test_a_picture_with_too_many_pixels_is_refused(client, editorial_sessionmaker, tmp_path, monkeypatch):
    monkeypatch.setattr(prod, "PICTURE_MAX_PIXELS", 1000)
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await post_picture(client, uid, image_bytes(size=(40, 70)))
    assert r.status_code == 413 and "pixels" in r.json()["detail"]
    assert prod.PICTURE_MAX_PIXELS == 1000


def test_the_real_pixel_limit_is_40_million():
    assert prod.PICTURE_MAX_PIXELS == 40_000_000


async def test_two_adds_at_once_get_two_pictures(client, editorial_sessionmaker, tmp_path):
    import asyncio

    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    a, b = await asyncio.gather(
        post_picture(client, uid, image_bytes(), note="one"), post_picture(client, uid, image_bytes(), note="two"),
    )
    assert a.status_code == 201 and b.status_code == 201
    got = (await load(editorial_sessionmaker, uid)).edit_plan["overrides"]["pictures"]
    assert sorted(p["id"] for p in got) == ["p1", "p2"] and sorted(p["note"] for p in got) == ["one", "two"]
    assert sorted(f.name for f in (tmp_path / ".walk-pictures").iterdir()) == ["p1.png", "p2.png"]


def test_the_picture_block_takes_a_row_of_its_own():
    css = (Path(prod.__file__).parents[1] / "workspace.css").read_text(encoding="utf-8")
    import re

    for cls in (".style-pick", ".pictures-pick"):
        rule = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", css).group(1)
        assert "flex: 1 1 100%" in rule, cls


def test_the_page_guards_a_picture_upload_and_a_second_remove():
    js = (Path(prod.__file__).parents[1] / "workspace.js").read_text(encoding="utf-8")
    he = (Path(prod.__file__).parents[1] / "i18n-he.js").read_text(encoding="utf-8")
    assert "pictureBusy" in js and "Adding the picture..." in js
    assert '"Adding the picture...":' in he
    assert '"Creatorz again":' in he
    for sentence in ("This picture file is empty", "This video has no such picture",
                     "The picture has too many pixels (over 40 million)"):
        assert f'"{sentence}":' in he, sentence
