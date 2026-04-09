# TCE-KMBoards Integration Gaps

Tracks remaining work for the Team Content Engine integration with KMBoards.
Status: DONE = implemented, FUTURE = planned but not blocking.

## DONE - Critical Infrastructure

### Gap 5: Workspace-Scoped Read Queries
**Status: DONE** (2026-04-09)
- SQLAlchemy `do_orm_execute` event listener auto-filters all SELECTs by workspace_id
- Installed in `src/tce/db/workspace_filter.py`, activated in `src/tce/db/session.py`
- Global tables exempted: cost_events, system_versions, prompt_versions, audit_logs, notifications
- Middleware in `src/tce/api/app.py` extracts X-Workspace-Id header and sets context per request
- 69 queries across 13 routers - all filtered automatically, zero individual changes

### Gap 7: Per-Client API Key Passthrough
**Status: DONE** (2026-04-09)
- `worker-tce.ts` reads client API keys from `tce_client_configs`
- Sends `api_keys` and `budget` overrides in the `run-for-workspace` request body
- TCE `run-for-workspace` endpoint shallow-copies Settings and applies overrides
- NULL keys = use agency defaults (no change for existing behavior)

### Gap 9: Cost Attribution Back to Supabase
**Status: DONE** (2026-04-09)
- `worker-tce.ts` fetches `/api/v1/costs/by-agent?run_id=X` after pipeline completion
- Writes `total_cost_usd` to `agent_team_runs` in Supabase
- Included in `markJobComplete` result payload

### Gap 6: Corpus Upload Proxy
**Status: DONE** (2026-04-09)
- `POST /api/clients/[clientId]/tce/upload` proxies file uploads to TCE's `/api/v1/documents/upload`
- Automatically sets X-Workspace-Id header from client's tce_client_configs
- Used by Brand Voice Lab for DOCX swipe file ingestion

### Gap 8: Gate Support in TCE Pipelines
**Status: DONE** (2026-04-09)
- `PipelineStep.is_gate` field added
- `PipelineOrchestrator` detects gate steps and sets `StepStatus.PAUSED_AT_GATE`
- `get_status()` returns `paused: true` and `paused_at_gate: step_name`
- `worker-tce.ts` detects paused state, calls `markJobPaused`, updates agent_team_runs status
- Content Planner template has a gate after weekly planning for plan review

## DONE - UI Integration

### Gap 11: TeamsPanel Dashboard URL Mapping
**Status: DONE** (2026-04-09)
- All 5 tce-* templates mapped to `/tce` in `TEMPLATE_DASHBOARD_URLS`

### Gap 1: TCE in Dashboard Registries
**Status: DONE** (2026-04-09)
- `INTERNAL_DASHBOARD_REGISTRY`: added `tce-content` with pathPrefixes and apiPathPrefixes
- `DASHBOARD_PORTAL_LINKS`: added Content Engine card
- `AGENT_DASHBOARD_CARDS`: added tce-content card for Guardian audit

### Gap 2: TCE Run Input Forms
**Status: DONE** (2026-04-09)
- TeamsPanel detects `tce-*` templates and renders specific input forms:
  - Content Engine / Planner / Performance Lab: topic/niche text input (optional - auto-discovered)
  - Polish Studio: large textarea for pasting draft copy
  - Brand Voice Lab: info banner pointing to file upload via client settings
- Client selector required for all TCE templates (needsClient = true)

### Gap 3+4: TCE Dashboard Page + Embedding
**Status: DONE** (2026-04-09)
- `/tce` page created at `src/app/tce/page.tsx`
- Embeds TCE's dashboard via iframe with optional workspace_id query param
- Accepts `?workspace_id=UUID` for per-client scoping

## FUTURE - Optimizations

### Gap 10: Webhook Callback from TCE
**Status: FUTURE**
- Currently km-worker polls TCE every 5s for status updates
- Could add `POST /tce-callback` to poke server and `callback_url` param to TCE's run-for-workspace
- TCE would POST completion/failure back instead of waiting for poll
- Not blocking - polling works fine for current scale

### Gap 3b: Native Content Viewer
**Status: FUTURE**
- Currently content is viewed via TCE's embedded iframe dashboard
- Could build native kmboards components to display FB/LI posts, approve, schedule
- Would fetch from TCE API: `GET /api/v1/content/packages?workspace_id=X`
- Nice-to-have for a more integrated experience

### Gap 12: Client Feature Toggle
**Status: FUTURE**
- Could add `tce_enabled` to `CLIENT_FEATURES` in `src/lib/client-features.ts`
- Would auto-render in ClientFeaturePermissions component
- Currently TCE is enabled by creating a `tce_client_configs` row via API
