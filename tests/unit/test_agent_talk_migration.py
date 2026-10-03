"""Migration 057 applies on the database the suite uses, and ends where the models are.

The suite builds its tables from the models (tests/editorial_db.py), so a migration that
disagrees with them would never fail on its own. This builds the tables as they were
before 057, runs 057's upgrade and downgrade through alembic on SQLite, and reads the
result back. Nothing here touches a server database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

import tce.models  # noqa: F401 - registers every table on Base.metadata
from tce.db.base import Base
from tests.editorial_db import TABLE_NAMES

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MIGRATION = VERSIONS / "057_agent_talks.py"

NEW_COLUMNS = {"recording_uploads": {"source", "agent_name", "call_transcript"}}
NEW_TABLE = "agent_talks"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_057", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _before_057() -> sa.MetaData:
    """The suite's tables without what 057 adds."""
    md = sa.MetaData()
    for name in TABLE_NAMES:
        if name == NEW_TABLE:
            continue
        table = Base.metadata.tables[name]
        dropped = NEW_COLUMNS.get(name, set())
        links = [
            sa.ForeignKeyConstraint(
                [c.name for c in fk.columns],
                [e.target_fullname for e in fk.elements],
                ondelete=fk.ondelete,
                name=fk.name,
            )
            for fk in table.foreign_key_constraints
            if not {c.name for c in fk.columns} & dropped
        ]
        sa.Table(name, md, *[c._copy() for c in table.columns if c.name not in dropped], *links)
    return md


def _run(sync_conn, step: str) -> None:
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        getattr(_migration(), step)()


def _shape(sync_conn) -> dict:
    insp = sa.inspect(sync_conn)
    tables = set(insp.get_table_names())
    out: dict = {"tables": tables}
    for name in ("recording_uploads", NEW_TABLE):
        if name in tables:
            out[name] = {c["name"] for c in insp.get_columns(name)}
            out[name + ".fks"] = {
                (tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in insp.get_foreign_keys(name)
            }
            out[name + ".unique"] = {
                tuple(u["column_names"]) for u in insp.get_unique_constraints(name)
            }
    return out


def test_057_follows_056_and_is_the_only_head():
    module = _migration()
    assert module.revision == "057" and module.down_revision == "056"
    # No other migration claims 056 as its parent: one line of history, one head.
    parents = []
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if 'down_revision = "056"' in text:
            parents.append(path.name)
    assert parents == ["057_agent_talks.py"]


async def test_057_applies_on_the_suites_database_and_matches_the_models():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: _before_057().create_all(c))
            before = await conn.run_sync(_shape)
            assert NEW_TABLE not in before["tables"]
            assert not NEW_COLUMNS["recording_uploads"] & before["recording_uploads"]

            await conn.run_sync(lambda c: _run(c, "upgrade"))
            after = await conn.run_sync(_shape)
            for name in ("recording_uploads", NEW_TABLE):
                assert after[name] == set(Base.metadata.tables[name].c.keys()), name
            assert (("upload_id",), "recording_uploads") in after[NEW_TABLE + ".fks"]
            # A create sent twice is the same talk: the identity is unique.
            assert ("workspace_id", "agent", "call_id", "started_at") in after[NEW_TABLE + ".unique"]

            await conn.run_sync(lambda c: _run(c, "downgrade"))
            undone = await conn.run_sync(_shape)
            assert undone["tables"] == before["tables"]
            assert undone["recording_uploads"] == before["recording_uploads"]

            await conn.run_sync(lambda c: _run(c, "upgrade"))  # and forward again
            again = await conn.run_sync(_shape)
            assert again[NEW_TABLE] == set(Base.metadata.tables[NEW_TABLE].c.keys())
    finally:
        await engine.dispose()


def test_the_suite_builds_the_agent_talk_table():
    assert NEW_TABLE in TABLE_NAMES


def test_on_postgres_057_is_additive_sql():
    """The server's SQL, written out offline: three nullable columns and one new table,
    nothing dropped or rewritten on the way up."""
    import io

    buf = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buf})
    with Operations.context(ctx):
        _migration().upgrade()
    sql = " ".join(buf.getvalue().split())
    assert "ALTER TABLE recording_uploads ADD COLUMN source VARCHAR(30)" in sql
    assert "ALTER TABLE recording_uploads ADD COLUMN agent_name VARCHAR(80)" in sql
    assert "ALTER TABLE recording_uploads ADD COLUMN call_transcript JSONB" in sql
    assert "CREATE TABLE agent_talks" in sql
    assert "DROP" not in sql.upper().replace("ON DELETE SET NULL", "")
