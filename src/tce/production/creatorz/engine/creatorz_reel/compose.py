"""Stage 3: draw the spec over base.mp4 -> overlay.mp4 (no audio) + events.json (sound cues, flashes, captions,
layer decisions). `stills` mode renders chosen times to PNG for a look before the full render."""
import json
import os
import subprocess

from . import compose_plan as cp
from . import draw

W, H = cp.W, cp.H


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _mask(work, fi):
    from PIL import Image, ImageFilter
    p = os.path.join(work, 'masks', f'f{fi:05d}.png')
    if not os.path.exists(p):
        return None
    return Image.open(p).convert('L').resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.5))


def _head_top(mask):
    import numpy as np
    if mask is None:
        return 330
    m = np.asarray(mask)
    rows = np.where((m[:, W // 4: 3 * W // 4] > 128).sum(1) > 40)[0]
    return int(rows[0]) if len(rows) else 330


def _occluded(img, cx, cy, mask, letters):
    """(share of the text's ink the speaker's mask covers, share of its worst letter) at this position"""
    import numpy as np
    a = np.asarray(img.split()[-1], dtype=np.float32) / 255.0
    x0, y0 = int(cx - img.width / 2), int(cy - img.height / 2)
    m = np.zeros_like(a)
    mx0, my0, mx1, my1 = max(0, x0), max(0, y0), min(W, x0 + img.width), min(H, y0 + img.height)
    if mx1 > mx0 and my1 > my0:
        m[my0 - y0:my1 - y0, mx0 - x0:mx1 - x0] = np.asarray(mask, dtype=np.float32)[my0:my1, mx0:mx1] / 255.0
    solid = (a > 0.5).astype(np.float32)
    return cp.hidden_shares(a.sum(0).tolist(), (a * m).sum(0).tolist(), solid.sum(0).tolist(),
                            (solid * m).sum(0).tolist(), letters)


def _images(spec, lang):
    """static image per item (or a function of t for cards / strikes / pairs)"""
    for it in spec['items']:
        m, k = it['m'], it['kind']
        if k == 'headline':
            size = m.get('size') or {'sky': 240, 'top': 170}.get(m.get('place', 'sky'), 150)
            img = draw.styled(m['text'], m.get('color', 'white'), m.get('look', 'plain'), size, 1000 if m.get('place', 'sky') in ('sky', 'top') else 940)
            it['img'] = draw.with_check(img) if m.get('check') else img
        elif k == 'pair':
            light = draw.text_img(m['light'], draw.font(72, 400), draw.WHITE, margin=30)
            face, halo = draw.COLORS.get(m.get('color', 'white'), draw.COLORS['white'])
            bold = draw.text_img(m['bold'], draw.fit(m['bold'], 900, m.get('size', 124), 940), face, glow=halo, glow_r=16, margin=40)
            it['light'], it['img'] = light, draw.stack([light, bold], gap=-40)
        elif k == 'badge':
            it['img'] = draw.badge(m['text'], m.get('color', 'green'))
        elif k == 'bubble':
            it['img'] = draw.bubble(m['lines'])
        elif k == 'tag':
            # Amatic SC's Hebrew is hand-drawn but thin: thicken it so the tag reads at phone size
            it['img'] = draw.text_img(m['text'], draw.hand(84, m['text']), draw.COLORS['yellow'][0], margin=30,
                                      stroke=3 if draw.is_rtl(m['text']) else 0)
        elif k == 'card_grid':
            it['cache'] = {}
            it['make'] = (lambda m: (lambda n: draw.grid_card(m['title'], m.get('title_color', 'white'), m.get('cells', 4),
                                                              m.get('filled', []), n, m.get('labels', 'שבוע {n}' if lang == 'he' else 'Week {n}'),
                                                              m.get('empty_label', 'פנוי' if lang == 'he' else 'free'))))(m)
        elif k == 'card_list':
            it['cache'] = {}
            it['make'] = (lambda m: (lambda n: draw.list_card(m['items'], n)))(m)


def run(plan, stills=None):
    from PIL import Image, ImageDraw
    work = plan['work']
    edit = json.load(open(os.path.join(work, 'edit.json'), encoding='utf8'))
    fps, dur = edit['fps'], edit['duration']
    nf = int(round(dur * fps))
    lang = edit.get('lang', 'en')
    spec = cp.build(plan, edit)
    _images(spec, lang)
    items = spec['items']
    by_idx = {it['idx']: it for it in items}
    # place sky text from the first frame's head top, then check EVERY frame for occlusion
    decisions = []
    for it in items:
        if it['layer'] != 'sky':
            continue
        f0 = int(it['t0'] * fps)
        mk0 = _mask(work, f0)
        if it['pos'] == 'auto':
            top = _head_top(mk0)
            h = it['img'].height
            it['pos'] = [W // 2, max(int(top - h / 2 + h * 0.15), h // 2 + 60)]
        fr = []
        letters = max(1, sum(1 for ch in str(it['m'].get('text', '')) if not ch.isspace()))
        for fi in range(f0, int(it['t1'] * fps)):
            mk = mk0 if fi == f0 else _mask(work, fi)
            if mk is None:
                fr = []
                break
            fr.append(_occluded(it['img'], it['pos'][0], it['pos'][1], mk, letters))
        it['layer'] = cp.decide_layer(fr)
        if it['layer'] == 'top':
            it['layer'] = 'front'
            it['pos'] = [W // 2, max(cp.TOP_Y, it['img'].height // 2 + 20)]
        decisions.append({'moment': it['idx'], 'text': it['m'].get('text'), 'layer': it['layer'],
                          'max_hidden': round(max(f[0] for f in fr), 3) if fr else None,
                          'worst_letter': round(max(f[1] for f in fr), 3) if fr else None})
    for it in items:                                   # strikes follow their target's final layer and spot
        if it['kind'] == 'strike':
            tgt = by_idx.get(it['target'])
            if not tgt or tgt['kind'] != 'headline':
                raise ValueError(f"strike moment {it['idx']}: target {it['target']} is not a headline moment")
            it['layer'], it['pos'], it['tgt'] = tgt['layer'], tgt['pos'], tgt
    caps = spec['captions']
    cap_cache = {}

    def cap_img(txt):
        if txt not in cap_cache:
            cap_cache[txt] = draw.text_img(txt, draw.fit(txt, 800, 88, 810), draw.WHITE, margin=40)
        return cap_cache[txt]

    def place(frame, img, cx, cy, t, t0, entry):
        if entry and t - t0 < entry / fps:
            import numpy as np
            p = _ease((t - t0) * fps / entry)
            sc = 0.72 + 0.28 * p
            im = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BILINEAR)
            if (1 - p) * 10 > 0.5:
                from PIL import ImageFilter
                im = im.filter(ImageFilter.GaussianBlur((1 - p) * 10))
            a = np.array(im)
            a[..., 3] = (a[..., 3] * p).astype(np.uint8)
            im = Image.fromarray(a, 'RGBA')
        else:
            im = img
        frame.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))

    def item_img(it, t):
        k = it['kind']
        if k in ('card_grid', 'card_list'):
            n = sum(1 for x in it['ticks'] if t >= x)
            if n not in it['cache']:
                it['cache'][n] = it['make'](n)
            return it['cache'][n]
        if k == 'pair' and 'bold_t' in it and t < it['bold_t']:
            return it['light']
        if k == 'strike':
            tw, th = it['tgt']['img'].size
            img = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
            p = min(1.0, max(0.0, (t - it['t0']) / 0.16))
            if p > 0:
                ImageDraw.Draw(img).line((40, th // 2 + 4, 40 + (tw - 80) * p, th // 2 + 4 - 6 * p), fill=draw.COLORS['red'][0] + (255,), width=max(12, th // 12))
            return img
        return it['img']

    def item_pos(it, img):
        if it['kind'] in ('card_grid', 'card_list'):
            return W // 2, cp.CARD_Y0 - 40 + img.height // 2
        if it['kind'] == 'pair' and 'bold_t' in it and img is it.get('light'):
            return it['pos'][0], cp.CAP_Y
        return it['pos']

    want = None
    if stills:
        want = {int(round(float(x) * fps)) for x in stills}
        os.makedirs(os.path.join(work, 'stills'), exist_ok=True)
    dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', os.path.join(work, 'base.mp4'), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                           stdout=subprocess.PIPE)
    enc = None if want else subprocess.Popen(
        ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(fps), '-i', '-',
         '-c:v', 'libx264', '-crf', '15', '-preset', 'medium', '-pix_fmt', 'yuv420p', os.path.join(work, 'overlay.mp4')],
        stdin=subprocess.PIPE)
    white = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    for fi in range(nf):
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        if want is not None and fi not in want:
            continue
        t = fi / fps + 1e-4
        base = Image.frombytes('RGB', (W, H), buf).convert('RGBA')
        frame = base.copy()
        act = [it for it in items if it['t0'] <= t < it['t1']]
        sky = [it for it in act if it['layer'] == 'sky']
        for it in sky:
            img = item_img(it, t)
            place(frame, img, *item_pos(it, img), t, it['t0'], it['entry'])
        if sky:
            mk = _mask(work, fi)
            if mk is not None:
                frame = Image.composite(base, frame, mk)
        drawn = []
        for it in act:
            if it['layer'] in ('front', 'card'):
                img = item_img(it, t)
                cx, cy = item_pos(it, img)
                drawn.append({'kind': it['kind'], 'box': [cx - img.width / 2, cy - img.height / 2, cx + img.width / 2,
                                                          cy + img.height / 2], 'it': it, 'img': img, 'xy': (cx, cy)})
        for d in cp.drop_covered(drawn):
            place(frame, d['img'], *d['xy'], t, d['it']['t0'], d['it']['entry'])
        if not any(a <= t < b for a, b in spec['hide_cap']):
            c = next((c for c in caps if c['t0'] <= t < c['t1']), None)
            if c:
                y = next((yy for a, b, yy in spec['cap_y'] if a <= t < b), cp.CAP_Y)
                ci = cap_img(c['text'])
                frame.alpha_composite(ci, (int(W / 2 - ci.width / 2), int(y - ci.height / 2)))
        for ft in spec['flashes']:
            k = int(round((t - ft) * fps))
            if 0 <= k < 3:
                frame = Image.blend(frame, white, (0.85, 0.45, 0.15)[k])
        if want is not None:
            frame.convert('RGB').save(os.path.join(work, 'stills', f't{fi / fps:06.2f}.png'))
            continue
        enc.stdin.write(frame.convert('RGB').tobytes())
        if fi % 200 == 0:
            print(f'compose: frame {fi}/{nf}', flush=True)
    if enc:
        enc.stdin.close()
        enc.wait()
    dec.stdout.close()
    dec.wait()
    events = {'sfx': spec['sfx'], 'flashes': spec['flashes'], 'moments': sorted({it['t0'] for it in items}),
              'ticks': sorted({x for it in items for x in it.get('ticks', [])}),
              'captions': [(round(c['t0'], 2), round(c['t1'], 2), c['text']) for c in caps], 'sky': decisions}
    json.dump(events, open(os.path.join(work, 'events.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    for d in decisions:
        print(f"compose: sky '{d['text']}' -> {d['layer']} (max hidden {d['max_hidden']}, worst letter {d['worst_letter']})")
    return events
