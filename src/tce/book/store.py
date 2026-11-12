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

12-Nov-2026 (T-20758), Ziv on a call: he agrees each new chapter's layout before any of
it is written or read to him, the way TCE goes big idea, then script, then workshop. So a
new chapter (one past written_through) moves through phases:

  layout              Layout to approve: the big idea, what it covers, one question
  on_hold             Drafted earlier, on hold: text exists from before the rule
  approved_unwritten  Layout approved, not written: Write this chapter waits for his word
  ready               Ready to listen
  approved            Approved

and its text is READABLE only when the layout is approved and the current version was
written after that approval (a version newer than the one on disk when he approved) or
the editor confirmed that version against the approved layout. A chapter that is not
readable sends no paragraphs and no audio from the API, whatever the page asks.

The record fields, per entry (the editor's names; the app writes only the ones marked *):
  layout {big_idea, covers[], question, version}   the layout (else the seed file's)
  layout_status        to_plan | proposed | approved *
  layout_approved_at / _by / _version *, layout_approved_draft_version *
  layout_notes [{at, by, text}] *, layout_history [...] *
  write_requested_at / _by *
  draft_confirmed_version, draft_confirmed_layout_version   the editor's confirm
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
PHASE_WORDS = {
    "layout": "Layout to approve",
    "on_hold": "Drafted earlier, on hold",
    "approved_unwritten": "Layout approved, not written",
    "ready": "Ready to listen",
    "approved": "Approved",
}
LAYOUT_STATUSES = ("to_plan", "proposed", "approved")
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

    def __init__(self, path: Path, written_through: int = 0, seed: Path | str | None = None):
        self.path = Path(path)
        self.dir = self.path.parent
        self.written_through = int(written_through or 0)
        self.seed = Path(seed) if seed else None

    def _seed(self) -> dict[int, dict[str, Any]]:
        """The layouts drawn up before the record carried its own, by chapter number."""
        if self.seed is None:
            return {}
        try:
            data = json.loads(self.seed.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rows = data.get("chapters") if isinstance(data, dict) else data
        out: dict[int, dict[str, Any]] = {}
        for row in rows or []:
            if isinstance(row, dict):
                with contextlib.suppress(TypeError, ValueError):
                    out[int(row.get("number"))] = row
        return out

    @staticmethod
    def _layout_of(entry: dict[str, Any], seed: dict[str, Any] | None) -> dict[str, Any] | None:
        """The chapter's layout: the record's own when it has one, else the seed's."""
        own = entry.get("layout")
        if isinstance(own, dict) and (own.get("big_idea") or own.get("covers")):
            src, where = own, "record"
        elif seed and (seed.get("big_idea") or seed.get("covers")):
            src, where = seed, "seed"
        else:
            return None
        covers = src.get("covers") or []
        return {
            "big_idea": str(src.get("big_idea") or "").strip(),
            "covers": [str(x).strip() for x in (covers if isinstance(covers, list) else [covers]) if str(x).strip()],
            "question": str(src.get("question") or src.get("question_for_ziv") or "").strip(),
            "version": int(src.get("version") or 1),
            "from": where,
        }

    def _phase(self, n: int, entry: dict[str, Any], seed: dict[str, Any] | None, version: int, has_text: bool,
               status: str) -> dict[str, Any]:
        """Where a chapter stands in layout, write, listen, and whether its text may be shown."""
        if n <= self.written_through:
            return {"phased": False, "readable": True, "phase": "", "phase_words": ""}
        layout = self._layout_of(entry, seed)
        raw = str(entry.get("layout_status") or (seed or {}).get("layout_status") or "").strip().lower()
        if raw not in LAYOUT_STATUSES:
            raw = "proposed" if layout else "to_plan"
        if layout is None:
            raw = "to_plan"
        approved_version = entry.get("layout_approved_version")
        if raw == "approved" and layout and approved_version is not None and layout["version"] > int(approved_version):
            raw = "proposed"  # the editor redrew the layout after his yes: it needs a new look
        approved = raw == "approved"
        readable = False
        if approved and has_text:
            before = int(entry.get("layout_approved_draft_version") or 0)
            confirmed = entry.get("draft_confirmed_version")
            confirmed_against = entry.get("draft_confirmed_layout_version")
            readable = version > before or (
                confirmed is not None and int(confirmed) == version
                and (confirmed_against is None or approved_version is None or int(confirmed_against) == int(approved_version))
            )
        if readable:
            phase = "approved" if status == "approved" else "ready"
        elif approved:
            phase = "approved_unwritten"
        else:
            phase = "on_hold" if has_text else "layout"
        notes = entry.get("layout_notes") or []
        return {
            "phased": True,
            "readable": readable,
            "phase": phase,
            "phase_words": PHASE_WORDS[phase],
            "layout": layout,
            "layout_status": raw,
            "layout_approved_at": entry.get("layout_approved_at") if approved else None,
            "layout_approved_by": entry.get("layout_approved_by") if approved else None,
            "layout_notes": [x for x in notes if isinstance(x, dict)][-30:],
            "write_requested_at": entry.get("write_requested_at") if approved else None,
            "outline": str(entry.get("layout_text") or (seed or {}).get("his_outline") or ""),
        }

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
        seeds = self._seed()
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
            phase = self._phase(n, entry, seeds.get(n), version, bool(paragraphs), status)
            out.append({
                **phase,
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
            self._save(data)
        return {"status": status, "at": at, "by": by, "history": history[-30:]}

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.dir / f".chapters.json.{os.getpid()}.tmp"
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.chmod(tmp, 0o664)
            os.replace(tmp, self.path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise RecordWriteError(str(exc)) from exc

    def _change(self, n: int, work) -> dict[str, Any]:
        """Change one entry, read fresh under the lock; work(entry, now) returns the answer."""
        with self._locked():
            data = self.load()
            entries = data.get("chapters") or []
            entry = next((e for e in entries if isinstance(e, dict) and str(e.get("number")) == str(n)), None)
            if entry is None:
                raise KeyError(n)
            at = _now()
            out = work(entry, at)
            data["updated_at"] = at
            self._save(data)
        return out

    # 12-Nov-2026 (T-20758): his word on a layout, his notes on it, and his ask to write.

    def layout_decision(self, n: int, approve: bool, *, by: str) -> dict[str, Any]:
        current = next((c for c in self.chapters() if c["n"] == n), None)
        if current is None:
            raise KeyError(n)
        if not current.get("phased"):
            raise ValueError(f"Chapter {n} is one you wrote yourself, so it has no layout to approve")
        layout = current.get("layout")
        if approve and not layout:
            raise ValueError(f"Episode {n} has no layout drawn up yet, so there is nothing to approve")

        def work(entry: dict[str, Any], at: str) -> dict[str, Any]:
            history = list(entry.get("layout_history") or [])
            if approve:
                if not (isinstance(entry.get("layout"), dict) and entry["layout"].get("big_idea")):
                    # Pin exactly what he approved into the record, so a later seed cannot change it.
                    entry["layout"] = {k: layout[k] for k in ("big_idea", "covers", "question", "version")}
                entry["layout_status"] = "approved"
                entry["layout_approved_at"] = at
                entry["layout_approved_by"] = by
                entry["layout_approved_version"] = int(layout["version"])
                entry["layout_approved_draft_version"] = int(current.get("version") or 0)
            else:
                entry["layout_status"] = "proposed"
                for key in ("layout_approved_at", "layout_approved_by", "layout_approved_version",
                            "layout_approved_draft_version", "write_requested_at", "write_requested_by"):
                    entry.pop(key, None)
            history.append({"layout": "approved" if approve else "reopened", "at": at, "by": by,
                            "layout_version": int((layout or {}).get("version") or 0), "draft_version": int(current.get("version") or 0)})
            entry["layout_history"] = history[-30:]
            return {"layout_status": entry["layout_status"], "at": at, "by": by}

        return self._change(n, work)

    def add_layout_note(self, n: int, text: str, *, by: str) -> dict[str, Any]:
        def work(entry: dict[str, Any], at: str) -> dict[str, Any]:
            note = {"at": at, "by": by, "text": text[:2000]}
            entry["layout_notes"] = ([x for x in entry.get("layout_notes") or [] if isinstance(x, dict)] + [note])[-60:]
            return note

        return self._change(n, work)

    def request_write(self, n: int, *, by: str) -> dict[str, Any]:
        current = next((c for c in self.chapters() if c["n"] == n), None)
        if current is None:
            raise KeyError(n)
        if not current.get("phased") or current.get("layout_status") != "approved":
            raise ValueError(f"Episode {n} can be written only after you approve its layout")
        if current.get("readable"):
            raise ValueError(f"Episode {n} is already written from its approved layout")

        def work(entry: dict[str, Any], at: str) -> dict[str, Any]:
            if entry.get("write_requested_at"):
                return {"write_requested_at": entry["write_requested_at"], "already": True}
            entry["write_requested_at"] = at
            entry["write_requested_by"] = by
            return {"write_requested_at": at, "already": False}

        return self._change(n, work)


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
            if not chapter.get("readable", True):
                raise ValueError(f"Episode {n} is held until its layout is approved and it is written from it")
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
        readable = c.get("readable", True)
        words = sum(len(p.split()) for p in c["paragraphs"]) if readable else 0
        s = entry.get("status", "draft")
        out.append({
            "phased": c.get("phased", False),
            "readable": readable,
            "phase": c.get("phase", ""),
            "phase_words": c.get("phase_words", ""),
            "big_idea": (c.get("layout") or {}).get("big_idea", ""),
            "layout_status": c.get("layout_status", ""),
            "write_requested_at": c.get("write_requested_at"),
            "n": c["n"], "title": c["title"], "part": c.get("part", ""),
            "paragraphs": len(c["paragraphs"]) if readable else 0, "words": words,
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
