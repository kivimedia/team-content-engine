"""Creatorz style for a TCE edit (10-Nov-2026, Ziv: "can TCE have that as a styling option
where we choose Pill style or Creatorz style?").

Pill is today's look and the default; a video with no style set renders exactly as before.
Creatorz keeps TCE's own edit, the same lines in the same order, on TCE's own frame clock
(the engine's exact mode). That is what keeps his notes, Jennifer's check and the subtitles
working: they all read the render's keep. What changes is the look: punch-ins every couple of
seconds, phrase captions, text that pops on the key words, sound effects, a music bed.

The engine in ./engine is vendored from kivi-design-pack (kivi-video-pack/skills/creatorz-style/
engine); ./engine/VERSION names the commit. Which words pop is the one creative decision, and
it goes to the subscription worker; nothing here calls a metered API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tce.production.creatorz.engine.creatorz_reel import compose_plan
from tce.production.creatorz.engine.creatorz_reel import cut as engine_cut
from tce.production.creatorz.engine.creatorz_reel import plan as engine_plan
from tce.production.retakes import EDIT_FPS
from tce.settings import settings

PILL, CREATORZ = "pill", "creatorz"
STYLES = (PILL, CREATORZ)
ENGINE_DIR = Path(__file__).parent / "engine"
MOMENTS_JOB = "video_creatorz_moments"
PROMPT_VERSION = "creatorz-moments-3"
# Exit 1 from the engine means a checklist line failed: the video is made, and the card says so.
ENGINE_OK = (0, 1)
_one_render = asyncio.Semaphore(1)

Status = Callable[[str], Awaitable[Any]]


class CreatorzFailed(Exception):
    """Why this video could not be made in Creatorz style, in a sentence for the card."""


@dataclass
class ReelResult:
    out: Path
    voice: Path
    shots: int
    checklist: list[list[str]]
    captions: list[list[Any]]


def style_of(plan: dict[str, Any] | None) -> str:
    style = ((plan or {}).get("overrides") or {}).get("style")
    return style if style in STYLES else PILL


def enabled_for(workspace_id: uuid.UUID | str | None) -> bool:
    """TCE_PRODUCTION_CREATORZ_WORKSPACES: a comma list of workspaces, or "*" for all. Config, like
    the workspace languages: a workspace not listed sees nothing new."""
    listed = [p.strip() for p in (settings.production_creatorz_workspaces or "").split(",") if p.strip()]
    if "*" in listed:
        return True
    return workspace_id is not None and str(workspace_id).lower() in {p.lower() for p in listed}


def bed_for(upload_id: uuid.UUID) -> str | None:
    """A music bed from the library on this server, the same one for a video every time.
    No library, no bed: the words, the zooms and the sound effects still run."""
    folder = settings.production_creatorz_beds_dir
    if not folder or not Path(folder).is_dir():
        return None
    beds = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a"))
    if not beds:
        return None
    return str(beds[int(hashlib.sha256(str(upload_id).encode()).hexdigest(), 16) % len(beds)])


def engine_words(plan_words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The plan's kept words as the engine reads them. "[sound]" marks a noise, not a word."""
    return [
        {"text": str(w["text"]), "start_s": float(w["start"]), "end_s": float(w["end"])}
        for w in plan_words
        if str(w.get("text") or "").strip() and str(w.get("text")) != "[sound]"
    ]


