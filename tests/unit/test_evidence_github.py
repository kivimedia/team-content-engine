"""GitHub collector: inventory, pagination, access states, reversals, grouping. Synthetic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from tce.evidence.collect import collect_github
from tce.evidence.common import RetryPolicy
from tce.evidence.github import (
    GitHubClient,
    build_commit_record,
    detect_reversals,
    group_commits,
    link_next,
    low_signal_reason,
)
from tce.models.editorial import EvidenceCollectionRun, EvidenceSource

WS = uuid.uuid4()
START = datetime(2026, 9, 7, tzinfo=UTC)
END = datetime(2026, 9, 14, tzinfo=UTC)
API = "https://api.github.test"


def sha(n: int) -> str:
    return f"{n:040x}"


def when(hours: float) -> str:
    return (START + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def listing_item(n: int, date: str, parents: int = 1) -> dict:
    return {
        "sha": sha(n),
        "commit": {"message": "x", "committer": {"date": date}, "author": {"date": date}},
        "parents": [{"sha": sha(9000 + i)} for i in range(parents)],
    }


def detail(repo: str, n: int, date: str, message: str, files: list[tuple[str, str]]) -> dict:
    return {
        "sha": sha(n),
        "html_url": f"https://github.com/{repo}/commit/{sha(n)}",
        "commit": {"message": message, "committer": {"date": date}, "author": {"date": date}},
        "parents": [{"sha": sha(9999)}],
        "files": [
            {
                "filename": path,
                "status": "modified",
                "additions": patch.count("\n+"),
                "deletions": patch.count("\n-"),
                "patch": patch,
                # the API's own blob_url points at a branch; we must not use it
                "blob_url": f"https://github.com/{repo}/blob/main/{path}",
            }
            for path, patch in files
        ],
    }


GAMMA = "org/gamma"
GAMMA_DETAILS = {
    sha(1): detail(GAMMA, 1, when(1), "feat(billing): add invoice reminder",
                   [("billing/reminder.py", "@@ -1 +1 @@\n+send reminder\n-pass")]),
    sha(2): detail(GAMMA, 2, when(3), "fix(billing): reminder wording",
                   [("billing/reminder.py", "@@ -1 +1 @@\n+send a reminder\n-send reminder")]),
    sha(4): detail(GAMMA, 4, when(5), "feat(search): add fuzzy matching",
                   [("search/query.py", "@@ -1 +1 @@\n+fuzzy = True\n-fuzzy = False")]),
    sha(3): detail(GAMMA, 3, when(7),
                   f'Revert "feat(search): add fuzzy matching"\n\nThis reverts commit {sha(4)}.',
                   [("search/query.py", "@@ -1 +1 @@\n+fuzzy = False\n-fuzzy = True")]),
    sha(5): detail(GAMMA, 5, when(9), "docs: explain setup",
                   [("docs/guide.md", "@@ -1 +1 @@\n+step one\n-todo")]),
    sha(7): detail(GAMMA, 7, when(30), "tweak timeout",
                   [("config/app.yaml", "@@ -1 +1 @@\n+timeout: 30\n-timeout: 10")]),
    sha(8): detail(GAMMA, 8, when(31), "put it back",
                   [("config/app.yaml", "@@ -1 +1 @@\n+timeout: 10\n-timeout: 30")]),
    sha(10): detail(GAMMA, 10, when(40), "chore(deps): bump httpx",
                    [("package-lock.json", "@@ -1 +1 @@\n+1.2\n-1.1")]),
}


class FakeGitHub:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.rate_limited = False
        self.detail_calls: list[str] = []

    def page(self, request, items, next_page: str | None):
        headers = {}
        if next_page:
            headers["Link"] = (
                f'<{request.url.copy_set_param("page", next_page)}>; rel="next", '
                f'<{request.url.copy_set_param("page", "9")}>; rel="last"'
            )
        return httpx.Response(200, json=items, headers=headers)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        path = request.url.path
        page = request.url.params.get("page", "1")
        if path == "/user/repos":
            assert "organization_member" in request.url.params.get("affiliation", "")
            if page == "1":
                return self.page(request, [{"full_name": "o/alpha"}, {"full_name": "o/beta"}], "2")
            return self.page(
                request,
                [{"full_name": GAMMA}, {"full_name": "o/empty"}, {"full_name": "o/secret"}],
                None,
            )
        if path == "/user/orgs":
            return self.page(request, [{"login": "org"}], None)
        if path == "/orgs/org/repos":
            return self.page(request, [{"full_name": GAMMA}, {"full_name": "org/delta"}], None)
        if path == "/repos/o/alpha/commits":
            if page == "1":
                return self.page(
                    request, [listing_item(100 + i, when(1 + i * 0.5)) for i in range(100)], "2"
                )
            return self.page(
                request, [listing_item(100 + i, when(1 + i * 0.5)) for i in range(100, 150)], None
            )
        if path.startswith("/repos/o/alpha/commits/"):
            n = int(path.rsplit("/", 1)[-1], 16)
            self.detail_calls.append(path)
            return httpx.Response(200, json=detail(
                "o/alpha", n, when(1 + (n - 100) * 0.5), f"feat: item {n}",
                [(f"items/f{n}.txt", "@@ -0,0 +1 @@\n+hello")],
            ))
        if path == "/repos/o/beta/commits":
            return httpx.Response(403, json={"message": "Resource not accessible"},
                                  headers={"X-RateLimit-Remaining": "4000"})
        if path == "/repos/o/empty/commits":
            return httpx.Response(409, json={"message": "Git Repository is empty."})
        if path == "/repos/o/secret/commits":
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/org/delta/commits":
            if not self.rate_limited:
                self.rate_limited = True
                return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers={
                    "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(self.now + 5)),
                })
            return self.page(request, [], None)
        if path == f"/repos/{GAMMA}/commits":
            items = [listing_item(int(s, 16), d["commit"]["committer"]["date"])
                     for s, d in GAMMA_DETAILS.items()]
            items.append(listing_item(11, when(12), parents=2))  # merge
            items.append(listing_item(12, "2026-09-01T00:00:00Z"))  # API filter not trusted
            return self.page(request, items, None)
        if path.startswith(f"/repos/{GAMMA}/commits/"):
            return httpx.Response(200, json=GAMMA_DETAILS[path.rsplit("/", 1)[-1]])
        return httpx.Response(500)


def make_client(fake: FakeGitHub, sleeps: list[float]) -> GitHubClient:
    async def sleep(s: float) -> None:
        sleeps.append(s)

    return GitHubClient(
        "test-token", base_url=API, transport=httpx.MockTransport(fake.handler),
        sleep=sleep, clock=lambda: fake.now, retry=RetryPolicy(max_attempts=3, max_wait_s=60),
    )


async def _collect(sessionmaker):
    fake = FakeGitHub()
    sleeps: list[float] = []
    client = make_client(fake, sleeps)
    run_id = await collect_github(sessionmaker, WS, START, END, client=client)
    await client.aclose()
    async with sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    return run, fake, sleeps


def test_link_next():
    header = f'<{API}/x?page=2>; rel="next", <{API}/x?page=5>; rel="last"'
    assert link_next(header) == f"{API}/x?page=2"
    assert link_next(f'<{API}/x?page=5>; rel="last"') is None


async def test_inventory_pagination_org_dedupe_and_access_states(editorial_sessionmaker):
    run, fake, sleeps = await _collect(editorial_sessionmaker)
    repo_items = {i["external_id"]: i for i in run.items if i["kind"] == "repo"}
    assert set(repo_items) == {"o/alpha", "o/beta", GAMMA, "o/empty", "o/secret", "org/delta"}
    assert run.counts["repos_listed"] == 6  # gamma listed twice, counted once
    assert repo_items["o/beta"]["state"] == "unavailable"
    assert repo_items["o/secret"]["state"] == "unavailable"
    assert repo_items["o/empty"]["state"] == "processed"
    assert repo_items["o/empty"]["reason"] == "empty repository"
    assert repo_items["org/delta"]["state"] == "processed"  # after the rate-limit wait
    assert any(5 <= s <= 7 for s in sleeps)
    # >100 commits fully paginated and every commit detail fetched
    assert len(fake.detail_calls) == 150
    assert "150 commits" in repo_items["o/alpha"]["reason"]
    assert run.counts["merge_commits_skipped"] == 1
    assert run.counts["commits_outside_window"] == 1
    assert run.complete is True
    assert run.status == "partial"  # two repos unavailable


async def test_grouping_reversals_low_signal_and_blob_urls(editorial_sessionmaker):
    run, _, _ = await _collect(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        rows = (await s.execute(
            select(EvidenceSource).where(EvidenceSource.external_id.like(f"{GAMMA}@%"))
        )).scalars().all()
    groups = {tuple(sorted(r.meta["commit_shas"])): r for r in rows}
    assert set(groups) == {
        (sha(1), sha(2)), (sha(3), sha(4)), (sha(5),), (sha(7), sha(8)), (sha(10),),
    }
    assert groups[(sha(3), sha(4))].meta["reverted"] is True
    assert groups[(sha(7), sha(8))].meta["reverted"] is True  # inverse patches
    assert groups[(sha(1), sha(2))].meta["reverted"] is False
    assert groups[(sha(10),)].meta["low_signal"] is True
    assert groups[(sha(1), sha(2))].meta["exclude_reason"] is None

    commits = {c["sha"]: c for c in groups[(sha(3), sha(4))].payload_private["commits"]}
    assert commits[sha(3)]["reverts"] == [sha(4)]
    assert commits[sha(4)]["reverted_by"] == [sha(3)]
    inv = {c["sha"]: c for c in groups[(sha(7), sha(8))].payload_private["commits"]}
    assert inv[sha(8)]["reverts"] == [sha(7)]
    assert inv[sha(8)]["revert_detection"][sha(7)] == "inverse_patch"

    for row in rows:
        for c in row.payload_private["commits"]:
            assert c["url"] == f"https://github.com/{GAMMA}/commit/{c['sha']}"
            for f in c["files"]:
                assert f["blob_url_at_sha"] == (
                    f"https://github.com/{GAMMA}/blob/{c['sha']}/{f['path']}"
                )
                assert "/blob/main/" not in f["blob_url_at_sha"]

    excluded = [i for i in run.items if i.get("kind") == "group" and i["state"] == "excluded"]
    assert len(excluded) == 3


async def test_rerun_creates_no_duplicates(editorial_sessionmaker):
    await _collect(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        first = (await s.execute(select(func.count()).select_from(EvidenceSource))).scalar()
    run2, _, _ = await _collect(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        second = (await s.execute(select(func.count()).select_from(EvidenceSource))).scalar()
    assert first == second
    group_states = {i["state"] for i in run2.items if i.get("kind") == "group"}
    assert group_states <= {"unchanged", "excluded"}
    assert all(
        i.get("upsert") == "unchanged" for i in run2.items if i["state"] == "excluded"
    )


def test_patch_truncation_keeps_exact_sha_and_path():
    long_patch = "@@ -1 +1 @@\n" + "+line\n" * 2000
    rec = build_commit_record(
        "o/r", detail("o/r", 42, when(1), "feat: big", [("a/b.py", long_patch)])
    )
    f = rec["files"][0]
    assert f["patch_truncated"] is True
    assert len(f["patch_excerpt"]) < len(long_patch)
    assert f["blob_url_at_sha"] == f"https://github.com/o/r/blob/{sha(42)}/a/b.py"


def test_grouping_by_ticket_and_time_limit():
    recs = [
        build_commit_record("o/r", detail("o/r", 1, when(0), "Fix ABC-12 login", [("a.py", "+x")])),
        build_commit_record("o/r", detail("o/r", 2, when(20), "ABC-12 tests", [("b.py", "+y")])),
        build_commit_record("o/r", detail("o/r", 3, when(200), "touch a", [("a.py", "+z")])),
    ]
    detect_reversals(recs)
    groups = group_commits(recs)
    shas = sorted(sorted(c["sha"] for c in g) for g in groups)
    assert shas == [[sha(1), sha(2)], [sha(3)]]


def test_model_bump_is_low_signal():
    rec = build_commit_record("o/r", detail(
        "o/r", 1, when(0), "chore: bump agents to newer model",
        [("src/settings.py", "@@ -1 +1 @@\n+model = 'b'\n-model = 'a'")],
    ))
    assert low_signal_reason([rec]) == "model id bump"


# --- NUL bytes: PostgreSQL text/JSONB cannot store U+0000 --------------------
# A live run lost a whole repository to "unsupported Unicode escape sequence,
# U+0000 cannot be converted to text" because one committed file carried NUL
# bytes in its diff. The file must stay in the record (exact path, counts, blob
# URL at the SHA) with its patch explicitly excluded, never silently dropped.

NUL = chr(0)


def _has_nul(value) -> bool:
    import json

    return "\\u0000" in json.dumps(value)


def test_nul_patch_is_excluded_with_exact_provenance():
    binary_like = f"@@ -0,0 +1,2 @@\n+PK{NUL}{NUL}\n+{NUL}{NUL}data"
    rec = build_commit_record(
        "o/r",
        detail("o/r", 77, when(1), "feat: add fixture", [
            ("fixtures/sample.bin", binary_like),
            ("src/app.py", "@@ -1 +1 @@\n+ok = True\n-ok = False"),
        ]),
    )
    assert not _has_nul(rec)
    binf, textf = rec["files"]
    assert binf["path"] == "fixtures/sample.bin"
    assert binf["blob_url_at_sha"] == f"https://github.com/o/r/blob/{sha(77)}/fixtures/sample.bin"
    assert binf["additions"] == 2
    assert binf["patch_excerpt"] is None
    assert binf["patch_signature"] is None
    assert binf["patch_excluded"] == "nul_bytes_binary_content"
    # the ordinary file in the same commit is untouched
    assert textf["patch_excerpt"].endswith("-ok = False")
    assert "patch_excluded" not in textf


def test_nul_in_message_or_path_is_replaced_and_flagged():
    rec = build_commit_record(
        "o/r", detail("o/r", 78, when(1), f"fix:{NUL} odd message", [(f"a{NUL}b.txt", "@@ +x")])
    )
    assert not _has_nul(rec)
    assert rec["message"] == "fix:� odd message"
    assert rec["files"][0]["path"] == "a�b.txt"
    assert rec["nul_replaced"] is True


async def test_repo_with_nul_patch_is_collected_not_failed(editorial_sessionmaker):
    class NulGitHub(FakeGitHub):
        def handler(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/user/repos":
                return self.page(request, [{"full_name": "o/nul"}], None)
            if path == "/user/orgs":
                return self.page(request, [], None)
            if path == "/repos/o/nul/commits":
                return self.page(request, [listing_item(500, when(2))], None)
            if path == f"/repos/o/nul/commits/{sha(500)}":
                return httpx.Response(200, json=detail(
                    "o/nul", 500, when(2), "feat(export): add sample archive",
                    [("export/sample.zip", f"@@ -0,0 +1 @@\n+{NUL}PK{NUL}"),
                     ("export/writer.py", "@@ -1 +1 @@\n+write = True\n-write = False")],
                ))
            return httpx.Response(500)

    fake = NulGitHub()
    client = make_client(fake, [])
    run_id = await collect_github(editorial_sessionmaker, WS, START, END, client=client)
    await client.aclose()
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
        rows = (await s.execute(
            select(EvidenceSource).where(EvidenceSource.external_id.like("o/nul@%"))
        )).scalars().all()
    assert (run.counts or {}).get("failed", 0) == 0, run.errors
    assert len(rows) == 1
    payload = rows[0].payload_private
    assert not _has_nul(payload) and not _has_nul(rows[0].meta)
    files = {f["path"]: f for c in payload["commits"] for f in c["files"]}
    assert files["export/sample.zip"]["patch_excluded"] == "nul_bytes_binary_content"
    assert files["export/writer.py"]["patch_excerpt"]


async def test_storage_backstop_replaces_and_counts_nul(editorial_sessionmaker):
    from tce.evidence.collect import upsert_source

    data = {
        "external_id": "mtg-1",
        "title": f"Weekly{NUL} sync",
        "occurred_at": START,
        "version_hash": "h1",
        "payload": {"turns": [{"text": f"a{NUL}b", f"k{NUL}": [f"{NUL}{NUL}"]}]},
        "meta": {"note": "x"},
    }
    async with editorial_sessionmaker() as s:
        state, row = await upsert_source(s, WS, "fathom_meeting", data, uuid.uuid4())
        await s.commit()
    assert state == "processed"
    assert not _has_nul(row.payload_private) and NUL not in row.title
    assert row.meta == {"note": "x", "nul_chars_replaced": 5}
    assert row.version_hash == "h1"  # identity with earlier runs is unchanged
