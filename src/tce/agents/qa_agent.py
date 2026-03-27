"""QA Agent — 12-dimension quality scoring with pass/fail gates (PRD Section 45)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.schemas.common import QA_DIMENSIONS, QA_THRESHOLDS, QA_WEIGHTS

SYSTEM_PROMPT = """\
You are the QA Agent for Team Content Engine. You are the last gate before content \
goes to the operator for approval.

Score this PostPackage on all 12 QA dimensions. Each dimension is scored 1-10.

SCORING DIMENSIONS:
1. evidence_completeness (pass >= 7, weight 12%) — All hard claims have source support
2. freshness (pass >= 7, weight 8%) — Sources are current
3. clarity (pass >= 7, weight 12%) — Thesis is clear, structure readable
4. novelty (pass >= 6, weight 8%) — Post adds value beyond what's already published
5. non_cloning (pass >= 8, weight 12%) — Similarity to source corpus below threshold
6. audience_fit (pass >= 7, weight 8%) — Post addresses target audience
7. cta_honesty (pass >= 9, weight 8%) — CTA is fulfillable and not misleading
8. platform_fit (pass >= 7, weight 5%) — Tone, length, format match platform
9. visual_coherence (pass >= 6, weight 5%) — Image prompts match thesis and mood
10. house_voice_fit (pass >= 7, weight 5%) — Sounds like house voice, not a clone
11. humanitarian_sensitivity (pass >= 8, weight 10%) — Respects human dignity and context
12. founder_voice_alignment (pass >= 7, weight 7%) — Reflects founder's personal voice

HARD RULES:
- If humanitarian_sensitivity < 8: CANNOT pass regardless of composite
- If cta_honesty < 9: CANNOT pass
- Be specific in justifications
- If unsure about a score, round DOWN

OUTPUT FORMAT: JSON with dimension_scores, composite_score, pass_status, \
blocking_issues, revision_suggestions, humanitarian_flags
"""


@register_agent
class QAAgent(AgentBase):
    name = "qa_agent"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Score a PostPackage on 12 QA dimensions."""
        facebook_post = context.get("facebook_draft", {}).get("facebook_post", "")
        linkedin_post = context.get("linkedin_draft", {}).get("linkedin_post", "")
        hook_variants = context.get("facebook_draft", {}).get("hook_variants", [])
        cta_package = context.get("cta_package", {})
        image_prompts = context.get("image_prompts", [])
        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        founder_voice = context.get("founder_voice", {})

        prompt_parts = [
            f"FACEBOOK POST:\n{facebook_post}",
            f"\nLINKEDIN POST:\n{linkedin_post}",
            f"\nHOOK VARIANTS:\n{json.dumps(hook_variants)}",
            f"\nCTA FLOW:\n{json.dumps(cta_package)}",
            f"\nIMAGE PROMPTS:\n{json.dumps(image_prompts, indent=2)}",
            f"\nSTORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"\nRESEARCH BRIEF:\n{json.dumps(research_brief, indent=2)}",
        ]

        if founder_voice:
            prompt_parts.append(f"\nFOUNDER VOICE PROFILE:\n{json.dumps(founder_voice, indent=2)}")

        prompt_parts.append("\nScore this PostPackage on all 12 dimensions.")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.2,
        )

        text = self._extract_text(response)
        try:
            scorecard = self._parse_json_response(text)
        except json.JSONDecodeError:
            scorecard = {"error": "Failed to parse QA output"}
            return {"qa_scorecard": scorecard}

        # Run humanitarian gate as an independent check (PRD Section 51)
        from tce.services.humanitarian_gate import HumanitarianGate

        humanitarian_gate = HumanitarianGate(
            sensitive_period=context.get("sensitive_period", False),
            current_events_context=context.get("current_events_context"),
        )
        gate_result = humanitarian_gate.check(
            facebook_post=facebook_post,
            linkedin_post=linkedin_post,
        )
        scorecard["humanitarian_gate"] = gate_result

        # Override LLM humanitarian score with gate score if lower
        dim_scores = scorecard.get("dimension_scores", {})
        gate_score = gate_result.get("score", 10)
        llm_score = dim_scores.get("humanitarian_sensitivity", 10)
        if isinstance(llm_score, dict):
            llm_score = llm_score.get("score", 10)
        if gate_score < llm_score:
            dim_scores["humanitarian_sensitivity"] = gate_score
            scorecard["dimension_scores"] = dim_scores

        # Compute composite score and pass status
        scorecard = self._compute_verdict(scorecard)

        # Verbose reporting
        composite = scorecard.get("composite_score", 0)
        status = scorecard.get("pass_status", "unknown")
        self._report(f"QA verdict: {status.upper()} (composite: {composite}/10)")
        dim_scores = scorecard.get("dimension_scores", {})
        for dim, val in dim_scores.items():
            score = val.get("score", val) if isinstance(val, dict) else val
            threshold = QA_THRESHOLDS.get(dim, 7)
            flag = " BLOCKED" if float(score) < threshold else ""
            self._report(f"  {dim}: {score}/10 (min {threshold}){flag}")
        blocking = scorecard.get("blocking_issues", [])
        if blocking:
            self._report(f"Blocking issues ({len(blocking)}):")
            for issue in blocking:
                self._report(f"  - {issue}")
        revisions = scorecard.get("revision_suggestions", [])
        if revisions:
            self._report("Revision suggestions:")
            for r in revisions[:5]:
                self._report(f"  - {str(r)[:120]}")

        return {"qa_scorecard": scorecard}

    def _compute_verdict(self, scorecard: dict[str, Any]) -> dict[str, Any]:
        """Compute composite score and pass/fail from dimension scores."""
        dim_scores = scorecard.get("dimension_scores", {})
        if not dim_scores:
            scorecard["pass_status"] = "fail"
            scorecard["composite_score"] = 0
            return scorecard

        # Normalize: dimension_scores might be {name: score} or {name: {score: N, ...}}
        normalized: dict[str, float] = {}
        for dim in QA_DIMENSIONS:
            val = dim_scores.get(dim, 0)
            if isinstance(val, dict):
                normalized[dim] = float(val.get("score", 0))
            else:
                normalized[dim] = float(val)

        # Weighted composite
        composite = sum(normalized.get(d, 0) * QA_WEIGHTS.get(d, 0) for d in QA_DIMENSIONS)
        scorecard["composite_score"] = round(composite, 2)

        # Check blocking dimensions
        blocking = []
        for dim in QA_DIMENSIONS:
            threshold = QA_THRESHOLDS.get(dim, 7)
            score = normalized.get(dim, 0)
            if score < threshold:
                blocking.append(f"{dim}: {score} < {threshold}")

        # Hard gates (PRD Section 45)
        humanitarian = normalized.get("humanitarian_sensitivity", 0)
        cta_honesty = normalized.get("cta_honesty", 0)

        if humanitarian < 8 or cta_honesty < 9:
            scorecard["pass_status"] = "fail"
        elif composite < 7.0 or any(
            normalized.get(d, 0) < QA_THRESHOLDS.get(d, 7) - 1 for d in QA_DIMENSIONS
        ):
            scorecard["pass_status"] = "fail"
        elif blocking:
            scorecard["pass_status"] = "conditional_pass"
        else:
            scorecard["pass_status"] = "pass"

        scorecard["blocking_issues"] = blocking
        return scorecard
