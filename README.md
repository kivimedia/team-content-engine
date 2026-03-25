# Team Content Engine

Agentic content engine that learns from a swipe corpus and produces daily Facebook + LinkedIn post packages and a weekly DOCX guide.

## Architecture

Multi-agent pipeline built with Python + FastAPI, orchestrated via an async DAG engine.

### Agents (13 total)

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

### Data Model (16 entities)

SourceDocument, PostExample, CreatorProfile, FounderVoiceProfile, PatternTemplate, ResearchBrief, StoryBrief, PostPackage, WeeklyGuide, ImageAsset, QAScorecard, CostEvent, PromptVersion, OperatorFeedback, LearningEvent, TrendBrief

### Workflows

- **Daily Content**: Trend Scout → Story Strategist → Research Agent → FB/LI Writers → CTA Agent → Creative Director → QA Agent
- **Corpus Ingestion**: Corpus Analyst → Engagement Scorer → Pattern Miner
- **Weekly Planning**: Trend Scout → Story Strategist → Research Agent → CTA Agent → Guide Builder
- **Weekly Learning**: Learning Loop analysis and recommendations

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL
docker compose up -d db

# Run migrations
alembic upgrade head

# Start the API server
uvicorn tce.api.app:app --reload

# Run tests
pytest
```

## API Endpoints

All endpoints are prefixed with `/api/v1`.

- `GET /health` — Health check
- `POST /documents/upload` — Upload DOCX corpus
- `GET /documents` — List documents
- `GET/POST /profiles/creators` — Manage creator profiles
- `GET/POST /profiles/founder-voice` — Manage founder voice
- `GET/POST /patterns/templates` — Pattern template library
- `GET /briefs/stories|research|trends` — View briefs
- `GET/PATCH /content/packages` — Manage post packages
- `POST /content/packages/{id}/approve|reject` — Approval flow
- `GET/POST /content/guides` — Weekly guides
- `GET /qa/scorecards` — QA scorecards
- `POST /pipeline/run` — Trigger workflow
- `GET /pipeline/{run_id}/status` — Pipeline status
- `GET /costs/daily|monthly` — Cost tracking
- `GET/POST /prompts/{agent}` — Prompt versioning
- `POST /feedback` — Operator feedback
- `POST /trends/scan` — Trigger trend scan

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI
- **Database**: PostgreSQL with pgvector
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **LLM**: Anthropic Claude API
- **Image Gen**: fal.ai
- **DOCX**: python-docx
