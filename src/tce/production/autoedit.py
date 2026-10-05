"""TCE edits by itself, on the subscription (25-Sep): the editor's review and editing requests.

"allow tce to do editing by itself on subscription". Two subscription jobs, both run
by the PC worker on the policy model (never a metered API):

- `video_edit_review` (28-Sep, replaced the 25-Sep proofread): after transcription,
  fix words the recogniser clearly misheard (it heard "Not after you've finished your
  service" where Ziv said no "not", flipping his point) and decide what the viewer
  should not hear - retakes (the complete take stays), talk to the dogs, recogniser
  junk. Conservative by design: every correction and every removal must quote the
  exact words by index, or it is dropped.
- `video_edit_request`: carry out what he typed in "Request an editing change" -
  word fixes, cuts, restores - or come back with one question.
- `video_edit_batch` (30-Sep, talk to the editor): every note of one sitting, each
  pinned to the second he paused on, read against one transcript, then one render.

This module is pure: prompts, schemas, and applying results to a transcript and an
edit plan. The router owns the background tasks, statuses and rendering.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tce.production.retakes import map_to_edit

EDIT_REQUEST_JOB = "video_edit_request"
AGENT_NAME = "video_editor"
PROMPT_VERSION = "autoedit-v1"
MAX_CORRECTIONS = 12
MAX_HOLD_MS = 600

# His standing rules, one file both editor jobs read (30-Sep: "the editor agent needs to be
# opus 5.5 with the right skill files"). Edited in the repo; the next job picks it up.
EDITOR_SKILL_PATH = Path(__file__).parent / "skills" / "video_editor.md"


def editor_skill(persona: Any = None) -> str:
    """His standing rules. A client workspace (5-Oct, `persona`) gets the same rules
    about its own speaker: never Ziv's name, his coaching topic or his dogs."""
    try:
        text = EDITOR_SKILL_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if persona is None or not text:
        return text
    from tce.editorial.persona import swap

    return swap(text, _persona_skill_swaps(persona))


def _asides_phrase(persona: Any) -> str:
    """Who he talks to off camera, for a client workspace."""
    names = list(getattr(persona, "aside_names", ()) or ())
    return f"talk to {' and '.join(names)}, " if names else ""


def _persona_skill_swaps(persona: Any) -> tuple[tuple[str, str], ...]:
    return (
        (
            "You edit Ziv Raviv's walking videos: he walks outside with his phone, talks to camera about\n"
            "coaching and selling, and the edit is cut in the style of TJ Robertson's reels.",
            f"You edit {persona.name}'s walking videos: he walks outside with his phone and talks to\n"
            "camera one sentence at a time, and the edit is cut in the style of TJ Robertson's reels.",
        ),
        (
            "- Talk that is not for the viewer goes: calls to his dogs Maple and Rain, Hebrew to the\n"
            "  dogs (\"בואו\", \"הולכים משם\", \"לא לא לא\"), \"no no no Rain\", false starts, sounds with no\n"
            "  words.",
            "- Talk that is not for the viewer goes: "
            + _asides_phrase(persona)
            + "talk to people around him or to himself,\n  false starts, sounds with no words.",
        ),
    )

_NORM = re.compile(r"[^\w']+")


def _norm(text: str) -> str:
    return " ".join(_NORM.sub(" ", text.lower()).split())


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# What the model sees


def numbered_transcript(
    words: list[dict[str, Any]],
    keep: list[list[float]] | None = None,
    kept: list[dict[str, Any]] | None = None,
    marks: dict[int, str] | None = None,
    span: tuple[int, int] | None = None,
    pins: dict[int, list[int]] | None = None,
    speakers: dict[int, str] | None = None,
) -> str:
    """One sentence a line, every word tagged with its index.

    `speakers` (an agent talk, 3-Oct): who says each word. A line never holds two
    voices, and each starts with its speaker after the clock ("HOST:", "ATLAS:").

    `span` (first, last) writes only those words, keeping their real indexes: the few
    seconds around the moment he paused on (talk to the editor, 30-Sep).

    `pins` writes `<note N>` after word i for each N in pins[i]: where the video was
    when he paused for note N (see pin_index). Key -1 is before the first word.

    With a plan, each line starts with where it lands in the EDITED video (that is the
    clock he watches), and words the edit removed are wrapped in ~~ so a request can
    bring them back. `kept` is the plan's own kept words with their times on the
    speech (28-Sep): the cut follows the audio, so the recogniser's clock alone would
    call some kept words cut.

    Every join between two kept words where the edit skips audio is written `/cut 1.4s/`
    (30-Sep: told only of the removed words, the editor said "the only cut is at 0:42"
    in an edit of 61 pieces). `marks` adds a note after a word (see word_marks).
    """
    timed = {int(w["index"]): float(w["start"]) for w in kept or [] if "index" in w}
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    last_piece: int | None = None
    prev_who: str | None = None
    for i, w in enumerate(words):
        if span is not None and not span[0] <= i <= span[1]:
            continue
        start = timed.get(i, float(w["start_s"]))
        who = speakers.get(i) if speakers else None
        if cur and who != prev_who:
            lines.append(stamp + " ".join(cur))
            cur = []
        prev_who = who
        if not cur:
            if keep is None:
                stamp = f"[{_clock(start)}] "
            else:
                edited = map_to_edit(start, keep)
                stamp = f"[{_clock(edited)} in the edit] " if edited is not None else "[cut] "
            if who:
                stamp += f"{who}: "
        token = f"{i}:{w['text']}"
        removed = keep is not None and (
            i not in timed if timed else map_to_edit((start + float(w["end_s"])) / 2, keep) is None
        )
        if removed:
            token = f"~~{token}~~"
        elif keep is not None:
            piece = _piece(keep, start, float(w["end_s"]))
            if piece is not None and last_piece is not None and piece != last_piece:
                skip = float(keep[piece][0]) - float(keep[last_piece][1])
                cur.append(f"/cut {max(0.0, skip):.1f}s/")
            if piece is not None:
                last_piece = piece
        if marks and i in marks:
            token = f"{token} ({marks[i]})"
        if pins:
            if i == 0 and -1 in pins:
                token = " ".join(f"<note {n}>" for n in pins[-1]) + " " + token
            if i in pins:
                token = token + " " + " ".join(f"<note {n}>" for n in pins[i])
        cur.append(token)
        if str(w["text"])[-1:] in ".?!" or len(cur) >= 24:
            lines.append(stamp + " ".join(cur))
            cur = []
    if cur:
        lines.append(stamp + " ".join(cur))
    return "\n".join(lines)


