"""Repo Storyteller - turns a RepoBrief + chosen angle into a story_brief
that downstream agents (research, writers, CTA, QA) already know how to use.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.models.pattern_template import PatternTemplate

SYSTEM_PROMPT = """\
You are the Repo Storyteller for Team Content Engine. You receive:
1. A structured repo snapshot (summary, architecture, features, fixes, snippets).
2. An angle: new_features | whole_repo | recent_fixes.
3. A pool of high-performing PatternTemplates.

Your job: produce a story_brief in the EXACT shape downstream agents expect
(topic, thesis, audience, angle_type, visual_job, evidence_requirements, platform_notes)
so research / writers / CTA / QA can run unchanged.

Rules:
- Anchor the thesis in concrete, verifiable claims from the repo (commit shas, features).
- Do NOT invent features or fixes beyond what the brief says.
- Match to one PatternTemplate that best fits the chosen angle:
   - new_features -> "Hidden Feature", "Tactical Workflow Guide", or "Case Study"
   - whole_repo -> "Teardown", "Big Shift Explainer", or "Tactical Workflow Guide"
   - recent_fixes -> "Contrarian Diagnosis", "Second-Order Implication", or "Lessons Learned"
- Output STRICTLY valid JSON.
"""

USER_PROMPT = """\
Repo brief (JSON):
{repo_brief_json}

Chosen angle: **{angle}**

Top-performing templates to choose from:
{templates_json}

Optional weekly keyword / CTA: {weekly_keyword}
Operator notes: {notes}
{strategy_block}

Return a single JSON object:
{{
  "story_brief": {{
    "topic": "short repo-grounded topic",
    "thesis": "the single claim this post will argue, grounded in commits",
    "audience": "who should care (builders / operators / agency owners / etc)",
    "angle_type": "one of: contrarian_insight, founder_journey, data_storytelling, industry_trends, how_we_built_it, client_transformation, myth_busting, behind_the_scenes, lessons_learned, future_prediction",
    "visual_job": "what an image should convey",
    "platform_notes": "any per-platform notes",
    "evidence_requirements": ["concrete claim 1", "concrete claim 2"]
  }},
  "matched_template": {{
    "template_name": "string",
    "template_family": "string",
    "match_reason": "why this template fits"
  }},
  "repo_citations": [
    {{
      "label": "Feature: <title>",
      "commit_sha": "abc1234",
      "why_cite": "what this proves about the thesis"
    }}
  ],
  "headline_options": ["3-5 possible post hooks"]
}}
"""


@register_agent
class RepoStoryteller(AgentBase):
    """Turn a RepoBrief into a story_brief + template match + citations."""

    name = "repo_storyteller"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        repo_brief = context.get("repo_brief") or {}
        if not repo_brief:
            return {"error": "repo_storyteller needs repo_brief in context"}

        angle = repo_brief.get("angle") or context.get("angle") or "generic"
        weekly_keyword = context.get("weekly_keyword") or ""
        notes = (context.get("operator_overrides") or {}).get("notes") or ""

        from tce.services.strategy_loader import load_strategy
        _strategy = load_strategy()
        strategy_block = (
            "\nBUSINESS STRATEGY CONTEXT (audience, framing, and visual_job must reflect this):\n"
            "The repo story will become a post targeting coaches/consultants burned by generic agency content.\n"
            "The audience field must name coaches or agency owners, not generic 'builders'.\n"
            "AUTHORSHIP: This repo belongs to the operator running this pipeline. The thesis, "
            "headline_options, and platform_notes must be phrased from the builder's first-person "
            "POV ('I shipped...', 'I built...'), never as a third-party report on someone else's work.\n"
            f"{_strategy[:3500]}"
        ) if _strategy else ""
        if _strategy:
            self._report("Loaded strategy context for repo storytelling")

        self._report(
            f"Story brief for {repo_brief.get('slug', '?')} (angle={angle})"
        )

        # Pull a few top-performing templates
        try:
            res = await self.db.execute(
                select(PatternTemplate)
                .where(PatternTemplate.status.in_(["validated", "provisional"]))
                .order_by(PatternTemplate.median_score.desc().nulls_last())
                .limit(8)
            )
            templates = [
                {
                    "template_name": t.template_name,
                    "template_family": t.template_family,
                    "best_for": t.best_for,
                    "hook_formula": t.hook_formula,
                    "body_formula": t.body_formula,
                    "median_score": t.median_score,
                }
                for t in res.scalars().all()
            ]
        except Exception as e:
            self._report(f"Could not load templates: {e}")
            templates = []

        # Compact the repo brief so the prompt stays cheap
        compact = {
            "slug": repo_brief.get("slug"),
            "repo_url": repo_brief.get("repo_url"),
            "angle": angle,
            "commit_sha": repo_brief.get("commit_sha"),
            "summary": repo_brief.get("summary"),
            "architecture_notes": repo_brief.get("architecture_notes"),
            "feature_highlights": (repo_brief.get("feature_highlights") or [])[:6],
            "bug_fixes": (repo_brief.get("bug_fixes") or [])[:6],
            "angle_lede": repo_brief.get("angle_lede"),
            "audience_guess": repo_brief.get("audience_guess"),
            "package_hints": repo_brief.get("package_hints"),
            "recent_commits_sample": (repo_brief.get("recent_commits") or [])[:10],
        }

        prompt = USER_PROMPT.format(
            repo_brief_json=json.dumps(compact, indent=2),
            angle=angle,
            templates_json=json.dumps(templates, indent=2) if templates else "[]",
            weekly_keyword=weekly_keyword or "(none)",
            notes=notes or "(none)",
            strategy_block=strategy_block,
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
            max_tokens=2500,
            temperature=0.5,
        )

        text = self._extract_text(response)
        try:
            parsed = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("Storyteller JSON parse failed - using minimal fallback.")
            parsed = {
                "story_brief": {
                    "topic": f"{repo_brief.get('slug')} ({angle})",
                    "thesis": repo_brief.get("summary") or "",
                    "audience": "builders and agency operators",
                    "angle_type": "how_we_built_it",
                    "visual_job": "product in use",
                    "platform_notes": "",
                    "evidence_requirements": [],
                },
                "matched_template": {},
                "repo_citations": [],
                "headline_options": [],
            }

        story_brief = parsed.get("story_brief", {})
        self._report(f"Topic: {story_brief.get('topic', '')}")
        self._report(f"Thesis: {(story_brief.get('thesis') or '')[:120]}")
        matched = parsed.get("matched_template", {}) or {}
        if matched.get("template_name"):
            self._report(f"Matched template: {matched['template_name']}")

        citations = parsed.get("repo_citations", [])
        self._report(f"Citations: {len(citations)}")
        return {
            "story_brief": story_brief,
            "matched_template": matched,
            "repo_citations": citations,
            "headline_options": parsed.get("headline_options", []),
            # Keep the full repo_brief flowing so writers can quote snippets too.
            "repo_brief": repo_brief,
        }
