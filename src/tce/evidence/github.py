"""GitHub collector: full accessible repo inventory, commits in a window, grouped.

API only (no clones). Every file reference is taken from the commit detail AT that
commit's SHA, and blob links embed the SHA, never a branch name. Nothing here
writes to GitHub.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from tce.evidence.common import (
    EvidenceHTTPError,
    RetryPolicy,
    Sleep,
    as_utc,
    in_window,
    iso_z,
    parse_iso,
    request_with_retries,
    stable_hash,
)

API_BASE = "https://api.github.com"
DEFAULT_MAX_PAGES = 100
PATCH_EXCERPT_CHARS = 3000
MAX_FILES_WITH_PATCH = 40
GROUP_WINDOW = timedelta(days=3)

_REVERT_SHA = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)
_CONVENTIONAL = re.compile(r"^\s*(\w+)(?:\(([^)]+)\))?!?:")
_TICKET = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b|(?<![\w/])#(\d+)\b")
_DEP_FILES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "requirements.txt", "requirements-dev.txt", "poetry.lock", "uv.lock", "pipfile",
    "pipfile.lock", "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile.lock",
    "composer.lock", "pyproject.toml",
}
_NOISY_SHARED_FILES = _DEP_FILES | {"readme.md", "changelog.md", ".gitignore"}
_DEP_MESSAGE = re.compile(
    r"^\s*(build|chore|fix)\((deps|deps-dev|dependencies)\)|^\s*deps(\([^)]*\))?:"
    r"|\bdependabot\b|\brenovate\b|\bbump\b.+\bfrom\b.+\bto\b"
    r"|\b(bump|upgrade|update)\b.*\bdependenc",
    re.IGNORECASE,
)
_MODEL_BUMP = re.compile(
    r"\b(bump|switch|default|move|update|upgrade|change)\b.*\b(model|claude|gpt|sonnet|opus|"
    r"haiku|gemini|image)\b|\b(model|agents?)\b.*\b(bump|to)\b.*\b(claude|gpt|sonnet|opus)",
    re.IGNORECASE,
)


def link_next(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().strip("<>")
        if any(s.strip() == 'rel="next"' for s in section[1:]):
            return url
    return None


@dataclass
class RepoCommits:
    state: str  # ok | empty | unavailable
    commits: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    pages: int = 0


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        clock: Callable[[], float] = time.time,
        timeout_s: float = 60.0,
    ) -> None:
        if not token:
            raise ValueError("GitHub token is not configured")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            transport=transport,
            timeout=timeout_s,
        )
        self._sleep = sleep
        self._retry = retry or RetryPolicy(max_attempts=4, max_wait_s=300.0)
        self._clock = clock
        self.max_pages = max_pages
        self.on_wait: Callable[[str], Any] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _rate_limit_wait(self, resp: httpx.Response) -> float | None:
        if resp.status_code not in (403, 429):
            return None
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                return 60.0
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            try:
                return max(1.0, float(reset) - self._clock() + 1.0)
            except (TypeError, ValueError):
                return 60.0
        if resp.status_code == 403 and "secondary rate limit" in resp.text.lower():
            return 60.0
        return None

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await request_with_retries(
            self._client, "GET", url, params=params, policy=self._retry, sleep=self._sleep,
            extra_wait=self._rate_limit_wait, on_wait=self.on_wait,
        )

    async def _paginate(
        self, url: str, params: dict[str, Any] | None
    ) -> tuple[list[Any], int, httpx.Response | None]:
        """All pages via Link. Returns (items, pages, failing_response_or_None)."""
        items: list[Any] = []
        pages = 0
        next_url: str | None = url
        next_params = params
        while next_url:
            if pages >= self.max_pages:
                raise EvidenceHTTPError(None, f"page cap {self.max_pages} reached for {url}")
            resp = await self._get(next_url, next_params)
            if resp.status_code != 200:
                return items, pages, resp
            pages += 1
            data = resp.json()
            items.extend(data if isinstance(data, list) else [])
            next_url = link_next(resp.headers.get("Link"))
            next_params = None  # the next link already carries the query
        return items, pages, None

    async def inventory(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Every repo the token can reach: user affiliations plus every org's repos."""
        repos: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, Any]] = []
        user_repos, _, bad = await self._paginate(
            "/user/repos",
            {"affiliation": "owner,collaborator,organization_member", "per_page": 100},
        )
        if bad is not None:
            raise EvidenceHTTPError(bad.status_code, "listing /user/repos failed")
        for r in user_repos:
            repos.setdefault(r["full_name"].lower(), r)
        orgs, _, bad = await self._paginate("/user/orgs", {"per_page": 100})
        if bad is not None:
            errors.append({"scope": "orgs", "reason": f"/user/orgs HTTP {bad.status_code}"})
            orgs = []
        for org in orgs:
            login = org.get("login")
            org_repos, _, bad = await self._paginate(
                f"/orgs/{login}/repos", {"type": "all", "per_page": 100}
            )
            if bad is not None:
                errors.append({
                    "scope": f"org:{login}",
                    "reason": f"org repo listing HTTP {bad.status_code}",
                })
            for r in org_repos:
                repos.setdefault(r["full_name"].lower(), r)
        ordered = sorted(repos.values(), key=lambda r: r["full_name"].lower())
        return ordered, errors

    async def list_commits(
        self, full_name: str, since: datetime, until: datetime
    ) -> RepoCommits:
        items, pages, bad = await self._paginate(
            f"/repos/{full_name}/commits",
            {"since": iso_z(since), "until": iso_z(until), "per_page": 100},
        )
        if bad is None:
            return RepoCommits("ok", items, pages=pages)
        if bad.status_code == 409:
            return RepoCommits("empty", [], "repository is empty", pages)
        if bad.status_code in (403, 404, 451):
            return RepoCommits("unavailable", [], f"commits HTTP {bad.status_code}", pages)
        raise EvidenceHTTPError(bad.status_code, f"commit listing HTTP {bad.status_code}")

    async def get_commit(self, full_name: str, sha: str) -> dict[str, Any]:
        """Commit detail at SHA, with every page of files."""
        url = f"/repos/{full_name}/commits/{sha}"
        resp = await self._get(url)
        if resp.status_code != 200:
            raise EvidenceHTTPError(resp.status_code, f"commit detail HTTP {resp.status_code}")
        detail = resp.json()
        files = list(detail.get("files") or [])
        next_url = link_next(resp.headers.get("Link"))
        pages = 1
        while next_url:
            if pages >= self.max_pages:
                raise EvidenceHTTPError(None, "page cap reached for commit files")
            more = await self._get(next_url)
            if more.status_code != 200:
                raise EvidenceHTTPError(more.status_code, "commit files page failed")
            files.extend(more.json().get("files") or [])
            next_url = link_next(more.headers.get("Link"))
            pages += 1
        detail["files"] = files
        return detail


