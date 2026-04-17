"""Add tracked_repos + repo_briefs tables and source_repo_id on post_packages.

Revision ID: 023
Revises: 022
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tracked_repos: GitHub repos the team wants to generate posts about
    op.create_table(
        "tracked_repos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("repo_url", sa.String(500), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("default_branch", sa.String(100), server_default="main"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("is_public", sa.Boolean, server_default=sa.true()),
        sa.Column("is_archived", sa.Boolean, server_default=sa.false()),
        sa.Column(
            "include_examples_in_posts",
            sa.Boolean,
            server_default=sa.true(),
            comment="When true, posts on matching topics cite this repo.",
        ),
        sa.Column(
            "blocked_topics",
            postgresql.ARRAY(sa.Text),
            nullable=True,
            comment="Topic substrings that should never trigger this repo as an example.",
        ),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column(
            "last_commit_sha",
            sa.String(40),
            nullable=True,
            comment="Last commit SHA observed on the default branch.",
        ),
        sa.Column("last_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "priority_score",
            sa.Float,
            server_default="0",
            comment="Higher = more likely to be picked for weekly spotlight.",
        ),
    )
    op.create_unique_constraint(
        "tracked_repos_workspace_slug_uq",
        "tracked_repos",
        ["workspace_id", "slug"],
    )
    op.create_index("ix_tracked_repos_slug", "tracked_repos", ["slug"])

    # repo_briefs: cached analyses per (repo, angle, commit_sha)
    op.create_table(
        "repo_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "tracked_repo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracked_repos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "angle",
            sa.String(30),
            nullable=False,
            comment="new_features | whole_repo | recent_fixes | generic",
        ),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("architecture_notes", sa.Text, nullable=True),
        sa.Column("readme_excerpt", sa.Text, nullable=True),
        sa.Column("recent_commits", postgresql.JSONB, nullable=True),
        sa.Column("feature_highlights", postgresql.JSONB, nullable=True),
        sa.Column("bug_fixes", postgresql.JSONB, nullable=True),
        sa.Column("code_snippets", postgresql.JSONB, nullable=True),
        sa.Column("package_hints", postgresql.JSONB, nullable=True),
        sa.Column("stats", postgresql.JSONB, nullable=True),
    )
    op.create_index(
        "ix_repo_briefs_repo_angle_sha",
        "repo_briefs",
        ["tracked_repo_id", "angle", "commit_sha"],
        unique=True,
    )

    # post_packages: link to originating tracked repo (optional)
    op.add_column(
        "post_packages",
        sa.Column(
            "source_repo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracked_repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "post_packages",
        sa.Column("source_repo_angle", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_packages", "source_repo_angle")
    op.drop_column("post_packages", "source_repo_id")
    op.drop_index("ix_repo_briefs_repo_angle_sha", table_name="repo_briefs")
    op.drop_table("repo_briefs")
    op.drop_index("ix_tracked_repos_slug", table_name="tracked_repos")
    op.drop_constraint(
        "tracked_repos_workspace_slug_uq", "tracked_repos", type_="unique"
    )
    op.drop_table("tracked_repos")
