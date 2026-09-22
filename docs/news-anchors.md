# Curated anchors for the third lane

Read by `tce.news.anchors.parse_curated_file` every time the index is rebuilt.

This file holds the anchors that **cannot be derived**. Repos come from commit
evidence, vendors from env keys and model ids from settings values, all
automatically. What is left is the two kinds a machine has no way to know:
capabilities Ziv cares about by name, and vendors he runs that never appear in a
config file on this box.

The two remaining anchor kinds, `client_solution` and `problem_pattern`, are
**not** here. They are standing facts, written to the database by
`scripts/seed_standing_facts.py` so they are citable by a candidate. An anchor
that cannot be cited cannot satisfy the non-news citation rule, which is the one
rule the whole lane rests on.

## Format

`## <anchor kind>` then `- <term>` bullets. Everything else is prose and is
ignored, so explain yourself freely. A `  # comment` after a term is stripped.

Keep terms **specific**. A single stop word ("ai", "agent", "automation",
"platform") is rejected at build time, because a match on the category name is a
coincidence rather than a connection. Phrases are fine and better: "prompt
caching" earns its place, "caching" does not.

## capability

- prompt caching
- computer use
- model context protocol
- mcp server
- subscription limits
- rate limits
- context window
- function calling
- structured outputs
- vision input
- voice agents
- realtime voice
- speech to text
- diarization
- webhooks
- batch processing
- fine tuning
- model deprecation
- data retention
- terms of service

## vendor

Vendors Ziv runs that no env key on this box names. Everything with a
`TCE_*_API_KEY` is derived automatically and does not belong here.

- whatsapp business
- meta business
- retell
- twilio
- stripe
- vercel
- supabase
- cloudflare
- google workspace
- freshdesk
- 17hats
- dubsado
- zoho
- smpl
- anthropic
- claude code
