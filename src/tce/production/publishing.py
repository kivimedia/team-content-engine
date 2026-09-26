"""TCE publishes the edited video itself: post copy, the four platforms, the live links.

26-Sep: "I want tce to be able to do the full publishing and to show me the post in
the library". The copy is written on the subscription (job `video_post_copy`) from what
he actually says in the edit - not from the script, which on the first walk used a
car-rental example he never said. He reads and edits it on the Library card; his tap
posts through the schedule-* skills already on this server (one tested path per
platform, no new Meta/YouTube/LinkedIn API code).

This module is pure where it can be: prompt, schema, validation, the exact command per
platform and reading the result back. The router owns the background work.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tce.production.retakes import map_to_edit

PLATFORMS = ("instagram", "facebook", "youtube", "linkedin")
LABELS = {
    "instagram": "Instagram Reel",
    "facebook": "Facebook Page",
    "youtube": "YouTube Short",
    "linkedin": "LinkedIn",
}
COPY_JOB = "video_post_copy"
AGENT_NAME = "video_publisher"
PROMPT_VERSION = "post-copy-v1"

SKILLS = {
    "instagram": "schedule-insta-post-skill",
    "facebook": "schedule-fb-page-post-skill",
    "youtube": "schedule-youtube-short-skill",
    "linkedin": "schedule-linkedin-post-skill",
}

# His writing rules: never an em or en dash, a plain hyphen instead.
_DASHES = re.compile("[–—]")


def spoken_text(words: list[dict[str, Any]], keep: list[list[float]]) -> str:
    """What he actually says in the edited video, in order."""
    out = []
    for w in words:
        mid = (float(w["start_s"]) + float(w["end_s"])) / 2
        if map_to_edit(mid, keep) is not None:
            out.append(str(w["text"]))
    return " ".join(out)


COPY_SYSTEM = (
    "You write the social posts for Ziv Raviv's walking videos (he coaches event-business "
    "owners and coaches on growing their business). Write from what he SAYS in the video - "
    "never add examples, numbers or claims he did not say. Plain, direct, first person, his "
    "voice. Never use an em dash or en dash; use a plain hyphen. No emojis. End every post "
    "with the booking line using the booking link given. House style per platform:\n"
    "- instagram.caption: a hook line, short paragraphs or a short numbered list, the "
    "booking line, then two lines each containing a single '.', then 5-8 lowercase hashtags.\n"
    "- facebook.message: the fullest version, short paragraphs, booking line with the link. "
    "No hashtags.\n"
    "- youtube.title: under 60 characters, the idea not clickbait. youtube.description: one or "
    "two sentences, a blank line, 'Book 15 minutes with Ziv: <link>', a blank line, 3-5 "
    "hashtags including #shorts. youtube.tags: 5-8 plain tags, the last one 'shorts'.\n"
    "- linkedin.message: professional, short paragraphs, booking line with the link, no "
    "hashtags in the text. linkedin.hashtags: 3-5 CamelCase words without '#'."
)

COPY_SCHEMA = {
    "type": "object",
    "properties": {
        "instagram": {"type": "object", "properties": {"caption": {"type": "string"}}, "required": ["caption"]},
        "facebook": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        "youtube": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "description", "tags"],
        },
        "linkedin": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["message", "hashtags"],
        },
    },
    "required": list(PLATFORMS),
}


def copy_prompt(title: str, spoken: str, booking_url: str, script_posts: dict[str, str]) -> str:
    ref = "\n\n".join(
        f"{k} (written from the script BEFORE he recorded - use only for tone, not content):\n{v}"
        for k, v in script_posts.items()
        if v
    )
    return (
        f"Video topic: {title}\nBooking link: {booking_url}\n\n"
        f"What he says in the edited video:\n{spoken}\n\n{ref}".strip()
    )


def clean_copy(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Keep only the fields each platform takes, with his dash rule applied."""

    def text(value: Any) -> str:
        return _DASHES.sub("-", str(value or "")).strip()

    out: dict[str, dict[str, Any]] = {}
    ig = raw.get("instagram") or {}
    out["instagram"] = {"caption": text(ig.get("caption"))}
    fb = raw.get("facebook") or {}
    out["facebook"] = {"message": text(fb.get("message"))}
    yt = raw.get("youtube") or {}
    tags = [text(t).lstrip("#") for t in (yt.get("tags") or []) if text(t)]
    out["youtube"] = {
        "title": text(yt.get("title"))[:95],
        "description": text(yt.get("description")),
        "tags": tags[:12],
    }
    li = raw.get("linkedin") or {}
    out["linkedin"] = {
        "message": text(li.get("message")),
        "hashtags": [text(h).lstrip("#").replace(" ", "") for h in (li.get("hashtags") or []) if text(h)][:6],
    }
    return out


