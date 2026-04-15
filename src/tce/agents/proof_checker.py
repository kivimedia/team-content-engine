"""Proof Checker agent - verifies factual claims in generated content.

Runs AFTER content writers, BEFORE qa_agent. Searches the web to verify
every factual claim (names, dates, statistics, events, quotes) and builds
a proof trail with source URLs. Sends content back for rewrite if critical
claims can't be verified.
"""

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are a fact-checking research assistant. Your job is to:

1. EXTRACT every factual claim from a social media post
2. CLASSIFY each claim as "critical" or "soft"
3. For each claim, suggest a concise web search query to verify it

CRITICAL claims (MUST be verified):
- Direct quotes attributed to a specific person
- Specific statistics, percentages, or numbers
- Named events, product launches, or announcements
- Dates of specific events
- Company-specific claims (revenue, headcount, features, policies)
- References to published documents, papers, or reports

SOFT claims (OK without source):
- General industry observations ("AI is transforming business")
- Logical arguments and opinions
- Original frameworks or methodologies
- Calls to action
- Rhetorical questions

Return a JSON object:
{
  "claims": [
    {
      "claim": "the exact text or close paraphrase of the claim",
      "type": "critical" or "soft",
      "search_query": "concise search query to verify this claim",
      "context": "brief note on what kind of source would verify this"
    }
  ]
}

Only extract claims that assert something factual. Skip opinions, advice, and rhetorical statements.
Be thorough - miss nothing that a skeptical reader would want a source for.
"""

VERIFY_PROMPT = """\
You are a fact-checking analyst. Given a claim and search results, determine if the claim is verified.

For each claim, assess:
1. Do the search results contain evidence that supports this specific claim?
2. Is the evidence from a credible source?
3. Does the evidence match the details (names, numbers, dates)?

Return a JSON object:
{
  "claims": [
    {
      "claim": "the claim text",
      "status": "verified" | "partially_verified" | "unverified" | "fabricated",
      "confidence": 0.0-1.0,
      "best_source_url": "URL of the best supporting source or null",
      "best_source_title": "title of the best source or null",
      "note": "brief explanation of what was found or not found",
      "suggested_rewrite": "if unverified/fabricated and the claim is critical, suggest how to rewrite it using verified facts. null if verified."
    }
  ]
}

