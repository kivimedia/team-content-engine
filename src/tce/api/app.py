"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
    repos,
    stack,
    trends,
    uploads,
    video_scripts,
    videos,
    workspace_context,
)
from tce.api.routers import (
    scheduler as scheduler_router,
)
from tce.db.session import async_session
from tce.services.seed import seed_database
from tce.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed database and start background scheduler on startup."""
    try:
        async with async_session() as db:
            await seed_database(db)
            await db.commit()
    except Exception:
        pass  # DB may not be available yet (e.g., during tests)

    # Auto-start the scheduler so recurring workflows (daily_content,
    # weekly_planning, daily_backup, etc.) fire without manual intervention.
    # Tests skip this via the TCE_DISABLE_SCHEDULER env var.
    import os

    if os.environ.get("TCE_DISABLE_SCHEDULER") != "1":
        try:
            from tce.services.scheduler import scheduler

            scheduler.start()
        except Exception:
            # Scheduler failure must never block the API from booting.
            pass

    yield

    # Stop the scheduler on shutdown so tests/restarts don't leave
    # orphaned background tasks.
    try:
        from tce.services.scheduler import scheduler

        scheduler.stop()
    except Exception:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    from tce.api.deps import get_workspace_id

    app = FastAPI(
        title="Team Content Engine",
        description=(
            "Agentic content engine that learns from a swipe corpus "
            "and produces daily social media packages"
        ),
        dependencies=[Depends(get_workspace_id)],
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS (must be added before other middleware so it wraps outermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Workspace context is set via the get_workspace_id() FastAPI dependency
    # in deps.py, NOT via middleware. Starlette's BaseHTTPMiddleware (which
    # @app.middleware("http") also uses internally) breaks ContextVar propagation
    # because it runs route handlers in a separate task. Dependencies run in
    # the same task as the route handler, so ContextVars work correctly.

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
    app.include_router(repos.router, prefix=prefix)
    app.include_router(videos.router, prefix=prefix)
    app.include_router(video_scripts.router, prefix=prefix)
    app.include_router(narration.router, prefix=prefix)
    app.include_router(monthly.router, prefix=prefix)
    app.include_router(stack.router, prefix=prefix)
    app.include_router(workspace_context.router, prefix=prefix)
    app.include_router(uploads.router, prefix=prefix)

    # Dashboard - no API prefix, served at root /dashboard
    app.include_router(dashboard.router)

    # Static file serving for rendered videos and audio
    media_dir = Path(settings.video_output_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()
