# Curated anchors for the demo workspace (a fictional wedding emcee and coach)

Read by `tce.news.anchors.build_anchor_index` for any workspace whose lane profile
is `wedding_coach` (TCE_WORKSPACE_LANE_PROFILES). For those workspaces this file
REPLACES `news-anchors.md`, and the anchors derived from this box's settings and
repos (Ziv's vendors, model ids, Kivi repos) are not built at all. Owner workspaces
never read this file.

Format is the same as `news-anchors.md`: `## <anchor kind>` then `- <term>`.
Matching is whole-word on the normalised title and summary, so plurals are listed
on purpose ("wedding planner" does not match "wedding planners").

`client_solution` is a strong kind: one hit is enough. Here it means a story her
"Weddings in the News" lane follows: a wedding trend, a wedding DJ or playlist, what
wedding guests want, a planner or a venue, a small or destination wedding.
`problem_pattern` needs two independent hits, so it holds the broad words that only
count together ("a wedding" plus "a DJ").

Never add "wedding reception", "bride", "groom" or "band" as an anchor of either kind:
celebrity gossip and jewelry round-ups would fill the 10 appraisals a day. Never add a
bare place or a person's name. Every term of either kind has a standing fact of the
same kind in scripts/seed_demo_lanes.py (a test enforces it).

## client_solution
- wedding trend
- wedding trends
- wedding entertainment
- wedding industry
- wedding dj
- wedding djs
- wedding singer
- wedding playlist
- first dance
- wedding guest
- wedding guests
- wedding toast
- wedding speech
- wedding speeches
- wedding planner
- wedding planners
- wedding venue
- wedding venues
- wedding season
- micro wedding
- micro weddings
- destination wedding
- destination weddings

## problem_pattern
- wedding
- weddings
- dj
- djs
- emcee
- emcees
- playlist
- live music
- dance floor
