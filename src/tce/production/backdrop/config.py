"""The app's side of the new-backgrounds step: who is offered the switch, whether a video has
it on, and what its render is told. (The step itself never imports this file.)"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from tce.settings import settings

from . import looks, omni, trial

# In a video's saved choices (edit_plan["overrides"]), next to its style.
KEY = "backdrop"
ON = "on"
CLI = Path(__file__).with_name("cli.py")
LEDGER = "spend.jsonl"

_sets: dict[str, tuple[int, bool]] = {}


def looks_dir(workspace_id: uuid.UUID | str | None) -> Path | None:
    root = (settings.production_backdrop_dir or "").strip()
    if not root or workspace_id is None:
        return None
    return Path(root) / str(workspace_id).lower()


def offered(workspace_id: uuid.UUID | str | None) -> bool:
    """The switch shows only where it can work: the server has a key for the paid model and
    this workspace has its own set of looks. Read on every Library card, so the answer is
    remembered until the set's file changes."""
    if not (settings.production_backdrop_key or "").strip():
        return False
    folder = looks_dir(workspace_id)
    if folder is None:
        return False
    try:
        stamp = (folder / looks.FILE).stat().st_mtime_ns
    except OSError:
        return False
    known = _sets.get(str(folder))
    if known is None or known[0] != stamp:
        known = (stamp, looks.load(folder) is not None)
        _sets[str(folder)] = known
    return known[1]


def wanted(plan: dict[str, Any] | None) -> bool:
    return ((plan or {}).get("overrides") or {}).get(KEY) == ON


def cache_dir(src: Path) -> Path:
    """Redrawn scenes stay next to the recording, so making the video again costs nothing for
    the scenes that did not change."""
    return src.with_name(f".{src.stem}-backdrop")


def for_render(
    workspace_id: uuid.UUID | str | None,
    upload_id: uuid.UUID | str,
    src: Path,
    plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """What the step is told for this render, or None when this video keeps its backgrounds."""
    if not wanted(plan) or not offered(workspace_id):
        return None
    test = trial.money(looks_dir(workspace_id), workspace_id, upload_id)
    return {
        # 19-Nov: a video in the live test also stops at the test's total for all its videos.
        **({"trial": test} if test else {}),
        "looks_dir": str(looks_dir(workspace_id)),
        "cache_dir": str(cache_dir(Path(src))),
        "model": settings.production_backdrop_model,
        "judge_model": settings.production_backdrop_judge_model,
        "resolution": settings.production_backdrop_resolution,
        "max_usd": float(settings.production_backdrop_max_usd),
        "day_usd": float(settings.production_backdrop_day_usd),
        # A different first place for each video, the same one every time it is made again.
        "start_look": int(uuid.UUID(str(upload_id)).hex[:6], 16),
        "ledger": str(Path(settings.production_backdrop_dir) / LEDGER),
        "label": f"{workspace_id}:{upload_id}",
    }


def card(
    workspace_id: uuid.UUID | str | None,
    plan: dict[str, Any] | None,
    upload_id: uuid.UUID | str | None = None,
) -> dict[str, Any] | None:
    """For the Library card's switch: None where it is not offered."""
    if not offered(workspace_id):
        return None
    kept_s = sum(float(b) - float(a) for a, b in (plan or {}).get("keep") or [])
    limit = float(settings.production_backdrop_max_usd)
    about = min(limit, omni.estimate_usd(kept_s / 2, settings.production_backdrop_resolution))
    out = {"on": wanted(plan), "about_usd": round(about * 2) / 2, "max_usd": limit}
    test = trial.card(looks_dir(workspace_id), upload_id) if upload_id is not None else None
    if test:
        out["trial"] = test  # 19-Nov: this video's place in the live test
    return out


def join_trial(
    workspace_id: uuid.UUID | str | None, upload_id: uuid.UUID | str, uploaded_at: Any
) -> dict[str, Any] | None:
    """19-Nov: a video turned to Creatorz joins the live test, where there is one and the switch
    can work here (trial.py). None for every other video."""
    if not offered(workspace_id):
        return None
    return trial.join(looks_dir(workspace_id), upload_id, uploaded_at)


def summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the render's sidecar keeps of the step's report."""
    if not report:
        return None
    return {
        "asked": int(report.get("asked") or 0),
        "changed": int(report.get("changed") or 0),
        "cost_usd": float(report.get("cost_usd") or 0.0),
        "note": str(report.get("note") or ""),
        "scenes": [
            {
                k: e.get(k)
                for k in ("start_s", "end_s", "result", "look", "why", "cached")
                if e.get(k) is not None
            }
            for e in report.get("scenes") or []
        ],
    }


def said(report: dict[str, Any] | None) -> str:
    """One sentence for the card, or "" when the step did not run."""
    if not report:
        return ""
    asked, changed = int(report.get("asked") or 0), int(report.get("changed") or 0)
    if not asked:
        return f". New backgrounds were not made: {report.get('note') or 'no scene to change'}"
    cost = float(report.get("cost_usd") or 0.0)
    paid = f"${cost:.2f}" if cost > 0 else "nothing new to pay"
    rest = (
        "" if changed == asked else f", {asked - changed} kept the real one after failing the check"
    )
    return f". New backgrounds on {changed} of {asked} scenes{rest} ({paid})"
