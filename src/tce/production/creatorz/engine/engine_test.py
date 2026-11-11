"""Unit tests for the Creatorz reel engine's pure logic (no numpy, no Pillow, no ffmpeg), so they run under `python -I`.
Each test names the bug or rule it guards; the checklist test plants bad input and asserts the FAIL."""
import unittest

from creatorz_reel import plan as P
from creatorz_reel import cut as C
from creatorz_reel import compose_plan as CP
from creatorz_reel import draw as D
from creatorz_reel import measure as M
from creatorz_reel import layout as L
from creatorz_reel import faces as F


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
            self.assertEqual(F.detect('x.mkv', [{}, {}], 30), ([None, None], None))
        finally:
            if real is None:
                del sys.modules['cv2']
            else:
                sys.modules['cv2'] = real

    def test_each_shot_renders_as_its_own_small_job(self):
        # one graph with a trim branch per shot buffered every later branch's frames: 6 GB and the kernel killed it
        # (first full TCE render on the server, 10-Nov); one seek and one short encode per shot stays flat
        shot = {'src_in': 3.0, 'src_out': 3.0 + 22 / 30, 'crop': [10, 20, 900, 1600]}
        cmd = C.video_segment_cmd('m.mkv', shot, 30, 'null', 's.mkv')
        self.assertEqual(cmd[cmd.index('-frames:v') + 1], '22')
        self.assertNotIn('-filter_complex', cmd)
        self.assertNotIn('-filter_complex_script', cmd)
        seek = float(cmd[cmd.index('-ss') + 1])
        self.assertLess(seek, 3.0)                     # the seek must keep the frame at 3.0
        self.assertGreater(seek, 3.0 - 1 / 30)         # and drop the frame before it
        self.assertLess(cmd.index('-ss'), cmd.index('-i'))
        self.assertIn('crop=900:1600:10:20', cmd[cmd.index('-vf') + 1])
        self.assertEqual(cmd[cmd.index('-bf') + 1], '0')    # joined with stream copy, so no reordered frames at a join

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
        f = face(top=500, fh=400, eye=652)
        x, y, w, h = L.crop_for(1.26, f)
        self.assertTrue(0 <= x and x + w <= 1080 and 0 <= y and y + h <= 1920)
        self.assertAlmostEqual((652 - y) / h, 1 / 3, delta=0.02)


class CaptionTest(unittest.TestCase):
    def test_a_shot_opens_with_its_caption(self):
        # 10-Nov: the frames between a cut and the shot's first word had no caption, so captions blinked at every cut
        s = [{'pick': 0, 'out_in': 0.0, 'out_out': 2.0, 'owords': [{'text': 'One', 's': 0.2, 'e': 0.6}, {'text': 'two.', 's': 0.7, 'e': 1.9}]},
             {'pick': 1, 'out_in': 2.0, 'out_out': 4.0, 'owords': [{'text': 'Three', 's': 2.25, 'e': 2.6}, {'text': 'four.', 's': 2.7, 'e': 3.9}]},
             {'pick': 2, 'out_in': 4.0, 'out_out': 7.0, 'owords': [{'text': 'Late.', 's': 5.5, 'e': 6.0}]}]
        caps = CP.captions(s)
        self.assertEqual([c['t0'] for c in caps], [0.0, 2.0, 5.5])     # a word a second and a half in does not show early
        self.assertEqual(caps[0]['t1'], 2.0)

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
            'sky': [{'text': 'PRICE', 'layer': 'sky', 'max_hidden': 0.1}],
            'look': {'on_face': [], 'edge': [], 'cut_head': [], 'accents': ['sand']}}

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

    def test_look_lines_fail_on_planted_ugly(self):
        # 10-Nov, the first real TCE render: captions on the mouth, headlines against the top edge, cut foreheads,
        # five colors. A clean look report passes; each planted fault fails its own line and only that line.
        clean = dict(self.GOOD, look={'on_face': [], 'edge': [], 'cut_head': [], 'accents': ['sand']})
        self.assertTrue(all(v[0] == 'PASS' for v in M.verdicts(clean)))
        blind = {k: v for k, v in self.GOOD.items() if k != 'look'}          # no report at all: nothing was looked at
        self.assertEqual(len([v for v in M.verdicts(blind) if v[0] == 'FAIL']), 6)
        for key, bad, line in (('on_face', [{'what': 'caption', 't': 4.0}], 'no text on the face'),
                               ('edge', [{'what': 'DONE', 't': 1.2}], 'text inside the safe area'),
                               ('cut_head', [12.4], 'the head stays in the frame'),
                               ('accents', ['sand', 'green'], 'one accent color'),
                               ('twice', [{'what': 'our own delivery', 't': 6.1}], 'nothing said twice on screen'),
                               ('short_cards', [{'what': 'card_list', 't': 29.0, 'shown': 1.5, 'needs': 4.3}],
                                'cards stay up long enough to read')):
            x = dict(self.GOOD, look=dict(clean['look'], **{key: bad}))
            self.assertEqual({v[1] for v in M.verdicts(x) if v[0] == 'FAIL'}, {line}, key)