def shots_for(keep: list[list[float]], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The reel's shots with their words on the edit clock. Pure: the moments are chosen and
    checked against exactly what the engine will cut."""
    shots = engine_cut.build_exact_shots([(s, e) for s, e in keep], words, EDIT_FPS)
    engine_cut.timeline(shots)
    return shots


EDGE_WALK_S = 0.35


def tighten_keep(
    keep: list[list[float]], levels: list[float], words: list[dict[str, Any]], *,
    protect: list[list[float]] = (), transcript: list[dict[str, Any]] = (), thr_db: float = -40.0, gap_s: float = 0.28,
    min_run_s: float = 0.12, pad_in: float = 0.05, pad_out: float = 0.08, edge_db: float | None = None,
) -> list[list[float]]:
    """The Creatorz pace: no air. TCE's own edit keeps a natural rhythm (445b0c26: 12.3 s of its
    81 s were air at the edges of kept ranges); here each kept range shrinks to the voice inside
    it, and a real pause inside one becomes a jump cut. It only ever removes air: a word too
    quiet for the meter keeps its place, and a laugh kept on purpose stays."""
    hop, reach = 0.01, int(round(EDGE_WALK_S / 0.01))

    def edges(v0: float, v1: float, a: float, b: float) -> tuple[float, float]:
        """A word starts and ends softer than the meter's -40 dB. With the recording's own floor
        given, each edge follows the sound out to it, a breath at most ("It" on 445b0c26 opens
        100 ms before -40 dB, and cutting there is a clipped word)."""
        if edge_db is None:
            return v0, v1
        lo, hi, k0, k1 = int(round(a / hop)), min(len(levels), int(round(b / hop))), int(round(v0 / hop)), int(round(v1 / hop))
        for _ in range(reach):
            if k0 - 1 < lo or levels[k0 - 1] <= edge_db:
                break
            k0 -= 1
        for _ in range(reach):
            if k1 >= hi or levels[k1] <= edge_db:
                break
            k1 += 1
        return k0 * hop, k1 * hop

    out: list[list[float]] = []
    for a, b in keep:
        spans = []
        for v0, v1 in engine_cut.voiced_runs(levels, a, b, thr_db, gap_s, min_run_s):
            s0, s1 = edges(v0, v1, a, b)
            spans.append([max(a, s0 - pad_in), min(b, s1 + pad_out)])
        spans += [[max(a, p_a), min(b, p_b)] for p_a, p_b in protect if p_a < b and a < p_b]
        for w in words:
            mid = (w["start_s"] + w["end_s"]) / 2
            if a <= mid < b and not any(s <= mid < e for s, e in spans):
                spans.append([max(a, w["start_s"] - pad_in), min(b, w["end_s"] + pad_out)])
        # Only the loud middle of a word clears the meter: its soft start and tail are not air. A cut strictly inside a
        # word's own times is a clipped word, by the rule Jennifer's check reads (autoedit.word_marks, plus or minus
        # 30 ms), and "the cut starts inside You" was the first thing she said about this (445b0c26).
        for w in [*words, *transcript]:
            s_w, e_w = float(w["start_s"]), float(w["end_s"])
            if not (s_w < b and a < e_w):  # any overlap: a first word's times can stretch back over silence
                continue
            for span in spans:
                if s_w + 0.03 < span[0] < e_w - 0.03:
                    span[0] = max(a, s_w - pad_in)
                if s_w + 0.03 < span[1] < e_w - 0.03:
                    span[1] = min(b, e_w + pad_out)
        merged: list[list[float]] = []
        for s, e in sorted(spans):
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        out.extend([round(s, 3), round(e, 3)] for s, e in merged)
    return out


def moments_key(keep: list[list[float]], words: list[dict[str, Any]]) -> str:
    """The moments belong to these words on this cut; anything else asks again."""
    body = json.dumps([keep, [[w["text"], w["start_s"]] for w in words], PROMPT_VERSION])
    return hashlib.sha256(body.encode()).hexdigest()[:20]


def reel_plan(
    *, src: Path, words_path: Path, keep: list[list[float]], lang: str, work: Path,
    moments: list[dict[str, Any]], punchline: int | None, bed: str | Path | None,
) -> dict[str, Any]:
    return {
        "schema": engine_plan.SCHEMA,
        "source": str(src),
        "words": str(words_path),
        "lang": lang,
        "grade": "golden",
        "fps": EDIT_FPS,
        "exact": True,
        "work": str(work),
        "out": str(Path(work) / "reel.mp4"),
        "picks": [{"span": [s, e]} for s, e in keep],
        "moments": moments,
        "punchline": punchline,
        "bed": str(bed) if bed else None,
        "length_range": [5, 3600],  # a full edit, not a 40 second reel
    }


# ---------------------------------------------------------------- the moments
_COMMON = {"at", "until", "sound", "gain"}
_ALLOWED: dict[str, set[str]] = {
    "headline": _COMMON | {"text", "color", "look", "place", "size", "check"},
    "strike": {"target", "at", "until", "sound", "gain"},
    "pair": _COMMON | {"light", "bold", "color", "size", "bold_at"},
    "badge": _COMMON | {"text", "color", "side"},
    "bubble": _COMMON | {"lines"},
    "tag": _COMMON | {"text"},
    "card_grid": {"at", "until", "title", "title_color", "cells", "filled", "labels", "empty_label", "ticks"},
    "card_list": {"at", "until", "items", "ticks"},
    "card_stat": {"at", "until", "text", "label"},
    "whip": {"at"},
    "flash": {"at", "sound", "gain"},
    "riser": {"into", "gain"},
    "sound": {"name", "at", "gain"},
}
# The engine draws white or the video's ONE accent color (10-Nov: five glowing colors in one video read as
# cheap). The old color names are still accepted from saved plans; each means "accent".
_COLORS = {"white", "accent", "yellow", "green", "cyan", "red"}
_LOOKS = {"plain", "extrude", "neon"}
_PLACES = {"sky", "top", "chest", "low"}
_SOUNDS = {"whoosh", "tick", "ding", "flash", "riser"}
_MID = {"pair", "bubble", "card_grid", "card_list", "card_stat"}
_CAPS = {"card_stat": 2, "whip": 4}  # the most of each in one video: a cutaway that repeats stops being one


def _tidy(raw: dict[str, Any]) -> dict[str, Any]:
    """Only the fields the engine reads, with values it can draw."""
    kind = raw["type"]
    m = {k: v for k, v in raw.items() if k in _ALLOWED[kind]}
    m["type"] = kind
    if kind == "card_stat" and m.get("text") is not None:
        m["text"] = str(m["text"])
    for field, allowed in (("color", _COLORS), ("title_color", _COLORS), ("look", _LOOKS), ("sound", _SOUNDS)):
        if field in m and m[field] not in allowed:
            del m[field]
    if kind == "headline" and "place" in raw and raw.get("place") not in _PLACES:
        m["place"] = "top"
    return m


def _missing(m: dict[str, Any]) -> str | None:
    kind = m["type"]
    required = {
        "headline": ["text", "at"], "pair": ["light", "bold", "at"], "badge": ["text", "at"], "bubble": ["lines", "at"],
        "tag": ["text", "at"], "card_grid": ["title", "at"], "card_list": ["items", "at"], "flash": ["at"],
        "riser": ["into"], "sound": ["name", "at"], "strike": ["target", "at"], "card_stat": ["text", "at"],
        "whip": ["at"],
    }[kind]
    for field in required:
        if not m.get(field) and m.get(field) != 0:
            return f"it has no {field}"
    if kind == "sound" and m["name"] not in _SOUNDS:
        return f"there is no sound called {m['name']}"
    for field in ("text", "bold"):
        if isinstance(m.get(field), str) and len(m[field]) > 40:
            return f"its {field} is too long for the screen"
    if kind == "card_list" and not (isinstance(m["items"], list) and 1 <= len(m["items"]) <= 6):
        return "a list card holds 1 to 6 lines"
    if kind == "bubble" and not (isinstance(m["lines"], list) and 1 <= len(m["lines"]) <= 3):
        return "a bubble holds 1 to 3 lines"
    if kind == "card_stat" and len(str(m["text"])) > 6:
        return "a number card holds one short number, like 80% or 3x"
    if kind == "card_stat" and len(str(m.get("label") or "")) > 28:
        return "its label is too long for the screen"
    return None


def _slot(m: dict[str, Any]) -> str | None:
    kind = m["type"]
    if kind == "headline":
        return "middle" if m.get("place") in ("chest", "low") else "top"
    if kind in _MID:
        return "middle"
    return kind if kind in ("badge", "tag") else None


def clean_moments(
    raw: Any, shots: list[dict[str, Any]], lang: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """What the writer gave, checked against the real cut: what the engine can draw, and a
    sentence for each thing it cannot, so the writer can be told once. One bad pop never
    costs the render."""
    edit = {"shots": shots, "duration": shots[-1]["out_out"] if shots else 0.0, "lang": lang}
    problems: list[str] = []
    kept: list[dict[str, Any]] = []  # {"raw_index", "m", "t0", "t1"}
    entries = raw if isinstance(raw, list) else []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("type") not in _ALLOWED:
            problems.append(f"moment {i}: unknown type {entry.get('type') if isinstance(entry, dict) else entry!r}")
            continue
        m = _tidy(entry)
        why = _missing(m)
        if why:
            problems.append(f"moment {i} ({m['type']}): {why}")
            continue
        try:
            items = compose_plan.build({"moments": [m]}, edit)["items"]
        except (engine_plan.CueError, KeyError, TypeError, ValueError, IndexError, StopIteration) as exc:
            problems.append(f"moment {i} ({m['type']}): {str(exc)[:160]}")
            continue
        t0, t1 = (items[0]["t0"], items[0]["t1"]) if items else (None, None)
        slot = _slot(m)
        clash = next(
            (k for k in kept if slot and _slot(k["m"]) == slot and t0 < k["t1"] - 0.01 and k["t0"] < t1 - 0.01), None
        )
        if clash is not None:
            problems.append(f"moment {i} ({m['type']}): overlaps moment {clash['raw_index']} in the same place on screen")
            continue
        most = _CAPS.get(m["type"])
        if most is not None and sum(1 for k in kept if k["m"]["type"] == m["type"]) >= most:
            problems.append(f"moment {i} ({m['type']}): a video holds at most {most} of these")
            continue
        kept.append({"raw_index": i, "m": m, "t0": t0, "t1": t1})
    # A strike names a headline by its place in the list, and the list may just have shrunk.
    position = {k["raw_index"]: new for new, k in enumerate(kept)}
    final: list[dict[str, Any]] = []
    dropped: set[int] = set()
    for k in kept:
        if k["m"]["type"] != "strike":
            continue
        target = k["m"].get("target")
        hit = next((x for x in kept if x["raw_index"] == target), None)
        if hit is None or hit["m"]["type"] != "headline":
            problems.append(f"moment {k['raw_index']} (strike): moment {target} is not a headline that was kept")
            dropped.add(k["raw_index"])
    survivors = [k for k in kept if k["raw_index"] not in dropped]
    position = {k["raw_index"]: new for new, k in enumerate(survivors)}
    for k in survivors:
        m = dict(k["m"])
        if m["type"] == "strike":
            m["target"] = position[m["target"]]
        final.append(m)
    return final, problems


MOMENTS_SYSTEM = """You direct short talking-head videos in the Creatorz style: fast, punchy, one idea at a time.
You get the lines of a finished edit, numbered, each with how long it lasts. Choose where text pops on screen and
where the picture cuts away from the speaker.

