"""Layout rules (pure Python, tested): text never sits on the face or against the frame edge, and a punch-in never cuts
the forehead. Built 10-Nov-2026 after the first real TCE render: captions on the chin and mouth, every headline jammed
against the top edge, foreheads cut in a quarter of the frames. Faces come from faces.summarize(), in source pixels."""

W, H = 1080, 1920
TOP_SAFE = 154                    # 8% of the height: the platform's top bar
SIDE_SAFE = 54                    # 5% of the width
BOTTOM_SAFE = 1536                # the bottom 20% belongs to the post text and the buttons
CAP_Y = 1190                      # caption line with no face found: chest height, 62%
CAP_MAX = 1470                    # the lowest a caption line may go (its glyphs end near 1510)
CAP_GAP = 96                      # chin -> caption center
FACE_MAX, FACE_MAX_PUNCH = 0.46, 0.52     # the face box may fill this share of the frame height
FACE_HARD = 0.58                  # ...and this much only when a cut would otherwise not change scale at all
HAIR = 0.30                       # hair above the face box, as a share of the box height
FOREHEAD = 0.12                   # the crop keeps at least this much (of the box height) above the face box. Not all
#                                   of HAIR: that pushed the face, and the caption line with it, too far down (10-Nov)
PAIR_MIN = 110                    # room under the caption line that a pair's bold line needs to sit there
MIN_STEP = 0.05                   # two neighbor shots never share a scale
UNDER_MIN = 92                    # the smallest glyph band worth a headline under the caption line
ABOVE_MIN = 150                   # the smallest band above the head worth a headline


def scale_cap(face, limit=FACE_MAX, h=H):
    """the biggest punch-in that keeps the face box under `limit` of the frame height; never under 1.0"""
    if not face or face['fh'] <= 0:
        return 9.0
    return max(1.0, limit * h / face['fh'])


def fit_scales(scales, faces, punch=None):
    """Cap every planned scale by its shot's face, then restore the alternation: when a cap leaves two neighbors within
    MIN_STEP, the later one steps down (never under 1.0) or, failing that, up as far as FACE_HARD allows. A jump cut
    that changes nothing reads as a glitch, so the step wins over the soft cap, never over the hard one."""
    out = []
    for i, (sc, f) in enumerate(zip(scales, faces)):
        cap = scale_cap(f, FACE_MAX_PUNCH if i == punch else FACE_MAX)
        sc = int(min(sc, cap) * 1000 + 1e-6) / 1000          # rounded DOWN: a cap is a cap
        if out and abs(sc - out[-1]) < MIN_STEP:
            down, up = round(out[-1] - 0.08, 3), round(out[-1] + 0.08, 3)
            if down >= 1.0:
                sc = down
            elif up <= scale_cap(f, FACE_HARD) + 1e-9:
                sc = up
        out.append(sc)
    return out


def crop_for(scale, face, w=W, h=H):
    """Crop box [x, y, w, h] for a punch-in: eyes on the upper third, centered on the face, the forehead always
    inside (the old crop used a guessed eye line, and with no face found it stayed centered and cut heads)."""
    cw, ch = w / scale, h / scale
    if face:
        cx = face['cx']
        y0 = face['eye_y'] - ch / 3
        y0 = min(y0, face['top'] - FOREHEAD * face['fh'])          # never cut into the forehead
        y0 = max(y0, face['chin'] + 0.04 * face['fh'] - ch)        # nor the chin
        cy = y0 + ch / 2
    else:
        cx, cy = w / 2, h / 2
    cx = min(max(cx, cw / 2), w - cw / 2)
    cy = min(max(cy, ch / 2), h - ch / 2)
    return [round(cx - cw / 2), round(cy - ch / 2), round(cw), round(ch)]


def to_out(face, crop, w=W, h=H):
    """the face in OUTPUT pixels after the crop is scaled to the frame; None stays None"""
    if not face:
        return None
    x, y, cw, ch = crop
    kx, ky = w / cw, h / ch
    return {'top': (face['top'] - y) * ky, 'chin': (face['chin'] - y) * ky, 'left': (face['left'] - x) * kx,
            'right': (face['right'] - x) * kx, 'eye_y': (face['eye_y'] - y) * ky, 'mouth': (face['mouth'] - y) * ky,
            'fh': face['fh'] * ky, 'fw': face['fw'] * kx}


def face_zone(fo):
    """[x0, y0, x1, y1]: brows to just under the mouth, a little inside the cheeks. Text may touch the jaw or the
    hair, never this."""
    inset = 0.08 * (fo['right'] - fo['left'])
    return [fo['left'] + inset, fo['top'] + 0.12 * fo['fh'], fo['right'] - inset, fo['mouth'] + 0.06 * fo['fh']]


