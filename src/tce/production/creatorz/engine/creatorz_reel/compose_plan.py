"""Moments -> a timed spec (pure Python, tested): what shows when, on which layer, where, with which sound.
Also the C1 caption line breaker (English + Hebrew) and the sky-text occlusion rule."""
import re

from . import layout
from .plan import resolve, cue_pick, CueError

W, H = layout.W, layout.H
CAP_Y = layout.CAP_Y              # C1 captions with no face found: chest height, 62% of 1920
SCENES = ('card_grid', 'card_list', 'card_stat', 'insert')   # full-screen cutaways
SWAP_MAX = 1.2                    # a headline that takes the caption line holds it for one beat
PRE_ROLL = 0.4                    # a caption may show this long before its first word is said
STAT_HOLD, INSERT_HOLD, INSERT_MAX = 1.6, 1.5, 4.0
OCCLUDE_LIMIT = 0.20              # sky text may lose at most 20% of its ink to the speaker in ANY frame
LETTER_LIMIT = 0.35               # ...and no single letter more than 35% ('NOT DONE.' lost its T at 12.5% overall)

WEAK = {
    'en': {'a', 'an', 'the', 'to', 'of', 'i', 'my', 'and', 'it', 'is', 'that', 'so', 'he', 'she', 'you', 'what',
           'about', 'for', 'in', 'on', 'at', 'with', 'your', 'our', 'their', 'this', 'but', 'or', 'if', 'we', 'they'},
    # the skill: Hebrew lines never end on של / את; plus the other short function words
    'he': {'של', 'את', 'עם', 'על', 'אל', 'כי', 'אם', 'או', 'גם', 'זה', 'אבל', 'ש', 'מה', 'לא', 'כל', 'יותר', 'הכי'},
}
NUM = re.compile(r'^[\d.,%$₪]+$')


def bare(t):
    return re.sub(r"[^\w']", '', t.lower())


def chunk_words(texts, lang='en', max_words=3, max_chars=16):
    """C1 phrase captions: 2-4 words on one line. Break after punctuation; never end a line on a weak word;
    a number stays with the word after it. Returns [(i0, i1_exclusive), ...]."""
    weak = WEAK.get(lang, WEAK['en'])
    out, i, n = [], 0, len(texts)
    while i < n:
        rest = n - i
        take = rest if (rest <= 4 and sum(len(t) for t in texts[i:]) <= max_chars) else min(max_words, rest)
        if rest - take == 1 and take < 4 and sum(len(t) for t in texts[i:]) <= max_chars + 6:
            take = rest                                   # no orphan single word at the end
        elif (take < 4 and i + take < n and re.search(r'[.,?!:;]$', texts[i + take])
              and not any(re.search(r'[.,?!:;]$', t) for t in texts[i:i + take])
              and sum(len(t) for t in texts[i:i + take + 1]) <= max_chars + 4):
            take += 1                                     # the word that ends the sentence joins its line ("afford it.")
        j = i + take
        for k in range(i, j - 1):                         # punctuation closes the line
            if re.search(r'[.,?!:;]$', texts[k]):
                j = k + 1
                break
        while (j - i > 1 and j < n and not re.search(r'[.,?!:;]$', texts[j - 1])
               and (bare(texts[j - 1]) in weak or NUM.match(texts[j - 1]))):
            j -= 1                                        # weak word or a number moves to the next line
        out.append((i, j))
        i = j
    return out


def captions(shots, lang='en'):
    caps = []
    for s in shots:
        ws = s['owords']
        for n, (i0, i1) in enumerate(chunk_words([w['text'] for w in ws], lang)):
            t0 = ws[i0]['s']
            if n == 0 and t0 - s['out_in'] <= PRE_ROLL:      # a shot opens WITH its caption: the frames between the cut
                t0 = s['out_in']                              # and the first word used to blink empty (10-Nov)
            caps.append({'t0': t0, 'text': ' '.join(w['text'] for w in ws[i0:i1]), 'shot_end': s['out_out']})
    for k, c in enumerate(caps):
        nxt = caps[k + 1]['t0'] if k + 1 < len(caps) else shots[-1]['out_out']
        c['t1'] = min(nxt, c['shot_end'])
    if caps:
        caps[0]['t0'] = 0.0
    return caps


