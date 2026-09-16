"""In-process status for long editorial jobs (selection, packets).

The durable truth lives in the database (topic_candidates, recording_packets,
llm_jobs). This registry only answers "what is running right now" for the
dashboard's live activity panel, with a human-readable current_activity string
and the llm job ids to link. It resets on restart; a restarted process shows
"idle" plus whatever the database already holds.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()
_ENTRIES: dict[tuple[str, str, str], dict[str, Any]] = {}
_MAX_ENTRIES = 500


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(workspace_id: uuid.UUID | str, kind: str, key: str) -> tuple[str, str, str]:
    return (str(workspace_id), kind, str(key))


def start(
    workspace_id: uuid.UUID | str, kind: str, key: str, activity: str, **extra: Any
) -> dict[str, Any]:
    entry = {
        "workspace_id": str(workspace_id),
        "kind": kind,
        "key": str(key),
        "state": "running",
        "current_activity": activity,
        "job_ids": [],
        "started_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "detail": None,
        **extra,
    }
    with _LOCK:
        if len(_ENTRIES) >= _MAX_ENTRIES:
            oldest = sorted(_ENTRIES.items(), key=lambda kv: kv[1]["updated_at"])[:50]
            for k, _ in oldest:
                _ENTRIES.pop(k, None)
        _ENTRIES[_key(workspace_id, kind, key)] = entry
    return dict(entry)


def update(workspace_id: uuid.UUID | str, kind: str, key: str, **fields: Any) -> None:
    with _LOCK:
        entry = _ENTRIES.get(_key(workspace_id, kind, key))
        if entry is None:
            return
        job_id = fields.pop("job_id", None)
        if job_id and str(job_id) not in entry["job_ids"]:
            entry["job_ids"].append(str(job_id))
        entry.update(fields)
        entry["updated_at"] = _now()
        if fields.get("state") in ("done", "waiting", "failed"):
            entry["finished_at"] = _now()


def get(workspace_id: uuid.UUID | str, kind: str, key: str) -> dict[str, Any] | None:
    with _LOCK:
        entry = _ENTRIES.get(_key(workspace_id, kind, key))
        return dict(entry, job_ids=list(entry["job_ids"])) if entry else None


def is_running(workspace_id: uuid.UUID | str, kind: str, key: str) -> bool:
    entry = get(workspace_id, kind, key)
    return bool(entry and entry["state"] == "running")


def list_for_workspace(workspace_id: uuid.UUID | str, limit: int = 50) -> list[dict[str, Any]]:
    ws = str(workspace_id)
    with _LOCK:
        rows = [
            dict(e, job_ids=list(e["job_ids"]))
            for e in _ENTRIES.values()
            if e["workspace_id"] == ws
        ]
    rows.sort(key=lambda e: e["updated_at"], reverse=True)
    return rows[:limit]


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()
