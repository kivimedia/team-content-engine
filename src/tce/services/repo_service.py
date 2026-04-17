"""RepoService - git operations for tracked repos.

Everything in this service treats GitHub as the source of truth:
- Every call to `ensure_clone` runs `git fetch --all` and resets to origin.
- `latest_brief` only returns a cached brief if its commit_sha == current HEAD
  AND it's within the TTL (default 6h).

This module is the ONLY place that shells out to `git` - agents go through it.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.repo_brief import RepoBrief
from tce.models.tracked_repo import TrackedRepo
from tce.settings import settings

logger = structlog.get_logger()

# Conventional-commit style prefixes mapped to classification buckets.
# Ordered so longest prefix matches first.
_COMMIT_PATTERNS: list[tuple[str, str]] = [
    ("feat:", "feature"),
    ("feature:", "feature"),
    ("feat(", "feature"),
    ("fix:", "fix"),
    ("bug:", "fix"),
    ("bugfix:", "fix"),
    ("hotfix:", "fix"),
    ("fix(", "fix"),
    ("perf:", "perf"),
    ("perf(", "perf"),
    ("refactor:", "refactor"),
    ("refactor(", "refactor"),
    ("chore:", "chore"),
    ("chore(", "chore"),
    ("docs:", "docs"),
    ("docs(", "docs"),
    ("test:", "test"),
    ("test(", "test"),
    ("style:", "style"),
    ("ci:", "ci"),
]


@dataclass
class Commit:
    sha: str
    short_sha: str
    subject: str
    author: str
    authored_at: datetime
    bucket: str  # feature | fix | perf | refactor | chore | docs | test | style | ci | other
    files_changed: list[str] = field(default_factory=list)
    url: str | None = None


DEFAULT_TTL_HOURS = 6
DEFAULT_COMMIT_WINDOW_DAYS = 30


def _slugify(url: str) -> str:
    """Extract owner-repo slug from a GitHub URL."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url.strip())
    if not m:
        raise ValueError(f"Not a GitHub URL: {url}")
    owner, name = m.group(1), m.group(2)
    return f"{owner}-{name}".lower()


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo_name) from a GitHub URL. Raises ValueError if malformed."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url.strip())
    if not m:
        raise ValueError(f"Not a GitHub URL: {url}")
    return m.group(1), m.group(2)


def classify_commit(subject: str) -> str:
    """Classify a commit subject line into a bucket."""
    lowered = subject.lstrip().lower()
    for prefix, bucket in _COMMIT_PATTERNS:
        if lowered.startswith(prefix):
            return bucket
    # Heuristic fallback for non-conventional commits
    if any(w in lowered for w in ("fix ", " fix", "bug", "hotfix", "patch")):
        return "fix"
    if any(w in lowered for w in ("add ", "new ", "introduce ", "implement ", "support ")):
        return "feature"
    return "other"


