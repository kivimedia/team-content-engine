"""Platform Writers - Facebook (engagement engine) and LinkedIn (authority engine).

Each writer runs a draft -> critique -> rewrite-once loop. The critic scores
the draft against the 36 voice patterns + banned-vocab list in
docs/super-coaching-strategy.md. If the score is below threshold the draft
is rewritten once with the critic's specific violations as feedback.
"""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.services.strategy_loader import load_voice_patterns


# Score below which the draft must be rewritten. The critic returns 1-10;
# 7 means "mostly Ziv's voice, a few patterns missed". Below that triggers a
# revision. Higher than this and we ship as-is.
_VOICE_PASS_SCORE = 7

# Maximum critic-driven rewrite attempts. The critic is a Sonnet call and the
# rewrite is another Sonnet call, so each retry adds ~$0.05. Two attempts
# is enough; the LLM either reaches threshold or settles into a different
# but-still-imperfect register.
_MAX_VOICE_REVISIONS = 1


_VOICE_CRITIC_SYSTEM = """\
You are the Voice Critic for Team Content Engine. You judge whether a
draft post matches Ziv Raviv's writing voice as documented in the
36-pattern voice spec below. You do NOT rewrite; you SCORE and FLAG.

Output STRICT JSON:
{
  "score": 1-10 integer,
  "verdict": "pass" | "revise",
  "violations": [
    {"pattern_id": "B6" | "F20" | "banned_vocab" | etc.,
     "quote": "the exact phrase from the draft that violated",
     "issue": "one sentence explaining why this fails",
     "fix": "concrete rewrite suggestion - the actual replacement words"}
  ],
  "summary": "one sentence overall verdict"
}

SCORING RUBRIC:
- 9-10: reads like a peer thinking out loud. No agency-speak. Hook has
  conflict or specificity. Has paraphrased memory or anonymized hero
  with stakes. One idea, not stacked.
- 7-8: mostly there, but missing one or two patterns (no aphorism line,
  missed underclaim opportunity, generic 2022-style objection).
- 5-6: feels like an AI-generated coaching post. Multiple stacked
  insights, generic urgency, present-tense thesis essay style.
- 1-4: agency-speak fingerprint. "smart money", "competitive
  landscape", "the math is compelling", "window is closing", or
  feature-paste from a vendor doc.

VERDICT: "pass" if score >= 7, "revise" otherwise.

CALL OUT EVERY VIOLATION YOU SEE. The downstream writer will use your
violations as the rewrite instruction set. Be specific with the quote
field - paste the exact phrase from the draft, not a paraphrase. Be
specific with the fix field - propose actual replacement words, not
abstract guidance.
"""


def _build_critic_user_prompt(draft_text: str, platform: str, voice_spec: str) -> str:
    return (
        f"VOICE SPEC (the rules):\n{voice_spec}\n\n"
        f"---\n\n"
        f"DRAFT to score ({platform}):\n\n{draft_text}\n\n"
        f"---\n\n"
        f"Score it. Flag every violation. Be specific."
    )


async def _critique_voice(
    agent, post_text: str, platform: str, voice_spec: str
) -> dict[str, Any]:
    """Single critic LLM call. Returns a dict with score/verdict/violations."""
    try:
        user = _build_critic_user_prompt(post_text, platform, voice_spec)
        resp = await agent._call_llm(
            messages=[{"role": "user", "content": user}],
            system=_VOICE_CRITIC_SYSTEM,
            max_tokens=2048,
            temperature=0.3,
        )
        text = agent._extract_text(resp)
        return agent._parse_json_response(text)
    except Exception as e:
        agent._report(f"  Voice critic call failed: {e}")
        return {"score": 7, "verdict": "pass", "violations": [], "summary": "(critic skipped)"}


async def _rewrite_for_voice(
    agent,
    original_post: str,
    violations: list[dict],
    voice_spec: str,
    platform: str,
    system_prompt: str,
) -> dict[str, Any] | None:
    """Single rewrite LLM call. Returns parsed JSON or None on failure."""
    try:
        user = _build_revision_user_prompt(
            original_post, violations, voice_spec, platform
        )
        resp = await agent._call_llm(
            messages=[{"role": "user", "content": user}],
            system=system_prompt,
            max_tokens=6144,
            temperature=0.7,
        )
        text = agent._extract_text(resp)
        return agent._parse_json_response(text)
    except Exception as e:
        agent._report(f"  Voice critic rewrite failed: {e}")
        return None