def _piece(keep: list[list[float]], start: float, end: float) -> int | None:
    """The keep range a word plays in (the one holding most of it)."""
    best, most = None, 0.0
    for k, (a, b) in enumerate(keep):
        got = min(end, float(b)) - max(start, float(a))
        if got > most:
            best, most = k, got
    if best is None:
        best = next((k for k, (a, b) in enumerate(keep) if float(a) - 0.05 <= start <= float(b) + 0.05), None)
    return best


PHONE_ZERO_DB = -85.0  # the phone's mic switched off: digital silence
PHONE_ZERO_WITHIN_S = 0.25  # ... this soon after the recogniser's end of the word
HISS_PRESENT_DB = -45.0  # an "s" is -24..-35 dB above 3.5 kHz on his phone; a lost one stays under
VOWEL_OVER_LOW_DB = 20.0  # the loud part of the word: this far above `low`
VOWEL_OVER_HISS_DB = 15.0  # ... and this far above its own band over 3.5 kHz
# Spellings that end on a HISSED "s" (course, place, less, box, push, what's, clicks, this,
# yes). Not the buzzing "z" spelled s ("is", "was", "sales", "because", "courses"): it is
# voiced and barely shows above 3.5 kHz even when said in full (30-Sep, all five walks).
_HISS_END = re.compile(r"(ce|ss|x|sh|tch|ts|ks|ps|fs|t's|rse|nse|lse|pse)$")
_HISS_WORDS = frozenset({"this", "yes", "us", "plus", "thus", "bus", "gas", "focus", "bonus", "status"})
_LETTERS = re.compile(r"[^\w']+")


def _ends_on_hiss(text: str) -> bool:
    bare = _LETTERS.sub("", str(text)).lower()
    return bare in _HISS_WORDS or bool(_HISS_END.search(bare))


def word_marks(
    words: list[dict[str, Any]],
    keep: list[list[float]] | None,
    levels: list[float] | None,
    low_db: float,
    hop: float = 0.01,
    hiss: list[float] | None = None,
) -> dict[int, str]:
    """What the editor cannot hear for itself, word by word (30-Sep, "cou" for "course").

    - "phone cut its end short": a word spelled to end on a hiss ("course") whose band
      above 3.5 kHz (`hiss`) never reaches HISS_PRESENT_DB between its loud part and the
      phone's digital silence. The recording lost the "s"; no cut can bring it back.
      Loudness alone cannot tell: "this" and "sales" end in a strong "s" and the phone's
      silence right after, just like the lost one. Without `hiss`, nothing is marked.
    - "the edit ends inside this word" / "starts inside": a keep range stops or starts
      inside a kept word while there is still sound there.
    """
    out: dict[int, str] = {}
    if not levels:
        return out

    def frames(arr: list[float], a: float, b: float) -> list[float]:
        return arr[max(0, int(round(a / hop))) : max(0, int(round(b / hop)))]

    for i, w in enumerate(words):
        s, e = float(w["start_s"]), float(w["end_s"])
        if w.get("sound") or e <= s:
            continue
        if hiss and _ends_on_hiss(w["text"]):
            k0 = int(round(s / hop))
            k1 = min(len(levels), int(round((e + PHONE_ZERO_WITHIN_S) / hop)))
            zero = next(
                (k for k in range(max(k0, int(round(e / hop)) - 5), k1) if levels[k] <= PHONE_ZERO_DB), None
            )
            # The vowel: loud, and far louder than its own hiss (an "s" is nearly all hiss).
            loud = [k for k in range(k0, zero or k0) if levels[k] >= low_db + VOWEL_OVER_LOW_DB
                    and k < len(hiss) and levels[k] - hiss[k] >= VOWEL_OVER_HISS_DB]
            if zero is not None and loud:
                tail = hiss[loud[-1] + 1 : zero]
                if not tail or max(tail) < HISS_PRESENT_DB:
                    out[i] = "phone cut its end short"
                    continue
        for a, b in keep or []:
            a, b = float(a), float(b)
            # Sound on the far side of the cut, standing above the noise in the gap beyond
            # the word (with echo cancellation off the phone keeps its wind, always above
            # `low`; read past the word, or the word's own sound hides the clip).
            if s + 0.03 < b < e - 0.03 and max(frames(levels, b, b + 0.03) or [-999.0]) > _over_noise(
                levels, e, +1, low_db
            ):
                out[i] = "the edit ends inside this word"
            elif s + 0.03 < a < e - 0.03 and max(frames(levels, a - 0.03, a) or [-999.0]) > _over_noise(
                levels, s, -1, low_db
            ):
                out[i] = "the edit starts inside this word"
    return out


def _over_noise(levels: list[float], t: float, direction: int, low_db: float) -> float:
    from tce.production.tightcut import TAIL_OVER_NOISE_DB, _gap_noise

    noise = _gap_noise(levels, t, t + direction * 1.0, direction)
    return low_db if noise is None else max(low_db, noise + TAIL_OVER_NOISE_DB)


def script_context(packet: Any | None, title: str | None) -> str:
    parts = [f"Topic: {title}"] if title else []
    if packet is not None:
        bullets = [str(b) for b in (getattr(packet, "bullets", None) or [])]
        phrases = [str(p) for p in (getattr(packet, "script_phrases", None) or [])]
        if bullets:
            parts.append("His points:\n" + "\n".join(f"- {b}" for b in bullets))
        if phrases:
            parts.append("The script he was reading from (he often speaks freely):\n"
                         + "\n".join(phrases))
    return "\n\n".join(parts) or "(no script for this recording)"


