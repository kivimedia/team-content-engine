"""Which stretches of a cut get a new background.

A cut is a list of kept ranges of the raw recording, played back to back. A scene is a run of
kept ranges that ends where a sentence ends, so the place behind the speaker never changes in
the middle of a thought. Every other scene keeps its real background; the opening always does.

Pure functions, no I/O: the same plan comes out for the same cut, so a re-render asks for the
same scenes and the cache answers instead of the paid model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The model edits at most 15 s of video per call; half a second of room.
MAX_SCENE_S = 14.5
# Shorter than this and a change of place reads as a glitch, not as a new spot.
MIN_SCENE_S = 4.0
# A line this short after a scene's last sentence is its punchline: it stays in the scene.
TAIL_LINE_S = 1.6
# A scene mostly hidden under a full-screen card is not worth paying for.
HIDDEN_SHARE = 0.5

_SENTENCE_END = (".", "?", "!")
_CLOSERS = "\"')]}”’"


@dataclass
class Scene:
    index: int
    keeps: list[int]  # indexes into the keep list
    start_s: float  # on the cut timeline
    end_s: float
    swap: bool = False
    look: str | None = None
    hidden_share: float = 0.0
    reason: str = ""
    text: str = field(default="", repr=False)

    @property
    def length_s(self) -> float:
        return self.end_s - self.start_s


def cut_offsets(keep: list[list[float]]) -> list[tuple[float, float]]:
    """Where each kept range sits on the cut timeline."""
    out, t = [], 0.0
    for a, b in keep:
        d = max(0.0, float(b) - float(a))
        out.append((t, t + d))
        t += d
    return out


def _ends_sentence(text: str) -> bool:
    return text.strip().rstrip(_CLOSERS).endswith(_SENTENCE_END)


def sentence_end_after(keep: list[list[float]], words: list[dict]) -> list[bool]:
    """For each kept range: does a sentence end at its end?

    ``words`` are on the cut timeline (``start`` / ``end`` seconds). A word belongs to the kept
    range that holds its midpoint. The last range always ends a sentence: the video ends there.
    """
    spans = cut_offsets(keep)
    last_word: list[str | None] = [None] * len(spans)
    k = 0
    for w in sorted(words, key=lambda w: float(w.get("start", 0.0))):
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        mid = (float(w.get("start", 0.0)) + float(w.get("end", 0.0))) / 2
        while k < len(spans) - 1 and mid >= spans[k][1]:
            k += 1
        last_word[k] = text
    flags = []
    carried: str | None = None
    for i, lw in enumerate(last_word):
        carried = lw if lw is not None else carried
        flags.append(i == len(spans) - 1 or (carried is not None and _ends_sentence(carried)))
    return flags


def _hidden_share(start: float, end: float, hidden: list[tuple[float, float]]) -> float:
    if end <= start:
        return 0.0
    covered = sum(max(0.0, min(end, b) - max(start, a)) for a, b in hidden)
    return min(1.0, covered / (end - start))


def group_scenes(
    keep: list[list[float]],
    words: list[dict],
    *,
    min_s: float = MIN_SCENE_S,
    max_s: float = MAX_SCENE_S,
    tail_s: float = TAIL_LINE_S,
) -> list[Scene]:
    """Kept ranges -> scenes that end on a sentence, each at most ``max_s`` long."""
    spans = cut_offsets(keep)
    ends = sentence_end_after(keep, words)
    scenes: list[Scene] = []
    cur: list[int] = []

    def close() -> None:
        if cur:
            scenes.append(Scene(len(scenes), list(cur), spans[cur[0]][0], spans[cur[-1]][1]))
            cur.clear()

    i = 0
    while i < len(spans):
        length = spans[i][1] - spans[i][0]
        cur_len = spans[cur[-1]][1] - spans[cur[0]][0] if cur else 0.0
        if cur and cur_len + length > max_s:
            close()  # no sentence end came in time: break at the cut rather than pass the limit
            continue
        cur.append(i)
        cur_len += length
        if ends[i] and cur_len >= min_s:
            # A short closing line that follows belongs to this scene, not to the next one.
            j = i + 1
            tail = 0.0
            while j < len(spans) and tail + (spans[j][1] - spans[j][0]) <= tail_s:
                tail += spans[j][1] - spans[j][0]
                if ends[j]:
                    break
                j += 1
            if j < len(spans) and ends[j] and 0 < tail <= tail_s and cur_len + tail <= max_s:
                cur.extend(range(i + 1, j + 1))
                i = j
            close()
        i += 1
    close()
    # A leftover shorter than a real scene joins the one before it when the limit allows.
    if len(scenes) >= 2 and scenes[-1].length_s < min_s:
        a, b = scenes[-2], scenes[-1]
        if b.end_s - a.start_s <= max_s:
            scenes[-2:] = [Scene(a.index, a.keeps + b.keeps, a.start_s, b.end_s)]
    spans_words = sorted(words, key=lambda w: float(w.get("start", 0.0)))
    for s in scenes:
        s.text = " ".join(
            str(w.get("text", "")).strip()
            for w in spans_words
            if s.start_s <= (float(w.get("start", 0.0)) + float(w.get("end", 0.0))) / 2 < s.end_s
        )
    return scenes


def plan_scenes(
    keep: list[list[float]],
    words: list[dict],
    looks: list[str],
    *,
    hidden: list[tuple[float, float]] | None = None,
    start_look: int = 0,
    opening_real: bool = True,
    min_s: float = MIN_SCENE_S,
    max_s: float = MAX_SCENE_S,
) -> list[Scene]:
    """Scenes with every other one marked for a new background and given a look.

    ``hidden`` are stretches of the cut where a full-screen card covers the picture. A scene that
    is mostly hidden is left alone and does not count in the every-other rhythm. A look is never
    used twice in one video: when the looks run out, the remaining scenes stay real.
    """
    scenes = group_scenes(keep, words, min_s=min_s, max_s=max_s)
    hidden = hidden or []
    turn = not opening_real  # True = this visible scene gets a new background
    used = 0
    for s in scenes:
        s.hidden_share = _hidden_share(s.start_s, s.end_s, hidden)
        if s.hidden_share > HIDDEN_SHARE:
            s.reason = "mostly under a card"
            continue
        if not turn:
            s.reason = "real (every other scene)" if s.index or not opening_real else "opening"
        elif not looks or used >= len(looks):
            s.reason = "real (no look left for this video)"
        else:
            s.swap = True
            s.look = looks[(start_look + used) % len(looks)]
            s.reason = "new background"
            used += 1
        turn = not turn
    return scenes
