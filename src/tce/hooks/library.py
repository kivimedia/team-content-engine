"""His hook library: favorites and the hooks picked for each week (T-25210).

Kept as one small file per workspace beside its recordings
(`<evidence_upload_dir>/<workspace>/hooks.json`), so the library needs no change to
the database. Writes are atomic (a temporary file, then a rename) and go one at a
time through a lock.

Shape:
    {"favorites": ["big-number", ...],
     "weeks": {"2026-11-23": [{"hook_id", "candidate_id", "why", "chosen_by", "at"}]}}

`chosen_by` is "tce" when TCE put the hook on a video, "owner" when he moved it.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tce.hooks.catalog import BY_ID, HOOKS, Hook, matches
from tce.settings import settings

_LOCK = asyncio.Lock()
KEEP_WEEKS = 12


class HookError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def store_path(ws: uuid.UUID) -> Path:
    return Path(settings.evidence_upload_dir) / str(ws) / "hooks.json"


def read_store(ws: uuid.UUID) -> dict[str, Any]:
    path = store_path(ws)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        # A damaged file must not take the page down; it is rewritten on the next save.
        data = {}
    favorites = [h for h in data.get("favorites", []) if h in BY_ID]
    weeks = data.get("weeks") if isinstance(data.get("weeks"), dict) else {}
    return {"favorites": favorites, "weeks": weeks}


def write_store(ws: uuid.UUID, data: dict[str, Any]) -> None:
    path = store_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    weeks = data.get("weeks", {})
    if len(weeks) > KEEP_WEEKS:
        data["weeks"] = {k: weeks[k] for k in sorted(weeks)[-KEEP_WEEKS:]}
    fd, tmp = tempfile.mkstemp(prefix=".hooks-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def week_videos(lineup: dict[str, Any]) -> list[dict[str, Any]]:
    """The videos a hook can go on: this week's, not filmed yet, in recording order.
    With none of those, the spares; with none at all, an empty list."""
    primary = [i for i in lineup.get("primary") or [] if not i.get("filmed")]
    if primary:
        return primary
    return [i for i in lineup.get("reserve") or [] if not i.get("filmed")]


def _topic_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title", "big_idea", "reason"))


def place(hook: Hook, videos: list[dict[str, Any]], taken: set[str]) -> tuple[str | None, str]:
    """Which of the week's videos this hook goes on, and why, in one line."""
    if not videos:
        return None, "There is no video this week to put it on yet. Choose topics first."
    if hook.fits:
        for pool in ([v for v in videos if v["candidate_id"] not in taken], videos):
            for video in pool:
                word = matches(hook, _topic_text(video))
                if word:
                    return video["candidate_id"], f"Its topic says “{word}”: {hook.fit_reason}."
    free = [v for v in videos if v["candidate_id"] not in taken]
    if free:
        return free[0]["candidate_id"], "This hook works on any opening line, and this video had no hook yet."
    return videos[0]["candidate_id"], "This hook works on any opening line; every video already has one, so it is first in your order."


async def toggle_favorite(ws: uuid.UUID, hook_id: str, on: bool) -> list[str]:
    if hook_id not in BY_ID:
        raise HookError("unknown_hook", "That hook is not in the library.", status=404)
    async with _LOCK:
        data = read_store(ws)
        favorites = [h for h in data["favorites"] if h != hook_id]
        if on:
            favorites.append(hook_id)
        data["favorites"] = favorites
        write_store(ws, data)
        return favorites


async def pick(
    ws: uuid.UUID, week: str, hook_id: str, lineup: dict[str, Any], candidate_id: str | None = None
) -> dict[str, Any]:
    """Pick a hook for this week. TCE chooses the video unless he names one."""
    hook = BY_ID.get(hook_id)
    if hook is None:
        raise HookError("unknown_hook", "That hook is not in the library.", status=404)
    videos = week_videos(lineup)
    async with _LOCK:
        data = read_store(ws)
        picks = [p for p in data["weeks"].get(week, []) if p.get("hook_id") != hook_id]
        if candidate_id is not None:
            if candidate_id not in {v["candidate_id"] for v in videos}:
                raise HookError("not_this_week", "That video is not on this week's list to record.", status=400)
            chosen, why, by = candidate_id, "You put it on this video.", "owner"
        else:
            taken = {p.get("candidate_id") for p in picks if p.get("candidate_id")}
            chosen, why = place(hook, videos, taken)
            by = "tce"
        entry = {"hook_id": hook_id, "candidate_id": chosen, "why": why, "chosen_by": by, "at": _now()}
        picks.append(entry)
        data["weeks"][week] = picks
        write_store(ws, data)
        return entry