def face(top=500, fh=600, cx=540, fw=460, eye=None, luma=0.5):
    """a face as faces.summarize() returns it, in source pixels: a box `fh` tall whose top is at `top`"""
    return {'cx': cx, 'cy': top + fh / 2, 'fw': fw, 'fh': fh, 'eye_y': eye if eye is not None else top + 0.36 * fh,
            'top': top, 'chin': top + fh, 'left': cx - fw / 2, 'right': cx + fw / 2, 'mouth': top + 0.78 * fh,
            'luma': luma, 'track': []}


class LayoutTest(unittest.TestCase):
    def test_a_face_that_fills_the_frame_caps_the_punch_in(self):
        # the selfie: a 760 px face box in a 1920 frame is already 40%; 1.26x and the 1.48x punchline made a giant face
        big = face(top=400, fh=760)
        self.assertAlmostEqual(L.scale_cap(big), 0.46 * 1920 / 760, places=3)
        got = L.fit_scales([1.18, 1.26, 1.48], [big, big, big], punch=2)
        self.assertTrue(all(s * 760 / 1920 <= L.FACE_HARD + 1e-6 for s in got), got)
        self.assertLessEqual(got[0] * 760 / 1920, 0.46 + 1e-6)

    def test_a_cut_between_two_full_faces_still_changes_scale(self):
        # the real video, shots 34-38: every face capped near 1.0, so neighbors came out 1.01 / 1.00 / 1.00 / 1.01
        full = face(top=300, fh=880)                                 # 46% of the frame at 1.0x already
        got = L.fit_scales([1.18, 1.26, 1.12, 1.22], [full] * 4)
        self.assertTrue(all(abs(a - b) >= L.MIN_STEP - 1e-9 for a, b in zip(got, got[1:])), got)
        self.assertTrue(all(s * 880 / 1920 <= L.FACE_HARD + 1e-6 for s in got), got)

    def test_capped_neighbors_still_differ(self):
        big = face(top=400, fh=760)
        got = L.fit_scales([1.18, 1.26, 1.12, 1.22], [big] * 4)
        self.assertTrue(all(abs(a - b) >= L.MIN_STEP - 1e-9 for a, b in zip(got, got[1:])), got)
        self.assertTrue(all(s >= 1.0 for s in got))

    def test_no_face_keeps_the_planned_scale(self):
        self.assertEqual(L.fit_scales([1.18, 1.26], [None, None]), [1.18, 1.26])

    def test_crop_never_cuts_into_the_forehead(self):
        # a face whose eyes sit low in its box: eyes-on-the-upper-third alone starts the crop inside the forehead
        f = face(top=420, fh=800, eye=880)
        x, y, cw, ch = L.crop_for(1.3, f)
        self.assertLessEqual(y, f['top'] - L.FOREHEAD * f['fh'] + 1)
        self.assertGreaterEqual(y + ch, f['chin'])
        out = L.to_out(f, [x, y, cw, ch])
        self.assertGreaterEqual(out['top'], L.FOREHEAD * out['fh'] - 2)

    def test_crop_without_a_face_is_centered(self):
        self.assertEqual(L.crop_for(1.25, None), [108, 192, 864, 1536])

    def test_one_caption_line_under_every_chin(self):
        outs = [{'chin': 1150}, {'chin': 1220}, None, {'chin': 1180}]
        lines = L.caption_lines(outs)
        self.assertEqual(len(set(lines)), 1)                         # one steady line
        self.assertGreaterEqual(lines[0], 1220 + L.CAP_GAP)          # under the lowest chin
        self.assertLessEqual(max(lines), L.CAP_MAX)

    def test_caption_line_never_rises_above_chest_or_sinks_past_the_floor(self):
        self.assertEqual(L.caption_lines([{'chin': 700}, {'chin': 760}]), [L.CAP_Y, L.CAP_Y])
        self.assertEqual(L.caption_lines([{'chin': 1700}]), [L.CAP_MAX])
        self.assertEqual(L.caption_lines([None, None]), [L.CAP_Y, L.CAP_Y])

    def test_headline_goes_above_only_with_real_room(self):
        roomy = {'top': 900, 'fh': 500, 'chin': 1400}                # a wide low-angle shot: sky above the head
        self.assertEqual(L.headline_slot(roomy, 1300)[0], 'above')
        tight = {'top': 330, 'fh': 760, 'chin': 1090}                # the selfie: hair starts near the top edge
        slot = L.headline_slot(tight, 1190)
        self.assertEqual(slot[0], 'under')
        self.assertGreaterEqual(slot[1], 1190 + 50)                  # below the caption line, never on the face
        self.assertLessEqual(slot[2], L.BOTTOM_SAFE)

    def test_headline_with_no_room_anywhere_takes_the_caption_line(self):
        tight = {'top': 330, 'fh': 900, 'chin': 1400}
        self.assertEqual(L.headline_slot(tight, L.CAP_MAX)[0], 'swap')

    def test_look_report_names_text_on_a_face_and_at_the_edge(self):
        fo = {'top': 400, 'chin': 1150, 'left': 300, 'right': 780, 'eye_y': 670, 'mouth': 985, 'fh': 750, 'fw': 480}
        shots = [{'out_in': 0.0, 'out_out': 3.0, 'face': fo, 'crop_top': 120},
                 {'out_in': 3.0, 'out_out': 6.0, 'face': dict(fo, top=10), 'crop_top': 120},     # our zoom cut the forehead
                 {'out_in': 6.0, 'out_out': 9.0, 'face': dict(fo, top=10), 'crop_top': 0}]       # the phone never filmed it
        texts = [{'what': 'caption on the mouth', 't0': 0.5, 't1': 1.5, 'box': [200, 940, 880, 1030]},
                 {'what': 'caption under the chin', 't0': 1.5, 't1': 2.5, 'box': [200, 1200, 880, 1290]},
                 {'what': 'DONE against the top', 't0': 0.2, 't1': 1.0, 'box': [300, 30, 780, 150]}]
        rep = L.look_report(texts, shots)
        self.assertEqual([x['what'] for x in rep['on_face']], ['caption on the mouth'])
        self.assertEqual([x['what'] for x in rep['edge']], ['DONE against the top'])
        self.assertEqual(rep['cut_head'], [3.0])

    def test_badge_moves_off_the_face(self):
        fo = {'top': 200, 'chin': 950, 'left': 60, 'right': 700, 'eye_y': 470, 'mouth': 785, 'fh': 750, 'fw': 640}
        cx, cy = L.side_spot(fo, 320, 320, 'left', 1190)
        self.assertFalse(L.meets([cx - 160, cy - 160, cx + 160, cy + 160], L.face_zone(fo)))

    def test_accent_comes_from_the_background(self):
        self.assertEqual(L.pick_accent((120, 170, 230)), 'sand')     # sky
        self.assertEqual(L.pick_accent((70, 120, 60)), 'sand')       # trees
        self.assertEqual(L.pick_accent((190, 130, 80)), 'ice')       # warm wood
        self.assertEqual(L.pick_accent((120, 120, 122)), 'butter')   # gray
        self.assertEqual(L.pick_accent(None), 'sand')

    def test_a_long_card_comes_and_goes_a_short_one_stays(self):
        self.assertEqual(L.card_windows(10.0, 13.5, [10.4, 11.5, 12.6]), [(10.0, 13.5)])
        wins = L.card_windows(10.0, 26.0, [10.5, 15.0, 20.0, 25.0])
        self.assertGreaterEqual(len(wins), 3)                        # the speaker comes back between ticks
        self.assertTrue(all(any(a <= x < b for a, b in wins) for x in (10.5, 15.0, 20.0, 25.0)))   # every tick is seen
        self.assertTrue(all(10.0 <= a and b <= 26.0 for a, b in wins))

    def test_a_card_stays_up_long_enough_to_read(self):
        # 11-Nov, Ziv at 0:39 of his video: "it transitions too fast so I can't manage to read it on time". The card
        # showed for 1.5 s, then came back for 1.25 s beats: four lines, 14 words, gone before they were read.
        items = ['Log into the real system', 'Test the change', 'Screenshots & videos', 'Point at the exact spot']
        words = sum(len(i.split()) for i in items)
        ticks = [29.6, 32.3, 35.4, 38.5]
        wins = L.card_windows(29.0, 40.6, ticks, words)
        self.assertGreaterEqual(wins[0][1] - wins[0][0], L.read_time(words) - 1e-6)       # the first look reads it all
        for x in ticks:                                              # every tick stays up long enough to see it land
            self.assertTrue(any(a <= x and b - x >= L.TICK_HOLD - 1e-6 for a, b in wins), (x, wins))
        for (_a0, b0), (a1, _b1) in zip(wins, wins[1:]):             # never back to the face for a blink
            self.assertGreaterEqual(a1 - b0, L.MIN_BACK - 1e-6, wins)
        self.assertGreaterEqual(L.read_time(words), 4.0)             # 14 words take about four seconds
        self.assertLessEqual(L.read_time(200), L.READ_MAX)

    def test_exposure_gamma_brightens_dark_shots_and_leaves_close_ones(self):
        self.assertGreater(L.exposure_gamma(0.30, 0.45), 1.0)
        self.assertLess(L.exposure_gamma(0.60, 0.45), 1.0)
        self.assertEqual(L.exposure_gamma(0.45, 0.455), 1.0)
        self.assertLessEqual(L.exposure_gamma(0.05, 0.6), 1.22)       # a backlit shot is only partly lifted
        self.assertEqual(L.exposure_gamma(None, 0.5), 1.0)

    def test_face_follow_is_smooth_bounded_and_covers_the_shot(self):
        track = [[2, 500, 600], [8, 560, 600], [14, 520, 640], [20, 900, 600], [26, 540, 610]]
        keys = L.smooth_track(track, 30, max_shift=40)
        self.assertEqual(keys[0][0], 0)
        self.assertEqual(keys[-1][0], 29)
        self.assertTrue(all(abs(dx) <= 40 and abs(dy) <= 40 for _k, dx, dy in keys), keys)
        self.assertEqual(L.smooth_track(track[:2], 30, 40), [])      # two samples are not a track
        expr = L.piecewise(keys, 1)
        self.assertIn('if(lt(n,', expr)
        self.assertEqual(L.piecewise([], 1), '0')

    def test_pop_overshoots_then_settles(self):
        self.assertAlmostEqual(L.ease_back(0.0), 0.0, places=6)
        self.assertAlmostEqual(L.ease_back(1.0), 1.0, places=6)
        self.assertGreater(max(L.ease_back(k / 20) for k in range(21)), 1.02)