_CORRECTION = {
    "type": "object",
    "properties": {
        "first": {"type": "integer"},
        "last": {"type": "integer"},
        "heard": {"type": "string"},
        "replacement": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["first", "last", "heard", "replacement", "why"],
}
_RANGE = {
    "type": "object",
    "properties": {"first": {"type": "integer"}, "last": {"type": "integer"}},
    "required": ["first", "last"],
}

# ---------------------------------------------------------------------------
# The editor's review (28-Sep): proofread and decide what the viewer should not hear,
# in one subscription job. "when I repeat a line twice (even partially) the editor is
# supposed to choose one that is full. If I call my dogs maple, rain bou (בואו) that
# needs to be edited out. if I say no no no rain that needs to be taken out."

REVIEW_JOB = "video_edit_review"
REVIEW_PROMPT_VERSION = "edit-review-v3"
REMOVAL_KINDS = ("retake", "false_start", "aside", "junk")
# Talk to a dog is a few words; a take said again can be a long sentence.
MAX_REMOVAL_WORDS = {"retake": 80, "false_start": 80, "aside": 30, "junk": 40}
MAX_REMOVED_SHARE = 0.6


_HE_REVIEW_SWAPS = (
    ("You edit Ziv Raviv's walking videos.", "You edit these walking videos."),
    ("speaks English with an Israeli accent.", "speaks everyday spoken Israeli Hebrew."),
    (
        "He calls the dogs in Hebrew too (for example בואו, 'come'), "
        "which the recogniser writes as 'boy', 'bo' or 'bow', or translates into English "
        "('from here', 'we're here'). ",
        "He speaks Hebrew to the viewer, so Hebrew is never an aside because it is Hebrew; "
        "only what is said to the dogs, to people around him or to himself is (for example "
        "בואו, 'come', said to the dogs). ",
    ),
    (
        "A line marked NOT ENGLISH was heard as another language when listened to again on its "
        "own: that is Hebrew he says to the dogs or to himself, and the English words on it are "
        "the recogniser's guess. Remove it as an aside unless the English on it plainly belongs to "
        "his point. ",
        "The transcript is Hebrew. ",
    ),
    (
        "Every correction quotes the exact words it replaces by index; replacement '' deletes.",
        "Every correction quotes the exact words it replaces by index; replacement '' deletes. "
        "A replacement is written in Hebrew, exactly as he says it.",
    ),
)


def _to_hebrew(text: str, swaps: tuple[tuple[str, str], ...]) -> str:
    """The Hebrew-workspace version of an instruction written for an English speaker.
    A swap that no longer finds its sentence fails loudly (a test pins each one)."""
    for old, new in swaps:
        if old not in text:
            raise ValueError(f"Hebrew instruction swap lost its sentence: {old[:60]!r}")
        text = text.replace(old, new)
    return text


def review_system(
    dog_names: list[str], rules: str = "", *, language: str = "en", persona: Any = None
) -> str:
    """The review's instructions. `rules` (3-Oct): the block of rules Jennifer learned
    from his notes on earlier videos (production/rules.py), placed after the
    hand-written skill file. Empty leaves the instructions exactly as they were.
    `language` "he" (4-Oct): a Hebrew workspace, with no English-only rule.
    `persona` (5-Oct): a client workspace; his name, his asides, no Ziv and no dogs.
    None (every owner workspace) leaves the text exactly as it was."""
    if persona is not None:
        dog_names = list(getattr(persona, "aside_names", ()) or ())
    text = _review_system_en(dog_names, rules, skill=editor_skill(persona) if persona is not None else None)
    if language == "he":
        text = _to_hebrew(text, _HE_REVIEW_SWAPS)
    if persona is None:
        return text
    from tce.editorial.persona import swap

    intro = "You edit these walking videos." if language == "he" else "You edit Ziv Raviv's walking videos."
    names = list(dog_names)
    company = f"sometimes with {' and '.join(names)}, " if names else ""
    asides_named = f"anything said to {' and '.join(names)}, " if names else ""
    swaps = [
        (intro, f"You edit {persona.name}'s walking videos."),
        (f"often with his two dogs, {' and '.join(names) if names else 'his dogs'}, and ", company + "and "),
        (
            "anything said to the dogs, to people around him, or to himself rather than "
            f"to the viewer - the dogs' names ({' and '.join(names) if names else 'his dogs'}), 'come', "
            "'come here', 'this way', 'good boy', 'no, no, no' said to a dog or to reject what he just said, ",
            asides_named + "anything said to people around him, or to himself rather than to the viewer - "
            "'no, no, no' said to reject what he just said, ",
        ),
    ]
    if language == "he":
        swaps.append(
            (
                "only what is said to the dogs, to people around him or to himself is (for example "
                "בואו, 'come', said to the dogs). ",
                "only what is said to people around him or to himself is. ",
            )
        )
    else:
        swaps.append(
            (
                "He calls the dogs in Hebrew too (for example בואו, 'come'), "
                "which the recogniser writes as 'boy', 'bo' or 'bow', or translates into English "
                "('from here', 'we're here'). ",
                "",
            )
        )
        swaps.append(
            (
                "that is Hebrew he says to the dogs or to himself",
                "that is Hebrew he says to someone near him or to himself",
            )
        )
    return swap(text, swaps)


def _review_system_en(dog_names: list[str], rules: str = "", *, skill: str | None = None) -> str:
    """`skill` None: his own skill file, read now (every owner workspace)."""
    skill_text = editor_skill() if skill is None else skill
    dogs = " and ".join(dog_names) if dog_names else "his dogs"
    return (
        "You edit Ziv Raviv's walking videos. He films himself on his phone while he walks, "
        f"often with his two dogs, {dogs}, and speaks English with an Israeli accent. You get "
        "the speech-recognition transcript, every word tagged with its index, and the script "
        "he had. Decide what the viewer should NOT hear, and fix words the recogniser clearly "
        "misheard.\n\n"
        "REMOVE:\n"
        "1. Retakes. When he says a line more than once - fully or partly, word for word or "
        "reworded - keep exactly one take: the complete one; if more than one is complete, the "
        "last complete one. Remove every other take, including a start he abandoned and said "
        "again (\"Which ... Which means that the sales call is the first step\"), even when "
        "other words or a long pause sit between the takes. Remove whole takes; never cut words "
        "out of the take you keep.\n"
        "2. Asides: anything said to the dogs, to people around him, or to himself rather than "
        f"to the viewer - the dogs' names ({dogs}), 'come', 'come here', 'this way', 'good boy', "
        "'no, no, no' said to a dog or to reject what he just said, 'wait', 'let me say that "
        "again'. He calls the dogs in Hebrew too (for example בואו, 'come'), "
        "which the recogniser writes as 'boy', 'bo' or 'bow', or translates into English "
        "('from here', 'we're here'). An aside often sits between two takes of a line.\n"
        "3. Junk: words the recogniser invented - many words inside a fraction of a second, or "
        "words that make no sense where they stand, most often at the very end.\n"
        "A line marked NOT ENGLISH was heard as another language when listened to again on its "
        "own: that is Hebrew he says to the dogs or to himself, and the English words on it are "
        "the recogniser's guess. Remove it as an aside unless the English on it plainly belongs to "
        "his point. [sound] is speech the recogniser could not make into words (a false start); it "
        "is cut on its own, leave it out of your removals.\n"
        "Keep everything else, in order. Never remove a sentence that makes a point he does not "
        "make in a take you keep. When unsure whether something is an aside or part of his "
        "point, keep it.\n\n"
        "FIX (corrections): only words that are clearly misheard - they contradict what he "
        "plainly says, are nonsense in context, or garble a name or term from his script. A "
        "misheard word can flip his point: it once heard 'Not after you've finished your "
        "service' where he said 'After you've finished your service'. Never rephrase, never "
        "tidy his spoken style; when unsure, leave it, because a wrong fix puts words in his "
        "mouth. Most transcripts need zero or one correction. Include a neighbouring word when "
        "its capitalisation must change (heard 'Not after', replacement 'After').\n\n"
        "Every removal gives the first and last word index, quotes those words exactly as heard, "
        "names its kind, and for a retake or false_start gives kept_from: the index of the first "
        "word of the take you keep (-1 otherwise). Every correction quotes the exact words it "
        "replaces by index; replacement '' deletes."
        + (f"\n\nHIS STANDING RULES (the editor's skill file):\n{skill_text}" if skill_text else "")
        + (f"\n\n{rules}" if rules else "")
    )


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "removals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first": {"type": "integer"},
                    "last": {"type": "integer"},
                    "heard": {"type": "string"},
                    "kind": {"type": "string", "enum": list(REMOVAL_KINDS)},
                    "kept_from": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["first", "last", "heard", "kind", "kept_from", "why"],
            },
        },
        "corrections": {"type": "array", "items": _CORRECTION},
    },
    "required": ["removals", "corrections"],
}


