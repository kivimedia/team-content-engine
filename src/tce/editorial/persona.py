"""Whose videos a prompt is about (5-Oct): a per-workspace persona.

Every prompt TCE wrote until 5-Oct named the owner: "Ziv's editorial assistant", "You
edit Ziv Raviv's walking videos", "his two dogs, Maple and Rain". A client workspace
(Matan, an Israeli mentalist) got all of that in its jobs.

A persona is read from the workspace's OWN profile rows (creator, brand, founder
voice), picked with `scoped_pick` and limited to rows of that workspace: a NULL row is
the owner's global profile, never a client's. Owner workspaces (owner_workspace_ids)
never get a persona, and neither does a workspace with no profile rows of its own:
`load_persona` returns None and every caller keeps its original text byte for byte.

Asides (who he talks to off camera, like the owner's dogs) are config, not a migration:
    TCE_WORKSPACE_ASIDE_NAMES=<workspace uuid>:Name|Name,<workspace uuid>:Name
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

MAX_ABOUT_CHARS = 900


@dataclass(frozen=True)
class Persona:
    workspace_id: uuid.UUID
    name: str  # what instructions call him ("Matan")
    full_name: str  # "Matan Rosenberg"
    language: str = "en"
    about: str = ""  # who he is, from his creator profile
    brand: str = ""  # his brand line
    phrases: tuple[str, ...] = ()
    samples: tuple[str, ...] = ()
    avoided_words: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    taboos: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    humor: str = ""
    register: str = ""
    aside_names: tuple[str, ...] = ()

    def who(self) -> str:
        """One paragraph: who he is."""
        parts = [self.full_name or self.name]
        if self.about:
            parts.append(self.about)
        if self.brand:
            parts.append(f"Brand: {self.brand}")
        return "\n".join(parts)

    def voice_block(self) -> str:
        """How he sounds and what he never does, for any prompt that writes or edits
        his words. Every line comes from his own profile rows."""
        lines = [f"WHO HE IS:\n{self.who()}"]
        if self.register or self.humor:
            lines.append(
                "HOW HE SOUNDS: "
                + "; ".join(x for x in (self.register, f"humour: {self.humor}" if self.humor else "") if x)
            )
        if self.phrases:
            lines.append("Words and phrases he really uses: " + " | ".join(self.phrases))
        if self.samples:
            lines.append("Lines he wrote himself:\n" + "\n".join(f"- {s}" for s in self.samples))
        if self.patterns:
            lines.append("How he opens and closes: " + " | ".join(self.patterns))
        if self.values:
            lines.append("What he believes:\n" + "\n".join(f"- {v}" for v in self.values))
        if self.themes:
            lines.append("What he keeps coming back to: " + " | ".join(self.themes))
        if self.taboos:
            lines.append(
                "HIS TABOOS (never break one, whatever else you are asked):\n"
                + "\n".join(f"- {t}" for t in self.taboos)
            )
        if self.avoided_words:
            lines.append("Words he never uses: " + " | ".join(self.avoided_words))
        return "\n\n".join(lines)


def _strs(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        value = [value]
    return tuple(str(v).strip() for v in value if str(v or "").strip())


def _first_name(full: str) -> str:
    head = (full or "").split(" - ")[0].strip()
    return head.split()[0] if head.split() else head


def workspace_aside_names(workspace_id: uuid.UUID | str | None) -> tuple[str, ...]:
    """TCE_WORKSPACE_ASIDE_NAMES for one workspace ("" for every other)."""
    from tce.settings import settings

    if workspace_id is None:
        return ()
    want = str(workspace_id).strip().lower()
    for part in (getattr(settings, "workspace_aside_names", "") or "").split(","):
        ws_text, _, names = part.strip().partition(":")
        if ws_text.strip().lower() == want:
            return tuple(n.strip() for n in names.split("|") if n.strip())
    return ()


def persona_from_rows(
    workspace_id: uuid.UUID,
    creator: Any = None,
    brand: Any = None,
    voice: Any = None,
    *,
    language: str = "en",
    aside_names: tuple[str, ...] = (),
) -> Persona | None:
    """A persona from the workspace's own rows; None when it has none."""
    if creator is None and brand is None and voice is None:
        return None
    full = str(getattr(creator, "creator_name", "") or "").strip()
    if not full and brand is not None:
        full = str(getattr(brand, "name", "") or "").split(" - ")[0].strip()
    if not full:
        return None
    vocab = getattr(voice, "vocabulary_signature", None) or {}
    rhythm = getattr(voice, "sentence_rhythm_profile", None) or {}
    if not isinstance(vocab, dict):
        vocab = {}
    if not isinstance(rhythm, dict):
        rhythm = {}
    about = str(getattr(creator, "style_notes", "") or "").strip()
    if len(about) > MAX_ABOUT_CHARS:
        about = about[:MAX_ABOUT_CHARS].rsplit(" ", 1)[0] + " ..."
    return Persona(
        workspace_id=workspace_id,
        name=_first_name(full),
        full_name=full,
        language=language,
        about=about,
        brand=str(getattr(brand, "description", "") or "").strip(),
        phrases=_strs(vocab.get("phrases")),
        samples=_strs(vocab.get("samples")),
        avoided_words=_strs(vocab.get("avoided_words")),
        values=_strs(getattr(voice, "values_and_beliefs", None)),
        taboos=_strs(getattr(voice, "taboos", None)),
        themes=_strs(getattr(voice, "recurring_themes", None)),
        patterns=_strs(getattr(creator, "top_patterns", None)),
        humor=str(getattr(voice, "humor_type", "") or "").strip(),
        register=str(rhythm.get("register") or "").strip(),
        aside_names=tuple(aside_names),
    )


