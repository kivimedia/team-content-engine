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
REVISE_JOB = "video_post_revise"

# 26-Sep: "I dont see TJ use CTAs on the posts. I want to build an audience without
# asking anyone for anything." His rules until he writes his own on the Settings page.
DEFAULT_POST_RULES = (
    "No call to action, ever. Never ask the reader for anything: no booking link, no "
    "'book a call', no 'comment below', no 'DM me', no 'follow for more', no 'link in bio', "
    "no 'share this'. Give the idea and stop. Build the audience by being worth following."
)
AGENT_NAME = "video_publisher"
PROMPT_VERSION = "post-copy-v2"

SKILLS = {
    "instagram": "schedule-insta-post-skill",
    "facebook": "schedule-fb-page-post-skill",
    "youtube": "schedule-youtube-short-skill",
    "linkedin": "schedule-linkedin-post-skill",
}

# His writing rules: never an em or en dash, a plain hyphen instead.
_DASHES = re.compile("[–—]")


def spoken_text(
    words: list[dict[str, Any]], keep: list[list[float]], kept: list[dict[str, Any]] | None = None
) -> str:
    """What he actually says in the edited video, in order.

    `kept` is the plan's own list of kept words (28-Sep): the cut follows the audio, so
    a kept word's recogniser midpoint can sit in trimmed silence and must not be lost.
    """
    if kept:
        indices = {int(w["index"]) for w in kept if "index" in w}
        return " ".join(
            str(w["text"]) for i, w in enumerate(words) if i in indices and not w.get("sound")
        )
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
    "voice. Never use an em dash or en dash; use a plain hyphen. No emojis. HIS POST RULES "
    "(given with the video) come first and override anything below. House style per platform:\n"
    "- instagram.caption: a hook line, short paragraphs or a short numbered list, then two "
    "lines each containing a single '.', then 5-8 lowercase hashtags.\n"
    "- facebook.message: the fullest version, short paragraphs. No hashtags.\n"
    "- youtube.title: under 60 characters, the idea not clickbait. youtube.description: one or "
    "two sentences, a blank line, 3-5 hashtags including #shorts. youtube.tags: 5-8 plain "
    "tags, the last one 'shorts'.\n"
    "- linkedin.message: professional, short paragraphs, no hashtags in the text. "
    "linkedin.hashtags: 3-5 CamelCase words without '#'."
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


def copy_prompt(title: str, spoken: str, rules: str, script_posts: dict[str, str]) -> str:
    ref = "\n\n".join(
        f"{k} (written from the script BEFORE he recorded - use only for tone, not content):\n{v}"
        for k, v in script_posts.items()
        if v
    )
    return (
        f"His post rules (obey exactly):\n{rules}\n\nVideo topic: {title}\n\n"
        f"What he says in the edited video:\n{spoken}\n\n{ref}".strip()
    )


REVISE_SUFFIX = (
    "\n\nYou are REVISING posts he already has. Apply his change request to every post "
    "given, keep everything he did not ask to change, and still obey his post rules. Return "
    "all four platforms; a platform marked 'already out' is returned unchanged."
)
REVISE_SYSTEM = COPY_SYSTEM + REVISE_SUFFIX


# ---------------------------------------------------------------------------
# A client workspace (5-Oct, Matan): his own four platforms, in his voice and his
# language. TCE never posts these for him: the schedule-* skills on this server post to
# the owner's accounts. He copies the post and posts it from his own.

CLIENT_PLATFORMS = ("instagram", "facebook", "youtube", "tiktok")
LABELS["tiktok"] = "TikTok"
CLIENT_PROMPT_VERSION = "post-copy-client-v1"

# Hard limits per platform, applied in code after the model.
LIMITS = {
    "instagram": {"chars": 2200, "hashtags": 10},
    "facebook": {"chars": 5000, "hashtags": 3},
    "youtube_title": 95,
    "youtube_description": {"chars": 5000, "hashtags": 5},
    "tiktok": {"chars": 2200, "hashtags": 5},
}
_HASHTAG = re.compile(r"(?<![\w#])#[\w֐-׿]+")


def platforms_for(persona: Any = None) -> tuple[str, ...]:
    return PLATFORMS if persona is None else CLIENT_PLATFORMS


