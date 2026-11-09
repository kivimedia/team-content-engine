"""The book's chapters and their state, kept as files beside the recordings.

Why files and not a table: the release path refuses a schema change, and a book is a
handful of chapters with one owner. Everything lives under
<evidence_upload_dir>/book/:

  chapters.json   [{"n", "title", "part", "paragraphs": [...]}] - the text as imported
  state.json      {"status": {"<n>": {...}}, "chars_spent": int, "episodes": int}
  audio/<sha>.mp3 one narrated paragraph, cached by its text and voice

A chapter's status is draft, in review or approved. Approve is his; the book editor
moves a chapter to in review when it hands him a rewrite.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = ("draft", "in_review", "approved")
STATUS_WORDS = {"draft": "Draft", "in_review": "In review", "approved": "Approved"}

_CHAPTER = re.compile(r"^\s*chapter\s+(\d+)\s*[-\u2013\u2014:.]?\s*(.*)$", re.IGNORECASE)
_PART = re.compile(r"^\s*part\s+([a-z0-9.]+)\s*[-\u2013\u2014:]?\s*(.*)$", re.IGNORECASE)
_RULE = re.compile(r"^[\s_\-=*]+$")

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(line: str) -> str:
    return line.replace("﻿", "").replace("…", "...").strip()


def parse_chapters(text: str) -> list[dict[str, Any]]:
    """The written chapters of a manuscript exported as plain text.

    A chapter starts at a line "Chapter <n> - <title>" and runs to the next chapter, or
    to the next "Part ..." line after it (the outline that follows the written part).
    The table of contents before the first chapter is not a chapter. A chapter number
    written out twice keeps its first copy that has text (a contents line has none). The Google Docs export puts one
    paragraph on each line, so every non-empty line is a paragraph; a line made only of
    underscores or dashes is a page rule, not text."""
    chapters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    part = ""
    seen: set[int] = set()
    buffer: list[str] = []

    def flush_paragraph() -> None:
        if current is not None and buffer:
            paragraph = " ".join(buffer).strip()
            if paragraph:
                current["paragraphs"].append(paragraph)
        buffer.clear()

    def close() -> None:
        nonlocal current
        flush_paragraph()
        if current is not None and current["paragraphs"]:
            chapters.append(current)
            seen.add(current["n"])
        current = None

    for raw in text.splitlines():
        line = _clean(raw)
        chapter = _CHAPTER.match(line)
        if chapter:
            close()
            number = int(chapter.group(1))
            if number in seen:
                continue
            title = chapter.group(2).strip().strip("“”\"").strip() or f"Chapter {number}"
            current = {"n": number, "title": title, "part": part, "paragraphs": []}
            continue
        match = _PART.match(line)
        if match and len(line) < 120:
            close()
            part = line
            continue
        if current is None:
            continue
        flush_paragraph()
        if not line or _RULE.match(line):
            continue
        buffer.append(line)
    close()
    return chapters


class BookStore:
    """One book's chapters, status and narration cache, on disk."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.audio_dir = self.root / "audio"

    # -------------------------------------------------------------- files

    def _read(self, name: str, default: Any) -> Any:
        path = self.root / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default

    def _write(self, name: str, data: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def chapters(self) -> list[dict[str, Any]]:
        return list(self._read("chapters.json", []))

    def state(self) -> dict[str, Any]:
        data = self._read("state.json", {})
        data.setdefault("status", {})
        data.setdefault("chars_spent", 0)
        data.setdefault("episodes", 0)
        return data

    # ------------------------------------------------------------- import

    def import_text(self, text: str, *, source: str = "") -> list[dict[str, Any]]:
        """Replace the chapters with the ones in this text. A chapter's status is kept
        when its text did not change, and goes back to draft when it did."""
        found = parse_chapters(text)
        if not found:
            raise ValueError("No chapter headings (Chapter 1 - ...) were found in that text")
        with _lock:
            old = {c["n"]: c for c in self.chapters()}
            state = self.state()
            for chapter in found:
                key = str(chapter["n"])
                before = old.get(chapter["n"])
                if before is not None and before.get("paragraphs") != chapter["paragraphs"]:
                    state["status"][key] = {"status": "draft", "at": _now(), "by": "import"}
            self._write("chapters.json", found)
            state["source"] = source
            state["imported_at"] = _now()
            self._write("state.json", state)
        return found

    def ensure_imported(self, source_path: str) -> None:
        """First open: read the configured manuscript when nothing is imported yet."""
        if self.chapters() or not source_path:
            return
        path = Path(source_path)
        if path.is_file():
            self.import_text(path.read_text(encoding="utf-8", errors="replace"), source=str(path))

    # ------------------------------------------------------------- status

    def status_of(self, n: int) -> dict[str, Any]:
        return dict(self.state()["status"].get(str(n)) or {"status": "draft"})

    def set_status(self, n: int, status: str, *, by: str, note: str = "") -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}")
        if not any(c["n"] == n for c in self.chapters()):
            raise KeyError(n)
        with _lock:
            state = self.state()
            entry = {"status": status, "at": _now(), "by": by}
            if note:
                entry["note"] = note[:2000]
            history = list((state["status"].get(str(n)) or {}).get("history") or [])
            history.append({k: v for k, v in entry.items() if k != "history"})
            entry["history"] = history[-50:]
            state["status"][str(n)] = entry
            self._write("state.json", state)
        return entry

    # -------------------------------------------------------------- narration

    def audio_path(self, text: str, voice_id: str) -> Path:
        digest = hashlib.sha256(f"{voice_id}\n{text}".encode()).hexdigest()[:32]
        return self.audio_dir / f"{digest}.mp3"

    def charge(self, chars: int) -> int:
        with _lock:
            state = self.state()
            state["chars_spent"] = int(state["chars_spent"]) + int(chars)
            self._write("state.json", state)
            return state["chars_spent"]

    def next_episode(self) -> int:
        with _lock:
            state = self.state()
            state["episodes"] = int(state["episodes"]) + 1
            self._write("state.json", state)
            return state["episodes"]


def summary(store: BookStore) -> list[dict[str, Any]]:
    """The chapter list as the page draws it."""
    state = store.state()
    out = []
    for c in store.chapters():
        entry = state["status"].get(str(c["n"])) or {"status": "draft"}
        words = sum(len(p.split()) for p in c["paragraphs"])
        out.append({
            "n": c["n"], "title": c["title"], "part": c.get("part", ""),
            "paragraphs": len(c["paragraphs"]), "words": words,
            "minutes": max(1, round(words / 150)),
            "status": entry.get("status", "draft"),
            "status_words": STATUS_WORDS.get(entry.get("status", "draft"), "Draft"),
            "status_at": entry.get("at"),
        })
    return out
