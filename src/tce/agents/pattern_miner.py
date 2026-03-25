"""Pattern Miner — extracts reusable templates from high-scoring posts."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Pattern Miner for a content engine. Your job is to analyze high-performing \
social media posts and extract reusable structural templates.

For each pattern you identify, provide:
- template_name: descriptive name
- template_family: one of (big_shift_explainer, contrarian_diagnosis, \
hidden_feature_shortcut, tactical_workflow_guide, founder_reflection, \
case_study_build_story, second_order_implication, weekly_roundup, \
teardown_myth_busting, comment_keyword_cta_guide)
- best_for: what type of content this template works best for
- hook_formula: the reusable hook structure (abstracted from specific content)
- body_formula: the reusable body structure
- proof_requirements: what evidence is needed
- cta_compatibility: which CTA types work with this template
- visual_compatibility: which visual types match
- platform_fit: facebook, linkedin, or both
- tone_profile: {curiosity, sharpness, practicality, strategic_depth, \
emotional_intensity} as 1-10 values
- risk_notes: what could go wrong with this template
- anti_patterns: what NOT to do
- source_influence_weights: which creator styles this draws from, as name:weight pairs

Output as a JSON array of template objects.
"""


@register_agent
class PatternMiner(AgentBase):
    name = "pattern_miner"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract templates from scored post examples."""
        scored_examples = context.get("scored_examples", [])

        if not scored_examples:
            return {"templates": [], "warnings": ["No scored examples provided"]}

        # Take top examples for pattern mining
        top_examples = scored_examples[:30]  # Use top 30 examples

        # Format for LLM
        examples_text = json.dumps(
            [
                {
                    "creator": ex.get("creator_name"),
                    "hook_type": ex.get("hook_type"),
                    "hook_text": ex.get("hook_text", "")[:200],
                    "body_structure": ex.get("body_structure"),
                    "cta_type": ex.get("cta_type"),
                    "tension_type": ex.get("tension_type"),
                    "final_score": ex.get("final_score"),
                    "tone_tags": ex.get("tone_tags"),
                }
                for ex in top_examples
            ],
            indent=2,
        )

        response = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze these top-performing posts and extract reusable templates.\n\n"
                    f"SCORED EXAMPLES:\n{examples_text}",
                }
            ],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.3,
        )

        text = self._extract_text(response)
        try:
            templates = self._parse_json_response(text)
            if not isinstance(templates, list):
                templates = [templates]
        except json.JSONDecodeError:
            return {"templates": [], "warnings": ["Failed to parse template JSON"]}

        return {
            "templates": templates,
            "template_count": len(templates),
        }