def copy_system(persona: Any = None) -> str:
    """COPY_SYSTEM for an owner workspace; his own rules for a client workspace."""
    if persona is None:
        return COPY_SYSTEM
    he = getattr(persona, "language", "en") == "he"
    lang = (
        "Write in natural spoken Israeli Hebrew, the way he talks to a friend - never "
        "translated, never formal. Hashtags may be Hebrew or English. "
        if he
        else ""
    )
    return (
        f"You write the social posts for {persona.name}'s walk-and-talk videos. Write from what "
        "he SAYS in the video - never add examples, events, audiences, numbers or claims he did "
        "not say, and never write anything as something that happened to him unless he says it "
        "in the video. Plain, direct, first person, his voice. " + lang + "Never explain, "
        "hint at or guess how an effect is done. Never mention money, prices, leads or "
        "clients by name, and never mock another performer. Never use an em dash or en dash; "
        "use a plain hyphen. HIS POST RULES (given with the video) come first and override "
        "anything below.\n\n"
        f"{persona.voice_block()}\n\n"
        "House style per platform:\n"
        "- instagram.caption: a hook line, then 2-5 short lines, then 5-10 hashtags on the last "
        f"line. At most {LIMITS['instagram']['chars']} characters.\n"
        "- facebook.message: the fullest version for his Facebook page, short paragraphs, at "
        f"most {LIMITS['facebook']['hashtags']} hashtags (none is fine).\n"
        "- youtube.title: under 60 characters, the idea not clickbait. youtube.description: one "
        "or two sentences, a blank line, 3-5 hashtags including #shorts. youtube.tags: 5-8 "
        "plain tags, the last one 'shorts'.\n"
        "- tiktok.caption: one or two short punchy lines (under 150 characters before the "
        "hashtags), then 3-5 hashtags."
    )


def revise_system(persona: Any = None) -> str:
    return REVISE_SYSTEM if persona is None else copy_system(persona) + REVISE_SUFFIX


def copy_schema(persona: Any = None) -> dict[str, Any]:
    if persona is None:
        return COPY_SCHEMA
    import copy

    props = {p: copy.deepcopy(COPY_SCHEMA["properties"][p]) for p in ("instagram", "facebook", "youtube")}
    props["tiktok"] = {"type": "object", "properties": {"caption": {"type": "string"}}, "required": ["caption"]}
    return {"type": "object", "properties": props, "required": list(CLIENT_PLATFORMS)}


def _cap_hashtags(text: str, most: int) -> str:
    """Keep the first `most` hashtags; the rest are taken out with their space."""
    seen = 0

    def keep(m: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= most else ""

    out = _HASHTAG.sub(keep, text)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _cap(text: str, limit: dict[str, int]) -> str:
    text = _cap_hashtags(text, limit["hashtags"])
    return text[: limit["chars"]].rstrip()


def clean_client_copy(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A client workspace's four posts, each held to its platform's limits."""
    base = clean_copy(raw)
    tt = raw.get("tiktok") or {}
    out = {
        "instagram": {"caption": _cap(base["instagram"]["caption"], LIMITS["instagram"])},
        "facebook": {"message": _cap(base["facebook"]["message"], LIMITS["facebook"])},
        "youtube": {
            "title": base["youtube"]["title"][: LIMITS["youtube_title"]],
            "description": _cap(base["youtube"]["description"], LIMITS["youtube_description"]),
            "tags": base["youtube"]["tags"][:8],
        },
        "tiktok": {"caption": _cap(_DASHES.sub("-", str(tt.get("caption") or "")).strip(), LIMITS["tiktok"])},
    }
    return out


def copy_problems(copies: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Per platform, what in a client's post breaks one of his rules in code: a
    method explained. The card shows it; nothing is posted by TCE anyway."""
    from tce.editorial.lane_profile import _METHOD_REVEAL

    out: dict[str, str] = {}
    for platform, fields in copies.items():
        text = " ".join(str(v) for v in fields.values() if isinstance(v, str))
        hit = _METHOD_REVEAL.search(text)
        if hit:
            out[platform] = f"Check before posting: it talks about how an effect is done ('{hit.group(0)}')"
    return out


def revise_prompt(
    title: str, spoken: str, rules: str, current: dict[str, dict[str, Any]],
    locked: list[str], request: str,
) -> str:
    import json

    lines = [
        f"His change request:\n{request.strip()}",
        f"His post rules (obey exactly):\n{rules}",
        f"Video topic: {title}",
        f"What he says in the edited video:\n{spoken}",
        "The posts as they are now (JSON):\n" + json.dumps(current, ensure_ascii=False, indent=1),
    ]
    if locked:
        lines.append("Already out, return unchanged: " + ", ".join(locked))
    return "\n\n".join(lines)


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
        "tiktok": ("caption",),
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
    if platform == "linkedin" and not at_iso:
        # 27-Sep: the skill's `publish` calls kmboards /api/linkedin/one-off-publish-now,
        # which does not exist (404) - LinkedIn failed while the other three went out.
        # `schedule --at now` uses the route that exists; kmboards' LinkedIn publisher
        # posts it within about five minutes.
        verb = ["schedule", "--at", "now"]
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
