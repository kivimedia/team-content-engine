# TCE PRD v3.0 - Implementation Gaps

**Audit Date:** 2026-03-28
**Status:** IN PROGRESS

## HIGH PRIORITY

### 1. Template Library Not Seeded (Section 9.3 / Appendix B)
- Pattern Miner exists but the 10 reference templates aren't pre-loaded
- Need seed data: Big Shift Explainer, Contrarian Diagnosis, Tactical Workflow, Case Study, etc.
- **Files:** `src/tce/services/seed.py`, `src/tce/models/pattern_template.py`
- **Status:** [ ]

### 2. Voice Axes Not Explicit in House Voice (Section 14.1)
- The 10 voice axes (curiosity, sharpness, practicality, etc.) not modeled as numeric sliders
- Influence weights exist but axes are implicit
- **Files:** `src/tce/services/house_voice.py`, `src/tce/models/creator_profile.py`
- **Status:** [ ]

### 3. Engagement Scorer Missing Outlier/Sample Guards (Section 12.6)
- No outlier trimming (5x threshold) or minimum sample size enforcement
- One viral post could skew template rankings
- **Files:** `src/tce/agents/engagement_scorer.py`
- **Status:** [ ]

### 4. A/B Testing Assignment Not Deterministic (Section 43.2)
- PRD requires deterministic assignment (e.g. odd dates = version A)
- May be using random instead of hash-based
- **Files:** `src/tce/services/ab_testing.py`
- **Status:** [ ]

### 5. QA Dimension Weights Not Validated (Section 45.2)
- Weights may not sum to 100%, no guard against operator misconfiguration
- **Files:** `src/tce/agents/qa_agent.py`
- **Status:** [ ]

## MEDIUM PRIORITY

### 6. Batch API Not Integrated (Section 36.8)
- Research Agent could save ~50% via Anthropic Batch API
- CostTracker tracks batch_api_used but doesn't use it
- **Files:** `src/tce/services/cost_tracker.py`, LLM call layer
- **Status:** [ ]

### 7. Publishing Adapters Tightly Coupled (Section 24)
- No adapter pattern for FB vs LI API differences
- **Files:** `src/tce/services/publishing.py`
- **Status:** [ ]

### 8. Prompt Caching Not Verified (Section 36.8)
- cache_prefix service exists but cache_control breakpoints may not hit cache
- **Files:** `src/tce/services/cache_prefix.py`
- **Status:** [ ]

### 9. Trend Scout Source Diversity (Section 49.4)
- Not verified it queries all 6+ recommended sources
- **Files:** `src/tce/agents/trend_scout.py`
- **Status:** [ ]

### 10. CTA No-Asset Playbook Incomplete (Section 18.3)
- PRD lists 5 fallback paths when no asset is ready
- Only some are implemented
- **Files:** `src/tce/agents/cta_agent.py`
- **Status:** [ ]

## LOW PRIORITY

### 11. DOCX Guide Design Polish (Section 20.4)
- Functional but looks like AI template
- Needs custom fonts, callout boxes, cover art
- **Files:** `src/tce/agents/docx_guide_builder.py`
- **Status:** [ ]

### 12. Cost Report Missing Optimization Recommendations (Section 36.6)
- Shows spend but doesn't suggest optimizations
- **Files:** `src/tce/api/routers/costs.py`
- **Status:** [ ]

### 13. No Auto-Rollback on Prompt QA Failure (Section 39.5)
- Prompts versioned but no auto-flag for rollback on quality drop
- **Files:** `src/tce/services/prompt_manager.py`
- **Status:** [ ]

### 14. QA Humanitarian Gate Lacks Daily Current-Events Feed (Section 51.3)
- Gate accepts current_events_context but Trend Scout doesn't auto-populate it
- **Files:** `src/tce/agents/qa_agent.py`, `src/tce/orchestrator/workflows.py`
- **Status:** [ ]

### 15. No Angle-Specific Influence Weights (Section 14.2)
- All post types use same weights
- PRD says tool-focused posts should lean heavier on certain creators
- **Files:** `src/tce/services/house_voice.py`
- **Status:** [ ]