async def load_persona(db: Any, workspace_id: uuid.UUID | str | None) -> Persona | None:
    """The persona of a client workspace, or None (owner workspaces, no own rows).

    `db` is an AsyncSession. Each pick is `scoped_pick` under that workspace's context
    and limited to its own rows: the NULL-workspace rows are the owner's profile.
    """
    from tce.db import workspace_filter
    from tce.models.brand_profile import BrandProfile
    from tce.models.creator_profile import CreatorProfile
    from tce.models.founder_voice_profile import FounderVoiceProfile

    if workspace_id is None:
        return None
    try:
        ws = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(str(workspace_id))
    except ValueError:
        return None
    if ws in workspace_filter.owner_workspace_ids():
        return None
    from sqlalchemy.exc import OperationalError, ProgrammingError

    token = workspace_filter._workspace_id_var.set(ws)
    try:
        rows = []
        for model in (CreatorProfile, BrandProfile, FounderVoiceProfile):
            stmt = workspace_filter.scoped_pick(model, model.workspace_id == ws)
            rows.append((await db.execute(stmt)).scalars().first())
    except (OperationalError, ProgrammingError):
        # A database without the profile tables (a bare test database): no persona.
        return None
    finally:
        workspace_filter._workspace_id_var.reset(token)
    return persona_from_rows(
        ws,
        *rows,
        language=workspace_filter.workspace_language(ws),
        aside_names=workspace_aside_names(ws),
    )


async def load_persona_from(source: Any, workspace_id: uuid.UUID | str | None) -> Persona | None:
    """load_persona from a session or a sessionmaker."""
    from tce.editorial.common import open_session

    if workspace_id is None:
        return None
    async with open_session(source) as db:
        return await load_persona(db, workspace_id)


def swap(text: str, swaps: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> str:
    """Replace each sentence; one that is no longer there fails loudly (a test pins
    every swap), so an edit to an owner prompt can never silently leak his name."""
    for old, new in swaps:
        if old not in text:
            raise ValueError(f"persona swap lost its sentence: {old[:60]!r}")
        text = text.replace(old, new)
    return text
