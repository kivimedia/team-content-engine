"""Trend formats picked for the week, beside the hooks (T-25834).

Kept in the same hooks.json as the hook library, under two keys of its own:

    "format_weeks":    {"2026-11-23": [{"format_id", "candidate_id", "why", "chosen_by",
                                        "at", "script": {...}}]}
    "format_examples": {"good-better-best": {"state", "videos", "at"}}
    "format_wants":    {"good-better-best": {"choice": "want" | "pass", "at"}}   (T-26074)

T-26074 (Ziv, 27-Nov-2026): the trend page is for understanding a trend and deciding,
nothing more. "I see a trend I say yes, it goes into the list of big ideas." A yes is
kept here as "want"; TCE works out how he would do it after, never on that page.

A format goes on one video of the week. TCE puts it on the first video with no
format yet unless he names one; he can move it. Its script is written in the
background from that video's topic and script, saved on the pick as a draft, and
shown for him to read, change and accept ("script.state": writing, ready,
approved, failed). Nothing here touches the video's own script or its takes.
"""

from __future__ import annotations

import uuid
from typing import Any

from tce.hooks import library
from tce.hooks.formats import BY_ID, FORMATS, Format

LINE_MAX = 220


def _picks(data: dict[str, Any], week: str) -> list[dict[str, Any]]:
    weeks = data.get("format_weeks") if isinstance(data.get("format_weeks"), dict) else {}
    return [p for p in weeks.get(week, []) if isinstance(p, dict)]


def _put(data: dict[str, Any], week: str, picks: list[dict[str, Any]]) -> None:
    weeks = data.get("format_weeks") if isinstance(data.get("format_weeks"), dict) else {}
    weeks[week] = picks
    if len(weeks) > library.KEEP_WEEKS:
        weeks = {k: weeks[k] for k in sorted(weeks)[-library.KEEP_WEEKS:]}
    data["format_weeks"] = weeks


def _get(format_id: str) -> Format:
    fmt = BY_ID.get(format_id)
    if fmt is None:
        raise library.HookError("unknown_format", "That format is not in the studio.", status=404)
    return fmt


def _place(videos: list[dict[str, Any]], taken: set[str]) -> tuple[str | None, str]:
    if not videos:
        return None, "There is no video this week to put it on yet. Choose topics first."
    free = [v for v in videos if v["candidate_id"] not in taken]
    if free:
        return free[0]["candidate_id"], "TCE put it on the first video of the week with no format yet. Any topic with three ways to do one thing fits it."
    return videos[0]["candidate_id"], "Every video already has a format, so it went on the first in your order."


async def pick(
    ws: uuid.UUID, week: str, format_id: str, lineup: dict[str, Any], candidate_id: str | None = None
) -> dict[str, Any]:
    """Put a format on one video of this week. TCE chooses the video unless he names one."""
    _get(format_id)
    videos = library.week_videos(lineup)
    async with library._LOCK:
        data = library.read_store(ws)
        picks = [p for p in _picks(data, week) if p.get("format_id") != format_id]
        if candidate_id is not None:
            if candidate_id not in {v["candidate_id"] for v in videos}:
                raise library.HookError("not_this_week", "That video is not on this week's list to record.", status=400)
            chosen, why, by = candidate_id, "You put it on this video.", "owner"
        else:
            taken = {p.get("candidate_id") for p in picks if p.get("candidate_id")}
            chosen, why = _place(videos, taken)
            by = "tce"
        entry = {"format_id": format_id, "candidate_id": chosen, "why": why, "chosen_by": by, "at": library._now()}
        picks.append(entry)
        _put(data, week, picks)
        library.write_store(ws, data)
        return entry


async def unpick(ws: uuid.UUID, week: str, format_id: str) -> None:
    _get(format_id)
    async with library._LOCK:
        data = library.read_store(ws)
        _put(data, week, [p for p in _picks(data, week) if p.get("format_id") != format_id])
        library.write_store(ws, data)


def current(ws: uuid.UUID, week: str, format_id: str) -> dict[str, Any] | None:
    return next((p for p in _picks(library.read_store(ws), week) if p.get("format_id") == format_id), None)


async def set_script(
    ws: uuid.UUID, week: str, format_id: str, candidate_id: str, script: dict[str, Any]
) -> bool:
    """Write the script on the pick that is still on that video: a pick moved
    meanwhile is not overwritten by a stale writer."""
    async with library._LOCK:
        data = library.read_store(ws)
        picks = _picks(data, week)
        for entry in picks:
            if entry.get("format_id") == format_id and entry.get("candidate_id") == candidate_id:
                entry["script"] = {**script, "at": library._now()}
                _put(data, week, picks)
                library.write_store(ws, data)
                return True
    return False


