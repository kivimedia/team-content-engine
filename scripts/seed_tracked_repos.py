"""Seed tracked_repos with the kivimedia family of projects.

Usage:
    python scripts/seed_tracked_repos.py
    python scripts/seed_tracked_repos.py --dry-run
    python scripts/seed_tracked_repos.py --include-private

Priority is computed from last-pushed date (via gh api) so the weekly
spotlight scheduler picks the freshest repo first.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `tce` importable when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select  # noqa: E402

from tce.db.session import async_session  # noqa: E402
from tce.models.tracked_repo import TrackedRepo  # noqa: E402


# Known kivimedia repos - pulled from your kmboards registry in ~/.claude/CLAUDE.md
# Tags help the `repo_examples` matcher surface the right repo for a given topic.
KNOWN_REPOS: list[dict] = [
    {
        "url": "https://github.com/kivimedia/boards",
        "display_name": "KMBoards",
        "tags": ["agency", "project-management", "nextjs", "supabase", "ai-agents"],
    },
    {
        "url": "https://github.com/kivimedia/choirmind",
        "display_name": "ChoirMind",
        "tags": ["choir", "music", "rtl", "hebrew", "nextjs"],
    },
    {
        "url": "https://github.com/kivimedia/carolinahq",
        "display_name": "CarolinaHQ",
        "tags": ["balloons", "event", "carolina", "nextjs"],
    },
    {
        "url": "https://github.com/kivimedia/KaraokeMadness",
        "display_name": "Karaoke Madness",
        "tags": ["karaoke", "music", "events", "nextjs"],
    },
    {
        "url": "https://github.com/kivimedia/deploy-helper",
        "display_name": "DeployHelper",
        "tags": ["deploy", "vercel", "ci-cd", "devops"],
    },
    {
        "url": "https://github.com/kivimedia/appspotlight",
        "display_name": "AppSpotlight",
        "tags": ["apps", "portfolio", "spotlight"],
    },
    {
        "url": "https://github.com/kivimedia/gigboard",
        "display_name": "GigBoard",
        "tags": ["gigs", "music", "bookings"],
    },
    {
        "url": "https://github.com/kivimedia/ghost-hunter",
        "display_name": "Ghost Hunter",
        "tags": ["scrape", "automation"],
    },
    {
        "url": "https://github.com/kivimedia/harmony-hub",
        "display_name": "Harmony Hub",
        "tags": ["music", "harmony"],
    },
    {
        "url": "https://github.com/kivimedia/kmshake",
        "display_name": "KM Shake",
        "tags": ["shake", "motion"],
    },
    {
        "url": "https://github.com/kivimedia/lavabowl",
        "display_name": "LavaBowl",
        "tags": ["games", "ai", "sandbox"],
    },
    {
        "url": "https://github.com/kivimedia/sendtoamram",
        "display_name": "Send to Amram",
        "tags": ["logistics", "israel"],
    },
    {
        "url": "https://github.com/kivimedia/inventory-plus",
        "display_name": "Stages Plus / Inventory Plus",
        "tags": ["inventory", "stages", "events"],
    },
    {
        "url": "https://github.com/kivimedia/export-hats",
        "display_name": "Export Hats",
        "tags": ["export", "hats", "ecommerce"],
    },
    {
        "url": "https://github.com/kivimedia/watch-video-skill",
        "display_name": "CutSense",
        "tags": ["video", "ai-editing", "cli"],
    },
    {
        "url": "https://github.com/kivimedia/marizai",
        "display_name": "MarizAI",
        "tags": ["ai", "agents", "cli"],
    },
    {
        "url": "https://github.com/kivimedia/courseiq",
        "display_name": "CourseIQ",
        "tags": ["courses", "cli", "ai"],
    },
    {
        "url": "https://github.com/kivimedia/testimonial-cutter",
        "display_name": "Testimonial Editor",
        "tags": ["testimonial", "video", "desktop"],
    },
    {
        "url": "https://github.com/kivimedia/matan-magic-crm",
        "display_name": "Matan Magic CRM",
        "tags": ["crm", "magic"],
    },
]


def _gh_via_cli(path: str) -> dict | None:
    try:
        result = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        import json as _json

        return _json.loads(result.stdout)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _gh_via_rest(path: str) -> dict | None:
    """Direct REST call using TCE_GITHUB_PAT. Works on the VPS where `gh` isn't installed."""
    import json as _json
    import os as _os
    import urllib.error
    import urllib.request

    pat = _os.environ.get("TCE_GITHUB_PAT") or _os.environ.get("GITHUB_TOKEN") or ""
    # Pull from .env file too
    if not pat:
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("TCE_GITHUB_PAT="):
                    pat = line.split("=", 1)[1].strip()
                    break
    url = "https://api.github.com/" + path.lstrip("/")
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "tce-seed-script")
    if pat:
        req.add_header("Authorization", f"Bearer {pat}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def gh_api(path: str) -> dict | None:
    """Fetch a GitHub API path via `gh` CLI, falling back to direct REST with TCE_GITHUB_PAT."""
    data = _gh_via_cli(path)
    if data is not None:
        return data
    return _gh_via_rest(path)


async def seed(dry_run: bool = False, include_private: bool = True) -> None:
    """Upsert KNOWN_REPOS into the tracked_repos table."""
    print(f"Seeding {len(KNOWN_REPOS)} repos (dry_run={dry_run})...")

    # Enrich each repo with live GitHub metadata (last pushed, language, private)
    enriched: list[dict] = []
    for entry in KNOWN_REPOS:
        url = entry["url"]
        parts = url.rstrip("/").split("/")
        owner, name = parts[-2], parts[-1]
        meta = gh_api(f"repos/{owner}/{name}") or {}
        is_public = not meta.get("private", False)
        last_pushed = meta.get("pushed_at")
        default_branch = meta.get("default_branch") or "main"
        language = meta.get("language")
        description = meta.get("description") or ""

        if not meta:
            print(f"  [skip] {owner}/{name} - gh api returned nothing (404 or auth)")
            continue
        if not include_private and not is_public:
            print(f"  [skip] {owner}/{name} - private and --include-private not set")
            continue

        priority = 0.0
        last_commit_at = None
        if last_pushed:
            try:
                last_commit_at = datetime.fromisoformat(
                    last_pushed.replace("Z", "+00:00")
                )
                age_days = (
                    datetime.now(timezone.utc) - last_commit_at
                ).total_seconds() / 86400
                # 100 points for pushed today; 0 for >= 30 days old
                priority = max(0.0, 100.0 - (age_days * 100 / 30))
            except ValueError:
                pass

        # Bonus: public repos get +5 so they beat stale private ones of same age.
        if is_public:
            priority += 5

        enriched.append(
            {
                **entry,
                "owner": owner,
                "name": name,
                "is_public": is_public,
                "description": description,
                "language": language,
                "default_branch": default_branch,
                "priority_score": round(priority, 2),
                "last_commit_at": last_commit_at,
            }
        )

    # Sort so the freshest / public repos get the highest priority_score.
    enriched.sort(key=lambda r: r["priority_score"], reverse=True)
    print(f"Enriched {len(enriched)} repos.")

    if dry_run:
        print("\nDry run - would insert:")
        for r in enriched:
            print(
                f"  {r['priority_score']:>6.1f}  {r['owner']}/{r['name']:<30}"
                f"  public={r['is_public']}  lang={r.get('language')}"
                f"  last_push={r.get('last_commit_at')}"
            )
        return

    async with async_session() as db:
        for r in enriched:
            slug = f"{r['owner']}-{r['name']}".lower()
            existing = (
                await db.execute(
                    select(TrackedRepo).where(TrackedRepo.slug == slug).limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                # Update freshness data but preserve user toggles.
                existing.display_name = existing.display_name or r["display_name"]
                existing.description = r["description"] or existing.description
                existing.language = r["language"] or existing.language
                existing.default_branch = r["default_branch"] or existing.default_branch
                existing.is_public = r["is_public"]
                existing.last_commit_at = r["last_commit_at"]
                existing.priority_score = r["priority_score"]
                if not existing.tags:
                    existing.tags = r.get("tags")
                action = "updated"
            else:
                repo = TrackedRepo(
                    repo_url=r["url"],
                    slug=slug,
                    display_name=r["display_name"],
                    description=r["description"],
                    language=r["language"],
                    default_branch=r["default_branch"],
                    is_public=r["is_public"],
                    last_commit_at=r["last_commit_at"],
                    priority_score=r["priority_score"],
                    tags=r.get("tags"),
                    include_examples_in_posts=True,
                    blocked_topics=[],
                )
                db.add(repo)
                action = "inserted"
            print(
                f"  [{action}] {slug:<40}  priority={r['priority_score']:>6.1f}"
                f"  public={r['is_public']}"
            )
        await db.commit()

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed tracked_repos for TCE.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-private",
        action="store_true",
        help="Only seed public repos.",
    )
    args = parser.parse_args()
    asyncio.run(seed(dry_run=args.dry_run, include_private=not args.skip_private))


if __name__ == "__main__":
    main()
