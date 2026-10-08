"""Every branch of the page's one click listener is reachable by a tap.

The listener only runs for an element matching CLICK_SELECTOR, which is built
from CLICK_ACTIONS. A branch whose data-attribute is missing from that list is a
button that silently does nothing: no error, no request, no log line. That
drift happened twice - rewrite, review and notify on 1-Oct, then "Ask Jennifer
to check it again", "It is fine, let it through" and "Delete this rule" on
8-Oct, which Ziv met in the Library.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")


def _kebab(camel: str) -> str:
    return re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), camel)


def _actions() -> set[str]:
    block = re.search(r"var CLICK_ACTIONS = \[(.*?)\];", JS, re.S)
    assert block, "CLICK_ACTIONS list not found in workspace.js"
    return set(re.findall(r'"([a-z-]+)"', block.group(1)))


def _listener_branches() -> set[str]:
    start = JS.index('document.addEventListener("click", function (event) {\n    var target = event.target.closest(CLICK_SELECTOR);')
    end = JS.index("\n  });", start)
    body = JS[start:end]
    return {_kebab(name) for name in re.findall(r"if \(d\.(\w+) !== undefined\)", body)}


def test_every_click_branch_has_its_action_in_the_list():
    missing = sorted(_listener_branches() - _actions())
    assert not missing, f"these buttons do nothing when tapped, add them to CLICK_ACTIONS: {missing}"


def test_every_listed_action_has_a_branch():
    unused = sorted(_actions() - _listener_branches())
    assert not unused, f"CLICK_ACTIONS names an action the listener never handles: {unused}"


def test_the_three_library_buttons_are_tappable():
    for attr in ("check-again", "release-hold", "rule-delete"):
        assert f"data-{attr}=" in JS, f"the page no longer renders data-{attr}"
        assert attr in _actions()
