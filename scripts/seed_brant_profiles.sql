-- Brant Matthews's creator, voice and brand profiles for his TCE workspace (28-Oct-2026).
-- These models carry no workspace column in the ORM, so client profiles are seeded by SQL
-- (POST /profiles/* writes a NULL workspace). Idempotent: a second run inserts nothing.
-- Sources: his 21-Oct call with Ziv (the three pillars, his own words), his confirmed
-- KM Hub business facts and brand voice (Fire Guy Show), fireguyshow.com.
-- Run: docker exec -i tce-db psql -U tce -d tce -v ON_ERROR_STOP=1 < scripts/seed_brant_profiles.sql

begin;

insert into creator_profiles (id, creator_name, source_urls, style_notes, allowed_influence_weight,
                              top_patterns, workspace_id, created_at, updated_at)
select gen_random_uuid(), 'Brant Matthews', array['https://fireguyshow.com/'],
  $q$Brant Matthews performs as the Fire Guy (Fire Guy Show), a fire performer for more than 30 years and a Guinness World Record holder: most torches extinguished by fire eating in one minute, 101, set at a state fair in 2018. Shows: Burning Rubber (fire juggling while riding a Onewheel, built for motorsport crowds) and Cold Fusion (a self-contained fire show for outdoor winter events). Performs at weddings, festivals, fairs, motorsport and winter events. Video content has three lanes he chose: The Sacred Flame (the history of fire, its myths and rituals), Keeper of the Flame (questions he answers from his own 30 years of performing) and Taming the Fire (records, stunts and danger mastery in the news, his take as a record holder). Films walking and talking in different places, one sentence at a time, 2 to 3 minutes once edited.$q$,
  0.2,
  array['Leads with the fire: what burns, what spins, what the crowd does',
        'States the record once, plainly, and moves on',
        'Short, punchy lines with a little humor',
        'Respect for danger over bravado'],
  '3844285d-f119-47e9-98e4-5691f0cbdb4b', now(), now()
where not exists (select 1 from creator_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b');

insert into founder_voice_profiles (id, vocabulary_signature, sentence_rhythm_profile, values_and_beliefs,
                                    metaphor_families, tone_range, taboos, recurring_themes, humor_type,
                                    workspace_id, created_at, updated_at)
select gen_random_uuid(),
  $j${"language": "en",
      "phrases": ["a safe artist displaying a dangerous element", "the sacred flame",
                  "keeper of the flame", "taming the fire", "too important to fail"],
      "samples": ["I am a safe artist displaying a dangerous element.",
                  "A wedding is too important to fail.",
                  "Speed, smoke, and total control.",
                  "If it's not simple, people will not understand it, will not resonate with it."],
      "avoided_words": ["hacks", "crush it", "insane", "you won't believe"]}$j$::jsonb,
  $j${"register": "punchy, warm, spoken American English", "avg_length": "short", "variation": "medium",
      "pauses": "a beat after the fire image, before the point"}$j$::jsonb,
  array['A safe artist displays a dangerous element: the risk the crowd feels is real, the risk to the event is not',
        'Safety is assumed on his side; on arrival he checks that the venue meets his standards',
        'Fire deserves respect: first you respect it, then you keep it, then you tame it',
        'Keep it simple, or people will not understand it',
        'A fire performer is an artist, and the work deserves to be taken seriously'],
  array['fire as a beast to tame', 'the spark', 'fanning the flame', 'cooking on the fire as mastery'],
  $j${"playful": 5, "serious": 5, "vulnerable": 4, "provocative": 4}$j$::jsonb,
  array['Never invent a story, a show, a crowd, a quote or a number',
        'Never teach how to do a fire or danger stunt, or dare anyone to try one',
        'Never a death, an injury or a disaster as the subject',
        'Never name clients, the venues that book him or their guests',
        'Never prices or fees',
        'No politics, war or crime',
        'No call to action'],
  array['the history of fire, its myths and rituals', 'his 30 years of performing with fire',
        'his Guinness World Record', 'control over danger', 'other number ones and their feats'],
  'punchy and a little funny, never at anyone''s expense',
  '3844285d-f119-47e9-98e4-5691f0cbdb4b', now(), now()
where not exists (select 1 from founder_voice_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b');

insert into brand_profiles (id, creator_profile_id, name, description, workspace_id, created_at, updated_at)
select gen_random_uuid(),
  (select id from creator_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b' limit 1),
  'Brant Matthews - Fire Guy Show',
  $q$Fire performer and Guinness World Record holder (most torches extinguished by fire eating in one minute, 101). Shows: Burning Rubber (fire on a Onewheel, motorsport crowds) and Cold Fusion (self-contained winter fire show). Site: fireguyshow.com. Content language: English (US).$q$,
  '3844285d-f119-47e9-98e4-5691f0cbdb4b', now(), now()
where not exists (select 1 from brand_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b');

select 'creator', count(*) from creator_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b'
union all select 'voice', count(*) from founder_voice_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b'
union all select 'brand', count(*) from brand_profiles where workspace_id = '3844285d-f119-47e9-98e4-5691f0cbdb4b';

commit;
