"""Pipeline step definition."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineStep:
    """A single step in an orchestrated pipeline."""

    agent_name: str
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 2
    timeout_seconds: int = 120
    optional: bool = False  # If True, failure doesn't block downstream steps
    is_gate: bool = False  # If True, pipeline pauses here for human approval
