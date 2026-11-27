"""The edit follows the trend format picked for the topic (T-25834).

For good, better, best the Creatorz edit puts each of the three words on screen in
big letters at the moment he says it: GOOD and BETTER in white, BEST in his color,
each taking the caption's place for one beat (a headline at "chest").

The writer of the moments is told first. Then each word is put in by rule at the
first place he says it, in order (good, then better, then best), where it starts a
sentence before anywhere else, so a "best" said in passing in the close does not
steal the third point. Anything the writer put on the same word in
the middle of the screen gives way. A word he never says in the take is named on
the status line.
"""

from __future__ import annotations

import re
from typing import Any

from tce.hooks import format_library
from tce.hooks.formats import Format

_EDGE = re.compile(r"^[^\w]+|[^\w]+$")
_MIDDLE = {"pair", "bubble", "card_grid", "card_list", "card_stat", "insert"}


def _norm(token: str) -> str:
    return _EDGE.sub("", token).lower()


def format_on(ws: Any, candidate_id: Any) -> Format | None:
    """The format picked onto this topic, from the newest week that has one."""
    found = format_library.format_on(ws, candidate_id)
    return found[0] if found else None


def directive(fmt: Format | None) -> str:
    """The lines added to the moments prompt, or "" with no format."""
    if fmt is None or not fmt.beats:
        return ""
    words = [b.word.upper() for b in fmt.beats]
    parts = ", ".join(f'"{w}" ({"accent" if i == len(words) - 1 else "white"})' for i, w in enumerate(words))
    return (
        f"\n\nThis video is the trend format “{fmt.name}”: {fmt.what} Put a headline with place \"chest\" on each"
        f" of these words, at the word itself where he says it: {parts}. Put nothing else in the middle of the"
        " screen on those words."
    )


_SENTENCE_END = (".", "!", "?", ":")


def _find(shots: list[dict[str, Any]], word: str, after: tuple[int, int]) -> tuple[int, str, tuple[int, int]] | None:
    """The first place after `after` (shot index, token index) where he says `word`.
    Where it starts a sentence ("... a package. Good: an hourly rate") wins over where
    it is only inside one ("I pick the best one"); a shot can start mid-sentence, so
    the line's own start counts only after an ending."""
    spoken = [(i, s) for i, s in enumerate(shots) if s.get("text")]
    for leading in (True, False):
        before = ""
        for i, shot in spoken:
            for t, raw in enumerate(str(shot["text"]).split()):
                starts = not before or before.rstrip("\"')”’").endswith(_SENTENCE_END)
                before = raw
                if (i, t) <= after or (leading and not starts):
                    continue
                if _norm(raw) == word:
                    return shot["pick"], raw, (i, t)
    return None


def _is_beat(moment: dict[str, Any], text: str) -> bool:
    return moment.get("type") == "headline" and str(moment.get("text") or "").strip().upper() == text


def _same_word(moment: dict[str, Any], pick: int, raw: str) -> bool:
    at = moment.get("at")
    return isinstance(at, dict) and at.get("pick") == pick and _norm(str(at.get("word") or "")) == _norm(raw)


def _middle(moment: dict[str, Any]) -> bool:
    kind = moment.get("type")
    return kind in _MIDDLE or (kind == "headline" and moment.get("place") in ("chest", "low"))


def ensure_beats(
    moments: list[dict[str, Any]], shots: list[dict[str, Any]], fmt: Format | None, *, keep_first: bool = False
) -> tuple[list[dict[str, Any]], str, list[str]]:
    """The moments with each beat word on screen, one plain sentence on how the edit
    follows the format, and the words put in. `keep_first` keeps moment 0 first (the
    hook opening); the beats go in right after it."""
    if fmt is None or not fmt.beats:
        return moments, "", []
    beats: list[dict[str, Any]] = []
    missing: list[str] = []
    after = (-1, -1)
    last = len(fmt.beats) - 1
    for index, beat in enumerate(fmt.beats):
        text = beat.word.upper()
        found = _find(shots, beat.word, after)
        if found is None:
            missing.append(text)
            continue
        pick, raw, after = found
        beats.append({
            "type": "headline", "text": text, "color": "accent" if index == last else "white", "place": "chest",
            "at": {"pick": pick, "word": raw},
        })
    if not beats:
        return moments, said(fmt, [], missing), []
    first = moments[0] if keep_first and moments else None
    rest = [
        m for m in moments
        if m is not first
        and not any(_is_beat(m, b["text"]) for b in beats)
        and not any(_middle(m) and _same_word(m, b["at"]["pick"], b["at"]["word"]) for b in beats)
    ]
    out = ([first] if first is not None else []) + beats + rest
    # a strike names a headline by its place in the list, and the list changed
    place = {id(m): n for n, m in enumerate(out)}
    final: list[dict[str, Any]] = []
    for m in out:
        if m.get("type") == "strike":
            target = m.get("target")
            old = moments[target] if isinstance(target, int) and 0 <= target < len(moments) else None
            if old is None or id(old) not in place:
                continue
            m = {**m, "target": place[id(old)]}
        final.append(m)
    landed = [b["text"] for b in beats]
    return final, said(fmt, landed, missing), landed


def said(fmt: Format, landed: list[str], missing: list[str]) -> str:
    if not landed:
        return f"The edit could not follow {fmt.name}: none of its words is said in this take."
    if not missing:
        return f"Cut to {fmt.name}: {_join(landed)} on screen as you say them."
    verb = "is" if len(missing) == 1 else "are"
    return f"Cut to {fmt.name}: {_join(landed)} on screen; {_join(missing)} {verb} not, as the word is not said in this take."


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
