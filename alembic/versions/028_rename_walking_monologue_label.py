"""Rename format_label 'walking_monologue' -> 'short_form_talking' on
post_examples. Most of the TJ corpus is talking-head (standing/sitting),
not walking. Neutral label is more honest and lets other creators in the
same format family (short-form phone-held single-take) share it without
falsely implying walking delivery.

Revision ID: 028
Revises: 027
Create Date: 2026-04-17
"""

from alembic import op


revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE post_examples SET format_label = 'short_form_talking' "
        "WHERE format_label = 'walking_monologue'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE post_examples SET format_label = 'walking_monologue' "
        "WHERE format_label = 'short_form_talking'"
    )
