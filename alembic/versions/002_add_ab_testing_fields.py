"""Add A/B testing fields to post_packages.

Revision ID: 002
Revises: 001
Create Date: 2026-03-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "post_packages",
        sa.Column("experiment_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "post_packages",
        sa.Column("variant", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_packages", "variant")
    op.drop_column("post_packages", "experiment_id")
