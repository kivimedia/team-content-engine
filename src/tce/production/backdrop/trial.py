"""The live test of new backgrounds (19-Nov-2026): of the owner's next few Creatorz videos, some
get new places and some keep the real ones, so their views can be put side by side.

A file next to the workspace's looks arms it, and nothing else does:

    <backdrop dir>/<workspace>/trial.json
    {"since": "2026-11-19T00:00:00+02:00", "plan": ["new", "real", "new", "real"],
     "usd": 16, "videos": []}

A video joins when it is turned to Creatorz, if it was uploaded on or after ``since`` and the
plan still has room. The n-th video to join gets ``plan[n - 1]``: "new" switches new places on
in that same choice, so the one render he asked for already has them; "real" changes nothing.
His own presses on the card afterwards always win. Every video in the test renders under one
total (``usd``) on top of the per-render and per-day limits.

Paths come from the caller (config.looks_dir), so this file reads no settings."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE = "trial.json"
NEW, REAL = "new", "real"

# Remembered per file by (modified time, size, inode): two writes inside one clock tick share a
# modified time on Linux, and each write is a new file (os.replace), so the inode tells them apart.
_seen: dict[str, tuple[tuple[int, int, int], dict[str, Any] | None]] = {}


def _file(folder: Path | str | None) -> Path | None:
    return Path(folder) / FILE if folder else None


def _utc(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC)


def load(folder: Path | str | None) -> dict[str, Any] | None:
    """The test as its file says, or None when there is no test (no file, or one that does not
    read as a test). Read on every Library card, so it is remembered until the file changes."""
    path = _file(folder)
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    known = _seen.get(str(path))
    if known is not None and known[0] == stamp:
        return known[1]
    test: dict[str, Any] | None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        plan = [str(p) for p in raw["plan"]]
        test = {
            "since": str(raw["since"]),
            "since_utc": _utc(str(raw["since"])),
            "plan": plan,
            "usd": float(raw["usd"]),
            "videos": [dict(v) for v in raw.get("videos") or []],
        }
        if not plan or any(p not in (NEW, REAL) for p in plan) or test["usd"] <= 0:
            test = None
    except (OSError, ValueError, KeyError, TypeError):
        test = None
    _seen[str(path)] = (stamp, test)
    return test


def _entry(test: dict[str, Any] | None, upload_id: Any) -> dict[str, Any] | None:
    if not test:
        return None
    return next((v for v in test["videos"] if v.get("upload_id") == str(upload_id)), None)


def _write(path: Path, test: dict[str, Any]) -> None:
    keep = {k: test[k] for k in ("since", "plan", "usd", "videos")}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(keep, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    _seen.pop(str(path), None)  # the next read is from the file just written, never from memory


def join(folder: Path | str | None, upload_id: Any, uploaded_at: datetime | None) -> dict[str, Any] | None:
    """Called when a video is turned to Creatorz. Its place in the test when it has just joined
    ({"upload_id", "slot", "arm", "at", "of", "joined": True}), its place without "joined" when
    it was already in, or None when it is not part of the test. Reads and writes the file with no await
    in between, so two choices in this process never take the same place."""
    test = load(folder)
    if test is None:
        return None
    had = _entry(test, upload_id)
    if had is not None:
        return {**had, "of": len(test["plan"])}
    if uploaded_at is None or len(test["videos"]) >= len(test["plan"]):
        return None
    when = uploaded_at if uploaded_at.tzinfo else uploaded_at.replace(tzinfo=UTC)
    if when.astimezone(UTC) < test["since_utc"]:
        return None
    slot = len(test["videos"]) + 1
    entry = {
        "upload_id": str(upload_id),
        "slot": slot,
        "arm": test["plan"][slot - 1],
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = _file(folder)
    assert path is not None
    _write(path, {**test, "videos": [*test["videos"], entry]})
    return {**entry, "of": len(test["plan"]), "joined": True}


def card(folder: Path | str | None, upload_id: Any) -> dict[str, Any] | None:
    """For the Library card: {"slot", "of", "arm"}, or None for a video not in the test."""
    test = load(folder)
    hit = _entry(test, upload_id)
    if hit is None:
        return None
    return {"slot": int(hit["slot"]), "of": len(test["plan"]), "arm": hit["arm"]}


def money(folder: Path | str | None, workspace_id: Any, upload_id: Any) -> dict[str, Any] | None:
    """What a render of a video in the test is told: the test's total and the ledger labels of
    every video in it (the step's own ledger names a render "<workspace>:<upload>")."""
    test = load(folder)
    if _entry(test, upload_id) is None:
        return None
    return {
        "usd": test["usd"],
        "labels": [f"{workspace_id}:{v['upload_id']}" for v in test["videos"]],
    }


def said(entry: dict[str, Any] | None) -> str:
    """The words the queued line adds for a video that has just joined the test."""
    if not entry or not entry.get("joined"):
        return ""
    what = "with new places" if entry["arm"] == NEW else "with the real backgrounds"
    return f" {what} (live test, video {entry['slot']} of {entry['of']})"
