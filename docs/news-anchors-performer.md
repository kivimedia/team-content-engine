# Curated anchors for a performer workspace (Matan)

Read by `tce.news.anchors.build_anchor_index` for any workspace whose lane profile
is `performer` (TCE_WORKSPACE_LANE_PROFILES). For those workspaces this file
REPLACES `news-anchors.md`, and the anchors derived from this box's settings and
repos (twilio, vercel, zoho, model ids, Kivi repos) are not built at all: those
are Ziv's vendors, not a mentalist's. Owner workspaces never read this file.

Format is the same as `news-anchors.md`: `## <anchor kind>` then `- <term>`.
Matching is whole-word on the normalised title and summary, so plurals are listed
on purpose ("trade show" does not match "trade shows").

`client_solution` is a strong kind: one hit is enough. Here it means what he
performs and where he performs it. `problem_pattern` needs two independent hits,
so it holds the broad event words that only count together.

Never add a bare "magic", "illusion", "show", "event" or "party": "Six Flags Magic
Mountain solar carport" and "magic of autumn decor" are exactly the junk they let
in. Name the craft ("magician", "magic show") or the event ("bar mitzvah").
Never add a bare place ("israel", "tel aviv"): alone they match war and politics
headlines, which never belong in his trend lane. Holiday names (Hanukkah, Purim)
are his busy corporate season, but alone they are recipes and candle-lighting
times, so they live in `problem_pattern` and count only next to a second hit.

## client_solution

- mentalist
- mentalists
- mentalism
- magician
- magicians
- illusionist
- illusionists
- magic trick
- magic tricks
- magic show
- magic shows
- close up magic
- closeup magic
- card trick
- card tricks
- sleight of hand
- mind reading
- mind reader
- penn teller
- penn and teller
- derren brown
- david blaine
- david copperfield
- uri geller
- lior suchard
- oz pearlman
- shin lim
- max maven
- banachek
- asi wind
- magic castle
- bar mitzvah
- bat mitzvah
- bar mitzvahs
- bat mitzvahs
- b nai mitzvah
- mitzvah
- corporate event
- corporate events
- company event
- company events
- corporate entertainment
- team building
- holiday party
- holiday parties
- office party
- event entertainment
- live entertainment
- interactive entertainment
- immersive experience
- immersive experiences
- immersive entertainment
- wedding entertainment
- wedding trends
- wedding trend
- reception entertainment
- trade show
- trade shows
- brand activation
- brand activations
- booth activation
- experiential marketing
- ai at events
- קוסם
- קוסמים
- מנטליסט
- מנטליזם
- קסמים
- בר מצווה
- בת מצווה
- אירוע חברה
- אירועי חברה
- ערב גיבוש

## problem_pattern

Tuned on a 240-item sample of his 11 feeds (5-Oct). Words like "wedding",
"guests", "planners", "celebration", "party", "engagement", "activation" and
"conference" were tried and removed: any two of them let in every wedding
photo gallery, a recruitment-history post and a company's "new website" note.
What is left are words about the guest experience itself.

- entertainment
- entertainer
- entertainers
- performer
- performers
- guest experience
- guest experiences
- attendee experience
- audience engagement
- interactive
- immersive
- gala
- hanukkah
- chanukah
- purim
- חנוכה
- פורים
