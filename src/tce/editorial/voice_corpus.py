"""Mining how Ziv actually talks out of his own calls.

Fathom keeps every turn with a speaker email, so his speech is identifiable exactly.
His turns average 58 characters, which is conversation, not voice. The unit that
carries voice is the run: consecutive turns by him with no one interrupting, which is
him explaining something. That is what he called a mini speech.

Two thirds of a working day on calls is him operating a computer out loud - "I'll
click here, paste it here, let me refresh". That is not how he talks about ideas, and
feeding it to a writer would teach exactly the wrong register. So every run is judged
and labelled, and only the teaching ones are shown to a writer. Nothing is deleted:
a run judged `operating` keeps its reason, so changing the filter re-judges the corpus
without touching the transcripts again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from tce.editorial.dedupe import tokens

ZIV_EMAIL = "ravivziv@gmail.com"

# A run has to be long enough to carry a register. Below this it is a reply, not a
# mini speech: "yeah", "exactly", "that makes sense".
MIN_WORDS = 45
# And short enough to BE one. A 3,000-word "stretch" is a whole call whose other
# speaker the diarization dropped, so it reads as Ziv interviewing himself.
MAX_WORDS = 700
# Merged dialogue gives itself away by rhythm: "People? Yes. Okay. One real weak spot."
# Teaching runs in long sentences; a merged transcript runs in fragments.
MIN_AVG_SENTENCE_WORDS = 7.0
# Gap between his turns that still counts as one continuous stretch. Longer than this
# and someone else spoke, or he stopped and started a new thought.
MAX_GAP_S = 12.0

# Driving software out loud. Deliberately specific: "click", "paste", "refresh" are
# not words he uses when teaching, and a run full of them is screen narration.
_OPERATING = re.compile(
    r"\b("
    r"click(?:ing|ed)?|paste(?:d|ing)?|copy(?:ing)?|scroll(?:ing|ed)?|refresh(?:ing|ed)?|"
    r"tab|browser|screen ?share|sharing my screen|zoom in|zoom out|"
    r"log ?in|logged in|password|dashboard|button|dropdown|checkbox|"
    r"loading|spinner|reload|sidebar|menu|toolbar|url|link here|"
    r"terminal|localhost|deploy(?:ing|ed)?|commit(?:ting|ted)?|repo|pull request"
    r")\b",
    re.IGNORECASE,
)
# Live demo narration. Low software-word density, unmistakably a screen being shown.
_DEMO = re.compile(
    r"\b(still loading|here it is|there it is|you can see here|as you can see here|"
    r"on the (?:right|left|top|bottom) (?:side|here)|i'?m logging in|"
    r"let'?s see what happens|watch what happens|wait for it|it'?s loading)\b",
    re.IGNORECASE,
)
# "let me", "I'm going to", "hold on" - the narration of an action in progress.
_NARRATION = re.compile(
    r"\b(let me (?:just )?(?:show|check|see|look|open|try|find|pull)|"
    r"i'?m going to (?:click|open|show|paste|run|type)|"
    r"hold on|one second|one sec|give me a second|bear with me|"
    r"can you see my screen|do you see (?:this|that|it))\b",
    re.IGNORECASE,
)
# Density above which the run is narration rather than an aside inside a lesson.
_OPERATING_PER_100_WORDS = 3.5

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Unicode-aware: an ASCII-only pattern counts every Hebrew run as zero words, which
# labels it "thin" (a short reply) when the true reason is the language.
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass
class Run:
    """Consecutive turns by one speaker, as one piece of speech."""

    source_id: uuid.UUID
    source_title: str | None
    occurred_at: Any
    first_turn_index: int
    turn_count: int
    start_s: float | None
    end_s: float | None
    language: str
    text: str
    kind: str = "teaching"
    kind_reason: str | None = None
    keywords: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(_WORD.findall(self.text))

    @property
    def opening(self) -> str:
        """The first sentence: the bank his openings are drawn from."""
        parts = _SENTENCE_END.split(self.text.strip(), maxsplit=1)
        first = (parts[0] if parts else "").strip()
        return first[:400]


def build_runs(
    turns: list[dict[str, Any]],
    *,
    source_id: uuid.UUID,
    source_title: str | None = None,
    occurred_at: Any = None,
    email: str = ZIV_EMAIL,
    max_gap_s: float = MAX_GAP_S,
) -> list[Run]:
    """Group one call's turns into his uninterrupted stretches of speech."""
    runs: list[Run] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(str(t.get("text") or "").strip() for t in current).strip()
        text = clean_text(text)
        if text:
            langs = {str(t.get("language") or "") for t in current}
            runs.append(
                Run(
                    source_id=source_id,
                    source_title=source_title,
                    occurred_at=occurred_at,
                    first_turn_index=int(current[0].get("index") or 0),
                    turn_count=len(current),
                    start_s=_as_float(current[0].get("start_s")),
                    end_s=_as_float(current[-1].get("end_s")),
                    # A run that changes language mid-way is mixed, and mixed speech
                    # teaches the wrong sentence shape for an English script.
                    language=langs.pop() if len(langs) == 1 else "mixed",
                    text=text,
                )
            )
        current.clear()

    for turn in sorted(turns, key=lambda t: int(t.get("index") or 0)):
        mine = str(turn.get("speaker_email") or "").lower() == email.lower()
        if not mine:
            flush()
            continue
        if current:
            gap = _gap(current[-1], turn)
            if gap is not None and gap > max_gap_s:
                flush()
        current.append(turn)
    flush()
    return runs