def hidden_shares(ink, hid, solid, solid_hid, letters):
    """(share of all ink hidden, share of the WORST letter hidden), from per-column sums of the text image: ink and
    hid count all ink (glow too), solid and solid_hid only solid strokes. letters = non-space characters, split
    evenly across the solid width. Pure python: compose sums the columns with numpy."""
    tot = sum(ink)
    overall = sum(hid) / tot if tot > 0 else 0.0
    cols = [x for x, s in enumerate(solid) if s > 0]
    if not cols or letters < 1:
        return overall, overall
    x0, x1 = cols[0], cols[-1] + 1
    edges = [round(x0 + (x1 - x0) * k / letters) for k in range(letters + 1)]
    per = []
    for a, b in zip(edges, edges[1:]):
        s = sum(solid[a:b])
        if s > 0:
            per.append(sum(solid_hid[a:b]) / s)
    return overall, max(per) if per else overall


def content_words(text, lang='en'):
    weak = WEAK.get(lang, WEAK['en'])
    return [w for w in (bare(t) for t in str(text).split()) if w and w not in weak]


TAG_HITS = 2                      # a chapter tag naming the word he says ("the rule:") is the style; two words is a repeat


def repeats(text, caption_texts, lang='en', share=0.6, min_hits=1):
    """True when text on screen says what a caption showing with it already says: most of its meaningful words, and at
    least `min_hits` of them, are in the caption. 11-Nov, Ziv at 0:06: the tag "our own delivery" sat right above "in
    our own delivery." ("its weird to show twice the same caption"). For a headline one keyword counts: the skill's
    escalation REPLACES the caption for a beat. A tag needs TAG_HITS: a one-word chapter label is the style."""
    mine = content_words(text, lang)
    if not mine:
        return False
    said = {w for c in caption_texts for w in content_words(c, lang)}
    hits = sum(1 for w in mine if w in said)
    return hits >= min_hits and hits / len(mine) >= share


def drop_covered(drawn):
    """drawn: [{'kind', 'box': [x0, y0, x1, y1]}] for one frame's front items, scenes included. A scene (a card, a
    picture) hides any other item its box meets, never text over text (demo 3's tag showed through the list card,
    10-Nov). A full-screen scene therefore hides everything but the captions."""
    cards = [d['box'] for d in drawn if d['kind'] in SCENES]

    def meets(b, c):
        return b[0] < c[2] and c[0] < b[2] and b[1] < c[3] and c[1] < b[3]
    return [d for d in drawn if d['kind'] in SCENES or not any(meets(d['box'], c) for c in cards)]


def decide_layer(fractions, limit=OCCLUDE_LIMIT):
    """sky text stays behind the head only if no frame hides more than `limit` of its ink; else it goes to the
    front (a handheld head rises mid-shot and ate 'WEE__ SLOT' on 10-Nov). Each entry is a share or an
    (overall, worst letter) pair from hidden_shares."""
    if not fractions:
        return 'top'
    overall = max(f[0] if isinstance(f, tuple) else f for f in fractions)
    letter = max(f[1] if isinstance(f, tuple) else 0.0 for f in fractions)
    return 'sky' if overall <= limit and letter <= LETTER_LIMIT else 'top'


def _until(m, shots, t0):
    if 'until' in m:
        return resolve(m['until'], shots, cue_pick(m.get('at')))
    p = cue_pick(m.get('at'))
    if p is not None:
        return resolve({'pick': p, 'at': 'end'}, shots)
    s = next(s for s in shots if s['out_in'] - 1e-6 <= t0 < s['out_out'] + 1e-6)
    return s['out_out']


def _face(s):
    f = s.get('face')
    return f if isinstance(f, dict) and 'chin' in f else None      # an old edit.json kept a list here


def _over(shots, t0, t1):
    return [s for s in shots if s['out_in'] < t1 - 0.02 and t0 < s['out_out'] - 0.02] or \
           [s for s in shots if s['out_in'] - 1e-6 <= t0 < s['out_out'] + 1e-6]


def face_union(shots):
    """the face across several shots, at its worst for layout: the highest top, the lowest chin and mouth, the widest
    sides. None when no shot has a face."""
    fs = [f for f in (_face(s) for s in shots) if f]
    if not fs:
        return None
    return {'top': min(f['top'] for f in fs), 'chin': max(f['chin'] for f in fs), 'left': min(f['left'] for f in fs),
            'right': max(f['right'] for f in fs), 'mouth': max(f['mouth'] for f in fs),
            'eye_y': min(f['eye_y'] for f in fs), 'fh': max(f['fh'] for f in fs), 'fw': max(f['fw'] for f in fs)}


