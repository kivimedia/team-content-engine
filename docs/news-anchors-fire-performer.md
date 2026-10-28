# Curated anchors for a fire-performer workspace (Brant Matthews, the Fire Guy)

Read by `tce.news.anchors.build_anchor_index` for any workspace whose lane profile
is `fire_performer` (TCE_WORKSPACE_LANE_PROFILES). For those workspaces this file
REPLACES `news-anchors.md`, and the anchors derived from this box's settings and
repos (Ziv's vendors, model ids, Kivi repos) are not built at all. Owner workspaces
never read this file.

Format is the same as `news-anchors.md`: `## <anchor kind>` then `- <term>`.
Matching is whole-word on the normalised title and summary, so plurals are listed
on purpose ("daredevil" does not match "daredevils").

`client_solution` is a strong kind: one hit is enough. Here it means a feat his
"Taming the Fire" lane follows: a world record, a daredevil, a stunt, a fire act.
`problem_pattern` needs two independent hits, so it holds the broad words that
only count together.

Never add a bare "fire", "flame", "record" or "records" as an anchor of either
kind: "wildfire", "house fire", "record heat" and "record jackpot" are disaster,
weather and lottery headlines, which never belong in his lane. Never add a bare
place or a person's name. Every strong term has a standing fact of the same kind
in scripts/seed_brant_lanes.py (a test enforces it).

## client_solution
- guinness world record
- guinness world records
- world record holder
- world record attempt
- breaks world record
- breaks the world record
- broke the world record
- sets world record
- sets a world record
- set a world record
- new world record
- fire breather
- fire breathing
- fire eater
- fire eating
- fire performer
- fire performers
- fire juggler
- fire juggling
- fire dancer
- fire show
- daredevil
- daredevils
- stuntman
- stuntwoman
- stunt performer
- stunt performers
- stunt rider
- motorcycle jump
- wall of death
- tightrope walker
- tightrope walk
- high wire
- highwire
- wingsuit
- base jumper
- base jumping
- free solo
- free soloist
- human cannonball
- sword swallower
- escape artist
- circus performer

## problem_pattern
- world record
- stunt
- stunts
- daring
- fearless
- feat
- feats
- danger
- dangerous
- flames
- circus
- juggler
- juggling
- acrobat
- acrobats
- jump
