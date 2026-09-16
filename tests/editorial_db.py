"""Shared in-memory SQLite database for evidence/editorial/LLM-job tests.

Registered for every test via `pytest_plugins` in tests/conftest.py:

    async def test_x(editorial_session):
        editorial_session.add(...)
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tce.db.base import Base
from tce.models import editorial, llm_job  # noqa: F401

TABLE_NAMES = (
    "llm_jobs",
    "evidence_sources",
    "evidence_collection_runs",
    "evidence_moments",
    "topic_candidates",
    "editorial_feedback",
    "recording_packets",
    "recording_uploads",
    "publication_receipts",
)


def make_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


async def create_tables(engine) -> None:
    tables = [Base.metadata.tables[n] for n in TABLE_NAMES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))


@pytest.fixture
async def editorial_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine()
    await create_tables(engine)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def editorial_session(
    editorial_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with editorial_sessionmaker() as session:
        yield session
