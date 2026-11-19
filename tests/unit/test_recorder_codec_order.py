"""19-Nov-2026: the recorders ask the phone for H.264 first.

A phone encodes H.264 in hardware. Asked for VP9 first, Chrome on the owner's Samsung encoded
VP9 in software at 1080x1920 and kept only 12.7 to 17.6 pictures a second, so his lips trailed
his voice in every video. Each recorder picks the first type its browser supports, so the order
of the list is the fix: every H.264 type before any VP8 or VP9 type, VP9 last."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
RECORDERS = ("recording.js", "recording-solo.js", "book.js")
_LIST = re.compile(
    r"const supportedMime = \[(?P<body>[^\]]*)\]\.find\(\(value\) => window\.MediaRecorder"
    r" && MediaRecorder\.isTypeSupported\(value\)\)"
)


def mime_order(text: str) -> list[str]:
    found = _LIST.search(text)
    assert found, "no supportedMime list in this recorder"
    return re.findall(r'"([^"]+)"', found.group("body"))


def h264_first_problems(order: list[str]) -> list[str]:
    """What is wrong with one recorder's order, in words; [] when it is right."""
    if not order:
        return ["the list is empty"]
    h264 = [i for i, m in enumerate(order) if "avc1" in m or "h264" in m]
    vpx = [i for i, m in enumerate(order) if "vp8" in m or "vp9" in m]
    problems = []
    if not h264:
        problems.append("no H.264 type")
    elif h264[0] != 0:
        problems.append(f"the first type is {order[0]}, not H.264")
    if h264 and vpx and max(h264) > min(vpx):
        problems.append("an H.264 type comes after a VP8/VP9 type")
    if "video/webm;codecs=vp9,opus" not in order:
        problems.append("VP9 is no longer offered at all (it stays, last)")
    elif order[-1] != "video/webm;codecs=vp9,opus":
        problems.append("VP9 is not last")
    return problems


@pytest.mark.parametrize("name", RECORDERS)
def test_recorder_asks_for_h264_first_and_vp9_last(name: str) -> None:
    order = mime_order((API / name).read_text(encoding="utf-8"))
    assert h264_first_problems(order) == [], f"{name}: {order}"


def test_the_three_recorders_ask_in_the_same_order() -> None:
    orders = {n: mime_order((API / n).read_text(encoding="utf-8")) for n in RECORDERS}
    assert len({tuple(o) for o in orders.values()}) == 1, orders


def test_the_check_fails_on_the_old_vp9_first_order() -> None:
    # The order every recorder had until 19-Nov: the check must refuse it, for the right reason.
    old = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
           "video/mp4;codecs=h264,aac", "video/mp4"]
    problems = h264_first_problems(old)
    assert "the first type is video/webm;codecs=vp9,opus, not H.264" in problems
    assert "an H.264 type comes after a VP8/VP9 type" in problems
    assert "VP9 is not last" in problems