def tight(shot_):
    """the same shot with a selfie face in it (output pixels): hair at the top edge, chin at 68%"""
    return dict(shot_, face={'top': 330, 'chin': 1300, 'left': 250, 'right': 830, 'eye_y': 680, 'mouth': 1090, 'fh': 970, 'fw': 580})


class CutawayTest(unittest.TestCase):
    EDIT = {'duration': 7.0, 'shots': [tight(s) for s in SHOTS], 'lang': 'en'}

    def build(self, moments, edit=None):
        return CP.build({'lang': 'en', 'moments': moments}, edit or self.EDIT)

    def test_a_headline_with_no_room_takes_the_caption_line_for_one_beat(self):
        # the real video: every "top" headline was jammed against the frame edge above a face that fills the frame
        spec = self.build([{'type': 'headline', 'text': 'PRICE', 'place': 'top', 'at': {'pick': 0, 'word': 'Sometimes'}}])
        it = spec['items'][0]
        self.assertEqual(it['layer'], 'front')
        self.assertEqual(it['slot'][0], 'swap')
        self.assertLessEqual(it['t1'] - it['t0'], CP.SWAP_MAX + 1e-6)
        self.assertIn((it['t0'], it['t1']), spec['hide_cap'])

    def test_sky_headline_goes_behind_the_head_only_where_there_is_sky(self):
        m = [{'type': 'headline', 'text': 'PRICE', 'place': 'sky', 'at': {'pick': 0, 'word': 'Sometimes'}}]
        self.assertEqual(self.build(m)['items'][0]['layer'], 'front')            # the tight selfie
        self.assertEqual(self.build(m, {'duration': 7.0, 'shots': SHOTS, 'lang': 'en'})['items'][0]['layer'], 'sky')

    def test_captions_sit_under_the_chin_on_one_line(self):
        lines = {y for _a, _b, y in self.build([])['cap_lines']}
        self.assertEqual(lines, {1300 + L.CAP_GAP})

    def test_a_long_list_card_cuts_away_in_beats_each_with_a_flash(self):
        long_edit = {'duration': 30.0, 'lang': 'en', 'shots': [shot(0, 0.0, 14.0, 'one two three four'.split()),
                                                                 shot(1, 14.0, 30.0, 'five six seven eight'.split())]}
        spec = self.build([{'type': 'card_list', 'items': ['A', 'B', 'C'], 'at': {'pick': 0, 'at': 'start'},
                            'until': {'pick': 1, 'at': 'end'},
                            'ticks': [{'pick': 0, 'word': 'two'}, {'pick': 0, 'word': 'four'}, {'pick': 1, 'word': 'seven'}]}], long_edit)
        card = spec['items'][0]
        self.assertEqual(card['layer'], 'scene')
        self.assertGreaterEqual(len(card['windows']), 3)
        self.assertLess(sum(b - a for a, b in card['windows']), 0.4 * (card['t1'] - card['t0']))   # the speaker gets most of it
        self.assertIn(card['windows'][0][0], spec['flashes'])        # the first cut to the card flashes
        for a, _b in card['windows'][1:]:                            # a return is a plain cut with a soft whoosh:
            self.assertNotIn(a, spec['flashes'])                      # four flashes in ten seconds were too much
        for a, _b in card['windows']:
            self.assertTrue(any(abs(a - t) <= 0.01 for t, _n, _g in spec['sfx']))

    def test_number_card_and_picture_hold_for_a_beat_not_the_whole_line(self):
        spec = self.build([{'type': 'card_stat', 'text': '80%', 'label': 'said yes', 'at': {'pick': 0, 'at': 'start'}},
                           {'type': 'insert', 'src': 'x.png', 'at': {'pick': 1, 'at': 'start'}}])
        stat, pic = spec['items']
        self.assertAlmostEqual(stat['windows'][0][1] - stat['windows'][0][0], CP.STAT_HOLD, places=3)
        self.assertAlmostEqual(pic['windows'][0][1] - pic['windows'][0][0], CP.INSERT_HOLD, places=3)
        self.assertEqual({stat['layer'], pic['layer']}, {'scene'})

    def test_a_whip_is_a_cut_with_a_whoosh_not_an_item(self):
        spec = self.build([{'type': 'whip', 'at': {'pick': 1, 'at': 'start'}}])
        self.assertEqual(spec['items'], [])
        self.assertEqual(spec['whips'], [3.6])
        self.assertTrue(any(n == 'whoosh' and abs(t - 3.52) < 0.01 for t, n, _g in spec['sfx']))

    def test_a_full_screen_scene_hides_every_other_item(self):
        scene = {'kind': 'card_stat', 'box': [0, 0, 1080, 1920]}
        tag = {'kind': 'tag', 'box': [40, 1080, 560, 1160]}
        self.assertEqual([d['kind'] for d in CP.drop_covered([tag, scene])], ['card_stat'])

    def test_a_picture_moment_needs_a_real_picture(self):
        base = {'schema': P.SCHEMA, 'source': 'a.mp4', 'words': 'w.json', 'picks': [{'span': [0, 1]}]}
        with self.assertRaises(P.PlanError):
            P.normalize(dict(base, moments=[{'type': 'insert', 'at': 0.5}]))
        with self.assertRaises(P.PlanError) as e:
            P.normalize(dict(base, moments=[{'type': 'insert', 'src': 'no-such-picture.png', 'at': 0.5}]))
        self.assertIn('no picture at', str(e.exception))

    def test_a_tall_screenshot_scrolls_a_wide_picture_fits_a_portrait_covers(self):
        self.assertEqual(D.picture_mode(780, 1688, 940, 1025), 'pan')       # fitted whole it was the size of a stamp
        self.assertEqual(D.picture_mode(1600, 900, 940, 1025), 'fit')
        self.assertEqual(D.picture_mode(1080, 1920, 940, 1025), 'cover')
        self.assertEqual(D.picture_mode(1170, 2000, 940, 1025), 'cover')

    def test_every_color_but_white_is_the_one_accent(self):
        self.assertFalse(D.is_accent('white'))
        self.assertFalse(D.is_accent(None))
        for name in ('accent', 'yellow', 'green', 'cyan', 'red'):
            self.assertTrue(D.is_accent(name), name)
        self.assertEqual(D.set_accent('ice'), 'ice')
        self.assertEqual(D.set_accent('no-such-color'), 'sand')
        self.assertEqual(D.set_accent([10, 200, 30]), 'custom')
        D.set_accent('sand')


