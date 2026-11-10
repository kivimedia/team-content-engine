"""The book's chapters and their state, kept as files beside the recordings.

Why files and not a table: the release path refuses a schema change, and a book is a
handful of chapters with one owner. Everything lives under
<evidence_upload_dir>/book/:

  chapters.json   [{"n", "title", "part", "paragraphs": [...]}] - the text as imported
  state.json      {"status": {"<n>": {...}}, "chars_spent": int, "episodes": int}
  audio/<sha>.mp3 one narrated paragraph, cached by its text and voice

A chapter's status is draft, in review or approved. Approve is his; the book editor
moves a chapter to in review when it hands him a rewrite.

9-Nov-2026 (T-19824), Ziv: "The focus on the book app should be to have me check the new
episodes you write in my voice based on the layout in the file". When the book editor's
own record exists (settings.book_editor_record, its chapters.json and one chNN-vM.md per
version), the Book reads it on every open instead of the one-time import: new episodes
and rewrites appear by themselves, an entry still "to_write" shows his layout lines, and
his Approve is written into that same record, so the app and the editor never disagree.
The imported manuscript stays only as the fallback when that record is absent.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = ("draft", "in_review", "approved")
STATUS_WORDS = {"draft": "Draft", "in_review": "In review", "approved": "Approved", "to_write": "Still to write"}
PART_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
_VERSION_FILE = re.compile(r"^ch(\d+)-v(\d+)\.md$", re.IGNORECASE)

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


def parse_episode_file(text: str) -> tuple[str, list[str]]:
    """One chapter file the book editor writes (chNN-vM.md): an optional HTML comment
    (its version note), the heading "Chapter <n> - <title>", then one paragraph a line.
    Returns the heading's title ("" when there is none) and the paragraphs."""
    title = ""
    paragraphs: list[str] = []
    in_comment = False
    for raw in text.splitlines():
        line = _clean(raw)
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if not line or _RULE.match(line):
            continue
        if not paragraphs and not title:
            heading = _CHAPTER.match(line) or re.match(r"^#+\s*(?:chapter\s+\d+\s*[-:.]?\s*)?(.*)$", line, re.IGNORECASE)
            if heading:
                title = heading.group(heading.lastindex or 1).strip().strip("\u201c\u201d\"").strip()
                continue
        paragraphs.append(line.lstrip("#").strip() if line.startswith("#") else line)
    return title, paragraphs


def part_label(part: Any) -> str:
    if isinstance(part, int) or (isinstance(part, str) and part.isdigit()):
        number = int(part)
        return f"Part {PART_WORDS.get(number, number)}"
    return str(part or "")


class RecordWriteError(RuntimeError):
    """His Approve could not be written into the book editor's record."""