def missing(platform: str, copy: dict[str, Any]) -> str | None:
    """Why this copy cannot be posted yet, or None."""
    need = {
        "instagram": ("caption",),
        "facebook": ("message",),
        "youtube": ("title", "description"),
        "linkedin": ("message",),
    }[platform]
    empty = [k for k in need if not str(copy.get(k) or "").strip()]
    return f"{LABELS[platform]} has no {', '.join(empty)}" if empty else None


def command(
    platform: str,
    copy: dict[str, Any],
    *,
    media_path: str,
    media_url: str,
    at_iso: str | None,
) -> list[str]:
    """The exact CLI call for one platform ('publish' now, or 'schedule --at')."""
    verb = ["schedule", "--at", at_iso] if at_iso else ["publish"]
    base = ["node", "dist/cli.js", *verb]
    if platform == "instagram":
        return [*base, "--type", "reel", "--media", media_path, "--caption", copy["caption"]]
    if platform == "facebook":
        return [*base, "--media", media_path, "--message", copy["message"]]
    if platform == "youtube":
        return [
            *base, "--media", media_path, "--title", copy["title"],
            "--description", copy["description"], "--tags", ",".join(copy.get("tags") or []),
            "--privacy", "public",
        ]
    if platform == "linkedin":
        args = [*base, "--type", "video", "--media", media_url, "--message", copy["message"]]
        if copy.get("hashtags"):
            args += ["--hashtags", ",".join(copy["hashtags"])]
        return args
    raise ValueError(f"unknown platform {platform}")


_PATTERNS = {
    "instagram": re.compile(r"ig_post=(\S+)"),
    "facebook": re.compile(r"fb_post_id=(\S+)"),
    "youtube": re.compile(r"video id=(\S+)"),
    "linkedin": re.compile(r"linkedin_post_id=(\S+)"),
}
_ROW = re.compile(r"(?:Row created: id=|db_id=|post_id=|Scheduled[^\n]*?id=)([0-9a-f-]{8,})")


def read_result(platform: str, stdout: str) -> dict[str, Any]:
    """What a finished CLI run says: the platform's post id and a link to it."""
    m = _PATTERNS[platform].search(stdout or "")
    post_id = m.group(1).strip() if m else None
    if post_id and post_id.startswith("("):  # "(not returned by service)"
        post_id = None
    url = None
    if post_id:
        if platform == "facebook":
            url = f"https://www.facebook.com/{post_id}"
        elif platform == "youtube":
            url = f"https://youtube.com/shorts/{post_id}"
        elif platform == "linkedin":
            url = f"https://www.linkedin.com/feed/update/{post_id}/"
    row = _ROW.search(stdout or "")
    return {"post_id": post_id, "url": url, "row_id": row.group(1) if row else None}


def social_encode_args(src: Path, out: Path) -> list[str]:
    """One upload-sized copy for every platform: Instagram Reels refuse files over
    100 MB, and the edit of a 3-minute walk is ~190 MB (ig-skill-video-flow recipe)."""
    return [
        "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "medium", "-b:v", "2800k", "-maxrate", "3500k",
        "-bufsize", "5000k", "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-map", "0:v:0", "-map", "0:a:0",
        "-movflags", "+faststart", str(out),
    ]
