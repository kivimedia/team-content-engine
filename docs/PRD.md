# Team Content Engine — Product Requirements Document (PRD)

**Version:** 3.0
**Date:** 2026-03-25
**Prepared for:** Ziv Raviv

## 1. Executive Summary

Build a Team Content Engine that ingests a DOCX swipe corpus of high-performing creators, reverse-engineers the repeatable mechanics behind the strongest posts, blends those mechanics into a distinct house voice, and generates a daily content package for Facebook and LinkedIn without becoming a clone of any source creator.

The product must:
- Accept the current corpus and future tabs/creators without redesign
- Score posts using visible engagement evidence
- Mine recurring narrative and structural patterns
- Verify future factual claims from primary sources before writing
- Create platform-specific copy and creative directions
- Support "say XXX" CTAs without fake lead magnets
- Produce one unique, polished DOCX brief per post
- Learn weekly from post outcomes and improve recommendations

## 2. Product Vision

Create a modular studio that behaves like a small editorial team: learn from the swipe corpus, score what worked, extract reusable structures, research the next topic deeply, strategize the best angle, write for Facebook and LinkedIn, design strong visual prompts, package everything into a post kit and a polished DOCX guide, publish or queue, measure and improve.

The end state is not "an AI writer." The end state is an editorial operating system.

## 3. Product Principles

### 3.1 Steal Mechanics, Not Exaggeration
The system may learn hook mechanics, story structure, rhythm, CTA design, visual patterns. The system may not reproduce unsupported claims, fake urgency, fabricated proof, exaggerated certainty, misleading screenshots or fabricated testimonials.

### 3.2 Truth Over Hype
Future content must pass a research gate using primary sources before drafts are approved.

### 3.3 Influence, Not Cloning
The system should blend influences into a house style rather than imitate an individual creator's voice verbatim.

### 3.4 Human Override
A human operator must be able to approve or reject sources, edit influence weights, lock or ban certain templates, approve publishing, override CTAs, disable automation per platform.

### 3.5 Extensible Corpus
The system must be able to ingest more tabs, more creators, more screenshots, more formats later and update rankings, templates, and influence weights without a schema rewrite.

## 4. In Scope (v1)

### Input Types
- DOCX swipe files with creator sections and post screenshots
- Optional future PDFs/images/slides
- External research sources for factual validation
- Operator-defined editorial goals and content priorities

### Output Package (Per Post Day, Mon-Fri)
- Facebook draft
- LinkedIn draft
- 5-10 short hook variants
- CTA keyword and comment-to-DM flow (references the weekly guide)
- 3 fal.ai-ready image prompts
- Metadata record for analytics and learning

### Weekly Output
- One polished DOCX guide (shared lead magnet for all 5 posts)

### Operating Cadence
- One post per day, five days per week (Monday through Friday)
- A weekly learning update that recalibrates recommendations

## 5. Source Corpus and Influence Model

### v1 Corpus Creators
- **Omri Barak:** big-news hooks, paradox, famous names, urgency
- **Ben Z. Yabets:** second-person diagnosis, 3-point frameworks, clean keyword CTAs
- **Nathan Savis:** contrarian openings, teardown energy, proof, high-tension copy
- **Eden Bibas:** practical AI utility posts, bullet-based clarity, guide/WhatsApp conversion CTAs
- **Alex Kap:** strategic depth, second-order implications, "what changed / what it means" analysis

### House Voice
Omri's curiosity + Ben's structure + Nathan's edge + Eden's practicality + Alex's strategic depth

### Default Influence Weights
Omri: 0.24, Ben: 0.20, Nathan: 0.20, Eden: 0.18, Alex: 0.18

## 6. Functional Requirements

### 6.1 Corpus Analyst
Parse the source DOCX into structured training rows with hook/body/CTA/visual classification.

### 6.2 Engagement Scorer
Rank examples using: `final_score = ((shares * 3.0) + (comments * 1.0)) * confidence_multiplier`
- Confidence A (both visible): 1.00
- Confidence B (one visible): 0.75
- Confidence C (cropped/unclear): 0.40

### 6.3 Pattern Miner
Extract repeatable mechanics into a reusable Template Library.

### 6.4 Research Agent
Verify claims from primary sources. Hard claims require source support. Soft claims require signal words. Opinion claims must be framed as opinion.

### 6.5 Story Strategist (Opus 4.6)
Choose the daily angle and best-fit template from the 5-day cadence:
- Monday: Big AI shift explained
- Tuesday: Practical workflow/tool post
- Wednesday: Contrarian belief-shift post
- Thursday: Case study/build-with-AI post
- Friday: Strategic implication/future-of-work post

### 6.6 Platform Writers
- **Facebook Writer:** Engagement engine (comments, shares, CTAs). 150-400 words, punchy, conversational.
- **LinkedIn Writer:** Authority engine (saves, follows). 300-800 words, executive, precise.

