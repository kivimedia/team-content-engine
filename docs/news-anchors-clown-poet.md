# Curated anchors for a clown-poet workspace (Christopher Gamble)

Read by `tce.news.anchors.build_anchor_index` for any workspace whose lane profile
is `clown_poet` (TCE_WORKSPACE_LANE_PROFILES). For those workspaces this file
REPLACES `news-anchors.md`, and the anchors derived from this box's settings and
repos (Ziv's vendors, model ids, Kivi repos) are not built at all. Owner workspaces
never read this file.

Format is the same as `news-anchors.md`: `## <anchor kind>` then `- <term>`.
Matching is whole-word on the normalised title and summary, so plurals are listed
on purpose ("artist" does not match "artists").

`client_solution` is a strong kind: one hit is enough. Here it means a story his
"Living a Creative Life" lane follows: creativity and play, a hobby or amateur
artist, art therapy, a clown or a street performer, a typewriter or a poetry event,
a community or public art project. `problem_pattern` needs two independent hits, so
it holds the broad art words that only count together ("a festival" plus "clowns").

Never add a bare "play", "kids", "parents" or "mental health" as an anchor of either
kind: sports, school and health headlines would fill the 10 appraisals a day. Never add
a bare place or a person's name. Every term of either kind has a standing fact of the
same kind in scripts/seed_chris_lanes.py (a test enforces it).

## client_solution
- creativity
- creative life
- creative block
- unstructured play
- free play
- imaginative play
- playfulness
- calgary arts development
- hobby artist
- hobby artists
- amateur artist
- amateur artists
- self-taught artist
- art class
- art classes
- live painting
- art therapy
- clowning
- clown school
- physical theatre
- street performer
- street performers
- busker
- buskers
- fringe festival
- typewriter
- typewriters
- typewriter poet
- typewriter poetry
- poet laureate
- poetry reading
- poetry festival
- open mic
- community art
- community arts
- community art project
- public art
- public art project

## problem_pattern
- artist
- artists
- art
- arts
- exhibition
- creative
- imagination
- painting
- painter
- studio
- hobby
- clown
- clowns
- circus
- theatre
- theater
- festival
- poem
- poems
- poetry
- poet
