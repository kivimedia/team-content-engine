"""Per-workspace context overrides (strategy, portfolio, trend focus).

Three small tables that let a tenant supply their own planner context
instead of inheriting the global files (docs/super-coaching-strategy.md,
docs/repo-portfolio.md, hardcoded trend_scout queries).

Loaders fall back to global when no row exists for the workspace, so
existing single-tenant behavior is preserved.

Revision ID: 033
Revises: 032
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_strategies_workspace_id"),
    )

    op.create_table(
        "workspace_portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_portfolios_workspace_id"),
    )

    op.create_table(
        "workspace_trend_focus",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("queries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_trend_focus_workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_trend_focus")
    op.drop_table("workspace_portfolios")
    op.drop_table("workspace_strategies")
