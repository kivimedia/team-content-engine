"""Migration 056 applies on the database the suite uses, and ends where the models are.

The suite builds its tables from the models (tests/editorial_db.py), so a migration
that disagrees with them would never fail here on its own. This builds the tables as
they were before 056, runs 056's upgrade and downgrade through alembic on SQLite, and
reads the result back.
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

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "056_talk_sessions.py"

# What 056 adds, and nothing else.
NEW_COLUMNS = {
    "recording_uploads": {"render_ref", "rendered_keep"},
    "editing_requests": {"session_id", "source_s", "understood"},
}
NEW_TABLE = "edit_sessions"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_056", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _before_056() -> sa.MetaData:
    """The suite's tables without what 056 adds."""
    md = sa.MetaData()
    for name in TABLE_NAMES:
        if name == NEW_TABLE:
            continue
        table = Base.metadata.tables[name]
        dropped = NEW_COLUMNS.get(name, set())
        # A copied column leaves its foreign key behind; the constraints come across apart.
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
    out = {"tables": tables}
    for name in ("recording_uploads", "editing_requests", NEW_TABLE):
        if name in tables:
            out[name] = {c["name"] for c in insp.get_columns(name)}
            out[name + ".fks"] = {
                (tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in insp.get_foreign_keys(name)
            }
            out[name + ".unique"] = {
                (ix["name"], tuple(ix["column_names"])) for ix in insp.get_indexes(name) if ix.get("unique")
            }
    return out


def _model_columns(name: str) -> set[str]:
    return set(Base.metadata.tables[name].c.keys())


async def test_056_applies_on_the_suites_database_and_matches_the_models():
    assert MIGRATION.exists()
    module = _migration()
    assert module.revision == "056" and module.down_revision == "055"

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: _before_056().create_all(c))
            before = await conn.run_sync(_shape)
            assert NEW_TABLE not in before["tables"]
            assert not NEW_COLUMNS["editing_requests"] & before["editing_requests"]
            assert (("upload_id",), "recording_uploads") in before["editing_requests.fks"]

            await conn.run_sync(lambda c: _run(c, "upgrade"))
            after = await conn.run_sync(_shape)
            for name in ("recording_uploads", "editing_requests", NEW_TABLE):
                assert after[name] == _model_columns(name), name
            assert (("session_id",), NEW_TABLE) in after["editing_requests.fks"]
            assert (("upload_id",), "recording_uploads") in after[NEW_TABLE + ".fks"]
            # One live sitting per video: two opens at once cannot both insert one.
            assert after[NEW_TABLE + ".unique"] == {("uq_edit_sessions_live_upload", ("upload_id",))}
            # The recreate kept the note's older links.
            assert (("upload_id",), "recording_uploads") in after["editing_requests.fks"]

            await conn.run_sync(lambda c: _run(c, "downgrade"))
            undone = await conn.run_sync(_shape)
            assert undone["tables"] == before["tables"]
            assert undone["editing_requests"] == before["editing_requests"]
            assert undone["editing_requests.fks"] == before["editing_requests.fks"]
            assert undone["recording_uploads"] == before["recording_uploads"]

            await conn.run_sync(lambda c: _run(c, "upgrade"))  # and forward again
            again = await conn.run_sync(_shape)
            assert again["editing_requests"] == _model_columns("editing_requests")
    finally:
        await engine.dispose()


def test_the_suite_builds_the_sitting_table():
    assert NEW_TABLE in TABLE_NAMES


LIVE_ONLY = "WHERE state IN ('open', 'thinking', 'rendering')"


def test_on_postgres_the_one_live_sitting_rule_covers_live_sittings_only():
    """The server's SQL, written out: a unique index on the video, for live sittings only
    (finished sittings of the same video are many)."""
    import io

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex

    buf = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buf})
    with Operations.context(ctx):
        _migration().upgrade()
    sql = " ".join(buf.getvalue().split())
    assert f"CREATE UNIQUE INDEX uq_edit_sessions_live_upload ON edit_sessions (upload_id) {LIVE_ONLY}" in sql

    index = next(i for i in Base.metadata.tables[NEW_TABLE].indexes if i.name == "uq_edit_sessions_live_upload")
    model_sql = " ".join(str(CreateIndex(index).compile(dialect=postgresql.dialect())).split())
    assert model_sql.startswith("CREATE UNIQUE INDEX") and model_sql.endswith(LIVE_ONLY)
