# Open-Source Evaluation Notes (PRD Section 47)

Evaluated repositories for potential use in the Team Content Engine build.

## Evaluated Repositories

| Repository | Stars | Potential Use | Risk Level | Decision |
|------------|-------|--------------|------------|----------|
| CrewAI | 47k | Agent orchestration (10-agent pipeline) | MEDIUM | **Evaluated, not adopted.** Closest architectural match but we built a custom async DAG orchestrator for tighter control over persistence and cost tracking. |
| LangGraph / LangChain | 113k | Workflow orchestration + tool use | LOW | **Evaluated, not adopted.** Mature and well-documented but heavier than needed. We use the Anthropic SDK directly for LLM calls. |
| n8n | 80k+ | Scheduling, WhatsApp triggers, notifications | LOW | **Not adopted for v1.** Could handle non-LLM automation in v2. Our scheduler is lightweight asyncio-based. |
| Dify | 114k | Chatbot interface + RAG + workflow | MEDIUM | **Not adopted.** Built custom chat panel (POST /chat endpoint) per PRD Section 44.5 recommendation. |
| AgentNeo | ~1k | Agent observability + cost tracing | HIGH | **Not adopted.** Smaller project, fewer contributors. Built custom CostTracker and CostEvent model instead. |
| Akamai social-transform | <1k | Reference architecture for multi-agent social content | LOW (reference) | **Used as reference only.** CrewAI-based FB/LI content pipeline. Good for patterns, not for direct code reuse. |

## Build vs Buy Decisions

### Built (our IP)
- Editorial intelligence: prompts, house voice system, scoring rubric, template library, QA rubric, feedback taxonomy
- Pipeline orchestrator: custom async DAG engine with per-step persistence
- Cost tracking: per-agent per-run with model-specific pricing
- Chatbot: intent-based operator interface

### Used from ecosystem
- **Anthropic SDK** (`anthropic`): Direct Claude API integration
- **FastAPI**: Web framework
- **SQLAlchemy 2.0**: Async ORM
- **python-docx**: DOCX generation
- **tenacity**: Retry with exponential backoff
- **structlog**: Structured logging
- **httpx**: Async HTTP client (fal.ai, web search)

## Security Rules Applied (PRD Section 47.3)
- All dependencies pinned to exact versions in `pyproject.toml`
- No blind install — all packages reviewed
- Agent code isolated from main server
- Input validation on all user-generated text passed to LLMs