class RepoService:
    """Git operations and cache management for tracked repos."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        github_pat: str | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        self.cache_dir = Path(
            cache_dir or os.environ.get("TCE_REPO_CACHE_DIR") or settings.repo_cache_dir
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.github_pat = github_pat or os.environ.get("TCE_GITHUB_PAT") or settings.github_pat
        self.ttl_hours = ttl_hours

    # ------------------------------------------------------------------
    # Low-level git runners
    # ------------------------------------------------------------------

    def _authed_url(self, repo_url: str) -> str:
        """Embed the PAT in HTTPS URLs so private repos work."""
        if not self.github_pat:
            return repo_url
        if repo_url.startswith("https://github.com/"):
            return repo_url.replace(
                "https://github.com/", f"https://x-access-token:{self.github_pat}@github.com/"
            )
        return repo_url

    async def _run_git(
        self, args: list[str], cwd: Path | None = None, timeout: int = 120
    ) -> subprocess.CompletedProcess:
        """Run a git command asynchronously via a thread."""

        def _run() -> subprocess.CompletedProcess:
            return subprocess.run(  # noqa: S603
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )

        return await asyncio.to_thread(_run)

    # ------------------------------------------------------------------
    # Clone / freshness
    # ------------------------------------------------------------------

    def local_path(self, tracked_repo: TrackedRepo) -> Path:
        """Path where the clone lives, namespaced by workspace when present."""
        workspace_part = (
            str(tracked_repo.workspace_id) if tracked_repo.workspace_id else "_global"
        )
        return self.cache_dir / workspace_part / tracked_repo.slug

    async def ensure_clone(self, tracked_repo: TrackedRepo) -> Path:
        """Make sure the local clone exists AND is synced with origin.

        On every call:
        1. If missing: clone
        2. If present: `git fetch --all` then `git reset --hard origin/<default_branch>`

        Returns the local clone path.
        """
        path = self.local_path(tracked_repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        authed_url = self._authed_url(tracked_repo.repo_url)
        branch = tracked_repo.default_branch or "main"

        if not (path / ".git").exists():
            logger.info("repo_service.clone", slug=tracked_repo.slug)
            if path.exists():
                # Wipe non-git leftovers
                await asyncio.to_thread(_rmtree, path)
            path.parent.mkdir(parents=True, exist_ok=True)
            result = await self._run_git(
                ["clone", "--depth", "200", "--branch", branch, authed_url, str(path)],
                timeout=300,
            )
            if result.returncode != 0:
                # Retry without branch flag (branch may not be main)
                logger.warning(
                    "repo_service.clone_retry",
                    slug=tracked_repo.slug,
                    stderr=result.stderr[-300:],
                )
                result = await self._run_git(
                    ["clone", "--depth", "200", authed_url, str(path)],
                    timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"git clone failed for {tracked_repo.slug}: {result.stderr[-500:]}"
                    )
            return path

        # Already cloned: fetch + reset to origin
        await self._run_git(["fetch", "--all", "--prune"], cwd=path, timeout=180)
        await self._run_git(
            ["reset", "--hard", f"origin/{branch}"], cwd=path, timeout=60
        )
        return path

    async def current_sha(self, path: Path) -> str:
        result = await self._run_git(["rev-parse", "HEAD"], cwd=path)
        return result.stdout.strip()

    async def remote_head_sha(self, tracked_repo: TrackedRepo) -> str | None:
        """Ask origin for the latest SHA without requiring a local clone."""
        authed_url = self._authed_url(tracked_repo.repo_url)
        branch = tracked_repo.default_branch or "main"
        result = await self._run_git(
            ["ls-remote", authed_url, f"refs/heads/{branch}"], timeout=30
        )
        if result.returncode != 0:
            return None
        line = (result.stdout or "").strip().split("\n")[0]
        if not line:
            return None
        return line.split()[0]

    # ------------------------------------------------------------------
    # Commit extraction
    # ------------------------------------------------------------------

    async def commits_since(
        self, path: Path, days: int = DEFAULT_COMMIT_WINDOW_DAYS
    ) -> list[Commit]:
        """Return commits from the last N days, classified into buckets."""
        since = f"--since={days} days ago"
        # %H|%h|%s|%an|%aI  (ISO date)
        result = await self._run_git(
            ["log", since, "--pretty=format:%H|%h|%s|%an|%aI", "--no-merges"],
            cwd=path,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("repo_service.log_failed", stderr=result.stderr[-300:])
            return []

        commits: list[Commit] = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue
            sha, short_sha, subject, author, authored = parts
            try:
                authored_at = datetime.fromisoformat(authored)
            except ValueError:
                authored_at = datetime.now(timezone.utc)
            commits.append(
                Commit(
                    sha=sha,
                    short_sha=short_sha,
                    subject=subject,
                    author=author,
                    authored_at=authored_at,
                    bucket=classify_commit(subject),
                )
            )
        return commits

    async def files_changed(self, path: Path, sha: str, limit: int = 8) -> list[str]:
        """Return up to `limit` files changed in a given commit."""
        result = await self._run_git(
            ["show", "--name-only", "--pretty=format:", sha], cwd=path, timeout=30
        )
        files = [
            f.strip() for f in (result.stdout or "").splitlines() if f.strip()
        ]
        return files[:limit]

    async def snippet_for_commit(
        self, path: Path, sha: str, max_lines: int = 40
    ) -> dict[str, Any] | None:
        """Grab the first interesting file touched by `sha` and return a short excerpt."""
        files = await self.files_changed(path, sha, limit=5)
        # Prefer source files over lockfiles/docs
        def _score(f: str) -> int:
            lower = f.lower()
            if lower.endswith((".lock", ".log", ".sum", ".md", ".txt")):
                return 1
            if any(lower.endswith(ext) for ext in (".ts", ".tsx", ".js", ".py", ".go", ".rs", ".sql")):
                return 10
            return 5

        files = sorted(files, key=_score, reverse=True)
        for fn in files:
            file_path = path / fn
            if not file_path.exists() or file_path.is_dir():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lines = content.splitlines()[:max_lines]
            return {
                "file": fn,
                "excerpt": "\n".join(lines),
                "commit_sha": sha,
            }
        return None

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    async def readme_excerpt(self, path: Path, max_chars: int = 4000) -> str | None:
        for name in ("README.md", "Readme.md", "readme.md", "README.rst", "README.txt", "README"):
            fp = path / name
            if fp.exists() and fp.is_file():
                try:
                    return fp.read_text(encoding="utf-8", errors="replace")[:max_chars]
                except Exception:
                    continue
        return None

    async def package_hints(self, path: Path) -> dict[str, Any]:
        """Detect package-shape hints (name, description, entry points)."""
        hints: dict[str, Any] = {}
        pj = path / "package.json"
        if pj.exists():
            try:
                import json

                data = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
                hints["package_json"] = {
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "main": data.get("main"),
                    "bin": data.get("bin"),
                    "scripts": list((data.get("scripts") or {}).keys())[:10],
                    "exports": bool(data.get("exports")),
                }
            except Exception:
                pass
        pt = path / "pyproject.toml"
        if pt.exists():
            try:
                text = pt.read_text(encoding="utf-8", errors="replace")
                name_match = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
                desc_match = re.search(r'^description\s*=\s*"([^"]+)"', text, re.MULTILINE)
                hints["pyproject"] = {
                    "name": name_match.group(1) if name_match else None,
                    "description": desc_match.group(1) if desc_match else None,
                }
            except Exception:
                pass
        cargo = path / "Cargo.toml"
        if cargo.exists():
            hints["cargo"] = True
        return hints

    # ------------------------------------------------------------------
    # Brief cache
    # ------------------------------------------------------------------

    async def latest_brief(
        self,
        db: AsyncSession,
        tracked_repo: TrackedRepo,
        angle: str,
        current_sha: str,
    ) -> RepoBrief | None:
        """Return the cached brief only if SHA matches and within TTL."""
        stmt = (
            select(RepoBrief)
            .where(
                RepoBrief.tracked_repo_id == tracked_repo.id,
                RepoBrief.angle == angle,
                RepoBrief.commit_sha == current_sha,
            )
            .order_by(RepoBrief.analyzed_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        brief = result.scalar_one_or_none()
        if not brief:
            return None
        if not brief.analyzed_at:
            return None
        # Compare as UTC-aware
        analyzed_at = brief.analyzed_at
        if analyzed_at.tzinfo is None:
            analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - analyzed_at
        if age > timedelta(hours=self.ttl_hours):
            return None
        return brief


def _rmtree(path: Path) -> None:
    """Best-effort rm -rf."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)
