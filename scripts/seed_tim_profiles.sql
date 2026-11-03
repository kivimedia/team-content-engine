-- Tim Huckabee's creator, voice and brand profiles for his TCE workspace (03-Nov-2026).
-- These models carry no workspace column in the ORM, so client profiles are seeded by SQL
-- (POST /profiles/* writes a NULL workspace). Idempotent: a second run inserts nothing.
-- Sources: his own words in the 21 Prosperity Path group coaching sessions (verbatim lines
-- only), his 21-Oct and 22-Oct calls with Ziv, theprofitableflorist.com.
-- Run: docker exec -i tce-db psql -U tce -d tce -v ON_ERROR_STOP=1 < scripts/seed_tim_profiles.sql

begin;

insert into creator_profiles (id, creator_name, source_urls, style_notes, allowed_influence_weight,
                              top_patterns, workspace_id, created_at, updated_at)
select gen_random_uuid(), 'Tim Huckabee', array['https://theprofitableflorist.com/'],
  $q$Tim Huckabee is the head coach of The Profitable Florist. In his own words he has been doing this for 30 years (21-Oct-2026 call), and he coaches retail flower shop owners, managers and staff across the US and Canada. He teaches through his courses (15 Minute Florist classes, mystery shopper calls, the Profitable Florists Club, TOTAL Training Sales Boot Camp, the Prosperity Path group coaching) and on site at shops, and he runs a Facebook group of about 6,000 florists. He worked at a high-end New York flower shop, grew up in Southern Connecticut and lives in Amsterdam, moving between Europe and the US. Video content has three lanes: From your courses (one lesson from his own courses), From the coaching room (questions he answers from his own coaching memory) and Smart ideas from other shops (a clever idea from a small business outside the flower trade, and what a florist can take from it). Films short vertical videos on his phone, one sentence at a time, one to two minutes once edited.$q$,
  0.2,
  array['Says the rule plainly, then gives the exact words to say on the phone',
        'Turns a florist''s fear into a number or a step',
        'Borrows a comparison from another kind of business',
        'Dry humor, a little edge, never at a customer''s expense'],
  '34944494-e003-4852-bc69-de7607bcbdb0', now(), now()
where not exists (select 1 from creator_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0');

insert into founder_voice_profiles (id, vocabulary_signature, sentence_rhythm_profile, values_and_beliefs,
                                    metaphor_families, tone_range, taboos, recurring_themes, humor_type,
                                    workspace_id, created_at, updated_at)
select gen_random_uuid(),
  $j${
 "language": "en",
 "phrases": [
  "talk about taking candy from a baby",
  "milking the clock",
  "Hail Mary moves",
  "kind of a hot mess",
  "a rolling advertisement for your store",
  "maybe we're not the flower shop for you today",
  "your cooler is a store within a store",
  "we are literally throwing away our profits",
  "it's my way or the highway",
  "grow your freedom",
  "the sky is always falling, the store is always on fire",
  "discount drift",
  "it's baby steps, but it's about you taking ownership",
  "If I'm out for a week, what breaks?"
 ],
 "samples": [
  "We want the customer to have a great experience, but there are times when we have to kind of let the customer know diplomatically that this isn't possible or that goes contrary to the rules or this is what we need to do.",
  "I've talked to too many flower shops who aren't charging enough for Valentine's Day flowers because their concern is, well, I'm going to be priced out of the market, or I can't compete with the grocery stores.",
  "Your cooler is a store within a store. And when a customer comes in and they look at your cooler, they draw a lot of conclusions, they make a lot of assumptions.",
  "I see some stores that have 70% walk-in, some that have 5% all over the map. My feeling is regardless, you can move the needle.",
  "Yes, we believe that the walls are going to come tumbling down if that person isn't there, and my response is, God forbid if they were hit by a bus, are you going to close the store?",
  "We want you to be able to learn new strategies that are going to help you to boost your sales, improve service and make your store and your team more efficient because the more efficient you are, the more prosperous you are.",
  "Let's all maybe give that flower a little attention pause before you immediately throw something in the garbage, because this shows you that we are literally throwing away our profits.",
  "And I would argue that they may be walking out with the 75 because they didn't buy the 125."
 ],
 "avoided_words": [
  "hacks",
  "crush it",
  "insane",
  "you won't believe",
  "secret",
  "game changer"
 ]
}$j$::jsonb,
  $j${"register": "direct, warm, practical spoken American English", "avg_length": "short", "variation": "medium",
      "pauses": "a beat before the rule, then the words to say"}$j$::jsonb,
  array[$a$An owner should be able to step away from the shop. A team that runs well without her is part of being prosperous, as important as making more money.$a$,
        $a$Charge what you need to cover your costs and make your profit. Do not shrink your markup out of fear, not on Valentine's Day and not when wholesale prices spike.$a$,
        $a$Price options need real gaps between them. A higher option makes the middle one feel safe, so offering it helps sales even when few people pick it.$a$,
        $a$Give every customer a great experience, but the customer is not always right. Say no politely, offer a solution instead of a lecture, and leave the door open.$a$,
        $a$Procedures only work if the owner manages them. Write them down, put them where they are used, review them often, and do not tolerate staff who ignore the policy.$a$,
        $a$Track it or it did not happen. Set baselines, put a call to action on every piece of marketing, and measure what comes back.$a$,
        $a$Waste is lost profit. Look at what is thrown out, price from today's costs, and buy with the numbers in front of you.$a$,
        $a$Change comes in small steps and incrementally, and the owner has to take ownership of it. Staff watch what the owner does.$a$],
  array[$a$Retail space as a store within a store (the cooler)$a$,
        $a$Fire and sparks: the store is always on fire, getting an ember going, a slow burn$a$,
        $a$A branded van as a rolling advertisement$a$,
        $a$Signs and procedures turning into wallpaper$a$,
        $a$Everyday comparisons from other businesses: a bookstore staff favorite shelf, the counter at a shipping company, a fast food cashier$a$],
  $j${"playful": 4, "serious": 5, "vulnerable": 3, "provocative": 4}$j$::jsonb,
  array['Never invent a story, a shop, an owner, a customer, a quote or a number',
        'Never name the shops he coaches, their owners, their staff or their customers',
        'Never his own fees',
        'No politics, elections, war, crime or tragedy',
        'No call to action'],
  array[$a$Phone sales: card message first, no budget question, reminder and follow-up calls$a$,
        $a$Price points, upgrades and the Cooler Magic idea of a cooler that is always full$a$,
        $a$Add-ons and celebration designs to raise average order value$a$,
        $a$Staff: hiring designers, accountability, pay against responsibility, procedures$a$,
        $a$Customer service, complaints and online reviews$a$,
        $a$Marketing, branding, a marketing budget and tracking results$a$,
        $a$Holiday planning, especially Valentine's Day, Thanksgiving and Christmas$a$,
        $a$Controlling costs: cost of goods, labor percent, waste, discount drift$a$,
        $a$Out-of-town and wire orders, and building loyalty with outbound orders$a$,
        $a$Owner freedom, time and not being the only one who can run the shop$a$],
  $a$Dry and self-deprecating with a little edge (joking about his own chins in photos, 'dating myself', 'throw you under the bus').$a$,
  '34944494-e003-4852-bc69-de7607bcbdb0', now(), now()
where not exists (select 1 from founder_voice_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0');

insert into brand_profiles (id, creator_profile_id, name, description, workspace_id, created_at, updated_at)
select gen_random_uuid(),
  (select id from creator_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0' limit 1),
  'Tim Huckabee - The Profitable Florist',
  $q$Coaching and training for retail flower shops: 15 Minute Florist classes, mystery shopper calls, the Profitable Florists Club, TOTAL Training Sales Boot Camp and the Prosperity Path. Site: theprofitableflorist.com. Content language: English (US).$q$,
  '34944494-e003-4852-bc69-de7607bcbdb0', now(), now()
where not exists (select 1 from brand_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0');

select 'creator', count(*) from creator_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0'
union all select 'voice', count(*) from founder_voice_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0'
union all select 'brand', count(*) from brand_profiles where workspace_id = '34944494-e003-4852-bc69-de7607bcbdb0';

commit;
