"""Tests for system versioning (PRD Section 16.3)."""

from tce.models.system_version import SystemVersion


def test_model_exists():
    assert SystemVersion is not None


def test_model_has_version_fields():
    """PRD Section 16.3: 4 version fields required."""
    fields = [
        "corpus_version",
        "template_library_version",
        "house_voice_version",
        "scoring_config_version",
    ]
    for field in fields:
        assert hasattr(SystemVersion, field), f"Missing: {field}"


def test_model_has_change_tracking():
    assert hasattr(SystemVersion, "change_type")
    assert hasattr(SystemVersion, "change_description")
    assert hasattr(SystemVersion, "changed_by")
    assert hasattr(SystemVersion, "config_snapshot")
