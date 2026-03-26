"""House Voice System — voice blending engine (PRD Section 14).

Manages the house voice blend, per-angle weight adjustment,
and anti-clone controls.
"""

from __future__ import annotations

from typing import Any

# PRD Section 14.1: Voice axes
VOICE_AXES = [
    "curiosity",
    "sharpness",
    "practicality",
    "strategic_depth",
    "emotional_intensity",
    "sentence_punch",
    "executive_clarity",
    "contrarian_heat",
    "friendliness",
    "urgency",
]

# PRD Section 14.2: Default influence weights
DEFAULT_INFLUENCE_WEIGHTS = {
    "Omri Barak": 0.24,
    "Ben Z. Yabets": 0.20,
    "Nathan Savis": 0.20,
    "Eden Bibas": 0.18,
    "Alex Kap": 0.18,
}

# PRD Section 14.2: Per-angle weight adjustments
ANGLE_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "weekly_roundup": {
        "Omri Barak": 0.30,
        "Alex Kap": 0.30,
        "Ben Z. Yabets": 0.15,
        "Nathan Savis": 0.15,
        "Eden Bibas": 0.10,
    },
    "tactical_workflow_guide": {
        "Eden Bibas": 0.30,
        "Ben Z. Yabets": 0.30,
        "Omri Barak": 0.15,
        "Alex Kap": 0.15,
        "Nathan Savis": 0.10,
    },
    "hidden_feature_shortcut": {
        "Eden Bibas": 0.30,
        "Ben Z. Yabets": 0.30,
        "Omri Barak": 0.15,
        "Alex Kap": 0.15,
        "Nathan Savis": 0.10,
    },
    "contrarian_diagnosis": {
        "Nathan Savis": 0.30,
        "Ben Z. Yabets": 0.25,
        "Omri Barak": 0.20,
        "Alex Kap": 0.15,
        "Eden Bibas": 0.10,
    },
    "teardown_myth_busting": {
        "Nathan Savis": 0.30,
        "Ben Z. Yabets": 0.25,
        "Omri Barak": 0.20,
        "Alex Kap": 0.15,
        "Eden Bibas": 0.10,
    },
    "founder_reflection": {
        "Nathan Savis": 0.25,
        "Alex Kap": 0.25,
        "Omri Barak": 0.20,
        "Ben Z. Yabets": 0.20,
        "Eden Bibas": 0.10,
    },
}

# PRD Section 14.3: Anti-clone controls
SIMILARITY_THRESHOLD = 0.85  # Max semantic similarity to corpus examples
MIN_RHYTHM_VARIATION = 0.3  # Minimum variation from source rhythm


class HouseVoiceEngine:
    """Manages the house voice blend and anti-clone controls."""

    def __init__(
        self,
        creator_profiles: dict[str, dict[str, Any]] | None = None,
        founder_voice: dict[str, Any] | None = None,
    ) -> None:
        self.creator_profiles = creator_profiles or {}
        self.founder_voice = founder_voice or {}

    def get_weights_for_angle(
        self,
        angle_type: str,
        operator_overrides: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Get influence weights for a specific angle type.

        Priority: operator_overrides > angle-specific > defaults.
        """
        if operator_overrides:
            return self._normalize_weights(operator_overrides)

        angle_weights = ANGLE_WEIGHT_OVERRIDES.get(angle_type)
        if angle_weights:
            return angle_weights

        return DEFAULT_INFLUENCE_WEIGHTS.copy()

    def blend_voice_axes(
        self,
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Compute blended voice axes from weighted creator profiles."""
        blended: dict[str, float] = {axis: 0.0 for axis in VOICE_AXES}

        for creator_name, weight in weights.items():
            profile = self.creator_profiles.get(creator_name, {})
            axes = profile.get("voice_axes", {})
            for axis in VOICE_AXES:
                blended[axis] += axes.get(axis, 5.0) * weight

        # Round to 1 decimal
        return {k: round(v, 1) for k, v in blended.items()}

    def build_voice_prompt(
        self,
        angle_type: str,
        operator_overrides: dict[str, float] | None = None,
    ) -> str:
        """Build a voice instruction block for writer prompts."""
        weights = self.get_weights_for_angle(
            angle_type, operator_overrides
        )
        blended_axes = self.blend_voice_axes(weights)

        lines = ["[HOUSE VOICE BLEND]"]
        lines.append(
            f"Angle: {angle_type}"
        )
        lines.append("Influence weights:")
        for creator, weight in sorted(
            weights.items(), key=lambda x: -x[1]
        ):
            lines.append(f"  {creator}: {weight:.2f}")

        lines.append("\nTarget voice axes (1-10):")
        for axis, value in blended_axes.items():
            lines.append(f"  {axis}: {value}")

        # Add founder voice if available
        if self.founder_voice:
            lines.append("\n[FOUNDER VOICE LAYER]")
            if self.founder_voice.get("values_and_beliefs"):
                lines.append(
                    f"Core values: "
                    f"{', '.join(self.founder_voice['values_and_beliefs'][:5])}"
                )
            if self.founder_voice.get("taboos"):
                lines.append(
                    f"Never say: "
                    f"{', '.join(self.founder_voice['taboos'][:5])}"
                )
            if self.founder_voice.get("recurring_themes"):
                lines.append(
                    f"Recurring themes: "
                    f"{', '.join(self.founder_voice['recurring_themes'][:5])}"
                )
            lines.append(
                "The founder's voice takes priority over "
                "all other style instructions."
            )

        # Anti-clone controls
        lines.append("\n[ANTI-CLONE CONTROLS]")
        lines.append(
            f"- Max similarity to source corpus: {SIMILARITY_THRESHOLD}"
        )
        lines.append(
            "- Do not reproduce signature phrases from any creator"
        )
        lines.append(
            "- Vary sentence rhythm — don't mirror any single source"
        )
        lines.append(
            "- Every post must have topic-specific proof blocks"
        )

        return "\n".join(lines)

    @staticmethod
    def _normalize_weights(
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Normalize weights to sum to 1.0."""
        total = sum(weights.values())
        if total <= 0:
            return weights
        return {k: round(v / total, 4) for k, v in weights.items()}
