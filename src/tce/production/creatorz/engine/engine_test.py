"""Unit tests for the Creatorz reel engine's pure logic (no numpy, no Pillow, no ffmpeg), so they run under `python -I`.
Each test names the bug or rule it guards; the checklist test plants bad input and asserts the FAIL."""
import unittest

from creatorz_reel import plan as P
from creatorz_reel import cut as C
from creatorz_reel import compose_plan as CP
from creatorz_reel import draw as D
from creatorz_reel import measure as M


def shot(pick, t0, t1, words):
    ow, step = [], (t1 - t0) / max(1, len(words))
    for k, w in enumerate(words):
        ow.append({'text': w, 's': round(t0 + k * step, 3), 'e': round(t0 + (k + 1) * step - 0.02, 3)})
    return {'pick': pick, 'out_in': t0, 'out_out': t1, 'owords': ow}


SHOTS = [shot(0, 0.0, 3.6, 'Sometimes a no isn\'t about price, it\'s the calendar.'.split()),
         shot(1, 3.6, 5.6, 'So I said no, thank you.'.split()),
         shot(2, 5.6, 7.0, 'Every two weeks.'.split())]


class CueTest(unittest.TestCase):
    def test_word_cue_is_scoped_to_its_pick_not_the_hook(self):
        # 10-Nov: an unscoped "no," matched the hook's "a no" and a 15 s overlay ran over the whole reel
        t = P.resolve({'pick': 1, 'word': 'no,'}, SHOTS)
        self.assertGreaterEqual(t, 3.6)

    def test_missing_word_names_what_the_pick_says(self):
        with self.assertRaises(P.CueError) as e:
            P.resolve({'pick': 2, 'word': 'price'}, SHOTS)
        self.assertIn('Every two weeks.', str(e.exception))

    def test_at_end_and_offset(self):
        self.assertAlmostEqual(P.resolve({'pick': 0, 'at': 'end', 'offset': -0.5}, SHOTS), 3.1)

    def test_nth_and_edge(self):
        s = [shot(0, 0, 2, ['week', 'after', 'week'])]
        self.assertGreater(P.resolve({'pick': 0, 'word': 'week', 'nth': 2}, s), P.resolve({'pick': 0, 'word': 'week', 'edge': 'end'}, s))

    def test_plan_rejects_unknown_moment_and_bad_schema(self):
        with self.assertRaises(P.PlanError):
            P.normalize({'schema': 'x', 'source': 'a', 'words': 'b', 'picks': [{'span': [0, 1]}]})
        with self.assertRaises(P.PlanError):
            P.normalize({'schema': P.SCHEMA, 'source': 'a', 'words': 'b', 'picks': [{'span': [0, 1]}], 'moments': [{'type': 'dissolve'}]})

    def test_pick_by_word_range(self):
        ws = [{'text': 'a', 'start_s': 1.0, 'end_s': 1.2}, {'text': 'b', 'start_s': 1.3, 'end_s': 1.6}]
        (a, b), = P.pick_spans([{'words': [0, 1]}], ws)
        self.assertLess(a, 1.0)
        self.assertGreater(b, 1.6)


