"""Humanitarian Sensitivity Gate (PRD Section 51).

Non-negotiable QA dimension with hard floor on weight and threshold.
Every post passes through this check before publication.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# PRD Section 51.6: Non-negotiable constraints
MIN_WEIGHT = 0.08  # Cannot be set below 8%
MIN_THRESHOLD = 7  # Pass threshold cannot be set below 7
ACTUAL_THRESHOLD = 8  # PRD specifies >= 8 for pass
CANNOT_BE_DISABLED = True


# PRD Section 51.4: Examples of what gets flagged
FLAG_PATTERNS = [
    {
        "pattern": "fear_exploitation",
        "description": "Using fear, suffering, or crisis as a hook to sell",
        "examples": [
            "AI is coming for your job and there's nothing you can do",
            "If you're not using AI by now, you deserve to be left behind",
        ],
    },
    {
        "pattern": "tone_mismatch",
        "description": "Playful/humorous content during active tragedy",
        "examples": [
            "Lighthearted tool post published same day as major tragedy",
        ],
    },
    {
        "pattern": "dignity_violation",
        "description": "Disrespecting people mentioned in the post",
        "examples": [
            "Most consultants are doing it wrong (without path forward)",
        ],
    },
    {
        "pattern": "war_metaphors",
        "description": "Casual military metaphors during active conflict",
        "examples": [
            "This tool is a weapon",
            "Destroy the competition",
        ],
    },
    {
        "pattern": "punishment_framing",
        "description": "Punishing the audience instead of helping them",
        "examples": [
            "If you're not using AI by now, you deserve to be left behind",
        ],
    },
]


class HumanitarianGate:
    """Enforces humanitarian sensitivity checks on content."""

    def __init__(
        self,
        current_events_context: str | None = None,
        sensitive_period: bool = False,
    ) -> None:
        self.current_events_context = current_events_context
        self.sensitive_period = sensitive_period

    def check(
        self,
        facebook_post: str = "",
        linkedin_post: str = "",
    ) -> dict[str, Any]:
        """Run humanitarian sensitivity checks on post content.

        Returns a dict with score, flags, and revision suggestions.
        """
        flags: list[dict[str, Any]] = []
        combined_text = (facebook_post + " " + linkedin_post).lower()

        # Check for fear exploitation patterns
        fear_phrases = [
            "nothing you can do",
            "you deserve to be left behind",
            "there's no escape",
            "you're already behind",
            "too late for you",
        ]
        for phrase in fear_phrases:
            if phrase in combined_text:
                flags.append({
                    "pattern": "fear_exploitation",
                    "phrase": phrase,
                    "severity": "high",
                    "suggestion": (
                        "Reframe to empower rather than threaten. "
                        "Show what's possible, not what's feared."
                    ),
                })

        # Check for casual war/violence metaphors
        war_phrases = [
            "weapon", "destroy the competition",
            "kill it", "battle", "warfare",
            "ammunition", "target your enemy",
        ]
        for phrase in war_phrases:
            if phrase in combined_text:
                flags.append({
                    "pattern": "war_metaphors",
                    "phrase": phrase,
                    "severity": (
                        "high" if self.sensitive_period else "medium"
                    ),
                    "suggestion": (
                        "Replace military metaphors with constructive ones. "
                        "Use 'build', 'create', 'improve' instead."
                    ),
                })

        # Check for punishment framing
        punishment_phrases = [
            "you deserve",
            "your fault",
            "you're doing it wrong",
            "shame on",
            "embarrassing that you",
        ]
        for phrase in punishment_phrases:
            if phrase in combined_text:
                flags.append({
                    "pattern": "punishment_framing",
                    "phrase": phrase,
                    "severity": "medium",
                    "suggestion": (
                        "Shift from criticism to guidance. "
                        "Help the reader improve, don't punish them."
                    ),
                })

        # Compute score
        if not flags:
            score = 10
        elif any(f["severity"] == "high" for f in flags):
            score = 4
        elif len(flags) >= 3:
            score = 5
        else:
            score = 7

        # Sensitive period penalty
        if self.sensitive_period and score > 6:
            score = max(score - 1, 6)

        passes = score >= ACTUAL_THRESHOLD

        return {
            "score": score,
            "passes": passes,
            "threshold": ACTUAL_THRESHOLD,
            "flags": flags,
            "sensitive_period": self.sensitive_period,
            "current_events_context": self.current_events_context,
            "revision_needed": not passes,
        }

    @staticmethod
    def get_flag_patterns() -> list[dict[str, Any]]:
        """Get all flag patterns for documentation/UI."""
        return FLAG_PATTERNS.copy()

    @staticmethod
    def validate_config(
        weight: float, threshold: int
    ) -> dict[str, Any]:
        """Validate that config doesn't violate non-negotiable constraints.

        PRD Section 51.6: Cannot be disabled or set below minimums.
        """
        issues = []
        if weight < MIN_WEIGHT:
            issues.append(
                f"Weight {weight} below minimum {MIN_WEIGHT}"
            )
        if threshold < MIN_THRESHOLD:
            issues.append(
                f"Threshold {threshold} below minimum {MIN_THRESHOLD}"
            )
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "enforced_weight": max(weight, MIN_WEIGHT),
            "enforced_threshold": max(threshold, MIN_THRESHOLD),
        }
