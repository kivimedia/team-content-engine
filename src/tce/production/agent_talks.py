"""Agent talks (3-Oct, contract C4): a filmed voice call with an agent becomes a video.

"One more click": on any agent's voice call page he taps record, and a selfie video of
the conversation (his camera, his microphone and the agent's voice from the call) goes
to TCE in pieces while the call runs. When the call ends the pieces are joined into one
file, the file lands in the library as an "Agent talk" titled "Talk with <Agent>,
<date>", and it edits itself like a finished walk.

This module is the part with no database: where the pieces live, joining them into one
file without re-encoding, naming the talk, and telling the two voices apart.

The pieces. MediaRecorder hands out one continuous stream cut into slices: the first
slice carries the header (WebM's EBML header and tracks, or a fragmented MP4's ftyp and
moov), every later slice continues it. Their bytes in order ARE the recording, so the
join is a byte concatenation followed by a remux (`-c copy`): the remux writes the
duration and seek index the recorder never could, and the pixels and samples are never
encoded again. The first lossy encode after the phone is the edit's own render.

The two voices. A talk has two people in it, and the edit must never cut the agent's
lines as retakes, asides or junk. The recogniser hears both voices as one list of words;
the call's own transcript says who said what. `voices` lines the two up by their words
(the agent's synthetic voice is transcribed almost word for word), maps the call's
clock onto the recording's for the words in between, and returns which transcript words
are the agent's.
"""

from __future__ import annotations

import asyncio
import bisect
import hashlib
import os
import re
import shutil
import statistics
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tce.production.media import ffmpeg_path, probe_media

SOURCE = "agent_talk"
SOURCE_LABEL = "Agent talk"
TIMEZONE = "Asia/Jerusalem"  # his clock, for the date in a talk's title

# One MediaRecorder slice. A few seconds of the best selfie a phone records is a few MB;
# this only stops something that is not a slice.
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MAX_SEQUENCE = 1_000_000
# The disk the pieces land on is shared with the database and every other service on
# the box. A talk never takes it below this much free space: a piece that would is
# refused (507) and the relay keeps it to send again; a join that would is refused
# before it writes anything, and the pieces stay (3-Oct review).
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
# How many missing sequence numbers a talk's record keeps (the count is always kept).
MAX_MISSING_KEPT = 200


def free_bytes(path: Path) -> int:
    """Free space on the disk that holds `path` (or its nearest existing parent)."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _gb(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GB"

# The recorder's type -> the container its pieces make.
CONTAINERS = {
    "video/webm": "webm",
    "audio/webm": "webm",
    "video/mp4": "mp4",
    "audio/mp4": "mp4",
    "video/x-matroska": "mkv",
}
# Containers tried for the remux, best first: one the phone's player plays, then one
# ffmpeg reads whatever the codecs are. A recording without a picture goes to a sound
# container, so the edit renders it on the audio canvas.
_REMUX_ORDER = {
    "webm": ("webm", "mp4", "mkv"),
    "mp4": ("mp4", "mkv"),
    "mkv": ("mkv", "mp4"),
}
_SOUND_ORDER = ("ogg", "m4a")
_MUX_OPTIONS = {"mp4": ["-movflags", "+faststart"], "m4a": ["-movflags", "+faststart"]}

HOST = "host"  # his lines ("ziv" in the call's transcript)
AGENT = "agent"
# The words a talk's name keeps in capitals ("ai-news" is "AI News").
_ACRONYMS = frozenset({"ai", "bdr", "ceo", "cto", "km", "qa", "tce", "ui", "ux"})


class TalkError(ValueError):
    """A request about a talk that cannot be done; `status` is the HTTP answer."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Naming


def container_for(mime: str) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    container = CONTAINERS.get(base)
    if container is None:
        raise TalkError(
            f"Unsupported recording type {mime or 'unknown'}: send video/webm or video/mp4",
            status=415,
        )
    return container