Status definitions:
- verified: Clear evidence found from credible source
- partially_verified: Related info found but details don't fully match
- unverified: No evidence found (claim might be true but can't confirm)
- fabricated: Evidence contradicts the claim

Be strict. "Partially verified" means some aspect checks out but not all details.
"Verified" means a credible source clearly supports the specific claim made.
"""

REWRITE_PROMPT = """\
You are a content editor. The proof checker found unverified claims in this post.
Rewrite the post to fix ONLY the flagged sections. Keep the voice, tone, structure,
and all verified parts exactly the same.

Rules:
- Replace unverified statistics with verified ones from the provided sources
- Replace unverified quotes with paraphrases or remove them
- Replace unverified events/dates with verified alternatives
- If a claim can't be fixed, remove it and smooth over the gap
- Do NOT add new claims - only fix or remove broken ones
- Keep the post roughly the same length
- Preserve the hook, CTA, and overall narrative arc
"""


@register_agent
class ProofChecker(AgentBase):
    name = "proof_checker"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Verify factual claims in generated posts and build a proof trail."""
        facebook_post = context.get("facebook_draft", {}).get("post", "") or context.get("facebook_post", "")
        linkedin_post = context.get("linkedin_draft", {}).get("post", "") or context.get("linkedin_post", "")

        if not facebook_post and not linkedin_post:
            self._report("No post content found - skipping proof check")
            return {"proof_trail": [], "proof_status": "skipped"}

        # Use whichever post is longer (they usually share the same claims)
        primary_post = facebook_post if len(facebook_post) >= len(linkedin_post) else linkedin_post
        platform = "facebook" if len(facebook_post) >= len(linkedin_post) else "linkedin"
        self._report(f"Checking {platform} post ({len(primary_post)} chars)")

        # Step 1: Extract claims
        self._report("Step 1/4: Extracting factual claims...")
        extract_response = await self._call_llm(
            messages=[{"role": "user", "content": f"Extract all factual claims from this post:\n\n{primary_post}"}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.2,
        )
        extract_text = self._extract_text(extract_response)
        try:
            extracted = self._parse_json_response(extract_text)
        except Exception:
            self._report("Failed to parse claim extraction - passing through")
            return {"proof_trail": [], "proof_status": "error"}

        claims = extracted.get("claims", [])
        critical_claims = [c for c in claims if c.get("type") == "critical"]
        soft_claims = [c for c in claims if c.get("type") != "critical"]
        self._report(f"Found {len(critical_claims)} critical + {len(soft_claims)} soft claims")

        if not critical_claims:
            self._report("No critical claims to verify - post is opinion/advice based")
            return {
                "proof_trail": [{"claim": c["claim"], "type": "soft", "status": "skipped"} for c in soft_claims],
                "proof_status": "verified",
            }

        # Step 2: Web search for each critical claim
        self._report(f"Step 2/4: Searching for evidence ({len(critical_claims)} claims)...")
        from tce.services.web_search import WebSearchService
        search = WebSearchService()

        search_results_by_claim = []
        for i, claim in enumerate(critical_claims):
            query = claim.get("search_query", claim["claim"][:100])
            self._report(f"  [{i+1}/{len(critical_claims)}] Searching: {query[:80]}")
            try:
                results = await search.search(query, count=5)
            except Exception:
                results = []
            search_results_by_claim.append({
                "claim": claim["claim"],
                "type": "critical",
                "search_query": query,
                "context": claim.get("context", ""),
                "search_results": [
                    {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
                    for r in results
                ],
            })

        # Step 3: Verify claims against search results
        self._report("Step 3/4: Verifying claims against sources...")
        verify_input = json.dumps(search_results_by_claim, indent=2)
        verify_response = await self._call_llm(
            messages=[{"role": "user", "content": f"Verify these claims against the search results:\n\n{verify_input}"}],
            system=VERIFY_PROMPT,
            max_tokens=4096,
            temperature=0.1,
        )
        verify_text = self._extract_text(verify_response)
        try:
            verified = self._parse_json_response(verify_text)
        except Exception:
            self._report("Failed to parse verification - marking all as unverified")
            verified = {"claims": []}

        # Build proof trail
        proof_trail = []
        needs_rewrite = False
        rewrite_instructions = []

        for vc in verified.get("claims", []):
            status = vc.get("status", "unverified")
            entry = {
                "claim": vc.get("claim", ""),
                "type": "critical",
                "status": status,
                "confidence": vc.get("confidence", 0),
                "source_url": vc.get("best_source_url"),
                "source_title": vc.get("best_source_title"),
                "note": vc.get("note", ""),
                "search_query": next(
                    (s["search_query"] for s in search_results_by_claim if s["claim"] == vc.get("claim")),
                    "",
                ),
            }
            proof_trail.append(entry)

            if status in ("unverified", "fabricated"):
                needs_rewrite = True
                rewrite_instructions.append({
                    "claim": vc["claim"],
                    "status": status,
                    "note": vc.get("note", ""),
                    "suggested_rewrite": vc.get("suggested_rewrite"),
                    "available_sources": next(
                        (s["search_results"][:3] for s in search_results_by_claim if s["claim"] == vc.get("claim")),
                        [],
                    ),
                })

            status_icon = {"verified": "+", "partially_verified": "~", "unverified": "?", "fabricated": "X"}.get(status, "?")
            self._report(f"  [{status_icon}] {vc.get('claim', '')[:80]}")

        # Add soft claims as skipped
        for sc in soft_claims:
            proof_trail.append({"claim": sc["claim"], "type": "soft", "status": "skipped"})

        verified_count = sum(1 for p in proof_trail if p["status"] == "verified")
        partial_count = sum(1 for p in proof_trail if p["status"] == "partially_verified")
        unverified_count = sum(1 for p in proof_trail if p["status"] in ("unverified", "fabricated"))
        self._report(f"Results: {verified_count} verified, {partial_count} partial, {unverified_count} unverified")

        # Step 4: Rewrite if needed
        if needs_rewrite:
            self._report("Step 4/4: Rewriting to fix unverified claims...")
            rewrite_context = json.dumps(rewrite_instructions, indent=2)

            # Rewrite Facebook post
            if facebook_post:
                fb_rewrite = await self._rewrite_post(facebook_post, rewrite_context, "Facebook")
                if fb_rewrite:
                    context["facebook_draft"] = context.get("facebook_draft", {})
                    context["facebook_draft"]["post"] = fb_rewrite
                    context["facebook_post"] = fb_rewrite
                    self._report("  Facebook post rewritten with verified facts")

            # Rewrite LinkedIn post
            if linkedin_post:
                li_rewrite = await self._rewrite_post(linkedin_post, rewrite_context, "LinkedIn")
                if li_rewrite:
                    context["linkedin_draft"] = context.get("linkedin_draft", {})
                    context["linkedin_draft"]["post"] = li_rewrite
                    context["linkedin_post"] = li_rewrite
                    self._report("  LinkedIn post rewritten with verified facts")

            overall_status = "rewritten"
        elif unverified_count == 0:
            self._report("Step 4/4: All claims verified - no rewrite needed")
            overall_status = "verified"
        else:
            self._report("Step 4/4: Some claims partially verified - passing through with warnings")
            overall_status = "partial"

        self._report(f"Proof check complete: {overall_status}")

        return {
            "proof_trail": proof_trail,
            "proof_status": overall_status,
            "proof_stats": {
                "total_claims": len(proof_trail),
                "critical": len(critical_claims),
                "verified": verified_count,
                "partial": partial_count,
                "unverified": unverified_count,
                "rewritten": needs_rewrite,
            },
        }

    async def _rewrite_post(self, post: str, rewrite_context: str, platform: str) -> str | None:
        """Rewrite a post to fix unverified claims."""
        try:
            response = await self._call_llm(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Rewrite this {platform} post to fix the unverified claims.\n\n"
                        f"ORIGINAL POST:\n{post}\n\n"
                        f"CLAIMS TO FIX:\n{rewrite_context}\n\n"
                        "Return ONLY the rewritten post text, nothing else."
                    ),
                }],
                system=REWRITE_PROMPT,
                max_tokens=4096,
                temperature=0.3,
            )
            return self._extract_text(response).strip()
        except Exception as e:
            self._report(f"  Rewrite failed for {platform}: {e}")
            return None
