"""Hourly memory reading the app logs about itself.

Why: the API process was seen at about 2.3 GB (mostly swapped out) 21 hours after
a restart, while an earlier process sat under 111 MB at 7 hours. Nobody outside
the process can tell a slow leak from a one-off high-water mark, and the box
hides this process from other users. So the process says it itself, once an
hour, on one JSON log line:

- rss_mb, swap_mb, hwm_mb from /proc/self/status (hwm is the peak resident size:
  a high hwm with a flat rss means a one-off spike, a rising rss means growth);
- the Python object types whose live count grew most since the last reading;
- how many asyncio tasks and threads are alive;
- with TCE_TRACEMALLOC=1 only, the source lines holding the most new memory.

It only reads. It changes no behavior, and any failure is swallowed so it can
never take the API down. TCE_MEMPROBE_SECONDS sets the interval (default 3600,
0 turns it off).
"""

from __future__ import annotations

import asyncio
import gc
import os
import threading
from collections import Counter
from typing import Any

import structlog

logger = structlog.get_logger()

_TOP_TYPES = 15
_TOP_LINES = 15


def read_status(path: str = "/proc/self/status") -> dict[str, float]:
    """Resident, swapped and peak resident size in MB. Missing fields are left out."""
    wanted = {"VmRSS": "rss_mb", "VmSwap": "swap_mb", "VmHWM": "hwm_mb"}
    out: dict[str, float] = {}
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in wanted:
                    parts = rest.split()
                    if parts and parts[0].isdigit():
                        out[wanted[key]] = round(int(parts[0]) / 1024, 1)
    except OSError:
        pass
    return out


def type_counts() -> Counter[str]:
    """Live object count per type name, from the garbage collector's view."""
    counts: Counter[str] = Counter()
    for obj in gc.get_objects():
        counts[type(obj).__name__] += 1
    return counts


def grown_types(
    before: Counter[str] | None, now: Counter[str], top: int = _TOP_TYPES
) -> list[list[Any]]:
    """[[type, count now, change since before], ...] biggest growth first.

    On the first reading (no before) it is simply the largest types.
    """
    if before is None:
        return [[name, n, n] for name, n in now.most_common(top)]
    deltas = []
    for name, n in now.items():
        d = n - before.get(name, 0)
        if d > 0:
            deltas.append((d, name, n))
    deltas.sort(reverse=True)
    return [[name, n, d] for d, name, n in deltas[:top]]


class MemoryProbe:
    def __init__(self) -> None:
        self._last_types: Counter[str] | None = None
        self._snapshot: Any = None
        self.readings = 0

    def reading(self) -> dict[str, Any]:
        """One reading. Never raises."""
        out: dict[str, Any] = {}
        try:
            out.update(read_status())
            now = type_counts()
            out["objects"] = sum(now.values())
            out["grown_types"] = grown_types(self._last_types, now)
            self._last_types = now
            try:
                out["tasks"] = len(asyncio.all_tasks())
            except RuntimeError:
                pass
            out["threads"] = threading.active_count()
            out.update(self._trace_lines())
        except Exception as exc:  # a reading must never hurt the API
            out["error"] = type(exc).__name__
        self.readings += 1
        out["reading"] = self.readings
        return out

    def _trace_lines(self) -> dict[str, Any]:
        import tracemalloc

        if not tracemalloc.is_tracing():
            return {}
        snap = tracemalloc.take_snapshot().filter_traces(
            (tracemalloc.Filter(False, tracemalloc.__file__),)
        )
        if self._snapshot is None:
            stats = snap.statistics("lineno")[:_TOP_LINES]
            lines = [[str(s.traceback[0]), round(s.size / 1048576, 2), 0.0] for s in stats]
        else:
            stats = snap.compare_to(self._snapshot, "lineno")[:_TOP_LINES]
            lines = [
                [str(s.traceback[0]), round(s.size / 1048576, 2), round(s.size_diff / 1048576, 2)]
                for s in stats
            ]
        self._snapshot = snap
        traced, peak = tracemalloc.get_traced_memory()
        return {
            "traced_mb": round(traced / 1048576, 1),
            "traced_peak_mb": round(peak / 1048576, 1),
            "top_lines": lines,
        }


def interval_seconds() -> int:
    raw = os.environ.get("TCE_MEMPROBE_SECONDS", "3600").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3600


def start_tracing_if_asked() -> None:
    if os.environ.get("TCE_TRACEMALLOC") == "1":
        import tracemalloc

        if not tracemalloc.is_tracing():
            tracemalloc.start(1)


async def poll(probe: MemoryProbe | None = None) -> None:  # pragma: no cover - a loop
    every = interval_seconds()
    if every <= 0:
        return
    probe = probe or MemoryProbe()
    start_tracing_if_asked()
    while True:
        try:
            logger.info("memory.reading", pid=os.getpid(), **probe.reading())
        except Exception:
            pass
        await asyncio.sleep(every)
