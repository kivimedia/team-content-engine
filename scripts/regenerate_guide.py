"""Standalone script to regenerate the weekly guide without the full pipeline.

Usage: python scripts/regenerate_guide.py
Outputs: DOCX file in the current directory.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anthropic

from tce.agents.docx_guide_builder import SYSTEM_PROMPT
from tce.utils.docx import create_guide_docx

# Sample context - representative of a real weekly run
SAMPLE_CONTEXT = {
    "weekly_theme": "AI agents are replacing SaaS dashboards - and most businesses aren't ready",
    "weekly_keyword": "AGENTSHIFT",
    "author_name": "Ziv Raviv",
    "story_brief": {
        "topic": "Why AI agents will replace 40% of SaaS tools by 2027",
        "thesis": (
            "The next wave of AI isn't chatbots - it's autonomous agents that do the work "
            "dashboards only show you. Businesses still buying dashboard-first SaaS are "
            "investing in rearview mirrors."
        ),
        "audience": "Agency owners and ops leaders doing $10K-100K/mo who are drowning in SaaS tools",
        "desired_belief_shift": (
            "FROM: 'I need better dashboards and more integrations' "
            "TO: 'I need fewer tools that actually do the work for me'"
        ),
    },
    "trend_brief": {
        "summary": "AI agent frameworks exploding - CrewAI raised $18M, AutoGen adoption up 340%",
        "trends": [
            {"headline": "Gartner: 25% of enterprises will deploy AI agents by end of 2026"},
            {"headline": "CrewAI raises $18M Series A for multi-agent orchestration"},
            {"headline": "Microsoft AutoGen usage up 340% in 6 months"},
            {"headline": "Salesforce Agentforce processes 1 billion agent actions in first 3 months"},
            {"headline": "McKinsey: AI agents could automate 60-70% of current work activities"},
        ],
    },
    "research_brief": {
        "verified_claims": [
            {
                "claim": "Gartner predicts 25% of enterprises will deploy AI agents by end of 2026, up from less than 2% in 2024",
                "source": "Gartner, October 2024 report",
                "confidence": 0.95,
            },
            {
                "claim": "McKinsey estimates AI agents could automate 60-70% of current employee work activities",
                "source": "McKinsey Global Institute, 2024",
                "confidence": 0.9,
            },
            {
                "claim": "The average mid-size company uses 137 SaaS applications, up from 80 in 2020",
                "source": "Productiv SaaS Management Index 2024",
                "confidence": 0.85,
            },
            {
                "claim": "Salesforce Agentforce processed over 1 billion autonomous agent actions in its first 90 days",
                "source": "Salesforce Q4 2025 earnings call",
                "confidence": 0.95,
            },
            {
                "claim": "Companies using AI agents for customer service report 40% reduction in resolution time and 25% cost savings",
                "source": "Zendesk AI Impact Report 2025",
                "confidence": 0.85,
            },
            {
                "claim": "CrewAI raised $18M Series A at $100M valuation for multi-agent orchestration platform",
                "source": "TechCrunch, January 2025",
                "confidence": 0.95,
            },
            {
                "claim": "68% of SaaS spend is wasted on unused or underused licenses",
                "source": "Zylo State of SaaS Report 2024",
                "confidence": 0.8,
            },
        ],
        "source_refs": [
            {"title": "Gartner AI Agent Predictions 2026", "url": "https://gartner.com/en/articles/ai-agents"},
            {"title": "McKinsey Global Institute - AI at Work", "url": "https://mckinsey.com/mgi/ai-work"},
            {"title": "Productiv SaaS Management Index", "url": "https://productiv.com/report"},
            {"title": "Salesforce Q4 2025 Earnings", "url": "https://salesforce.com/investors"},
            {"title": "Zendesk AI Impact Report", "url": "https://zendesk.com/ai-report"},
            {"title": "TechCrunch - CrewAI Series A", "url": "https://techcrunch.com/crewai-series-a"},
            {"title": "Zylo State of SaaS 2024", "url": "https://zylo.com/saas-report"},
        ],
    },
    "cta_package": {"weekly_keyword": "AGENTSHIFT"},
}


async def main():
    api_key = os.environ.get("TCE_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Read from .env
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("TCE_ANTHROPIC_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
                        break
    if not api_key:
        print("ERROR: No API key found")
        return

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Build user prompt (same logic as DocxGuideBuilder._execute)
    ctx = SAMPLE_CONTEXT
    sb = ctx["story_brief"]
    rb = ctx["research_brief"]
    tb = ctx["trend_brief"]

    prompt_parts = [
        f"Weekly theme: {ctx['weekly_theme']}",
        f"Weekly CTA keyword: {ctx['weekly_keyword']}",
        f"Author name: {ctx['author_name']}",
        f"Core thesis: {sb['thesis']}",
        f"Target audience: {sb['audience']}",
        f"Desired belief shift: {sb['desired_belief_shift']}",
    ]

    trends_summary = [f"- {t['headline']}" for t in tb["trends"][:6]]
    prompt_parts.append("Current trends:\n" + "\n".join(trends_summary))

    prompt_parts.append(
        "VERIFIED EVIDENCE (use these facts in the guide):\n"
        + json.dumps(rb["verified_claims"], indent=2)
    )
    prompt_parts.append("Sources: " + json.dumps(rb["source_refs"][:10], indent=2))

    prompt_parts.append(
        "\nCreate the complete reader-facing guide. Remember: this is a GIFT "
        "for the reader, not an internal brief. Zero campaign/ops content."
    )

    user_msg = "\n\n".join(prompt_parts)

    print("Calling Sonnet 4 to generate guide content...")
    print(f"  Theme: {ctx['weekly_theme']}")
    print(f"  Keyword: {ctx['weekly_keyword']}")
    print(f"  Research claims: {len(rb['verified_claims'])}")

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        temperature=0.5,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text
    print(f"  Response: {len(text)} chars, {response.usage.input_tokens} in / {response.usage.output_tokens} out")

    # Parse JSON
    # Strip markdown code fences if present
    clean = text.strip()
    if clean.startswith("```"):
        first_nl = clean.index("\n")
        last_fence = clean.rfind("```")
        clean = clean[first_nl + 1 : last_fence].strip()

    try:
        guide_content = json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print("Raw response saved to guide_raw_response.txt")
        with open("guide_raw_response.txt", "w", encoding="utf-8") as f:
            f.write(text)
        return

    # Inject author info
    guide_content["author_name"] = ctx["author_name"]
    guide_content["author_url"] = "zivraviv.com"

    # Report
    title = guide_content.get("guide_title", "Weekly Guide")
    print(f"\n  Title: {title}")
    print(f"  Subtitle: {guide_content.get('subtitle', '')[:100]}")
    sections = guide_content.get("sections", [])
    print(f"  Sections ({len(sections)}):")
    for s in sections:
        st = s.get("type", "narrative")
        t = s.get("title", s.get("label", st))
        if st == "framework":
            print(f"    [{st}] {t} ({len(s.get('steps', []))} steps)")
        elif st == "scenarios":
            print(f"    [{st}] {t} ({len(s.get('scenarios', []))} scenarios)")
        elif st == "quick_win":
            print(f"    [{st}] {t} ({len(s.get('table_headers', []))} cols)")
        elif st == "closing":
            print(f"    [{st}] {s.get('headline', '')[:80]}")
            ynh = s.get("you_now_have", [])
            if ynh:
                print(f"      you_now_have: {ynh}")
        else:
            print(f"    [{st}] {t} ({len(s.get('content', ''))} chars)")

    # Generate DOCX
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    out_path = os.path.join(os.path.dirname(__file__), "..", f"{safe_title}.docx")
    create_guide_docx(guide_content, out_path)
    abs_path = os.path.abspath(out_path)
    print(f"\nDOCX generated: {abs_path}")
    print(f"File size: {os.path.getsize(abs_path):,} bytes")

    # Also save the JSON for inspection
    json_path = os.path.join(os.path.dirname(__file__), "..", f"{safe_title}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(guide_content, f, indent=2, ensure_ascii=False)
    print(f"JSON saved: {os.path.abspath(json_path)}")


if __name__ == "__main__":
    asyncio.run(main())
