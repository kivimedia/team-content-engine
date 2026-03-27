"""Tests for operator onboarding (PRD Section 43.6)."""

from tce.services.onboarding import (
    GLOSSARY,
    QUICKSTART_STEPS,
    ROLE_DOCUMENTATION,
    TROUBLESHOOTING,
    OnboardingService,
)


def test_quickstart_seven_steps():
    """PRD Section 43.6: step-by-step walkthrough."""
    assert len(QUICKSTART_STEPS) == 7


def test_quickstart_has_endpoints():
    """Each step should reference an API endpoint."""
    for step in QUICKSTART_STEPS:
        assert "endpoint" in step
        ep = step["endpoint"]
        assert ep.startswith("/") or ep.startswith("POST") or ep.startswith("GET")


def test_glossary_key_terms():
    """PRD Section 43.6: concept glossary."""
    expected_terms = [
        "house_voice",
        "founder_voice",
        "influence_weights",
        "template_families",
        "confidence_tags",
        "qa_scorecard",
        "cta_keyword",
        "weekly_guide",
    ]
    for term in expected_terms:
        assert term in GLOSSARY, f"Missing glossary term: {term}"


def test_troubleshooting_issues():
    """At least 4 common issues documented."""
    assert len(TROUBLESHOOTING) >= 4


def test_role_documentation():
    """Operator vs system responsibilities defined."""
    assert "operator_responsibilities" in ROLE_DOCUMENTATION
    assert "system_handles_automatically" in ROLE_DOCUMENTATION
    assert len(ROLE_DOCUMENTATION["operator_responsibilities"]) >= 5
    assert len(ROLE_DOCUMENTATION["system_handles_automatically"]) >= 5


def test_full_onboarding():
    result = OnboardingService.get_full_onboarding()
    assert "quickstart" in result
    assert "glossary" in result
    assert "troubleshooting" in result
    assert "roles" in result