async def _run_voice_critic_loop(
    agent,
    result: dict[str, Any],
    post_key: str,
    platform: str,
    system_prompt: str,
) -> dict[str, Any]:
    """Run draft -> critique -> rewrite-once. Returns possibly-updated result.

    Shared by FacebookWriter and LinkedInWriter. The agent argument provides
    _call_llm / _extract_text / _parse_json_response / _report.
    """
    post_text = result.get(post_key, "")
    if not post_text:
        return result

    voice_spec = load_voice_patterns()
    if not voice_spec:
        agent._report("  Voice critic: spec not found - skipping")
        return result

    for attempt in range(_MAX_VOICE_REVISIONS + 1):
        critique = await _critique_voice(agent, post_text, platform, voice_spec)
        score = critique.get("score", 0)
        verdict = critique.get("verdict", "")
        violations = critique.get("violations") or []
        summary = critique.get("summary", "")

        agent._report(
            f"  Voice critic [pass {attempt + 1}]: score={score}/10 verdict={verdict} "
            f"({len(violations)} violation{'s' if len(violations) != 1 else ''})"
        )
        if summary:
            agent._report(f"    {summary[:160]}")
        for v in violations[:5]:
            pid = v.get("pattern_id", "?")
            quote = (v.get("quote") or "")[:80]
            agent._report(f"    [{pid}] {quote}")

        if verdict == "pass" or score >= _VOICE_PASS_SCORE or attempt >= _MAX_VOICE_REVISIONS:
            if attempt >= _MAX_VOICE_REVISIONS and verdict != "pass":
                agent._report(f"  Voice critic: shipping anyway after {attempt + 1} attempts")
            result["voice_score"] = score
            result["voice_verdict"] = verdict
            result["voice_violations"] = violations
            return result

        agent._report("  Voice critic: rewriting to address violations...")
        revised = await _rewrite_for_voice(
            agent=agent,
            original_post=post_text,
            violations=violations,
            voice_spec=voice_spec,
            platform=platform,
            system_prompt=system_prompt,
        )
        if revised:
            if revised.get(post_key):
                result[post_key] = _clean_dash(revised[post_key])
                post_text = result[post_key]
            if revised.get("rationale"):
                result["rationale"] = _clean_dash(revised["rationale"])
            if revised.get("hook_variants"):
                result["hook_variants"] = [
                    _clean_dash(h) if isinstance(h, str) else h
                    for h in revised["hook_variants"]
                ]
            if revised.get("word_count"):
                result["word_count"] = revised["word_count"]
        else:
            agent._report("  Voice critic: rewrite failed - keeping original")
            result["voice_score"] = score
            result["voice_verdict"] = verdict
            result["voice_violations"] = violations
            return result

    return result


def _build_revision_user_prompt(
    original_post: str,
    violations: list[dict],
    voice_spec: str,
    platform: str,
) -> str:
    """Build the rewrite prompt that turns critic violations into a fix-list."""
    fix_lines = []
    for v in violations:
        pid = v.get("pattern_id", "?")
        quote = v.get("quote", "")
        issue = v.get("issue", "")
        fix = v.get("fix", "")
        fix_lines.append(
            f"- [{pid}] FIX THIS PHRASE: \"{quote}\"\n  WHY: {issue}\n  REPLACE WITH (or in this style): {fix}"
        )
    fix_block = "\n".join(fix_lines) if fix_lines else "(no specific phrase fixes; rewrite for tone)"

    return (
        f"You wrote this {platform} post, and the voice critic flagged it. "
        f"Rewrite it - keep the same topic, thesis, and CTA, but FIX every "
        f"flagged violation. The voice spec is below as ground truth. Output "
        f"the SAME JSON shape as the original draft "
        f"(facebook_post / linkedin_post + hook_variants + word_count + rationale).\n\n"
        f"VOICE SPEC:\n{voice_spec}\n\n"
        f"---\n\n"
        f"ORIGINAL DRAFT:\n{original_post}\n\n"
        f"---\n\n"
        f"VIOLATIONS TO FIX (each one must go):\n{fix_block}\n\n"
        f"Rewrite now. Same JSON shape."
    )


