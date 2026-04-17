"""Repo Scout - pulls a fresh clone of a tracked repo and extracts a RepoBrief.

Source of truth: GitHub. Every run does `git fetch --all && git reset --hard` so
we never work from stale state. A cached RepoBrief is reused ONLY when the
commit SHA still matches HEAD AND it's within the TTL.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.models.repo_brief import RepoBrief
from tce.models.tracked_repo import TrackedRepo
from tce.services.repo_service import Commit, RepoService

SYSTEM_PROMPT = """\
You are the Repo Scout for Team Content Engine. Given a concrete snapshot of a
GitHub repo (README excerpt, recent commits grouped by type, package metadata,
file structure), produce a crisp structured summary that downstream agents can
turn into a LinkedIn / Facebook post.

Rules:
- Ground every statement in the provided data. Do not invent features or fixes.
- When a commit subject is vague ("fix bug"), say so, don't embellish.
- Feature highlights must reference at least one commit short_sha.
- Bug-fix entries must explain "what broke / what now works" only if the subject
  makes that clear; otherwise mark `explanation_confidence: "low"`.
- Output STRICTLY valid JSON, no markdown fences, no commentary.
"""

USER_PROMPT_TEMPLATE = """\
Analyze this repo snapshot and return a structured brief.

Angle for this brief: **{angle}**
- new_features: emphasize recently shipped features
- whole_repo: architecture tour, what it does, who it serves
- recent_fixes: emphasize bug fixes and lessons
- generic: balanced overview

Repo: {owner}/{name}
URL: {repo_url}
Default branch: {branch}
Current HEAD: {head_sha}
Commit window: last {window_days} days ({commit_count} non-merge commits)

Package metadata:
{package_json}

README excerpt (first 4k chars):
---
{readme}
---

Commits grouped by bucket (top 12 per bucket, newest first):
{commits_json}

Return a JSON object with this exact shape:
{{
  "summary": "2-4 sentence description of what the repo is + what changed recently",
  "architecture_notes": "1-3 sentences on structure (e.g. 'Python FastAPI backend + SQLAlchemy ORM; alembic migrations; Remotion for video').",
  "feature_highlights": [
    {{
      "title": "short headline",
      "commit_sha": "short sha",
      "why_interesting": "1-2 sentences",
      "files_hint": ["path/a.ts"]
    }}
  ],
  "bug_fixes": [
    {{
      "title": "short headline",
      "commit_sha": "short sha",
      "what_broke": "plain english or 'unclear from subject'",
      "explanation_confidence": "high|medium|low"
    }}
  ],
  "package_hints": {{
    "kind": "cli | library | web_app | api | worker | other",
    "entry_points": ["..."],
    "notable_scripts": ["..."],
    "is_installable_package": true
  }},
  "angle_lede": "1 sentence that could open a post for this angle",
  "audience_guess": "who would care about this repo"
}}