class CutTest(unittest.TestCase):
    def test_cut_follows_the_voice_not_a_stretched_first_word(self):
        # TCE gave "I" 0.6 s over -58 dB air; the cut must start where the voice starts
        db = [-58.0] * 60 + [-22.0] * 80 + [-55.0] * 40 + [-20.0] * 50
        runs = C.voiced_runs(db, 0.0, 2.3)
        self.assertEqual(runs[0][0], 0.60)
        self.assertEqual(len(runs), 2)          # the 0.4 s pause splits into two shots

    def test_short_gap_merges_and_blip_drops(self):
        db = [-20.0] * 30 + [-60.0] * 20 + [-20.0] * 30 + [-60.0] * 50 + [-20.0] * 5 + [-60.0] * 10
        runs = C.voiced_runs(db, 0.0, 1.45)
        self.assertEqual(runs, [(0.0, 0.8)])     # 0.2 s gap merged, 0.05 s blip dropped

    def test_stretched_word_lands_in_one_shot_only(self):
        # "more" touched two runs and was captioned twice (10-Nov)
        ws = [{'text': 'booked', 'start_s': 56.16, 'end_s': 56.60}, {'text': 'more', 'start_s': 56.88, 'end_s': 57.56},
              {'text': 'than', 'start_s': 57.56, 'end_s': 57.74}]
        got = C.assign_words(ws, [(55.75, 56.94), (57.33, 58.25)])
        self.assertEqual([w['text'] for w in got[0]], ['booked'])
        self.assertEqual([w['text'] for w in got[1]], ['more', 'than'])

    def test_a_touch_of_the_next_word_is_not_that_word(self):
        ws = [{'text': 'see.', 'start_s': 134.13, 'end_s': 134.39}, {'text': 'word', 'start_s': 134.39, 'end_s': 134.45}]
        got = C.assign_words(ws, [(133.9, 134.40)])
        self.assertEqual([w['text'] for w in got[0]], ['see.'])

    def test_stretched_early_first_word_stays_with_its_run(self):
        # strike 2 (10-Nov): "It" started in the silence and only 0.1 s of it sat in the run -> dropped "It comes back"
        ws = [{'text': 'It', 'start_s': 13.95, 'end_s': 14.60}, {'text': 'comes', 'start_s': 14.60, 'end_s': 14.90}]
        got = C.assign_words(ws, [(14.50, 16.60)])
        self.assertEqual([w['text'] for w in got[0]], ['It', 'comes'])

    def test_pick_edge_inside_running_voice_cuts_at_the_edge(self):
        # "80%." runs straight into "Honestly": padding past the pick end would play "Hon-"
        self.assertEqual(C.run_bounds(158.3, 158.70, 154.7, 158.70)[1], 158.70)
        self.assertAlmostEqual(C.run_bounds(10.65, 12.67, 10.0, 12.85)[1], 12.75)

    CFG = {'thr_db': -40.0, 'gap_max': 0.28, 'min_run': 0.12, 'pad_in': 0.05, 'pad_out': 0.08}

    def test_pick_end_before_the_voice_ends_keeps_the_last_syllable(self):
        # strike 3 (10-Nov): TCE ended "away." at 67.40, the voice ran to 67.65, the cut at 67.44 chopped "-way"
        db = [-60.0] * 100 + [-20.0] * 142 + [-55.0] * 110
        ws = [{'text': 'right', 'start_s': 1.6, 'end_s': 2.0}, {'text': 'away.', 'start_s': 2.0, 'end_s': 2.30}]
        s = C.build_shots([(0.9, 2.35)], ws, db, self.CFG)
        self.assertGreaterEqual(s[0]['src_out'], 2.42)

    def test_pick_start_after_the_voice_starts_keeps_the_first_syllable(self):
        db = [-60.0] * 80 + [-20.0] * 120 + [-55.0] * 60
        ws = [{'text': 'Here', 'start_s': 1.04, 'end_s': 1.4}, {'text': 'it', 'start_s': 1.4, 'end_s': 1.9}]
        s = C.build_shots([(0.92, 2.1)], ws, db, self.CFG)
        self.assertLessEqual(s[0]['src_in'], 0.80)

    def test_no_reach_past_the_edge_into_an_unpicked_word(self):
        # the sound after the edge is the next word ("Hi"), not this word's decay: stay at the edge
        db = [-60.0] * 100 + [-20.0] * 155 + [-55.0] * 100
        ws = [{'text': 'so', 'start_s': 1.2, 'end_s': 1.9}, {'text': 'away.', 'start_s': 2.0, 'end_s': 2.30},
              {'text': 'Hi', 'start_s': 2.36, 'end_s': 2.55}]
        s = C.build_shots([(0.9, 2.35)], ws[:2], db, self.CFG)
        self.assertGreaterEqual(s[0]['src_out'], 2.55)            # without the next word it reaches
        s = C.build_shots([(0.9, 2.35)], ws, db, self.CFG)
        self.assertLessEqual(s[0]['src_out'], 2.35)

    def test_no_reach_into_the_next_pick(self):
        db = [-60.0] * 100 + [-20.0] * 142 + [-55.0] * 20 + [-20.0] * 60 + [-55.0] * 40
        ws = [{'text': 'away.', 'start_s': 1.4, 'end_s': 2.30}, {'text': 'That', 'start_s': 2.62, 'end_s': 3.0}]
        s = C.build_shots([(0.9, 2.35), (2.36, 3.3)], ws, db, self.CFG)
        self.assertLessEqual(s[0]['src_out'], 2.36)

    def test_reach_stops_at_the_first_dip_not_after_a_breath(self):
        # demo 1 "week." ended 22.60, a breath ran 22.68-22.78: reaching to the long quiet kept the breath
        db = [-60.0] * 100 + [-20.0] * 142 + [-50.0] * 6 + [-30.0] * 12 + [-55.0] * 60
        ws = [{'text': 'away.', 'start_s': 1.4, 'end_s': 2.30}]
        s = C.build_shots([(0.9, 2.35)], ws, db, self.CFG)
        self.assertGreaterEqual(s[0]['src_out'], 2.42)
        self.assertLessEqual(s[0]['src_out'], 2.48)

    def test_exact_mode_cuts_on_the_callers_frame_clock(self):
        # TCE: the file's clock must be TCE's own keep (round(second x 30)), or notes and QC point at the wrong moment
        ws = [{'text': 'one', 'start_s': 1.05, 'end_s': 1.5}, {'text': 'two', 'start_s': 3.05, 'end_s': 3.4}]
        s = C.build_exact_shots([(1.012, 2.02), (3.0, 3.49), (5.0, 5.01)], ws, fps=30)
        self.assertEqual([(x['src_in'], x['src_out']) for x in s], [(30 / 30, 61 / 30), (90 / 30, 105 / 30)])  # under a frame: dropped
        self.assertEqual([x['text'] for x in s], ['one', 'two'])

    def test_exact_long_range_changes_zoom_at_word_ends_only(self):
        ws = [{'text': f'w{i}' + (',' if i == 5 else ''), 'start_s': i * 0.5, 'end_s': i * 0.5 + 0.45} for i in range(18)]
        s = C.build_exact_shots([(0.0, 9.0)], ws, fps=30)
        self.assertGreater(len(s), 2)
        for a, b in zip(s, s[1:]):
            self.assertEqual(a['src_out'], b['src_in'])                                 # the picture and sound run on
            self.assertTrue(any(abs(w['end_s'] - a['src_out']) < 0.034 for w in ws), a) # never inside a word
        self.assertTrue(all(x['src_out'] - x['src_in'] <= 3.6 for x in s), [x['src_out'] - x['src_in'] for x in s])
        self.assertEqual(s[0]['text'].split()[-1], 'w5,')                               # a phrase end beats a plain word end
        self.assertEqual(' '.join(x['text'] for x in s), ' '.join(w['text'] for w in ws))

    def test_exact_range_without_words_stays(self):
        # a laugh TCE kept on purpose has no words: it stays in the reel (TCE b3a0456)
        s = C.build_exact_shots([(1.0, 2.2)], [], fps=30)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['words'], [])

    def test_every_exact_shot_is_its_own_pick(self):
        ws = [{'text': f'w{i}.', 'start_s': i * 1.0, 'end_s': i * 1.0 + 0.9} for i in range(9)]
        s = C.build_exact_shots([(0.0, 9.0), (10.0, 11.0)], ws, fps=30)
        self.assertEqual([x['pick'] for x in s], list(range(len(s))))

    def test_an_opencv_without_face_finding_only_loses_the_centering(self):
        # OpenCV 5 moved CascadeClassifier: the reel must still be made (10-Nov, first render on the server)
        import sys
        import types
        fake = types.SimpleNamespace(VideoCapture=lambda path: None)
        real = sys.modules.get('cv2')
        sys.modules['cv2'] = fake
        try:
            self.assertEqual(C._faces('x.mkv', [{}, {}]), [None, None])
        finally:
            if real is None:
                del sys.modules['cv2']
            else:
                sys.modules['cv2'] = real

    def test_contiguous_shots_have_no_fade_at_their_join(self):
        shots = [{'src_in': 1.0, 'src_out': 2.0}, {'src_in': 2.0, 'src_out': 3.0}, {'src_in': 5.0, 'src_out': 6.0}]
        self.assertEqual(C.join_fades(shots), [(True, False), (False, True), (True, True)])

    def test_mask_cache_key_changes_with_the_cut(self):
        from creatorz_reel import masks as MK
        e = {'shots': [{'src_in': 1.0, 'src_out': 2.0, 'crop': [0, 0, 900, 1600]}]}
        a = MK.cut_stamp(e)
        e['shots'][0]['src_out'] = 2.04
        self.assertNotEqual(a, MK.cut_stamp(e))

    def test_running_voice_with_no_quiet_stays_at_the_edge(self):
        db = [-60.0] * 100 + [-20.0] * 200
        ws = [{'text': 'away.', 'start_s': 1.4, 'end_s': 2.30}]
        s = C.build_shots([(0.9, 2.35)], ws, db, self.CFG)
        self.assertLessEqual(s[0]['src_out'], 2.35)

    def test_neighbors_never_share_a_scale_and_wide_picks_stay_wide(self):
        picks = [0, 1, 1, 2, 3, 4, 4, 5, 6, 7]
        sc = C.plan_scales(picks, wide_picks={0, 4, 5}, punch_pick=6)
        for a, b in zip(sc, sc[1:]):
            self.assertGreaterEqual(abs(a - b), 0.05)
        self.assertEqual(sc[0], 1.0)
        self.assertEqual(max(sc), C.PUNCH)
        self.assertEqual(sc[picks.index(6)], C.PUNCH)

    def test_two_wide_picks_in_a_row_still_change_scale(self):
        sc = C.plan_scales([0, 1], wide_picks={0, 1})
        self.assertGreaterEqual(abs(sc[0] - sc[1]), 0.05)

    def test_crop_puts_eyes_on_upper_third_and_stays_inside(self):
        x, y, w, h = C.crop_for(1.26, [540, 700, 400, 400])
        self.assertTrue(0 <= x and x + w <= 1080 and 0 <= y and y + h <= 1920)
        eyes = 700 - 400 * 0.12
        self.assertAlmostEqual((eyes - y) / h, 1 / 3, delta=0.02)


