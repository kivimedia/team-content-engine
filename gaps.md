# Team Content Engine - PRD v3.0 Gap Analysis

**Generated:** 2026-03-26
**PRD:** `C:\Users\raviv\Downloads\Team_Content_Engine_Complete_v3.0.md`
**Codebase:** `C:\Users\raviv\Team Content Engine\` / VPS `/home/ziv/tce/`
**Closed:** 2026-03-26 (14/14 critical+high+medium gaps)

---

## Critical (core functionality broken)

### GAP-01: No web search integration for Trend Scout + Research Agent
- **PRD:** 37.2, 49.3, 49.7
- **Issue:** Both agents use LLM internal knowledge only. No live web search API.
- **Fix:** Brave Search API client (`src/tce/services/web_search.py`). TrendScout calls `search_news()` + `search_fresh()` for focus areas. ResearchAgent calls `search()` for claim verification.
- **Status:** [x] Closed - deployed to VPS

### GAP-02: No OCR pipeline for screenshot ingestion
- **PRD:** 9.1, 38.2
- **Issue:** Can't parse screenshots from swipe corpus DOCX.
- **Fix:** `document_ingest.py` - `_extract_images_ocr()` extracts DOCX embedded images, sends to Claude Haiku vision API for Hebrew-aware OCR.
- **Status:** [x] Closed - deployed to VPS

### GAP-03: No comment-to-DM detection (CTA fulfillment loop)
- **PRD:** 24.4
- **Issue:** Core CTA loop has no webhook/polling for keyword comments.
- **Fix:** `src/tce/services/cta_fulfillment.py` - FB Graph API webhook + keyword matching + Messenger DM. LinkedIn manual fallback. Endpoints in `dm_fulfillment.py`.
- **Status:** [x] Closed - deployed to VPS

---

## High (significant functionality missing)

### GAP-04: No S3/object storage
- **PRD:** 23.1, 41.2, 43.5
- **Issue:** Images stored as fal.ai temp URLs only.
- **Fix:** `src/tce/services/storage.py` - S3-compatible client (upload, download, upload_from_url). Graceful skip when no creds.
- **Status:** [x] Closed - deployed to VPS

### GAP-05: Trend scan endpoint is a stub
- **PRD:** 49.6, 49.9
- **Issue:** `/trends/scan` returned stub response.
- **Fix:** `trends.py` router now spawns background TrendScout agent via `asyncio.create_task`. New `GET /trends/scan/{scan_id}` for polling results.
- **Status:** [x] Closed - deployed to VPS

### GAP-06: Backup is a placeholder
- **PRD:** 43.5
- **Issue:** Wrote placeholder text, no actual backup.
- **Fix:** `backup.py` now runs `docker exec tce-db pg_dump` (with direct fallback). `scheduler.py` runs daily backup at 2 AM + cleanup.
- **Status:** [x] Closed - deployed to VPS

### GAP-07: Multi-segment prompt caching not implemented
- **PRD:** 36.8
- **Issue:** Only single cache segment used.
- **Fix:** `src/tce/services/cache_prefix.py` - CachePrefixBuilder loads 6 segments (system prompt, house voice, templates, rubric, profiles, CTA rules) each with `cache_control: ephemeral`. Integrated in `base.py _call_llm`.
- **Status:** [x] Closed - deployed to VPS

### GAP-08: No feature flags for publishing
- **PRD:** 24.3
- **Issue:** No toggle system for FB/LI publishing.
- **Fix:** `feature_flags` DB table + `src/tce/services/feature_flags.py` with 60s in-memory cache. 7 default flags auto-seeded.
- **Status:** [x] Closed - deployed to VPS (migration 005)

---

## Medium (incomplete but functional)

### GAP-09: Email/webhook notification channels missing
- **PRD:** 43.1
- **Issue:** Only in-app notifications.
- **Fix:** `notifications.py` - `_send_email()` via Resend API, `_send_webhook()` to Slack. Auto-dispatches for warning/critical severity.
- **Status:** [x] Closed - deployed to VPS

### GAP-10: Cost dashboard missing breakdowns
- **PRD:** 36.4
- **Issue:** Only totals exposed.
- **Fix:** `costs.py` - 4 new endpoints: `/by-agent`, `/model-distribution`, `/cache-efficiency`, `/per-post`.
- **Status:** [x] Closed - deployed to VPS

### GAP-11: No relearning API router
- **PRD:** 48.7
- **Issue:** RelearningService had no API.
- **Fix:** `src/tce/api/routers/relearning.py` - `/status`, `/evaluate`, `/proposals` endpoints. Registered in app.py.
- **Status:** [x] Closed - deployed to VPS

### GAP-12: Weekly cost report missing from learning loop
- **PRD:** 15.4, 36.6
- **Issue:** Learning loop didn't include cost data.
- **Fix:** `scheduler.py _execute_job` gathers cost data via CostTracker + CostOptimizationService before running weekly_learning workflow. Passes as `cost_summary` context.
- **Status:** [x] Closed - deployed to VPS

### GAP-13: Missing DB fields
- **PRD:** 11.1, 11.7, 11.8
- **Issue:** Missing `actual_joins`, `ingested_at`, `image_prompts` columns.
- **Fix:** Migration 005 adds all three. ORM models updated.
- **Status:** [x] Closed - deployed to VPS

### GAP-14: Missing .env vars
- **PRD:** Multiple
- **Issue:** Missing env vars for new services.
- **Fix:** `.env.example` + `settings.py` updated with 14 new `TCE_` prefixed vars.
- **Status:** [x] Closed - deployed to VPS

---

## Low (nice-to-have, not blocking)

### GAP-15: Deconstruction record field + API
- **PRD:** 48.5
- **Issue:** No `deconstruction_record` JSONB on post_examples. No API for corpus review in Appendix C format.

### GAP-16: `SourceDocument.ingested_at` vs `created_at` distinction
- **PRD:** 11.1
- **Issue:** Minor schema distinction - covered in GAP-13.

---

## UI/UX Gaps (identified 2026-03-28)

### Critical - Daily workflow blockers

### GAP-17: No inline post editing
- **PRD:** 22.2
- **Issue:** Can "AI Revise" and "Copy" but can't directly edit post text. Must use separate "Edit & Submit Copy" form.
- **Status:** [ ]

### GAP-18: No "Why was this chosen?" explainability
- **PRD:** 22.2
- **Issue:** Packages show raw posts with zero context - no angle reasoning, template justification, influence weights, or research brief summary.
- **Status:** [ ]

### GAP-19: DM Flow is read-only
- **PRD:** 24.4
- **Issue:** CTA Flow Editor described in PRD (keyword config, DM reply builder, delivery message editor). Currently static text with "Copy All" only.
- **Status:** [ ]

### GAP-20: No operator notes on day cards
- **PRD:** 22.1
- **Issue:** Planner week grid has no way to add operator notes per day. PRD: "Operator can manually add topics", notes field.
- **Status:** [ ]

### GAP-21: No post scheduling/publishing controls
- **PRD:** 5.3, 24.3
- **Issue:** Status badges exist (APPROVED/PUBLISHED) but no "Schedule" or "Publish now" button. Approval is a dead end.
- **Status:** [ ]

### High Priority - Missing screens/features

### GAP-22: No Settings page
- **PRD:** 36.4, 43.1
- **Issue:** API key management, budget caps, notification preferences, audience config, voice tone adjustment - all env vars only.
- **Status:** [ ]

### GAP-23: No Notification Center
- **PRD:** 43.1
- **Issue:** Package ready alerts, QA failure alerts, budget warnings, 72h approval timeout reminders. Zero notification system in UI.
- **Status:** [ ]

### GAP-24: No Research Brief visibility
- **PRD:** 9.4, 22.2
- **Issue:** Research Agent produces verified facts, sources, caveats, "safe to publish" statement. Never shown in package UI.
- **Status:** [ ]

### GAP-25: No Template Library browser
- **PRD:** 9.3
- **Issue:** View, search, lock/unlock templates. Pattern Miner output invisible in UI.
- **Status:** [ ]

### GAP-26: Analytics is shallow
- **PRD:** 8.1, 8.2, 8.3
- **Issue:** PRD: actual vs predicted, best CTAs, best templates, visual performance, failure modes. Current: 4 summary cards only.
- **Status:** [ ]

### Medium Priority - Polish and workflow

### GAP-27: No global search
- **PRD:** 22.1
- **Issue:** Search posts by topic, creator, template across the whole system. No search exists.
- **Status:** [ ]

### GAP-28: No breadcrumb navigation
- **PRD:** 22.1
- **Issue:** PRD calls for breadcrumbs. Tabs are flat with no workflow context.
- **Status:** [ ]

### GAP-29: Package filter is day-only
- **PRD:** 22.1
- **Issue:** No filter by status (draft/approved/rejected), date range, or QA score.
- **Status:** [ ]

### GAP-30: No drag-and-drop calendar
- **PRD:** 22.1
- **Issue:** Rescheduling controls - can't move posts between days.
- **Status:** [ ]

### GAP-31: No buffer posts
- **PRD:** 22.1
- **Issue:** "Maintain 2-3 pre-approved packages as backup." No buffer concept in UI.
- **Status:** [ ]

### GAP-32: No Prompt Library manager
- **PRD:** 39
- **Issue:** View/edit/version agent prompts. Not exposed in UI.
- **Status:** [ ]

### GAP-33: No Chatbot interface
- **PRD:** 44
- **Issue:** Conversational chat panel for natural language pipeline control. Not implemented.
- **Status:** [ ]

### GAP-34: QA scorecard lacks dimension details
- **PRD:** 46
- **Issue:** Shows scores as numbers with tooltip hovers. PRD: 12 dimensions with full justification text, expandable details.
- **Status:** [ ]

### GAP-35: No keyboard shortcuts
- **Issue:** No keyboard navigation for daily editorial tool. Standard UX expectation (J/K nav, Enter approve, etc).
- **Status:** [ ]

### GAP-36: Creator influence weights not adjustable
- **PRD:** 4.4
- **Issue:** Shows weights but no sliders/controls to change them. PRD: "edit influence weights."
- **Status:** [x] Closed - GAP-17 through GAP-36 deployed 2026-03-28

---

## Bugs Found (2026-03-28 second audit)

### BUG-01: `_packagesCache` vs `_pkgCache` variable mismatch
- **Impact:** Download All, inline edit, DM edit, schedulePublish all broken - wrong variable name
- **Fix:** Replace all `_packagesCache` with `_pkgCache`
- **Status:** [x] Fixed

### BUG-02: `switchTab()` function not defined
- **Impact:** "Package" button in weekly plan summary throws ReferenceError
- **Fix:** Added `switchTab(tabName)` helper function
- **Status:** [x] Fixed

### BUG-03: Chat tab unreachable
- **Impact:** Chat tab existed in router map but had no nav button
- **Fix:** Added `<button data-tab="chat">Chat</button>` to nav
- **Status:** [x] Fixed

### BUG-04: Settings save buttons not persisting
- **Impact:** Budget and audience settings lost on page refresh
- **Fix:** Wired to localStorage with pre-population on render
- **Status:** [x] Fixed

---

## Remaining PRD Gaps (2026-03-28 second audit)

### GAP-37: Visual Prompt Review - image selection + individual regeneration
- **PRD:** 41.2
- **Issue:** PRD requires operator to select 1 of 3 images (radio select), regenerate individual images with adjusted prompts. Current UI shows all images but has no selection or per-image regen.
- **Status:** [ ]

### GAP-38: Relearning Review Screen
- **PRD:** 48.7
- **Issue:** Before/after comparison of corpus changes. Proposed template/score/weight changes with approve/reject per change. No screen exists.
- **Status:** [ ]

### GAP-39: Founder Voice editing
- **PRD:** 50
- **Issue:** Voice Profile tab is read-only. PRD: editable vocabulary signature, values/beliefs, metaphor families, taboos, "I don't talk like that anymore" correction.
- **Status:** [ ]

### GAP-40: House Voice axis sliders
- **PRD:** 14.1
- **Issue:** 10 voice axes (curiosity, sharpness, practicality, etc.) need adjustable sliders, not just display bars.
- **Status:** [ ]

### GAP-41: Cost Dashboard visualizations
- **PRD:** 36.4
- **Issue:** PRD requires stacked bar charts (daily spend by agent), weekly/monthly trend lines, budget threshold markers. Current: numbers only.
- **Status:** [ ]

### GAP-42: A/B Testing Framework UI
- **PRD:** 43.2
- **Issue:** experiment_id/variant tagging on packages, hook/CTA/visual/prompt variant testing, results in analytics. Nothing exists.
- **Status:** [ ]

### GAP-43: Creator management controls
- **PRD:** 16.4
- **Issue:** Approve/reject creators, exclude from angle types (checkboxes per template family), edit anti-clone markers. Only name + weight shown.
- **Status:** [ ]

### GAP-44: Engagement Scorer controls
- **PRD:** 9.2
- **Issue:** Change scoring weights (shares/comments multipliers), exclude low-confidence posts. No controls.
- **Fix:** `GET/POST /controls/scorer-weights` endpoints + `OperatorControlService` scorer weight methods. Default weights: shares 3.0, comments 2.0, saves 2.5, likes 1.0, clicks 1.5, dwell_time 1.0.
- **Status:** [x] Closed

### GAP-45: CTA Flow Editor (full)
- **PRD:** 9.7
- **Issue:** Full CTA editor: weekly primary keyword, per-post secondary, DM reply chain builder with fulfillment checklist. Current DM Flow edit is field-level only.
- **Status:** [ ]

### GAP-46: DOCX Guide Viewer
- **PRD:** 9.9
- **Issue:** Inline guide preview, Export PDF, markdown mirror, operator fulfillment checklist. Currently: DOCX download link only.
- **Status:** [ ]

### GAP-47: Seasonal adjustment controls
- **PRD:** 43.3
- **Issue:** Override 5-day cadence for holidays/launches. No controls.
- **Status:** [ ]

### GAP-48: Humanitarian override with justification
- **PRD:** 51.5
- **Issue:** Override button on flagged posts, required written justification, logged in weekly report. No such control exists.
- **Status:** [ ]

### GAP-49: Pipeline partial resume
- **PRD:** 42.4
- **Issue:** Resume from last successful step (step indicator showing where it stopped). Current: retry-all only.
- **Fix:** `resume_from_step` param on `POST /pipeline/run` + `PipelineOrchestrator.run()`. Marks all predecessor steps as COMPLETED, starts execution from the named step.
- **Status:** [x] Closed

### GAP-50: Per-creator influence weights per angle type
- **PRD:** 14.2
- **Issue:** Different weights per angle type (e.g. creator X at 40% for case_study but 10% for contrarian). Current slider is global only.
- **Status:** [ ]

### GAP-51: Prompt side-by-side comparison
- **PRD:** 39
- **Issue:** Compare two prompt versions side-by-side, see which packages used which version. Current: version list with rollback only.
- **Status:** [ ]

### GAP-52: Corpus low-confidence flagging
- **PRD:** 22.1
- **Issue:** Corpus Review should flag low-confidence parsed items for operator review. Not implemented.
- **Status:** [ ]
