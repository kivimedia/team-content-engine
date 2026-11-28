"""The ten visual hooks proved on the owner's own takes (T-25210, 25 and 26 Nov 2026).

A hook is in this list only after its proof clip rendered from one of his recorded
takes and passed a frame check (timing, safe area, contrast). The ones still waiting
for that proof are in WAITING (T-26347, 28 Nov 2026: six from the first round plus
four from a reel he sent): the Hooks page lists them so he knows what take each
needs, and none can be picked for a video until it moves up into HOOKS.

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
    # What the first spoken line must give this hook, for the script writer (T-25711).
    script_need: str = ""
    # A waiting hook only (T-26347): what its proof clip still needs, in his words.
    waiting_for: str = ""

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
        script_need="one short, strong key word in the first line that can sit big behind his head",
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
        script_need="one key word in the first line worth zooming in on",
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
        script_need="a first line short enough to read word by word, under twelve words",
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
        script_need="a first word that is already the point, with no warm-up words before it",
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
        script_need="an early word that names the mistake or the wrong belief, short enough for a two or three word stamp",
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
        script_need="a clear before and a clear after, the problem said early and the result said later",
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
        script_need="a specific number said out loud in the first line, taken from the evidence, never invented",
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
        script_need="one key word in the first line where the picture can snap to color",
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
        script_need="a claim in the first lines that one of his own screenshots or results can prove",
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
        script_need="a place, or a change of place, named in the first line",
    ),
)

BY_ID: dict[str, Hook] = {h.id: h for h in HOOKS}

# Not proved yet (T-26347). Never in BY_ID: a waiting hook cannot be picked, starred
# or put on a video. When its proof clip passes the frame check, move it up into HOOKS
# with its preview and, where it has one, its fit rule.
_TAKE = "A fresh take from you: "
WAITING: tuple[Hook, ...] = (
    Hook(
        "hand-title",
        "Hand to the lens with a title",
        "You push your open hand at the lens, a bold title lands on your palm as it fills the screen, then your hand drops and you talk.",
        "Push one open palm slowly at the lens until it fills the frame, then drop it and start talking.",
        coach=(
            "Stand at arm's length with the phone on a stand, so it does not move.",
            "Push one open palm straight at the lens until it fills the frame, then pull it away.",
            "Start your first line the moment your hand drops.",
        ),
        script_need="a bold title of three to five words for the palm, and a first line that follows straight from it",
        waiting_for=_TAKE + "your hand pushed at the lens. The same take can also prove the hand cover.",
    ),
    Hook(
        "color-wipe",
        "Colored wipe between shots",
        "A band in your hook color sweeps across the screen and reveals the next shot.",
        "Nothing special: say your first point, pause for a beat, then say the next one.",
        coach=(
            "Stand at arm's length and keep the same spot for the whole take.",
            "Hands relaxed.",
            "Leave a short pause after your first point; the wipe runs in that pause.",
        ),
        script_need="a first line in two parts, with a natural pause between them where the wipe can run",
        waiting_for="A proof clip only: it can be made from one of your existing takes.",
    ),
    Hook(
        "object-mic",
        "Talking into an object as a mic",
        "You open by talking into something unexpected held like a microphone, a banana or a stapler, then put it down and carry on.",
        "Hold an everyday object like a microphone close to your mouth for the first line.",
        coach=(
            "Stand at arm's length with the object in one hand at chin height.",
            "Talk into it like a microphone for the first line, eyes on the lens.",
            "Put it down on the next line and carry on talking.",
        ),
        script_need="a first line that sounds like an announcement, said into the object",
        waiting_for=_TAKE + "you talking into an object as if it were a microphone.",
    ),
    Hook(
        "title-drop",
        "Title swipes down",
        "Your title slides down from the top of the screen and settles above your head as you start.",
        "Leave room above your head and start with the line the title says.",
        coach=(
            "Stand at arm's length with room above your head.",
            "Hands low, so nothing crosses the title.",
            "Say the title line first, clearly.",
        ),
        script_need="a title of under six words at the very start that can drop in from the top",
        waiting_for="A proof clip only: it can be made from one of your existing takes.",
    ),
    Hook(
        "speed-ramp",
        "Speed ramp walk-in",
        "You walk in fast toward the camera, the picture slows right as you start to talk.",
        "Start a few steps back and walk toward the lens, stopping in your spot on the first word.",
        coach=(
            "Start four or five steps back from your spot.",
            "Walk toward the lens with your arms natural.",
            "Stop in your spot and start talking on the first word.",
        ),
        script_need="a first word that lands the moment he stops walking, with no warm-up",
        waiting_for=_TAKE + "you walking in toward the camera.",
    ),
    Hook(
        "beside-yourself",
        "You beside yourself",
        "A second copy of you appears beside you and reacts to what you say.",
        "Record the reaction as a second short take in the same spot.",
        coach=(
            "Phone on a stand; it must not move between the two takes.",
            "Take one: say your line standing on the left of the frame.",
            "Take two: stand on the right and react to the line.",
        ),
        script_need="a first line worth reacting to, a claim or a question",
        waiting_for=_TAKE + "two short takes in the same spot, the line and the reaction.",
    ),
    Hook(
        "out-of-frame",
        "Stepping out of a frame",
        "You appear inside a picture frame and lean out over its border.",
        "Lean toward the camera on the first word.",
        coach=(
            "Stand at arm's length, centered.",
            "Hands low to start.",
            "Lean toward the lens on the first word.",
        ),
        script_need="a first word strong enough to lean in on",
        waiting_for=_TAKE + "you leaning in toward the lens on the first word.",
    ),
    Hook(
        "throw-catch",
        "Throw to the camera, catch in the next scene",
        "You toss something at the lens, it covers the screen, and the next shot opens with it landing.",
        "Throw an object straight at the lens so it fills the frame; in the next take start with it in your hand.",
        coach=(
            "Phone on a stand, and something soft to throw.",
            "Take one: throw it straight at the lens so it fills the frame.",
            "Take two: start with it in your hand and say your first line.",
        ),
        script_need="a first line that follows a change, a new place or a new idea",
        waiting_for=_TAKE + "two takes, the throw and the catch.",
    ),
    Hook(
        "hand-cover",
        "Hand cover transition",
        "Your palm covers the lens and uncovers into a new place or outfit.",
        "Cover the lens fully with your palm at the end of take one, start take two covered.",
        coach=(
            "Phone on a stand at the same height for both takes.",
            "End take one by covering the lens fully with your palm.",
            "Start take two with the lens covered, then pull your hand away and talk.",
        ),
        script_need="a first line that follows a change, a new place or a new look",
        waiting_for=_TAKE + "two takes, ending and starting with your palm on the lens.",
    ),
    Hook(
        "beat-high-five",
        "High five on the beat, with music",
        "A trending sound plays and you high five or clap right on its beat to open.",
        "Play the sound while recording and hit the gesture on the beat.",
        coach=(
            "Stand at arm's length with the sound playing out loud.",
            "Hands ready at chest height.",
            "High five or clap right on the beat, then start talking.",
        ),
        script_need="a first line short enough to land right after the beat",
        waiting_for=_TAKE + "you clapping or high fiving on the beat of a sound.",
    ),
)


def matches(hook: Hook, text: str) -> str | None:
    """The first words in `text` that make this hook fit, or None."""
    low = (text or "").lower()
    for pattern in hook.fits:
        found = re.search(pattern, low)
        if found:
            return found.group(0).strip()
    return None
