"""Tests for operator controls (PRD Section 4.4)."""

import asyncio

from tce.services.operator_controls import OperatorControlService


def test_service_exists():
    assert OperatorControlService is not None


def test_template_control_methods():
    for method in ["lock_template", "unlock_template", "ban_template"]:
        assert hasattr(OperatorControlService, method)
        assert asyncio.iscoroutinefunction(
            getattr(OperatorControlService, method)
        )


def test_source_control_methods():
    for method in ["approve_source", "reject_source"]:
        assert hasattr(OperatorControlService, method)
        assert asyncio.iscoroutinefunction(
            getattr(OperatorControlService, method)
        )


def test_weight_control_method():
    assert hasattr(OperatorControlService, "set_influence_weight")
    assert asyncio.iscoroutinefunction(
        OperatorControlService.set_influence_weight
    )


def test_platform_flags_default():
    flags = OperatorControlService.get_platform_flags()
    assert flags["facebook"] is True
    assert flags["linkedin"] is True


def test_set_platform_flag():
    result = OperatorControlService.set_platform_flag("facebook", False)
    assert result["new_value"] is False
    # Reset
    OperatorControlService.set_platform_flag("facebook", True)


def test_set_unknown_platform():
    result = OperatorControlService.set_platform_flag("tiktok", True)
    assert "error" in result
