"""Encrypt existing idea and script text after widening title storage.

Revision ID: s007
Revises: s006
"""

import sqlalchemy as sa

from alembic import op
from tce.standalone.crypto import decrypt_text, encrypt_text

revision = "s007"
down_revision = "s006"
branch_labels = None
depends_on = None

FIELDS = {
    "standalone_ideas": ("title", "angle", "why_now", "evidence", "notes"),
    "standalone_script_versions": ("script", "note"),
}


def upgrade() -> None:
    with op.batch_alter_table("standalone_ideas") as batch:
        batch.alter_column(
            "title", existing_type=sa.String(250), type_=sa.Text(), existing_nullable=False
        )
    connection = op.get_bind()
    for table, columns in FIELDS.items():
        for column in columns:
            purpose = ("idea" if table == "standalone_ideas" else "script") + "." + column
            rows = connection.execute(sa.text(f"SELECT id, {column} FROM {table}")).all()
            for row in rows:
                value = encrypt_text(row[1], purpose)
                connection.execute(sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                   {"value": value, "id": row[0]})


def downgrade() -> None:
    connection = op.get_bind()
    for table, columns in FIELDS.items():
        for column in columns:
            purpose = ("idea" if table == "standalone_ideas" else "script") + "." + column
            rows = connection.execute(sa.text(f"SELECT id, {column} FROM {table}")).all()
            for row in rows:
                connection.execute(sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                   {"value": decrypt_text(row[1], purpose), "id": row[0]})
    with op.batch_alter_table("standalone_ideas") as batch:
        batch.alter_column(
            "title", existing_type=sa.Text(), type_=sa.String(250), existing_nullable=False
        )
