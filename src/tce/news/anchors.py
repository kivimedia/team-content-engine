"""The anchor index: the named things in Ziv's work an announcement can land on.

This is the gate that makes the third lane precise, and it is deliberately dumb.
A funding round matches nothing here and is rejected without a model call, which
is why daily discovery costs nothing on a quiet day and why the rejection cannot
drift when a model version changes.

Six kinds of anchor, from three kinds of source:

  derived from the database, rebuilt nightly
    dependency   repos with real commit activity in the window
    vendor       env-key prefixes in settings (TCE_FATHOM_API_KEY -> fathom)
    model_id     claude-*, gpt-*, gemini-*, whisper*, nova-* in settings values

  curated by hand in docs/news-anchors.md, reviewed when it changes
    capability   prompt caching, computer use, MCP, subscription limits, ...
    vendor       anything Ziv runs that never appears in a config file

  written by Ziv or the team as standing facts (see `standing.py`)
    client_solution   what Kivi Media runs for clients, in categories not names
    problem_pattern   the problems the owners he coaches keep bringing

The last two are the routes opened by Ziv's 21-Sep correction: AI is in scope
when it makes sense for the owners he coaches, or when it applies to Kivi Media's
clients or solutions. They carry `standing_moment_id` so they are citable; an
anchor that cannot be cited cannot satisfy the non-news citation rule and would
quietly turn into "trust me, it is relevant".
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import ANCHOR_KINDS, ANCHOR_ORIGINS, NewsAnchor

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# `\w` with a str pattern is Unicode-aware in Python 3, so Hebrew letters survive.
# This matters more than it looks: the evidence this index is partly derived from
# is bilingual, and an ASCII-only [^a-z0-9] normaliser DELETES Hebrew outright -
# a Hebrew-only term empties to "" and reads as absent, while a mixed term
# collapses to its Latin half and silently matches the wrong thing. There is a
# test that asserts the values which must SURVIVE, not only the ones dropped.
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str | None) -> str:
    """Fold to a comparable form without destroying non-Latin scripts."""
    if not text:
        return ""
    return _NON_WORD.sub(" ", str(text)).casefold().strip()


def tokens(text: str | None) -> set[str]:
    """Normalised word set, used by the matcher in phase 3."""
    return {t for t in normalize(text).split(" ") if t}


# Words that describe the whole category rather than anything of Ziv's. A match
# on these alone is not a connection, it is a coincidence, and letting them count
# is precisely how "this is important AI news" gets back in.
STOP_TERMS = frozenset(
    {
        "ai",
        "agent",
        "agents",
        "agentic",
        "automation",
        "llm",
        "llms",
        "model",
        "models",
        "api",
        "apis",
        "cloud",
        "data",
        "platform",
        "tool",
        "tools",
        "software",
        "app",
        "apps",
        "chat",
        "bot",
        "bots",
        "assistant",
        "workflow",
        "workflows",
        "integration",
        "integrations",
        "tech",
        "startup",
        "business",
        "system",
        "systems",
        # Real names of his that are also ordinary words: a settings key
        # (search_api_key) and repos (boards, clara). Alone they match Pinterest
        # boards and anyone called Clara, never his work.
        "search",
        "boards",
        "clara",
    }
)

# Anchor kinds strong enough to qualify an item on their own. A problem_pattern
# is real but broad, so two independent ones are required instead of one.
STRONG_KINDS = frozenset({"dependency", "vendor", "model_id", "client_solution"})

_MODEL_ID = re.compile(
    r"\b(?:claude|gpt|gemini|llama|whisper|nova|mistral|qwen|deepseek)[-.\w]*\d[-.\w]*\b",
    re.IGNORECASE,
)

# A term this short or this generic cannot carry a match by itself.
_MIN_TERM_LEN = 3


@dataclass
class DerivedAnchor:
    """One anchor before it is written, with where it came from."""

    kind: str
    term: str
    origin_kind: str
    origin_ref: str | None = None
    weight: float = 1.0
    standing_moment_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise ValueError(f"unknown anchor kind: {self.kind}")
        if self.origin_kind not in ANCHOR_ORIGINS:
            raise ValueError(f"unknown anchor origin: {self.origin_kind}")

    @property
    def normalized(self) -> str:
        return normalize(self.term)

    def usable(self) -> bool:
        """Reject terms that could only ever produce noise."""
        n = self.normalized
        if len(n) < _MIN_TERM_LEN:
            return False
        # A single stop word is never an anchor. A phrase containing one is fine:
        # "prompt caching" is specific, "caching" plus "ai" is not.
        parts = [p for p in n.split(" ") if p]
        if not parts:
            return False
        return not (len(parts) == 1 and parts[0] in STOP_TERMS)


@dataclass
class AnchorIndexResult:
    """What a rebuild did, in terms a person can read back."""

    created: int = 0
    updated: int = 0
    deactivated: int = 0
    skipped_unusable: list[str] = field(default_factory=list)
    by_kind: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False

    def summary(self) -> str:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(self.by_kind.items())) or "nothing"
        head = "would build" if self.dry_run else "built"
        return (
            f"{head} {sum(self.by_kind.values())} anchors ({kinds}); "
            f"{self.created} new, {self.updated} updated, {self.deactivated} retired"
        )


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def vendors_from_settings(settings_obj: Any) -> list[DerivedAnchor]:
    """Env keys name the vendors Ziv actually pays for.

    `fathom_api_key` -> fathom. The value is never read, only the key, so this
    touches no secret.
    """
    out: list[DerivedAnchor] = []
    seen: set[str] = set()
    suffixes = ("_api_key", "_api_base", "_access_token", "_page_token", "_service_key")
    for name in sorted(getattr(settings_obj, "model_fields", {}) or {}):
        for suffix in suffixes:
            if name.endswith(suffix):
                vendor = name[: -len(suffix)]
                if vendor and vendor not in seen:
                    seen.add(vendor)
                    out.append(
                        DerivedAnchor(
                            kind="vendor",
                            term=vendor.replace("_", " "),
                            origin_kind="env",
                            origin_ref=f"settings.{name}",
                        )
                    )
                break
    return [a for a in out if a.usable()]


def model_ids_from_settings(settings_obj: Any) -> list[DerivedAnchor]:
    """Pinned model ids, which is where a deprecation notice lands."""
    out: list[DerivedAnchor] = []
    seen: set[str] = set()
    for name in sorted(getattr(settings_obj, "model_fields", {}) or {}):
        if "model" not in name:
            continue
        value = getattr(settings_obj, name, None)
        if not isinstance(value, str):
            continue
        for match in _MODEL_ID.findall(value):
            key = normalize(match)
            if key and key not in seen:
                seen.add(key)
                out.append(
                    DerivedAnchor(
                        kind="model_id",
                        term=match,
                        origin_kind="env",
                        origin_ref=f"settings.{name}",
                    )
                )
    return [a for a in out if a.usable()]


async def repos_from_commit_evidence(
    session: Any,
    workspace_id: uuid.UUID,
    *,
    window_days: int = 90,
    now: datetime | None = None,
) -> list[DerivedAnchor]:
    """Repos with real commit activity, weighted by how much of it there was.

    A repo Ziv has not touched in three months should not pull news toward
    itself, so the window is real and the weight is not flat.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)
    since = now - timedelta(days=window_days)
    rows = (
        await session.execute(
            select(EvidenceSource.payload_private, EvidenceSource.occurred_at).where(
                EvidenceSource.workspace_id == workspace_id,
                EvidenceSource.source_kind == "github_commit_group",
                EvidenceSource.occurred_at.is_not(None),
                EvidenceSource.occurred_at >= since,
            )
        )
    ).all()

    counts: Counter[str] = Counter()
    for payload, _occurred in rows:
        repo = (payload or {}).get("repo") if isinstance(payload, dict) else None
        if isinstance(repo, str) and repo.strip():
            counts[repo.strip()] += 1

    if not counts:
        return []
    top = counts.most_common()[0][1]
    out: list[DerivedAnchor] = []
    for repo, n in counts.items():
        # "kivimedia/km-florist-receptionist" -> the part news would ever name.
        short = repo.split("/", 1)[-1]
        out.append(
            DerivedAnchor(
                kind="dependency",
                term=short,
                origin_kind="repo",
                origin_ref=repo,
                # 0.4 floor so a quiet repo still counts, 1.0 for the busiest.
                weight=round(0.4 + 0.6 * (n / top), 3),
            )
        )
    return [a for a in out if a.usable()]


