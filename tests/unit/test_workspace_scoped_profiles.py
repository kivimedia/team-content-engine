"""The newest-profile picks never cross into a client workspace.

Workspaces are a workspace_id column. The global SELECT filter only runs when a
workspace context is set, so a pick of "the newest FounderVoiceProfile" made with
no context (owner runs, crons, legacy paths) used to return whichever workspace
wrote last - a client's voice in the owner's scripts once a second client exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from tce.db.base import Base
from tce.db.workspace_filter import set_workspace_context
from tce.models.brand_profile import BrandProfile
from tce.models.creator_profile import CreatorProfile
from tce.models.founder_voice_profile import FounderVoiceProfile
from tce.services.cache_prefix import CachePrefixBuilder
from tce.settings import settings


@compiles(ARRAY, "sqlite")
def _array_sqlite(_type, _compiler, **_kw):  # pragma: no cover - DDL only
    return "TEXT"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - DDL only
    return "TEXT"


OWNER_WS = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")
CLIENT_WS = uuid.uuid4()
T0 = datetime(2026, 10, 1, 12, 0, 0)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Base.metadata.tables[n]
        for n in ("creator_profiles", "pattern_templates", "founder_voice_profiles",
                  "brand_profiles")
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    set_workspace_context(None)
    await engine.dispose()


async def _seed_voices(db: AsyncSession) -> tuple[FounderVoiceProfile, FounderVoiceProfile]:
    owner = FounderVoiceProfile(workspace_id=OWNER_WS, humor_type="owner", created_at=T0)
    client = FounderVoiceProfile(
        workspace_id=CLIENT_WS, humor_type="client", created_at=T0 + timedelta(days=1)
    )
    db.add_all([owner, client])
    await db.commit()
    return owner, client


async def test_unscoped_voice_pick_never_returns_a_client_workspace_row(db):
    await _seed_voices(db)
    set_workspace_context(None)
    builder = CachePrefixBuilder(db)
    await builder._load()
    assert builder._voice is not None
    assert builder._voice.humor_type == "owner"


async def test_scoped_voice_pick_returns_that_workspace_row(db):
    await _seed_voices(db)
    set_workspace_context(CLIENT_WS)
    builder = CachePrefixBuilder(db)
    await builder._load()
    assert builder._voice is not None
    assert builder._voice.humor_type == "client"


async def test_scoped_pick_prefers_workspace_row_over_newer_global_row(db):
    from tce.db.workspace_filter import scoped_pick

    db.add_all([
        FounderVoiceProfile(workspace_id=CLIENT_WS, humor_type="client", created_at=T0),
        FounderVoiceProfile(
            workspace_id=None, humor_type="global", created_at=T0 + timedelta(days=2)
        ),
    ])
    await db.commit()
    set_workspace_context(CLIENT_WS)
    fv = (await db.execute(scoped_pick(FounderVoiceProfile))).scalars().first()
    assert fv.humor_type == "client"


async def test_scoped_pick_falls_back_to_global_row(db):
    from tce.db.workspace_filter import scoped_pick

    db.add(FounderVoiceProfile(workspace_id=None, humor_type="global", created_at=T0))
    await db.commit()
    set_workspace_context(CLIENT_WS)
    fv = (await db.execute(scoped_pick(FounderVoiceProfile))).scalars().first()
    assert fv.humor_type == "global"


async def test_unscoped_name_lookup_skips_client_creator_with_same_name(db):
    from tce.db.workspace_filter import scoped_pick

    db.add_all([
        CreatorProfile(workspace_id=None, creator_name="Ben", created_at=T0),
        CreatorProfile(
            workspace_id=CLIENT_WS, creator_name="Ben", created_at=T0 + timedelta(days=1)
        ),
    ])
    await db.commit()
    set_workspace_context(None)
    stmt = scoped_pick(CreatorProfile, CreatorProfile.creator_name == "Ben")
    rows = (await db.execute(stmt)).scalars().all()
    assert len(rows) == 1 and rows[0].workspace_id is None


async def test_unscoped_brand_pick_skips_client_brand(db):
    from tce.db.workspace_filter import scoped_pick

    db.add_all([
        BrandProfile(workspace_id=OWNER_WS, name="owner", created_at=T0),
        BrandProfile(workspace_id=CLIENT_WS, name="client", created_at=T0 + timedelta(days=1)),
    ])
    await db.commit()
    set_workspace_context(None)
    brand = (await db.execute(scoped_pick(BrandProfile))).scalars().first()
    assert brand.name == "owner"


def test_owner_workspace_ids_default_and_override(monkeypatch):
    from tce.db.workspace_filter import owner_workspace_ids

    ed = str(uuid.uuid4())
    monkeypatch.setattr(settings, "editor_default_workspace_id", ed)
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    assert owner_workspace_ids() == {uuid.UUID(ed), OWNER_WS}
    other = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", f" {other} , not-a-uuid ")
    assert owner_workspace_ids() == {other}