# Speech artefacts, not voice. A transcript is thick with them and they teach a writer
# nothing except to imitate hesitation. Removed conservatively: only standalone filler
# tokens and an immediately repeated word, never anything that carries meaning.
_FILLER = re.compile(
    r"(?<!\w)(?:u[mh]+|e[rh]+|mm+|hmm+|uh-huh|you know,)(?!\w)[,.]?", re.IGNORECASE
)
_STUTTER = re.compile(r"\b(\w+)(?:[ ,]+\1\b)+", re.IGNORECASE)


def clean_text(text: str) -> str:
    """The same words with the hesitation taken out."""
    out = _FILLER.sub(" ", text or "")
    out = _STUTTER.sub(r"\1", out)
    out = re.sub(r"\s+([,.!?])", r"\1", out)
    out = re.sub(r"([,.!?])\1+", r"\1", out)
    out = re.sub(r"\s+", " ", out).strip()
    # A sentence that now starts with a comma lost its filler; tidy the seam.
    return re.sub(r"(?<=[.!?]) *, *", " ", out)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gap(previous: dict[str, Any], turn: dict[str, Any]) -> float | None:
    end, start = _as_float(previous.get("end_s")), _as_float(turn.get("start_s"))
    if end is None or start is None:
        return None
    return start - end


def judge(run: Run, *, min_words: int = MIN_WORDS) -> tuple[str, str]:
    """(kind, reason). Only "teaching" runs are ever shown to a writer."""
    # Language first: it is decisive, and judging length first would report a Hebrew
    # stretch as "a short reply" when the real reason is that it is not English.
    if run.language != "en":
        # His content is in English. Hebrew speech carries his stories and his
        # thinking, and the wrong sentence shape for an English script.
        return "other_language", f"language {run.language}"
    words = run.word_count
    if words < min_words:
        return "thin", f"{words} words: a reply, not a stretch of speech"
    if words > MAX_WORDS:
        return "merged", f"{words} words: a call segment, not one stretch of speech"
    average = words / max(len(_SENTENCE_END.split(run.text)), 1)
    if average < MIN_AVG_SENTENCE_WORDS:
        return "merged", f"{average:.1f} words per sentence: reads as merged dialogue"
    narration = _NARRATION.search(run.text) or _DEMO.search(run.text)
    if narration:
        return "operating", f"narrating an action: '{narration.group(0)}'"
    hits = _OPERATING.findall(run.text)
    density = len(hits) * 100.0 / max(words, 1)
    if density >= _OPERATING_PER_100_WORDS:
        return "operating", f"{len(hits)} software words in {words}: driving a screen"
    return "teaching", f"{words} words, {len(hits)} software words"


def prepare(runs: list[Run], *, min_words: int = MIN_WORDS) -> list[Run]:
    """Judge and tag every run in place, returning the same list."""
    for run in runs:
        run.kind, run.kind_reason = judge(run, min_words=min_words)
        run.keywords = sorted(tokens(run.text))[:120] if run.kind == "teaching" else []
    return runs