class CaptionTest(unittest.TestCase):
    def test_line_never_ends_on_a_weak_word(self):
        texts = 'I do the same thing to my own clients.'.split()
        for i0, i1 in CP.chunk_words(texts, 'en'):
            if i1 < len(texts):
                self.assertNotIn(CP.bare(texts[i1 - 1]), CP.WEAK['en'])

    def test_hebrew_line_never_ends_on_shel_or_et(self):
        texts = 'זה הסרטון של הלקוח את כל הסיפור'.split()
        for i0, i1 in CP.chunk_words(texts, 'he'):
            if i1 < len(texts):
                self.assertNotIn(texts[i1 - 1], {'של', 'את'})

    def test_number_stays_with_its_unit(self):
        texts = 'we booked 600 students this year'.split()
        lines = [' '.join(texts[a:b]) for a, b in CP.chunk_words(texts, 'en')]
        self.assertTrue(any('600 students' in l for l in lines), lines)

    def test_punctuation_closes_a_line(self):
        texts = "I could afford it. That wasn't".split()
        self.assertEqual(CP.chunk_words(texts, 'en')[0], (0, 4))

    def test_every_word_captioned_once(self):
        texts = 'one two three four five six seven eight nine'.split()
        ch = CP.chunk_words(texts, 'en')
        self.assertEqual(ch[0][0], 0)
        self.assertEqual(ch[-1][1], len(texts))
        for (a, b), (c, d) in zip(ch, ch[1:]):
            self.assertEqual(b, c)


