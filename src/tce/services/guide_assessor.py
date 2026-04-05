"""Guide quality assessor - shared across pipeline and API endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Any

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from tce.services.cost_tracker import CostTracker

QUALITY_THRESHOLD = 8.0
MAX_ITERATIONS = 3

ASSESSMENT_SYSTEM = """\
You are a strict quality assessor for B2B lead magnets (free guides given to \
readers who comment a keyword on social media). Score the guide on exactly \
6 dimensions, 1-10 each.

SCORING CALIBRATION:
- 8-10: genuinely earns it - a professional would thank you for this
- 5-7: adequate but forgettable - covers the topic without going deep
- 1-4: fails the dimension - generic, vague, or actively misleading

DIMENSION ANCHORS:

practical:
  8+: At least 2 framework steps include a fill-in template, checklist, or \
scoring rubric the reader can use TODAY. Quick Win produces a real output.
  5-7: Steps are numbered and concrete but produce no tangible artifact.
  1-4: Vague actions ("evaluate your process", "identify your goals").

valuable:
  8+: Contains at least 3 insights the reader could not easily find via Google. \
Saves real time/money with specifics (actual numbers, named companies, real tools).
  5-7: Useful overview but lacks depth. Nothing they couldn't learn from a blog.
  1-4: Generic content applicable to any topic. Could be from ChatGPT on first ask.

generous:
  8+: Gives a complete, usable framework. Reader can implement without buying \
anything else. No teasing, no "contact us for the full method."
  5-7: Helpful but holds back the "real" method - feels like a teaser.
  1-4: Pure teaser. More questions than answers.

accurate:
  8+: Every major claim cites a specific study, company, or data point by name. \
Zero "studies show" or "research indicates" without naming the study.
  5-7: Mix of cited and uncited claims. 1-2 vague references.
  1-4: Mostly unsourced. Heavy on "experts say" type claims.

quick_win:
  8+: Exercise is completable in 15 minutes and produces something the reader \
keeps (a scored audit, a completed worksheet, a specific decision made).
  5-7: Exercise exists but output is vague ("you'll have more clarity").
  1-4: No exercise, or the "exercise" is just reading the guide.

transformation:
  8+: Clear before/after belief shift. Reader thinks differently about the topic. \
Comparison table shows a real paradigm shift, not just "bad vs good."
  5-7: Some perspective shift but nothing the reader couldn't already see.
  1-4: No belief shift. Reader confirms what they already thought.

OUTPUT: JSON only, no markdown fences. Format:
{"practical":{"score":N,"reason":"..."},"valuable":{"score":N,"reason":"..."},\
"generous":{"score":N,"reason":"..."},"accurate":{"score":N,"reason":"..."},\
"quick_win":{"score":N,"reason":"..."},"transformation":{"score":N,"reason":"..."},\
"composite":N.N,"summary":"1-2 sentence overall assessment"}\
"""


async def assess_guide_content(
    markdown_content: str,
    guide_title: str,
    settings: Any,
    db: AsyncSession | None = None,
) -> dict:
    """Run Sonnet-based quality assessment on guide content.

    Returns dict with keys: practical, valuable, generous, accurate,
    quick_win, transformation (each {score, reason}), composite, summary.
    """
    api_key = settings.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Use Sonnet for more reliable calibration
    model = settings.default_model
    content = markdown_content[:12000]
    word_count = len(markdown_content.split())

    resp = await client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0.2,
        system=ASSESSMENT_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"GUIDE TITLE: {guide_title}\n"
                f"WORD COUNT: {word_count}\n\n"
                f"CONTENT:\n{content}"
            ),
        }],
    )

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        scores = json.loads(text)
    except json.JSONDecodeError:
        scores = {"error": "Failed to parse assessment", "raw": text[:500]}

    # Compute composite if not provided
    dims = ["practical", "valuable", "generous", "accurate", "quick_win", "transformation"]
    if "composite" not in scores and "error" not in scores:
        dim_scores = [
            scores[d]["score"]
            for d in dims
            if isinstance(scores.get(d), dict) and "score" in scores[d]
        ]
        if dim_scores:
            scores["composite"] = round(sum(dim_scores) / len(dim_scores), 1)

    # Record cost if db provided
    if db is not None:
        tracker = CostTracker(db)
        await tracker.record(
            run_id=uuid.uuid4(),
            agent_name="guide_assessor",
            model_used=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    return scores


def build_feedback_prompt(scores: dict, iteration: int) -> str:
    """Build structured feedback for the generator to improve the guide.

    Returns a prompt block that tells the generator exactly what scored low
    and how to fix it.
    """
    composite = scores.get("composite", 0)
    dims = ["practical", "valuable", "generous", "accurate", "quick_win", "transformation"]
    dim_labels = {
        "practical": "Practical",
        "valuable": "Valuable",
        "generous": "Generous",
        "accurate": "Accurate",
        "quick_win": "Quick Win",
        "transformation": "Transformation",
    }

    lines = [
        f"\n--- QUALITY GATE FEEDBACK (Iteration {iteration} scored {composite}/10 "
        f"- threshold is {QUALITY_THRESHOLD}) ---",
        "",
        "Your previous guide did not meet the quality threshold. "
        "You MUST regenerate the ENTIRE guide addressing these weaknesses:",
        "",
    ]

    for dim in dims:
        d = scores.get(dim, {})
        if not isinstance(d, dict):
            continue
        score = d.get("score", 0)
        reason = d.get("reason", "")
        status = "PASS" if score >= 8 else "NEEDS IMPROVEMENT"
        lines.append(f"- {dim_labels[dim]} ({score}/10 - {status}): {reason}")
        if score < 8:
            if dim == "practical":
                lines.append("  FIX: Add concrete fill-in templates, checklists, or rubrics to at least 2 framework steps.")
            elif dim == "valuable":
                lines.append("  FIX: Add 3+ non-obvious insights with specific numbers, named companies, or real tools.")
            elif dim == "generous":
                lines.append("  FIX: Make the framework complete and self-contained. No teasing or gatekeeping.")
            elif dim == "accurate":
                lines.append("  FIX: Name every study, company, and data source. Replace ALL 'studies show' with specific citations.")
            elif dim == "quick_win":
                lines.append("  FIX: Create a 15-minute exercise that produces a concrete artifact (scored audit, filled worksheet, binary decision).")
            elif dim == "transformation":
                lines.append("  FIX: The comparison must show a genuine belief shift the reader didn't expect. Not 'bad vs good' - show what they believe that is wrong.")

    lines.extend([
        "",
        "Do NOT patch sections - regenerate the complete guide from scratch.",
        f"Target composite score: {QUALITY_THRESHOLD}+/10.",
        "--- END FEEDBACK ---",
    ])

    return "\n".join(lines)
