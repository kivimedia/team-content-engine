"""FastAPI application factory."""

import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from tce.db.workspace_filter import set_workspace_context
from tce.settings import settings

from tce.api import dashboard
from tce.api.routers import (
    admin,
    briefs,
    calendar,
    chat,
    content,
    costs,
    dm_fulfillment,
    documents,
    experiments,
    feedback,
    health,
    monthly,
    narration,
    notifications,
    onboarding,
    operator_controls,
    patterns,
    pipeline,
    profiles,
    prompts,
    qa,
    relearning,
    stack,
    trends,
    videos,
)
from tce.api.routers import (
    scheduler as scheduler_router,
)
from tce.db.session import async_session
from tce.services.seed import seed_database
from tce.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed database with defaults on startup."""
    try:
        async with async_session() as db:
            await seed_database(db)
            await db.commit()
    except Exception:
        pass  # DB may not be available yet (e.g., during tests)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title="Team Content Engine",
        description=(
            "Agentic content engine that learns from a swipe corpus "
            "and produces daily social media packages"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Workspace context middleware - extracts X-Workspace-Id header
    # and sets it for automatic query filtering
    class WorkspaceMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            ws_header = request.headers.get("x-workspace-id")
            if ws_header:
                try:
                    set_workspace_context(uuid.UUID(ws_header))
                except ValueError:
                    pass
            else:
                set_workspace_context(None)
            response = await call_next(request)
            return response

    app.add_middleware(WorkspaceMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(profiles.router, prefix=prefix)
    app.include_router(patterns.router, prefix=prefix)
    app.include_router(briefs.router, prefix=prefix)
    app.include_router(content.router, prefix=prefix)
    app.include_router(qa.router, prefix=prefix)
    app.include_router(pipeline.router, prefix=prefix)
    app.include_router(costs.router, prefix=prefix)
    app.include_router(prompts.router, prefix=prefix)
    app.include_router(feedback.router, prefix=prefix)
    app.include_router(trends.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(calendar.router, prefix=prefix)
    app.include_router(scheduler_router.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(experiments.router, prefix=prefix)
    app.include_router(onboarding.router, prefix=prefix)
    app.include_router(operator_controls.router, prefix=prefix)
    app.include_router(dm_fulfillment.router, prefix=prefix)
    app.include_router(relearning.router, prefix=prefix)
    app.include_router(videos.router, prefix=prefix)
    app.include_router(narration.router, prefix=prefix)
    app.include_router(monthly.router, prefix=prefix)
    app.include_router(stack.router, prefix=prefix)

    # Dashboard - no API prefix, served at root /dashboard
    app.include_router(dashboard.router)

    # Static file serving for rendered videos and audio
    media_dir = Path(settings.video_output_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()
