"""Tests for DOCX generation (PRD Section 9.9)."""

import tempfile
from pathlib import Path

from tce.utils.docx import create_guide_docx


def test_create_guide_docx():
    """DOCX file should be created with correct structure."""
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


def test_create_guide_empty_sections():
    """Should handle empty sections gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/empty_guide.docx"
        create_guide_docx("Empty Guide", [], output_path)
        assert Path(output_path).exists()


def test_create_guide_long_content():
    """Should handle long content without crashing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/long_guide.docx"
        sections = [
            {
                "title": f"Section {i}",
                "content": f"Content paragraph {i}. " * 50,
            }
            for i in range(12)  # 12 sections per PRD Section 20.3
        ]
        create_guide_docx("Long Guide", sections, output_path)
        assert Path(output_path).exists()


def test_create_guide_creates_parent_dirs():
    """Should create parent directories if they don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/deep/nested/dir/guide.docx"
        create_guide_docx(
            "Nested Guide",
            [{"title": "Test", "content": "Content"}],
            output_path,
        )
        assert Path(output_path).exists()