def review_transcript(words: list[dict[str, Any]], speakers: dict[int, str] | None = None) -> str:
    """One utterance a line with its clock, and the pauses between them: a retake shows
    as the same words again after a pause, an aside as a short line among long ones.

    A stretch the second listen heard as another language gets its own line saying so,
    with what it sounds like in Hebrew; "[sound]" is speech it could not make into words.

    `speakers` (an agent talk, 3-Oct) names who says each word: a line never holds two
    voices, and each line starts with its speaker ("HOST:", "ATLAS:").
    """
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    prev_end: float | None = None
    prev_lang: str | None = None
    prev_who: str | None = None
    for i, w in enumerate(words):
        start, end = float(w["start_s"]), float(w["end_s"])
        gap = start - prev_end if prev_end is not None else 0.0
        lang = w.get("lang") or None
        who = speakers.get(i) if speakers else None
        if cur and (gap >= 1.0 or len(cur) >= 24 or lang != prev_lang or who != prev_who):
            lines.append(stamp + " ".join(cur))
            cur = []
        if gap >= 1.5:
            lines.append(f"(pause {gap:.1f} s)")
        if not cur:
            stamp = f"[{_clock(start)}] "
            if who:
                stamp += f"{who}: "
            if lang:
                heard = f'; in Hebrew it sounds like "{w["heard_as"]}"' if w.get("heard_as") else ""
                stamp += f"(NOT ENGLISH - heard as '{lang}'{heard}) "
        prev_lang = lang
        prev_who = who
        cur.append(f"{i}:{w['text']}")
        if str(w["text"])[-1:] in ".?!":
            lines.append(stamp + " ".join(cur))
            cur = []
        prev_end = end
    if cur:
        lines.append(stamp + " ".join(cur))
    return "\n".join(lines)


def review_prompt(
    words: list[dict[str, Any]], context: str, speakers: dict[int, str] | None = None
) -> str:
    return (
        f"{context}\n\nTranscript (index:word):\n{review_transcript(words, speakers)}\n\n"
        "Return the removals (retakes, asides, junk) and the clearly misheard words to fix. "
        f"At most {MAX_CORRECTIONS} corrections. Empty lists are a normal answer."
    )


def talk_context(agent: str) -> str:
    """What every job reading an agent talk is told about it (3-Oct)."""
    return (
        f"This video is a voice call between him and {agent}, an AI agent, that he filmed. "
        f"Where the transcript says who speaks, HOST is him and {agent.upper()} is {agent}. "
        f"{agent}'s lines are the other half of the conversation; cut one only when his note "
        "asks for it."
    )


def conversation_rules(agent: str, *, known: bool = True) -> str:
    """The review's instructions for an agent talk (3-Oct): a filmed voice call between
    him and an AI agent. The agent's lines are the other half of the conversation."""
    name = agent.upper()
    if not known:
        return (
            f"THIS VIDEO IS A CONVERSATION: a voice call between him and {agent}, an AI agent, "
            "that he filmed. Which voice says each line could not be worked out, so nothing "
            "may be removed from it: return no removals, only the clearly misheard words."
        )
    return (
        f"THIS VIDEO IS A CONVERSATION: a voice call between him and {agent}, an AI agent, "
        f"that he filmed. Every line starts with who says it: HOST is him, {name} is "
        f"{agent}. {agent}'s lines are content, the other half of the conversation: never "
        f"remove them, as a retake, a false start, an aside or junk, even when {agent} "
        f"repeats his words, asks something twice or answers in one word. A retake is only "
        f"ever him saying his own line again; when {agent} says something close to his "
        f"words, that is an answer, not a retake. His own lines follow the rules above: his "
        "talk to the dogs, his false starts and the recogniser's junk still go. The silence "
        "while one waits for the other is cut by the edit on its own; it is not a removal."
    )


