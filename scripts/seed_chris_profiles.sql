-- Chris Gamble's creator, voice and brand profiles for his TCE workspace (05-Nov-2026).
-- These models carry no workspace column in the ORM, so client profiles are seeded by SQL
-- (POST /profiles/* writes a NULL workspace). Idempotent: a second run inserts nothing.
-- Sources: his own words on his 05-Nov-2026 call with Ziv (verbatim lines only) and
-- christophergamble.co. Nothing private: his personal matters stay out of every profile.
-- Run: docker exec -i tce-db psql -U tce -d tce -v ON_ERROR_STOP=1 < scripts/seed_chris_profiles.sql

begin;

insert into creator_profiles (id, creator_name, source_urls, style_notes, allowed_influence_weight,
                              top_patterns, workspace_id, created_at, updated_at)
select gen_random_uuid(), 'Christopher Gamble', array['https://christophergamble.co/', 'https://christophergamble.co/about/', 'https://christophergamble.co/typewriter-poetry/'],
  $q$Christopher (Chris) Gamble is a Calgary-based clown, physical theatre artist, director and touring performer. He has made theatre since he was a kid (first clown workshop at age 10, a diploma in the arts from Red Deer College in 2001), co-founded NoBones Theatre in 2005 and studied clown with Alan Clay in New Zealand in 2008. He makes family shows (The Suitcase Circus), roaming entertainment, workshops, cabaret and Typewriter Poetry: he sits at his grandfather's 1934 typewriter and writes a poem on the spot for whoever stops, at festivals, markets, weddings and private events across Alberta. He is a single parent. Video content has three lanes, the pillars he named on 05-Nov-2026: Parent as an Artist (questions he answers from his own life), Living a Creative Life (creativity and play in the news, and his take) and Typewriter Poetry (a real thing about typewriters or poem forms, then a poem he writes on the spot). Films walk-and-talk videos outside, one short line at a time, one place, one take.$q$,
  0.2,
  array['Challenges a belief gently ("can I challenge that for a second?") and turns it around in a few sentences',
        'Talks about the human moment over the polished product',
        'Playful and a little absurd, then honest',
        'Speaks to a thing in front of him as if it could listen'],
  'f34e9762-6b7f-4399-afcf-b674db1e28f5', now(), now()
where not exists (select 1 from creator_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5');

insert into founder_voice_profiles (id, vocabulary_signature, sentence_rhythm_profile, values_and_beliefs,
                                    metaphor_families, tone_range, taboos, recurring_themes, humor_type,
                                    workspace_id, created_at, updated_at)
select gen_random_uuid(),
  $j${
 "language": "en",
 "phrases": [
  "can I challenge that for a second?",
  "living a creative life",
  "their eyes get as big as saucers",
  "yes, AI can do it, but do you want it to?",
  "you are not censoring yourself",
  "a place that you love to go",
  "weird spots of typing"
 ],
 "samples": [
  "I think one thing that I'm a niche in that I can really identify is like what it is as a parent and an artist.",
  "When I talk to a lot of people that are in similar situations, their eyes get as big as saucers when they hear about what I'm doing and how I'm getting it done.",
  "How do you make sure you know what you are as a creator, and that like you are not censoring yourself for putting that out into the world?",
  "AI can do exactly what I do and probably give you a better, funnier poem, and nobody wants it.",
  "Hey, like, listen, I just saw this festival right over here, I think I'm going to write a poem about it.",
  "The goal is not just to get a laugh. The goal is to create a shared moment that feels alive.",
  "I think we all have the urge to be a clown, whether we know it or not."
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
  $j${"register": "playful, warm, honest spoken English", "avg_length": "short", "variation": "medium",
      "pauses": "a beat on the walk between lines, a look up for the line that matters"}$j$::jsonb,
  array[$a$Living a creative life is not about being an artist. It is knowing what you are as a creator and not censoring yourself.$a$,
        $a$Guilt and pressure kill the need to create. A studio should be a place you love even if you never make a painting in it.$a$,
        $a$A poem made by a person for one moment matters because someone paid close attention to you.$a$,
        $a$Clown gives people permission to be silly, curious, brave and a little more open than when they walked in.$a$,
        $a$People need places where they can laugh, take part, loosen up and connect with each other.$a$,
        $a$Being a parent and an artist is possible, and other parents should hear how it gets done.$a$],
  array[$a$The typewriter: keys, ribbon, paper, the carriage return$a$,
        $a$The suitcase and the circus: a ringmaster who cannot do it alone$a$,
        $a$Play and permission: the fool, the room, failing out loud and calling it play$a$],
  $j${"playful": 5, "serious": 3, "vulnerable": 4, "provocative": 3}$j$::jsonb,
  array['Never invent a story, a person, a quote or a number',
        'Never write a poem for him',
        'Never his children''s names or private details, family conflict or anything legal',
        'Never prices, fees or money',
        'No politics, war, crime or tragedy',
        'No call to action'],
  array[$a$Being a single parent and a working artist$a$,
        $a$Living a creative life, play, and dropping the guilt about making things$a$,
        $a$Typewriter Poetry: poems on the spot, the human moment over the machine$a$,
        $a$Clown and physical theatre: permission to be silly, curious and brave$a$],
  $a$Physical and absurd, gentle with people, happy to be the fool (he will jump off a suitcase to make you laugh).$a$,
  'f34e9762-6b7f-4399-afcf-b674db1e28f5', now(), now()
where not exists (select 1 from founder_voice_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5');

insert into brand_profiles (id, creator_profile_id, name, description, workspace_id, created_at, updated_at)
select gen_random_uuid(),
  (select id from creator_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5' limit 1),
  'Christopher Gamble - clown and typewriter poet',
  $q$Clown, physical theatre, The Suitcase Circus, roaming entertainment, workshops and Typewriter Poetry, Calgary, Alberta. Site: christophergamble.co. Content language: English.$q$,
  'f34e9762-6b7f-4399-afcf-b674db1e28f5', now(), now()
where not exists (select 1 from brand_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5');

select 'creator', count(*) from creator_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5'
union all select 'voice', count(*) from founder_voice_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5'
union all select 'brand', count(*) from brand_profiles where workspace_id = 'f34e9762-6b7f-4399-afcf-b674db1e28f5';

commit;