class EditorRecord:
    """The book editor's record of the book: the one source of truth for what is written,
    which version is newest and where each episode stands."""

    def __init__(self, path: Path, written_through: int = 0):
        self.path = Path(path)
        self.dir = self.path.parent
        self.written_through = int(written_through or 0)

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _versions(self) -> dict[int, tuple[int, str]]:
        """The newest chNN-vM.md on disk for every chapter number."""
        newest: dict[int, tuple[int, str]] = {}
        try:
            names = os.listdir(self.dir)
        except OSError:
            return newest
        for name in names:
            m = _VERSION_FILE.match(name)
            if not m:
                continue
            n, v = int(m.group(1)), int(m.group(2))
            if n not in newest or v > newest[n][0]:
                newest[n] = (v, name)
        return newest

    @staticmethod
    def _status(entry: dict[str, Any], has_text: bool, version: int) -> str:
        raw = str(entry.get("status") or "draft").strip().lower().replace(" ", "_").replace("-", "_")
        if raw in ("review", "in_review", "for_review", "ready", "ready_for_review"):
            raw = "in_review"
        if not has_text:
            return "to_write"
        if raw == "to_write":
            return "draft"
        if raw == "approved":
            approved = entry.get("approved_version")
            if approved is not None and version > int(approved):
                return "in_review"  # a rewrite after his yes waits for a new look
            return "approved"
        return raw if raw in STATUSES else "draft"

    def chapters(self) -> list[dict[str, Any]]:
        data = self.load()
        entries = data.get("chapters") or []
        newest = self._versions()
        out: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                n = int(entry.get("number"))
            except (TypeError, ValueError):
                continue
            version, name = newest.get(n, (0, ""))
            listed = str(entry.get("file") or "")
            m = _VERSION_FILE.match(listed) if listed else None
            if m and int(m.group(1)) == n and int(m.group(2)) >= version and (self.dir / listed).is_file():
                version, name = int(m.group(2)), listed
            title = str(entry.get("title") or "").strip()
            paragraphs: list[str] = []
            if name:
                try:
                    heading, paragraphs = parse_episode_file((self.dir / name).read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    heading, paragraphs = "", []
                title = title or heading
            status = self._status(entry, bool(paragraphs), version)
            items = entry.get("layout_items") or []
            out.append({
                "n": n,
                "title": title or f"Chapter {n}",
                "part": part_label(entry.get("part")),
                "paragraphs": paragraphs,
                "status": status,
                "status_at": entry.get("status_at") or entry.get("approved_at") or entry.get("updated_at"),
                "version": version,
                "file": name,
                "layout_items": list(items) if isinstance(items, list) else [items],
                "layout_text": str(entry.get("layout_text") or ""),
                "group": "written" if n <= self.written_through else "new",
            })
        out.sort(key=lambda c: c["n"])
        return out

    @contextlib.contextmanager
    def _locked(self):
        handle = None
        try:
            import fcntl

            handle = open(self.dir / ".chapters.lock", "a")  # noqa: SIM115
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError:
            handle = None  # the thread lock still serializes this process
        try:
            with _lock:
                yield
        finally:
            if handle is not None:
                handle.close()

    def set_status(self, n: int, status: str, *, by: str, note: str = "", version: int = 0) -> dict[str, Any]:
        """Write his decision on one episode into the record. Only that entry's status
        fields change, read fresh under the lock, so a rewrite the editor saved a moment
        earlier is kept. The file is replaced whole (group-writable, so the editor goes
        on writing it)."""
        with self._locked():
            data = self.load()
            entries = data.get("chapters") or []
            entry = next((e for e in entries if isinstance(e, dict) and str(e.get("number")) == str(n)), None)
            if entry is None:
                raise KeyError(n)
            at = _now()
            entry["status"] = status
            entry["status_at"] = at
            entry["status_by"] = by
            if status == "approved":
                entry["approved_at"] = at
                entry["approved_version"] = int(version or entry.get("version") or 1)
            else:
                entry["approved_at"] = None
                entry.pop("approved_version", None)
            history = list(entry.get("status_history") or [])
            row = {"status": status, "at": at, "by": by, "version": int(version or 0)}
            if note:
                row["note"] = note[:2000]
            history.append(row)
            entry["status_history"] = history[-30:]
            data["updated_at"] = at
            tmp = self.dir / f".chapters.json.{os.getpid()}.tmp"
            try:
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.chmod(tmp, 0o664)
                os.replace(tmp, self.path)
            except OSError as exc:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise RecordWriteError(str(exc)) from exc
        return {"status": status, "at": at, "by": by, "history": history[-30:]}


class BookStore:
    """One book's chapters, status and narration cache, on disk. With an editor record
    that exists, the chapters and their status come from it; the narration cache, the
    spend and the episode count stay here."""

    def __init__(self, root: Path, record: EditorRecord | None = None):
        self.root = Path(root)
        self.audio_dir = self.root / "audio"
        self.record = record if record is not None and record.exists() else None

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
        if self.record is not None:
            return self.record.chapters()
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
        if self.record is not None or not source_path or self._read("chapters.json", []):
            return
        path = Path(source_path)
        if path.is_file():
            self.import_text(path.read_text(encoding="utf-8", errors="replace"), source=str(path))

    # ------------------------------------------------------------- status

    def status_of(self, n: int) -> dict[str, Any]:
        if self.record is not None:
            for c in self.record.chapters():
                if c["n"] == n:
                    entry = next((e for e in self.record.load().get("chapters") or [] if str(e.get("number")) == str(n)), {})
                    return {"status": c["status"], "at": c.get("status_at"), "history": entry.get("status_history") or []}
            return {"status": "draft"}
        return dict(self.state()["status"].get(str(n)) or {"status": "draft"})

    def set_status(self, n: int, status: str, *, by: str, note: str = "") -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}")
        if self.record is not None:
            chapter = next((c for c in self.record.chapters() if c["n"] == n), None)
            if chapter is None:
                raise KeyError(n)
            if chapter["status"] == "to_write":
                raise ValueError(f"Episode {n} is not written yet, so there is nothing to approve")
            return self.record.set_status(n, status, by=by, note=note, version=chapter["version"])
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

    # 10-Nov-2026 (T-19955): Ziv picks the reading voice from samples ("I want to use
    # version four... Needs to be a man voice"). His pick is saved here, so it needs no
    # release; until he picks, the settings' voice and model read.
    def voice(self) -> dict[str, str] | None:
        chosen = self.state().get("voice")
        if isinstance(chosen, dict) and chosen.get("voice_id"):
            return {"voice_id": str(chosen["voice_id"]), "model": str(chosen.get("model") or ""), "name": str(chosen.get("name") or "")}
        return None

    def set_voice(self, voice_id: str, model: str, *, name: str = "", by: str = "") -> dict[str, str]:
        with _lock:
            state = self.state()
            state["voice"] = {"voice_id": voice_id, "model": model, "name": name, "by": by}
            self._write("state.json", state)
        return self.voice() or {}

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
        if store.record is not None:
            entry = {"status": c["status"], "at": c.get("status_at")}
        else:
            entry = state["status"].get(str(c["n"])) or {"status": "draft"}
        words = sum(len(p.split()) for p in c["paragraphs"])
        s = entry.get("status", "draft")
        out.append({
            "n": c["n"], "title": c["title"], "part": c.get("part", ""),
            "paragraphs": len(c["paragraphs"]), "words": words,
            "minutes": max(1, round(words / 150)) if words else 0,
            "status": s,
            "status_words": STATUS_WORDS.get(s, "Draft"),
            "status_at": entry.get("at"),
            "version": c.get("version", 0),
            "layout_items": c.get("layout_items", []),
            "layout_text": c.get("layout_text", ""),
            "group": c.get("group", "written"),
        })
    return out