def _outside(first: int, last: int, protected: frozenset[int] | set[int]) -> list[tuple[int, int]]:
    """The runs of [first, last] that hold no protected word."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i in range(first, last + 1):
        if i in protected:
            if start is not None:
                runs.append((start, i - 1))
                start = None
        elif start is None:
            start = i
    if start is not None:
        runs.append((start, last))
    return runs


def validate_removals(
    words: list[dict[str, Any]],
    removals: list[dict[str, Any]],
    *,
    protected: frozenset[int] | set[int] | None = None,
    protected_name: str = "the agent",
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Removals as time ranges, each proven by quoting the words at its indices.

    A misquote, an overlap, an index outside the transcript or a span longer than its
    kind allows (MAX_REMOVAL_WORDS) is dropped. If what is left would remove more than
    MAX_REMOVED_SHARE of the words, None: that is not an edit, it is a
    misunderstanding, and the rules decide instead.

    `protected` (an agent talk, 3-Oct): the agent's words. A removal never takes them:
    it shrinks to the parts around them, and one that is all the agent's is dropped,
    with a note saying so.
    """
    valid: list[dict[str, Any]] = []
    notes: list[str] = []
    taken: set[int] = set()  # what the review pointed at: a second removal there is skipped
    removed: set[int] = set()  # what is actually taken out
    guarded = frozenset(protected or ())
    for r in removals or []:
        try:
            first, last = int(r["first"]), int(r["last"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(r.get("kind") or "")
        if kind not in REMOVAL_KINDS:
            continue
        if first < 0 or last < first or last >= len(words) or last - first + 1 > MAX_REMOVAL_WORDS[kind]:
            notes.append(f"skipped a removal at {first}-{last}: outside the transcript or too long")
            continue
        span = set(range(first, last + 1))
        if taken & span:
            continue
        heard = " ".join(str(w["text"]) for w in words[first : last + 1])
        if _norm(heard) != _norm(str(r.get("heard") or "")):
            notes.append(f'skipped a removal at {first}-{last}: it quoted "{r.get("heard")}"')
            continue
        runs = _outside(first, last, guarded) if guarded else [(first, last)]
        if not runs:
            notes.append(
                f"skipped a removal at {first}-{last}: those are {protected_name}'s words, "
                "and a talk keeps both voices"
            )
            continue
        kept_from = r.get("kept_from")
        if guarded and kind in ("retake", "false_start") and kept_from in guarded:
            # His line, then the agent saying it back: an answer, not a second take.
            notes.append(
                f"skipped a removal at {first}-{last}: the take it keeps is {protected_name}'s "
                "answer, not his line said again"
            )
            continue
        if runs != [(first, last)]:
            notes.append(f"kept {protected_name}'s words inside the removal at {first}-{last}")
        taken |= span
        keeper = (
            float(words[kept_from]["start_s"])
            if kind in ("retake", "false_start")
            and isinstance(kept_from, int)
            and 0 <= kept_from < len(words)
            and kept_from not in span
            else None
        )
        for a, b in runs:
            removed |= set(range(a, b + 1))
            item = {
                "start": float(words[a]["start_s"]),
                "end": float(words[b]["end_s"]),
                "text": " ".join(str(w["text"]) for w in words[a : b + 1]),
                "kind": kind,
                "why": str(r.get("why") or "")[:200],
            }
            if keeper is not None:
                item["keeper_start"] = keeper
            valid.append(item)
    if words and len(removed) > MAX_REMOVED_SHARE * len(words):
        notes.append(
            f"the review wanted to remove {len(removed)} of {len(words)} words; used the rules instead"
        )
        return None, notes
    return sorted(valid, key=lambda v: v["start"]), notes


EDIT_REQUEST_SYSTEM = (
    "You are the video editor for Ziv Raviv's walking videos. He watched the edited "
    "video and typed a request. Carry it out with these tools only:\n"
    "- corrections: fix transcript words (the captions come from them). Quote the exact "
    "words by index; replacement '' deletes.\n"
    "- cut: remove a range of words (by index) from the video.\n"
    "- restore: put back words the edit removed (shown wrapped in ~~).\n"
    "- hold: give one kept word more room at its start or end, in ms (up to 600), when the "
    "edit clipped it (marked 'the edit ends inside this word', or heard cut short at a "
    "/cut/ join). It cannot bring back a sound the phone never recorded.\n"
    "Times in the transcript are where each line lands in the EDITED video, the clock he "
    "watches. Do exactly what he asked and nothing more. If the request cannot be done "
    "with these tools, or you cannot tell what he means, set needs_you true and ask ONE "
    "short question naming what you checked. reply: one or two plain sentences to him "
    "saying what you changed, quoting the new words where you fixed captions."
)


def edit_request_system(persona: Any = None) -> str:
    """The request editor's instructions with his standing rules (the skill file).
    `persona` (5-Oct): a client workspace's speaker instead of Ziv; None as before."""
    skill = editor_skill(persona)
    base = EDIT_REQUEST_SYSTEM
    if persona is not None:
        from tce.editorial.persona import swap

        base = swap(
            base,
            (("You are the video editor for Ziv Raviv's walking videos.",
              f"You are the video editor for {persona.name}'s walking videos."),),
        )
    return base + (f"\n\n{skill}" if skill else "")


_HOLD = {
    "type": "object",
    "properties": {
        "index": {"type": "integer"},
        "side": {"type": "string", "enum": ["start", "end"]},
        "extra_ms": {"type": "integer"},
        "why": {"type": "string"},
    },
    "required": ["index", "side", "extra_ms", "why"],
}

EDIT_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "needs_you": {"type": "boolean"},
        "question": {"type": "string"},
        "corrections": {"type": "array", "items": _CORRECTION},
        "cut": {"type": "array", "items": _RANGE},
        "restore": {"type": "array", "items": _RANGE},
        "hold": {"type": "array", "items": _HOLD},
    },
    "required": ["reply", "needs_you", "corrections", "cut", "restore", "hold"],
}


