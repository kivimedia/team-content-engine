"""The corporate-topic generator is gone, and nothing may quietly replace it.

Background, so a future reader knows what these assertions are defending.

Until 21-Sep-2026 TCE had two ways to produce content topics. One was the
evidence-first path: Fathom calls and git commits become EvidenceMoments, the
selector puts every candidate through four audience gates, and a candidate that
fails any of them is stored as a rejection. The other was `trend_scout`, a
registered agent wired into four orchestrator workflows, which queried hardcoded
venture-capital and enterprise-AI feeds, ranked what it found by Reddit comments
per hour, and was told by its own prompt to return "minimum 15, aim for 20-25"
trends per run. Nothing in that path asked whether a coach or an event-business
owner would care. It was dormant only because a settings flag defaulted to
false.

That second path is the failure the evidence pipeline was built to replace, so
these tests assert it cannot return: not the agent, not the route, not the feeds,
and not a new sibling that writes candidates without passing the gates.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "tce"

# Sources whose defining characteristic was that they are popular, not that they
# are relevant to a small owner-led service business. These are the literal
# hosts trend_scout queried.
RETIRED_FEED_HOSTS = (
    "techcrunch.com",
    "venturebeat.com",
    "theverge.com",
    "news.ycombinator.com",
    "reddit.com/r/",
    "semafor.com",
    "platformer.news",
)


def _python_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_trend_scout_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("tce.agents.trend_scout")


def test_trend_scout_is_not_registered():
    """Importing the agent package must not bring a trend scout back."""
    import tce.agents  # noqa: F401
    from tce.agents.registry import agent_registry

    names = set(agent_registry())
    assert "trend_scout" not in names
    # A rename is the obvious way this comes back.
    suspicious = {n for n in names if "trend" in n or "scout" in n}
    assert suspicious <= {"repo_scout"}, (
        f"Unexpected trend/scout agent registered: {sorted(suspicious - {'repo_scout'})}. "
        "A topic source must go through the evidence pipeline and its four gates."
    )


def test_trends_router_is_not_mounted():
    """POST /trends/scan ran the scout ad hoc, outside every gate."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("tce.api.routers.trends")

    from tce.api.app import create_app

    paths = {getattr(r, "path", "") for r in create_app().routes}
    assert not [p for p in paths if "/trends" in p], (
        f"A /trends route is mounted again: {sorted(p for p in paths if '/trends' in p)}"
    )


def test_no_workflow_step_references_a_trend_scout():
    from tce.orchestrator.workflows import WORKFLOWS

    for name, steps in WORKFLOWS.items():
        agents = [s.agent_name for s in steps]
        assert "trend_scout" not in agents, f"workflow {name} still starts at trend_scout"


def _blocklist_line_range() -> tuple[str, int, int]:
    """Where the news lane declares the hosts it refuses.

    A blocklist has to name what it blocks, so that one assignment is the single
    place these hostnames may legally appear. Locating it by AST rather than by
    filename means renaming or moving the constant does not quietly widen the
    exemption: if `BLOCKED_HOSTS` stops existing there, every occurrence in the
    tree becomes an offence again.
    """
    path = SRC / "news" / "feeds.py"
    if not path.exists():
        return ("", -1, -1)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "BLOCKED_HOSTS" for t in node.targets
        ):
            return ("news/feeds.py", node.lineno, node.end_lineno or node.lineno)
    return ("", -1, -1)


def test_popularity_feeds_are_not_queried_anywhere():
    """The feeds themselves, not just the agent that used them.

    Deleting trend_scout while leaving its source list somewhere reachable is
    how this comes back as a "small helper". Comments may name these hosts,
    because the retirement notes do. String literals may not, with exactly one
    exemption: the news lane's own BLOCKED_HOSTS, which exists to refuse them.
    """
    exempt_file, start, end = _blocklist_line_range()
    offenders: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                low = node.value.lower()
                for host in RETIRED_FEED_HOSTS:
                    if host not in low:
                        continue
                    if rel == exempt_file and start <= node.lineno <= end:
                        continue  # the blocklist naming what it blocks
                    offenders.append(f"{rel}:{node.lineno} -> {host}")
    assert not offenders, (
        "Retired popularity feeds are referenced in code again:\n  " + "\n  ".join(offenders)
    )


def test_the_blocklist_exemption_is_narrow():
    """The exemption must be a real declaration, not a hole anyone can widen."""
    exempt_file, start, end = _blocklist_line_range()
    assert exempt_file == "news/feeds.py", (
        "BLOCKED_HOSTS is not where the guard expects it; the exemption above is "
        "no longer anchored to a real declaration"
    )
    assert 0 < end - start < 30, "the exempt block grew unexpectedly large"

    from tce.news.feeds import BLOCKED_HOSTS, is_blocked_host

    # Naming them is only acceptable because naming them is how they are refused.
    for host in ("techcrunch.com", "venturebeat.com"):
        assert host in BLOCKED_HOSTS
        assert is_blocked_host(f"https://{host}/feed")


def test_every_topic_candidate_write_goes_through_the_selector():
    """The structural guarantee: one writer, and it is the gated one.

    `TopicCandidate(...)` is constructed in exactly two places:

    - `editorial/selector.py`, which runs `enforce_candidates()` before it saves
      anything, and
    - `editorial/feedback.py`, which inserts the calibration items the editor
      accepted by hand in September 2026. That one is a human decision being
      recorded, not a generator, and the next test pins it to that role.

    Any third module constructing one is a second ungated path to the recorder,
    whatever it is called.
    """
    allowed = {"editorial/selector.py", "editorial/feedback.py"}
    offenders: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        rel = path.relative_to(SRC).as_posix()
        if rel in allowed:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "TopicCandidate":
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "TopicCandidate is constructed outside the gated selector at:\n  "
        + "\n  ".join(offenders)
        + "\nEvery candidate must pass enforce_candidates() first."
    )


def test_the_calibration_writer_can_only_write_calibration_rows():
    """The one allowed non-selector writer stays what it is.

    `seed_calibration_candidates` is allowed to insert candidates because a
    person accepted each one. It must pin `origin=ORIGIN_CALIBRATION` on the
    row itself, so it can never be widened into a general-purpose insert that
    quietly produces selector-looking topics.
    """
    path = SRC / "editorial" / "feedback.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        == "TopicCandidate"
    ]
    assert calls, "the calibration writer disappeared; drop it from the allowlist above"

    for call in calls:
        origin = next((kw for kw in call.keywords if kw.arg == "origin"), None)
        assert origin is not None, f"feedback.py:{call.lineno} writes a candidate with no origin"
        name = getattr(origin.value, "id", None) or getattr(origin.value, "attr", None)
        assert name == "ORIGIN_CALIBRATION", (
            f"feedback.py:{call.lineno} writes origin={name}. "
            "The calibration writer may only produce calibration rows."
        )


def test_selector_still_enforces_the_four_settled_gates():
    """The gates themselves, so the guard above is guarding something real."""
    from tce.models.editorial import REJECTION_GATES

    assert set(REJECTION_GATES) == {
        "small_service_business",
        "coach_or_event_owner_relevance",
        "concrete_supported_substance",
        "connects_to_ziv_work",
    }
