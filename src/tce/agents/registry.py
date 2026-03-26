"""Agent registry — maps agent names to classes for orchestrator lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tce.agents.base import AgentBase

# Global registry: agent_name -> AgentBase subclass
_registry: dict[str, type[AgentBase]] = {}


def register_agent(cls: type[AgentBase]) -> type[AgentBase]:
    """Decorator to register an agent class by its name attribute."""
    _registry[cls.name] = cls
    return cls


def agent_registry() -> dict[str, type[AgentBase]]:
    """Return a copy of the agent registry."""
    return dict(_registry)


def get_agent_class(name: str) -> type[AgentBase]:
    """Look up an agent class by name. Raises KeyError if not found."""
    if name not in _registry:
        raise KeyError(f"Agent '{name}' not registered. Available: {list(_registry.keys())}")
    return _registry[name]
