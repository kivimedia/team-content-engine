# Curated anchors for a florist-coach workspace (Tim Huckabee, The Profitable Florist)

Read by `tce.news.anchors.build_anchor_index` for any workspace whose lane profile
is `florist_coach` (TCE_WORKSPACE_LANE_PROFILES). For those workspaces this file
REPLACES `news-anchors.md`, and the anchors derived from this box's settings and
repos (Ziv's vendors, model ids, Kivi repos) are not built at all. Owner workspaces
never read this file.

Format is the same as `news-anchors.md`: `## <anchor kind>` then `- <term>`.
Matching is whole-word on the normalised title and summary, so plurals are listed
on purpose ("bakery" does not match "bakeries").

`client_solution` is a strong kind: one hit is enough. Here it means a move his
"Smart ideas from other shops" lane follows: a small shop's loyalty idea, a
subscription, a pop-up or an open house, a window display, the owner of a toy shop,
a bakery or a cafe. `problem_pattern` needs two independent hits, so it holds the
broad shop and sales words that only count together ("a bakery" plus "customers").

Never add a bare "sales", "shop", "store", "owner", "business" or "flowers" as a
strong anchor: "sales tax", "store closing", "new owner shutters plants" and
"business news" are chain, tax and layoff headlines, which never belong in his lane.
They live in `problem_pattern` and count only next to a second hit. Never add a bare
place or a person's name. Every term of either kind has a standing fact of the same
kind in scripts/seed_tim_lanes.py (a test enforces it).

## client_solution
- loyalty program
- loyalty programs
- loyalty card
- loyalty cards
- punch card
- punch cards
- rewards program
- subscription box
- subscription boxes
- subscription service
- pop-up shop
- pop-up shops
- holiday open house
- small business saturday
- shop small
- shop local
- window display
- window displays
- repeat customers
- regular customers
- foot traffic
- independent retailer
- independent retailers
- independent bookstore
- independent toy store
- toy store owner
- toy shop owner
- bakery owner
- cafe owner
- coffee shop owner
- restaurant owner
- restaurant owners
- gift shop owner
- boutique owner
- bookstore owner
- garden center owner
- upsell
- upselling

## problem_pattern
- toy store
- toy shop
- bakery
- bakeries
- restaurant
- restaurants
- cafe
- coffee shop
- gift shop
- boutique
- bookstore
- garden center
- small business
- small businesses
- small business owner
- small business owners
- local business
- local businesses
- shop owner
- shop owners
- store owner
- store owners
- business owner
- business owners
- customers
- holiday sales
- holiday shoppers
- add-on
- add-ons
- bundle
- bundles
