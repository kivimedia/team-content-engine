"""Drawing: captions, matte 3D headlines, full-screen navy scenes, badge, speech bubble, check mark (Hebrew right-to-left).
One accent color per reel (set_accent), heavy Montserrat for Latin and Heebo for Hebrew, no neon: the first real render
used five glowing colors and read as cheap (10-Nov-2026). Needs Pillow (numpy for the chromatic aberration).
`visual()` is pure and tested. Every text image carries its transparent margin in img.info['pad']."""
import os
import re

from . import layout

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), 'fonts')
W, H = layout.W, layout.H
WHITE = (255, 255, 255)
INK = (10, 12, 34)                 # dark navy for marks drawn ON the accent
NAVY = (0, 0, 40)
RED = (232, 72, 60)                # only the strike line: the old or wrong thing
HEB = re.compile(r'[֐-׿]')
FILES = {'Montserrat': 'Montserrat.ttf', 'Heebo': 'Heebo.ttf', 'Caveat': 'Caveat.ttf', 'Amatic': 'AmaticSC-Bold.ttf'}

_accent = {'name': 'sand', 'face': layout.ACCENTS['sand'][0], 'side': layout.ACCENTS['sand'][1]}
USED = set()                       # accent names actually drawn: the checklist's "one accent color" reads this


def set_accent(name):
    """a name from layout.ACCENTS, or [r, g, b]; anything else keeps sand"""
    if isinstance(name, (list, tuple)) and len(name) == 3:
        face = tuple(int(v) for v in name)
        _accent.update(name='custom', face=face, side=tuple(int(v * 0.58) for v in face))
    else:
        key = name if name in layout.ACCENTS else 'sand'
        _accent.update(name=key, face=layout.ACCENTS[key][0], side=layout.ACCENTS[key][1])
    USED.clear()
    return _accent['name']


def accent():
    USED.add(_accent['name'])
    return _accent['face'], _accent['side']


def is_accent(color):
    """the plan's color names: white stays white, every other name is THE accent"""
    return bool(color) and color != 'white'


def is_rtl(text):
    return bool(HEB.search(text))


def visual(text):
    """Logical -> visual order for one line, for renderers without bidi shaping (Pillow without raqm).
    Uses python-bidi when installed; otherwise reverses the word order and each Hebrew word's letters, keeping
    numbers and Latin words left-to-right and moving end punctuation to the visual left."""
    if not is_rtl(text):
        return text
    try:
        from bidi.algorithm import get_display
        return get_display(text)
    except Exception:
        pass
    m = re.match(r'^(.*?)([.,!?:;…]*)$', text)
    body, punct = m.group(1), m.group(2)
    out = []
    for tok in body.split(' '):
        out.append(tok[::-1] if is_rtl(tok) else tok)
    return punct + ' '.join(reversed(out))


_font_cache = {}


