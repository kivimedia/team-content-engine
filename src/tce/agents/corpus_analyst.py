"""Corpus Analyst — parses DOCX swipe files into structured PostExample records."""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import select

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.models.source_document import SourceDocument

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are the Corpus Analyst for a content engine. Your job is to parse social media \
post examples from a document and extract structured data for each post.

The document contains OCR-extracted text from screenshots of Facebook posts. \
Some sections marked "## OCR from Embedded Images" contain text extracted from \
post screenshots - these include the actual post content, engagement numbers, \
and descriptions of visuals used.

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

VISUAL ANALYSIS (critical for image prompt generation):
- visual_type: type of visual (screenshot, diagram, editorial_portrait, selfie, \
stock_photo, text_overlay, carousel, video_thumbnail, meme, quote_card, none)
- visual_description: brief description of the visual if detectable from context \
(e.g., "selfie with coaching client", "whiteboard framework diagram", \
"quote card on dark background")
- visual_text_overlay: any text overlaid on the image
- visual_mood: emotional mood of the visual (warm, professional, raw, polished, etc.)
- visual_engagement_correlation: does this visual type seem to correlate with \
higher engagement? (high, medium, low, unknown)

The corpus is in Hebrew. Extract structural patterns regardless of language. \
Output all analysis in English.

Return a JSON array of post objects.
"""

# File name patterns that indicate post corpus (not books/voice material)
POST_CORPUS_PATTERNS = ["fb_profile", "fb_post", "post_example", "swipe_file", "corpus"]


@register_agent
class CorpusAnalyst(AgentBase):
    name = "corpus_analyst"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Parse document content into structured post examples.

        If document_text is provided in context, uses that directly.
        Otherwise, loads post-corpus documents from the DB automatically
        (files matching FB_profiles / post patterns, NOT books).
        """
        document_text = context.get("document_text", "")
        document_id = context.get("document_id")

        # If no text provided, auto-load post-corpus docs from DB
        if not document_text:
            docs = await self._load_corpus_docs()
            if not docs:
                return {"post_examples": [], "warnings": ["No post-corpus documents found in DB"]}
            self._report(f"Loaded {len(docs)} post-corpus documents from DB")
        else:
            docs = [{"id": document_id, "text": document_text, "name": "provided"}]

        all_examples: list[dict[str, Any]] = []
        warnings: list[str] = []

        for doc in docs:
            doc_text = doc["text"]
            doc_id = doc["id"]
            doc_name = doc["name"]

            if not doc_text or not doc_text.strip():
                warnings.append(f"{doc_name}: empty text, skipping")
                continue

            self._report(f"Analyzing {doc_name} ({len(doc_text)} chars)")
            chunks = self._chunk_text(doc_text, max_chars=80000)

            for i, chunk in enumerate(chunks):
                chunk_label = f"{doc_name} chunk {i + 1}/{len(chunks)}"
                self._report(f"Processing {chunk_label}")

                response = await self._call_llm(
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Parse the following corpus section into "
                                f"structured post examples.\n\n"
                                f"SOURCE: {doc_name}\n"
                                f"DOCUMENT SECTION {i + 1}/{len(chunks)}:"
                                f"\n\n{chunk}"
                            ),
                        }
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=16384,
                    temperature=0.2,
                )

                text = self._extract_text(response)
                try:
                    examples = self._parse_json_response(text)
                    # Handle dict wrapper - LLM sometimes returns {"post_examples": [...]}
                    if isinstance(examples, dict):
                        for key in ("post_examples", "posts", "examples", "data"):
                            if key in examples and isinstance(examples[key], list):
                                examples = examples[key]
                                break
                    if isinstance(examples, list):
                        for ex in examples:
                            ex["document_id"] = str(doc_id)
                            ex["source_file"] = doc_name
                        all_examples.extend(examples)
                        self._report(f"{chunk_label}: found {len(examples)} posts")
                    else:
                        warnings.append(f"{chunk_label}: expected array, got {type(examples)}")
                except json.JSONDecodeError:
                    # Try to salvage truncated JSON arrays
                    salvaged = self._salvage_truncated_json(text)
                    if salvaged:
                        for ex in salvaged:
                            ex["document_id"] = str(doc_id)
                            ex["source_file"] = doc_name
                        all_examples.extend(salvaged)
                        self._report(f"{chunk_label}: salvaged {len(salvaged)} posts from truncated JSON")
                    else:
                        warnings.append(f"{chunk_label}: JSON parse error, salvage also failed")

        self._report(f"Total: {len(all_examples)} post examples from {len(docs)} documents")
        return {
            "post_examples": all_examples,
            "warnings": warnings,
            "total_parsed": len(all_examples),
        }

    async def _load_corpus_docs(self) -> list[dict[str, Any]]:
        """Load post-corpus documents from DB (FB profiles, not books)."""
        result = await self.db.execute(
            select(SourceDocument).where(SourceDocument.extracted_text.isnot(None))
        )
        all_docs = result.scalars().all()

        # Filter to post-corpus files (FB profiles, swipe files)
        # Exclude books (used for founder voice, not post templates)
        corpus_docs = []
        for doc in all_docs:
            name_lower = doc.file_name.lower().replace(" ", "_")
            is_corpus = any(pat in name_lower for pat in POST_CORPUS_PATTERNS)
            if is_corpus:
                corpus_docs.append(
                    {
                        "id": str(doc.id),
                        "text": doc.extracted_text,
                        "name": doc.file_name,
                    }
                )
                logger.info(
                    "corpus_analyst.loaded_doc",
                    name=doc.file_name,
                    chars=len(doc.extracted_text or ""),
                )

        return corpus_docs

    @staticmethod
    def _salvage_truncated_json(text: str) -> list[dict[str, Any]] | None:
        """Try to extract complete JSON objects from a truncated array response."""
        import re

        # Find the start of the JSON array
        match = re.search(r"\[", text)
        if not match:
            return None

        # Extract everything after the opening bracket
        content = text[match.start() + 1 :]
        # Find all complete JSON objects using brace matching
        objects = []
        i = 0
        while i < len(content):
            if content[i] == "{":
                depth = 0
                for j in range(i, len(content)):
                    if content[j] == "{":
                        depth += 1
                    elif content[j] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                obj = json.loads(content[i : j + 1])
                                objects.append(obj)
                            except json.JSONDecodeError:
                                pass
                            i = j + 1
                            break
                else:
                    break  # Truncated - no closing brace
            else:
                i += 1

        return objects if objects else None

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
