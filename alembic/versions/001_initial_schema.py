"""Initial schema — all 17 tables.

Revision ID: 001
Revises:
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Independent tables (no FKs) ---

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="he"),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "creator_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("creator_name", sa.String(200), nullable=False),
        sa.Column("source_urls", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("style_notes", sa.Text(), nullable=True),
        sa.Column("allowed_influence_weight", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("disallowed_clone_markers", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("top_patterns", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("voice_axes", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "founder_voice_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_document_ids", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("vocabulary_signature", postgresql.JSONB(), nullable=True),
        sa.Column("sentence_rhythm_profile", postgresql.JSONB(), nullable=True),
        sa.Column("values_and_beliefs", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("metaphor_families", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("tone_range", postgresql.JSONB(), nullable=True),
        sa.Column("taboos", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("recurring_themes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("humor_type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pattern_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("template_family", sa.String(100), nullable=False),
        sa.Column("best_for", sa.Text(), nullable=True),
        sa.Column("hook_formula", sa.Text(), nullable=True),
        sa.Column("body_formula", sa.Text(), nullable=True),
        sa.Column("proof_requirements", sa.Text(), nullable=True),
        sa.Column("cta_compatibility", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("visual_compatibility", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("platform_fit", sa.String(50), nullable=True),
        sa.Column("tone_profile", postgresql.JSONB(), nullable=True),
        sa.Column("risk_notes", sa.Text(), nullable=True),
        sa.Column("anti_patterns", sa.Text(), nullable=True),
        sa.Column("example_ids", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("source_influence_weights", postgresql.JSONB(), nullable=True),
        sa.Column("median_score", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_avg", sa.Float(), nullable=True),
        sa.Column("creator_diversity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="provisional"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "research_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("question_set", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("verified_claims", postgresql.JSONB(), nullable=True),
        sa.Column("uncertain_claims", postgresql.JSONB(), nullable=True),
        sa.Column("rejected_claims", postgresql.JSONB(), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(), nullable=True),
        sa.Column("freshness_date", sa.String(50), nullable=True),
        sa.Column("thesis_candidates", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("risk_flags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("safe_to_publish", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "trend_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("brief_type", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("trends", postgresql.JSONB(), nullable=True),
        sa.Column("selected_trend_ids", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("rejected_trend_ids", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("operator_additions", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("breaking_overrides", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("model_target", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("ab_test_group", sa.String(50), nullable=True),
        sa.Column("performance_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "weekly_guides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("weekly_theme", sa.String(500), nullable=False),
        sa.Column("guide_title", sa.String(500), nullable=False),
        sa.Column("docx_path", sa.String(1000), nullable=True),
        sa.Column("pdf_path", sa.String(1000), nullable=True),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("cta_keyword", sa.String(100), nullable=True),
        sa.Column("dm_flow", postgresql.JSONB(), nullable=True),
        sa.Column("fulfillment_link", sa.String(1000), nullable=True),
        sa.Column("downloads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversion_rate", sa.Float(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cost_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("model_used", sa.String(200), nullable=False),
        sa.Column("model_version", sa.String(200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extended_thinking_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("wall_time_seconds", sa.Float(), nullable=True),
        sa.Column("batch_api_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("prompt_cache_hit_rate", sa.Float(), nullable=True),
        sa.Column("prompt_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- Tables with FK to pattern_templates ---

    op.create_table(
        "story_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("angle_type", sa.String(100), nullable=False),
        sa.Column("desired_belief_shift", sa.Text(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("house_voice_weights", postgresql.JSONB(), nullable=True),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("evidence_requirements", postgresql.JSONB(), nullable=True),
        sa.Column("cta_goal", sa.String(100), nullable=True),
        sa.Column("visual_job", sa.String(100), nullable=True),
        sa.Column("platform_notes", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["pattern_templates.id"]),
    )

    # --- Tables with FK to source_documents + creator_profiles ---

    op.create_table(
        "post_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("post_text_raw", sa.Text(), nullable=True),
        sa.Column("hook_text", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("cta_text", sa.Text(), nullable=True),
        sa.Column("hook_type", sa.String(100), nullable=True),
        sa.Column("body_structure", sa.String(100), nullable=True),
        sa.Column("story_arc", sa.String(100), nullable=True),
        sa.Column("tension_type", sa.String(100), nullable=True),
        sa.Column("cta_type", sa.String(100), nullable=True),
        sa.Column("visual_type", sa.String(100), nullable=True),
        sa.Column("visual_description", sa.Text(), nullable=True),
        sa.Column("proof_style", sa.String(100), nullable=True),
        sa.Column("tone_tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("topic_tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("audience_guess", sa.String(200), nullable=True),
        sa.Column("paragraph_count", sa.Integer(), nullable=True),
        sa.Column("uses_bullets", sa.Boolean(), nullable=True),
        sa.Column("has_explicit_keyword_cta", sa.Boolean(), nullable=True),
        sa.Column("visible_comments", sa.Integer(), nullable=True),
        sa.Column("visible_shares", sa.Integer(), nullable=True),
        sa.Column("engagement_confidence", sa.String(1), nullable=False, server_default="C"),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("evidence_image_ref", sa.String(500), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("manual_review_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("parser_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creator_profiles.id"]),
    )

    # --- Tables with FK to story_briefs + weekly_guides ---

    op.create_table(
        "post_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brief_id", sa.Uuid(), nullable=True),
        sa.Column("weekly_guide_id", sa.Uuid(), nullable=True),
        sa.Column("facebook_post", sa.Text(), nullable=True),
        sa.Column("linkedin_post", sa.Text(), nullable=True),
        sa.Column("hook_variants", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("cta_keyword", sa.String(100), nullable=True),
        sa.Column("secondary_cta_keyword", sa.String(100), nullable=True),
        sa.Column("dm_flow", postgresql.JSONB(), nullable=True),
        sa.Column("quality_scores", postgresql.JSONB(), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["brief_id"], ["story_briefs.id"]),
        sa.ForeignKeyConstraint(["weekly_guide_id"], ["weekly_guides.id"]),
    )
    op.create_index("ix_post_packages_approval_status", "post_packages", ["approval_status"])

    # --- Tables with FK to post_packages ---

    op.create_table(
        "image_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("fal_model_used", sa.String(200), nullable=True),
        sa.Column("fal_request_id", sa.String(200), nullable=True),
        sa.Column("image_url", sa.String(2000), nullable=True),
        sa.Column("image_s3_path", sa.String(1000), nullable=True),
        sa.Column("resolution", sa.String(20), nullable=True),
        sa.Column("aspect_ratio", sa.String(10), nullable=True),
        sa.Column("generation_cost_usd", sa.Float(), nullable=True),
        sa.Column("generation_time_seconds", sa.Float(), nullable=True),
        sa.Column("operator_selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["post_packages.id"]),
    )

    op.create_table(
        "qa_scorecards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("pass_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("model_justifications", postgresql.JSONB(), nullable=True),
        sa.Column("operator_overrides", postgresql.JSONB(), nullable=True),
        sa.Column("final_verdict", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("scored_by", sa.String(20), nullable=False, server_default="model"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["post_packages.id"]),
    )

    op.create_table(
        "operator_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("feedback_tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("feedback_notes", sa.Text(), nullable=True),
        sa.Column("action_taken", sa.String(20), nullable=False),
        sa.Column("revision_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["post_packages.id"]),
    )

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("actual_comments", sa.Integer(), nullable=True),
        sa.Column("actual_shares", sa.Integer(), nullable=True),
        sa.Column("actual_clicks", sa.Integer(), nullable=True),
        sa.Column("actual_dms", sa.Integer(), nullable=True),
        sa.Column("actual_saves", sa.Integer(), nullable=True),
        sa.Column("actual_follows", sa.Integer(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("postmortem_summary", sa.Text(), nullable=True),
        sa.Column("template_effectiveness_delta", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["post_packages.id"]),
    )

    # --- Content calendar (new in this phase) ---

    op.create_table(
        "content_calendar",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("angle_type", sa.String(100), nullable=False),
        sa.Column("topic", sa.String(500), nullable=True),
        sa.Column("post_package_id", sa.Uuid(), nullable=True),
        sa.Column("weekly_guide_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["post_package_id"], ["post_packages.id"]),
        sa.ForeignKeyConstraint(["weekly_guide_id"], ["weekly_guides.id"]),
    )
    op.create_index("ix_content_calendar_date", "content_calendar", ["date"])

    # --- Notifications ---

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("channel", sa.String(20), nullable=False, server_default="in_app"),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("content_calendar")
    op.drop_table("learning_events")
    op.drop_table("operator_feedback")
    op.drop_table("qa_scorecards")
    op.drop_table("image_assets")
    op.drop_table("post_packages")
    op.drop_table("post_examples")
    op.drop_table("story_briefs")
    op.drop_table("cost_events")
    op.drop_table("weekly_guides")
    op.drop_table("prompt_versions")
    op.drop_table("trend_briefs")
    op.drop_table("research_briefs")
    op.drop_table("pattern_templates")
    op.drop_table("founder_voice_profiles")
    op.drop_table("creator_profiles")
    op.drop_table("source_documents")