def meets(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def caption_lines(faces_out):
    """Caption center y per shot. One steady line for the whole reel (a caption that hops at every cut reads as a
    mistake): under the chin of nearly every shot, never above CAP_Y, never past CAP_MAX. A shot whose chin sits lower
    than the reel line gets its own."""
    wants = [min(CAP_MAX, max(CAP_Y, round(f['chin'] + CAP_GAP))) for f in faces_out if f]
    if not wants:
        return [CAP_Y] * len(faces_out)
    v = sorted(wants)
    reel = v[min(len(v) - 1, int(len(v) * 0.85))]
    return [reel if (not f or min(CAP_MAX, round(f['chin'] + CAP_GAP)) <= reel) else min(CAP_MAX, round(f['chin'] + CAP_GAP))
            for f in faces_out]


def headline_slot(fo, cap_y, want='sky'):
    """Where a top headline can live in this shot: ('above', band_top, band_bottom) when there is real room over the
    head, else ('under', band_top, band_bottom) below the caption line, else ('swap', ...) = it takes the caption
    line for a beat. Bands are glyph bands in output pixels. want: sky / top ask for above first; chest / low for swap."""
    if want in ('chest', 'low'):
        return ('swap', cap_y - 80, min(BOTTOM_SAFE, cap_y + 90))
    head_top = (fo['top'] - HAIR * fo['fh']) if fo else 330
    if head_top - TOP_SAFE >= ABOVE_MIN:
        return ('above', TOP_SAFE, head_top - 14)
    under_top = cap_y + 58
    if BOTTOM_SAFE - under_top >= UNDER_MIN:
        return ('under', under_top, BOTTOM_SAFE)
    return ('swap', cap_y - 80, min(BOTTOM_SAFE, cap_y + 90))


def clamp_box(cx, cy, bw, bh, margin=0):
    """keep a box of bw x bh (glyphs, without its transparent margin) inside the safe area; returns the center"""
    cx = min(max(cx, SIDE_SAFE + bw / 2 - margin), W - SIDE_SAFE - bw / 2 + margin)
    cy = min(max(cy, TOP_SAFE + bh / 2 - margin), BOTTOM_SAFE - bh / 2 + margin)
    return cx, cy


def side_spot(fo, bw, bh, side, cap_y):
    """A free spot for a small item (badge) beside the head: the asked side at eye height, then the other side, then
    the asked side beside the caption line. The first whose box clears the face zone wins."""
    xs = {'left': SIDE_SAFE + bw / 2 + 10, 'right': W - SIDE_SAFE - bw / 2 - 10}
    other = 'right' if side == 'left' else 'left'
    tries = [(xs[side], 420), (xs[other], 420), (xs[side], cap_y - 60 - bh / 2), (xs[other], cap_y - 60 - bh / 2)]
    if not fo:
        return tries[0]
    zone = face_zone(fo)
    for cx, cy in tries:
        cy = min(max(cy, TOP_SAFE + bh / 2), BOTTOM_SAFE - bh / 2)
        if not meets([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], zone):
            return cx, cy
    return tries[2][0], min(BOTTOM_SAFE - bh / 2, cap_y + 60 + bh / 2)


def look_report(texts, shots_out):
    """texts: [{'what', 't0', 't1', 'box': [x0, y0, x1, y1] (glyph box)}]; shots_out: [{'out_in', 'out_out', 'face',
    'crop_top'}]. Returns {'on_face': [...], 'edge': [...], 'cut_head': [...]}: what a viewer would call ugly, by
    name. A head is "cut" when OUR crop took the forehead away (crop_top > 0): what the phone never filmed is not
    ours to restore."""
    on_face, edge, cut = [], [], []
    for s in shots_out:
        f = s.get('face')
        if f and s.get('crop_top', 0) > 2 and f['top'] - 0.5 * FOREHEAD * f['fh'] < -0.004 * H:
            cut.append(round(s['out_in'], 2))
    for tx in texts:
        b = tx['box']
        if b[0] < SIDE_SAFE - 16 or b[2] > W - SIDE_SAFE + 16 or b[1] < TOP_SAFE - 40 or b[3] > BOTTOM_SAFE + 30:
            edge.append({'what': tx['what'], 't': round(tx['t0'], 2)})
        for s in shots_out:
            f = s.get('face')
            if f and s['out_in'] < tx['t1'] - 0.02 and tx['t0'] < s['out_out'] - 0.02 and meets(b, face_zone(f)):
                on_face.append({'what': tx['what'], 't': round(max(tx['t0'], s['out_in']), 2)})
                break
    return {'on_face': on_face, 'edge': edge, 'cut_head': cut}


# ---------------------------------------------------------------- style: one accent per reel
ACCENTS = {  # face, side (the darker shade of the 3D extrusion)
    'sand': ((240, 226, 188), (150, 132, 92)),
    'butter': ((255, 226, 128), (168, 132, 40)),
    'ice': ((178, 228, 255), (60, 120, 160)),
}


def _hue(rgb):
    r, g, b = [v / 255.0 for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 1e-6:
        return None, 0.0
    if mx == r:
        hdeg = (60 * ((g - b) / (mx - mn))) % 360
    elif mx == g:
        hdeg = 60 * ((b - r) / (mx - mn)) + 120
    else:
        hdeg = 60 * ((r - g) / (mx - mn)) + 240
    return hdeg, (mx - mn) / mx


def pick_accent(bg_rgb):
    """One accent for the whole reel, from the footage's own background: cool or green backgrounds (sky, trees, a teal
    room) get warm sand; warm backgrounds (wood, sunset walls) get ice; a gray or unknown one gets butter."""
    if not bg_rgb:
        return 'sand'
    hue, sat = _hue(bg_rgb)
    if hue is None or sat < 0.08:
        return 'butter'
    return 'ice' if (hue < 65 or hue > 330) else 'sand'


# ---------------------------------------------------------------- cutaways: when a full-screen card is on
READ_BASE, READ_PER_WORD, READ_MIN, READ_MAX = 0.8, 0.25, 2.0, 5.0
TICK_LEAD, TICK_HOLD, MIN_BACK = 0.3, 1.8, 2.0


def read_time(words):
    """Seconds a full-screen card needs on its first look: a beat to find it, then about four words a second."""
    return max(READ_MIN, min(READ_MAX, READ_BASE + READ_PER_WORD * words))


def card_windows(t0, t1, ticks, words=0, whole=6.0):
    """When a full-screen card is up. A short card (up to `whole` seconds) stays for all of it. A long one stays long
    enough to READ on its first look (read_time of its words), comes back at every tick for TICK_HOLD seconds, and
    gives the speaker back only for a real stretch (MIN_BACK or more: his own render came back for 1.7 s, then the card for 1.5 s, the flicker he flagged). 11-Nov, Ziv at 0:39: "it transitions too fast
    so I can't manage to read it on time": it was 1.5 s, then 1.25 s beats."""
    if t1 - t0 <= whole:
        return [(round(t0, 3), round(t1, 3))]
    wins = [(t0, min(t1, t0 + read_time(words)))] + [(max(t0, x - TICK_LEAD), min(t1, x + TICK_HOLD)) for x in sorted(ticks)]
    wins.sort()
    out = []
    for a, b in wins:
        if out and a < out[-1][1] + MIN_BACK:           # back to the face for less than that reads as a flicker
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 0.2]


# ---------------------------------------------------------------- finish and motion
def exposure_gamma(luma, target, lo=0.86, hi=1.22, dead=0.03, strength=0.85):
    """ffmpeg eq gamma that moves a shot's face brightness toward the reel's median: out = in^(1/gamma). Most of the
    way, not all of it; small differences are left alone and a backlit shot is only partly lifted. Measured on the
    real video: the biggest brightness jump at a cut went from 0.134 to 0.024 of full scale."""
    import math
    if not luma or not target or luma <= 0.02 or luma >= 0.98 or target <= 0.02 or target >= 0.98:
        return 1.0
    g = 1.0 + strength * (math.log(luma) / math.log(target) - 1.0)
    g = min(hi, max(lo, g))
    return 1.0 if abs(g - 1.0) < dead else round(g, 3)


def smooth_track(track, frames, max_shift, window=3):
    """Face-follow keyframes for one shot: [[frame, dx, dy]] offsets from the shot's median face spot, smoothed (a
    moving average over `window` samples), limited to +-max_shift, with a key on the first and last frame. The crop
    follows these so the eyes stay put while a handheld phone drifts. Fewer than 3 samples: no follow."""
    if not track or len(track) < 3:
        return []
    xs, ys = sorted(p[1] for p in track), sorted(p[2] for p in track)
    mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
    pts = sorted(track)
    sm = []
    for i, (k, _x, _y) in enumerate(pts):
        lo, hi = max(0, i - window // 2), min(len(pts), i + window // 2 + 1)
        dx = sum(p[1] for p in pts[lo:hi]) / (hi - lo) - mx
        dy = sum(p[2] for p in pts[lo:hi]) / (hi - lo) - my
        sm.append([int(k), round(min(max_shift, max(-max_shift, dx)), 1), round(min(max_shift, max(-max_shift, dy)), 1)])
    if sm[0][0] > 0:
        sm.insert(0, [0, sm[0][1], sm[0][2]])
    if sm[-1][0] < frames - 1:
        sm.append([frames - 1, sm[-1][1], sm[-1][2]])
    return sm


def piecewise(keys, col, var='n'):
    """ffmpeg expression: linear interpolation of column `col` of [[frame, a, b]] keys over the frame number"""
    if not keys:
        return '0'
    expr = f'{keys[-1][col]}'
    for (k0, *v0), (k1, *v1) in reversed(list(zip(keys, keys[1:]))):
        a, b = v0[col - 1], v1[col - 1]
        seg = f'{a}+({b - a:.3f})*({var}-{k0})/{max(1, k1 - k0)}'
        expr = f'if(lt({var},{k1}),{seg},{expr})'
    return expr


def ease_back(x, s=1.6):
    """ease-out with a small overshoot: a pop lands a touch big, then settles"""
    x = min(1.0, max(0.0, x)) - 1.0
    return 1.0 + (s + 1.0) * x ** 3 + s * x ** 2
