"""Stage 3: draw the spec over base.mp4 -> overlay.mp4 (no audio) + events.json (sound cues, flashes, captions,
layer decisions, the look report). `stills` mode renders chosen times to PNG for a look before the full render.
Where things go is decided by layout.py from each shot's face: nothing sits on the face or against the frame edge."""
import json
import os
import subprocess

from . import compose_plan as cp
from . import draw
from . import layout

W, H = cp.W, cp.H
WHIP = {-3: (31, 24), -2: (81, 70), -1: (181, 170), 0: (181, -170), 1: (81, -70), 2: (31, -24)}   # frame -> blur, slide
PAN_PX_S = 420                    # how fast a tall picture scrolls: a quick look, still readable


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


def _glyph_h(img):
    return img.height - 2 * img.info.get('pad', 0)


def _fit_band(make, size, band):
    """the biggest image from make(size) whose glyphs fit a band of `band` pixels"""
    img = make(size)
    for _ in range(4):
        gh = _glyph_h(img)
        if gh <= band or size <= 44:
            break
        size = max(44, int(size * band / gh) - 2)
        img = make(size)
    return img


def _headline(it):
    """image + spot for a headline by its slot: above the head, under the caption line, or on it for a beat"""
    m = it['m']

    def make(size):
        img = draw.styled(m['text'], m.get('color', 'white'), m.get('look', 'plain'), size)
        return draw.with_check(img) if m.get('check') else img
    if it['layer'] == 'sky':
        it['img'] = make(m.get('size') or 240)
        return
    if m.get('pos'):
        it['img'], it['pos'] = make(m.get('size') or 150), list(m['pos'])
        return
    kind, y0, y1 = it['slot']
    want = m.get('size') or {'above': 170, 'under': 132, 'swap': 150}[kind]
    img = _fit_band(make, min(want, {'above': 240, 'under': 132, 'swap': 150}[kind]), y1 - y0)
    gh = _glyph_h(img)
    cy = {'above': max(y0 + gh / 2, y1 - gh / 2), 'under': y0 + gh / 2, 'swap': it['cap_y']}[kind]
    it['img'], it['pos'] = img, [W // 2, round(cy)]


def _images(spec, lang):
    """image(s) and spot per item; scenes get a function of their tick count"""
    for it in spec['items']:
        m, k, fo, cap_y = it['m'], it['kind'], it.get('face'), it.get('cap_y', layout.CAP_Y)
        if k == 'headline':
            _headline(it)
        elif k == 'pair':
            light = draw.text_img(m['light'], draw.fit(m['light'], 800, 66, 800), draw.WHITE, margin=40, outline=3)
            band = layout.BOTTOM_SAFE - (cap_y + 52)
            it['stacked'] = band >= layout.PAIR_MIN
            # room under the caption line: the bold line lands below the light one. No room (a low chin): the bold
            # line takes the caption line from the light one, the pair told in time instead of in space
            bold = _fit_band(lambda size: draw.styled(m['bold'], m.get('color') or 'accent', 'extrude', size, 940),
                             min(m.get('size', 124), 124) if it['stacked'] else min(m.get('size', 150), 150),
                             band if it['stacked'] else 170)
            it['light'], it['img'] = light, bold
            it['pos'] = [W // 2, cap_y]
            it['bold_pos'] = [W // 2, round(cap_y + 52 + _glyph_h(bold) / 2)] if it['stacked'] else [W // 2, cap_y]
        elif k == 'badge':
            img = draw.badge(m['text'])
            it['img'] = img
            if it['pos'] == 'auto':
                it['pos'] = [round(v) for v in layout.side_spot(fo, img.width - 80, img.height - 80, it['side'], cap_y)]
        elif k == 'bubble':
            img = draw.bubble(m['lines'])
            tip = (fo['chin'] + 14) if fo else (cap_y - 190)
            room = layout.BOTTOM_SAFE + 20 - tip
            body = img.height - img.info['top'] - 50
            if body > room:                                    # three long lines under a low chin: shrink, never climb the face
                from PIL import Image
                kf = max(0.62, room / body)
                info = dict(img.info)
                img = img.resize((round(img.width * kf), round(img.height * kf)), Image.LANCZOS)
                img.info.update(pad=round(info['pad'] * kf), top=round(info['top'] * kf),
                                edges=tuple(round(v * kf) for v in info['edges']))
            it['img'] = img
            it['pos'] = [W // 2, round(tip - img.info['top'] + img.height / 2)]
        elif k == 'tag':
            face, _side = draw.accent()
            img = draw.text_img(m['text'], draw.hand(88, m['text']), face, margin=30, outline=2,
                                stroke=2 if draw.is_rtl(m['text']) else 0)
            it['img'] = img
            if it['pos'] == 'auto':
                x, y = (830 if it.get('rtl') else 250), cap_y - 92
                if fo and layout.meets(draw.glyph_box(img, x, y), layout.face_zone(fo)):
                    y = cap_y + 92
                gw, gh = img.width - 60, img.height - 60
                x, y = layout.clamp_box(x, y, gw, gh)
                it['pos'] = [round(x), round(y)]
        elif k == 'card_grid':
            it['cache'] = {}
            it['make'] = (lambda m, b: (lambda n: draw.grid_scene(
                m['title'], m.get('cells', 4), m.get('filled', []), n, m.get('labels', 'שבוע {n}' if lang == 'he' else 'Week {n}'),
                m.get('empty_label', 'פנוי' if lang == 'he' else 'free'), b)))(m, it['bottom'])
        elif k == 'card_list':
            it['cache'] = {}
            it['make'] = (lambda m, b: (lambda n: draw.list_scene(m['items'], n, b)))(m, it['bottom'])
        elif k == 'card_stat':
            it['cache'] = {0: draw.stat_scene(str(m['text']), m.get('label', ''), it['bottom'])}
        elif k == 'insert':
            it['layer_at'], it['covers'] = draw.picture_scene(m['src'], it['bottom'])


def _whip(base, k):
    """a whip pan across a cut: the outgoing frames smear and slide away, the incoming ones arrive the same way"""
    import numpy as np
    from PIL import Image
    kern, shift = WHIP[k]
    a = np.roll(np.asarray(base.convert('RGB'), dtype=np.float32), -shift, axis=1)
    c = np.cumsum(np.pad(a, ((0, 0), (kern // 2 + 1, kern // 2), (0, 0)), mode='edge'), axis=1)
    return Image.fromarray(((c[:, kern:, :] - c[:, :-kern, :]) / kern).astype(np.uint8)).convert('RGBA')


def _push(img, z, c):
    """An image zoomed by z about the point c, sub-pixel smooth (a slow push must not step a pixel at a time).
    OpenCV does it in a few milliseconds; Pillow's bicubic took 0.2 s a frame (10-Nov), so its fallback is bilinear."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        from PIL import Image
        return img.transform(img.size, Image.AFFINE, (1 / z, 0, c[0] * (1 - 1 / z), 0, 1 / z, c[1] * (1 - 1 / z)),
                             resample=Image.BILINEAR)
    from PIL import Image
    m = np.float32([[z, 0, c[0] * (1 - z)], [0, z, c[1] * (1 - z)]])
    out = cv2.warpAffine(np.asarray(img), m, img.size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(out, img.mode)


def _zoomed(layer, z):
    """a full-frame layer scaled by z about its center"""
    from PIL import Image
    if abs(z - 1.0) < 1e-3:
        return layer
    w, h = round(W * z), round(H * z)
    big = layer.resize((w, h), Image.BILINEAR)
    if z >= 1.0:
        x, y = (w - W) // 2, (h - H) // 2
        return big.crop((x, y, x + W, y + H))
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    out.alpha_composite(big, ((W - w) // 2, (H - h) // 2))
    return out


def run(plan, stills=None):
    from PIL import Image, ImageDraw
    work = plan['work']
    edit = json.load(open(os.path.join(work, 'edit.json'), encoding='utf8'))
    fps, dur = edit['fps'], edit['duration']
    nf = int(round(dur * fps))
    lang = edit.get('lang', 'en')
    draw.set_accent(plan.get('accent') or edit.get('accent') or 'sand')
    spec = cp.build(plan, edit)
    items = spec['items']
    _images(spec, lang)
    by_idx = {it['idx']: it for it in items}
    # sky text: placed from the first frame's head top, then EVERY frame is checked for occlusion
    decisions = []
    for it in items:
        if it['layer'] != 'sky':
            continue
        f0 = int(it['t0'] * fps)
        mk0 = _mask(work, f0)
        top = _head_top(mk0)
        h = it['img'].height
        pad = it['img'].info.get('pad', 0)
        pos = [W // 2, max(int(top - h / 2 + h * 0.15), h // 2 - pad + layout.TOP_SAFE)]
        fr = []
        letters = max(1, sum(1 for ch in str(it['m'].get('text', '')) if not ch.isspace()))
        for fi in range(f0, int(it['t1'] * fps)):
            mk = mk0 if fi == f0 else _mask(work, fi)
            if mk is None:
                fr = []
                break
            fr.append(_occluded(it['img'], pos[0], pos[1], mk, letters))
        if cp.decide_layer(fr) == 'sky':
            it['pos'] = pos
        else:                                          # no clean place behind the head: its front slot
            it['layer'] = 'front'
            cp.apply_slot(it, spec)
            _headline(it)
        decisions.append({'moment': it['idx'], 'text': it['m'].get('text'), 'layer': it['layer'],
                          'max_hidden': round(max(f[0] for f in fr), 3) if fr else None,
                          'worst_letter': round(max(f[1] for f in fr), 3) if fr else None})
    for it in items:                                   # strikes follow their target's final layer and spot
        if it['kind'] == 'strike':
            tgt = by_idx.get(it['target'])
            if not tgt or tgt['kind'] != 'headline':
                raise ValueError(f"strike moment {it['idx']}: target {it['target']} is not a headline moment")
            it['layer'], it['pos'], it['tgt'] = tgt['layer'], tgt['pos'], tgt
            # a strike lives only while its headline shows: a red line over nothing is a glitch (10-Nov)
            it['t0'], it['t1'] = max(it['t0'], tgt['t0']), min(it['t1'], tgt['t1'])
    caps = spec['captions']
    cap_cache = {}

    def cap_img(txt):
        if txt not in cap_cache:
            cap_cache[txt] = draw.caption(txt)
        return cap_cache[txt]

    def cap_line(t):
        return next((y for a, b, y in spec['cap_lines'] if a <= t < b), layout.CAP_Y)

    def scene_at(t):
        return next((it for it in items if it['layer'] == 'scene' and any(a <= t < b for a, b in it['windows'])), None)

    def hidden(t):
        return any(a <= t < b for a, b in spec['hide_cap'])

    def push_at(t):
        """(zoom, center) of the slow push at time t: each shot drifts in toward the speaker's eyes"""
        s = next((s for s in edit['shots'] if s['out_in'] <= t < s['out_out']), None)
        if not s or not s.get('push'):
            return 1.0, (W / 2, H * 0.42)
        f = cp._face(s)
        c = ((f['left'] + f['right']) / 2, f['eye_y']) if f else (W / 2, H * 0.42)
        return 1.0 + s['push'] * (t - s['out_in']) / max(0.04, s['out_out'] - s['out_in']), c

    # the look report: every text box against the face of every shot it shows over, and against the safe area
    texts = []
    for it in items:
        if it['layer'] == 'scene' or it['kind'] == 'strike':
            continue
        if it['layer'] == 'sky':                       # behind the head on purpose; the occlusion rule guards it
            continue
        texts.append({'what': str(it['m'].get('text') or it['m'].get('bold') or it['m'].get('lines') or it['kind']),
                      't0': it['t0'], 't1': it['t1'], 'box': draw.glyph_box(it['img'], *(it.get('bold_pos') or it['pos']))})
        if it['kind'] == 'pair':
            texts.append({'what': it['m']['light'], 't0': it['t0'], 't1': it['t1'], 'box': draw.glyph_box(it['light'], *it['pos'])})
    for c in caps:
        tm = c['t0'] + 1e-3
        if hidden(tm) or scene_at(tm):
            continue
        texts.append({'what': 'caption: ' + c['text'], 't0': c['t0'], 't1': c['t1'],
                      'box': draw.glyph_box(cap_img(c['text']), W / 2, cap_line(tm))})
    look = layout.look_report(texts, [{'out_in': s['out_in'], 'out_out': s['out_out'], 'face': cp._face(s),
                                       'crop_top': s['crop'][1]} for s in edit['shots']])
    look['accents'] = sorted(draw.USED)
    look['faces'] = sum(1 for s in edit['shots'] if cp._face(s))
    for key in ('on_face', 'edge'):
        for x in look[key]:
            print(f"compose: look - {key.replace('_', ' ')}: {x['what'][:40]} at {x['t']:.2f} s")

    def place(frame, img, cx, cy, t, t0, entry):
        if entry and t - t0 < entry / fps:
            import numpy as np
            p = (t - t0) * fps / entry
            sc = 0.70 + 0.30 * layout.ease_back(p)     # lands a touch big, then settles
            im = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BILINEAR)
            if (1 - p) * 8 > 1.0:
                from PIL import ImageFilter
                im = im.filter(ImageFilter.GaussianBlur((1 - p) * 8))
            a = np.array(im)
            a[..., 3] = (a[..., 3] * min(1.0, p * 2.2)).astype(np.uint8)
            im = Image.fromarray(a, 'RGBA')
        else:
            im = img
        frame.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))

    def strike_img(it, t):
        tgt = it['tgt']['img']
        pad = tgt.info.get('pad', 0)
        img = Image.new('RGBA', tgt.size, (0, 0, 0, 0))
        p = min(1.0, max(0.0, (t - it['t0']) / 0.16))
        if p > 0:
            y = tgt.height // 2 + 4
            ImageDraw.Draw(img).line((pad - 10, y, pad - 10 + (tgt.width - 2 * pad + 20) * p, y - 6 * p),
                                     fill=draw.RED + (255,), width=max(10, _glyph_h(tgt) // 9))
        return img

    def parts(it, t):
        """[(image, cx, cy, entry start, entry frames)] to draw for one front / sky item at time t"""
        k = it['kind']
        if k == 'strike':
            return [(strike_img(it, t), it['pos'][0], it['pos'][1], it['t0'], 0)]
        if k == 'pair':
            bt = it.get('bold_t', it['t0'])
            out = [] if (t >= bt and not it['stacked']) else [(it['light'], it['pos'][0], it['pos'][1], it['t0'], it['entry'])]
            if t >= bt:
                out.append((it['img'], it['bold_pos'][0], it['bold_pos'][1], bt, it['entry']))
            return out
        return [(it['img'], it['pos'][0], it['pos'][1], it['t0'], it['entry'])]

    def scene_frame(it, t):
        a, b = next(w for w in it['windows'] if w[0] <= t < w[1])
        if 'layer_at' in it:                           # a picture: a tall one scrolls while it is up
            layer = it['layer_at']((t - a) / max(0.2, b - a), PAN_PX_S * (b - a))
        else:
            n = sum(1 for x in it.get('ticks', []) if t >= x)
            if n not in it['cache']:
                it['cache'][n] = it['make'](n)
            layer = it['cache'][n]
        z = 1.0 + 0.045 * (t - a) / max(0.2, b - a)    # every scene drifts in slowly: a still frame reads as a freeze
        p = (t - a) * fps / it['entry']
        if p < 1.0:
            z *= 0.94 + 0.06 * layout.ease_back(p)
        if it.get('covers'):
            return _zoomed(layer, z).convert('RGBA')
        frame = draw.scene_bg().copy()
        frame.alpha_composite(_zoomed(layer, z))
        return frame

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
        base = Image.frombytes('RGB', (W, H), buf)
        z, zc = push_at(t)
        if z > 1.0005:                                 # the slow push inside a shot, into the eyes
            base = _push(base, z, zc)
        base = base.convert('RGBA')
        for wt in spec['whips']:
            k = int(round((t - wt) * fps))
            if k in WHIP:
                base = _whip(base, k)
                break
        scene = scene_at(t)
        if scene:
            frame = scene_frame(scene, t)
        else:
            frame = base.copy()
            act = [it for it in items if it['t0'] <= t < it['t1'] and it['layer'] != 'scene']
            sky = [it for it in act if it['layer'] == 'sky']
            for it in sky:
                for img, cx, cy, e0, en in parts(it, t):
                    place(frame, img, cx, cy, t, e0, en)
            if sky:
                mk = _mask(work, fi)
                if mk is not None:
                    if z > 1.0005:                     # the mask was cut from the frame before its push
                        mk = _push(mk, z, zc)
                    frame = Image.composite(base, frame, mk)
            for it in act:
                if it['layer'] == 'front':
                    for img, cx, cy, e0, en in parts(it, t):
                        place(frame, img, cx, cy, t, e0, en)
        if scene or not hidden(t):                     # over a scene the captions always run: nothing else is saying the words
            c = next((c for c in caps if c['t0'] <= t < c['t1']), None)
            if c:
                ci = cap_img(c['text'])
                frame.alpha_composite(ci, (int(W / 2 - ci.width / 2), int(cap_line(t) - ci.height / 2)))
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
              'captions': [(round(c['t0'], 2), round(c['t1'], 2), c['text']) for c in caps], 'sky': decisions, 'look': look,
              'accent': look['accents'], 'whips': spec['whips']}
    json.dump(events, open(os.path.join(work, 'events.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    for d in decisions:
        print(f"compose: sky '{d['text']}' -> {d['layer']} (max hidden {d['max_hidden']}, worst letter {d['worst_letter']})")
    print(f"compose: look - {len(look['on_face'])} text on a face, {len(look['edge'])} at the frame edge, "
          f"{len(look['cut_head'])} heads cut by a zoom, faces found in {look['faces']}/{len(edit['shots'])} shots")
    return events
