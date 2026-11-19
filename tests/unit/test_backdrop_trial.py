"""The live test of new backgrounds (19-Nov-2026): of the next four Creatorz videos, the 1st and
3rd get new places, the 2nd and 4th keep the real ones, all under one total. Armed by a file next
to the workspace's looks and by nothing else; his own presses on the card always win."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tce.editorial import library
from tce.production.backdrop import config as backdrop_config
from tce.production.backdrop import step, trial
from tests.unit.test_backdrop_wiring import offered  # noqa: F401 - fixture
from tests.unit.test_creatorz_style import (  # noqa: F401 - `client` and `wired` are fixtures
    AUTH,
    WS,
    client,
    edited_file,
    load,
    seed,
    wired,
)

A, B, C, D, E = (f"0a1b2c3d-0000-4000-8000-00000000000{i}" for i in range(1, 6))
PAST = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def arm(folder, since="2026-11-19T00:00:00+02:00", plan=("new", "real", "new", "real"), usd=16):
    (folder / trial.FILE).write_text(json.dumps({"since": since, "plan": list(plan), "usd": usd, "videos": []}))
    trial._seen.clear()


def after(hours: float = 1.0) -> datetime:
    return datetime(2026, 11, 18, 22, 0, tzinfo=UTC) + timedelta(hours=hours)  # 19-Nov 00:00 Israel = 18-Nov 22:00 UTC


# ---------------------------------------------------------------- the file
def test_no_file_means_no_test(tmp_path):
    assert trial.load(tmp_path) is None and trial.load(None) is None
    assert trial.join(tmp_path, A, after()) is None
    assert trial.card(tmp_path, A) is None and trial.money(tmp_path, WS, A) is None


@pytest.mark.parametrize("bad", ["{", '{"since": "2026-11-19", "plan": [], "usd": 16}',
                                 '{"since": "2026-11-19", "plan": ["maybe"], "usd": 16}',
                                 '{"since": "2026-11-19", "plan": ["new"], "usd": 0}'])
def test_a_file_that_does_not_read_as_a_test_is_no_test(tmp_path, bad):
    (tmp_path / trial.FILE).write_text(bad)
    trial._seen.clear()
    assert trial.load(tmp_path) is None and trial.join(tmp_path, A, after()) is None


def test_the_next_four_take_new_real_new_real_and_a_fifth_is_not_in(tmp_path):
    arm(tmp_path)
    got = [trial.join(tmp_path, u, after(i)) for i, u in enumerate((A, B, C, D))]
    assert [(g["slot"], g["arm"], g["of"], g["joined"]) for g in got] == [
        (1, "new", 4, True), (2, "real", 4, True), (3, "new", 4, True), (4, "real", 4, True)]
    assert trial.join(tmp_path, E, after(5)) is None
    saved = json.loads((tmp_path / trial.FILE).read_text())
    assert [v["upload_id"] for v in saved["videos"]] == [A, B, C, D]
    assert saved["since"] == "2026-11-19T00:00:00+02:00" and saved["usd"] == 16


def test_a_video_already_in_keeps_its_place_and_is_not_counted_twice(tmp_path):
    arm(tmp_path)
    trial.join(tmp_path, A, after())
    again = trial.join(tmp_path, A, after())
    assert again["slot"] == 1 and "joined" not in again
    assert trial.said(again) == ""  # its first render already said it
    assert trial.join(tmp_path, B, after())["slot"] == 2


def test_a_video_uploaded_before_the_test_began_is_not_in_it(tmp_path):
    arm(tmp_path)
    assert trial.join(tmp_path, A, PAST) is None
    assert trial.join(tmp_path, A, None) is None
    # The database keeps upload times as UTC without a zone.
    assert trial.join(tmp_path, B, after().replace(tzinfo=None))["slot"] == 1


def test_what_the_card_and_the_render_are_told(tmp_path):
    arm(tmp_path)
    trial.join(tmp_path, A, after())
    trial.join(tmp_path, B, after())
    assert trial.card(tmp_path, B) == {"slot": 2, "of": 4, "arm": "real"}
    assert trial.card(tmp_path, C) is None
    assert trial.money(tmp_path, WS, A) == {"usd": 16.0, "labels": [f"{WS}:{A}", f"{WS}:{B}"]}
    assert trial.money(tmp_path, WS, C) is None
    first = trial.join(tmp_path, C, after())
    assert trial.said(first) == " with new places (live test, video 3 of 4)"


# ---------------------------------------------------------------- money
def _ledger(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


def test_spent_since_can_count_only_the_test_videos_and_all_time(tmp_path):
    now = datetime.now(UTC)
    ledger = _ledger(tmp_path / "spend.jsonl", [
        {"at": (now - timedelta(days=3)).isoformat(), "label": "w:a", "cost_usd": 4.0},
        {"at": now.isoformat(), "label": "w:b", "cost_usd": 5.0},
        {"at": now.isoformat(), "label": "w:other", "cost_usd": 3.0},
    ])
    assert step.spent_since(ledger) == pytest.approx(8.0)
    assert step.spent_since(ledger, None) == pytest.approx(12.0)
    assert step.spent_since(ledger, None, {"w:a", "w:b"}) == pytest.approx(9.0)


def test_the_test_total_stops_a_render_once_its_videos_have_spent_it(tmp_path):
    now = datetime.now(UTC).isoformat()
    ledger = _ledger(tmp_path / "spend.jsonl", [
        {"at": now, "label": "w:a", "cost_usd": 9.0},
        {"at": now, "label": "w:other", "cost_usd": 7.0},  # not a test video: not the test's money
    ])
    cfg = {"max_usd": 8.0, "day_usd": 25.0, "ledger": ledger, "trial": {"usd": 16.0, "labels": ["w:a", "w:c"]}}
    out, stop = step.limited(cfg)
    assert stop is None and out["max_usd"] == pytest.approx(7.0)
    assert out["limit_why"] == "the live test's limit ($16.00 for its videos) was reached"
    _ledger(tmp_path / "spend.jsonl", [{"at": now, "label": "w:a", "cost_usd": 9.0},
                                       {"at": now, "label": "w:c", "cost_usd": 7.5}])
    out, stop = step.limited(cfg)
    assert stop == "the live test's limit ($16.00 for its videos) was reached"


def test_a_render_outside_the_test_has_only_its_own_and_the_days_limits(tmp_path):
    now = datetime.now(UTC).isoformat()
    ledger = _ledger(tmp_path / "spend.jsonl", [{"at": now, "label": "w:a", "cost_usd": 20.0}])
    out, stop = step.limited({"max_usd": 8.0, "day_usd": 25.0, "ledger": ledger})
    assert stop is None and out["max_usd"] == pytest.approx(5.0) and "one day" in out["limit_why"]
    out, stop = step.limited({"max_usd": 8.0, "day_usd": 0, "ledger": ledger})
    assert stop is None and out["max_usd"] == 8.0 and "limit_why" not in out
    _ledger(tmp_path / "spend.jsonl", [{"at": now, "label": "w:a", "cost_usd": 25.0}])
    assert step.limited({"max_usd": 8.0, "day_usd": 25.0, "ledger": ledger})[1] == (
        "the spend limit for one day ($25.00) was reached")


def test_the_render_of_a_test_video_carries_the_total(offered, tmp_path):  # noqa: F811
    arm(offered, since="2026-01-01T00:00:00+00:00")
    backdrop_config.join_trial(WS, A, after())
    plan = {"overrides": {"style": "creatorz", "backdrop": "on"}}
    told = backdrop_config.for_render(WS, A, tmp_path / "walk.mp4", plan)
    assert told["trial"] == {"usd": 16.0, "labels": [f"{WS}:{A}"]}
    assert "trial" not in backdrop_config.for_render(WS, B, tmp_path / "walk.mp4", plan)


# ---------------------------------------------------------------- the route and the card
async def test_turning_new_videos_to_creatorz_fills_the_test_in_order(
    offered, client, editorial_sessionmaker, tmp_path  # noqa: F811
):
    arm(offered, since="2026-01-01T00:00:00+00:00")
    src, out = edited_file(tmp_path)
    first, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    second, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    for uid in (first, second):
        r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
        assert r.status_code == 202, r.text
    one, two = await load(editorial_sessionmaker, first), await load(editorial_sessionmaker, second)
    assert one.edit_plan["overrides"] == {"style": "creatorz", "backdrop": "on"}
    assert one.status_detail == "Queued: making the Creatorz version with new places (live test, video 1 of 4)"
    assert two.edit_plan["overrides"] == {"style": "creatorz"}
    assert two.status_detail == "Queued: making the Creatorz version with the real backgrounds (live test, video 2 of 4)"
    assert len(client.spawned) == 2
    one.status = "edited"  # once the render is done, the card shows the Style row again
    card = next(a for a in library._actions(one, 0) if a["key"] == "style")
    assert card["backdrop"]["trial"] == {"slot": 1, "of": 4, "arm": "new"} and card["backdrop"]["on"] is True


async def test_a_video_from_before_the_test_turns_creatorz_as_always(
    offered, client, editorial_sessionmaker, tmp_path  # noqa: F811
):
    arm(offered, since="2099-01-01T00:00:00+00:00")
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 202
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"] == {"style": "creatorz"}
    assert row.status_detail == "Queued: making the Creatorz version"
    assert json.loads((offered / trial.FILE).read_text())["videos"] == []
    row.status = "edited"
    card = next(a for a in library._actions(row, 0) if a["key"] == "style")
    assert "trial" not in card["backdrop"]


async def test_without_the_test_file_creatorz_is_exactly_as_before(
    offered, client, editorial_sessionmaker, tmp_path  # noqa: F811
):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 202
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"] == {"style": "creatorz"}
    assert row.status_detail == "Queued: making the Creatorz version"
    assert not (offered / trial.FILE).exists()
