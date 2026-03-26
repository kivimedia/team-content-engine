"""Founder Voice Extractor — extracts voice profile from books/posts (PRD Section 50)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Founder Voice Extractor for Team Content Engine. Your job is to \
analyze the founder's writing (books, posts, transcripts) and extract their \
authentic voice profile.

Extract these dimensions (PRD Section 50.3):
- vocabulary_signature: distinctive words and phrases the founder naturally uses
- sentence_rhythm: avg sentence length, variation, cadence patterns
- values_and_beliefs: core convictions the founder stands for
- metaphor_families: recurring metaphor domains (sports, war, construction, food, etc.)
- humor_type: dry, self-deprecating, observational, or none
- tone_range: mapped across contexts (serious, playful, vulnerable, provocative)
- taboos: things the founder would never say or endorse
- recurring_themes: topics the founder keeps coming back to

OUTPUT FORMAT (JSON):
{
  "vocabulary_signature": {"distinctive_words": [...], "avoided_words": [...], "phrases": [...]},
  "sentence_rhythm_profile": {"avg_length": "short/medium/long", "variation": "low/medium/high"},
  "values_and_beliefs": ["..."],
  "metaphor_families": ["..."],
  "humor_type": "...",
  "tone_range": {"serious": 1-10, "playful": 1-10, "vulnerable": 1-10, "provocative": 1-10},
  "taboos": ["..."],
  "recurring_themes": ["..."]
}
"""


@register_agent
class FounderVoiceExtractor(AgentBase):
    name = "founder_voice_extractor"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract voice profile from founder's writing."""
        text = context.get("founder_text", "")
        source_type = context.get("source_type", "book")

        if not text:
            return {
                "founder_voice": {},
                "warnings": ["No founder text provided"],
            }

        # Chunk if very long
        chunks = self._chunk_text(text, max_chars=60000)
        all_profiles: list[dict] = []

        for i, chunk in enumerate(chunks):
            response = await self._call_llm(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Analyze this {source_type} excerpt "
                            f"({i + 1}/{len(chunks)}) and extract "
                            f"the founder's voice profile.\n\n{chunk}"
                        ),
                    }
                ],
                system=SYSTEM_PROMPT,
                max_tokens=4096,
                temperature=0.3,
            )

            text_out = self._extract_text(response)
            try:
                profile = self._parse_json_response(text_out)
                all_profiles.append(profile)
            except json.JSONDecodeError:
                pass

        # Merge profiles from multiple chunks
        merged = self._merge_profiles(all_profiles)
        return {"founder_voice": merged}

    def _chunk_text(
        self, text: str, max_chars: int = 60000
    ) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_chars:
                chunks.append(text)
                break
            split_at = text.rfind("\n\n", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
        return chunks

    def _merge_profiles(
        self, profiles: list[dict]
    ) -> dict[str, Any]:
        """Merge voice profiles extracted from multiple chunks."""
        if not profiles:
            return {}
        if len(profiles) == 1:
            return profiles[0]

        # Take first profile as base, merge lists from others
        merged = profiles[0].copy()
        for profile in profiles[1:]:
            for key in [
                "values_and_beliefs",
                "metaphor_families",
                "taboos",
                "recurring_themes",
            ]:
                existing = merged.get(key, [])
                new = profile.get(key, [])
                if isinstance(existing, list) and isinstance(new, list):
                    merged[key] = list(set(existing + new))

            # Merge vocabulary
            if "vocabulary_signature" in profile:
                base_vocab = merged.get("vocabulary_signature", {})
                new_vocab = profile["vocabulary_signature"]
                for sub_key in [
                    "distinctive_words",
                    "avoided_words",
                    "phrases",
                ]:
                    base_list = base_vocab.get(sub_key, [])
                    new_list = new_vocab.get(sub_key, [])
                    if isinstance(base_list, list):
                        base_vocab[sub_key] = list(
                            set(base_list + new_list)
                        )
                merged["vocabulary_signature"] = base_vocab

        return merged
