"""The ten visual hooks proved on the owner's own takes (T-25210, 25 and 26 Nov 2026).

A hook is in this list only after its proof clip rendered from one of his recorded
takes and passed a frame check (timing, safe area, contrast). The six that still
need a fresh take from him (speed ramp, beside yourself, out of a frame, throw and
catch, hand cover, high five on the beat) join when they are proved.

`fits` is the plain rule TCE uses to put a picked hook on one of the week's
videos: words in the topic that make this opening the natural one. A hook with no
rule fits any opening line. The match always says why in one line, and he can move
it to another video.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PREVIEW_DIR = Path(__file__).resolve().parent / "previews"


@dataclass(frozen=True)
class Hook:
    id: str
    name: str
    what: str
    record: str
    fits: tuple[str, ...] = field(default_factory=tuple)
    fit_reason: str = ""
    # Before he presses record (T-25711): where to stand, hands and body, when to move.
    coach: tuple[str, ...] = field(default_factory=tuple)

    @property
    def preview(self) -> Path:
        return PREVIEW_DIR / f"{self.id}.mp4"


HOOKS: tuple[Hook, ...] = (
    Hook(
        "word-behind",
        "Word behind you",
        "A big word sits in the frame and you end up in front of it, so the word is behind your head.",
        "Hold the camera a little further away so there is room above your head. Say the key word clearly.",
        coach=(
            "Stand two steps back, centered, with room above your head.",
            "Hands low and still, so nothing crosses the word.",
            "Say the key word clearly and stay in your spot for the first two seconds.",
        ),
    ),
    Hook(
        "punch-in",
        "Punch-in zoom on the key word",
        "The picture snaps in close on the one word that matters, then back out.",
        "Say the hook line straight to the lens and lean in a little on the key word.",
        coach=(
            "Stand at arm's length, eyes on the lens.",
            "Keep your hands below your chin so the close frame stays clean.",
            "Lean in a little on the key word, then settle back.",
        ),
    ),
    Hook(
        "word-by-word",
        "Headline word by word",
        "Your opening line appears one word at a time, in time with your voice.",
        "Leave room above your head and say the line clearly, in one breath.",
        coach=(
            "Stand at arm's length with a little room above your head.",
            "Hands relaxed and low; the words appear over that space.",
            "Say the line clearly in one breath, no pause in the middle.",
        ),
    ),
    Hook(
        "whip-in",
        "Whip into the first line",
        "A fast blurred slide with a whoosh lands you on your first word.",
        "Start talking the moment you press record, no pause.",
        coach=(
            "Be in your spot and framed before you press record.",
            "Hands ready, no reaching for the phone after you press.",
            "Start talking the moment you press record, no pause.",
        ),
    ),
    Hook(
        "freeze-stamp",
        "Freeze frame with a stamp",
        "The picture freezes on the key word, a short label stamps on, then it plays on.",
        "Make one clear face or gesture on the key word and hold it for half a beat.",
        fits=(r"\bmistakes?\b", r"\bwrong\b", r"\bstop\b", r"\bnever\b", r"\bdon'?t\b", r"\bmyths?\b",
              r"\bnot\b", r"\bfail", r"\btrap"),
        fit_reason="it calls something out, and the stamp names it",
        coach=(
            "Stand at arm's length, face well lit.",
            "Make one clear face or gesture on the key word.",
            "Hold it for half a beat, then carry on talking.",
        ),
    ),
    Hook(
        "split-screen",
        "Split screen: before and after",
        "Two moments side by side, the question and the answer, then the answer takes the screen.",
        "Say the problem early and the result later in the same take; TCE puts the two side by side.",
        fits=(r"\bbefore\b", r"\bafter\b", r"\bused to\b", r"\binstead\b", r"\bvs\.?\b", r"\bversus\b",
              r"\bagain\b", r"\bfrom .{1,40} to\b"),
        fit_reason="it has a before and an after to put side by side",
        coach=(
            "Stay in the same spot and framing for the whole take.",
            "Use your hands when you say the problem and again for the result.",
            "Say the problem early and the result later; TCE puts them side by side.",
        ),
    ),
    Hook(
        "big-number",
        "Big number",
        "Your number fills the screen on the word, with a ding, then you are back.",
        "Say the number out loud and clearly, for example eighty percent.",
        fits=(r"\d[\d,.]*(?:\s?%|\s?percent)?", r"\b(two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|percent)\b"),
        fit_reason="it has a number to put on the screen",
        coach=(
            "Stand at arm's length, eyes on the lens.",
            "Hold up the number with your fingers if it is small, otherwise hands low.",
            "Say the number out loud and clearly, for example eighty percent.",
        ),
    ),
    Hook(
        "bw-to-color",
        "Black and white to color",
        "The opening is black and white and snaps to color on the key word.",
        "Nothing special: say the key word clearly.",
        coach=(
            "Stand at arm's length in good light; color shows best in daylight.",
            "Hands relaxed.",
            "Say the key word clearly; the color comes on with it.",
        ),
    ),
    Hook(
        "proof-pop",
        "Proof pops in under you",
        "Your own screenshot or result pops up on the claim, and your picture lifts to make room.",
        "Attach the picture that proves it to the take, and say the claim it proves.",
        fits=(r"\bproof\b", r"\bprove", r"\bresults?\b", r"\bscreenshots?\b", r"\bdone\b", r"\bbuilt\b",
              r"\bshipped\b", r"\bworks?\b", r"\bdemo\b"),
        fit_reason="it makes a claim a picture of yours can prove",
        coach=(
            "Stand a little higher in the frame; the picture pops in under you.",
            "Point down on the claim, toward where the proof appears.",
            "Attach the picture that proves it to the take, and say the claim it proves.",
        ),
    ),
    Hook(
        "background-jump",
        "Background jump",
        "You stay where you are and the room behind you changes on the key word.",
        "Stay in one spot for the first two seconds; a plain background helps.",
        fits=(r"\btravel", r"\bplaces?\b", r"\brooms?\b", r"\bstage\b", r"\boffice\b", r"\bworld\b",
              r"\bmove\b", r"\bstudio\b", r"\bhome\b"),
        fit_reason="it takes you somewhere, and the room can change with it",
        coach=(
            "Stand in front of a plain wall or background.",
            "Keep hands close to your body so the edge around you stays clean.",
            "Stay still in one spot for the first two seconds.",
        ),
    ),
)

BY_ID: dict[str, Hook] = {h.id: h for h in HOOKS}


def matches(hook: Hook, text: str) -> str | None:
    """The first words in `text` that make this hook fit, or None."""
    low = (text or "").lower()
    for pattern in hook.fits:
        found = re.search(pattern, low)
        if found:
            return found.group(0).strip()
    return None
