"""FeatureFlag - DB table created by migration 005. Queried via raw SQL in FeatureFlagService.

Schema: key TEXT PRIMARY KEY, enabled BOOLEAN DEFAULT false, updated_at TIMESTAMPTZ
Managed by: src/tce/services/feature_flags.py

This table intentionally uses a TEXT primary key instead of UUID because flags
are looked up by name, not by generated ID. The Base class UUID primary key is
not used here - the table is created directly by Alembic migration 005.
"""