class SaidTwiceTest(unittest.TestCase):
    """11-Nov, Ziv at 0:06 of his video: the tag "our own delivery" sat right above the caption "in our own delivery."
    ("its weird to show twice the same caption"). Text on screen never says what the caption already says."""
    SHOTS = [shot(0, 0.0, 3.0, 'I learned this in our own delivery.'.split()),
             shot(1, 3.0, 5.0, 'You hand a task over.'.split())]
    EDIT = {'duration': 5.0, 'shots': SHOTS, 'lang': 'en'}

    def build(self, *moments):
        return CP.build({'lang': 'en', 'moments': list(moments)}, self.EDIT)

    def test_a_tag_that_repeats_the_caption_is_not_shown(self):
        spec = self.build({'type': 'tag', 'text': 'our own delivery', 'at': {'pick': 0, 'word': 'delivery.'}})
        self.assertEqual(spec['items'], [])
        self.assertEqual([d['text'] for d in spec['dropped']], ['our own delivery'])

    def test_a_tag_that_names_what_comes_next_stays(self):
        spec = self.build({'type': 'tag', 'text': 'the fix:', 'at': {'pick': 0, 'word': 'delivery.'}})
        self.assertEqual([it['kind'] for it in spec['items']], ['tag'])

    def test_a_one_word_chapter_tag_on_the_word_he_says_stays(self):
        # his real video: "the rule:" over "I made a rule for my agents." is a chapter label, the reels' own style
        edit = {'duration': 3.0, 'lang': 'en', 'shots': [shot(0, 0.0, 3.0, 'I made a rule for my agents.'.split())]}
        spec = CP.build({'lang': 'en', 'moments': [{'type': 'tag', 'text': 'the rule:', 'at': {'pick': 0, 'at': 'start'}}]}, edit)
        self.assertEqual([it['kind'] for it in spec['items']], ['tag'])
        self.assertTrue(CP.repeats('the rule:', ['I made a rule']))             # one word for a headline: a beat
        self.assertFalse(CP.repeats('the rule:', ['I made a rule'], min_hits=CP.TAG_HITS))

    def test_a_headline_that_repeats_the_caption_takes_its_place_for_a_beat(self):
        spec = self.build({'type': 'headline', 'text': 'OUR OWN DELIVERY', 'place': 'top', 'at': {'pick': 0, 'word': 'our'}})
        it = spec['items'][0]
        self.assertLessEqual(it['t1'] - it['t0'], CP.SWAP_MAX + 1e-6)
        self.assertIn((it['t0'], it['t1']), spec['hide_cap'])        # one of the two goes: the caption, for the beat

    def test_what_counts_as_saying_it_twice(self):
        self.assertTrue(CP.repeats('DONE', ["it's not done."]))        # a keyword pop REPLACES the caption for a beat
        self.assertTrue(CP.repeats('our own delivery', ['in our own delivery.']))
        self.assertTrue(CP.repeats('like a new hire', ["Honestly, that's what I want from a new hire."]))
        self.assertTrue(CP.repeats('SAY IT', ["it's finished when you say it's finished."]))
        self.assertFalse(CP.repeats('the rule:', ['for my agents.']))
        self.assertFalse(CP.repeats('the fix:', ['Every two weeks.']))
        self.assertFalse(CP.repeats('', ['anything']))

    def test_a_struck_headline_keeps_its_time(self):
        # the strike crosses out the old idea later in the line: cutting the headline to a beat would lose the joke
        spec = self.build({'type': 'headline', 'text': 'OUR OWN DELIVERY', 'place': 'top', 'at': {'pick': 0, 'word': 'our'}},
                          {'type': 'strike', 'target': 0, 'at': {'pick': 0, 'word': 'delivery.'}})
        head = spec['items'][0]
        self.assertGreater(head['t1'] - head['t0'], CP.SWAP_MAX)


