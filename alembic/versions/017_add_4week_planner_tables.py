"""Add 4-week planner tables: slot_options, monthly_plans, post_stack, guide_options + element_feedback column.

Revision ID: 017
Revises: 016
Create Date: 2026-04-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Phase 1: slot_options ---
    op.create_table(
        "slot_options",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("calendar_entry_id", UUID(as_uuid=True), sa.ForeignKey("content_calendar.id"), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("angle_type", sa.String(100), nullable=False),
        sa.Column("plan_context", JSONB(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("post_package_id", UUID(as_uuid=True), sa.ForeignKey("post_packages.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_slot_options_calendar_entry_id", "slot_options", ["calendar_entry_id"])

    # --- Phase 2: monthly_plans ---
    op.create_table(
        "monthly_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), server_default="draft", nullable=False),
        sa.Column("plan_data", JSONB(), nullable=True),
        sa.Column("weekly_plan_ids", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_monthly_plans_month_start", "monthly_plans", ["month_start"])

    # --- Phase 3: element_feedback column on post_packages ---
    op.add_column(
        "post_packages",
        sa.Column("element_feedback", JSONB(), nullable=True),
    )

    # --- Phase 4: post_stack ---
    op.create_table(
        "post_stack",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("post_package_id", UUID(as_uuid=True), sa.ForeignKey("post_packages.id"), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- Phase 4: guide_options ---
    op.create_table(
        "guide_options",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("weekly_plan_id", UUID(as_uuid=True), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("subtitle", sa.String(500), nullable=True),
        sa.Column("sections", JSONB(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("weekly_guide_id", UUID(as_uuid=True), sa.ForeignKey("weekly_guides.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_guide_options_weekly_plan_id", "guide_options", ["weekly_plan_id"])


def downgrade() -> None:
    op.drop_table("guide_options")
    op.drop_table("post_stack")
    op.drop_column("post_packages", "element_feedback")
    op.drop_table("monthly_plans")
    op.drop_table("slot_options")
