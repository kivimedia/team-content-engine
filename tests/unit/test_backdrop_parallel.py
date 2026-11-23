"""New backgrounds drawn side by side (23-Nov-2026, wait-less item F12, part 1).

Up to three scenes of one render are redrawn at once. The three spend limits (one render, the
day, the live test) are kept under ONE lock: every try books what it can cost before it is sent,
so scenes racing for room that only one of them fits under can never both be paid for. The
step and its fake model are the ones test_backdrop.py drives; no paid call is made anywhere.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tce.production.backdrop import config as backdrop_config
from tce.production.backdrop import omni, step
from tce.settings import settings
from tests.unit.test_backdrop import FakeModel, cut  # noqa: F401 - `cut` is a fixture
from tests.unit.test_backdrop_wiring import WS, offered  # noqa: F401 - `offered` is a fixture

# One 5-second scene: the redraw's estimate and the look after it.
ONE_TRY = omni.estimate_usd(5.0, "1080p") + omni.LOOK_USD
# What the fake model's answer bills for one redraw (its tokens) plus the look.
ONE_PAID = 0.525 + omni.LOOK_USD


class SlowModel(FakeModel):
    """The fake model, slow enough that a second scene is sent while the first is drawn."""

    def __init__(self, *, hold_s: float = 0.6, together: int = 0, **kw):
        super().__init__(**kw)
        self.hold_s, self.flying, self.most = hold_s, 0, 0
        self._count = threading.Lock()
        self._meet = threading.Barrier(together, timeout=8) if together else None

    def edit(self, video_uri, ref_uris, prompt, *, model, resolution, out):
        with self._count:
            self.flying += 1
            self.most = max(self.most, self.flying)
        try:
            if self._meet is not None:
                try:
                    self._meet.wait()  # every scene in flight at the same moment
                except threading.BrokenBarrierError:
                    raise omni.OmniError("edit: the scenes were not drawn side by side") from None
            time.sleep(self.hold_s)
            return super().edit(video_uri, ref_uris, prompt, model=model, resolution=resolution, out=out)
        finally:
            with self._count:
                self.flying -= 1


def _ledger(cfg) -> list[dict]:
    path = Path(cfg["ledger"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ------------------------------------------------------------ side by side
def test_the_scenes_are_drawn_side_by_side_and_the_report_keeps_their_order(cut):
    work, cfg = cut
    model, said = SlowModel(together=2, hold_s=0.0), []
    report = step.run(work / "plan.json", {**cfg, "parallel": 3}, api=model, say=said.append)
    assert model.most == 2, "both scenes were in flight at once"
    assert report["asked"] == 2 and report["changed"] == 2 and report["note"] == ""
    assert [e["result"] for e in report["scenes"]] == ["real", "new", "real", "new"]
    assert [e["look"] for e in report["scenes"] if e["result"] == "new"] == ["lane", "pines"]
    assert report["cost_usd"] == pytest.approx(2 * ONE_PAID, abs=1e-3)
    # spend.jsonl gets its one line for the render, as before.
    [line] = _ledger(cfg)
    assert line["cost_usd"] == pytest.approx(report["cost_usd"]) and line["drawn_s"] == 10.0
    assert said[-1].startswith("backdrop: joined 2/2, $")
    assert all(line.startswith("backdrop: ") for line in said)  # never two lines run together


def test_one_at_a_time_is_what_a_render_gets_without_the_number(cut):
    work, cfg = cut
    model = SlowModel(hold_s=0.2)
    report = step.run(work / "plan.json", cfg, api=model)
    assert model.most == 1 and report["changed"] == 2


def test_the_app_tells_each_render_how_many_at_once(offered, tmp_path):  # noqa: F811
    assert settings.production_backdrop_parallel == 3
    told = backdrop_config.for_render(
        WS, "0a1b2c3d-0000-4000-8000-000000000001", tmp_path / "walk.mp4",
        {"overrides": {"style": "creatorz", "backdrop": "on"}},
    )
    assert told["parallel"] == 3 and told["max_usd"] == 8.0 and told["day_usd"] == 25.0


# ------------------------------------------------------------ the race for room
RACES = {
    # Room for one try, never two, under each of the three limits in turn.
    "one render": ({"max_usd": 0.9}, [], "the spend limit for one video ($0.90) was reached"),
    "the day": (
        {"day_usd": 25.0},
        [{"at": "now", "label": "other", "cost_usd": 24.2}],
        "the spend limit for one day ($25.00) was reached",
    ),
    "the live test": (
        {"day_usd": 25.0, "trial": {"usd": 16.0, "labels": ["test", "earlier"]}},
        [{"at": "2026-01-01T00:00:00+00:00", "label": "earlier", "cost_usd": 15.2}],
        "the live test's limit ($16.00 for its videos) was reached",
    ),
}


def _race(cut, limit: str, workers: int = 3):
    work, cfg = cut
    extra, rows, why = RACES[limit]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    Path(cfg["ledger"]).write_text(
        "".join(json.dumps({**r, "at": now if r["at"] == "now" else r["at"]}) + "\n" for r in rows)
    )
    before = step.spent_since(cfg["ledger"], None)
    model = SlowModel()
    report = step.run(work / "plan.json", {**cfg, **extra, "parallel": workers}, api=model)
    return report, model, step.spent_since(cfg["ledger"], None) - before, why


@pytest.mark.parametrize("limit", list(RACES))
def test_two_scenes_racing_for_room_only_one_fits_under_and_only_one_is_paid(cut, limit):
    report, model, added, why = _race(cut, limit)
    assert len(model.edits) == 1 and report["changed"] == 1, "one try fits; the other is never sent"
    # The first scene gets the room, as it did one at a time; the second keeps its real place.
    assert [e["result"] for e in report["scenes"]] == ["real", "new", "real", "real"]
    assert report["scenes"][3]["why"] == why
    assert added == pytest.approx(ONE_PAID) and added <= 0.9  # what spend.jsonl was told


def test_the_race_test_catches_a_booking_that_does_not_hold_its_room(cut, monkeypatch):
    """The planted-bad case: a check that looks only at what is already spent (the old
    one-at-a-time check, run side by side) lets both scenes through. The test above must
    fail on it, and it does: two redraws are paid for under room for one."""

    def unheld(self, usd, turn=None):
        return round(self.spent + usd, 6) <= round(self.room, 6)

    monkeypatch.setattr(step.Budget, "book", unheld)
    report, model, added, _why = _race(cut, "one render")
    assert len(model.edits) == 2 and report["changed"] == 2 and added > 0.9


# ------------------------------------------------------------ the budget itself
def test_three_tries_racing_for_room_for_one_get_one_booking():
    budget = step.Budget(8.0)
    meet, got = threading.Barrier(3), []

    def go():
        meet.wait()  # all three ask at the same moment
        got.append(budget.book(5.0))

    threads = [threading.Thread(target=go, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    assert got == [True] and budget.held == pytest.approx(5.0), "one holds the room, two wait"
    budget.settle(5.0, 5.0)  # the one in flight really spent it
    for t in threads:
        t.join(5)
    assert sorted(got) == [False, False, True]
    assert budget.spent == pytest.approx(5.0) and budget.held == 0.0


def test_a_try_waits_for_one_in_flight_and_gets_its_room_back_when_that_one_cost_nothing():
    budget = step.Budget(1.0)
    assert budget.book(0.6)
    result: list[bool] = []
    later = threading.Thread(target=lambda: result.append(budget.book(0.6)), daemon=True)
    later.start()
    time.sleep(0.2)
    assert result == [], "it waits while the other try may still cost less"
    budget.settle(0.6, 0.0)  # the model did not answer: nothing was spent
    later.join(5)
    assert result == [True] and budget.held == pytest.approx(0.6)


def test_a_try_is_refused_once_the_one_in_flight_really_spent_the_room():
    budget = step.Budget(1.0)
    assert budget.book(0.6)
    result: list[bool] = []
    later = threading.Thread(target=lambda: result.append(budget.book(0.6)), daemon=True)
    later.start()
    time.sleep(0.2)
    budget.settle(0.6, 0.55, 5.0)
    later.join(5)
    assert result == [False] and budget.spent == pytest.approx(0.55) and budget.held == 0.0
    assert budget.drawn_s == 5.0


def test_first_tries_book_in_scene_order_whoever_asks_first():
    budget = step.Budget(1.0)
    result: dict[int, bool] = {}
    second = threading.Thread(target=lambda: result.__setitem__(2, budget.book(0.6, 2)), daemon=True)
    second.start()
    time.sleep(0.2)
    assert result == {}, "scene 2 waits for scene 1 to book"
    assert budget.book(0.6, 1) is True
    budget.settle(0.6, 0.6)
    second.join(5)
    assert result == {2: False}
    # A scene that never books (drawn on an earlier render) lets the next one go at once.
    budget = step.Budget(5.0)
    budget.passed(1)
    assert budget.book(0.6, 2) is True


def test_nothing_is_booked_once_a_scene_broke():
    budget = step.Budget(8.0)
    budget.close()
    assert budget.book(0.1) is False and budget.held == 0.0
