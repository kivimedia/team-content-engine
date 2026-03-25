"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tce.api.routers import (
    admin,
    briefs,
    calendar,
    chat,
    content,
    costs,
    documents,
    feedback,
    health,
    patterns,
    pipeline,
    profiles,
    prompts,
    qa,
    trends,
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

    return app


app = create_app()
