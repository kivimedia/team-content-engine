"""A workspace's set of looks: invented places in the style of the owner's own village.

A set is a folder with ``looks.json`` and the stills it names:

    {"speaker": "short dark hair, a beard",
     "looks": [{"id": "pine-path", "name": "Pine path",
                "place": "They are now walking on a quiet path ...",
                "refs": ["pines-left.png", "roof-line.png"]}]}

The stills are background-only crops (no face in them) from the owner's recordings; the model
takes the houses, stone and plants from them. ``speaker`` is what must stay recognizable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# The model takes at most six reference images with an edit.
MAX_REFS = 6
# Bump when the wording below changes: scenes drawn with the old wording are drawn again.
PROMPT_VERSION = 1
FILE = "looks.json"


@dataclass(frozen=True)
class Look:
    id: str
    name: str
    place: str
    refs: tuple[Path, ...]


@dataclass(frozen=True)
class LookSet:
    looks: tuple[Look, ...]
    speaker: str = ""

    @property
    def ids(self) -> list[str]:
        return [look.id for look in self.looks]

    def get(self, look_id: str) -> Look | None:
        return next((look for look in self.looks if look.id == look_id), None)


def load(folder: str | Path | None) -> LookSet | None:
    """The set in ``folder``, or None when there is none that can be used. A look whose stills
    are all gone is still usable (the paragraph alone describes the place); a look without a
    paragraph is not."""
    if not folder:
        return None
    folder = Path(folder)
    try:
        raw = json.loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    looks: list[Look] = []
    seen: set[str] = set()
    for item in raw.get("looks") or []:
        if not isinstance(item, dict):
            continue
        look_id = str(item.get("id") or "").strip()
        place = " ".join(str(item.get("place") or "").split())
        if not look_id or not place or look_id in seen:
            continue
        seen.add(look_id)
        refs = [folder / Path(str(name)).name for name in item.get("refs") or []]
        refs = tuple(p for p in refs if p.is_file())[:MAX_REFS]
        looks.append(Look(look_id, str(item.get("name") or look_id), place, refs))
    if not looks:
        return None
    return LookSet(tuple(looks), " ".join(str(raw.get("speaker") or "").split()))


def prompt(look: Look, speaker: str = "", fix: str = "") -> str:
    """What the model is told for one scene. ``fix`` is what the last try got wrong."""
    keep = f", {speaker}" if speaker else ""
    refs = (
        " The reference images show the look of the houses, stone and plants." if look.refs else ""
    )
    text = (
        "Edit this video. Keep the person speaking exactly as they are, frame for frame: the same "
        f"face{keep}, expression, mouth and lip movements, head position and size in the frame, "
        "clothes, and the same handheld selfie camera motion and timing. Do not change the light "
        "on the face or the skin tone.\n\n"
        f"Replace only the background behind them. {look.place}{refs} The houses, trees and gardens "
        "pass by naturally as they walk, following the real camera movement.\n\n"
        "No other people, no cars or other vehicles, no text, no logos, no signs."
    )
    return f"{text}\n\n{fix.strip()}" if fix.strip() else text


def fingerprint(look: Look, speaker: str = "") -> str:
    """Changes when anything the model is shown or told for this look changes."""
    h = hashlib.sha256()
    h.update(f"{PROMPT_VERSION}\n{prompt(look, speaker)}\n".encode())
    for ref in look.refs:
        h.update(ref.name.encode())
        h.update(hashlib.sha256(ref.read_bytes()).digest())
    return h.hexdigest()[:16]