def parse_curated_file(path: Path) -> list[DerivedAnchor]:
    """Read docs/news-anchors.md.

    Format is deliberately boring so it can be edited without a tool:

        ## capability
        - prompt caching
        - computer use

    Anything that is not a `## kind` heading or a `- term` bullet is prose and
    is ignored, so the file can explain itself to whoever edits it next.
    """
    if not path.exists():
        return []
    out: list[DerivedAnchor] = []
    kind: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            candidate = line[3:].strip()
            kind = candidate if candidate in ANCHOR_KINDS else None
            continue
        if kind and line.startswith("- "):
            term = line[2:].strip()
            # Allow "term  # why it is here" without the comment becoming a term.
            term = term.split("  #", 1)[0].strip()
            if term:
                out.append(
                    DerivedAnchor(
                        kind=kind,
                        term=term,
                        origin_kind="manual",
                        origin_ref=path.name,
                    )
                )
    return [a for a in out if a.usable()]


async def anchors_from_standing_facts(
    session: Any, workspace_id: uuid.UUID
) -> list[DerivedAnchor]:
    """The two routes Ziv's correction opened, made citable.

    Each standing fact carries its own anchor kind and term in `news_ref`, set by
    the write path in `standing.py`, and the anchor points back at the moment so
    a candidate resting on it has something real to cite.
    """
    rows = (
        await session.execute(
            select(EvidenceMoment.id, EvidenceMoment.news_ref, EvidenceMoment.lesson_summary)
            .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
            .where(
                EvidenceMoment.workspace_id == workspace_id,
                EvidenceSource.source_kind == "standing_fact",
                EvidenceMoment.status == "active",
            )
        )
    ).all()

    out: list[DerivedAnchor] = []
    for moment_id, ref, lesson in rows:
        ref = ref or {}
        kind = ref.get("anchor_kind")
        term = ref.get("anchor_term") or lesson
        if kind not in ("client_solution", "problem_pattern"):
            # A standing fact with no anchor kind is a note, not an anchor. Skip
            # it rather than guessing which of the two it meant to be.
            continue
        out.append(
            DerivedAnchor(
                kind=kind,
                term=str(term),
                origin_kind="manual",
                origin_ref="standing_fact",
                standing_moment_id=moment_id,
            )
        )
    return [a for a in out if a.usable()]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def build_anchor_index(
    session: Any,
    workspace_id: uuid.UUID | str,
    *,
    settings_obj: Any | None = None,
    curated_path: Path | None = None,
    window_days: int = 90,
    dry_run: bool = False,
    now: datetime | None = None,
) -> tuple[AnchorIndexResult, list[DerivedAnchor]]:
    """Rebuild the index. Deterministic, no model call, safe to run nightly.

    Anchors that disappear from every source are DEACTIVATED, never deleted, so
    a term that stops being derived does not take its match history with it.
    """
    ws = uuid.UUID(str(workspace_id))
    settings_obj = settings_obj if settings_obj is not None else _default_settings()
    curated_path = curated_path or _default_curated_path()
    now = now or datetime.now(UTC).replace(tzinfo=None)

    derived: list[DerivedAnchor] = []
    derived += vendors_from_settings(settings_obj)
    derived += model_ids_from_settings(settings_obj)
    derived += await repos_from_commit_evidence(
        session, ws, window_days=window_days, now=now
    )
    derived += parse_curated_file(curated_path)
    derived += await anchors_from_standing_facts(session, ws)

    result = AnchorIndexResult(dry_run=dry_run)

    # Collapse duplicates: the same term can be derived twice (a repo also named
    # in the curated file). Keep the highest weight and the richer origin.
    best: dict[tuple[str, str], DerivedAnchor] = {}
    for anchor in derived:
        if not anchor.usable():
            result.skipped_unusable.append(f"{anchor.kind}:{anchor.term}")
            continue
        key = (anchor.kind, anchor.normalized)
        current = best.get(key)
        if current is None or anchor.weight > current.weight:
            if current is not None and current.standing_moment_id and not anchor.standing_moment_id:
                anchor.standing_moment_id = current.standing_moment_id
            best[key] = anchor

    for anchor in best.values():
        result.by_kind[anchor.kind] = result.by_kind.get(anchor.kind, 0) + 1

    if dry_run:
        return result, sorted(best.values(), key=lambda a: (a.kind, a.normalized))

    existing = {
        (row.kind, row.normalized_term): row
        for row in (
            await session.execute(select(NewsAnchor).where(NewsAnchor.workspace_id == ws))
        )
        .scalars()
        .all()
    }

    for key, anchor in best.items():
        row = existing.get(key)
        if row is None:
            session.add(
                NewsAnchor(
                    id=uuid.uuid4(),
                    workspace_id=ws,
                    kind=anchor.kind,
                    term=anchor.term,
                    normalized_term=anchor.normalized,
                    origin_kind=anchor.origin_kind,
                    origin_ref=anchor.origin_ref,
                    standing_moment_id=anchor.standing_moment_id,
                    weight=anchor.weight,
                    last_seen_at=now,
                    active=True,
                )
            )
            result.created += 1
        else:
            row.term = anchor.term
            row.origin_kind = anchor.origin_kind
            row.origin_ref = anchor.origin_ref
            row.standing_moment_id = anchor.standing_moment_id
            row.weight = anchor.weight
            row.last_seen_at = now
            row.active = True
            result.updated += 1

    for key, row in existing.items():
        if key not in best and row.active:
            row.active = False
            result.deactivated += 1

    await session.flush()
    return result, sorted(best.values(), key=lambda a: (a.kind, a.normalized))


def _default_settings() -> Any:
    from tce.settings import settings

    return settings


def _default_curated_path() -> Path:
    # repo_root/docs/news-anchors.md, from src/tce/news/anchors.py
    return Path(__file__).resolve().parents[3] / "docs" / "news-anchors.md"