Answer with JSON only: {"moments": [...], "punchline": <line number or null>}.

Rules:
- About one moment every 3 to 4 seconds of video, and never more than 4.5 seconds without one.
- Pop the word that carries the point, never filler.
- "word" in a cue must be a word exactly as written in THAT line. Cue: {"pick": <line number>, "word": "..."} or {"pick": <line number>, "at": "start"} or "end".
- Write on-screen text in the same language as the lines. Headlines are 1 to 3 words; UPPERCASE for Latin letters.
- The video has ONE accent color, picked from the footage. "color" is "white" or "accent", nothing else. Use accent for the few words that matter most, white for the rest.
- You never choose where text sits: the engine finds the free spot and keeps every word off the speaker's face.
- Screen places: top (headline), middle (headline with place "chest", pair, bubble, cards), badge, tag. Never two at once in one place.
- A moment lasts until the end of its line unless you give "until" (a cue).
- A headline is ONE BEAT, about a second, whatever its "until" says. It cannot cover a stretch: over several lines in a row, put a moment on each.
- Give the eye a rest from the face: a talking head with nothing else for 20 seconds is too long. Use the full-screen cards for that.

Types:
- headline: text, color, place ("top", or "chest" to take the caption line for one beat)
- pair: light (small first line), bold (big line), at, bold_at (cue where the bold line lands)
- badge: text (a short number)
- bubble: lines (1 to 3 short lines), for a sentence someone said
- tag: text, a small handwritten label that names what comes next
- strike: target (the index in your moments list of a headline), at: a red line through the old or wrong idea
- card_list: items (2 to 4 short lines), at, until, ticks: a FULL-SCREEN checklist. The picture cuts to it at "at" and again for a beat at every tick. "ticks" is a list with one cue per item, at the word where the speaker gets to that item (or "spread" when the items are not said one by one). At most one every 30 seconds.
- card_stat: text (ONE number, like "80%" or "3x"), label (2 to 4 words under it), at: a FULL-SCREEN number for a second and a half, for the one number that matters. At most 2 in a video.
- card_grid: title, cells (3 to 6), filled (cell numbers, the first cell is 0), labels ("Week {n}"), empty_label, at, until: a FULL-SCREEN row of boxes; rarely
- whip: at ({"pick": N, "at": "start"}): a fast blur across the cut into line N, where the talk turns to a new part. At most 4 in a video, never closer than 12 seconds apart.
- flash: at: a white flash before a turn in the story, rarely