class CardCoverTest(unittest.TestCase):
    def test_a_card_hides_text_it_would_cover(self):
        # demo 3 (10-Nov): the 'try this today:' tag showed through the list card, text over text
        tag = {'kind': 'tag', 'box': [40, 1080, 560, 1160]}
        top = {'kind': 'headline', 'box': [40, 100, 1040, 300]}
        card = {'kind': 'card_list', 'box': [90, 860, 990, 1290]}
        self.assertEqual([d['kind'] for d in CP.drop_covered([tag, top, card])], ['headline', 'card_list'])
        self.assertEqual([d['kind'] for d in CP.drop_covered([tag, top])], ['tag', 'headline'])


class SkyTest(unittest.TestCase):
    def test_sky_text_moves_front_when_any_frame_hides_too_much(self):
        # 10-Nov: one clean still, then the handheld head rose and ate 'WEE__ SLOT'
        self.assertEqual(CP.decide_layer([0.05, 0.08, 0.31, 0.06]), 'top')
        self.assertEqual(CP.decide_layer([0.05, 0.12, 0.18]), 'sky')

    def test_one_hidden_letter_sends_the_word_front(self):
        # demo 2 (10-Nov): the head covered 'T D' of 'NOT DONE.', 12.5% of the ink (under 20%), and it read 'NO_ DONE.'
        ink = [30.0] * 180                                  # nine letters, 20 columns each, 30 px of ink per column
        hid = [30.0 if 40 <= x < 60 else 0.0 for x in range(180)]   # the third letter fully behind the head
        overall, letter = CP.hidden_shares(ink, hid, ink, hid, 9)
        self.assertLess(overall, CP.OCCLUDE_LIMIT)
        self.assertEqual(CP.decide_layer([(overall, letter)]), 'top')
        graze = [5.0] * 180                                 # the head grazes the bottom of every letter: still readable
        self.assertEqual(CP.decide_layer([CP.hidden_shares(ink, graze, ink, graze, 9)]), 'sky')

    def test_no_masks_means_front(self):
        self.assertEqual(CP.decide_layer([]), 'top')