def _clean_dash(s: str) -> str:
    """Replace all dash-like Unicode chars and double dashes with single dash."""
    for ch in "\u2014\u2013\u2015\u2012\u2015\u2053\u2E3A\u2E3B\uFE58\uFF0D":
        s = s.replace(ch, " - ")
    return s.replace("--", " - ")


def _build_template_block(context: dict) -> str:
    """Build an explicit template formula block for the writer prompt."""
    tpl = context.get("_resolved_template")
    if not tpl:
        return ""
    lines = ["ASSIGNED TEMPLATE FORMULA (follow this structure):"]
    lines.append(f"Template: {tpl.get('template_name', '?')} ({tpl.get('template_family', '?')})")
    if tpl.get("hook_formula"):
        lines.append(f"Hook formula: {tpl['hook_formula']}")
    if tpl.get("body_formula"):
        lines.append(f"Body formula: {tpl['body_formula']}")
    if tpl.get("anti_patterns"):
        lines.append(f"Anti-patterns to AVOID: {tpl['anti_patterns']}")
    return "\n".join(lines)


_ANGLE_GUIDANCE = {
    "new_features": {
        "label": "New features (recently shipped capabilities)",
        "lead_with": "features",
        "instruction": (
            "Lead the post with what was just shipped. The hook should name a "
            "specific feature; the body should walk through what it does and why "
            "it matters. Bug fixes are background context only - do not anchor "
            "the post on them. The repo's architecture is irrelevant unless it "
            "explains why the new feature was hard to build."
        ),
    },
    "whole_repo": {
        "label": "Whole repo (overview - what it does, who it's for)",
        "lead_with": "summary",
        "instruction": (
            "This is a tour of the repo, not a changelog. Lead with what the "
            "project IS and who it's for - use the Summary and Architecture "
            "lines. Features and fixes are evidence the project is alive and "
            "useful, not the headline. Do NOT structure the post as 'here's a "
            "new feature' or 'here's a recent fix'. Frame: 'this is a thing "
            "that exists, here's the shape of it, here's why it matters'."
        ),
    },
    "recent_fixes": {
        "label": "Recent fixes (bugs solved, edge cases, debugging stories)",
        "lead_with": "fixes",
        "instruction": (
            "Lead with a specific bug or edge case from the Recent bug fixes "
            "list. The hook should name the problem (what broke, what surprised "
            "the team, what the symptom was). The body is the debugging story: "
            "the wrong hypothesis, the actual root cause, the fix. Feature "
            "highlights are noise here - mention them only if they directly "
            "caused the bug. The lesson is the payload."
        ),
    },
    "generic": {
        "label": "Generic (no specific angle)",
        "lead_with": "summary",
        "instruction": (
            "Pick the single most interesting thing in the brief - feature, "
            "fix, or architectural choice - and build the post around it. "
            "Don't try to cover all three."
        ),
    },
}


