"""Laughs stay in the edit (29-Oct-2026, Ziv on Connie's videos: "dont cut out her laughs!").

The tight cut keeps words. A laugh between two sentences has none, so it went out with the
pause around it: in "Get your ask in gear" the 1.1 s laugh after "Well, guess what?" (0:38.9)
was 0 % in the edit, and in "The counterfeit yes" the laugh after "yes, that sounds great"
lost its last fifth. The recogniser writes nothing for a laugh (a second listen heard no
word in any of her gaps) and a general sound tagger heard speech or a gasp, so a laughter
detector (scripts/laugh_worker.py, built by scripts/setup-laughs.sh) is the witness.

find_laughs runs it once per recording, niced, and keeps the answer beside the recording
keyed by its size and time, like the level reading. keep_laughs puts each laugh that sits
beside kept speech back into the keep. No detector configured, or a run that fails: no
laughs, and the cut is exactly what it was before.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

import structlog

from tce.production.tightcut import _grid
from tce.settings import settings

logger = structlog.get_logger()

WORKER = Path(__file__).resolve().parents[3] / "scripts" / "laugh_worker.py"

LAUGH_PAD_S = 0.08  # the detector reads in 0.09 s steps: its edges are that coarse
LAUGH_MAX_S = 3.0  # a longer laugh keeps its first 3 s
LAUGH_REACH_S = 0.6  # a laugh this close to a kept range belongs to what was said there
# A put-back laugh this close to a kept range runs into it with no cut: the longest pause
# the house cut keeps anyway (TJ's 0.24-0.40 s), so a laugh never adds dead air.
LAUGH_JOIN_S = 0.35
OVER_WORD_S = 0.05  # a laugh over a word the edit took out by more than this stays out with it
# Words taken out on purpose. A laugh over recognition noise or a "[sound]" the second listen
# split off is the laugh itself, so those never keep it out.
BLOCKING = frozenset({"retake", "false_start", "aside", "requested_cut"})
TIMEOUT_MIN_S = 180.0
TIMEOUT_PER_S = 2.0  # the loaded box read one minute of recording in about 60 s at 2 threads

_locks: dict[str, asyncio.Lock] = {}


def configured() -> bool:
    python, model = settings.production_laugh_python, settings.production_laugh_dir
    return bool(python and model and Path(python).exists() and Path(model).is_dir() and WORKER.exists())


def _cache(src: Path) -> Path:
    return src.with_name(f".{src.stem}-laughs.json")


def _key(src: Path) -> str:
    stat = src.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def cached(path: str | Path | None) -> list[list[float]] | None:
    """The laughs already found in this recording, or None when it was never read (or
    the recording changed since)."""
    if not path:
        return None
    src = Path(path)
    try:
        data = json.loads(_cache(src).read_text(encoding="utf-8"))
        if data.get("key") != _key(src):
            return None
        return [[float(a), float(b), float(p)] for a, b, p in data.get("laughs") or []]
    except (OSError, ValueError, TypeError):
        return None


async def find_laughs(
    path: str | Path | None, ffmpeg: str | None = None, duration_s: float | None = None
) -> list[list[float]] | None:
    """[start, end, peak] for each laugh in the recording, or None when there is no
    detector here or it failed. One run per recording at a time: a second caller (the
    plan, while the run started at transcription is still going) waits for its answer."""
    if not path or not configured():
        return None
    src = Path(path)
    if not src.exists():
        return None
    hit = cached(src)
    if hit is not None:
        return hit
    lock = _locks.setdefault(str(src), asyncio.Lock())
    async with lock:
        hit = cached(src)
        if hit is not None:
            return hit
        args = [settings.production_laugh_python, str(WORKER), settings.production_laugh_dir, str(src)]
        if ffmpeg:
            args += ["--ffmpeg", ffmpeg]
        nice = shutil.which("nice")
        if nice:
            args = [nice, "-n", "10", *args]
        timeout = max(TIMEOUT_MIN_S, TIMEOUT_PER_S * float(duration_s or 0.0))
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("production.laughs_timeout", file=src.name, timeout_s=timeout)
            return None
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-1:] or [""]
            logger.warning("production.laughs_failed", file=src.name, code=proc.returncode, err=tail[0][:200])
            return None
        try:
            data = json.loads(out.decode().strip().splitlines()[-1])
            laughs = [[float(a), float(b), float(p)] for a, b, p in data.get("laughs") or []]
        except (ValueError, IndexError, TypeError):
            logger.warning("production.laughs_unreadable", file=src.name)
            return None
        try:  # written aside and renamed, like the level reading
            part = _cache(src).with_name(_cache(src).name + ".part")
            part.write_text(json.dumps({"key": _key(src), "laughs": laughs}), encoding="utf-8")
            os.replace(part, _cache(src))
        except OSError:
            pass
        logger.info("production.laughs_found", file=src.name, laughs=len(laughs))
        return laughs


def played(a: float, b: float, keep: list[list[float]]) -> float:
    """How much of [a, b] on the recording is in the edit."""
    return sum(max(0.0, min(b, float(e)) - max(a, float(s))) for s, e in keep)


def keep_laughs(
    keep: list[list[float]],
    laughs: list[list[float]],
    removed: list[list[float]],
    end_bound: float,
) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """Each laugh beside kept speech goes back into `keep`.

    `removed` are the spans of words the edit took out on purpose (BLOCKING) and of cuts
    asked for: a laugh over one stays out with it. A laugh further than LAUGH_REACH_S from
    everything kept (inside a dropped take, in the lead-in before the first word) stays
    out too. Returns the new keep and one line a laugh for the plan: where, how sure, and
    whether it plays.
    """
    out = [[float(a), float(b)] for a, b in keep]
    lines: list[dict[str, Any]] = []
    for s, e, peak in sorted(laughs):
        a, b = max(0.0, s - LAUGH_PAD_S), min(end_bound, e + LAUGH_PAD_S)
        b = min(b, a + LAUGH_MAX_S)
        if b - a <= 0:
            continue
        line = {"start": round(s, 3), "end": round(e, 3), "peak": round(peak, 2)}
        if played(a, b, keep) >= (b - a) - 0.02:
            lines.append({**line, "kept": True, "why": "already in the edit"})
            continue
        if any(rs < b - OVER_WORD_S and re_ > a + OVER_WORD_S for rs, re_ in removed):
            lines.append({**line, "kept": False, "why": "over words the edit took out"})
            continue
        if not any(ks - LAUGH_REACH_S <= b and ke + LAUGH_REACH_S >= a for ks, ke in keep):
            lines.append({**line, "kept": False, "why": "not beside anything kept"})
            continue
        if not any(ks <= a <= ke for ks, ke in keep):
            before = max((ke for _ks, ke in keep if ke < a), default=None)
            if before is not None and a - before <= LAUGH_JOIN_S:
                a = before
        if not any(ks <= b <= ke for ks, ke in keep):
            after = min((ks for ks, _ke in keep if ks > b), default=None)
            if after is not None and after - b <= LAUGH_JOIN_S:
                b = after
        out.append([_grid(a, up=False), _grid(b, up=True)])
        lines.append({**line, "kept": True, "why": "put back beside the words"})
    out.sort()
    merged: list[list[float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [[round(a, 6), round(b, 6)] for a, b in merged], lines


def spans(plan: dict[str, Any] | None) -> list[list[float]]:
    """Every laugh the plan knows of, on the recording's clock, for what the editor reads
    (numbered_transcript marks one only where it plays in the edit it is shown)."""
    return [[float(x["start"]), float(x["end"])] for x in (plan or {}).get("laughs") or []]
