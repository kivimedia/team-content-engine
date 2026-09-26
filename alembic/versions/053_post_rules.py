"""His post rules: how every post TCE writes must read.

26-Sep: "I dont see TJ use CTAs on the posts. I want to build an audience without
asking anyone for anything." Nullable text on editorial_settings; empty means the
default rule (no call to action). Additive only.

Revision ID: 053
Revises: 052
Create Date: 2026-09-26
"""

import sqlalchemy as sa

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("editorial_settings", sa.Column("post_rules", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("editorial_settings", "post_rules")