def edit_request_prompt(
    words: list[dict[str, Any]],
    keep: list[list[float]],
    context: str,
    request: str,
    *,
    scope: str,
    start_s: float | None,
    end_s: float | None,
    kept: list[dict[str, Any]] | None = None,
    marks: dict[int, str] | None = None,
    history: list[dict[str, str]] | None = None,
    speakers: dict[int, str] | None = None,
) -> str:
    where = ""
    if scope == "timestamp" and start_s is not None and end_s is not None:
        where = f"\nHe pointed at {_clock(start_s)} to {_clock(end_s)} in the edited video."
    return (
        f"{context}\n\n{_earlier_block(history)}His request now:\n{request.strip()}{where}\n\n"
        f"Transcript (index:word; ~~cut~~ words are not in the edit; /cut Ns/ is a join):\n"
        f"{numbered_transcript(words, keep, kept, marks, speakers=speakers)}"
    )


def _earlier_block(history: list[dict[str, Any]] | None) -> str:
    """Earlier notes on this video and what came of them (one conversation per video).

    A row with `where` was a note pinned in a sitting ("at 0:38"); `undone` means he put
    back the version from before it."""
    if not history:
        return ""
    rows = []
    for h in history:
        said = str(h.get("request") or "").strip()
        line = f"- {h['where']}, he said: {said}" if h.get("where") else f"- He wrote: {said}"
        if h.get("reply"):
            line += f" | You answered: {str(h['reply']).strip()}"
        if h.get("question"):
            line += f" | You asked him: {str(h['question']).strip()}"
        if h.get("undone"):
            line += " | He undid this afterwards"
        rows.append(line)
    return "Earlier notes on this video, oldest first:\n" + "\n".join(rows) + "\n\n"


# ---------------------------------------------------------------------------
# Talk to the editor (30-Sep): every note of one sitting in one job, one render.
# "Collect all notes, one re-render at the end." The notes are read against one
# transcript, so word numbers cannot drift from one note to the next.

EDIT_BATCH_JOB = "video_edit_batch"
EDIT_BATCH_PROMPT_VERSION = "edit-batch-v1"

EDIT_BATCH_RULES = (
    "THIS TIME HE GAVE SEVERAL NOTES IN ONE SITTING. He watched the edit and paused on it "
    "each time something was wrong; each pause is one note, numbered in the order he gave "
    "them, and the video renders once after all of them. <note N> in the transcript marks "
    "where the video was when he paused for note N: what he means is usually just before "
    "it, the part he had just heard. 'agreed' is how the editor he spoke with read the note "
    "back to him; he heard it and did not correct it, but where it and his own words "
    "disagree, his words win.\n"
    "Answer every note once, by its number, in notes, each with only its own changes. The "
    f"tools and limits above apply to each note (at most {MAX_CORRECTIONS} word fixes a note). "
    "Every word number refers to this one transcript: never renumber for an earlier note's "
    "change. A later note can refine or cancel an earlier one: the later note then carries "
    "the change and its reply says which note it replaces ('Instead of note 1: ...'), and the "
    "earlier note makes no change and its reply points to the later note. Never make the "
    "same change in two notes, and never fix the same words in two notes. If one note "
    "cannot be done or you cannot tell what he means, set needs_you on that note alone with "
    "one short question; the other notes still go ahead.\n"
    "summary: one or two plain sentences for the whole sitting, saying what changed."
)


def edit_batch_system(persona: Any = None) -> str:
    """The request editor's instructions and his standing rules, plus the batch rules."""
    return edit_request_system(persona) + "\n\n" + EDIT_BATCH_RULES


_BATCH_NOTE = {
    "type": "object",
    "properties": {"note": {"type": "integer"}, **EDIT_REQUEST_SCHEMA["properties"]},
    "required": ["note", *EDIT_REQUEST_SCHEMA["required"]],
}

EDIT_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "array", "items": _BATCH_NOTE},
        "summary": {"type": "string"},
    },
    "required": ["notes", "summary"],
}


def pin_index(
    words: list[dict[str, Any]], source_s: float, kept: list[dict[str, Any]] | None = None
) -> int:
    """The word a pause at `source_s` (the recording's clock) comes after: the last word
    that had started by then. -1 when he paused before the first word."""
    timed = {int(w["index"]): float(w["start"]) for w in kept or [] if "index" in w}
    at = -1
    for i, w in enumerate(words):
        if timed.get(i, float(w["start_s"])) <= source_s + 1e-6:
            at = i
    return at


def _note_where(note: dict[str, Any]) -> str:
    if note.get("where"):
        return str(note["where"])
    if note.get("edit_s") is not None:
        return f"{_clock(float(note['edit_s']))} in the edit"
    return "the whole video"


PLAN_MOVED_LINE = (
    "He gave these notes on the version he watched, which is the edit shown in the "
    "transcript below. The edit plan has changed since that version was made and was "
    "not rendered, so the new version can differ from it in places his notes do not "
    "mention: judge each note against the version he watched."
)


