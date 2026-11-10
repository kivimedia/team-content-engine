"""The reel plan (creatorz-reel/1): load, defaults, word cues. Pure Python (no numpy) so tests run under `python -I`."""
import json
import os
import re

SCHEMA = 'creatorz-reel/1'
DEFAULTS = {
    'fps': 25, 'lang': 'en', 'grade': 'golden', 'bed': None, 'bed_gain_db': -15.0,
    'work': 'work', 'out': 'reel.mp4', 'thr_db': -40.0, 'gap_max': 0.28, 'min_run': 0.12,
    'pad_in': 0.05, 'pad_out': 0.08, 'wide': None, 'punchline': None, 'moments': [], 'exact': False,
}
MOMENT_TYPES = {'headline', 'pair', 'badge', 'bubble', 'tag', 'strike', 'card_grid', 'card_list', 'flash', 'riser', 'sound'}


class PlanError(ValueError):
    pass


def load(path):
    with open(path, encoding='utf8') as f:
        plan = json.load(f)
    return normalize(plan, os.path.dirname(os.path.abspath(path)))


def normalize(plan, base='.'):
    if plan.get('schema') != SCHEMA:
        raise PlanError(f"plan schema must be '{SCHEMA}', got {plan.get('schema')!r}")
    out = dict(DEFAULTS)
    out.update(plan)
    for key in ('source', 'words'):
        if not out.get(key):
            raise PlanError(f'plan needs "{key}"')
    for key in ('source', 'words', 'bed', 'work', 'out'):
        if out.get(key) and not os.path.isabs(out[key]):
            out[key] = os.path.normpath(os.path.join(base, out[key]))
    if not out.get('picks'):
        raise PlanError('plan needs "picks": the lines to keep, in order')
    for i, m in enumerate(out['moments']):
        if m.get('type') not in MOMENT_TYPES:
            raise PlanError(f"moment {i}: unknown type {m.get('type')!r} (one of {sorted(MOMENT_TYPES)})")
    if out['lang'] not in ('en', 'he'):
        raise PlanError("lang must be 'en' or 'he'")
    return out


def pick_spans(picks, words, lead=0.12, tail=0.15):
    """Each pick is {"span": [a, b]} in source seconds or {"words": [i, j]} (word indexes, inclusive)."""
    spans = []
    for k, p in enumerate(picks):
        if 'span' in p:
            a, b = float(p['span'][0]), float(p['span'][1])
        elif 'words' in p:
            i, j = int(p['words'][0]), int(p['words'][1])
            if not (0 <= i <= j < len(words)):
                raise PlanError(f'pick {k}: word range {i}-{j} outside 0-{len(words) - 1}')
            a, b = words[i]['start_s'] - lead, words[j]['end_s'] + tail
        else:
            raise PlanError(f'pick {k}: needs "span" or "words"')
        if b <= a:
            raise PlanError(f'pick {k}: empty span {a}-{b}')
        spans.append((max(0.0, a), b))
    return spans


def norm(text):
    return re.sub(r"[^\w']", '', text.lower())


class CueError(ValueError):
    pass


def resolve(cue, shots, default_pick=None):
    """A cue names a moment on the OUTPUT timeline.
    {"pick": 3, "word": "price", "nth": 1, "edge": "start"|"end", "offset": 0.0}  - a word, searched ONLY inside pick 3
    {"pick": 3, "at": "start"|"end"}                                              - the pick's first or last frame
    a number                                                                      - output seconds
    Words are scoped to their pick on purpose: an unscoped "no," matched the hook's "a no" and ran 15 s (10-Nov)."""
    if isinstance(cue, (int, float)):
        return float(cue)
    if not isinstance(cue, dict):
        raise CueError(f'cue must be a number or an object, got {cue!r}')
    pick = cue.get('pick', default_pick)
    cand = [s for s in shots if s['pick'] == pick]
    if not cand:
        raise CueError(f'cue {cue}: pick {pick} has no shots')
    off = float(cue.get('offset', 0.0))
    if 'at' in cue:
        if cue['at'] == 'start':
            return cand[0]['out_in'] + off
        if cue['at'] == 'end':
            return cand[-1]['out_out'] + off
        raise CueError(f'cue {cue}: "at" must be start or end')
    if 'word' not in cue:
        raise CueError(f'cue {cue}: needs "word" or "at"')
    ws = [w for s in cand for w in s['owords']]
    key = norm(cue['word'])
    hits = [w for w in ws if norm(w['text']) == key]
    nth = int(cue.get('nth', 1))
    if len(hits) < nth:
        said = ' '.join(w['text'] for w in ws)
        raise CueError(f'cue word {cue["word"]!r} (#{nth}) not in pick {pick}: "{said}"')
    w = hits[nth - 1]
    return (w['e'] if cue.get('edge') == 'end' else w['s']) + off


def cue_pick(cue):
    return cue.get('pick') if isinstance(cue, dict) else None
