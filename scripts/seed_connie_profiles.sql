-- Connie Kadansky's creator, voice and brand profiles for her TCE workspace (23-Oct-2026).
-- These models carry no workspace column in the ORM, so client profiles are seeded by SQL
-- (POST /profiles/* writes a NULL workspace). Idempotent: a second run inserts nothing.
-- Sources: her 22-Oct call with Ziv, her "Pleasing or Leading the Prospect" document
-- (verbatim lines), exceptionalsales.com (page titles and summaries).
-- Run: docker exec -i tce-db psql -U tce -d tce -v ON_ERROR_STOP=1 < scripts/seed_connie_profiles.sql

begin;

insert into creator_profiles (id, creator_name, source_urls, style_notes, allowed_influence_weight,
                              top_patterns, workspace_id, created_at, updated_at)
select gen_random_uuid(), 'Connie Kadansky', array['https://exceptionalsales.com/'],
  $q$Connie Kadansky, Exceptional Sales Performance (exceptionalsales.com), a US sales coach. She helps salespeople, sales managers and coaches get past Sales Call Reluctance (the emotional hesitation to prospect and self-promote) and lead a sales conversation instead of pleasing the prospect. Offers the SPQ*Gold assessment. Teaches negotiation on sales calls in her own words: name the feeling, sum it up, ask what or how. Runs the Dojo, where reps practice out loud with AI buyers. Video content has three lanes: from her teaching, from the practice room (questions she answers from her own memory) and negotiation in the wild (a real negotiation in the news and what it teaches a rep). Films walk-and-talk, one sentence at a time, short sentences, like a friendly chat over coffee.$q$,
  0.2,
  array['Names what the other person feels before asking a question ("Sounds like...")',
        'Asks what and how questions instead of pitching',
        'Short, plain lines a busy person can follow',
        'Contrasts the pleaser line with the leader line'],
  '7247b8fa-d627-4357-b6e8-ca2a26cd4b14', now(), now()
where not exists (select 1 from creator_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14');

insert into founder_voice_profiles (id, vocabulary_signature, sentence_rhythm_profile, values_and_beliefs,
                                    metaphor_families, tone_range, taboos, recurring_themes, humor_type,
                                    workspace_id, created_at, updated_at)
select gen_random_uuid(),
  $j${"language": "en",
      "phrases": ["Sounds like...", "Whose comfort is driving the conversation?", "respectful tension",
                  "get curious about what is underneath", "counterfeit yes", "get your ask in gear",
                  "It's not laziness. It's psychology.", "Oh, this is so good.", "That's awesome!"],
      "samples": ["Salespeople with Yielder Call Reluctance respond to the Prospect's statement. The sales leader gets curious about what is underneath the statement.",
                  "Sales Call Reluctance is nothing to be embarrassed about. Allowing it to persist needlessly is.",
                  "Sounds like this is a demanding week.",
                  "What is taking priority on your job sites right now?",
                  "Sounds like the number is higher than you expected.",
                  "What are you comparing it with?",
                  "Of course. What part of the decision still needs more thought?",
                  "Happy to send it. What question would you want the information to answer?"],
      "avoided_words": ["pushy closing tricks", "hacks", "crush it"]}$j$::jsonb,
  $j${"register": "warm, direct spoken American English", "avg_length": "short", "variation": "medium",
      "pauses": "a deliberate pause after naming a feeling"}$j$::jsonb,
  array['Leading a customer means helping them think clearly, make a good decision and take action, even when that takes respectful tension',
        'Pleasing a customer keeps them comfortable and keeps your approval, and it costs the sale',
        'Sales Call Reluctance is learned, so it can be unlearned with conscious effort and good coaching',
        'Reading about a skill is not doing it: people get better by practicing out loud',
        'Sales is not only what we do, it is who we believe we are when we do it'],
  array['pleasing versus leading', 'whose comfort is driving the conversation',
        'the counterfeit yes', 'the self-critical inner voice'],
  $j${"playful": 4, "serious": 6, "vulnerable": 5, "provocative": 4}$j$::jsonb,
  array['Never name her clients, their companies or their reps',
        'Never her own fees or pricing',
        'Never invent a story, a rep, a quote or a number',
        'Never use Chris Voss''s brand terms as her own',
        'No politics, elections, war, crime or tragedy',
        'No call to action'],
  array['Sales Call Reluctance', 'the Yielder who wants to be liked', 'pleasing or leading the prospect',
        'naming the feeling', 'prospecting without fear', 'practicing out loud'],
  'warm and light, never at anyone''s expense',
  '7247b8fa-d627-4357-b6e8-ca2a26cd4b14', now(), now()
where not exists (select 1 from founder_voice_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14');

insert into brand_profiles (id, creator_profile_id, name, description, workspace_id, created_at, updated_at)
select gen_random_uuid(),
  (select id from creator_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14' limit 1),
  'Connie Kadansky - Exceptional Sales Performance',
  $q$Sales Call Reluctance and negotiation coach for salespeople, sales managers and coaches. Site: exceptionalsales.com. Content language: English (US).$q$,
  '7247b8fa-d627-4357-b6e8-ca2a26cd4b14', now(), now()
where not exists (select 1 from brand_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14');

select 'creator', count(*) from creator_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14'
union all select 'voice', count(*) from founder_voice_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14'
union all select 'brand', count(*) from brand_profiles where workspace_id = '7247b8fa-d627-4357-b6e8-ca2a26cd4b14';

commit;
