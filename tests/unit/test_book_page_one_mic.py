"""The Book opens on one microphone, and the editor speaks first (25-Nov, T-25211).

Ziv, 25-Nov: "When I go into the book part they put a button for chatting, it is super weird,
it should have been just a microphone on the top ... I go in, I start a conversation and I
understand what's going on with the context of what was written already."

The microphone at the top dials the editor with his mic live, without popping the keyboard,
and its first line carries where he is, the short version of the book the editor keeps
(GET /book/catch-up), the last chapter and the next as the editor summed them up, and the ask
to speak first and then take the next chapter's layout. While they talk the chapter redraws
when the editor records his layout approval. Stubbed server: test_book_page_typed_chat.py's.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from tce.api.routers.book import catch_up
from tests.unit.test_book_page_typed_chat import FAKE_VOICE, Editor, _open
from tests.unit.test_book_page_wait_less import READY_16, _shot, _until, _view, sync_playwright

CATCH_UP = {
    "updated": "2026-11-23T21:21:14Z",
    "overview": "The other half has five parts and 53 chapters: you wrote 1 to 11.",
    "chapters": {"13": "The bakery: how the bakery came back. More: the oven story.",
                 "14": "The fair: three stalls in a row. More: the rain day."},
}


VOICE = FAKE_VOICE.replace("start(opts) {", "start(opts) { window.__voiceOn = opts.on;")


class Mic(Editor):
    def __call__(self, route):
        if urlsplit(route.request.url).path == "/voice-client.js":
            self.calls.append(("VOICE", None))
            return route.fulfill(body=VOICE, content_type="application/javascript")
        if urlsplit(route.request.url).path == "/api/v1/book/catch-up":
            self.calls.append(("CATCHUP", None))
            return route.fulfill(json=CATCH_UP)
        return super().__call__(route)


def test_one_microphone_on_top_and_typing_only_inside_the_call_or_the_fold():
    html = (Path(__file__).resolve().parents[2] / "src" / "tce" / "api" / "book.html").read_text(encoding="utf-8")
    assert html.count('id="bookMic"') == 1
    panel = html[html.index('id="editorPanel"'):html.index("</section>", html.index('id="editorPanel"'))]
    assert 'id="editorType"' in panel and "Type instead</button>" in panel
    assert "Chat with the editor about" not in html


def test_the_microphone_dials_the_editor_live_and_its_first_line_is_the_catch_up():
    editor = Mic([_view(13, **READY_16), _view(14)])
    editor.views[13]["status"] = "approved"
    editor.views[13]["phase"] = "approved"
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        start = page.evaluate("() => window.__voice.starts[0]")
        first = page.evaluate("() => window.__voice.sent[0]")
        focused = page.evaluate("() => document.activeElement && document.activeElement.id")
        pressed = page.get_attribute("#bookMic", "aria-pressed")
        panel_open = page.is_visible("#editorPanel")
        browser.close()
    assert start == {"agent": "book-editor", "greet": False, "startMuted": False}
    assert first.startswith("[Where I am in the Book]")
    assert "Speak first" in first
    assert "53 chapters" in first
    assert 'Episode 13 "Episode title 13"' in first and "the bakery came back" in first
    assert 'Episode 14 "Episode title 14" is next' in first and "three stalls" in first
    assert "walk him through the layout of Episode 14" in first
    assert focused != "editorText"
    assert pressed == "true" and panel_open
    assert editor.count("CATCHUP") == 1


def test_on_a_call_the_microphone_is_mute_and_unmute_with_no_second_call():
    editor = Mic([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        page.locator("#bookMic").click()
        _until(page, lambda: page.get_attribute("#bookMic", "aria-pressed") == "false")
        starts = page.evaluate("() => window.__voice.starts.length")
        browser.close()
    assert starts == 1


def test_the_layout_redraws_when_the_editor_records_his_approval_on_the_call():
    editor = Mic([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor, path="/book/14", wait=False)
        page.locator("#layoutApprove").wait_for()
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        editor.views[14].update(layout_status="approved", phase="approved_unwritten",
                                phase_words="Layout approved, not written", layout_approved_at="2026-11-25T09:00:00")
        page.evaluate("() => window.__voiceOn('turn_end', { text: 'Recorded: the layout of 14 is approved.' })")
        _until(page, lambda: page.is_visible("#writeButton"))
        approve_shown = page.is_visible("#layoutApprove")
        browser.close()
    assert not approve_shown


# --- 27-Nov (release 2): his first use, 26-Nov 21:34 UTC, and the rest of the plan -------------

FOLDED = ("filmButton", "listTalk", "agentCatchup", "agentList", "chapterDirectory", "writtenFold", "reviewDetails")


def _seen_above_the_fold(page):
    # checkVisibility: a closed <details> keeps its content laid out (content-visibility: hidden),
    # so a bounding box alone counts what is folded away.
    return page.evaluate("""() => [...document.querySelectorAll("button, a, summary")].filter((e) => {
        const r = e.getBoundingClientRect();
        return e.checkVisibility() && r.width && r.height && r.bottom > 0 && r.top < innerHeight; })
        .map((e) => e.id || e.tagName)""")


def _said(page, n):
    _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") >= n)
    return page.evaluate(f"() => window.__voice.sent[{n - 1}]")


def test_the_chapters_page_is_the_next_chapter_the_microphone_and_one_fold():
    html = (Path(__file__).resolve().parents[2] / "src" / "tce" / "api" / "book.html").read_text(encoding="utf-8")
    fold = html[html.index('id="everythingElse"'):html.index('id="chapterView"')]
    for element in FOLDED:
        assert f'id="{element}"' in fold, element
    assert 'id="talkButton"' not in html  # no chat button in the player
    top_bar = html[html.index('class="topbar"'):html.index("</header>")]
    assert 'id="bookMic"' in top_bar and 'id="listTalk"' not in top_bar and 'id="filmButton"' not in top_bar
    editor = Mic([_view(12, **READY_16), _view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#reviewNext").wait_for()
        seen = _seen_above_the_fold(page)
        hint = page.inner_text("#micHint")
        width = page.evaluate("() => document.documentElement.scrollWidth")
        page.click("#everythingSummary")
        page.locator("#chapterDirectory").wait_for()
        opened = page.is_visible("#listTalk") and page.is_visible("#chapterDirectory")
        browser.close()
    assert seen == ["bookBack", "bookMic", "reviewNext", "everythingSummary"], seen
    assert "microphone" in hint and width <= 390
    assert opened


def test_film_sits_in_the_top_bar_on_a_chapter_and_in_the_fold_on_the_chapters_page():
    editor = Mic([_view(12, **READY_16), _view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#reviewNext").wait_for()
        where_list = page.evaluate("() => document.getElementById('filmButton').closest('#everythingElse, .topbar').id || 'topbar'")
        page.click("#reviewNext")
        page.locator("#chapterView").wait_for()
        where_chapter = page.evaluate("() => document.getElementById('filmButton').closest('#everythingElse, .topbar').className")
        page.click("#bookBack")
        page.locator("#listView").wait_for()
        where_back = page.evaluate("() => document.getElementById('filmButton').closest('#everythingElse, .topbar').id")
        count = page.evaluate("() => document.querySelectorAll('#filmButton').length")
        browser.close()
    assert where_list == "everythingElse" and "topbar" in where_chapter and where_back == "everythingElse"
    assert count == 1


def test_the_microphone_opens_the_chat_with_a_keyboard_under_the_editors_words():
    editor = Mic([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        first = _said(page, 1)
        form_first = page.is_visible("#editorForm")
        keyboard = page.is_visible("#editorType")
        page.evaluate("() => window.__voiceOn('turn_end', { text: 'So far the book says the first half is the hard part.' })")
        _shot(page, "mic-keyboard", "bookMic", "editorState", "editorLog", "editorType", "editorEnd")
        page.click("#editorType")
        page.locator("#editorText").wait_for()
        focused = page.evaluate("() => document.activeElement && document.activeElement.id")
        page.fill("#editorText", "Start with the bakery.")
        page.click("#editorForm button[type=submit]")
        typed = _said(page, 2)
        starts = page.evaluate("() => window.__voice.starts.length")
        browser.close()
    assert not form_first and keyboard
    assert focused == "editorText"
    assert typed == "Start with the bakery." and starts == 1  # the same conversation, no second call
    assert "never open with yes, okay or a greeting" in first


def test_a_press_soon_after_the_call_ended_carries_on_where_they_stopped():
    """His 26-Nov calls: the first ended mid-interview at 21:40:52 and he pressed again 6 s later;
    the second call opened on the whole catch-up and "go over its text?" instead of carrying on."""
    editor = Mic([_view(12, **READY_16), _view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        _said(page, 1)
        page.evaluate("() => window.__voiceOn('said', { text: 'At some point the business started to lose members.' })")
        page.evaluate("() => window.__voiceOn('turn_end', { text: 'Was that churn from market changes or the offer no longer fitting?' })")
        page.click("#editorEnd")
        _until(page, lambda: page.get_attribute("#bookMic", "aria-pressed") == "false")
        page.locator("#bookMic").click()
        again = _said(page, 2)
        state = page.inner_text("#editorState")
        starts = page.evaluate("() => window.__voice.starts.length")
        browser.close()
    assert starts == 2
    assert again.startswith("[Where I am in the Book]")
    assert "pressed the microphone again, moments after your last call" in again
    assert "Do not catch him up on the book again" in again
    assert "what the book covers so far" not in again and "53 chapters" not in again
    assert "- Ziv: At some point the business started to lose members." in again
    assert "- Editor: Was that churn from market changes or the offer no longer fitting?" in again
    assert "never open with yes" in again
    assert "up where you stopped" in state


def _open_kept(pw, editor, ended_ms_ago):
    """The page as the phone reloads it: this tab's kept chat (lines and when the call ended)
    is in its session store before the page's own script runs."""
    kept = ("try { sessionStorage.setItem('tce-book-chat', JSON.stringify({ at: Date.now(), open: false, shown: false,"
            f" call: false, mic: false, ended: Date.now() - {ended_ms_ago},"
            " lines: [{ who: 'me', text: 'The school started with a podcast.' }, { who: 'editor', text: 'What came next?' }] }));"
            " } catch (e) {}")
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    page.add_init_script(kept)
    page.route("https://book.test/**", editor)
    page.goto("https://book.test/book")
    page.locator("#reviewNext").wait_for()
    _until(page, lambda: "What came next?" in (page.text_content("#editorLog") or ""))  # restored
    return browser, page


