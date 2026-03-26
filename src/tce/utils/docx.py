"""DOCX generation helpers for the Guide Builder."""

from __future__ import annotations

from pathlib import Path

import docx
from docx.shared import Pt


def create_guide_docx(
    title: str,
    sections: list[dict[str, str]],
    output_path: str,
) -> str:
    """Create a polished DOCX guide from structured sections.

    Args:
        title: Guide title for the cover page.
        sections: List of {title, content} dicts.
        output_path: Where to save the DOCX file.

    Returns:
        The output path.
    """
    doc = docx.Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    # Cover page
    heading = doc.add_heading(title, level=0)
    heading.alignment = 1  # Center
    doc.add_paragraph("")  # Spacer

    # Add sections
    for section in sections:
        doc.add_heading(section.get("title", ""), level=1)
        content = section.get("content", "")
        for para_text in content.split("\n\n"):
            if para_text.strip():
                doc.add_paragraph(para_text.strip())

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path
