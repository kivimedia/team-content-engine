"""Specificity and source origin survive without exposing private repo names."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from tce.editorial import packets, selector, solution_names
from tce.evidence import moments
from tce.models.editorial import REJECTION_GATES, EvidenceMoment, EvidenceSource, TopicCandidate

OWNER = uuid4()
CLIENT = uuid4()


def source_moment(kind, ws=OWNER, repo="kivimedia/kmhub"):
    source = EvidenceSource(
        id=uuid4(), workspace_id=ws, source_kind=kind, title="Private source",
        external_id="source", occurred_at=datetime(2026, 10, 21),
        version_hash="a" * 64, payload_private={"repo": repo, "commits": []}, meta={},
    )
    moment = EvidenceMoment(
        id=uuid4(), workspace_id=ws, source_id=source.id,
        source_version_hash=source.version_hash, lesson_summary="A useful distinction",
        excerpt_private="synthetic example", claim_type="demonstrated",
        speaker_confidence="high", sensitivity_flags=[],
        code_refs=[{"repo": repo, "sha": "1" * 40, "path": "src/flow.py"}]
        if kind == "github_commit_group" else None,
    )
    return selector.PoolMoment(moment, source, True)


def proposed(cited, primary_id=None, *, solution_central=False):
    return {
        "moment_ids": [pm.id for pm in cited],
        "primary_moment_id": primary_id,
        "solution_central": solution_central,
        "title": "No and not now need different follow-up",
        "lesson": "A refusal and a delay require different handling.",
        "audience": "coaches", "public_angle": "Clarify the next step.",
        "gates": {g: {"pass": True, "reason": "synthetic evidence"} for g in REJECTION_GATES},
        "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 4},
    }


def test_commit_extractor_supplies_only_a_verified_owner_solution(monkeypatch):
    monkeypatch.setattr(moments, "owner_policy", lambda ws: ws == OWNER)
    approved = source_moment("github_commit_group").source
    prompt = moments._jobs_for_source(approved)[0][0]
    assert "VERIFIED PUBLIC SOLUTION: KM Hub" in prompt
    assert "VERIFIED PUBLIC SOLUTION" not in moments._jobs_for_source(
        source_moment("github_commit_group", CLIENT).source
    )[0][0]
    assert "VERIFIED PUBLIC SOLUTION" not in moments._jobs_for_source(
        source_moment("github_commit_group", repo="kivimedia/private-coach").source
    )[0][0]
    assert "Only a supplied verified public solution" in moments.SYSTEM_PROMPT


def test_selector_shows_verified_solution_separately_and_preserves_private_names(monkeypatch):
    monkeypatch.setattr(selector.news_rules, "owner_policy", lambda ws: ws == OWNER)
    public = source_moment("github_commit_group")
    private = source_moment("github_commit_group", repo="kivimedia/private-coach")
    assert selector._pool_prompt_item(public)["verified_public_solution"] == "KM Hub"
    public.moment.sensitivity_flags = ["client_identity"]
    assert selector._pool_prompt_item(public)["verified_public_solution"] == "KM Hub"
    assert "verified_public_solution" not in selector._pool_prompt_item(private)
    assert "verified_public_solution" not in selector._pool_prompt_item(
        source_moment("github_commit_group", CLIENT)
    )
    assert "verified public solution" in selector.SYSTEM_PROMPT.lower()


def test_selector_recognizes_exact_stored_google_article_url(monkeypatch):
    monkeypatch.setattr(selector.news_rules, "owner_policy", lambda ws: ws == OWNER)
    news = source_moment("news_item")
    news.source.url_private = (
        "http://workspaceupdates.googleblog.com/2026/10/"
        "publish-interactive-apps-from-gemini-app-to-Google-Sites.html"
    )
    assert selector._pool_prompt_item(news)["verified_public_solution"] == "Google Sites"
    news.source.url_private += "?private=x"
    assert "verified_public_solution" not in selector._pool_prompt_item(news)


def test_mixed_evidence_has_one_validated_initiating_kind_or_stays_unknown(monkeypatch):
    monkeypatch.setattr(selector.news_rules, "owner_policy", lambda ws: ws == OWNER)
    call = source_moment("fathom_meeting")
    build = source_moment("github_commit_group")
    pool = [call, build]
    allowed = {pm.id for pm in pool}

    known, rejected = selector.enforce_candidates([proposed(pool, build.id)], pool, allowed)
    assert not rejected and known[0]["gates"]["_primary_source_kind"] == "github_commit_group"
    unknown, rejected = selector.enforce_candidates([proposed(pool)], pool, allowed)
    assert not rejected and "_primary_source_kind" not in unknown[0]["gates"]
    wrong, rejected = selector.enforce_candidates([proposed(pool, "not-cited")], pool, allowed)
    assert not rejected and "_primary_source_kind" not in wrong[0]["gates"]
    single, rejected = selector.enforce_candidates([proposed([call])], [call], {call.id})
    assert not rejected and single[0]["gates"]["_primary_source_kind"] == "fathom_meeting"
    central, rejected = selector.enforce_candidates(
        [proposed([build], build.id, solution_central=True)], [build], {build.id}
    )
    assert not rejected and central[0]["gates"]["_solution_central"] is True


def test_packet_writer_sees_only_a_cited_public_solution(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    citation = {
        "moment_id": str(uuid4()), "source_kind": "github_commit_group",
        "code_refs": [{"repo": "kivimedia/kmhub", "sha": "1" * 40,
                       "path": "src/flow.py"}],
    }
    item = TopicCandidate(
        workspace_id=OWNER, week_start=datetime(2026, 10, 21),
        moment_ids=[citation["moment_id"]], title="A follow-up principle",
        lesson="Different replies need different handling.", audience="coaches",
        public_angle="A useful distinction", gates={"_primary_source_kind": "github_commit_group"},
        citations_private=[citation],
    )
    prompt = packets.build_packet_prompt("strategy", item)
    assert "VERIFIED PUBLIC SOLUTION: KM Hub" in prompt
    assert "Only a verified public solution" in packets.SYSTEM_PROMPT
    citation["code_refs"][0]["repo"] = "kivimedia/private-coach"
    assert "VERIFIED PUBLIC SOLUTION" not in packets.build_packet_prompt("strategy", item)