Keep arrays short (max 6 features, 6 fixes).
"""


@register_agent
class RepoScout(AgentBase):
    """Pulls a fresh clone + builds a structured brief from the commit log."""

    name = "repo_scout"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        tracked_repo_id = context.get("tracked_repo_id")
        repo_url = context.get("repo_url")
        angle = context.get("angle", "generic")
        force_refresh = bool(context.get("force_refresh", False))

        if not tracked_repo_id and not repo_url:
            return {"error": "repo_scout needs tracked_repo_id or repo_url in context"}

        tracked_repo = await self._resolve_repo(tracked_repo_id, repo_url, context)
        if not tracked_repo:
            return {"error": "Could not resolve tracked repo"}

        self._report(f"Resolved repo: {tracked_repo.slug} (angle={angle})")

        service = RepoService()

        # Freshness: always fetch origin first so the HEAD we compare is real.
        self._report(f"Fetching origin/{tracked_repo.default_branch or 'main'}...")
        path = await service.ensure_clone(tracked_repo)
        head_sha = await service.current_sha(path)
        self._report(f"HEAD is {head_sha[:10]} on {tracked_repo.default_branch or 'main'}")

        # Update the TrackedRepo row with the latest observed SHA.
        tracked_repo.last_commit_sha = head_sha
        tracked_repo.last_scanned_at = datetime.now(timezone.utc)

        # Try cache first (unless force_refresh)
        if not force_refresh:
            cached = await service.latest_brief(self.db, tracked_repo, angle, head_sha)
            if cached:
                age_min = int(
                    (datetime.now(timezone.utc) - cached.analyzed_at.replace(
                        tzinfo=cached.analyzed_at.tzinfo or timezone.utc
                    )).total_seconds() / 60
                )
                self._report(
                    f"Cache hit: brief for {head_sha[:10]}/{angle}"
                    f" is {age_min}m old - reusing."
                )
                return {"repo_brief": _serialize_brief(cached, tracked_repo)}

        # Collect fresh data
        commit_window = int(context.get("commit_window_days", 30))
        self._report(f"Scanning last {commit_window} days of commits...")
        commits = await service.commits_since(path, days=commit_window)
        self._report(f"Found {len(commits)} commits")

        buckets = _group_commits(commits)
        self._report(
            "Buckets: "
            + ", ".join(f"{k}={len(v)}" for k, v in buckets.items() if v)
        )

        # Grab a snippet for the top 3 commits in feature + fix buckets so the
        # story can cite real code, not vibes.
        snippet_tasks = []
        for bucket_name in ("feature", "fix"):
            for c in buckets.get(bucket_name, [])[:3]:
                snippet_tasks.append((bucket_name, c))
        snippets: list[dict[str, Any]] = []
        for bucket_name, commit in snippet_tasks:
            snip = await service.snippet_for_commit(path, commit.sha)
            if snip:
                snip["bucket"] = bucket_name
                snip["commit_subject"] = commit.subject
                snippets.append(snip)
        if snippets:
            self._report(f"Extracted {len(snippets)} code snippets.")

        readme = await service.readme_excerpt(path) or ""
        pkg_hints = await service.package_hints(path)

        # Summarize via LLM
        owner, name = _owner_name(tracked_repo.repo_url)
        prompt = USER_PROMPT_TEMPLATE.format(
            angle=angle,
            owner=owner,
            name=name,
            repo_url=tracked_repo.repo_url,
            branch=tracked_repo.default_branch or "main",
            head_sha=head_sha[:10],
            window_days=commit_window,
            commit_count=len(commits),
            package_json=json.dumps(pkg_hints, indent=2) if pkg_hints else "(none detected)",
            readme=readme[:4000] if readme else "(no README)",
            commits_json=json.dumps(_commits_for_prompt(buckets), indent=2),
        )

        self._report("Asking LLM to summarize the repo snapshot...")
        response = await self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
            temperature=0.3,
        )

        text = self._extract_text(response)
        try:
            parsed = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("LLM response wasn't valid JSON - using safe fallback.")
            parsed = {
                "summary": (readme[:400] if readme else f"{owner}/{name}"),
                "architecture_notes": "",
                "feature_highlights": [],
                "bug_fixes": [],
                "package_hints": pkg_hints,
                "angle_lede": "",
                "audience_guess": "",
            }

        # Persist the new RepoBrief (replaces cache for same SHA+angle)
        await _upsert_brief(
            db=self.db,
            tracked_repo=tracked_repo,
            angle=angle,
            commit_sha=head_sha,
            parsed=parsed,
            commits=commits,
            snippets=snippets,
            readme=readme,
        )
        await self.db.flush()

        result = {
            "repo_brief": {
                "tracked_repo_id": str(tracked_repo.id),
                "slug": tracked_repo.slug,
                "repo_url": tracked_repo.repo_url,
                "default_branch": tracked_repo.default_branch or "main",
                "angle": angle,
                "commit_sha": head_sha,
                "summary": parsed.get("summary", ""),
                "architecture_notes": parsed.get("architecture_notes", ""),
                "readme_excerpt": readme[:4000] if readme else None,
                "feature_highlights": parsed.get("feature_highlights", []),
                "bug_fixes": parsed.get("bug_fixes", []),
                "recent_commits": [_commit_to_dict(c) for c in commits[:30]],
                "code_snippets": snippets,
                "package_hints": parsed.get("package_hints", pkg_hints),
                "angle_lede": parsed.get("angle_lede", ""),
                "audience_guess": parsed.get("audience_guess", ""),
                "stats": {
                    "commit_count": len(commits),
                    "buckets": {k: len(v) for k, v in buckets.items()},
                    "window_days": commit_window,
                },
            }
        }
        self._report(
            f"Brief done: {len(parsed.get('feature_highlights', []))} features,"
            f" {len(parsed.get('bug_fixes', []))} fixes."
        )
        return result

    async def _resolve_repo(
        self,
        tracked_repo_id: Any,
        repo_url: str | None,
        context: dict[str, Any],
    ) -> TrackedRepo | None:
        """Load or auto-create the TrackedRepo row."""
        if tracked_repo_id:
            try:
                rid = (
                    tracked_repo_id
                    if isinstance(tracked_repo_id, uuid.UUID)
                    else uuid.UUID(str(tracked_repo_id))
                )
            except ValueError:
                return None
            return await self.db.get(TrackedRepo, rid)

        if not repo_url:
            return None

        # Upsert by slug
        from tce.services.repo_service import parse_github_url

        try:
            owner, name = parse_github_url(repo_url)
        except ValueError:
            return None
        slug = f"{owner}-{name}".lower()
        result = await self.db.execute(
            select(TrackedRepo).where(TrackedRepo.slug == slug).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        repo = TrackedRepo(
            repo_url=repo_url.strip(),
            slug=slug,
            display_name=name,
        )
        self.db.add(repo)
        await self.db.flush()
        return repo


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _owner_name(url: str) -> tuple[str, str]:
    from tce.services.repo_service import parse_github_url

    try:
        return parse_github_url(url)
    except ValueError:
        return ("unknown", "unknown")


def _group_commits(commits: list[Commit]) -> dict[str, list[Commit]]:
    buckets: dict[str, list[Commit]] = {}
    for c in commits:
        buckets.setdefault(c.bucket, []).append(c)
    return buckets


def _commits_for_prompt(buckets: dict[str, list[Commit]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for bucket, commits in buckets.items():
        out[bucket] = [
            {
                "short_sha": c.short_sha,
                "subject": c.subject[:200],
                "author": c.author,
                "date": c.authored_at.date().isoformat() if c.authored_at else None,
            }
            for c in commits[:12]
        ]
    return out


def _commit_to_dict(c: Commit) -> dict[str, Any]:
    return {
        "sha": c.sha,
        "short_sha": c.short_sha,
        "subject": c.subject,
        "author": c.author,
        "authored_at": c.authored_at.isoformat() if c.authored_at else None,
        "bucket": c.bucket,
    }


def _serialize_brief(brief: RepoBrief, tracked_repo: TrackedRepo) -> dict[str, Any]:
    """Turn a persisted RepoBrief into the dict shape downstream agents expect."""
    return {
        "tracked_repo_id": str(tracked_repo.id),
        "slug": tracked_repo.slug,
        "repo_url": tracked_repo.repo_url,
        "default_branch": tracked_repo.default_branch or "main",
        "angle": brief.angle,
        "commit_sha": brief.commit_sha,
        "summary": brief.summary or "",
        "architecture_notes": brief.architecture_notes or "",
        "readme_excerpt": brief.readme_excerpt,
        "feature_highlights": brief.feature_highlights or [],
        "bug_fixes": brief.bug_fixes or [],
        "recent_commits": brief.recent_commits or [],
        "code_snippets": brief.code_snippets or [],
        "package_hints": brief.package_hints or {},
        "stats": brief.stats or {},
        "cached": True,
    }


async def _upsert_brief(
    db,
    tracked_repo: TrackedRepo,
    angle: str,
    commit_sha: str,
    parsed: dict[str, Any],
    commits: list[Commit],
    snippets: list[dict[str, Any]],
    readme: str | None,
) -> RepoBrief:
    """Insert or update the brief for (tracked_repo_id, angle, commit_sha)."""
    stmt = select(RepoBrief).where(
        RepoBrief.tracked_repo_id == tracked_repo.id,
        RepoBrief.angle == angle,
        RepoBrief.commit_sha == commit_sha,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    stats = {
        "commit_count": len(commits),
        "window_days": 30,
    }
    payload = {
        "workspace_id": tracked_repo.workspace_id,
        "tracked_repo_id": tracked_repo.id,
        "angle": angle,
        "commit_sha": commit_sha,
        "summary": parsed.get("summary") or "",
        "architecture_notes": parsed.get("architecture_notes") or "",
        "readme_excerpt": readme[:4000] if readme else None,
        "feature_highlights": parsed.get("feature_highlights") or [],
        "bug_fixes": parsed.get("bug_fixes") or [],
        "recent_commits": [_commit_to_dict(c) for c in commits[:30]],
        "code_snippets": snippets,
        "package_hints": parsed.get("package_hints") or {},
        "stats": stats,
        "analyzed_at": datetime.now(timezone.utc),
    }

    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
        return existing
    brief = RepoBrief(**payload)
    db.add(brief)
    return brief
