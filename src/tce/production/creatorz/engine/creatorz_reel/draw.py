"""Drawing: text with glow / extrusion / shadow (Hebrew right-to-left), navy cards, badge, speech bubble, check mark.
Needs Pillow (and numpy for the chromatic aberration). `visual()` is pure and tested."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), 'fonts')
WHITE = (255, 255, 255)
COLORS = {  # face, halo
    'white': ((255, 255, 255), None),
    'green': ((40, 214, 20), (8, 120, 0)),       # skill: about #18C000 with a #087800 halo
    'yellow': ((240, 255, 70), (170, 150, 0)),   # lemon neon for numbers and places
    'cyan': ((90, 236, 255), (0, 120, 170)),     # aspiration words
    'red': ((255, 48, 48), (120, 0, 0)),         # the old or wrong thing
}
KHAKI = (160, 160, 112)
NAVY = (0, 0, 40)
HEB = re.compile(r'[֐-׿]')


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


def font(size, weight=800, family='Rubik'):
    from PIL import ImageFont
    key = (family, size, weight)
    if key not in _font_cache:
        path = {'Rubik': 'Rubik.ttf', 'Caveat': 'Caveat.ttf', 'Amatic': 'AmaticSC-Bold.ttf'}[family]
        f = ImageFont.truetype(os.path.join(FONTS, path), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        _font_cache[key] = f
    return _font_cache[key]


def hand(size, text=''):
    """handwritten label font: Caveat for Latin, Amatic SC for Hebrew"""
    return font(int(size * 1.15), 700, 'Amatic') if is_rtl(text) else font(size, 700, 'Caveat')


def fit(text, weight, size, max_w, family='Rubik'):
    f = font(size, weight, family)
    while f.getlength(visual(text)) > max_w and size > 30:
        size -= 4
        f = font(size, weight, family)
    return f


def text_img(txt, f, fill, glow=None, glow_r=16, shadow=True, extrude=0, extrude_col=KHAKI, margin=60, stroke=0):
    from PIL import Image, ImageDraw, ImageFilter
    txt = visual(txt)
    bbox = f.getbbox(txt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    wd, hd = tw + 2 * margin + extrude, th + 2 * margin + extrude
    ox, oy = margin - bbox[0], margin - bbox[1]
    out = Image.new('RGBA', (wd, hd), (0, 0, 0, 0))
    if shadow:
        sh = Image.new('RGBA', out.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((ox + 2 + extrude, oy + 6 + extrude), txt, font=f, fill=(0, 0, 0, 170))
        out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(9)))
    if glow:
        g = Image.new('RGBA', out.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text((ox, oy), txt, font=f, fill=glow + (255,), stroke_width=4)
        out = Image.alpha_composite(out, g.filter(ImageFilter.GaussianBlur(glow_r)))
        out = Image.alpha_composite(out, g.filter(ImageFilter.GaussianBlur(glow_r / 3)))
    d = ImageDraw.Draw(out)
    for k in range(extrude, 0, -1):
        c = tuple(int(v * (0.55 + 0.45 * (1 - k / max(1, extrude)))) for v in extrude_col)
        d.text((ox + k * 0.7, oy + k), txt, font=f, fill=c + (255,))
    d.text((ox, oy), txt, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=fill + (255,))
    return out


def styled(text, color='white', look='plain', size=200, max_w=1000, weight=900):
    face, halo = COLORS.get(color, COLORS['white'])
    f = fit(text, weight, size, max_w)
    if look == 'extrude':
        return text_img(text, f, face, extrude=max(8, f.size // 16), margin=50)
    if look == 'neon' or halo:
        return text_img(text, f, face, glow=halo or (80, 110, 255), glow_r=max(14, f.size // 11), margin=60)
    return text_img(text, f, face, margin=50)


def stack(imgs, gap=-30):
    from PIL import Image
    w = max(i.width for i in imgs)
    h = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    y = 0
    for i in imgs:
        out.alpha_composite(i, ((w - i.width) // 2, y))
        y += i.height + gap
    return out


def check_mark(d, cx, cy, r, col=WHITE, w=12):
    d.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.12, cy + r * 0.35), (cx + r * 0.5, cy - r * 0.38)],
           fill=col + (255,), width=w, joint='curve')


def _glow_shape(img, shape, box, r, fill, blur):
    from PIL import Image, ImageDraw, ImageFilter
    h = Image.new('RGBA', img.size, (0, 0, 0, 0))
    getattr(ImageDraw.Draw(h), shape)(box, fill=fill + (255,)) if shape == 'ellipse' else ImageDraw.Draw(h).rounded_rectangle(box, r, fill=fill + (255,))
    img.alpha_composite(h.filter(ImageFilter.GaussianBlur(blur)))


def with_check(img):
    from PIL import Image, ImageDraw
    r = int(img.height * 0.26)
    out = Image.new('RGBA', (img.width + 2 * r + 20, img.height), (0, 0, 0, 0))
    out.alpha_composite(img, (0, 0))
    cx, cy = img.width + r - 10, img.height // 2
    _glow_shape(out, 'ellipse', (cx - r, cy - r, cx + r, cy + r), 0, COLORS['green'][1], 14)
    d = ImageDraw.Draw(out)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=COLORS['green'][0] + (255,))
    check_mark(d, cx, cy, r * 0.95, w=max(8, r // 5))
    return out


def chroma(img, shift=2):
    import numpy as np
    from PIL import Image
    a = np.array(img).astype(np.int16)
    out = a.copy()
    out[:, :-shift, 0] = np.maximum(a[:, :-shift, 0], a[:, shift:, 0])
    out[:, shift:, 2] = np.maximum(a[:, shift:, 2], a[:, :-shift, 2])
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), 'RGBA')


def card_base(cw, ch):
    """dark-navy card (#000028), soft blue glow, CRT scan lines; returned with a 40 px transparent margin"""
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new('RGBA', (cw + 80, ch + 80), (0, 0, 0, 0))
    _glow_shape(img, 'rounded_rectangle', (40, 40, 40 + cw, 40 + ch), 48, (40, 70, 255), 24)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, 40 + cw, 40 + ch), 48, fill=NAVY + (242,), outline=(70, 100, 230, 255), width=3)
    sl = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sl)
    for y in range(44, 40 + ch - 4, 6):
        ds.line((44, y, 36 + cw, y), fill=(255, 255, 255, 10))
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, 40 + cw, 40 + ch), 48, fill=255)
    img.alpha_composite(Image.composite(sl, Image.new('RGBA', img.size, (0, 0, 0, 0)), mask))
    return img


