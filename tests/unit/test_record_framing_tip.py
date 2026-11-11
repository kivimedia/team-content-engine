"""A framing tip before he records (Ziv, 11-Nov: "tip").

The Creatorz look could not fix how a video was filmed: on a phone held close the face fills
the frame, so the zoom has nowhere to go and text has no room. One line before recording says
how to hold the phone. It shows before recording and gets out of the way while he records."""

from __future__ import annotations

import re
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
TIP = (
    "Framing tip: hold the phone at arm's length on the wide lens, with a little sky or wall above "
    "your head. It leaves room for text and keeps your head in the frame."
)


def read(name: str) -> str:
    return (API / name).read_text(encoding="utf-8")


def test_both_record_pages_show_the_tip_before_recording():
    solo = read("recording-solo.html")
    scripted = read("recording.html")
    assert TIP in solo and 'id="soloTip"' in solo
    assert TIP in scripted and 'id="cameraTip"' in scripted
    # on the scripted page it sits in the camera's empty state, which is gone once the camera runs
    empty = re.search(r'<div id="cameraEmpty".*?</div>', scripted, re.S).group(0)
    assert TIP in empty


def test_the_solo_tip_hides_while_he_records_and_comes_back_after():
    js = read("recording-solo.js")
    assert js.count('$("soloTip").hidden = true') == js.count('$("soloHelp").hidden = true') >= 1
    assert js.count('$("soloTip").hidden = false') == js.count('$("soloHelp").hidden = false') >= 1


def test_a_hebrew_workspace_reads_the_tip_in_hebrew():
    he = read("i18n-he.js")
    line = next((ln for ln in he.splitlines() if TIP in ln), None)
    assert line is not None
    assert re.search(r"[֐-׿]", line.split(TIP, 1)[1])


def test_the_tip_has_no_dashes_and_reads_easily():
    assert "—" not in TIP and "–" not in TIP and "--" not in TIP
    assert len(TIP.split()) <= 35
