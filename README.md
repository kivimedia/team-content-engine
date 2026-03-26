# Team Content Engine

Agentic content engine that learns from a swipe corpus and produces daily Facebook + LinkedIn post packages and a weekly DOCX guide. Built from a comprehensive PRD v3.0 specification.

## Architecture

Multi-agent pipeline built with Python + FastAPI, orchestrated via an async DAG engine with automatic cost tracking, prompt versioning, and database persistence.

### Agents (14 total)

| Agent | Model | Purpose |
|-------|-------|---------|
| Corpus Analyst | Sonnet 4.6 | Parse DOCX swipe files into structured PostExample records |
| Engagement Scorer | Haiku 4.5 | Rank posts using visible comments/shares with confidence adjustment |
| Pattern Miner | Sonnet 4.6 | Extract reusable templates from high-scoring posts |
| Trend Scout | Sonnet 4.6 | Discover trending stories and angles worth writing about |
| Story Strategist | Opus 4.6 | Choose the daily angle and best-fit template |
| Research Agent | Sonnet 4.6 | Verify claims from primary sources before drafting |
| Facebook Writer | Sonnet 4.6 | Write engagement-optimized FB posts |
| LinkedIn Writer | Sonnet 4.6 | Write authority-building LI posts |
| CTA Agent | Sonnet 4.6 | Handle "say XXX" keyword CTAs and DM flows |
| Creative Director | Sonnet 4.6 | Generate 3 fal.ai image prompts per post |
| DOCX Guide Builder | Sonnet 4.6 | Create weekly lead magnet guide |
| QA Agent | Sonnet 4.6 | 12-dimension quality scoring with pass/fail gates |
| Learning Loop | Sonnet 4.6 | Weekly performance analysis and recommendations |
| Founder Voice Extractor | Sonnet 4.6 | Extract founder's authentic voice from books/posts |

### Data Model (18 entities)

SourceDocument, PostExample, CreatorProfile, FounderVoiceProfile, PatternTemplate, ResearchBrief, StoryBrief, PostPackage, WeeklyGuide, ImageAsset, QAScorecard, CostEvent, PromptVersion, OperatorFeedback, LearningEvent, TrendBrief, ContentCalendarEntry, Notification

### Services (17 total)

| Service | PRD Section | Purpose |
|---------|-------------|---------|
| CostTracker | 36 | Per-agent per-run LLM cost tracking with model-specific pricing |
| PromptManager | 39 | Versioned prompts with rollback support |
| PipelineResultSaver | - | Converts agent output dicts to ORM records |
| DocumentIngestService | 9.1 | Parse DOCX/text uploads |
| LearningService | 9.10 | Aggregate performance data for learning loop |
| ChatbotService | 44 | Conversational operator interface (12 intents) |
| RelearningService | 48 | Corpus relearning with 3 trigger types |
| HouseVoiceEngine | 14 | Voice blending with 10 axes, per-angle weights |
| NotificationService | 43.1 | Operator alerts (7 notification types) |
| ABTestingService | 43.2 | Experiment management with deterministic assignment |
| ImageGenerationService | 41 | fal.ai integration with retry and batch support |
| ResilienceManager | 42 | Circuit breaker, rate limiting, fallback models |
| WhatsAppService | 40 | CTA fulfillment flows with compliance |
| HumanitarianGate | 51 | Non-negotiable sensitivity checks on content |
| CostOptimizationService | 36.8 | Spending analysis and optimization recommendations |
| CompetitorMonitorService | 43.4 | Source creator overlap and trend detection |
| OnboardingService | 43.6 | Quickstart, glossary, troubleshooting, role docs |

### Workflows

- **Daily Content**: Trend Scout -> Story Strategist -> Research Agent -> FB/LI Writers -> CTA Agent -> Creative Director -> QA Agent
- **Corpus Ingestion**: Corpus Analyst -> Engagement Scorer -> Pattern Miner
- **Weekly Planning**: Trend Scout -> Story Strategist -> Research Agent -> CTA Agent -> Guide Builder
- **Weekly Learning**: Learning Loop analysis and recommendations

### QA Scoring (12 dimensions)

Evidence completeness (12%), Freshness (8%), Clarity (12%), Novelty (8%), Non-cloning (12%), Audience fit (8%), CTA honesty (8%), Platform fit (5%), Visual coherence (5%), House voice fit (5%), Humanitarian sensitivity (10%), Founder voice alignment (7%)

Hard gates: humanitarian_sensitivity >= 8, cta_honesty >= 9

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL
docker compose up -d db

# Run migrations
alembic upgrade head

# Start the API server (seeds 5 creators + 10 templates on startup)
uvicorn tce.api.app:app --reload

# Run tests (152 tests)
pytest
```

## API Endpoints (20 routers)

All endpoints prefixed with `/api/v1`.

| Router | Key Endpoints |
|--------|-----------|
| Health | `GET /health` |
| Documents | `POST /documents/upload`, `GET /documents/{id}/examples` |
| Profiles | CRUD `/profiles/creators`, `/profiles/founder-voice` |
| Patterns | CRUD `/patterns/templates` |
| Briefs | `GET /briefs/stories`, `/briefs/research`, `/briefs/trends` |
| Content | CRUD `/content/packages`, approve/reject/export, CRUD `/content/guides` |
| QA | `GET /qa/scorecards`, `GET /qa/scorecards/package/{id}` |
| Pipeline | `POST /pipeline/run`, `GET /pipeline/{id}/status` |
| Costs | `GET /costs/daily`, `GET /costs/monthly`, `GET /costs/run/{id}` |
| Prompts | CRUD `/prompts/{agent}`, `POST /prompts/{agent}/rollback` |
| Feedback | `POST /feedback`, `POST /feedback/learning` |
| Calendar | `POST /calendar/plan-week`, `GET /calendar/today` |
| Scheduler | `GET /scheduler/status`, `POST /scheduler/trigger/{job}` |
| Chat | `POST /chat` (conversational operator interface) |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` |
| Experiments | CRUD `/experiments`, `GET /experiments/{id}/results` |
| Onboarding | `GET /onboarding/quickstart`, `/glossary`, `/troubleshooting` |
| Admin | `POST /admin/seed` |

## Seed Data

Auto-loaded on startup:

- **5 Creator Profiles**: Omri Barak, Ben Z. Yabets, Nathan Savis, Eden Bibas, Alex Kap
- **10 Pattern Templates**: Big Shift Explainer, Tactical Workflow Guide, Contrarian Diagnosis, Case Study, Second-Order Implication, Hidden Feature, Teardown, Weekly Roundup, Founder Reflection, Comment Keyword CTA Guide
- **3 Starter Prompts**: Story Strategist, Facebook Writer, QA Agent

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI
- **Database**: PostgreSQL with pgvector
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **LLM**: Anthropic Claude API (Opus/Sonnet/Haiku tiers)
- **Image Gen**: fal.ai (Flux Pro)
- **DOCX**: python-docx
- **Resilience**: tenacity (retry), custom circuit breaker
- **CI**: GitHub Actions (ruff + mypy + pytest)