def edit_batch_prompt(
    words: list[dict[str, Any]],
    keep: list[list[float]],
    context: str,
    notes: list[dict[str, Any]],
    *,
    kept: list[dict[str, Any]] | None = None,
    marks: dict[int, str] | None = None,
    history: list[dict[str, Any]] | None = None,
    plan_moved: bool = False,
    speakers: dict[int, str] | None = None,
) -> str:
    """Every note of the sitting, numbered in the order he gave them.

    Each note: `said` (his words as heard), `understood` (the reading he heard back),
    `edit_s` (the paused second on the edit clock) or `where` (a typed note's place),
    and `source_s` (the paused second on the recording), which puts `<note N>` in the
    transcript. One block a note: [note N | 0:38 in the edit | he said "..." | agreed: "..."].

    `keep` is the keep of the file he watched, never a plan that moved on since (1-Oct
    review); `plan_moved` says so in one line when the plan is no longer that edit.
    """
    blocks: list[str] = []
    pins: dict[int, list[int]] = {}
    for n, note in enumerate(notes, 1):
        parts = [f"note {n}", _note_where(note)]
        said = str(note.get("said") or "").strip()
        parts.append(f'he said "{said}"' if said else "his own words were not caught")
        understood = str(note.get("understood") or "").strip()
        if understood:
            parts.append(f'agreed: "{understood}"')
        blocks.append("[" + " | ".join(parts) + "]")
        if note.get("source_s") is not None and words:
            pins.setdefault(pin_index(words, float(note["source_s"]), kept), []).append(n)
    return (
        f"{context}\n\n{_earlier_block(history)}"
        f"His notes from this sitting, in the order he gave them:\n" + "\n".join(blocks) + "\n\n"
        + (PLAN_MOVED_LINE + "\n\n" if plan_moved else "")
        + "Transcript (index:word; ~~cut~~ words are not in the edit; /cut Ns/ is a join; "
        "<note N> is where the video was when he paused for note N):\n"
        f"{numbered_transcript(words, keep, kept, marks, pins=pins, speakers=speakers)}"
    )