class BuildTest(unittest.TestCase):
    PLAN = {'lang': 'en', 'moments': [
        {'type': 'headline', 'text': 'PRICE', 'at': {'pick': 0, 'word': 'price,'}, 'until': {'pick': 0, 'word': 'calendar.'}},
        {'type': 'strike', 'target': 0, 'at': {'pick': 0, 'word': 'price,', 'edge': 'end'}, 'until': {'pick': 0, 'word': 'calendar.'}},
        {'type': 'pair', 'light': 'So I said', 'bold': 'NO, THANK YOU.', 'at': {'pick': 1, 'word': 'said'}, 'bold_at': {'pick': 1, 'word': 'no,'}},
        {'type': 'card_grid', 'title': 'EVERY 2 WEEKS?', 'cells': 4, 'filled': [0, 2], 'at': {'pick': 2, 'at': 'start'},
         'ticks': [{'pick': 2, 'word': 'Every'}, {'pick': 2, 'word': 'weeks.'}]},
        {'type': 'riser', 'into': {'pick': 2, 'at': 'start'}},
    ]}
    EDIT = {'duration': 7.0, 'shots': SHOTS, 'lang': 'en'}

    def test_every_pop_gets_a_sound_and_cards_flash(self):
        spec = CP.build(self.PLAN, self.EDIT)
        cues = [t for t, _, _ in spec['sfx']]
        for it in spec['items']:
            self.assertTrue(any(abs(it['t0'] - c) <= 0.12 for c in cues), it['kind'])
        card = [it for it in spec['items'] if it['kind'] == 'card_grid'][0]
        self.assertIn(card['t0'], spec['flashes'])
        self.assertEqual(len(card['ticks']), 2)

    def test_chest_moments_hide_the_running_caption(self):
        spec = CP.build(self.PLAN, self.EDIT)
        pair = [it for it in spec['items'] if it['kind'] == 'pair'][0]
        self.assertIn((pair['t0'], pair['t1']), spec['hide_cap'])

    def test_default_until_is_the_end_of_the_pick(self):
        spec = CP.build(self.PLAN, self.EDIT)
        pair = [it for it in spec['items'] if it['kind'] == 'pair'][0]
        self.assertEqual(pair['t1'], 5.6)


