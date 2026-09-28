"""The "Back to KM BOT" link on every TCE page lands on the KM BOT console, not its sales page.

Ziv, 28-Sep-2026, on his phone: KM BOT "doesn't show the footer menu". The phone
app had tapped TCE's "<- KM BOT" link, which pointed at the host root. Since
04-Sep that root is the public sales page and the console lives at /app, so the
link dropped him on a marketing page with no tab bar and no way back but the
page's own Log in link.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
PAGES = sorted(p.name for p in API.glob("*.html") if "Back to KM BOT" in p.read_text(encoding="utf-8"))
LINK = re.compile(r'<a\b[^>]*aria-label="Back to KM BOT"[^>]*>', re.I)


def test_the_pages_that_carry_the_link_are_found():
    assert {"workspace.html", "recording.html"} <= set(PAGES)


@pytest.mark.parametrize("page", PAGES)
def test_back_to_kmbot_opens_the_console(page):
    html = (API / page).read_text(encoding="utf-8")
    links = LINK.findall(html)
    assert links, page
    for tag in links:
        href = re.search(r'href="([^"]*)"', tag).group(1)
        assert href == "https://bot.kivimedia.co/app", f"{page}: {href}"
