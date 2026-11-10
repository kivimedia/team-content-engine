"""Moments -> a timed spec (pure Python, tested): what shows when, on which layer, where, with which sound.
Also the C1 caption line breaker (English + Hebrew) and the sky-text occlusion rule."""
import re

from .plan import resolve, cue_pick, CueError

W, H = 1080, 1920
CAP_Y = 1190                      # C1 captions: chest height, 62% of 1920
CARD_X0, CARD_X1, CARD_Y0 = 90, 990, 880
TOP_Y = 190
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
        for i0, i1 in chunk_words([w['text'] for w in ws], lang):
            caps.append({'t0': ws[i0]['s'], 'text': ' '.join(w['text'] for w in ws[i0:i1]), 'shot_end': s['out_out']})
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


def drop_covered(drawn):
    """drawn: [{'kind', 'box': [x0, y0, x1, y1]}] for one frame's front items, cards included. A card hides any other
    item its box meets, never text over text (demo 3's tag showed through the list card, 10-Nov)."""
    cards = [d['box'] for d in drawn if d['kind'] in ('card_grid', 'card_list')]

    def meets(b, c):
        return b[0] < c[2] and c[0] < b[2] and b[1] < c[3] and c[1] < b[3]
    return [d for d in drawn if d['kind'] in ('card_grid', 'card_list') or not any(meets(d['box'], c) for c in cards)]


def decide_layer(fractions, limit=OCCLUDE_LIMIT):
    """sky text stays behind the head only if no frame hides more than `limit` of its ink; else it goes to the
    front at the top (a handheld head rises mid-shot and ate 'WEE__ SLOT' on 10-Nov). Each entry is a share or an
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


def build(plan, edit):
    shots = edit['shots']
    lang = edit.get('lang', plan.get('lang', 'en'))
    items, sfx, flashes, hide, cap_y = [], [], [], [], []
    rtl = lang == 'he'

    def sound(t, name, gain):
        if name:
            sfx.append((round(t, 3), name, float(gain)))

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
            t0 = resolve(m['at'], shots)
            t1 = _until(m, shots, t0)
        except CueError as e:
            raise CueError(f'moment {i} ({kind}): {e}')
        if t1 <= t0:
            raise CueError(f'moment {i} ({kind}): ends ({t1:.2f}) before it starts ({t0:.2f})')
        it = {'idx': i, 'kind': kind, 't0': round(t0, 3), 't1': round(t1, 3), 'm': m, 'entry': m.get('entry', 6)}
        snd, gain = m.get('sound', 'whoosh'), m.get('gain', -6)
        if kind == 'headline':
            place = m.get('place', 'sky')
            it['layer'] = 'sky' if place == 'sky' else 'front'
            it['pos'] = m.get('pos') or ({'chest': [W // 2, CAP_Y], 'low': [W // 2, CAP_Y + 60], 'top': [W // 2, TOP_Y]}.get(place, 'auto'))
            if place in ('chest', 'low'):
                hide.append((it['t0'], it['t1']))
        elif kind == 'strike':
            tgt = m['target']
            it['layer'] = 'follow'
            it['target'] = tgt
            it['entry'] = 0
            snd, gain = m.get('sound', 'whoosh'), m.get('gain', -10)
        elif kind == 'pair':
            it['layer'], it['pos'] = 'front', [W // 2, CAP_Y + 25]
            if 'bold_at' in m:
                it['bold_t'] = round(resolve(m['bold_at'], shots, cue_pick(m['at'])), 3)
                sound(it['bold_t'], snd, gain)
                gain = m.get('light_gain', -12)
            hide.append((it['t0'], it['t1']))
        elif kind == 'badge':
            side = m.get('side', 'right' if rtl else 'left')
            it['layer'], it['pos'] = 'front', m.get('pos') or ([150, 420] if side == 'left' else [930, 420])
        elif kind == 'bubble':
            it['layer'], it['pos'] = 'front', [W // 2, CAP_Y - 20]
            it['entry'] = m.get('entry', 5)
            hide.append((it['t0'], it['t1']))
        elif kind == 'tag':
            it['layer'], it['pos'] = 'front', m.get('pos') or ([830, CAP_Y - 80] if rtl else [250, CAP_Y - 80])
            it['entry'] = 4
            gain = m.get('gain', -12)
        elif kind in ('card_grid', 'card_list'):
            it['layer'] = 'card'
            it['entry'] = 4
            flashes.append(it['t0'])
            sound(it['t0'], 'flash', m.get('flash_gain', -8))
            snd = None
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
            cap_y.append((it['t0'], it['t1'], CARD_Y0))
        sound(it['t0'], snd, gain)
        items.append(it)
    return {'items': items, 'sfx': sorted(sfx), 'flashes': sorted(flashes), 'hide_cap': hide, 'cap_y': cap_y,
            'captions': captions(shots, lang), 'duration': edit['duration']}


def sky_intervals(plan, edit):
    spec = build(plan, edit)
    return [(it['t0'], it['t1']) for it in spec['items'] if it.get('layer') == 'sky']