def apply_slot(it, spec):
    """A front headline takes its slot. One that has to take the caption line holds it for a beat, captions off."""
    if it['slot'][0] == 'swap':
        it['t1'] = round(min(it['t1'], it['t0'] + SWAP_MAX), 3)
        spec['hide_cap'].append((it['t0'], it['t1']))


def build(plan, edit):
    shots = edit['shots']
    lang = edit.get('lang', plan.get('lang', 'en'))
    items, sfx, flashes, whips, dropped = [], [], [], [], []
    rtl = lang == 'he'
    lines = layout.caption_lines([_face(s) for s in shots])
    spec = {'items': items, 'hide_cap': [], 'cap_lines': [(s['out_in'], s['out_out'], y) for s, y in zip(shots, lines)]}
    caps = captions(shots, lang)
    struck = {m.get('target') for m in plan['moments'] if m.get('type') == 'strike'}

    def said_with(t0, t1):
        return [c['text'] for c in caps if c['t0'] < t1 - 0.02 and t0 < c['t1'] - 0.02]

    def sound(t, name, gain):
        if name:
            sfx.append((round(max(0.0, t), 3), name, float(gain)))

    def line_for(sel):
        return max(y for s, y in zip(shots, lines) if s in sel)

    for i, m in enumerate(plan['moments']):
        kind = m['type']
        try:
            if kind == 'riser':
                t = resolve(m['into'], shots)
                sound(max(0.0, t - 1.40), 'riser', m.get('gain', -8))
                continue
            if kind == 'sound':
                sound(resolve(m['at'], shots), m['name'], m.get('gain', -6))
                continue
            if kind == 'flash':
                t = resolve(m['at'], shots)
                flashes.append(round(t, 3))
                sound(t, m.get('sound', 'flash'), m.get('gain', -6))
                continue
            if kind == 'whip':
                t = resolve(m['at'], shots)
                whips.append(round(t, 3))
                sound(t - 0.08, m.get('sound', 'whoosh'), m.get('gain', -3))
                continue
            t0 = resolve(m['at'], shots)
            t1 = _until(m, shots, t0)
        except CueError as e:
            raise CueError(f'moment {i} ({kind}): {e}')
        if t1 <= t0:
            raise CueError(f'moment {i} ({kind}): ends ({t1:.2f}) before it starts ({t0:.2f})')
        it = {'idx': i, 'kind': kind, 't0': round(t0, 3), 't1': round(t1, 3), 'm': m, 'entry': m.get('entry', 7)}
        sel = _over(shots, it['t0'], it['t1'])
        it['face'], it['cap_y'] = face_union(sel), line_for(sel)
        snd, gain = m.get('sound', 'whoosh'), m.get('gain', -6)
        if kind == 'headline':
            place = m.get('place', 'sky')
            it['slot'] = layout.headline_slot(it['face'], it['cap_y'], place)
            # behind the head only where there is sky to stand in: on a tight selfie the head would hide it all
            roomy = it['face'] is None or it['slot'][0] == 'above'
            it['layer'] = 'sky' if (place == 'sky' and roomy and not m.get('pos')) else 'front'
            it['pos'] = m.get('pos') or 'auto'
            if it['layer'] == 'front' and not m.get('pos'):
                apply_slot(it, spec)
            # the same words as the caption: the headline takes the caption's place for a beat, never both at once.
            # A struck headline is the old idea being crossed out, not a repeat: it keeps its time
            if i not in struck and (it['t0'], it['t1']) not in spec['hide_cap'] and repeats(m.get('text', ''), said_with(it['t0'], it['t1']), lang):
                it['t1'] = round(min(it['t1'], it['t0'] + SWAP_MAX), 3)
                it['repeat'] = True
                spec['hide_cap'].append((it['t0'], it['t1']))
        elif kind == 'strike':
            it['layer'], it['target'], it['entry'] = 'follow', m['target'], 0
            snd, gain = m.get('sound', 'whoosh'), m.get('gain', -10)
        elif kind == 'pair':
            it['layer'] = 'front'
            if 'bold_at' in m:
                it['bold_t'] = round(resolve(m['bold_at'], shots, cue_pick(m['at'])), 3)
                sound(it['bold_t'], snd, gain)
                gain = m.get('light_gain', -12)
            spec['hide_cap'].append((it['t0'], it['t1']))
        elif kind == 'badge':
            it['layer'], it['side'] = 'front', m.get('side', 'right' if rtl else 'left')
            it['pos'] = m.get('pos') or 'auto'
        elif kind == 'bubble':
            it['layer'], it['entry'] = 'front', m.get('entry', 6)
            spec['hide_cap'].append((it['t0'], it['t1']))
        elif kind == 'tag':
            # a tag names what comes next; one that repeats the line under it says the same thing twice: not shown
            if repeats(m.get('text', ''), said_with(it['t0'], it['t1']), lang, min_hits=TAG_HITS):
                dropped.append({'moment': i, 'kind': kind, 'text': m.get('text', ''), 'why': 'repeats the caption'})
                continue
            it['layer'], it['entry'], it['rtl'] = 'front', 5, rtl
            it['pos'] = m.get('pos') or 'auto'
            gain = m.get('gain', -12)
        elif kind in SCENES:
            it['layer'], it['entry'] = 'scene', 5
            it['bottom'] = min(y for s, y in zip(shots, lines) if s in sel) - 150      # the captions run under it
            snd = None
            if kind in ('card_grid', 'card_list'):
                ticks = m.get('ticks', 'spread')
                n = len(m.get('filled', [])) if kind == 'card_grid' else len(m.get('items', []))
                if ticks == 'spread':
                    span = it['t1'] - it['t0']
                    tt = [it['t0'] + 0.2 + k * min(0.32, (span - 0.4) / max(1, n)) for k in range(n)]
                else:
                    tt = [resolve(c, shots, cue_pick(m.get('at'))) for c in ticks]
                it['ticks'] = [round(x, 3) for x in tt]
                for x in it['ticks']:
                    sound(x, 'tick', m.get('tick_gain', -6))
                it['words'] = card_words(m)
                it['windows'] = layout.card_windows(it['t0'], it['t1'], it['ticks'], it['words'])
            elif kind == 'card_stat':
                it['windows'] = [(it['t0'], round(min(it['t1'], it['t0'] + m.get('hold', STAT_HOLD)), 3))]
            else:
                hold = min(INSERT_MAX, it['t1'] - it['t0']) if 'until' in m else m.get('hold', INSERT_HOLD)
                it['windows'] = [(it['t0'], round(min(it['t1'], it['t0'] + hold), 3))]
            for k, (a, _b) in enumerate(it['windows']):         # the first cut to a scene flashes; a return is a plain
                if k == 0:                                        # cut with a soft whoosh (four flashes in ten seconds
                    flashes.append(a)                             # were part of "it transitions too fast", 11-Nov)
                    sound(a, 'flash', m.get('flash_gain', -8))
                else:
                    sound(a, 'whoosh', -12)
        sound(it['t0'], snd, gain)
        items.append(it)
    spec.update(sfx=sorted(sfx), flashes=sorted(set(flashes)), whips=sorted(whips), captions=caps, dropped=dropped,
                duration=edit['duration'])
    return spec


def card_words(m):
    """how many words a card asks the viewer to read"""
    if m['type'] == 'card_list':
        return sum(len(str(i).split()) for i in m.get('items', []))
    if m['type'] == 'card_grid':
        return len(str(m.get('title', '')).split()) + int(m.get('cells', 4))
    return len(str(m.get('text', '')).split()) + len(str(m.get('label', '')).split())


def short_cards(items):
    """cards whose first look is shorter than it takes to read them (only when the card's own line is that short)"""
    out = []
    for it in items:
        if it.get('kind') in ('card_list', 'card_grid') and it.get('windows'):
            a, b = it['windows'][0]
            need = layout.read_time(it.get('words', 0))
            if b - a < min(need, it['t1'] - it['t0']) - 1e-3 or (it['t1'] - it['t0'] < need - 1e-3):
                out.append({'what': it['kind'], 't': round(a, 2), 'shown': round(b - a, 2), 'needs': round(need, 2)})
    return out


def sky_intervals(plan, edit):
    spec = build(plan, edit)
    return [(it['t0'], it['t1']) for it in spec['items'] if it.get('layer') == 'sky']

