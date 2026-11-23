"""The lines the wait-less pages added (23-Nov, item B9) have their Hebrew rows.

Record without a script is served through the Hebrew layer to a Hebrew workspace once a
client gets it; the Book is the owner's and is not, but its lines have their rows too.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
NODE = shutil.which("node")

LINES = [
    "Putting it together",
    "Your recording is being put together into its video now. You can leave this page.",
    "Sent, but it could not be finished yet (the server could not put it together just now). Trying again in a few seconds.",
    "Sending paused (the server could not put it together just now). Trying again in a few seconds; nothing is lost.",
    "Next to review",
    '"Book session on Episode 16, 23 Nov" is being put together into its video now. You can leave this page.',
]


def test_the_lines_are_the_ones_the_pages_write():
    solo = (API / "recording-solo.js").read_text(encoding="utf-8")
    book = (API / "book.js").read_text(encoding="utf-8")
    html = (API / "book.html").read_text(encoding="utf-8")
    not_now = 'const NOT_NOW = "the server could not put it together just now"'
    assert 'top("Putting it together")' in solo and LINES[1] in solo
    assert not_now in solo and not_now in book
    assert "Sent, but it could not be finished yet (${failed.message}). Trying again in a few seconds." in solo
    assert "Sending paused (${error.message}). Trying again in a few seconds; nothing is lost." in book
    assert "is being put together into its video now. You can leave this page.`" in book
    assert ">Next to review<small>" in html


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_each_line_has_its_hebrew_row():
    path = json.dumps(str(API / "i18n-he.js"))
    got = json.loads(subprocess.run(
        [NODE, "-e", f"const t = require({path}).translate; process.stdout.write(JSON.stringify("
                     f"{json.dumps(LINES)}.map((x) => t(x))));"],
        check=True, capture_output=True, text=True, timeout=30).stdout)
    for line, hebrew in zip(LINES, got, strict=True):
        assert hebrew and hebrew != line and any("֐" <= ch <= "׿" for ch in hebrew), line
    assert '"Book session on Episode 16, 23 Nov"' in got[-1]


# 23-Nov-2026 (wait-less F11): what the Book's chat says about a typed comment with no call.
TYPED_LINES = [
    "The editor is busy with another job. Your comment goes to it the moment that job ends, and the answer shows here.",
    "The line to the editor dropped while it was answering. Its answer shows here when it is ready.",
    "The editor finished without a written reply.",
    "The editor's answer has not come back here yet. It will be in the editor's chat in KM BOT.",
    "The editor could not answer that.",
    "Comment not sent: no connection to KM BOT. Your draft is saved.",
]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_the_typed_comment_lines_are_the_books_and_have_their_hebrew_rows():
    book = (API / "book.js").read_text(encoding="utf-8")
    for line in TYPED_LINES[:5]:
        assert line in book, line
    assert "Comment not sent: no connection to KM BOT. Your draft is saved." in book
    path = json.dumps(str(API / "i18n-he.js"))
    got = json.loads(subprocess.run(
        [NODE, "-e", f"const t = require({path}).translate; process.stdout.write(JSON.stringify("
                     f"{json.dumps(TYPED_LINES)}.map((x) => t(x))));"],
        check=True, capture_output=True, text=True, timeout=30).stdout)
    for line, hebrew in zip(TYPED_LINES, got, strict=True):
        assert hebrew and hebrew != line and any("֐" <= ch <= "׿" for ch in hebrew), line
    assert "KM BOT" in got[-1]