def word_holds(words: list[dict[str, Any]], holds: list[dict[str, Any]]) -> list[list[Any]]:
    """The model's holds as [time the word starts or ends, side, extra seconds]."""
    out: list[list[Any]] = []
    for h in holds:
        try:
            i, extra = int(h["index"]), int(h["extra_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        side = str(h.get("side") or "end")
        if 0 <= i < len(words) and side in ("start", "end") and extra > 0:
            at = float(words[i]["end_s" if side == "end" else "start_s"])
            out.append([round(at, 3), side, min(extra, MAX_HOLD_MS) / 1000])
    return out


# ---------------------------------------------------------------------------
# Applying what came back


def apply_corrections(
    words: list[dict[str, Any]], corrections: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply corrections whose quote matches the words at those indices exactly.

    Returns (new words, applied). Applied last-to-first so earlier indices hold. A
    correction that misquotes, overlaps another, or falls outside the list is dropped:
    the model must prove it is looking at the words it changes.
    """
    valid, _skipped = _check_corrections(words, corrections, {}, None)
    return _replace_words(words, valid), sorted(valid, key=lambda c: c["first"])


def _check_corrections(
    words: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    taken: dict[int, int | None],
    note: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The corrections that quote their words exactly and touch no word already fixed.

    `taken` maps a word index to the note that fixed it (None outside a sitting) and is
    shared across the notes of one sitting. Returns (valid, what was skipped and why, in
    his words). At most MAX_CORRECTIONS are read.
    """
    valid: list[dict[str, Any]] = []
    skipped: list[str] = []
    items = list(corrections or [])
    if len(items) > MAX_CORRECTIONS:
        skipped.append(f"only the first {MAX_CORRECTIONS} word fixes were used")
    for c in items[:MAX_CORRECTIONS]:
        try:
            first, last = int(c["first"]), int(c["last"])
        except (KeyError, TypeError, ValueError):
            skipped.append("a word fix that did not say which words")
            continue
        if first < 0 or last < first or last >= len(words):
            skipped.append(f'a word fix of "{c.get("heard") or ""}" pointed outside the transcript')
            continue
        span = range(first, last + 1)
        heard = " ".join(str(w["text"]) for w in words[first : last + 1])
        clash = next((i for i in span if i in taken), None)
        if clash is not None:
            owner = taken[clash]
            skipped.append(
                f'"{heard}" overlaps words note {owner} already fixed'
                if owner is not None and owner != note
                else f'"{heard}" overlaps another fix in this note'
            )
            continue
        if _norm(heard) != _norm(str(c.get("heard") or "")):
            skipped.append(f'a fix quoted "{c.get("heard") or ""}" where the words are "{heard}"')
            continue
        replacement = str(c.get("replacement") or "").strip()
        if replacement == heard:
            continue
        for i in span:
            taken[i] = note
        valid.append({**c, "first": first, "last": last, "heard": heard, "replacement": replacement})
    return valid, skipped


def _replace_words(words: list[dict[str, Any]], valid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply checked corrections last-to-first, so earlier indices hold."""
    out = [dict(w) for w in words]
    for c in sorted(valid, key=lambda c: c["first"], reverse=True):
        first, last = c["first"], c["last"]
        start, end = float(out[first]["start_s"]), float(out[last]["end_s"])
        new = replacement_words(c["replacement"], start, end, out[first].get("precision", "word"))
        out[first : last + 1] = new
    return out


UNCLEAR_QUESTION = (
    "I could not turn that into a change to the video. What exactly should change, and roughly where?"
)
MISSED_QUESTION = "I did not get to this one. Say it again in your next notes."


def _checked_ranges(
    words: list[dict[str, Any]], ranges: list[dict[str, Any]], what: str
) -> tuple[list[list[float]], list[str]]:
    out: list[list[float]] = []
    skipped: list[str] = []
    for r in ranges or []:
        got = word_ranges(words, [r])
        if got:
            out.extend(got)
        else:
            skipped.append(f"a {what} that pointed outside the transcript")
    return out, skipped


def apply_batch(
    words: list[dict[str, Any]],
    overrides: dict[str, Any] | None,
    answer: dict[str, Any] | None,
    count: int,
) -> dict[str, Any]:
    """What one sitting's answer does, before anything is written (pure).

    Every note's changes are checked against the ONE transcript the job read. Word
    fixes share one set of taken words: a fix touching words an earlier note already
    fixed is reported on its own note instead of silently dropped, and at most
    MAX_CORRECTIONS are read per note. Cut, restore and hold fold in note order through
    merge_overrides, so a later note wins over an earlier one. A note that asks him a
    question changes nothing.

    Returns {"words", "overrides", "changed", "summary", "notes"}; each note is
    {"note", "outcome", "reply", ...} with outcome one of:
    change (something to render), answer (a reply, nothing to change), question (it
    asks him), refused (every change it proposed was skipped), unclear (neither a
    change nor a reply), missing (the answer never got to it).
    """
    by_note: dict[int, dict[str, Any]] = {}
    for item in (answer or {}).get("notes") or []:
        try:
            n = int(item.get("note"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 1 <= n <= count and n not in by_note:
            by_note[n] = item
    taken: dict[int, int | None] = {}
    fixes: list[dict[str, Any]] = []
    merged: dict[str, Any] | None = overrides
    changed = False
    out_notes: list[dict[str, Any]] = []
    for n in range(1, count + 1):
        item = by_note.get(n)
        if item is None:
            out_notes.append({"note": n, "outcome": "missing", "reply": "", "question": MISSED_QUESTION})
            continue
        reply = str(item.get("reply") or "").strip()
        if item.get("needs_you"):
            question = str(item.get("question") or "").strip() or UNCLEAR_QUESTION
            out_notes.append({"note": n, "outcome": "question", "reply": reply, "question": question})
            continue
        valid, skipped = _check_corrections(words, item.get("corrections") or [], taken, n)
        cut, bad_cut = _checked_ranges(words, item.get("cut") or [], "cut")
        restore, bad_restore = _checked_ranges(words, item.get("restore") or [], "restore")
        proposed_holds = item.get("hold") or []
        hold = word_holds(words, proposed_holds)
        skipped += bad_cut + bad_restore
        if len(hold) < len(proposed_holds):
            skipped.append("a hold that pointed outside the transcript or asked for no time")
        entry: dict[str, Any] = {
            "note": n,
            "reply": reply,
            "corrections": [{"heard": c["heard"], "replacement": c["replacement"]} for c in valid],
            "cut": cut,
            "restore": restore,
            "hold": hold,
            "skipped": skipped,
        }
        proposed = any(item.get(k) for k in ("corrections", "cut", "restore", "hold"))
        if valid or cut or restore or hold:
            fixes.extend(valid)
            if cut or restore or hold:
                merged = merge_overrides(merged, cut, restore, hold)
            changed = True
            entry["outcome"] = "change"
        elif proposed and skipped:
            entry["outcome"] = "refused"
            entry["question"] = (
                "I could not make this change: " + "; ".join(skipped) + ". Say it again if it still matters."
            )
        elif reply:
            entry["outcome"] = "answer"
        else:
            entry["outcome"] = "unclear"
            entry["question"] = UNCLEAR_QUESTION
        out_notes.append(entry)
    return {
        "words": _replace_words(words, fixes) if fixes else [dict(w) for w in words],
        "overrides": merged if changed else overrides,
        "changed": changed,
        "summary": str((answer or {}).get("summary") or "").strip(),
        "notes": out_notes,
    }


def replacement_words(text: str, start: float, end: float, precision: str) -> list[dict[str, Any]]:
    tokens = text.split()
    if not tokens:
        return []
    step = (end - start) / len(tokens)
    return [
        {
            "text": t,
            "start_s": round(start + k * step, 3),
            "end_s": round(start + (k + 1) * step, 3),
            "precision": precision,
        }
        for k, t in enumerate(tokens)
    ]


def word_ranges(
    words: list[dict[str, Any]], ranges: list[dict[str, Any]]
) -> list[list[float]]:
    out: list[list[float]] = []
    for r in ranges:
        try:
            first, last = int(r["first"]), int(r["last"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= first <= last < len(words):
            out.append([float(words[first]["start_s"]), float(words[last]["end_s"])])
    return out


def _merge(ranges: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def apply_overrides(plan: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Keep = (planned keep + restored) - cut. Persisted overrides survive re-plans."""
    if not overrides:
        return plan
    keep = _merge([list(r) for r in plan.get("keep") or []] + [list(r) for r in overrides.get("restore") or []])
    keep = _subtract(keep, [list(r) for r in overrides.get("cut") or []])
    # 3-Oct: dead air Jennifer's check took out of the finished file.
    keep = _subtract(keep, [list(r) for r in overrides.get("trim") or []])
    keep = [[round(s, 3), round(e, 3)] for s, e in keep if e - s > 0.05]
    units = []
    for u in plan.get("units") or []:
        mid = (float(u["start"]) + float(u["end"])) / 2
        units.append({**u, "kept": any(s <= mid <= e for s, e in keep)})
    stats = dict(plan.get("stats") or {})
    stats["kept_seconds"] = round(sum(e - s for s, e in keep), 2)
    stats["ranges"] = len(keep)
    return {**plan, "keep": keep, "units": units, "stats": stats, "overrides": overrides}


def merge_overrides(
    old: dict[str, Any] | None,
    cut: list[list[float]],
    restore: list[list[float]],
    hold: list[list[Any]] | None = None,
    trim: list[list[float]] | None = None,
) -> dict[str, Any]:
    """The newest instruction wins: restoring what an earlier request cut lifts that cut,
    and a new hold on the same word edge replaces the old one.

    `trim` (3-Oct, Jennifer's check): dead air taken out of the finished file, as
    ranges on the recording. Trims survive every later change, like the cuts; a restore
    over the same stretch lifts the trim there, because his word wins over her check."""
    old = old or {}
    old_cut = _subtract([list(r) for r in old.get("cut") or []], restore)
    old_restore = _subtract([list(r) for r in old.get("restore") or []], cut)
    out: dict[str, Any] = {"cut": _merge(old_cut + cut), "restore": _merge(old_restore + restore)}
    holds = {(round(float(h[0]), 3), h[1]): h for h in (old.get("hold") or []) + (hold or [])}
    if holds:
        out["hold"] = sorted(holds.values())
    trims = _subtract(
        [list(r) for r in old.get("trim") or []] + [list(r) for r in trim or []], restore
    )
    if trims:
        out["trim"] = [[round(s, 3), round(e, 3)] for s, e in trims]
    return out


def _subtract(ranges: list[list[float]], minus: list[list[float]]) -> list[list[float]]:
    out = _merge(ranges)
    for ms, me in _merge(minus):
        nxt: list[list[float]] = []
        for s, e in out:
            if me <= s or ms >= e:
                nxt.append([s, e])
                continue
            if s < ms:
                nxt.append([s, ms])
            if me < e:
                nxt.append([me, e])
        out = nxt
    return out
