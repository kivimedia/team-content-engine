"""Migration 045 and the ORM must describe the same tables.

This drift happened TWICE while the news lane was built: 045 added columns to
evidence_moments, topic_candidates and recording_packets, and the models were not
updated. Nothing failed, because SQLAlchemy ignores columns it does not know and
the migration was never applied here - so the first sign would have been a
production database silently disagreeing with the code. This test reads the
migration itself, so the next column added there cannot be forgotten here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import tce.models  # noqa: F401 - registers every table on Base.metadata
from tce.db.base import Base

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "045_news_lane.py"
)


def _declared() -> dict[str, set[str]]:
    """{table: {column}} for everything 045's upgrade() creates or adds."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    upgrade = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
    )
    out: dict[str, set[str]] = {}
    for call in ast.walk(upgrade):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        name = call.func.attr
        if name == "create_table" and call.args:
            table = call.args[0].value
            for arg in call.args[1:]:
                if (
                    isinstance(arg, ast.Call)
                    and getattr(arg.func, "attr", "") == "Column"
                    and arg.args
                    and isinstance(arg.args[0], ast.Constant)
                ):
                    out.setdefault(table, set()).add(arg.args[0].value)
        elif name == "add_column" and len(call.args) >= 2:
            table = call.args[0].value
            col = call.args[1]
            if isinstance(col, ast.Call) and col.args and isinstance(col.args[0], ast.Constant):
                out.setdefault(table, set()).add(col.args[0].value)
    return out


def test_the_migration_was_actually_parsed():
    declared = _declared()
    assert "news_items" in declared and "news_anchors" in declared
    assert {"news_ref"} <= declared["evidence_moments"]
    assert {"news_item_id", "expires_at"} <= declared["topic_candidates"]
    assert {"news_block", "format"} <= declared["recording_packets"]


def test_every_column_the_migration_adds_exists_on_the_model():
    missing = []
    for table, columns in sorted(_declared().items()):
        model_table = Base.metadata.tables.get(table)
        if model_table is None:
            missing.append(f"{table} (whole table)")
            continue
        for column in sorted(columns - set(model_table.c.keys())):
            missing.append(f"{table}.{column}")
    assert not missing, (
        "migration 045 adds columns the models do not know about - the database "
        "and the code would silently disagree:\n  " + "\n  ".join(missing)
    )