def clean_lines(fmt: Format, lines: Any) -> dict[str, str]:
    """His own edit of the script: one line per step, trimmed, no long dashes."""
    if not isinstance(lines, dict):
        raise library.HookError("bad_script", "The script did not come through. Try again.", status=400)
    out: dict[str, str] = {}
    for step in fmt.steps:
        text = " ".join(str(lines.get(step.id) or "").replace("—", "-").replace("–", "-").split())
        if not text:
            raise library.HookError("empty_line", f"The line for {step.label} is empty.", status=400)
        if len(text) > LINE_MAX:
            raise library.HookError("long_line", f"The line for {step.label} is too long to say in one breath.", status=400)
        out[step.id] = text
    return out


async def approve(
    ws: uuid.UUID, week: str, format_id: str, lines: Any
) -> dict[str, Any]:
    """He read the script, maybe changed a word, and accepts it as it is now."""
    fmt = _get(format_id)
    cleaned = clean_lines(fmt, lines)
    entry = current(ws, week, format_id)
    if entry is None or not entry.get("candidate_id"):
        raise library.HookError("not_picked", "That format is not on a video this week.", status=409)
    script = entry.get("script") or {}
    if script.get("state") not in ("ready", "approved"):
        raise library.HookError("no_script", "There is no script to accept yet.", status=409)
    changed = any(cleaned[k] != (script.get("lines") or {}).get(k) for k in cleaned)
    await set_script(ws, week, format_id, entry["candidate_id"], {
        **script, "state": "approved", "lines": cleaned,
        "detail": "You accepted this script" + (" with your changes." if changed else "."),
    })
    return current(ws, week, format_id) or {}


def _script_view(fmt: Format, script: dict[str, Any] | None) -> dict[str, Any] | None:
    if not script:
        return None
    lines = script.get("lines") if isinstance(script.get("lines"), dict) else {}
    names = script.get("names") if isinstance(script.get("names"), dict) else {}
    return {
        "state": script.get("state") or "",
        "detail": script.get("detail") or "",
        "at": script.get("at"),
        "lines": [
            {"step": s.id, "label": s.label, "text": lines.get(s.id, ""), "name": names.get(s.id, "")}
            for s in fmt.steps
        ] if lines else [],
    }


def _steps(fmt: Format, prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id, "label": s.label, "does": s.does, "coach": list(s.coach), "screen": s.screen,
            "word": s.word, "drawing_url": f"{prefix}hooks/formats/{fmt.id}/drawing/{s.id}.svg",
        }
        for s in fmt.steps
    ]


