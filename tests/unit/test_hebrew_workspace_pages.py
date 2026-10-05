"""Hebrew screens for a Hebrew workspace's own login; the owner's pages unchanged.

A page served to a scoped editor key whose workspace language is "he" comes back
right to left with the Hebrew UI layer. Every page served to the owner (or to no
key at all) is byte for byte the file on disk, exactly as before. Synthetic keys.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.api import dashboard
from tce.api.private_access import ScopedEditorGuard
from tce.settings import settings

API = Path(dashboard.__file__).parent
OWNER_KEY = "owner-key-" + uuid.uuid4().hex
MATAN_KEY = "matan-key-" + uuid.uuid4().hex
ZIV_WS = "3e8c3f9c-0213-57cd-ab30-173d5700090f"
MATAN_WS = "40c0f179-7d5e-4397-b4de-b0b2f3e96fc2"
NODE = shutil.which("node")
PAGES = ("/record", "/today", "/topics", "/week", "/library", "/settings",
         "/topics/abc", "/scripts/abc", "/library/abc/talk", "/library/rules")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", ZIV_WS)
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{MATAN_WS}"))
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN_WS}:he")

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.add_middleware(ScopedEditorGuard)
    return TestClient(app)


def _file_for(path: str) -> str:
    name = "recording.html" if path == "/record" else "workspace.html"
    return (API / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize("headers", [{}, {"X-TCE-Editor-Key": OWNER_KEY}])
def test_owner_pages_are_byte_for_byte_the_files(client, path, headers):
    r = client.get(path, headers=headers)
    assert r.status_code == 200
    assert r.text == _file_for(path)
    assert "i18n-he" not in r.text and 'dir="rtl"' not in r.text


def test_owner_pages_unchanged_even_if_an_owner_workspace_were_hebrew(client, monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", f"{ZIV_WS}:he,{MATAN_WS}:he")
    r = client.get("/record", headers={"X-TCE-Editor-Key": OWNER_KEY})
    assert r.text == _file_for("/record")


@pytest.mark.parametrize("path", PAGES)
def test_hebrew_login_gets_rtl_hebrew_pages(client, path):
    r = client.get(path, headers={"X-TCE-Editor-Key": MATAN_KEY})
    assert r.status_code == 200
    html = r.text
    assert '<html lang="he" dir="rtl">' in html
    assert '<script src="i18n-he.js"></script>' in html
    assert 'href="i18n-he.css"' in html
    assert "Heebo" in html  # a face with Hebrew glyphs
    # The Hebrew layer loads before the page's own scripts run.
    assert html.index("i18n-he.js") < html.index("</head>")
    # Nothing else in the page changed (5-Oct: besides the scoped login's head, which
    # hides the microphone and the KM BOT link, test_matan_decisions_5oct.py).
    assert html.replace(dashboard.HE_HEAD, "</head>").replace(dashboard.SCOPED_HEAD, "</head>").replace(
        '<html lang="he" dir="rtl">', '<html lang="en">') == _file_for(path)


def test_a_scoped_english_workspace_keeps_english_pages(client, monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", "")
    r = client.get("/record", headers={"X-TCE-Editor-Key": MATAN_KEY})
    # English, left to right; only the scoped login's head (no mic, no KM BOT link).
    assert r.text == _file_for("/record").replace("</head>", dashboard.SCOPED_HEAD, 1)


def test_hebrew_assets_are_served(client):
    js = client.get("/i18n-he.js", headers={"X-TCE-Editor-Key": MATAN_KEY})
    css = client.get("/i18n-he.css", headers={"X-TCE-Editor-Key": MATAN_KEY})
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert ".reader-sentence" in css.text and "direction: rtl" in css.text


def test_root_sends_a_scoped_login_to_today_and_the_owner_to_the_dashboard(client):
    r = client.get("/", headers={"X-TCE-Editor-Key": MATAN_KEY}, follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/today"
    r = client.get("/", headers={"X-TCE-Editor-Key": OWNER_KEY}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


# --- The JS: the Hebrew layer and the teleprompter's sentences (Node) ----------------

needs_node = pytest.mark.skipif(not NODE, reason="node not installed")


def _node(script: str):
    out = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True,
                         timeout=30).stdout
    return json.loads(out)


@needs_node
def test_hebrew_layer_translates_ui_strings_and_leaves_content_alone():
    path = json.dumps(str(API / "i18n-he.js"))
    got = _node(
        f"const t = require({path}).translate;"
        "process.stdout.write(JSON.stringify(["
        "t('Record'), t('  Points '), t('Full script'), t('Point 3'), t('Pause'), t('Resume'),"
        "t('Finish'), t('Why (private): it is short'), t('Today'),"
        "t('שלום, זה התסריט שלי.'), t('Some English content line'), t('')]));"
    )
    assert got[:9] == ["הקלטה", "  נקודות ", "תסריט מלא", "נקודה 3", "השהיה", "המשך",
                       "סיום", "למה (רק לך): it is short", "היום"]
    assert got[9:] == [None, None, None]


def _reader_sentences():
    source = (API / "recording.js").read_text(encoding="utf-8")
    m = re.search(r"^function readerSentences\(.*?^\}\r?$", source, re.M | re.S)
    assert m, "readerSentences"
    return m.group(0)


@needs_node
def test_teleprompter_splits_hebrew_into_one_sentence_per_line():
    fn = _reader_sentences()
    got = _node(
        fn + "\nprocess.stdout.write(JSON.stringify(["
        "readerSentences('אתם יודעים מה הכי מפחיד אנשים? לא הקלפים. זה הרגע שהם מבינים!', 'he'),"
        "readerSentences('משפט אחד בלי נקודה', 'he'),"
        "readerSentences('One. Two? Three!', 'en'),"
        "readerSentences('', 'he')]));"
    )
    assert got[0] == ["אתם יודעים מה הכי מפחיד אנשים?", "לא הקלפים.", "זה הרגע שהם מבינים!"]
    assert got[1] == ["משפט אחד בלי נקודה"]
    # English (the owner) is one line per item, exactly as before.
    assert got[2] == ["One. Two? Three!"]
    assert got[3] == [""]


def test_owner_reader_path_is_unchanged_in_the_source():
    """The split only happens for a Hebrew page; English keeps the single text node."""
    source = (API / "recording.js").read_text(encoding="utf-8")
    assert 'const PAGE_LANG = document.documentElement.lang === "he" ? "he" : "en";' in source
    assert "readerSentences(text, PAGE_LANG)" in source
    assert "line.appendChild(document.createTextNode(text));" in source