def _build_repo_block(context: dict, platform: str) -> tuple[str, str | None]:
    """Build a REPO CONTEXT block for repo-sourced runs.

    Returns (block_text, repo_url). Empty string + None if not a repo run.
    The block forces the writer to ground the post in concrete repo specifics
    (slug, summary, top features w/ commit shas, top snippets) and to close
    with the repo URL. The user-selected angle (new_features / whole_repo /
    recent_fixes) reorders the evidence sections and adds explicit framing
    instructions so the post matches what the operator picked in the form.
    """
    if context.get("_source") != "repo":
        return "", None
    repo_brief = context.get("repo_brief") or {}
    repo_url = repo_brief.get("repo_url") or context.get("repo_url")
    if not repo_url:
        return "", None

    slug = repo_brief.get("slug") or ""
    summary = (repo_brief.get("summary") or "").strip()
    arch = (repo_brief.get("architecture_notes") or "").strip()
    angle = repo_brief.get("angle") or context.get("angle") or "generic"
    angle_cfg = _ANGLE_GUIDANCE.get(angle, _ANGLE_GUIDANCE["generic"])

    features = repo_brief.get("feature_highlights") or []
    fixes = repo_brief.get("bug_fixes") or []
    snippets = repo_brief.get("code_snippets") or []
    citations = context.get("repo_citations") or []

    lines = [
        "REPO CONTEXT (this post is about a real GitHub repo - ground every claim here):",
        f"Repo: {slug or repo_url}",
        f"URL: {repo_url}",
        f"Angle: {angle_cfg['label']}",
        f"Angle instruction: {angle_cfg['instruction']}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if arch:
        lines.append(f"Architecture: {arch}")

    def _features_section() -> list[str]:
        if not features:
            return []
        out = ["\nTop feature highlights (cite at least one with its commit sha):"]
        for f in features[:4]:
            sha = f.get("commit_sha") or ""
            title = f.get("title") or ""
            why = f.get("why_interesting") or ""
            out.append(f"  - {title} [{sha}] - {why}".rstrip(" -"))
        return out

    def _fixes_section() -> list[str]:
        if not fixes:
            return []
        out = ["\nRecent bug fixes (cite at least one with its commit sha):"]
        for f in fixes[:4]:
            sha = f.get("commit_sha") or ""
            title = f.get("title") or ""
            what = f.get("what_broke") or ""
            out.append(f"  - {title} [{sha}] - {what}".rstrip(" -"))
        return out

    # Reorder evidence sections so the angle's primary material reads first.
    if angle_cfg["lead_with"] == "fixes":
        lines.extend(_fixes_section())
        lines.extend(_features_section())
    elif angle_cfg["lead_with"] == "summary":
        # Whole-repo: summary already leads at the top; features & fixes
        # are both background evidence. Show features first (they show
        # vitality) but don't elevate either over the architectural framing.
        lines.extend(_features_section())
        lines.extend(_fixes_section())
    else:
        lines.extend(_features_section())
        lines.extend(_fixes_section())

    if snippets:
        lines.append("\nReal code snippets (reference at least one if relevant):")
        for s in snippets[:2]:
            path = s.get("path") or s.get("file") or ""
            subj = s.get("commit_subject") or ""
            preview = (s.get("snippet") or s.get("preview") or "")[:240]
            if preview:
                lines.append(f"  - {path} ({subj}):\n    {preview}")

    if citations:
        lines.append("\nStoryteller-chosen citations:")
        for c in citations[:3]:
            label = c.get("label") or ""
            sha = c.get("commit_sha") or ""
            why = c.get("why_cite") or ""
            lines.append(f"  - {label} [{sha}] - {why}".rstrip(" -"))

    lines.append("")
    lines.append("HARD RULES FOR THIS POST:")
    lines.append("- The post must be recognizably about THIS repo - mention the slug or a specific feature/fix in the first 3 lines.")
    if angle == "new_features":
        lines.append("- The hook MUST name a specific feature from the 'feature highlights' list. Do not lead with a bug fix or an architectural overview.")
    elif angle == "recent_fixes":
        lines.append("- The hook MUST name a specific bug or symptom from the 'bug fixes' list. Do not lead with a feature announcement.")
    elif angle == "whole_repo":
        lines.append("- The hook MUST frame what the project IS and who it's for. Do not lead with a single feature or fix - that's a different angle.")
    lines.append("- Reference at least one concrete commit sha by [shortsha] inline, not in a separate footer.")
    lines.append("- Generic AI/coaching commentary is NOT acceptable.")
    if platform == "facebook":
        lines.append(f"- The CTA at the very end MUST be the repo URL on its own line: {repo_url}")
        lines.append("- Do NOT use the 'comment KEYWORD' pattern for this post - the CTA is the repo link.")
    else:
        lines.append(f"- Close the post with the repo URL on its own line: {repo_url}")
        lines.append("- Soft CTA only: invite readers to check out the code, star the repo, or read the README.")

    return "\n".join(lines), repo_url


def _clean_writer_output(result: dict) -> dict:
    """Clean all text fields in writer output of emdashes/en dashes."""
    for key in ("facebook_post", "linkedin_post", "rationale"):
        if key in result and isinstance(result[key], str):
            result[key] = _clean_dash(result[key])
    if "hook_variants" in result and isinstance(result["hook_variants"], list):
        result["hook_variants"] = [
            _clean_dash(h) if isinstance(h, str) else h
            for h in result["hook_variants"]
        ]
    return result

_VOICE_RULES = """\
ZIV'S CONTENT VOICE RULES (apply to every post):
- Conflict hooks outperform curiosity-gap: "her marketing company made a mess" beats "a story from last week"
- Anonymize heroes, specify villains fairly: concede villain's strengths BEFORE the critique — the concession is credibility
- Three-beat emotional cadence for the narrative turn: Feeling → interpretation → wish. Short lines, space between.
- One standalone aphorism on its own line, not crowded — use once per post
- Bulleted pain with emotional words ("super annoying", "ignored", "felt dismissed") — never sanitize
- Peer language: "another coach I worked with" not "a client" or "a contact"
- Underclaim for credibility — "minimal tweaking" beats "zero tweaking"
- Process language > result language: "the process that creates voice precision" beats just "voice precision"
- Diagnosis > observation: name the mental model that caused the failure, not just the symptom
- One idea per post — never stack multiple insights, CTAs, or angles
- Show the hero being patient before they snap — decision feels measured, not reactive
- Never agency-speak: "maximize ROI", "AI-powered solutions", "leverage synergies", "seamlessly integrates"
"""

FB_SYSTEM_PROMPT = """\
You are the Facebook Writer for Team Content Engine. Your job is to write a \
scroll-stopping, comment-triggering post that makes people engage.
""" + _VOICE_RULES + """
FACEBOOK-SPECIFIC RULES:
- The first 2 lines must survive the "See more" cut - they ARE the hook
- Short paragraphs: 1-3 sentences max per block
- Use whitespace aggressively - a blank line between every block
- Tone: emotional, conversational, punchy. Permission to be provocative
- NEVER use emdashes or en dashes. Use a single hyphen (-) instead. No exceptions
- Build toward the CTA
- No hashtags. No emoji unless the voice naturally uses them
- No AI-slop preamble ("In today's fast-paced world...")
- Length: 600-1200 words. LONGER IS ALWAYS BETTER. Develop every idea fully with examples, \
micro-stories, and specific details. A 400-word post is a skeleton - flesh it out. \
Each proof block should be 2-3 paragraphs minimum, not a single sentence

OUTPUT FORMAT (JSON):
- facebook_post: the complete post text
- hook_variants: 5 alternative opening lines, each <= 2 sentences
- word_count: integer
- rationale: brief explanation of platform-specific choices made
"""

LI_SYSTEM_PROMPT = """\
You are the LinkedIn Writer for Team Content Engine. Your job is to write an \
authority-building post that makes people save, follow, and think differently.
""" + _VOICE_RULES + """
LINKEDIN-SPECIFIC RULES:
- Clear thesis in the first 3 lines
- Longer, more developed argument - can include frameworks, numbered insights
- Stronger evidence packaging - more data, more "here's what most people miss"
- NEVER use emdashes or en dashes. Use a single hyphen (-) instead. No exceptions
- Professional close with a takeaway, not a hard CTA
- May include a soft CTA (follow for more, share if useful)
- NEVER a "say XXX" comment-trigger
- Length: 800-2000 words. Go DEEP. Develop complete frameworks with full explanations, \
give numbered insights with examples for each, tell full stories with specific details. \
A 500-word LinkedIn post is a tweet thread - write a real article. \
Each section/insight should be a full paragraph with evidence, not a bullet point
- Executive, precise, deeper tone

OUTPUT FORMAT (JSON):
- linkedin_post: the complete post text
- hook_variants: 5 alternative opening lines
- word_count: integer
- rationale: brief explanation of platform-specific choices made
"""

SHARED_PROMPT_SUFFIX = """\

EVIDENCE RULES (STRICT - ZERO TOLERANCE FOR FABRICATION):
- Every hard claim must come from the Research Brief's verified_claims WITH a source
- Uncertain claims must use signal words: "suggests," "points to," "early data shows"
- Rejected claims must NOT be used
- NEVER invent specific details: no fake product names, feature descriptions, code behaviors, \
company actions, statistics, quotes, or technical mechanisms that aren't in the Research Brief
- If a claim sounds like a fact (X does Y, company Z launched W), it MUST be in verified_claims. \
If it's not there, DO NOT WRITE IT - not even as opinion
- If the research brief has no verified claims or safe_to_publish is false: \
write the post as a THOUGHT PIECE using general observations and your thesis as a question, \
NOT as an exposé with specific allegations. Frame as "here's a pattern worth examining" \
not "here's what's secretly happening." Do NOT refuse to write - but keep claims general and honest.
- When in doubt, be LESS specific. "AI tools have hidden behaviors" is fine. \
"Claude removes Co-Authored-By lines" is fabrication unless verified_claims confirms it.

PLAN ADHERENCE (NON-NEGOTIABLE):
- Your topic and thesis come from STORY BRIEF - this is your assignment
- Research brief provides supporting evidence ONLY - it does NOT change your topic
- If research findings contradict the story brief, note the tension but STAY ON the assigned topic
- Your post MUST be recognizably about the story_brief topic - a reader should identify it in the first 2 sentences

ANTI-CLONE CHECK:
- Do not use the same opening structure as recent posts
- Do not contain phrases signature to a source creator
- Do not follow the template so rigidly it reads like fill-in-the-blank
"""

CREATOR_INSPIRATION_PROMPT = """\

CREATOR INSPIRATION REFERENCE:
You are writing a post INSPIRED by the style of {creator_name}. \
Study the reference post below and absorb its structural patterns, \
tone, pacing, and engagement techniques. Then write an ORIGINAL post \
on today's topic using those techniques. Do NOT copy the content - \
borrow the craft.

Reference post ({word_count} words):
---
{post_text}
---

Style notes to emulate:
- Hook type: {hook_type}
- Body structure: {body_structure}
- Story arc: {story_arc}
- CTA approach: {cta_type}
{extra_notes}

IMPORTANT: The output must be ORIGINAL content on today's story brief topic. \
Only the STYLE and STRUCTURE should be inspired by the reference. \
Maximum allowed influence: {influence_weight}% - the rest must be your own voice.
"""


def _build_inspiration_block(context: dict) -> str:
    """Build the creator inspiration prompt section if creator_inspiration is in context."""
    insp = context.get("creator_inspiration")
    if not insp:
        return ""
    extra = ""
    if insp.get("tone_tags"):
        extra += f"- Tone: {', '.join(insp['tone_tags'])}\n"
    if insp.get("topic_tags"):
        extra += f"- Topics: {', '.join(insp['topic_tags'])}\n"
    if insp.get("style_notes"):
        extra += f"- Creator style: {insp['style_notes']}\n"
    return CREATOR_INSPIRATION_PROMPT.format(
        creator_name=insp.get("creator_name", "Unknown"),
        word_count=insp.get("word_count", "?"),
        post_text=insp.get("post_text", ""),
        hook_type=insp.get("hook_type", "unknown"),
        body_structure=insp.get("body_structure", "unknown"),
        story_arc=insp.get("story_arc", "unknown"),
        cta_type=insp.get("cta_type", "unknown"),
        extra_notes=extra,
        influence_weight=insp.get("influence_weight", 20),
    )


@register_agent
class FacebookWriter(AgentBase):
    name = "facebook_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        founder_voice = context.get("founder_voice", {})
        weekly_keyword = context.get("weekly_keyword", "guide")
        thesis = story_brief.get("thesis", "N/A")[:60]
        self._report(f"Writing FB post - thesis: {thesis}")

        repo_block, repo_url = _build_repo_block(context, platform="facebook")

        prompt_parts = [
            f"STORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"RESEARCH BRIEF:\n{json.dumps(research_brief, indent=2)}",
        ]
        if repo_block:
            # Repo runs replace the comment-keyword CTA with a direct link.
            prompt_parts.append(repo_block)
        else:
            prompt_parts.append(f'Weekly CTA keyword: "{weekly_keyword}"')
            prompt_parts.append(
                f'CTA line must end with: Comment "{weekly_keyword}" and I\'ll send it to you.'
            )

        template_block = _build_template_block(context)
        if template_block:
            prompt_parts.insert(1, template_block)

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        inspiration_block = _build_inspiration_block(context)
        if inspiration_block:
            prompt_parts.append(inspiration_block)

        if repo_url:
            self._report(f"Repo-sourced post - grounding in {repo_url}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=FB_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
            max_tokens=6144,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            result = self._parse_json_response(text)
        except json.JSONDecodeError:
            result = {"facebook_post": text, "hook_variants": [], "rationale": "raw output"}

        # Clean emdashes/en dashes from all text fields
        result = _clean_writer_output(result)

        # Voice critic loop: score the draft, rewrite once if it doesn't pass.
        result = await _run_voice_critic_loop(
            agent=self,
            result=result,
            post_key="facebook_post",
            platform="facebook",
            system_prompt=FB_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
        )

        wc = result.get("word_count", len(result.get("facebook_post", "").split()))
        hooks = result.get("hook_variants", [])
        self._report(f"FB post drafted ({wc} words, {len(hooks)} hook variants)")
        post_text = result.get("facebook_post", "")
        if post_text:
            first_lines = post_text.strip().split("\n")[:3]
            self._report(f"  Opening: {' '.join(first_lines)[:150]}...")
        for i, h in enumerate(hooks[:3], 1):
            self._report(f"  Hook {i}: {str(h)[:120]}")
        if len(hooks) > 3:
            self._report(f"  ... and {len(hooks) - 3} more hooks")
        rationale = result.get("rationale", "")
        if rationale:
            self._report(f"  Rationale: {str(rationale)[:150]}")
        return {"facebook_draft": result}



@register_agent
class LinkedInWriter(AgentBase):
    name = "linkedin_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        founder_voice = context.get("founder_voice", {})
        thesis = story_brief.get("thesis", "N/A")[:60]
        self._report(f"Writing LI post - thesis: {thesis}")

        repo_block, repo_url = _build_repo_block(context, platform="linkedin")

        prompt_parts = [
            f"STORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"RESEARCH BRIEF:\n{json.dumps(research_brief, indent=2)}",
        ]
        if repo_block:
            prompt_parts.append(repo_block)

        template_block = _build_template_block(context)
        if template_block:
            prompt_parts.insert(1, template_block)

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        inspiration_block = _build_inspiration_block(context)
        if inspiration_block:
            prompt_parts.append(inspiration_block)

        if repo_url:
            self._report(f"Repo-sourced post - grounding in {repo_url}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=LI_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
            max_tokens=8192,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            result = self._parse_json_response(text)
        except json.JSONDecodeError:
            result = {"linkedin_post": text, "hook_variants": [], "rationale": "raw output"}

        # Clean emdashes/en dashes from all text fields
        result = _clean_writer_output(result)

        # Voice critic loop: score the draft, rewrite once if it doesn't pass.
        result = await _run_voice_critic_loop(
            agent=self,
            result=result,
            post_key="linkedin_post",
            platform="linkedin",
            system_prompt=LI_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
        )

        wc = result.get("word_count", len(result.get("linkedin_post", "").split()))
        hooks = result.get("hook_variants", [])
        self._report(f"LI post drafted ({wc} words, {len(hooks)} hook variants)")
        post_text = result.get("linkedin_post", "")
        if post_text:
            first_lines = post_text.strip().split("\n")[:3]
            self._report(f"  Opening: {' '.join(first_lines)[:150]}...")
        for i, h in enumerate(hooks[:3], 1):
            self._report(f"  Hook {i}: {str(h)[:120]}")
        rationale = result.get("rationale", "")
        if rationale:
            self._report(f"  Rationale: {str(rationale)[:150]}")
        return {"linkedin_draft": result}