async def unpick(ws: uuid.UUID, week: str, hook_id: str) -> None:
    async with _LOCK:
        data = read_store(ws)
        data["weeks"][week] = [p for p in data["weeks"].get(week, []) if p.get("hook_id") != hook_id]
        write_store(ws, data)


async def library(ws: uuid.UUID, week: str, lineup: dict[str, Any], preview_url: Any) -> dict[str, Any]:
    """The page's whole read: every hook (favorites first), this week's picks with the
    video each one is on, and the videos he can move one to.

    A pick whose video has left the week (taken out, or filmed) is put on another
    video and saved, and its line says so: nothing silently points at a gone video."""
    videos = week_videos(lineup)
    titles = {v["candidate_id"]: v.get("title") or "" for v in videos}
    async with _LOCK:
        data = read_store(ws)
        picks = data["weeks"].get(week, [])
        changed = False
        taken: set[str] = set()
        kept: list[dict[str, Any]] = []
        for entry in picks:
            hook = BY_ID.get(entry.get("hook_id"))
            if hook is None:
                changed = True
                continue
            if entry.get("candidate_id") not in titles:
                chosen, why = place(hook, videos, taken)
                if chosen != entry.get("candidate_id"):
                    left = "Its video left this week's list. " if entry.get("candidate_id") else ""
                    entry = {**entry, "candidate_id": chosen, "why": left + why, "chosen_by": "tce", "at": _now()}
                    changed = True
            if entry.get("candidate_id"):
                taken.add(entry["candidate_id"])
            kept.append(entry)
        if changed:
            data["weeks"][week] = kept
            write_store(ws, data)
    favorites = data["favorites"]
    by_hook = {p["hook_id"]: p for p in kept}
    order = sorted(HOOKS, key=lambda h: (h.id not in favorites, HOOKS.index(h)))
    hooks = []
    for hook in order:
        entry = by_hook.get(hook.id)
        hooks.append({
            "id": hook.id,
            "name": hook.name,
            "what": hook.what,
            "record": hook.record,
            "preview_url": preview_url(hook.id),
            "favorite": hook.id in favorites,
            "pick": None if entry is None else {
                "candidate_id": entry.get("candidate_id"),
                "title": titles.get(entry.get("candidate_id") or "", ""),
                "why": entry.get("why", ""),
                "chosen_by": entry.get("chosen_by", "tce"),
            },
        })
    return {
        "week_start": week,
        "hooks": hooks,
        "picked": len(kept),
        "favorites": len(favorites),
        "videos": [{"candidate_id": v["candidate_id"], "title": v.get("title") or ""} for v in videos],
        "proved": len(HOOKS),
    }


def hooks_for_week(ws: uuid.UUID, week: str) -> dict[str, list[str]]:
    """candidate_id -> the names of the hooks picked onto it this week (the week page)."""
    out: dict[str, list[str]] = {}
    for entry in read_store(ws)["weeks"].get(week, []):
        hook = BY_ID.get(entry.get("hook_id"))
        if hook is not None and entry.get("candidate_id"):
            out.setdefault(entry["candidate_id"], []).append(hook.name)
    return out


def for_video(ws: uuid.UUID, week: str, candidate_id: str) -> list[dict[str, Any]]:
    """The hooks picked onto one video this week, with what to do on camera (T-25711).

    The recording screen reads this before he presses record. Read only: a pick whose
    video left the week is moved by the library page, not here."""
    out: list[dict[str, Any]] = []
    for entry in read_store(ws)["weeks"].get(week, []):
        hook = BY_ID.get(entry.get("hook_id"))
        if hook is None or entry.get("candidate_id") != candidate_id:
            continue
        out.append({
            "id": hook.id,
            "name": hook.name,
            "what": hook.what,
            "record": hook.record,
            "coach": list(hook.coach) or [hook.record],
            "why": entry.get("why", ""),
            "chosen_by": entry.get("chosen_by", "tce"),
        })
    return out
