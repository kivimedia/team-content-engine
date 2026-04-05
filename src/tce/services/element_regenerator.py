"""Element-level regeneration service - regenerate a single element of a post package."""

from __future__ import annotations

import json
import uuid
from typing import Any

import anthropic
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.post_package import PostPackage
from tce.models.story_brief import StoryBrief
from tce.settings import settings

logger = structlog.get_logger()


async def regenerate_element(
    package_id: uuid.UUID,
    element_type: str,
    feedback: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Regenerate a single element of a post package.

    element_type: "facebook_post" | "linkedin_post" | "hook" | "image_0", "image_1", etc.
    feedback: operator's instructions for what to change.

    Returns dict with the updated element value.
    """
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise ValueError(f"Package {package_id} not found")

    # Load story brief for context
    brief_context = ""
    if pkg.brief_id:
        brief = await db.get(StoryBrief, pkg.brief_id)
        if brief:
            brief_context = (
                f"Topic: {brief.topic}\n"
                f"Angle: {brief.angle_type}\n"
                f"Thesis: {brief.thesis}\n"
                f"Audience: {brief.audience}\n"
            )

    api_key = settings.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Store feedback history
    fb_history = pkg.element_feedback or {}
    fb_history[element_type] = feedback
    pkg.element_feedback = fb_history

    result: dict[str, Any] = {"element": element_type, "status": "regenerated"}

    if element_type == "facebook_post":
        result["value"] = await _regen_post(
            client, "Facebook", pkg.facebook_post or "", brief_context, feedback
        )
        pkg.facebook_post = result["value"]

    elif element_type == "linkedin_post":
        result["value"] = await _regen_post(
            client, "LinkedIn", pkg.linkedin_post or "", brief_context, feedback
        )
        pkg.linkedin_post = result["value"]

    elif element_type == "hook":
        result["value"] = await _regen_hooks(
            client, pkg.facebook_post or pkg.linkedin_post or "", brief_context, feedback
        )
        pkg.hook_variants = result["value"]

    elif element_type.startswith("image_"):
        idx = int(element_type.split("_")[1])
        result["value"] = await _regen_image_prompt(
            client, pkg.image_prompts, idx, brief_context, feedback
        )
        pkg.image_prompts = result["value"]

    else:
        raise ValueError(f"Unknown element type: {element_type}")

    await db.commit()
    return result


async def _regen_post(
    client: anthropic.AsyncAnthropic,
    platform: str,
    current_text: str,
    brief_context: str,
    feedback: str,
) -> str:
    """Regenerate a FB or LI post based on feedback."""
    system = (
        f"You are a B2B social media writer for {platform}. "
        "Rewrite the post applying the operator's feedback precisely. "
        "Return ONLY the revised post text - no explanation, no markdown fences."
    )
    user_msg = (
        f"STORY CONTEXT:\n{brief_context}\n\n"
        f"CURRENT {platform.upper()} POST:\n{current_text}\n\n"
        f"OPERATOR FEEDBACK: {feedback}\n\n"
        f"Rewrite the post applying this feedback. Keep the same general structure "
        f"and length unless the feedback says otherwise."
    )
    resp = await client.messages.create(
        model=settings.default_model,  # Sonnet for quality rewrites
        max_tokens=2048,
        temperature=0.5,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text.strip()


async def _regen_hooks(
    client: anthropic.AsyncAnthropic,
    post_text: str,
    brief_context: str,
    feedback: str,
) -> list[str]:
    """Regenerate hook variants based on feedback."""
    system = (
        "You are a B2B social media hook writer. "
        "Generate 5 alternative opening hooks for a post. "
        "Apply the operator's feedback to guide the style. "
        "Return ONLY a JSON array of 5 strings."
    )
    user_msg = (
        f"CONTEXT:\n{brief_context}\n\n"
        f"POST:\n{post_text[:500]}\n\n"
        f"OPERATOR FEEDBACK: {feedback}\n\n"
        f"Generate 5 hooks applying this feedback."
    )
    resp = await client.messages.create(
        model=settings.haiku_model,
        max_tokens=512,
        temperature=0.7,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    try:
        hooks = json.loads(resp.content[0].text.strip())
        if isinstance(hooks, list):
            return [str(h) for h in hooks[:10]]
    except (json.JSONDecodeError, IndexError):
        pass
    return [resp.content[0].text.strip()]


async def _regen_image_prompt(
    client: anthropic.AsyncAnthropic,
    image_prompts: Any,
    index: int,
    brief_context: str,
    feedback: str,
) -> Any:
    """Regenerate a specific image prompt based on feedback."""
    prompts = image_prompts if isinstance(image_prompts, list) else []
    if index >= len(prompts):
        raise ValueError(f"Image index {index} out of range (have {len(prompts)})")

    current = prompts[index]
    system = (
        "You are a creative director for social media visuals. "
        "Revise the image prompt applying the operator's feedback. "
        "Return ONLY a JSON object with: prompt_text, negative_prompt, aspect_ratio, mood."
    )
    user_msg = (
        f"CONTEXT:\n{brief_context}\n\n"
        f"CURRENT PROMPT:\n{json.dumps(current)}\n\n"
        f"FEEDBACK: {feedback}\n\n"
        f"Revise the image prompt."
    )
    resp = await client.messages.create(
        model=settings.haiku_model,
        max_tokens=512,
        temperature=0.5,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    try:
        revised = json.loads(resp.content[0].text.strip())
        if isinstance(revised, dict):
            prompts[index] = {**current, **revised}
    except (json.JSONDecodeError, IndexError):
        prompts[index]["prompt_text"] = resp.content[0].text.strip()

    return prompts