def display_name(agent: str) -> str:
    """The agent as the library names it: "atlas" is "Atlas", "ai-news" is "AI News". A
    name that already has capitals is kept as it came."""
    raw = " ".join(str(agent or "").split()).strip()
    if not raw:
        return "the agent"
    if any(ch.isupper() for ch in raw):
        return raw[:80]
    parts = [p for p in re.split(r"[\s_\-]+", raw) if p]
    return " ".join(p.upper() if p in _ACRONYMS else p[:1].upper() + p[1:] for p in parts)[:80]


def local_time(moment: datetime) -> datetime:
    """A naive UTC instant on his clock."""
    return moment.replace(tzinfo=UTC).astimezone(ZoneInfo(TIMEZONE))


def talk_title(agent: str, started_at: datetime) -> str:
    """ "Talk with Atlas, 3 Oct": the agent and the day, on his clock."""
    local = local_time(started_at)
    return f"Talk with {display_name(agent)}, {local.day} {local:%b}"


def week_label(started_at: datetime) -> datetime:
    """The Monday of the talk's week, as topic rows keep it (a naive calendar label)."""
    day: date = local_time(started_at).date()
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day)


def parse_instant(value: str | None) -> datetime | None:
    """An ISO time from the call ("2026-10-03T14:52:07.120Z") as naive UTC."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TalkError(f"Not a time: {value!r}", status=400) from exc
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


# ---------------------------------------------------------------------------
# The pieces on disk


def talk_folder(root: Path, workspace_id: uuid.UUID, talk_id: uuid.UUID) -> Path:
    return Path(root) / "agent-talks" / str(workspace_id) / str(talk_id)


def _pieces_dir(folder: Path) -> Path:
    return folder / "pieces"


def _piece_path(folder: Path, sequence: int) -> Path:
    return _pieces_dir(folder) / f"{sequence:07d}.part"


def pieces(folder: Path) -> list[tuple[int, Path]]:
    """Every piece that arrived, by sequence number."""
    out: list[tuple[int, Path]] = []
    directory = _pieces_dir(folder)
    if not directory.exists():
        return out
    for path in directory.glob("*.part"):
        try:
            out.append((int(path.stem), path))
        except ValueError:
            continue
    return sorted(out)


def received(folder: Path) -> tuple[int, int]:
    """(pieces, bytes) that arrived so far."""
    items = pieces(folder)
    total = 0
    for _seq, path in items:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return len(items), total


@dataclass
class Stored:
    created: bool
    pieces: int
    bytes_total: int


def store_piece(folder: Path, sequence: int, data: bytes) -> Stored:
    """Keep one piece. The same piece sent again (a retry) changes nothing; a different
    piece under a number that already arrived is refused, so two recordings can never be
    spliced into one file."""
    if sequence < 0 or sequence > MAX_SEQUENCE:
        raise TalkError(f"Piece number {sequence} is outside 0 to {MAX_SEQUENCE}", status=400)
    if not data:
        raise TalkError("The piece was empty", status=400)
    if len(data) > MAX_CHUNK_BYTES:
        raise TalkError(
            f"The piece is larger than {MAX_CHUNK_BYTES // (1024 * 1024)} MB", status=413
        )
    path = _piece_path(folder, sequence)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if path.exists():
        old = path.read_bytes()
        if len(old) != len(data) or hashlib.sha256(old).digest() != hashlib.sha256(data).digest():
            raise TalkError(
                f"Piece {sequence} already arrived with different bytes; a new recording "
                "needs a new talk",
                status=409,
            )
    else:
        free = free_bytes(path.parent)
        if free - len(data) < MIN_FREE_BYTES:
            raise TalkError(
                f"The server's disk is nearly full ({_gb(free)} free), so piece {sequence} was not "
                "kept. Send it again once space is freed.",
                status=507,
            )
        # Written aside and renamed: a crash never leaves half a piece under its number.
        part = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        part.write_bytes(data)
        os.replace(part, path)
        created = True
    count, total = received(folder)
    return Stored(created=created, pieces=count, bytes_total=total)


# ---------------------------------------------------------------------------
# The join


@dataclass
class Joined:
    path: Path
    container: str
    proof: dict[str, Any]
    pieces: int
    bytes: int
    missing: list[int] = field(default_factory=list)  # the first MAX_MISSING_KEPT
    missing_count: int = 0


Prober = Callable[[str | Path], Awaitable[dict[str, Any]]]


async def _audio_decodes(exe: str, path: Path) -> bool:
    """"Has an audio track" is not "the sound plays": the sound must decode end to end."""
    proc = await asyncio.create_subprocess_exec(
        exe, "-v", "error", "-i", str(path), "-map", "0:a", "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await proc.communicate()
    return proc.returncode == 0 and not err.strip()


async def _remux(
    exe: str, raw: Path, folder: Path, order: tuple[str, ...], want_video: bool, prober: Prober
) -> tuple[Path, str, dict[str, Any]]:
    """Rewrap the joined stream (no re-encode) into the first container that holds it
    and plays: picture first, then sound (24-Sep: a join that took tracks by position
    filled the sound with picture)."""
    tried: list[str] = []
    for container in order:
        out = folder / f"talk.{container}"
        out.unlink(missing_ok=True)
        args = [
            exe, "-y", "-v", "error", "-fflags", "+genpts", "-i", str(raw),
            "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
            *_MUX_OPTIONS.get(container, []), str(out),
        ]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _out, err = await proc.communicate()
        if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            first = (err.decode("utf-8", "replace").strip().splitlines() or ["no output"])[0]
            tried.append(f"{container}: {first[:160]}")
            out.unlink(missing_ok=True)
            continue
        try:
            proof = await prober(out)
        except Exception as exc:  # noqa: BLE001 - one container failing is not the end
            tried.append(f"{container}: unreadable ({str(exc)[:120]})")
            out.unlink(missing_ok=True)
            continue
        if not proof.get("has_audio"):
            tried.append(f"{container}: no sound")
        elif want_video and not proof.get("has_video"):
            tried.append(f"{container}: no picture")
        elif not await _audio_decodes(exe, out):
            tried.append(f"{container}: the sound does not decode")
        else:
            return out, container, proof
        out.unlink(missing_ok=True)
    raise TalkError(
        "The pieces could not be joined into a video that plays (" + "; ".join(tried) + ")",
        status=422,
    )


def _concatenate(paths: list[Path], target: Path) -> int:
    total = 0
    with target.open("wb") as out:
        for path in paths:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    total += len(block)
                    out.write(block)
    return total


async def join(folder: Path, extension: str, *, prober: Prober = probe_media) -> Joined:
    """Join every piece that arrived into one file, remuxed, never re-encoded.

    Piece 0 carries the stream's header, so it must be there. A piece missing further on
    (it never arrived) leaves a skip in the video; the join goes ahead without it and
    says which numbers were missing. On success the pieces and the raw join are removed
    (the joined file holds every byte of them); on failure they stay for another try.
    """
    exe = ffmpeg_path()
    if not exe:
        raise TalkError("ffmpeg is not installed on this server", status=503)
    items = pieces(folder)
    if not items:
        # A finish that joined the pieces and then stopped (a restart before the video's
        # row was written) left the joined file: that file is the talk.
        for container in (*_REMUX_ORDER, *_SOUND_ORDER):
            done = folder / f"talk.{container}"
            if done.exists() and done.stat().st_size:
                proof = await prober(done)
                if proof.get("has_audio"):
                    return Joined(path=done, container=container, proof=proof, pieces=0,
                                  bytes=done.stat().st_size)
        raise TalkError("No piece of this talk arrived, so there is nothing to join", status=409)
    numbers = [n for n, _ in items]
    if numbers[0] != 0:
        raise TalkError(
            "Piece 0 never arrived. It carries the start of the recording, so the video "
            "cannot be made without it",
            status=409,
        )
    missing, missing_count = _missing(numbers)
    # The join writes the pieces once more (the raw join) and once again (the remux)
    # before it removes them: room for both, over the floor, or nothing is written.
    size = sum(path.stat().st_size for _n, path in items)
    free = free_bytes(folder)
    if free - 2 * size < MIN_FREE_BYTES:
        raise TalkError(
            f"The server's disk is nearly full ({_gb(free)} free; joining this talk needs "
            f"{_gb(2 * size)} more), so it was not joined yet. The pieces are kept; finish it "
            "again once space is freed.",
            status=507,
        )
    raw = folder / f"talk.raw.{extension}"
    # A long talk is gigabytes: written off the event loop, so the server keeps answering.
    total = await asyncio.to_thread(_concatenate, [path for _n, path in items], raw)
    try:
        raw_proof = await prober(raw)
    except Exception:  # noqa: BLE001 - the remux below says what is wrong
        raw_proof = {}
    want_video = bool(raw_proof.get("has_video", True))
    order = _REMUX_ORDER.get(extension, (extension,)) if want_video else _SOUND_ORDER
    out, container, proof = await _remux(exe, raw, folder, order, want_video, prober)
    raw.unlink(missing_ok=True)
    for _n, path in items:
        path.unlink(missing_ok=True)
    try:
        _pieces_dir(folder).rmdir()
    except OSError:
        pass  # a piece that arrived meanwhile stays where it is
    return Joined(path=out, container=container, proof=proof, pieces=len(items), bytes=total,
                  missing=missing, missing_count=missing_count)


def _missing(numbers: list[int]) -> tuple[list[int], int]:
    """The sequence numbers that never arrived, from the sorted numbers that did: the
    first MAX_MISSING_KEPT of them and how many in all. Counted gap by gap, so a number
    far out (up to MAX_SEQUENCE) never builds a list of a million (3-Oct review)."""
    kept: list[int] = []
    count = 0
    prev = -1
    for n in numbers:
        if n > prev + 1:
            count += n - prev - 1
            room = MAX_MISSING_KEPT - len(kept)
            if room > 0:
                kept.extend(range(prev + 1, min(n, prev + 1 + room)))
        prev = n
    return kept, count


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The two voices

_TOKEN = re.compile(r"[\w']+", re.UNICODE)
SECONDS_PER_TOKEN = 0.35  # a word's place in its line, as time, when only a later word matched
SAME_BREATH_S = 0.35  # a gap this short between two words is one voice speaking on


def _tokens(text: str) -> list[str]:
    return [t.replace("'", "") for t in _TOKEN.findall(str(text or "").lower()) if t.strip("'")]


def call_lines(transcript: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The call's lines that say who and what: {"who": host|agent, "text", "t_s"}."""
    out: list[dict[str, Any]] = []
    for line in transcript or []:
        if not isinstance(line, dict):
            continue
        who = str(line.get("who") or "").strip().lower()
        text = str(line.get("text") or "").strip()
        if not text or who not in ("ziv", "agent", "host"):
            continue
        t_ms = line.get("t_ms")
        try:
            t_s = float(t_ms) / 1000.0 if t_ms is not None else None
        except (TypeError, ValueError):
            t_s = None
        out.append({"who": AGENT if who == "agent" else HOST, "text": text, "t_s": t_s})
    return out