# ---------------------------------------------------------------------------
# Pure transforms (unit-tested without HTTP)
# ---------------------------------------------------------------------------


def commit_date(item: dict[str, Any]) -> datetime | None:
    commit = item.get("commit") or {}
    return parse_iso((commit.get("committer") or {}).get("date")) or parse_iso(
        (commit.get("author") or {}).get("date")
    )


def commit_in_window(item: dict[str, Any], start: datetime, end: datetime) -> bool:
    return in_window(commit_date(item), start, end)


def is_merge(item: dict[str, Any]) -> bool:
    return len(item.get("parents") or []) > 1


def blob_url_at_sha(full_name: str, sha: str, path: str) -> str:
    return f"https://github.com/{full_name}/blob/{sha}/{path}"


NUL = "\x00"
NUL_PATCH_EXCLUDED = "nul_bytes_binary_content"


def build_commit_record(full_name: str, detail: dict[str, Any]) -> dict[str, Any]:
    """One commit, exact at its SHA.

    PostgreSQL text and JSONB cannot hold U+0000. A diff containing NUL bytes is
    binary content, so its patch is excluded by name (`patch_excluded`) while the
    file keeps its exact path, counts and blob URL. A stray NUL in a message or
    path is replaced with U+FFFD and the commit is flagged `nul_replaced`.
    """
    sha = detail["sha"]
    replaced = False

    def clean(text: str) -> str:
        nonlocal replaced
        if NUL in text:
            replaced = True
            return text.replace(NUL, "�")
        return text

    message = clean((detail.get("commit") or {}).get("message") or "")
    files = []
    for idx, f in enumerate(detail.get("files") or []):
        path = clean(f.get("filename") or "")
        patch = f.get("patch")
        excluded = None
        if patch is not None and NUL in patch:
            patch, excluded = None, NUL_PATCH_EXCLUDED
        excerpt = None
        truncated = False
        if patch is not None and idx < MAX_FILES_WITH_PATCH:
            excerpt = patch[:PATCH_EXCERPT_CHARS]
            truncated = len(patch) > PATCH_EXCERPT_CHARS
        entry = {
            "path": path,
            "status": f.get("status"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "patch_excerpt": excerpt,
            "patch_truncated": truncated,
            "patch_signature": _patch_signature(patch) if patch is not None else None,
            "blob_url_at_sha": blob_url_at_sha(full_name, sha, path),
        }
        if excluded:
            entry["patch_excluded"] = excluded
        files.append(entry)
    date = commit_date(detail)
    record = {
        "sha": sha,
        "repo": full_name,
        "message": message,
        "committed_at": iso_z(date) if date else None,
        "url": f"https://github.com/{full_name}/commit/{sha}",
        "files": files,
        "reverts": [],
        "reverted_by": [],
    }
    if replaced:
        record["nul_replaced"] = True
    return record


def _patch_signature(patch: str) -> dict[str, list[str]]:
    added: list[str] = []
    removed: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@") or line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.append(line[1:].strip())
    return {"added": sorted(a for a in added if a), "removed": sorted(r for r in removed if r)}


def _patches_invert(earlier: dict[str, Any], later: dict[str, Any]) -> bool:
    a_files = {f["path"]: f for f in earlier["files"]}
    b_files = {f["path"]: f for f in later["files"]}
    if not a_files or set(a_files) != set(b_files):
        return False
    for path, fa in a_files.items():
        sa, sb = fa.get("patch_signature"), b_files[path].get("patch_signature")
        if sa is None or sb is None:
            return False
        if not (sa["added"] or sa["removed"]):
            return False
        if sa["added"] != sb["removed"] or sa["removed"] != sb["added"]:
            return False
    return True


def detect_reversals(commits: list[dict[str, Any]]) -> None:
    """Annotate `reverts` / `reverted_by` in place (message trailers and inverse patches).

    `commits` must be in chronological order (oldest first).
    """
    by_sha = {c["sha"]: c for c in commits}

    def resolve(prefix: str) -> dict[str, Any] | None:
        if prefix in by_sha:
            return by_sha[prefix]
        matches = [c for s, c in by_sha.items() if s.startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    def link(reverter: dict[str, Any], target: dict[str, Any], how: str) -> None:
        if target["sha"] not in reverter["reverts"]:
            reverter["reverts"].append(target["sha"])
            reverter.setdefault("revert_detection", {})[target["sha"]] = how
        if reverter["sha"] not in target["reverted_by"]:
            target["reverted_by"].append(reverter["sha"])

    for c in commits:
        for prefix in _REVERT_SHA.findall(c["message"]):
            target = resolve(prefix.lower())
            if target is not None and target is not c:
                link(c, target, "message")
            elif target is None:
                c.setdefault("reverts_outside_window", []).append(prefix)
    for i, later in enumerate(commits):
        if later["reverts"]:
            continue
        for earlier in reversed(commits[:i]):
            if earlier["reverted_by"] or earlier["sha"] in later["reverts"]:
                continue
            if _patches_invert(earlier, later):
                link(later, earlier, "inverse_patch")
                break


def _scope_and_tickets(message: str) -> tuple[str | None, set[str]]:
    subject = message.splitlines()[0] if message else ""
    m = _CONVENTIONAL.match(subject)
    scope = m.group(2).strip().lower() if m and m.group(2) else None
    tickets = {a or f"#{b}" for a, b in _TICKET.findall(message)}
    return scope, tickets


def group_commits(
    commits: list[dict[str, Any]], window: timedelta = GROUP_WINDOW
) -> list[list[dict[str, Any]]]:
    """Group related commits in one repo (union-find). Chronological input."""
    parent = list(range(len(commits)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    info = []
    for c in commits:
        scope, tickets = _scope_and_tickets(c["message"])
        paths = {
            f["path"] for f in c["files"]
            if f["path"].rsplit("/", 1)[-1].lower() not in _NOISY_SHARED_FILES
        }
        info.append((parse_iso(c["committed_at"]), scope, tickets, paths))
    index = {c["sha"]: i for i, c in enumerate(commits)}
    for i in range(len(commits)):
        di, si, ti, pi = info[i]
        for j in range(i + 1, len(commits)):
            dj, sj, tj, pj = info[j]
            if di and dj and abs(dj - di) > window:
                continue
            if (pi & pj) or (si and si == sj) or (ti & tj):
                union(i, j)
    for c in commits:
        for target in c["reverts"]:
            if target in index:
                union(index[c["sha"]], index[target])
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, c in enumerate(commits):
        groups.setdefault(find(i), []).append(c)
    return list(groups.values())


def group_net_reverted(group: list[dict[str, Any]], by_sha: dict[str, dict[str, Any]]) -> bool:
    memo: dict[str, bool] = {}

    def live(sha: str, depth: int = 0) -> bool:
        if sha in memo:
            return memo[sha]
        if depth > 50:
            return True
        c = by_sha.get(sha)
        result = True
        if c is not None:
            result = not any(live(r, depth + 1) for r in c["reverted_by"])
        memo[sha] = result
        return result

    for c in group:
        if live(c["sha"]) and not c["reverts"]:
            return False
    return True


def low_signal_reason(group: list[dict[str, Any]]) -> str | None:
    paths = [f["path"].rsplit("/", 1)[-1].lower() for c in group for f in c["files"]]
    changed = sum(f.get("additions", 0) + f.get("deletions", 0) for c in group for f in c["files"])
    messages = [c["message"].splitlines()[0] if c["message"] else "" for c in group]
    if paths and all(p in _DEP_FILES for p in paths):
        return "dependency manifest changes only"
    if messages and all(_DEP_MESSAGE.search(m) for m in messages) and changed <= 60:
        return "dependency bump"
    if messages and all(_MODEL_BUMP.search(m) for m in messages) and changed <= 30:
        return "model id bump"
    return None


def group_external_id(full_name: str, shas: list[str]) -> str:
    digest = stable_hash(sorted(shas))[:24]
    return f"{full_name}@{digest}"


def build_group_source(
    full_name: str, group: list[dict[str, Any]], by_sha: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    group = sorted(group, key=lambda c: c["committed_at"] or "")
    shas = [c["sha"] for c in group]
    reverted = group_net_reverted(group, by_sha)
    low = low_signal_reason(group)
    payload = {"repo": full_name, "commits": group}
    first_subject = group[0]["message"].splitlines()[0] if group[0]["message"] else ""
    occurred = parse_iso(group[-1]["committed_at"])
    meta = {
        "repo": full_name,
        "commit_shas": shas,
        "commit_count": len(group),
        "file_count": len({f["path"] for c in group for f in c["files"]}),
        "first_committed_at": group[0]["committed_at"],
        "last_committed_at": group[-1]["committed_at"],
        "reverted": reverted,
        "low_signal": low is not None,
        "low_signal_reason": low,
        "exclude_reason": "reverted" if reverted else ("low_signal" if low else None),
        "has_reversal_links": any(c["reverts"] or c["reverted_by"] for c in group),
    }
    return {
        "external_id": group_external_id(full_name, shas),
        "title": f"{full_name}: {first_subject}"[:500],
        "occurred_at": as_utc(occurred) if occurred else None,
        "url_private": group[-1]["url"],
        "payload": payload,
        "meta": meta,
        "version_hash": stable_hash(payload),
    }
