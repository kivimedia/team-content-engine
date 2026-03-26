"""Tests for auth/RBAC (PRD Section 25)."""

from tce.services.auth import (
    PROTECTED_ACTIONS,
    AuthService,
    Role,
)


def test_three_roles():
    assert len(Role) == 3
    assert "admin" in [r.value for r in Role]
    assert "operator" in [r.value for r in Role]
    assert "viewer" in [r.value for r in Role]


def test_admin_has_all_permissions():
    service = AuthService(Role.ADMIN)
    assert service.has_permission("read")
    assert service.has_permission("write")
    assert service.has_permission("delete")
    assert service.has_permission("seed_database")
    assert service.has_permission("manage_users")


def test_operator_permissions():
    service = AuthService(Role.OPERATOR)
    assert service.has_permission("read")
    assert service.has_permission("write")
    assert service.has_permission("approve")
    assert service.has_permission("trigger_pipeline")
    assert not service.has_permission("delete")
    assert not service.has_permission("manage_users")
    assert not service.has_permission("seed_database")


def test_viewer_limited():
    service = AuthService(Role.VIEWER)
    assert service.has_permission("read")
    assert service.has_permission("view_costs")
    assert not service.has_permission("write")
    assert not service.has_permission("approve")
    assert not service.has_permission("trigger_pipeline")


def test_require_permission_raises():
    service = AuthService(Role.VIEWER)
    try:
        service.require_permission("write")
        assert False, "Should have raised"
    except PermissionError:
        pass


def test_get_roles():
    roles = AuthService.get_roles()
    assert "admin" in roles
    assert "operator" in roles
    assert "viewer" in roles


def test_protected_actions():
    assert "seed_database" in PROTECTED_ACTIONS
    assert Role.ADMIN in PROTECTED_ACTIONS["seed_database"]
