"""Authentication and RBAC (PRD Section 25).

Simple role-based access control for v1.
In production, replace with JWT/OAuth2.
"""

from __future__ import annotations

from enum import StrEnum

import structlog

logger = structlog.get_logger()


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


# Permission matrix: role -> allowed actions
PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN: {
        "read", "write", "delete", "approve", "reject", "publish",
        "manage_prompts", "manage_templates", "manage_creators",
        "manage_settings", "manage_users", "trigger_pipeline",
        "view_costs", "manage_experiments", "seed_database",
    },
    Role.OPERATOR: {
        "read", "write", "approve", "reject", "publish",
        "manage_prompts", "manage_templates", "manage_creators",
        "trigger_pipeline", "view_costs", "manage_experiments",
    },
    Role.VIEWER: {
        "read", "view_costs",
    },
}

# Actions that require specific roles
PROTECTED_ACTIONS = {
    "seed_database": {Role.ADMIN},
    "manage_users": {Role.ADMIN},
    "manage_settings": {Role.ADMIN},
    "delete": {Role.ADMIN},
    "publish": {Role.ADMIN, Role.OPERATOR},
    "approve": {Role.ADMIN, Role.OPERATOR},
    "reject": {Role.ADMIN, Role.OPERATOR},
    "trigger_pipeline": {Role.ADMIN, Role.OPERATOR},
}


class AuthService:
    """Simple role-based authorization service."""

    def __init__(self, current_role: str = Role.OPERATOR) -> None:
        self.current_role = current_role

    def has_permission(self, action: str) -> bool:
        """Check if the current role has permission for an action."""
        allowed = PERMISSIONS.get(self.current_role, set())
        return action in allowed

    def require_permission(self, action: str) -> None:
        """Raise if the current role lacks permission."""
        if not self.has_permission(action):
            raise PermissionError(
                f"Role '{self.current_role}' lacks permission "
                f"for action '{action}'"
            )

    def get_allowed_actions(self) -> set[str]:
        """Get all actions allowed for the current role."""
        return PERMISSIONS.get(self.current_role, set()).copy()

    @staticmethod
    def get_roles() -> list[str]:
        """Get all available roles."""
        return [r.value for r in Role]

    @staticmethod
    def get_role_permissions(role: str) -> set[str]:
        """Get permissions for a specific role."""
        return PERMISSIONS.get(role, set()).copy()