def grid_card(title, title_color, cells, filled, ticks_on, labels='Week {n}', empty_label='free', width=900):
    """n boxes in a row; `filled` boxes get a green tick once their turn comes (ticks_on counts them in order);
    the others are dashed 'free' boxes. Right-to-left order for a Hebrew title."""
    from PIL import ImageDraw
    rtl = is_rtl(title) or is_rtl(labels)
    img = card_base(width, 590)
    face, halo = COLORS.get(title_color, COLORS['white'])
    t = text_img(title, fit(title, 900, 96, width - 140), face, glow=halo or (80, 110, 255), glow_r=14, shadow=False, margin=40)
    img.alpha_composite(chroma(t), ((img.width - t.width) // 2, 110))
    d = ImageDraw.Draw(img)
    n = max(1, min(int(cells), 6))
    box = min(168, (width - 120 - (n - 1) * 30) // n)
    gap = 30 if n > 4 else 34
    x0 = (img.width - (n * box + (n - 1) * gap)) // 2
    y0 = 370
    lab = font(38 if n <= 4 else 32, 600)
    shown = 0
    for k in range(n):
        slot = (n - 1 - k) if rtl else k
        x = x0 + slot * (box + gap)
        d.text((x + box / 2, y0 - 30), visual(labels.format(n=k + 1)), font=lab, fill=(200, 210, 255, 255), anchor='mm')
        if k in filled:
            on = shown < ticks_on
            shown += 1
            if on:
                _glow_shape(img, 'rounded_rectangle', (x, y0, x + box, y0 + box), 30, COLORS['green'][1], 16)
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((x, y0, x + box, y0 + box), 30, fill=COLORS['green'][0] + (255,))
                check_mark(d, x + box / 2, y0 + box / 2, box * 0.42, w=16)
            else:
                d.rounded_rectangle((x, y0, x + box, y0 + box), 30, outline=(120, 140, 255, 255), width=4)
        else:
            for s in range(0, box, 22):
                for seg in ((x + s, y0, x + min(s + 11, box), y0), (x + s, y0 + box, x + min(s + 11, box), y0 + box),
                            (x, y0 + s, x, y0 + min(s + 11, box)), (x + box, y0 + s, x + box, y0 + min(s + 11, box))):
                    d.line(seg, fill=(90, 236, 255, 230), width=4)
            d.text((x + box / 2, y0 + box / 2), visual(empty_label), font=font(44, 700), fill=COLORS['cyan'][0] + (255,), anchor='mm')
    return chroma(img)


def list_card(items, ticks_on, width=900):
    """a checklist that ticks one line at a time; right-aligned with the circle on the right for Hebrew"""
    from PIL import ImageDraw
    rows = max(1, len(items))
    img = card_base(width, 120 + rows * 170 - 40)
    d = ImageDraw.Draw(img)
    rtl = any(is_rtl(i) for i in items)
    y = 160
    for k, it in enumerate(items):
        r = 46
        cx = (img.width - 160) if rtl else 160
        cy = y + 50
        if k < ticks_on:
            _glow_shape(img, 'ellipse', (cx - r, cy - r, cx + r, cy + r), 0, COLORS['green'][1], 14)
            d = ImageDraw.Draw(img)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=COLORS['green'][0] + (255,))
            check_mark(d, cx, cy, r * 0.95, w=11)
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(120, 140, 255, 255), width=4)
        col = WHITE if k < ticks_on else (150, 160, 210)
        t = text_img(it, fit(it, 700, 70, width - 240), col, glow=(80, 110, 255) if k < ticks_on else None, glow_r=10, shadow=False, margin=20)
        t = chroma(t) if k < ticks_on else t
        tx = (cx - r - 16 - t.width) if rtl else (cx + r + 16)
        img.alpha_composite(t, (int(tx), int(cy - t.height // 2)))
        y += 170
    return img


def badge(text, color='green', r=120):
    from PIL import Image, ImageDraw
    face, halo = COLORS.get(color, COLORS['green'])
    img = Image.new('RGBA', (2 * r + 80, 2 * r + 80), (0, 0, 0, 0))
    _glow_shape(img, 'ellipse', (40, 40, 40 + 2 * r, 40 + 2 * r), 0, halo or (8, 120, 0), 18)
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 40 + 2 * r, 40 + 2 * r), fill=face + (255,))
    f = fit(text, 900, 150, int(1.6 * r))
    d.text((40 + r, 40 + r), visual(text), font=f, fill=WHITE + (255,), anchor='mm')
    return img


def bubble(lines):
    from PIL import Image, ImageDraw, ImageFilter
    f = font(64, 600)
    vis = [visual(l) for l in lines]
    tw = max(f.getlength(l) for l in vis)
    lh = 78
    bw, bh = int(tw + 90), int(lh * len(vis) + 70)
    img = Image.new('RGBA', (bw + 60, bh + 90), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((34, 38, 34 + bw, 38 + bh), 44, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((30, 30, 30 + bw, 30 + bh), 44, fill=(255, 255, 255, 255))
    rtl = any(is_rtl(l) for l in lines)
    tail_x = 30 + bw - 100 if rtl else 30 + 70
    d.polygon([(tail_x, 30 + bh - 2), (tail_x - 20, 30 + bh + 46), (tail_x + 60, 30 + bh - 2)], fill=(255, 255, 255, 255))
    for k, l in enumerate(vis):
        x = 30 + bw - 45 - f.getlength(l) if rtl else 30 + 45
        d.text((x, 30 + 35 + k * lh), l, font=f, fill=(20, 24, 40, 255))
    return img
