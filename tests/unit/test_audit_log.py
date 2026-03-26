"""Tests for audit log model (PRD Section 25)."""

from tce.models.audit_log import AuditLog


def test_model_exists():
    assert AuditLog is not None


def test_model_tracks_who():
    assert hasattr(AuditLog, "actor")
    assert hasattr(AuditLog, "actor_type")


def test_model_tracks_what():
    assert hasattr(AuditLog, "action")
    assert hasattr(AuditLog, "resource_type")
    assert hasattr(AuditLog, "resource_id")


def test_model_tracks_details():
    assert hasattr(AuditLog, "description")
    assert hasattr(AuditLog, "before_state")
    assert hasattr(AuditLog, "after_state")
