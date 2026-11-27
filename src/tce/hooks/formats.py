"""Trend formats: a whole video shape, not only its first two seconds (T-25834).

A hook is how a video opens. A format is how the whole video goes: a known shape
people are watching right now, that a topic is poured into. Each format here
carries what the hook studio needs end to end:

    why       why the shape holds viewers, said plainly (the examples are real
              videos from the trending lookup, never described from memory)
    steps     the script template, one step per beat, each with what that part of
              the script does, two or three lines on camera for the recording
              cards, a drawing, and what the edit puts on screen there
    word      the spoken word the edit finds in the take to put a beat on screen
    song      whether the shape needs a song (a trending song is only offered after
              its rights are checked for the platform; this one needs none)

First format: good, better, best. Three ways to do one thing, the best one last,
one word on screen for each point. Easiest to coach and to edit, and it works with
no song.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    id: str
    label: str
    does: str  # what this part of the script does, for him and for the writer
    coach: tuple[str, ...]  # on camera: where to sit or stand, where to look, hands
    screen: str = ""  # what the edit shows on this step, in plain words
    word: str = ""  # the spoken word the edit puts on screen ("" for none)
    fingers: int = 0  # the drawing: fingers held up
    lean: bool = False  # the drawing: leaning in toward the lens


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    what: str
    why: str
    example_query: str
    song: str
    edit: str
    steps: tuple[Step, ...] = field(default_factory=tuple)

    @property
    def beats(self) -> tuple[Step, ...]:
        """The steps the edit puts a word on screen for, in order."""
        return tuple(s for s in self.steps if s.word)

    @property
    def script_need(self) -> str:
        return (
            "an opening line that names the one thing without saying the three words, then "
            + ", ".join(f"one line that starts with “{s.word.capitalize()}”" for s in self.beats)
            + ", then one closing line"
        )


GOOD_BETTER_BEST = Format(
    id="good-better-best",
    name="Good, better, best",
    what="Three ways to do one thing, from fine to the best, with one word on screen for each: GOOD, BETTER, BEST.",
    why="People stay to the end to see which one is best, and each point is one short line, so it is easy to follow "
        "and to save. It needs no song and no props.",
    example_query="good better best",
    song="No song needed. The words on screen carry it.",
    edit="The edit puts GOOD, BETTER and BEST in big letters on the words as you say them, BEST in your color.",
    steps=(
        Step(
            "open", "The topic",
            "One line that names the one thing, without the three words yet. For example: three ways to price a package.",
            (
                "Sit or stand at arm's length, centered, with a little room above your head.",
                "Look straight into the lens.",
                "Hands low and still. Say the topic in one breath.",
            ),
            screen="Your words as captions.",
        ),
        Step(
            "good", "Good",
            "The way most people do it. It works, but only just. Start the line with the word good.",
            (
                "Stay in your spot, eyes on the lens.",
                "Hold up one finger as you say good.",
                "One short line, then a beat of pause.",
            ),
            screen="GOOD in big letters on the word.",
            word="good", fingers=1,
        ),
        Step(
            "better", "Better",
            "A step up: what people who care do. Start the line with the word better.",
            (
                "Lean in a little toward the lens.",
                "Two fingers up as you say better.",
                "One short line, then a beat of pause.",
            ),
            screen="BETTER in big letters on the word.",
            word="better", fingers=2, lean=True,
        ),
        Step(
            "best", "Best",
            "The one you would choose, and why it wins. Start the line with the word best.",
            (
                "Look up into the lens and slow down: this is the one they waited for.",
                "Three fingers up as you say best.",
                "Say why it wins in one line.",
            ),
            screen="BEST in your color on the word.",
            word="best", fingers=3, lean=True,
        ),
        Step(
            "close", "The close",
            "One line: which one you use, or what to do next. Then stop.",
            (
                "Back to where you started.",
                "Hands down.",
                "Say it in one line and stop; no goodbye.",
            ),
            screen="Your words as captions.",
        ),
    ),
)

FORMATS: tuple[Format, ...] = (GOOD_BETTER_BEST,)
BY_ID: dict[str, Format] = {f.id: f for f in FORMATS}

_INK = "#16324f"
_ACCENT = "#1b6fa8"
_SKIN = "#f4dcc8"


def drawing(fmt: Format, step_id: str) -> str | None:
    """A simple line drawing of the step, 9 by 16 like the phone: where he is in the
    frame, the hand, and the word the edit puts on screen. None for an unknown step."""
    step = next((s for s in fmt.steps if s.id == step_id), None)
    if step is None:
        return None
    scale = 1.14 if step.lean else 1.0
    cx, head_y, head_r = 90, 112, 34 * scale
    body = (
        f'<path d="M{cx - 62 * scale:.0f} 320 C{cx - 60 * scale:.0f} 236 {cx - 40 * scale:.0f} {head_y + 62 * scale:.0f} '
        f'{cx} {head_y + 60 * scale:.0f} C{cx + 40 * scale:.0f} {head_y + 62 * scale:.0f} {cx + 60 * scale:.0f} 236 '
        f'{cx + 62 * scale:.0f} 320" fill="#dfe9f3" stroke="{_INK}" stroke-width="3"/>'
    )
    head = f'<circle cx="{cx}" cy="{head_y}" r="{head_r:.0f}" fill="{_SKIN}" stroke="{_INK}" stroke-width="3"/>'
    eyes = (
        f'<circle cx="{cx - 11}" cy="{head_y - 4}" r="3" fill="{_INK}"/>'
        f'<circle cx="{cx + 11}" cy="{head_y - 4}" r="3" fill="{_INK}"/>'
        f'<path d="M{cx - 10} {head_y + 13} Q{cx} {head_y + 20} {cx + 10} {head_y + 13}" fill="none" '
        f'stroke="{_INK}" stroke-width="2.5" stroke-linecap="round"/>'
    )
    hand = ""
    if step.fingers:
        hx, hy = 150, 182
        hand = (
            f'<path d="M{cx + 42} 258 L{hx} {hy + 26}" stroke="{_INK}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M{cx + 42} 258 L{hx} {hy + 26}" stroke="#dfe9f3" stroke-width="7" stroke-linecap="round"/>'
            f'<rect x="{hx - 13}" y="{hy + 6}" width="26" height="24" rx="8" fill="{_SKIN}" stroke="{_INK}" stroke-width="2.5"/>'
        )
        for n in range(step.fingers):
            fx = hx - 8 + n * 8
            hand += (
                f'<rect x="{fx - 3}" y="{hy - 16}" width="7" height="26" rx="3.5" fill="{_SKIN}" '
                f'stroke="{_INK}" stroke-width="2"/>'
            )
    else:
        hand = (
            f'<path d="M{cx - 40} 300 Q{cx} 290 {cx + 40} 300" fill="none" stroke="{_INK}" stroke-width="3" '
            'stroke-linecap="round"/>'
        )
    word = ""
    if step.word:
        color = _ACCENT if step is fmt.beats[-1] else "#ffffff"
        shadow = _INK
        word = (
            f'<text x="86" y="304" text-anchor="middle" font-family="Arial Black, Arial, sans-serif" font-weight="900" '
            f'font-size="30" fill="{color}" stroke="{shadow}" stroke-width="5" paint-order="stroke">'
            f"{step.word.upper()}</text>"
        )
    room = (
        '<path d="M14 40 L166 40" stroke="#9fb6cc" stroke-width="2" stroke-dasharray="6 6"/>'
        '<text x="90" y="32" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#3d5a75">'
        "room above your head</text>"
    ) if step.id == "open" else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 320" width="180" height="320" role="img" '
        f'aria-label="{step.label}: drawing of where to be and what to do">'
        '<rect x="1.5" y="1.5" width="177" height="317" rx="16" fill="#f7fafc" stroke="#9fb6cc" stroke-width="3"/>'
        f"{room}{body}{head}{eyes}{hand}{word}</svg>"
    )
