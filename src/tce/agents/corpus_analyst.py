"""Corpus Analyst — parses DOCX swipe files into structured PostExample records."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Corpus Analyst for a content engine. Your job is to parse social media \
post examples from a document and extract structured data for each post.

For each post you find, extract:
- creator_name: who wrote it
- post_text_raw: the full text of the post
- hook_text: the opening hook (first 1-3 sentences)
- body_text: the main body
- cta_text: the call-to-action at the end
- hook_type: classify the hook (e.g., paradox, diagnosis, famous_name, tool_reveal, \
scenario, status_comparison, direct_attack)
- body_structure: classify the structure (e.g., numbered_framework, chronological, \
bullet_list, problem_reframe, scenario_procedure)
- story_arc: the narrative arc (e.g., escalating_stakes, injustice_resolution, \
myth_busting, progressive_revelation)
- tension_type: what creates tension (e.g., curiosity_gap, status_threat, \
contrarian_claim, procedural_dread)
- cta_type: classify the CTA (e.g., keyword_comment, discussion_prompt, \
soft_follow, self_disclosure, content_link)
- visual_type: type of visual (e.g., screenshot, diagram, editorial_portrait, none)
- tone_tags: list of tone descriptors
- topic_tags: list of topic tags
- audience_guess: who this post targets
- proof_style: how claims are supported
- paragraph_count: number of paragraphs
- uses_bullets: boolean
- has_explicit_keyword_cta: boolean
- visible_comments: number if visible, null if not
- visible_shares: number if visible, null if not
- engagement_confidence: A (both visible), B (one visible), C (neither/unclear)

The corpus is in Hebrew. Extract structural patterns regardless of language. \
Output all analysis in English.

Return a JSON array of post objects.
"""


@register_agent
class CorpusAnalyst(AgentBase):
    name = "corpus_analyst"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Parse document content into structured post examples."""
        document_text = context.get("document_text", "")
        document_id = context.get("document_id")

        if not document_text:
            return {"post_examples": [], "warnings": ["No document text provided"]}

        # Chunk if document is very long (>100k chars)
        chunks = self._chunk_text(document_text, max_chars=80000)
        all_examples: list[dict[str, Any]] = []
        warnings: list[str] = []

        for i, chunk in enumerate(chunks):
            response = await self._call_llm(
                messages=[
                    {
                        "role": "user",
                        "content": f"Parse the following corpus section into structured post examples.\n\n"
                        f"DOCUMENT SECTION {i + 1}/{len(chunks)}:\n\n{chunk}",
                    }
                ],
                system=SYSTEM_PROMPT,
                max_tokens=8192,
                temperature=0.2,
            )

            text = self._extract_text(response)
            try:
                examples = self._parse_json_response(text)
                if isinstance(examples, list):
                    for ex in examples:
                        ex["document_id"] = str(document_id)
                    all_examples.extend(examples)
                else:
                    warnings.append(f"Chunk {i + 1}: expected array, got {type(examples)}")
            except json.JSONDecodeError as e:
                warnings.append(f"Chunk {i + 1}: JSON parse error: {e}")

        return {
            "post_examples": all_examples,
            "warnings": warnings,
            "total_parsed": len(all_examples),
        }

    def _chunk_text(self, text: str, max_chars: int = 80000) -> list[str]:
        """Split text into chunks, trying to break at paragraph boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_chars:
                chunks.append(text)
                break
            # Find a paragraph break near the limit
            split_at = text.rfind("\n\n", 0, max_chars)
            if split_at == -1:
                split_at = text.rfind("\n", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
        return chunks
