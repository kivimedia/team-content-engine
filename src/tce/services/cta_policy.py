"""Call-to-action policy for the legacy daily and repo-driven writers.

The settled default strategy (docs/super-coaching-strategy.md) has exactly one call to
action: book a strategy session. No forced giveaway, guide or comment keyword, no software
pitch. Legacy agents (cta_agent, facebook/linkedin writers, repo_storyteller, copy_polisher)
used to hardcode a comment-keyword DM flow and a public repo link; they now ask this module.

- Default strategy, or a workspace override that EXTENDS it: strategy-session invitation.
  A comment keyword is used only when the operator explicitly supplied one for this run
  (the weekly planner's rule) AND a real asset exists to send; nothing is invented.
- A workspace override that REPLACES the default is that tenant's own strategy: writers are
  told to follow its call to action. Its keyword/guide flow stays available only if that
  strategy text explicitly calls for one.
- A repository is private evidence unless the run explicitly marks it public, and even then
  the link is only used for a replace-mode tenant. Code supports a lesson; it is not the pitch.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from tce.services.strategy_loader import (
    EffectiveStrategy,
    load_effective_strategy,
    load_strategy,
)

STRATEGY_SESSION = "strategy_session"
WORKSPACE_DEFINED = "workspace_defined"

FB_STRATEGY_SESSION_LINE = (
    "If this is the kind of thing you want working inside your business, "
    "book a strategy session with me."
)
LI_STRATEGY_SESSION_LINE = (
    "If you want to work through this in your own business, book a strategy session."
)

_KEYWORD_ALLOWED = re.compile(
    r"comment[- ]keyword|comment ['\"]?[a-z]+['\"]? (?:below|to get|and i)|lead magnet|"
    r"free guide|dm (?:me )?(?:the word|for)|say ['\"]?[a-z]+['\"]? in the comments",
    re.IGNORECASE,
)
_KEYWORD_FORBIDDEN = re.compile(
    r"no (?:forced )?(?:giveaway|guide|lead magnet|comment keyword)", re.IGNORECASE
)


@dataclass
class CtaPolicy:
    mode: str  # strategy_session | workspace_defined
    allow_comment_keyword: bool
    allow_public_repo_link: bool
    keyword: str | None = None
    strategy_excerpt: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "allow_comment_keyword": self.allow_comment_keyword,
            "allow_public_repo_link": self.allow_public_repo_link,
            "keyword": self.keyword,
            "sources": list(self.sources),
            "notes": list(self.notes),
        }


def _explicit_keyword(context: dict[str, Any]) -> str | None:
    kw = context.get("cta_keyword") or context.get("weekly_keyword")
    kw = str(kw).strip() if kw else ""
    return kw or None


def _repo_marked_public(context: dict[str, Any]) -> bool:
    brief = context.get("repo_brief") or {}
    for holder in (brief, context):
        if holder.get("is_public") is True or holder.get("visibility") == "public":
            return True
    return False


def policy_from_strategy(effective: EffectiveStrategy, context: dict[str, Any]) -> CtaPolicy:
    replace = any(
        s.get("kind") == "db_override" and s.get("mode") == "replace" for s in effective.sources
    )
    keyword = _explicit_keyword(context)
    has_asset = bool(str(context.get("guide_title") or "").strip())

    if replace:
        text = effective.text or ""
        strategy_wants_keyword = bool(_KEYWORD_ALLOWED.search(text)) and not bool(
            _KEYWORD_FORBIDDEN.search(text)
        )
        policy = CtaPolicy(
            mode=WORKSPACE_DEFINED,
            allow_comment_keyword=strategy_wants_keyword,
            allow_public_repo_link=_repo_marked_public(context),
            keyword=keyword if strategy_wants_keyword else None,
            strategy_excerpt=text[:3000],
            sources=list(effective.sources),
        )
        if keyword and not strategy_wants_keyword:
            policy.notes.append("keyword supplied but this workspace strategy has no keyword CTA")
        return policy

    policy = CtaPolicy(
        mode=STRATEGY_SESSION,
        allow_comment_keyword=bool(keyword and has_asset),
        allow_public_repo_link=False,
        keyword=keyword if keyword and has_asset else None,
        sources=list(effective.sources),
    )
    if keyword and not has_asset:
        policy.notes.append(
            f"operator keyword '{keyword}' ignored: no guide exists to send, so the "
            "strategy-session invitation is used"
        )
    return policy


async def resolve_cta_policy(db: Any, context: dict[str, Any]) -> CtaPolicy:
    """Policy for this run's workspace. Without a DB or workspace, the default strategy."""
    ws = context.get("workspace_id")
    ws_uuid = None
    if ws:
        try:
            ws_uuid = ws if isinstance(ws, uuid.UUID) else uuid.UUID(str(ws))
        except ValueError:
            ws_uuid = None
    if db is not None and ws_uuid is not None:
        effective = await load_effective_strategy(db, ws_uuid)
    else:
        text = load_strategy()
        effective = EffectiveStrategy(
            text=text,
            sources=[{"kind": "file", "ref": "docs/super-coaching-strategy.md", "mode": "default"}],
        )
    return policy_from_strategy(effective, context)


def writer_cta_block(policy: CtaPolicy, platform: str) -> str:
    """The CTA instructions a platform writer receives."""
    if policy.allow_comment_keyword and policy.keyword:
        if platform == "facebook":
            return (
                f'Weekly CTA keyword: "{policy.keyword}"\n'
                f'CTA line must end with: Comment "{policy.keyword}" and I\'ll send it to you.'
            )
        return "CTA: soft close only. NEVER a 'say XXX' comment-trigger on LinkedIn."
    if policy.mode == WORKSPACE_DEFINED:
        return (
            "CALL TO ACTION: use the call to action defined in this workspace's strategy "
            "below. Do not add a comment keyword, DM flow, giveaway or link it does not ask "
            "for.\n\nWORKSPACE STRATEGY:\n" + policy.strategy_excerpt
        )
    line = FB_STRATEGY_SESSION_LINE if platform == "facebook" else LI_STRATEGY_SESSION_LINE
    return (
        "CALL TO ACTION (settled strategy, non-negotiable):\n"
        "- The only call to action is booking a strategy session. Close with a short, "
        f'conditional invitation in this spirit: "{line}"\n'
        "- No comment keyword, no 'I'll send it to you', no DM flow, no free guide, download "
        "or giveaway.\n"
        "- No software sale or product pitch, and never prices, fees or money figures."
    )