class FaceSampleTest(unittest.TestCase):
    def test_every_shot_gets_its_samples_even_a_short_one(self):
        shots = [{'src_in': 10.0, 'src_out': 12.4}, {'src_in': 12.4, 'src_out': 12.5}, {'src_in': 30.0, 'src_out': 31.0}]
        ks = F.shot_samples(shots, 10.0, 110)                        # 22 s of samples, 5 a second
        self.assertEqual(ks[0], list(range(0, 12)))
        self.assertEqual(len(ks[1]), 1)                              # 0.1 s long: the nearest sample, not nothing
        self.assertEqual(ks[2], list(range(100, 105)))
        self.assertTrue(all(0 <= k < 110 for row in ks for k in row))

    def test_layout_uses_extremes_the_crop_uses_medians(self):
        found = [{'k': k, 'x0': 300, 'y0': y0, 'x1': 760, 'y1': y0 + 600, 'eye_y': y0 + 210, 'mouth_y': y0 + 470, 'luma': 0.5}
                 for k, y0 in enumerate((400, 420, 380, 500, 410))]
        s = F.summarize(found, 5)
        self.assertEqual(s['top'], 380)                              # the highest the head got
        self.assertEqual(s['chin'], 1100)                            # the lowest the chin got
        self.assertEqual(s['cy'], 410 + 300)                         # the median, for the crop
        self.assertEqual(len(s['track']), 5)

    def test_a_face_seen_once_in_six_samples_is_not_a_face(self):
        one = [{'k': 0, 'x0': 0, 'y0': 0, 'x1': 10, 'y1': 10, 'eye_y': 3, 'mouth_y': 8, 'luma': 0.5}]
        self.assertIsNone(F.summarize(one, 6))


if __name__ == '__main__':
    unittest.main()
