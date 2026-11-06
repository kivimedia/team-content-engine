-- The demo creator's creator, voice and brand profiles (06-Nov-2026).
-- Nell Hartwick and Lark & Lantern Entertainment are FICTIONAL, written so product pictures
-- and demo videos never show a real client's workspace. Her lines below were written for
-- this demo; nobody said them.
-- These models carry no workspace column in the ORM, so client profiles are seeded by SQL
-- (POST /profiles/* writes a NULL workspace). Idempotent: a second run inserts nothing.
-- Run: docker exec -i tce-db psql -U tce -d tce -v ON_ERROR_STOP=1 < scripts/seed_demo_profiles.sql

begin;

insert into creator_profiles (id, creator_name, source_urls, style_notes, allowed_influence_weight,
                              top_patterns, workspace_id, created_at, updated_at)
select gen_random_uuid(), 'Nell Hartwick', array[]::text[],
  $q$Nell Hartwick is a wedding emcee and DJ in Richmond, Virginia. She runs Lark & Lantern Entertainment, a small wedding entertainment company, and she coaches other wedding DJs, emcees and bands on how to run a great night. She talks to her phone the way she talks into a microphone: warm, quick and direct, one short line at a time.$q$,
  0.2,
  array['Opens with what the room looks like, then says what it means',
        'Turns a small moment on the dance floor into one thing to do differently',
        'Warm and quick, then direct',
        'Talks to the entertainer watching as if they were setting up next to her'],
  '6e9faea3-412b-4839-90e7-77b67f654808', now(), now()
where not exists (select 1 from creator_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808');

insert into founder_voice_profiles (id, vocabulary_signature, sentence_rhythm_profile, values_and_beliefs,
                                    metaphor_families, tone_range, taboos, recurring_themes, humor_type,
                                    workspace_id, created_at, updated_at)
select gen_random_uuid(),
  $j${
 "language": "en",
 "phrases": [
  "run the room",
  "read the floor",
  "that is information",
  "build the night backward",
  "one team, one timeline",
  "the next person up"
 ],
 "samples": [
  "A great reception is not a playlist. It is a host who reads the room.",
  "Nobody is dancing. That is information.",
  "Ask the couple what they want their guests to feel, then build the night backward.",
  "The planner, the caterer and the photographer are on your team, so talk to them first.",
  "Fewer guests make every moment louder, so the host matters more, not less.",
  "Watch who is on the floor, and watch who is not."
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
  $j${"register": "warm, quick, direct spoken English", "avg_length": "short", "variation": "medium",
      "pauses": "a beat before the line that matters, the way she would on a microphone"}$j$::jsonb,
  array[$a$A great reception is not a playlist. It is a host who reads the room.$a$,
        $a$The dance floor is the measure of the night: who is on it, who is not, who is next.$a$,
        $a$Ask the couple what they want their guests to feel, then build the night backward.$a$,
        $a$A timeline only works when the planner, the caterer and the photographer hear it the same way.$a$,
        $a$Small weddings need a host more than big ones do.$a$],
  array[$a$The microphone: who holds it, when to hand it over$a$,
        $a$The floor: empty, filling, full, the next person up$a$,
        $a$The night as a story with a beginning, a middle and a last song$a$],
  $j${"playful": 4, "serious": 3, "vulnerable": 3, "provocative": 2}$j$::jsonb,
  array['Never invent a story, a person, a quote or a number',
        'Never prices, fees or money',
        'Never a client''s, a venue''s or a guest''s name',
        'No politics, war, crime, tragedy or celebrity gossip',
        'No call to action'],
  array[$a$Reading a room and running a wedding reception$a$,
        $a$Coaching wedding DJs, emcees and bands$a$,
        $a$The craft of a great party$a$,
        $a$What weddings are turning into, and what stays the same$a$],
  $a$Quick and warm, the kind of joke you can make into a microphone with somebody's grandmother listening.$a$,
  '6e9faea3-412b-4839-90e7-77b67f654808', now(), now()
where not exists (select 1 from founder_voice_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808');

insert into brand_profiles (id, creator_profile_id, name, description, workspace_id, created_at, updated_at)
select gen_random_uuid(),
  (select id from creator_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808' limit 1),
  'Nell Hartwick - wedding emcee and coach',
  $q$Lark & Lantern Entertainment, wedding DJ and emcee services, and coaching for wedding entertainers, Richmond, Virginia. Content language: English.$q$,
  '6e9faea3-412b-4839-90e7-77b67f654808', now(), now()
where not exists (select 1 from brand_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808');

select 'creator', count(*) from creator_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808'
union all select 'voice', count(*) from founder_voice_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808'
union all select 'brand', count(*) from brand_profiles where workspace_id = '6e9faea3-412b-4839-90e7-77b67f654808';

commit;