def test_after_a_reload_the_carry_on_holds_for_half_an_hour_then_the_catch_up_comes_back():
    sent = {}
    for name, ago in (("soon", 5 * 60 * 1000), ("late", 31 * 60 * 1000)):
        editor = Mic([_view(12, **READY_16), _view(14)])
        with sync_playwright() as pw:
            browser, page = _open_kept(pw, editor, ago)
            page.locator("#bookMic").click()
            sent[name] = _said(page, 1)
            browser.close()
    assert "5 minutes after your last call" in sent["soon"] and "- Ziv: The school started with a podcast." in sent["soon"]
    assert "what the book covers so far" in sent["late"] and "pressed the microphone again" not in sent["late"]


def test_catch_up_reads_the_editors_short_version(tmp_path):
    f = tmp_path / "book-summary.md"
    f.write_text(
        "<!-- Kept current by book-editor. Updated 2026-11-23T21:21:14Z. -->\n\n"
        "The other half: the short version\n\nFive parts, 53 chapters.\n\n"
        "Part one of five: Understanding the framework (chapters 1 to 15)\n"
        "Chapter 1, The first million was hard: The line every millionaire repeats.\n"
        "  More: You protected yourself with skepticism.\n"
        "Part two of five: Questions\n"
        "Chapter 2, My second million was easy: A tour.\n",
        encoding="utf-8",
    )
    got = catch_up(f)
    assert got["updated"] == "2026-11-23T21:21:14Z"
    assert "53 chapters" in got["overview"] and "Part two" not in got["overview"]
    assert got["chapters"]["1"].startswith("The first million was hard:") and "More: You protected" in got["chapters"]["1"]
    assert set(got["chapters"]) == {"1", "2"}
    assert catch_up(tmp_path / "missing.md") == {"updated": "", "overview": "", "chapters": {}}
