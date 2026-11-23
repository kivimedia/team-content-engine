"""Jennifer's slow readings of an edit run at once (23-Nov-2026, wait-less item F12, part 2).

The second listen, the loudness meter, the caption frames, the word marks and her reading of
the words on the subscription used to run one after another. They now run together; each
answer lands in the check it always fed, the card says what she is doing, and one that
breaks stops the rest the way it did before. The real render and meters run on a generated
recording (test_jennifer_flow.py); the worker is the fake one there.
"""

from __future__ import annotations

import asyncio

import pytest

from tce.api.routers import production as prod
from tce.production import qc
from tests.unit.test_jennifer_flow import (  # noqa: F401 - `wired` and `tone_recogniser` are fixtures
    CLEAN,
    edit,
    needs_ffmpeg,
    spoken,
    tone_recogniser,
    wired,
)

SLOW = ("listens", "loudness", "frames", "marks", "asides")


def _meeting(monkeypatch, *, late: str | None = None, endless: bool = False, broken: str | None = None):
    """Each slow reading waits until all five are in flight at once (or 3 s pass), then
    answers as the real one does. `late` finishes only after the others (or never, when
    `endless`); `broken` raises instead of answering."""
    seen = {"in_flight": 0, "most": 0, "cancelled": [], "finished": []}
    all_in = asyncio.Event()
    others_done = asyncio.Event()
    real = {
        "listens": prod._qc_render_listens,
        "loudness": qc.measure_loudness,
        "frames": qc.sample_caption_frames,
        "marks": prod.word_marks_for,
        "asides": prod._qc_asides,
    }

    def wrap(name):
        async def reading(*a, **k):
            seen["in_flight"] += 1
            seen["most"] = max(seen["most"], seen["in_flight"])
            if seen["in_flight"] == len(SLOW):
                all_in.set()
            try:
                try:
                    await asyncio.wait_for(all_in.wait(), 3)
                except TimeoutError:
                    pass
                if name == broken:
                    raise RuntimeError(f"{name} broke")
                if name == late:
                    if endless:
                        await asyncio.sleep(60)
                    try:
                        await asyncio.wait_for(others_done.wait(), 20)
                    except TimeoutError:
                        pass
                    await asyncio.sleep(0.2)
                got = await real[name](*a, **k)
                seen["finished"].append(name)
                if late and len(seen["finished"]) == len(SLOW) - 1 and late not in seen["finished"]:
                    others_done.set()
                return got
            except asyncio.CancelledError:
                seen["cancelled"].append(name)
                raise
            finally:
                seen["in_flight"] -= 1

        return reading

    monkeypatch.setattr(prod, "_qc_render_listens", wrap("listens"))
    monkeypatch.setattr(qc, "measure_loudness", wrap("loudness"))
    monkeypatch.setattr(qc, "sample_caption_frames", wrap("frames"))
    monkeypatch.setattr(prod, "word_marks_for", wrap("marks"))
    monkeypatch.setattr(prod, "_qc_asides", wrap("asides"))
    said: list[str] = []
    step = prod._qc_step

    async def saying(upload_id, ws, round_no, doing, fixed=None):
        said.append(doing)
        return await step(upload_id, ws, round_no, doing, fixed)

    monkeypatch.setattr(prod, "_qc_step", saying)
    return seen, said


@needs_ffmpeg
async def test_her_slow_readings_run_at_once_and_each_lands_in_its_own_check(
    wired, tone_recogniser, tmp_path, monkeypatch
):
    seen, said = _meeting(monkeypatch, late="asides")
    _ws, _uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    assert seen["most"] == len(SLOW), f"all five were in flight at once (at most {seen['most']})"
    # Each answer is where it always went, and the edit is checked as before.
    found = row.qc
    assert row.status == "edited" and found["state"] == "passed"
    assert abs(found["numbers"]["lufs"] - (-14.0)) <= qc.LOUDNESS_TOLERANCE_LU
    assert found["checks"]["audibility"]["heard"] == 9
    assert found["checks"]["captions"]["playback_state"] == "pass"
    frames = found["checks"]["captions"]["frames"]
    assert frames["confirmed"] == frames["samples"] > 0
    assert list(found["checks"])[:5] == ["gaps", "loudness", "captions", "audibility", "asides"]
    assert [a["kind"] for a in wired["asked"]] == [qc.ASIDES_JOB]
    # The card: everything she does at once in one line, then the reading still going.
    together = next(line for line in said if line.endswith("all at once"))
    for part in ("listening to it again", "how loud", "caption frames", "heard whole", "on the subscription"):
        assert part in together
    assert said[said.index(together) + 1].startswith("reading the words still in it")


@needs_ffmpeg
async def test_one_reading_that_breaks_stops_the_others(wired, tone_recogniser, tmp_path, monkeypatch):
    ws, uid, _row = await edit(wired, tmp_path, spoken(CLEAN))
    seen, _said = _meeting(monkeypatch, late="asides", endless=True, broken="loudness")
    with pytest.raises(RuntimeError, match="loudness broke"):
        await asyncio.wait_for(prod._qc_measure(uid, ws, 0), 30)
    assert seen["most"] == len(SLOW)
    assert "asides" in seen["cancelled"], "the reading still running was stopped, not left behind"
    assert seen["in_flight"] == 0, "nothing of the check is still running once it has ended"


def test_the_card_line_names_each_reading_once():
    assert prod._all_at_once(["a"]) == "a"
    assert prod._all_at_once(["a", "b", "c"]) == "a, b and c, all at once"
