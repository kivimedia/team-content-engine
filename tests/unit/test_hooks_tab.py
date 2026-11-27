"""The Hooks tab in TCE's bottom menu (27-Nov-2026, T-25908).

Ziv: "It need to be accessible by browsing!" The hook studio was reachable only from
a button inside This week. It is now a tab in the menu on every page that has one,
the owner's only like Book, and lit while he is on it.
"""

from pathlib import Path

from tce.api import dashboard, private_access

ROOT = Path(dashboard.__file__).parent


def test_both_menus_carry_a_hooks_tab_before_book():
    for name in ("workspace.html", "recording.html"):
        html = (ROOT / name).read_text(encoding="utf-8")
        tab = '<a href="/hooks"   data-route="hooks" class="hooks-entry">'
        assert tab in html, name
        assert html.index(tab) < html.index('data-route="book" class="book-entry"'), name
        assert ">Hooks</a>" in html, name


def test_the_hooks_tab_is_hidden_for_a_client_and_its_page_is_fenced():
    assert ".hooks-entry" in dashboard.SCOPED_HEAD
    assert "/hooks" not in private_access.SCOPED_PAGE_PATHS
    assert not private_access.scoped_path_allowed("/hooks")


def test_the_hooks_page_lights_its_own_tab():
    js = (ROOT / "workspace.js").read_text(encoding="utf-8")
    assert 'hooks: "hooks" }[route.name]' in js
    assert 'hooks: "week" }' not in js


def test_no_dashes_in_the_changed_pages():
    for name in ("workspace.html", "recording.html"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, name
