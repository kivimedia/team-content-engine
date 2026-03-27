"""Anti-clone enforcement service (PRD Section 14.3).

Checks post content against source corpus for similarity,
phrase blacklist violations, and rhythm cloning.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# PRD Section 14.3: Thresholds
SIMILARITY_THRESHOLD = 0.85
PHRASE_MATCH_LIMIT = 3  # Max exact phrases from any single creator


class AntiCloneChecker:
    """Checks generated content against source corpus for cloning."""

    def __init__(
        self,
        creator_profiles: list[dict[str, Any]] | None = None,
        corpus_examples: list[dict[str, Any]] | None = None,
    ) -> None:
        self.creator_profiles = creator_profiles or []
        self.corpus_examples = corpus_examples or []
        self._blacklisted_phrases: set[str] = set()
        self._build_blacklist()

    def _build_blacklist(self) -> None:
        """Build phrase blacklist from creator profiles."""
        for profile in self.creator_profiles:
            markers = profile.get("disallowed_clone_markers", [])
            if markers:
                for marker in markers:
                    self._blacklisted_phrases.add(marker.lower())

    def check(
        self,
        post_text: str,
        platform: str = "facebook",
    ) -> dict[str, Any]:
        """Run anti-clone checks on generated content."""
        issues: list[dict[str, Any]] = []
        post_lower = post_text.lower()

        # 1. Phrase blacklist check
        for phrase in self._blacklisted_phrases:
            if phrase in post_lower:
                issues.append(
                    {
                        "type": "blacklisted_phrase",
                        "phrase": phrase,
                        "severity": "high",
                        "action": "Must rewrite to avoid this phrase",
                    }
                )

        # 2. Corpus similarity check (simple word overlap)
        for example in self.corpus_examples[:50]:
            corpus_text = (
                example.get("hook_text", "") or example.get("post_text_raw", "") or ""
            ).lower()
            if not corpus_text:
                continue

            similarity = self._word_overlap_similarity(post_lower, corpus_text)
            if similarity > SIMILARITY_THRESHOLD:
                issues.append(
                    {
                        "type": "high_similarity",
                        "creator": example.get("creator_name", "unknown"),
                        "similarity": round(similarity, 3),
                        "severity": "high",
                        "action": (
                            "Post too similar to corpus example. Rewrite with different vocabulary."
                        ),
                    }
                )

        # 3. Consecutive rhythm check (same sentence length pattern)
        post_sentences = [s.strip() for s in post_text.replace("\n", " ").split(".") if s.strip()]
        for example in self.corpus_examples[:20]:
            corpus_text = example.get("post_text_raw", "") or ""
            corpus_sentences = [
                s.strip() for s in corpus_text.replace("\n", " ").split(".") if s.strip()
            ]
            if self._rhythm_match(post_sentences, corpus_sentences):
                issues.append(
                    {
                        "type": "rhythm_clone",
                        "creator": example.get("creator_name", "unknown"),
                        "severity": "medium",
                        "action": ("Sentence rhythm too close to source. Vary paragraph lengths."),
                    }
                )

        passes = not any(i["severity"] == "high" for i in issues)

        return {
            "passes": passes,
            "issues": issues,
            "issue_count": len(issues),
            "blacklist_size": len(self._blacklisted_phrases),
            "corpus_examples_checked": min(50, len(self.corpus_examples)),
        }

    @staticmethod
    def _word_overlap_similarity(text_a: str, text_b: str) -> float:
        """Simple word overlap Jaccard similarity."""
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    @staticmethod
    def _rhythm_match(
        sentences_a: list[str],
        sentences_b: list[str],
        window: int = 5,
    ) -> bool:
        """Check if sentence length patterns match over a window."""
        if len(sentences_a) < window or len(sentences_b) < window:
            return False

        lengths_a = [len(s.split()) for s in sentences_a[:window]]
        lengths_b = [len(s.split()) for s in sentences_b[:window]]

        # Check if relative pattern matches (short/medium/long)
        pattern_a = ["S" if n < 8 else "M" if n < 20 else "L" for n in lengths_a]
        pattern_b = ["S" if n < 8 else "M" if n < 20 else "L" for n in lengths_b]

        matches = sum(1 for a, b in zip(pattern_a, pattern_b) if a == b)
        return matches >= window - 1  # 4 out of 5 match
