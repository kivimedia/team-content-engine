"""Token counting and cost estimation helpers."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~2 for Hebrew."""
    return max(1, len(text) // 4)


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Quick cost estimate without cache considerations."""
    from tce.services.cost_tracker import compute_cost

    return compute_cost(model, input_tokens, output_tokens)
