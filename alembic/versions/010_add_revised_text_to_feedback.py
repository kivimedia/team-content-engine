"""Add revised text columns to operator_feedback for copy-change feedback loop.

Revision ID: 010
Revises: 009
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operator_feedback",
        sa.Column("revised_facebook_post", sa.Text(), nullable=True),
    )
    op.add_column(
        "operator_feedback",
        sa.Column("revised_linkedin_post", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operator_feedback", "revised_linkedin_post")
    op.drop_column("operator_feedback", "revised_facebook_post")
