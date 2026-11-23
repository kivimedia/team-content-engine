"""The Book page answers his taps at once (23-Nov, wait-less item B9, part 1).

A layout word, a write ask or an approve redraws from its own answer: no second fetch of
the chapter. Once the chapter needs nothing more from him, one tap (Next to review) opens
the next chapter waiting on him; before, it took two: Back to the chapters, then the
list's review link. The stubbed server is test_book_page_wait_less.py's. Pictures of each
state go to TCE_SHOT_DIR when set.
"""

from __future__ import annotations

from tests.unit.test_book_page_wait_less import READY_16, Book, _open, _shot, _until, _view, sync_playwright


def test_a_layout_tap_redraws_from_its_answer_and_one_tap_opens_the_next_review():
    book = Book([_view(12), _view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book/12")
        page.locator("#layoutApprove").wait_for()
        _until(page, lambda: "LIST" in book.kinds())  # read once, behind the page
        assert page.locator("#planNextReview").is_hidden()  # this layout still waits on him
        page.click("#layoutApprove")
        page.locator("#writeButton").wait_for()
        assert page.inner_text("#bookStatus").startswith("The layout of Episode 12 is approved.")
        assert page.locator("#layoutApprovedLine").is_visible()
        assert page.locator("#planNextReview").is_hidden()  # Write this chapter is still his to press
        page.click("#writeButton")
        page.locator("#writeAskedLine").wait_for()
        assert page.inner_text("#bookStatus").startswith("Asked the editor to write Episode 12")
        # The two taps answered with the chapter: it was fetched once, when it opened.
        assert book.kinds().count("GET") == 1 and book.calls[:1] == [("GET", 12)]
        assert [c for c in book.calls if c[0] in ("LAYOUT", "WRITE")] == [("LAYOUT", 12), ("WRITE", 12)]
        page.locator("#planNextReview").wait_for()
        assert page.inner_text("#planNextReview") == "Next to review\nEpisode 14: Episode title 14"
        _shot(page, "layout-asked", "layoutReopen", "planNextReview")
        page.click("#planNextReview")
        page.wait_for_url("**/book/14")
        page.wait_for_function("document.getElementById('chapterTitle').textContent === 'Episode 14: Episode title 14'")
        assert book.calls[-1] == ("GET", 14)
        browser.close()


def test_approve_offers_the_next_review_in_the_reading_dock():
    book = Book([_view(14), _view(16, **READY_16)])
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book/16")
        page.locator("#approveButton").wait_for()
        _until(page, lambda: "LIST" in book.kinds())
        assert page.locator("#nextReview").is_hidden()  # he is reviewing this one
        page.click("#approveButton")
        page.locator("#unapproveButton").wait_for()
        assert page.inner_text("#bookStatus") == "Episode 16 is approved."
        page.locator("#nextReview").wait_for()
        assert page.inner_text("#nextReview") == "Next to review\nEpisode 14: Episode title 14"
        assert book.kinds().count("GET") == 1
        _shot(page, "approved-dock", "unapproveButton", "nextReview")
        # Undo puts it back in review: nothing to jump to from here.
        page.click("#unapproveButton")
        page.locator("#approveButton").wait_for()
        assert page.locator("#nextReview").is_hidden()
        page.click("#approveButton")
        page.locator("#nextReview").wait_for()
        page.click("#nextReview")
        page.wait_for_url("**/book/14")
        page.locator("#layoutApprove").wait_for()
        browser.close()