### 6.7 CTA / Funnel Agent
Weekly keyword model — one primary keyword per week mapping to the weekly guide.

### 6.8 Creative Director
Generate 3 visual directions per post: hero scroll-stopper, proof/diagram, alternate emotional.

### 6.9 DOCX Guide Builder
One polished guide per week covering the weekly theme with 12 required sections.

### 6.10 QA + Learning Loop
12-dimension scoring rubric with weighted composite and hard gates.

## 7. QA Scoring Rubric (12 Dimensions)

| Dimension | Pass Threshold | Weight |
|-----------|---------------|--------|
| Evidence completeness | >= 7 | 12% |
| Freshness | >= 7 | 8% |
| Clarity | >= 7 | 12% |
| Novelty | >= 6 | 8% |
| Non-cloning | >= 8 | 12% |
| Audience fit | >= 7 | 8% |
| CTA honesty | >= 9 | 8% |
| Platform fit | >= 7 | 5% |
| Visual coherence | >= 6 | 5% |
| House voice fit | >= 7 | 5% |
| Humanitarian sensitivity | >= 8 | 10% |
| Founder voice alignment | >= 7 | 7% |

**Hard gates:** humanitarian_sensitivity < 8 = FAIL, cta_honesty < 9 = FAIL

## 8. House Voice System

10 configurable voice axes: curiosity, sharpness, practicality, strategic_depth, emotional_intensity, sentence_punch, executive_clarity, contrarian_heat, friendliness, urgency.

Per-angle weight adjustments supported. Anti-clone controls: semantic similarity threshold (0.85), phrase blacklist, rhythm variation requirement.

## 9. Founder Voice Layer

The founder's voice is the identity layer. Priority: Founder voice > House voice > Template structure. Extracted from books, posts, transcripts via FounderVoiceExtractor agent.

## 10. Humanitarian Sensitivity Gate

Non-negotiable. Cannot be disabled. Weight cannot be set below 8%. Threshold cannot be set below 7. Checks: fear exploitation, tone mismatch with current events, dignity violations, war metaphors during conflict, punishment framing.

## 11. Key Non-Functional Requirements

- **Modularity:** Each agent independently swappable
- **Auditability:** Every draft traceable to source patterns, research, prompts, approvals
- **Deterministic Records:** Every run saves inputs, model versions, config versions, outputs, QA decisions
- **Human Reviewability:** Operator can inspect why any decision was made
- **Extensibility:** More creators, platforms, languages, cadences

## 12. Template Library (10 Families)

1. Big Shift Explainer (Monday)
2. Tactical Workflow Guide (Tuesday)
3. Contrarian Diagnosis (Wednesday)
4. Case Study / Build Story (Thursday)
5. Second-Order Implication (Friday)
6. Hidden Feature / Tool Shortcut (Tuesday alt)
7. Teardown / Myth Busting (Wednesday alt)
8. Weekly Roundup (Friday alt)
9. Founder Reflection
10. Comment Keyword CTA Guide

## 13. Architecture

- **Backend:** Python 3.11+ / FastAPI
- **Database:** PostgreSQL with pgvector
- **ORM:** SQLAlchemy 2.0 (async)
- **Migrations:** Alembic
- **LLM:** Anthropic Claude API (Opus/Sonnet/Haiku tiers)
- **Image Gen:** fal.ai (Flux Pro)
- **DOCX:** python-docx
- **Orchestration:** Custom async DAG engine

### Model Assignments
| Agent | Model |
|-------|-------|
| Story Strategist | Opus 4.6 |
| Corpus Analyst | Sonnet 4.6 |
| Pattern Miner | Sonnet 4.6 |
| Research Agent | Sonnet 4.6 |
| FB/LI Writers | Sonnet 4.6 |
| CTA Agent | Sonnet 4.6 |
| Creative Director | Sonnet 4.6 |
| QA Agent | Sonnet 4.6 |
| Engagement Scorer | Haiku 4.5 |

## 14. Estimated Costs

With prompt caching: ~$655-700/month (5-day cadence, English output)
Without caching: ~$1,135-1,180/month
Floor estimate: ~$350-400/month (3 posts/week, batch research, Sonnet-only)

## 15. Acceptance Criteria

See PRD v3.0 Section 27 for the complete list of 20+ acceptance criteria covering corpus ingestion, scoring, template library, daily/weekly workflows, QA gates, cost tracking, prompt versioning, chatbot interface, relearning, trend scouting, and more.

---

*This is a summary of the full PRD v3.0. The complete specification includes detailed sections on workflows (15), data model (11), CTA/funnel rules (18), creative prompt system (19), publishing adapters (24), security (25), observability (26), phased implementation (28), risks (29), and appendices (A-H) with scoring rubric, template library, corpus deconstructions, worked example, reference prompts, entity relationship diagram, phase timelines, and edge case scenarios.*
