"""Tests for DOCX generation (professional lead magnet styling)."""

import tempfile
from pathlib import Path

from tce.utils.docx import create_guide_docx

# --- Legacy API compatibility ---


def test_legacy_api_still_works():
    """Legacy calling convention: create_guide_docx(title, sections, path)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/test_guide.docx"
        sections = [
            {"title": "Objective", "content": "Learn AI basics."},
            {"title": "Evidence Bank", "content": "Source: Anthropic blog."},
            {"title": "Summary", "content": "5 posts this week."},
        ]
        result = create_guide_docx("Test Weekly Guide", sections, output_path)
        assert result == output_path
        assert Path(output_path).exists()
        assert Path(output_path).stat().st_size > 0


def test_legacy_empty_sections():
    """Legacy API should handle empty sections gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/empty_guide.docx"
        create_guide_docx("Empty Guide", [], output_path)
        assert Path(output_path).exists()


# --- New structured API ---


def _make_full_guide() -> dict:
    """Build a realistic guide structure for testing."""
    return {
        "guide_title": "The Platform Dependency Trap",
        "subtitle": "How to build AI-resilient business operations before it's too late",
        "author_name": "Ziv Raviv",
        "author_url": "zivraviv.com",
        "sections": [
            {
                "type": "narrative",
                "title": "The $1 Billion Wake-Up Call",
                "content": (
                    "When Disney lost $1 billion and their entire AI video strategy "
                    "in 30 minutes, it revealed a hidden danger.\n\n"
                    "The partnership seemed solid. The technology was proven. "
                    "Then OpenAI made a strategic decision."
                ),
            },
            {
                "type": "callout",
                "label": "KEY INSIGHT",
                "content": (
                    "AI companies now prioritize strategic control over partnership revenue."
                ),
                "callout_style": "amber",
            },
            {
                "type": "comparison",
                "title": "Platform-Dependent vs AI-Resilient",
                "bad_label": "Platform-Dependent Businesses",
                "bad_items": [
                    "Build core functions on one AI platform",
                    "No backup plan for tool withdrawal",
                    "Treat AI partnerships as permanent",
                ],
                "good_label": "AI-Resilient Businesses",
                "good_items": [
                    "Diversify across 3+ AI providers",
                    "30-minute switch capability",
                    "Treat AI as acceleration, not foundation",
                ],
            },
            {
                "type": "framework",
                "title": "The Platform Independence Framework",
                "intro": (
                    "Four layers that protect your business from sudden AI partnership collapses."
                ),
                "steps": [
                    {
                        "label": "Diversification Strategy",
                        "explanation": (
                            "Never build core business functions on a single AI platform."
                        ),
                        "bullets": [
                            "Maintain relationships with 3+ AI providers",
                            "Keep 30% of AI capabilities in-house",
                        ],
                        "action": (
                            "List every AI tool your business uses."
                            " For each one, identify at least"
                            " one alternative."
                        ),
                    },
                    {
                        "label": "The 30-Minute Rule",
                        "explanation": (
                            "Every AI-dependent process must have a manual or alternative backup."
                        ),
                        "bullets": [
                            "Test backup systems monthly",
                            "Document exact steps to switch providers",
                        ],
                        "action": (
                            "Pick your most critical AI-dependent"
                            " process. Create a step-by-step"
                            " backup plan this week."
                        ),
                    },
                ],
            },
            {
                "type": "scenarios",
                "title": "What To Do When It Happens",
                "intro": "Five situations you might face and exactly how to respond.",
                "scenarios": [
                    {
                        "situation": "Your AI vendor announces a strategic pivot",
                        "response": (
                            "Immediately activate your"
                            " diversification plan. Begin"
                            " testing alternative providers."
                        ),
                    },
                    {
                        "situation": "API pricing suddenly doubles",
                        "response": (
                            "Switch non-critical workloads to alternatives within 48 hours."
                        ),
                    },
                    {
                        "situation": "A competitor gets exclusive access to your AI provider",
                        "response": (
                            "This is your signal to accelerate in-house capability building."
                        ),
                    },
                ],
            },
            {
                "type": "closing",
                "headline": "Use AI partnerships for acceleration. Never for survival.",
                "recap_steps": [
                    "Diversify across multiple AI providers",
                    "Build the 30-minute switch capability",
                    "Watch for early warning signals",
                ],
                "cta": (
                    "Want to discuss your AI resilience strategy? Connect with me at zivraviv.com"
                ),
            },
        ],
        "cta_keyword": "CONTROL",
    }


def test_new_api_full_guide():
    """New API should create a DOCX with all section types."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/full_guide.docx"
        guide_data = _make_full_guide()
        result = create_guide_docx(guide_data, output_path)
        assert result == output_path
        assert Path(output_path).exists()
        # Full guide with all section types should be a decent size
        assert Path(output_path).stat().st_size > 5000


def test_narrative_only():
    """Guide with only narrative sections should work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/narrative.docx"
        guide = {
            "guide_title": "Simple Guide",
            "subtitle": "A test",
            "sections": [
                {
                    "type": "narrative",
                    "title": "Introduction",
                    "content": "Hello world.\n\nSecond paragraph.",
                },
                {"type": "narrative", "title": "Conclusion", "content": "Goodbye."},
            ],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()


def test_comparison_table():
    """Comparison table with uneven items should not crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/comparison.docx"
        guide = {
            "guide_title": "Comparison Test",
            "sections": [
                {
                    "type": "comparison",
                    "title": "Before vs After",
                    "bad_label": "Old Way",
                    "bad_items": ["Item 1", "Item 2"],
                    "good_label": "New Way",
                    "good_items": ["Item A", "Item B", "Item C", "Item D"],
                },
            ],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()


def test_framework_section():
    """Framework with steps and action callouts should render."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/framework.docx"
        guide = {
            "guide_title": "Framework Test",
            "sections": [
                {
                    "type": "framework",
                    "title": "My Framework",
                    "intro": "Here are the steps.",
                    "steps": [
                        {
                            "label": "First Step",
                            "explanation": "Do this first.",
                            "bullets": ["Point A", "Point B"],
                            "action": "Take this action now.",
                        },
                    ],
                },
            ],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()


def test_scenario_section():
    """Scenario tables should render without errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/scenarios.docx"
        guide = {
            "guide_title": "Scenario Test",
            "sections": [
                {
                    "type": "scenarios",
                    "title": "What To Do",
                    "scenarios": [
                        {"situation": "Something happens", "response": "Do this."},
                        {"situation": "Another thing", "response": "Do that."},
                    ],
                },
            ],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()


def test_creates_parent_dirs():
    """Should create parent directories if they don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/deep/nested/dir/guide.docx"
        guide = {
            "guide_title": "Nested Test",
            "sections": [{"type": "narrative", "title": "Test", "content": "Content"}],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()


def test_bullets_in_narrative():
    """Narrative sections should auto-detect bullet lists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/bullets.docx"
        guide = {
            "guide_title": "Bullet Test",
            "sections": [
                {
                    "type": "narrative",
                    "title": "With Bullets",
                    "content": (
                        "Some text.\n\n- First bullet\n"
                        "- Second bullet\n- Third bullet"
                        "\n\nMore text."
                    ),
                },
            ],
        }
        create_guide_docx(guide, output_path)
        assert Path(output_path).exists()
