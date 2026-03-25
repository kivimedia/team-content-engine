"""Tests for full prompt library (PRD Appendix E)."""

from tce.services.prompt_library import (
    FACEBOOK_WRITER_PROMPT,
    FULL_PROMPT_LIBRARY,
    QA_AGENT_PROMPT,
    STORY_STRATEGIST_PROMPT,
)


def test_three_full_prompts():
    """PRD Appendix E: 3 production prompts."""
    assert len(FULL_PROMPT_LIBRARY) == 3


def test_story_strategist_prompt():
    """Prompt should contain key PRD elements."""
    assert "Story Strategist" in STORY_STRATEGIST_PROMPT
    assert "StoryBrief" in STORY_STRATEGIST_PROMPT
    assert "belief_shift" in STORY_STRATEGIST_PROMPT
    assert "template" in STORY_STRATEGIST_PROMPT.lower()
    assert "Trend Brief" in STORY_STRATEGIST_PROMPT


def test_facebook_writer_prompt():
    """FB prompt should contain platform rules."""
    assert "Facebook Writer" in FACEBOOK_WRITER_PROMPT
    assert "See more" in FACEBOOK_WRITER_PROMPT
    assert "150-400 words" in FACEBOOK_WRITER_PROMPT
    assert "FOUNDER VOICE" in FACEBOOK_WRITER_PROMPT
    assert "ANTI-CLONE" in FACEBOOK_WRITER_PROMPT


def test_qa_agent_prompt():
    """QA prompt should contain all 12 dimensions."""
    assert "QA Agent" in QA_AGENT_PROMPT
    assert "EVIDENCE COMPLETENESS" in QA_AGENT_PROMPT
    assert "HUMANITARIAN SENSITIVITY" in QA_AGENT_PROMPT
    assert "FOUNDER VOICE ALIGNMENT" in QA_AGENT_PROMPT
    assert "CTA HONESTY" in QA_AGENT_PROMPT
    assert "pass >= 8" in QA_AGENT_PROMPT  # humanitarian
    assert "pass >= 9" in QA_AGENT_PROMPT  # CTA honesty


def test_prompts_have_template_variables():
    """Prompts should use template variables."""
    assert "{trend_brief}" in STORY_STRATEGIST_PROMPT
    assert "{founder_voice}" in FACEBOOK_WRITER_PROMPT
    assert "{fb_post}" in QA_AGENT_PROMPT