def font(size, weight=800, family=None, text=''):
    """heavy sans by script: Heebo when the text has Hebrew, Montserrat otherwise"""
    from PIL import ImageFont
    family = family or ('Heebo' if is_rtl(text) else 'Montserrat')
    key = (family, size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(os.path.join(FONTS, FILES[family]), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        _font_cache[key] = f
    return _font_cache[key]


def hand(size, text=''):
    """handwritten label font: Caveat for Latin, Amatic SC for Hebrew"""
    return font(int(size * 1.15), 700, 'Amatic') if is_rtl(text) else font(size, 700, 'Caveat')


def fit(text, weight, size, max_w, family=None, min_size=30):
    f = font(size, weight, family, text)
    while f.getlength(visual(text)) > max_w and size > min_size:
        size -= 4
        f = font(size, weight, family, text)
    return f


def text_img(txt, f, fill, glow=None, glow_r=16, shadow=True, extrude=0, extrude_col=None, margin=60, stroke=0,
             outline=0):
    """One line of text on a transparent image. outline = a thin dark edge that keeps white text readable on a bright
    sky; extrude = matte 3D depth in extrude_col; glow only for text on the navy scenes."""
    from PIL import Image, ImageDraw, ImageFilter
    txt = visual(txt)
    bbox = f.getbbox(txt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    wd, hd = tw + 2 * margin + extrude, th + 2 * margin + extrude
    ox, oy = margin - bbox[0], margin - bbox[1]
    out = Image.new('RGBA', (wd, hd), (0, 0, 0, 0))
    if shadow:
        sh = Image.new('RGBA', out.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((ox + 1 + extrude, oy + 5 + extrude), txt, font=f, fill=(0, 0, 0, 150),
                                stroke_width=outline, stroke_fill=(0, 0, 0, 150))
        out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(8)))
    if glow:
        g = Image.new('RGBA', out.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text((ox, oy), txt, font=f, fill=glow + (255,), stroke_width=4)
        out = Image.alpha_composite(out, g.filter(ImageFilter.GaussianBlur(glow_r)))
        out = Image.alpha_composite(out, g.filter(ImageFilter.GaussianBlur(glow_r / 3)))
    d = ImageDraw.Draw(out)
    if extrude:
        col = extrude_col or tuple(int(v * 0.58) for v in fill)
        for k in range(extrude, 0, -1):
            c = tuple(int(v * (0.72 + 0.28 * (1 - k / extrude))) for v in col)
            d.text((ox + k * 0.6, oy + k), txt, font=f, fill=c + (255,), stroke_width=1, stroke_fill=c + (255,))
    if outline:
        d.text((ox, oy), txt, font=f, fill=(0, 0, 0, 0), stroke_width=outline, stroke_fill=(8, 10, 20, 210))
    d.text((ox, oy), txt, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=fill + (255,))
    out.info['pad'] = margin
    return out


def glyph_box(img, cx, cy):
    """[x0, y0, x1, y1] of the visible glyphs of an image placed with its center at (cx, cy)"""
    pad = img.info.get('pad', 0)
    left, top, right, bottom = img.info.get('edges') or (pad, pad, pad, pad)      # transparent margin per side
    return [cx - img.width / 2 + left, cy - img.height / 2 + top, cx + img.width / 2 - right, cy + img.height / 2 - bottom]


def caption(txt):
    """C1 phrase caption: heavy white, a thin dark edge, a soft shadow. One weight for the whole reel."""
    return text_img(txt, fit(txt, 800, 78, 800), WHITE, margin=40, outline=3)


def styled(text, color='white', look='plain', size=200, max_w=950, weight=900):
    """A headline. White stays plain white with a dark edge; any other color is the reel's accent as matte 3D letters
    (look is accepted for old plans: neon no longer glows)."""
    f = fit(text, weight, size, max_w)
    if is_accent(color):
        face, side = accent()
        return text_img(text, f, face, extrude=max(6, f.size // 15), extrude_col=side, margin=50)
    return text_img(text, f, WHITE, margin=50, outline=max(3, f.size // 40))


def stack(imgs, gap=-30):
    from PIL import Image
    w = max(i.width for i in imgs)
    h = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    y = 0
    for i in imgs:
        out.alpha_composite(i, ((w - i.width) // 2, y))
        y += i.height + gap
    out.info['pad'] = min(i.info.get('pad', 0) for i in imgs)
    return out


def check_mark(d, cx, cy, r, col=INK, w=12):
    d.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.12, cy + r * 0.35), (cx + r * 0.5, cy - r * 0.38)],
           fill=col + (255,), width=w, joint='curve')


def _glow_shape(img, shape, box, r, fill, blur, alpha=255):
    from PIL import Image, ImageDraw, ImageFilter
    h = Image.new('RGBA', img.size, (0, 0, 0, 0))
    if shape == 'ellipse':
        ImageDraw.Draw(h).ellipse(box, fill=fill + (alpha,))
    else:
        ImageDraw.Draw(h).rounded_rectangle(box, r, fill=fill + (alpha,))
    img.alpha_composite(h.filter(ImageFilter.GaussianBlur(blur)))


def with_check(img):
    from PIL import Image, ImageDraw
    face, _side = accent()
    r = int(img.height * 0.22)
    out = Image.new('RGBA', (img.width + 2 * r + 20, img.height), (0, 0, 0, 0))
    out.alpha_composite(img, (0, 0))
    cx, cy = img.width + r - 10, img.height // 2
    d = ImageDraw.Draw(out)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=face + (255,))
    check_mark(d, cx, cy, r * 0.95, w=max(8, r // 5))
    out.info['pad'] = img.info.get('pad', 0)
    return out


def chroma(img, shift=2):
    import numpy as np
    from PIL import Image
    a = np.array(img).astype(np.int16)
    out = a.copy()
    out[:, :-shift, 0] = np.maximum(a[:, :-shift, 0], a[:, shift:, 0])
    out[:, shift:, 2] = np.maximum(a[:, shift:, 2], a[:, :-shift, 2])
    res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), 'RGBA')
    res.info.update(img.info)
    return res


# ---------------------------------------------------------------- full-screen navy scenes (the cutaways)
_scene_bg = {}


def scene_bg():
    """The whole frame as a navy scene (#000028 at the edges, a lifted blue center), CRT scan lines, a vignette. A
    cutaway takes the WHOLE screen for a beat; a card floating on the chest covered the chin (10-Nov)."""
    if 'bg' in _scene_bg:
        return _scene_bg['bg']
    import numpy as np
    from PIL import Image
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H * 0.42) / (H * 0.62)) ** 2)
    k = np.clip(1.0 - d, 0.0, 1.0) ** 1.4
    rgb = np.zeros((H, W, 3), np.float32)
    rgb[..., 0] = 2 + 14 * k
    rgb[..., 1] = 3 + 22 * k
    rgb[..., 2] = 40 + 62 * k
    rgb[::6] *= 0.86                                    # scan lines
    rgb[1::6] *= 0.93
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')
    _scene_bg['bg'] = img
    return img


def _scene_layer():
    from PIL import Image
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def list_scene(items, ticks_on, bottom=1080):
    """A checklist that ticks one line at a time, as a transparent W x H layer for scene_bg(). The rows are centered
    between 300 and `bottom` (the caption line keeps running under it). Right-to-left for Hebrew."""
    from PIL import ImageDraw
    img = _scene_layer()
    rows = max(1, len(items))
    pitch = min(215, (bottom - 300) // rows)
    rtl = any(is_rtl(i) for i in items)
    face, _side = accent()
    r = int(pitch * 0.25)
    room = W - 2 * 84 - 2 * r - 26
    # ONE size for every row (the longest line sets it) and the whole block centered: rows fitted one by one came
    # out in three different sizes (10-Nov)
    size = min(fit(it, 800, int(pitch * 0.50), room).size for it in items)
    block = 2 * r + 26 + max(font(size, 800, text=it).getlength(visual(it)) for it in items)
    x0 = (W - block) / 2
    y = (300 + bottom) // 2 - (rows * pitch) // 2 + pitch // 2
    for k, it in enumerate(items):
        cx = (W - x0 - r) if rtl else (x0 + r)
        d = ImageDraw.Draw(img)
        if k < ticks_on:
            d.ellipse((cx - r, y - r, cx + r, y + r), fill=face + (255,))
            check_mark(d, cx, y, r * 0.95, w=max(8, r // 4))
        else:
            d.ellipse((cx - r, y - r, cx + r, y + r), outline=(120, 140, 255, 255), width=4)
        col = WHITE if k < ticks_on else (170, 180, 225)
        # crisp: no glow, no color fringe. With both, and a slow zoom over them, Ziv asked "is this blurry?" (11-Nov)
        t = text_img(it, font(size, 800 if k < ticks_on else 600, text=it), col, shadow=False, margin=24)
        tx = (cx - r - 26 - t.width + 24) if rtl else (cx + r + 26 - 24)
        img.alpha_composite(t, (int(tx), int(y - t.height // 2)))
        y += pitch
    return img


def grid_scene(title, cells, filled, ticks_on, labels='Week {n}', empty_label='free', bottom=1080):
    """n boxes in a row under a title; `filled` boxes get a tick once their turn comes; the others are dashed 'free'
    boxes. Right-to-left order for a Hebrew title. A transparent W x H layer for scene_bg()."""
    from PIL import ImageDraw
    img = _scene_layer()
    rtl = is_rtl(title) or is_rtl(labels)
    face, _side = accent()
    mid = (300 + bottom) // 2
    t = text_img(title, fit(title, 900, 110, W - 160), face, shadow=False, margin=40)
    img.alpha_composite(t, ((W - t.width) // 2, mid - 250 - t.height // 2 + 40))
    d = ImageDraw.Draw(img)
    n = max(1, min(int(cells), 6))
    gap = 30
    box = min(190, (W - 140 - (n - 1) * gap) // n)
    x0 = (W - (n * box + (n - 1) * gap)) // 2
    y0 = mid - 20
    lab = font(40 if n <= 4 else 34, 600, text=labels)
    shown = 0
    for k in range(n):
        slot = (n - 1 - k) if rtl else k
        x = x0 + slot * (box + gap)
        d.text((x + box / 2, y0 - 34), visual(labels.format(n=k + 1)), font=lab, fill=(200, 210, 255, 255), anchor='mm')
        if k in filled:
            on = shown < ticks_on
            shown += 1
            if on:
                d.rounded_rectangle((x, y0, x + box, y0 + box), 32, fill=face + (255,))
                check_mark(d, x + box / 2, y0 + box / 2, box * 0.42, w=16)
            else:
                d.rounded_rectangle((x, y0, x + box, y0 + box), 32, outline=(120, 140, 255, 255), width=4)
        else:
            for s in range(0, box, 22):
                for seg in ((x + s, y0, x + min(s + 11, box), y0), (x + s, y0 + box, x + min(s + 11, box), y0 + box),
                            (x, y0 + s, x, y0 + min(s + 11, box)), (x + box, y0 + s, x + box, y0 + min(s + 11, box))):
                    d.line(seg, fill=(150, 170, 255, 230), width=4)
            d.text((x + box / 2, y0 + box / 2), visual(empty_label), font=font(44, 700, text=empty_label),
                   fill=(190, 205, 255, 255), anchor='mm')
    return img


def stat_scene(number, label='', bottom=1080):
    """One big number and a short line under it: the reel's "600 students" beat. Transparent W x H layer."""
    img = _scene_layer()
    face, side = accent()
    mid = (300 + bottom) // 2
    num = text_img(number, fit(number, 900, 380, W - 180), face, extrude=18, extrude_col=side, margin=50, shadow=False)
    img.alpha_composite(num, ((W - num.width) // 2, mid - num.height // 2 - (70 if label else 0)))
    if label:
        lab = text_img(label, fit(label, 700, 92, W - 200), WHITE, shadow=False, margin=30)
        img.alpha_composite(lab, ((W - lab.width) // 2, mid + num.height // 2 - 110))
    return img


def picture_mode(pw, ph, win_w, win_h):
    """How a picture becomes a cutaway. 'cover': near 9:16, it fills the frame. 'pan': a tall one (a phone screenshot)
    fills the window's width and scrolls, because fitted whole it came out the size of a stamp (10-Nov). 'fit':
    everything else sits whole in the window. Pure."""
    if abs(pw / ph - W / H) < 0.09:
        return 'cover'
    return 'pan' if ph * (win_w / pw) > win_h * 1.08 else 'fit'


def picture_scene(path, bottom=1080):
    """A picture or screenshot as a cutaway: (layer_at, covers). layer_at(p, travel) gives the W x H layer at progress
    p (0..1) through its time on screen; travel caps how far a tall picture scrolls, in pixels."""
    from PIL import Image, ImageDraw, ImageFilter
    pic = Image.open(path).convert('RGB')
    x0, y0 = 70, 230
    win_w, win_h = W - 2 * x0, bottom - y0
    mode = picture_mode(pic.width, pic.height, win_w, win_h)
    if mode == 'cover':
        k = max(W / pic.width, H / pic.height)
        pic = pic.resize((round(pic.width * k), round(pic.height * k)), Image.LANCZOS)
        x, y = (pic.width - W) // 2, (pic.height - H) // 2
        full = pic.crop((x, y, x + W, y + H)).convert('RGBA')
        return (lambda p, travel=0: full), True
    if mode == 'fit':
        k = min(win_w / pic.width, win_h / pic.height)
        pic = pic.resize((max(2, round(pic.width * k)), max(2, round(pic.height * k))), Image.LANCZOS)
        fw, fh = pic.size
    else:
        pic = pic.resize((win_w, max(2, round(pic.height * win_w / pic.width))), Image.LANCZOS)
        fw, fh = win_w, win_h
    x, y = (W - fw) // 2, y0 + (win_h - fh) // 2
    under = _scene_layer()
    sh = _scene_layer()
    ImageDraw.Draw(sh).rounded_rectangle((x + 4, y + 18, x + fw + 4, y + fh + 18), 34, fill=(0, 0, 0, 170))
    under.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    mask = Image.new('L', (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw, fh), 34, fill=255)
    rim = _scene_layer()
    ImageDraw.Draw(rim).rounded_rectangle((x, y, x + fw, y + fh), 34, outline=(120, 140, 255, 200), width=3)

    def layer_at(p, travel=0):
        img = under.copy()
        off = 0
        if mode == 'pan':
            e = min(1.0, max(0.0, p))
            off = round(min(pic.height - fh, travel) * e * e * (3 - 2 * e))      # eased, like a thumb scrolling
        img.paste(pic.crop((0, off, fw, off + fh)), (x, y), mask)
        img.alpha_composite(rim)
        return img
    return layer_at, False


def badge(text, color='accent', r=120):
    from PIL import Image, ImageDraw
    face, _side = accent()
    img = Image.new('RGBA', (2 * r + 80, 2 * r + 80), (0, 0, 0, 0))
    _glow_shape(img, 'ellipse', (40, 46, 40 + 2 * r, 46 + 2 * r), 0, (0, 0, 0), 14, alpha=150)
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 40 + 2 * r, 40 + 2 * r), fill=face + (255,))
    f = fit(text, 900, 150, int(1.6 * r))
    d.text((40 + r, 40 + r), visual(text), font=f, fill=INK + (255,), anchor='mm')
    img.info['pad'] = 40
    return img


def bubble(lines):
    from PIL import Image, ImageDraw, ImageFilter
    f = font(60, 700, text=' '.join(lines))
    vis = [visual(l) for l in lines]
    tw = max(f.getlength(l) for l in vis)
    lh = 76
    bw, bh = int(tw + 90), int(lh * len(vis) + 66)
    top = 56                                               # room for the tail, which points UP at the mouth
    img = Image.new('RGBA', (bw + 60, bh + top + 50), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((34, top + 8, 34 + bw, top + 8 + bh), 44, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((30, top, 30 + bw, top + bh), 44, fill=(255, 255, 255, 255))
    rtl = any(is_rtl(l) for l in lines)
    tail_x = (30 + bw - 150) if rtl else (30 + 90)
    d.polygon([(tail_x, top + 2), (tail_x + 34, 10), (tail_x + 64, top + 2)], fill=(255, 255, 255, 255))
    for k, l in enumerate(vis):
        x = 30 + bw - 45 - f.getlength(l) if rtl else 30 + 45
        d.text((x, top + 30 + k * lh), l, font=f, fill=(20, 24, 40, 255))
    img.info['pad'] = 30
    img.info['top'] = 10                                   # the tail's tip: the bubble's real top edge
    img.info['edges'] = (30, 10, 30, 50)
    return img