@dataclass(frozen=True)
class Voices:
    """Who said each transcript word of an agent talk."""

    agent: str  # the agent as the library names it
    labels: dict[int, str]  # transcript index -> HOST | AGENT
    agent_words: frozenset[int]
    known: bool  # False: the call's transcript did not line up, so every word is kept
    matched: int = 0  # words the call's transcript confirmed by their text
    offset_s: float | None = None  # recording clock minus the call's clock

    def speaker_names(self) -> dict[int, str]:
        """Labels for a prompt: the host as HOST, the agent by name in capitals."""
        name = self.agent.upper()
        return {i: (name if who == AGENT else "HOST") for i, who in self.labels.items()}


def voices(
    words: list[dict[str, Any]], transcript: list[dict[str, Any]] | None, agent: str
) -> Voices:
    """Which recogniser words are the agent's.

    1. Line the words up with the call's lines by their text (the agent's synthetic voice
       is heard almost word for word, his own lines closely). Each matched word takes
       the speaker of the line it matched.
    2. The call's clock against the recording's: the median gap between a line's time
       and its first matched word. That places on the recording an agent line whose
       words were all misheard, and its words are the agent's.
    3. A word the text did not settle takes the voice on both sides of it when they
       agree. Between the two voices it is his, unless it runs on from the agent's
       speech without a breath: the agent's every word is in the call's transcript, his
       talk to the dogs may not be.

    No line that says who, or no word matched at all: the voices cannot be told apart,
    and every word is the agent's to keep (only the pauses are cut).
    """
    name = display_name(agent)
    lines = call_lines(transcript)
    n = len(words)
    if not lines or not n:
        return Voices(agent=name, labels={i: AGENT for i in range(n)},
                      agent_words=frozenset(range(n)), known=False)

    heard: list[tuple[str, int]] = []
    for i, w in enumerate(words):
        if w.get("sound"):
            continue
        for tok in _tokens(w.get("text", "")):
            heard.append((tok, i))
    said: list[tuple[str, int, int]] = []  # token, line, position in the line
    for k, line in enumerate(lines):
        for pos, tok in enumerate(_tokens(line["text"])):
            said.append((tok, k, pos))

    votes: dict[int, dict[str, int]] = {}
    first_match: dict[int, tuple[int, int]] = {}  # line -> (position, word index)
    matcher = SequenceMatcher(None, [t for t, _ in heard], [t for t, _, _ in said])
    for a, b, size in matcher.get_matching_blocks():
        for j in range(size):
            word = heard[a + j][1]
            _tok, k, pos = said[b + j]
            who = lines[k]["who"]
            votes.setdefault(word, {}).setdefault(who, 0)
            votes[word][who] += 1
            if k not in first_match or pos < first_match[k][0]:
                first_match[k] = (pos, word)
    labels: dict[int, str] = {}
    for word, tally in votes.items():
        labels[word] = AGENT if tally.get(AGENT, 0) >= tally.get(HOST, 0) else HOST
    matched = len(labels)
    if not matched:
        return Voices(agent=name, labels={i: AGENT for i in range(n)},
                      agent_words=frozenset(range(n)), known=False)

    gaps = [
        float(words[word]["start_s"]) - (lines[k]["t_s"] + pos * SECONDS_PER_TOKEN)
        for k, (pos, word) in first_match.items()
        if lines[k]["t_s"] is not None
    ]
    offset = statistics.median(gaps) if gaps else None

    # An agent line the text never found (the recogniser garbled all of it): where the
    # call's clock puts it on the recording.
    lost: list[tuple[float, float]] = []
    if offset is not None:
        for k, line in enumerate(lines):
            if line["who"] == AGENT and k not in first_match and line["t_s"] is not None:
                start = line["t_s"] + offset
                length = max(1.0, len(_tokens(line["text"])) * SECONDS_PER_TOKEN)
                lost.append((start - 0.25, start + length + 0.25))

    def close(a: int, b: int) -> bool:
        """Word a ends and word b starts within one breath: the same voice speaking on."""
        return float(words[b]["start_s"]) - float(words[a]["end_s"]) <= SAME_BREATH_S

    settled = sorted(labels)
    for i in range(n):
        if i in labels:
            continue
        mid = (float(words[i]["start_s"]) + float(words[i]["end_s"])) / 2
        if any(a <= mid <= b for a, b in lost):
            labels[i] = AGENT
            continue
        at = bisect.bisect_left(settled, i)
        before = settled[at - 1] if at > 0 else None
        after = settled[at] if at < len(settled) else None
        if before is not None and after is not None and labels[before] == labels[after]:
            labels[i] = labels[before]  # inside one voice's speech: a word the call wrote otherwise
            continue
        # Between the two voices, or at either end. Every word the agent said is in the
        # call's transcript, so a word it did not confirm is his, unless it runs on from
        # the agent's speech without a breath (a word of the agent's the recogniser misheard).
        agent_on = (before is not None and labels[before] == AGENT and close(before, i)) or (
            after is not None and labels[after] == AGENT and close(i, after)
        )
        labels[i] = AGENT if agent_on else HOST
    agent_words = frozenset(i for i, who in labels.items() if who == AGENT)
    return Voices(agent=name, labels=labels, agent_words=agent_words, known=True,
                  matched=matched, offset_s=round(offset, 3) if offset is not None else None)