class RtlTest(unittest.TestCase):
    def test_latin_is_untouched(self):
        self.assertEqual(D.visual('Every 2 weeks'), 'Every 2 weeks')

    def test_hebrew_reads_right_to_left_with_numbers_kept(self):
        v = D.visual('כל 2 שבועות')
        self.assertTrue(v.startswith('תועובש'), v)   # the last word comes first, letters reversed
        self.assertIn('2', v)


class ChecklistTest(unittest.TestCase):
    GOOD = {'duration': 39.3, 'first_word': 0.0, 'tail': 0.01, 'pauses': [], 'still_max': 2.1, 'text_gap_max': 3.8,
            'scales': [1.0, 1.18, 1.26], 'lufs': -14.4, 'tp': -1.3, 'video': '1080,1920,25/1', 'silent_pops': [],
            'sky': [{'text': 'PRICE', 'layer': 'sky', 'max_hidden': 0.1}]}

    def test_good_reel_passes(self):
        self.assertTrue(all(v[0] == 'PASS' for v in M.verdicts(self.GOOD)))

    def test_planted_bad_reel_fails_every_line_it_should(self):
        bad = dict(self.GOOD, first_word=0.4, tail=0.6, pauses=[0.5, 0.6], still_max=4.6, text_gap_max=5.8,
                   scales=[1.18, 1.18], lufs=-18.0, tp=-0.2, video='1920,1080,30/1', silent_pops=[2.4],
                   sky=[{'text': 'WEEKLY SLOT', 'layer': 'sky', 'max_hidden': 0.31}])
        fails = {v[1] for v in M.verdicts(bad) if v[0] == 'FAIL'}
        self.assertEqual(len(fails), 11, fails)     # all 12 lines but the length check

    def test_one_eaten_letter_fails_readability(self):
        bad = dict(self.GOOD, sky=[{'text': 'NOT DONE.', 'layer': 'sky', 'max_hidden': 0.125, 'worst_letter': 0.9}])
        fails = {v[1] for v in M.verdicts(bad) if v[0] == 'FAIL'}
        self.assertEqual(fails, {'sky text kept readable'})

    def test_frame_rate_is_per_plan(self):
        good30 = dict(self.GOOD, video='1080,1920,30/1', fps=30)
        self.assertTrue(all(v[0] == 'PASS' for v in M.verdicts(good30)))
        wrong = {v[1] for v in M.verdicts(dict(self.GOOD, fps=30)) if v[0] == 'FAIL'}
        self.assertEqual(wrong, {'1080x1920 at 30 fps'})

    def test_length_range_is_per_plan(self):
        long_ok = dict(self.GOOD, duration=97.3, length_range=(20, 600))
        self.assertTrue(all(v[0] == 'PASS' for v in M.verdicts(long_ok)))


if __name__ == '__main__':
    unittest.main()
