"""Widen image_assets.image_url from varchar(2000) to text.

OpenAI's gpt-image-2 returns base64 by default. Without S3 configured we
embed the b64 directly as a data: URL, which can be 2-3 MB. The old
varchar(2000) limit caused StringDataRightTruncationError on insert and
silently lost every OpenAI-generated image.

Revision ID: 035
Revises: 034
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "image_assets",
        "image_url",
        existing_type=sa.String(length=2000),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "image_assets",
        "image_url",
        existing_type=sa.Text(),
        type_=sa.String(length=2000),
        existing_nullable=True,
    )
