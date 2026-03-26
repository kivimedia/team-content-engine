"""Tests for publishing adapter export format."""

import asyncio

from tce.services.publishing import ManualExportAdapter


def test_manual_export_format():
    """Export should include all platform-specific content."""
    adapter = ManualExportAdapter()
    package = {
        "facebook_post": "Check out this AI tool!",
        "linkedin_post": "Here's a deeper analysis of AI agents.",
        "hook_variants": ["Hook 1", "Hook 2"],
        "cta_keyword": "agents",
        "dm_flow": {"trigger": "agents", "ack": "Thanks!"},
    }
    result = asyncio.get_event_loop().run_until_complete(
        adapter.publish(package)
    )
    assert result["adapter"] == "manual_export"
    assert result["status"] == "exported"
    assert "facebook" in result
    assert "linkedin" in result
    assert result["facebook"]["post"] == "Check out this AI tool!"
    assert result["facebook"]["cta"] == "agents"
    assert "instructions" in result


def test_manual_export_empty_package():
    """Should handle empty package gracefully."""
    adapter = ManualExportAdapter()
    result = asyncio.get_event_loop().run_until_complete(
        adapter.publish({})
    )
    assert result["adapter"] == "manual_export"
    assert result["facebook"]["post"] == ""