async def page(ws: uuid.UUID, week: str, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every format for the studio page, with this week's pick and its script.

    A pick whose video left the week (taken out, or filmed) goes on another video
    and its line says so, the same as a hook: nothing points at a gone video."""
    titles = {v["candidate_id"]: v.get("title") or "" for v in videos}
    async with library._LOCK:
        data = library.read_store(ws)
        picks = _picks(data, week)
        changed = False
        taken: set[str] = set()
        kept: list[dict[str, Any]] = []
        for entry in picks:
            if entry.get("format_id") not in BY_ID:
                changed = True
                continue
            if entry.get("candidate_id") not in titles:
                chosen, why = _place(videos, taken)
                if chosen != entry.get("candidate_id"):
                    left = "Its video left this week's list. " if entry.get("candidate_id") else ""
                    entry = {**entry, "candidate_id": chosen, "why": left + why, "chosen_by": "tce",
                             "at": library._now(), "script": None}
                    changed = True
            if entry.get("candidate_id"):
                taken.add(entry["candidate_id"])
            kept.append(entry)
        if changed:
            _put(data, week, kept)
            library.write_store(ws, data)
        examples = data.get("format_examples") if isinstance(data.get("format_examples"), dict) else {}
        wants = data.get("format_wants") if isinstance(data.get("format_wants"), dict) else {}
    by_format = {p["format_id"]: p for p in kept}
    out = []
    for fmt in FORMATS:
        entry = by_format.get(fmt.id)
        seen = examples.get(fmt.id) if isinstance(examples.get(fmt.id), dict) else {}
        out.append({
            "id": fmt.id,
            "name": fmt.name,
            "what": fmt.what,
            "why": fmt.why,
            "song": fmt.song,
            "edit": fmt.edit,
            "steps": _steps(fmt, ""),
            "examples": (seen.get("videos") or [])[:6],
            "real": _real(fmt),
            "decision": (wants.get(fmt.id) or {}).get("choice") if isinstance(wants.get(fmt.id), dict) else None,
            "decided_at": (wants.get(fmt.id) or {}).get("at") if isinstance(wants.get(fmt.id), dict) else None,
            "pick": None if entry is None else {
                "candidate_id": entry.get("candidate_id"),
                "title": titles.get(entry.get("candidate_id") or "", ""),
                "why": entry.get("why", ""),
                "chosen_by": entry.get("chosen_by", "tce"),
                "script": _script_view(fmt, entry.get("script")),
            },
        })
    return out


def for_video(ws: uuid.UUID, week: str, candidate_id: str) -> list[dict[str, Any]]:
    """The format on one video this week, step by step for the recording screen.
    Each step says the line to say when the script is written, else what the line does."""
    out: list[dict[str, Any]] = []
    for entry in _picks(library.read_store(ws), week):
        fmt = BY_ID.get(entry.get("format_id"))
        if fmt is None or entry.get("candidate_id") != candidate_id:
            continue
        script = entry.get("script") or {}
        written = script.get("state") in ("ready", "approved") and isinstance(script.get("lines"), dict)
        steps = _steps(fmt, "")
        for step in steps:
            step["say"] = (script["lines"].get(step["id"]) or "") if written else ""
        out.append({
            "id": fmt.id, "name": fmt.name, "what": fmt.what, "edit": fmt.edit, "steps": steps,
            "script_state": script.get("state") or "none",
            "script_detail": script.get("detail") or "",
        })
    return out


def format_on(ws: uuid.UUID, candidate_id: Any) -> tuple[Format, dict[str, Any]] | None:
    """The format on this topic and its pick, from the newest week that has one (the edit)."""
    if candidate_id is None:
        return None
    weeks = library.read_store(ws).get("format_weeks") or {}
    if not isinstance(weeks, dict):
        return None
    for week in sorted(weeks, reverse=True):
        for entry in weeks[week] or []:
            if isinstance(entry, dict) and entry.get("candidate_id") == str(candidate_id):
                fmt = BY_ID.get(entry.get("format_id"))
                if fmt is not None:
                    return fmt, entry
    return None


def names_for_week(ws: uuid.UUID, week: str) -> dict[str, list[str]]:
    """candidate_id -> the formats on it this week, for the week page's hook line."""
    out: dict[str, list[str]] = {}
    for entry in _picks(library.read_store(ws), week):
        fmt = BY_ID.get(entry.get("format_id"))
        if fmt is not None and entry.get("candidate_id"):
            out.setdefault(entry["candidate_id"], []).append(f"{fmt.name} (format)")
    return out


CHOICES = ("want", "pass")


async def decide(ws: uuid.UUID, format_id: str, choice: str | None) -> dict[str, Any] | None:
    """His yes ("want": it goes on his big ideas list) or no ("pass") on a trend.
    None takes the decision back. Returns what is kept now."""
    _get(format_id)
    if choice is not None and choice not in CHOICES:
        raise library.HookError("bad_choice", "That is not a choice for a trend.", status=400)
    async with library._LOCK:
        data = library.read_store(ws)
        wants = data.get("format_wants") if isinstance(data.get("format_wants"), dict) else {}
        if choice is None:
            wants.pop(format_id, None)
            kept = None
        else:
            kept = {"choice": choice, "at": library._now()}
            wants[format_id] = kept
        data["format_wants"] = wants
        library.write_store(ws, data)
        return kept


def wanted(ws: uuid.UUID) -> list[dict[str, Any]]:
    """The trends he said yes to, oldest first: his big ideas waiting for TCE's idea."""
    wants = library.read_store(ws).get("format_wants") or {}
    out = []
    for format_id, entry in wants.items():
        fmt = BY_ID.get(format_id)
        if fmt is None or not isinstance(entry, dict) or entry.get("choice") != "want":
            continue
        out.append({"id": fmt.id, "name": fmt.name, "what": fmt.what, "at": entry.get("at")})
    return sorted(out, key=lambda e: e.get("at") or "")


def _real(fmt: Format) -> list[dict[str, Any]]:
    return [
        {
            "video_id": e.video_id, "url": e.url, "channel": e.channel, "title": e.title, "watch": e.watch,
            # YouTube's own stills from the start, middle and end of the clip: they play
            # as a moving picture on the card before he taps for the video itself.
            "frames": [f"https://i.ytimg.com/vi/{e.video_id}/hq{n}.jpg" for n in (1, 2, 3)],
            "embed": f"https://www.youtube-nocookie.com/embed/{e.video_id}?autoplay=1&playsinline=1&rel=0",
        }
        for e in fmt.real
    ]


async def save_examples(ws: uuid.UUID, format_id: str, found: dict[str, Any]) -> None:
    async with library._LOCK:
        data = library.read_store(ws)
        examples = data.get("format_examples") if isinstance(data.get("format_examples"), dict) else {}
        examples[format_id] = found
        data["format_examples"] = examples
        library.write_store(ws, data)