"punchline" is the line number of the single strongest line.

Example: {"moments": [{"type": "headline", "text": "PRICE", "color": "accent", "place": "top", "at": {"pick": 0, "word": "price,"}},
{"type": "strike", "target": 0, "at": {"pick": 0, "word": "calendar."}},
{"type": "pair", "light": "here's what he", "bold": "NEVER SAID", "at": {"pick": 3, "word": "Here's"}, "bold_at": {"pick": 3, "word": "never"}},
{"type": "card_stat", "text": "80%", "label": "said yes", "at": {"pick": 5, "word": "80%"}},
{"type": "whip", "at": {"pick": 6, "at": "start"}},
{"type": "tag", "text": "the fix:", "at": {"pick": 6, "at": "start"}},
{"type": "card_list", "items": ["Every two weeks", "Same help"], "at": {"pick": 7, "at": "start"}, "until": {"pick": 8, "at": "end"},
 "ticks": [{"pick": 7, "word": "two"}, {"pick": 8, "word": "help"}]}],
"punchline": 3}"""

MOMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": sorted(_ALLOWED)}},
                "required": ["type"],
                "additionalProperties": True,
            },
        },
        "punchline": {"type": ["integer", "null"]},
    },
    "required": ["moments"],
    "additionalProperties": False,
}


def moments_prompt(shots: list[dict[str, Any]], lang: str) -> str:
    lines = [
        f"[{s['pick']}] ({s['out_out'] - s['out_in']:.1f}s) {s['text']}" for s in shots if s.get("text")
    ]
    length = shots[-1]["out_out"] if shots else 0.0
    return (
        f"Language: {'Hebrew' if lang == 'he' else 'English'}. The video is {length:.0f} seconds long, so about "
        f"{max(1, round(length / 3.5))} moments.\n\nLines:\n" + "\n".join(lines)
    )


Ask = Callable[[str, str, dict[str, Any], int], Awaitable[dict[str, Any]]]


def _punchline(answer: dict[str, Any], shots: list[dict[str, Any]]) -> int | None:
    p = answer.get("punchline")
    return p if isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(shots) else None


QUIET_MAX_S = 5.0  # the engine's own checklist line: a text moment at least every 5 seconds


def quiet_gaps(moments: list[dict[str, Any]], shots: list[dict[str, Any]], lang: str) -> list[tuple[float, float]]:
    """Stretches of the video where nothing pops for longer than the style allows, as
    (from, to) in seconds. What counts is when a moment STARTS (and each tick of a card): a
    headline is a one-second beat, so it does not fill the lines after it (11-Nov: the writer
    let one headline cover four lines and 7 seconds had nothing on screen)."""
    if not shots:
        return []
    edit = {"shots": shots, "duration": shots[-1]["out_out"], "lang": lang}
    try:
        items = compose_plan.build({"moments": moments}, edit)["items"]
    except (engine_plan.CueError, KeyError, TypeError, ValueError, IndexError, StopIteration):
        return []
    marks = sorted({0.0, edit["duration"]} | {it["t0"] for it in items} | {t for it in items for t in it.get("ticks", [])})
    return [(a, b) for a, b in zip(marks, marks[1:]) if b - a > QUIET_MAX_S]


def _line_at(shots: list[dict[str, Any]], t: float) -> int:
    return next((s["pick"] for s in shots if s["out_in"] <= t < s["out_out"]), shots[-1]["pick"])


def _hole_sentences(holes: list[tuple[float, float]], shots: list[dict[str, Any]]) -> list[str]:
    return [
        f"nothing pops between {a:.0f} s and {b:.0f} s (lines {_line_at(shots, a + 0.05)} to {_line_at(shots, b - 0.05)}): "
        "add a moment there. A headline is one beat and does not cover the lines after it"
        for a, b in holes
    ]


async def get_moments(shots: list[dict[str, Any]], lang: str, ask: Ask) -> dict[str, Any]:
    """The writer's moments, checked. Anything wrong goes back once with the exact reasons,
    a stretch with nothing on screen included; after that the good ones go ahead and the
    rest are dropped."""
    prompt = moments_prompt(shots, lang)
    answer = await ask(prompt, MOMENTS_SYSTEM, MOMENTS_SCHEMA, 0)
    moments, problems = clean_moments(answer.get("moments"), shots, lang)
    holes = quiet_gaps(moments, shots, lang) if moments else []
    problems = problems + _hole_sentences(holes, shots)
    if problems:
        again = (
            prompt + "\n\nYour last answer could not be used as it was:\n- " + "\n- ".join(problems[:30])
            + "\n\nLast answer:\n" + json.dumps(answer.get("moments"), ensure_ascii=False)[:12000]
            + "\n\nSend the whole list again with these fixed."
        )
        try:
            second = await ask(again, MOMENTS_SYSTEM, MOMENTS_SCHEMA, 1)
        except CreatorzFailed:
            second = None
        if second is not None:
            better, _still = clean_moments(second.get("moments"), shots, lang)
            # fewer quiet stretches wins; with the same number, the answer that kept more moments
            was = (len(holes) if moments else 10**6, -len(moments))
            now = (len(quiet_gaps(better, shots, lang)) if better else 10**6, -len(better))
            if now <= was:
                moments, answer = better, second
    if not moments:
        raise CreatorzFailed("the writer of the text moments gave nothing that fits this video")
    return {"moments": moments, "punchline": _punchline(answer, shots)}


# ---------------------------------------------------------------- the engine
_PROGRESS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^cut: (\d+) shots"), r"cut into \1 shots, grading the picture"),
    (re.compile(r"^masks: (\d+)/(\d+)"), r"finding you in the frames so text can sit behind your head (\1 of \2)"),
    (re.compile(r"^compose: frame (\d+)/(\d+)"), r"drawing the captions, text and zooms, frame \1 of \2"),
    (re.compile(r"^mix: "), "mixing your voice, the music and the sound effects"),
    (re.compile(r"^(PASS|FAIL|INFO) "), "measuring the finished video"),
]


def progress_sentence(line: str) -> str | None:
    for pattern, text in _PROGRESS:
        found = pattern.match(line.strip())
        if found:
            return "Creatorz style: " + found.expand(text)
    return None


def _wrapper() -> list[str]:
    """A memory cap and low priority, so a video can never crowd the server (29-Oct: runaway
    parallel jobs froze the box). Not the box-wide heavy-job queue: that is for builds and test
    suites, and a video he is waiting for must not sit behind an hours-long build, any more than
    a Pill render does. One Creatorz render runs at a time (_one_render). Where there is no
    systemd (a PC), the engine runs directly."""
    if not shutil.which("systemd-run"):
        return []
    return ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=6G", "-p", "MemorySwapMax=1G", "--", "nice", "-n", "10"]


def _engine_env() -> dict[str, str]:
    env = dict(os.environ, PYTHONUNBUFFERED="1", OMP_NUM_THREADS="6")
    if hasattr(os, "getuid"):  # the memory cap needs the user's systemd, which pm2 does not hand down
        runtime = f"/run/user/{os.getuid()}"
        env.setdefault("XDG_RUNTIME_DIR", runtime)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    return env


def _stop(proc: asyncio.subprocess.Process) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError):
        pass


def _last_error(tail: list[str]) -> str:
    return next((t for t in reversed(tail) if not re.match(r"^(PASS|FAIL|INFO|compose:|masks:|cut:)", t)), "no output")[:200]


async def _run_engine(plan_path: Path, work: Path, on_status: Status) -> list[str]:
    python = settings.production_creatorz_python or sys.executable
    command = [*_wrapper(), python, "-P", str(ENGINE_DIR / "reel.py"), "all", str(plan_path)]
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(work),
        env=_engine_env(), start_new_session=hasattr(os, "killpg"),
    )
    tail: list[str] = []
    last = ""

    async def read() -> None:
        nonlocal last
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                tail[:] = (tail + [line])[-12:]
            said = progress_sentence(line)
            if said and said != last:
                last = said
                await on_status(said)
        await proc.wait()

    try:
        await asyncio.wait_for(read(), timeout=settings.production_creatorz_timeout_s)
    except TimeoutError as exc:
        raise CreatorzFailed(f"the render ran past {settings.production_creatorz_timeout_s / 60:.0f} minutes") from exc
    finally:
        if proc.returncode is None:
            _stop(proc)
    if proc.returncode not in ENGINE_OK:
        raise CreatorzFailed(f"the engine stopped (exit {proc.returncode}): {_last_error(tail)}")
    return tail


async def render_reel(
    *, src: Path, words: list[dict[str, Any]], keep: list[list[float]], lang: str, work: Path,
    moments: list[dict[str, Any]], punchline: int | None, bed: str | None, on_status: Status,
) -> ReelResult:
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    words_path = work / "words.json"
    plan_path = work / "plan.json"
    words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    plan_path.write_text(
        json.dumps(
            reel_plan(src=src, words_path=words_path, keep=keep, lang=lang, work=work, moments=moments, punchline=punchline, bed=bed),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if _one_render.locked():
        await on_status("Creatorz style: waiting for the video ahead of this one to finish")
    async with _one_render:
        await on_status("Creatorz style: preparing the footage")
        tail = await _run_engine(plan_path, work, on_status)
    out, voice = work / "reel.mp4", work / "voice.wav"
    if not out.exists() or out.stat().st_size == 0 or not voice.exists():
        # exit 1 is also what a crash returns, not only a failed checklist line
        raise CreatorzFailed(f"the engine stopped without a video: {_last_error(tail)}")
    read = lambda name: json.loads((work / name).read_text(encoding="utf-8"))  # noqa: E731
    return ReelResult(
        out=out, voice=voice, shots=len(read("edit.json")["shots"]), checklist=read("checklist.json"),
        captions=[list(c) for c in read("events.json")["captions"]],
    )
