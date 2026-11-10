"""Stage 1: the cut. Footage -> 25 fps master -> voiced runs inside each pick -> shots with alternating punch-ins ->
graded base.mp4 + voice.wav + edit.json. The pure helpers (voiced_runs, plan_scales, crop_for, timeline) carry no numpy."""
import json
import math
import os
import subprocess

from . import plan as planmod

W, H = 1080, 1920
SR = 48000
ALT = (1.18, 1.26, 1.12, 1.22)
WIDE, PUNCH = 1.0, 1.48
GRADES = {
    # golden hour outdoors: warm skin and mids, teal-leaning sky, deeper blacks
    'golden': ("eq=contrast=1.07:saturation=1.16:gamma=0.98,"
               "colorbalance=rs=0.03:bs=-0.04:rm=0.035:gm=0.0:bm=-0.035:rh=-0.03:gh=0.0:bh=0.03,"
               "curves=all='0/0 0.08/0.05 0.5/0.5 0.92/0.95 1/1'"),
    # studio: teal-cyan shadows and background, warm skin, deep blacks
    'studio': ("eq=contrast=1.09:saturation=1.08,"
               "colorbalance=rs=-0.04:gs=0.0:bs=0.05:rm=0.03:gm=0.0:bm=-0.02,"
               "curves=all='0/0 0.1/0.05 0.5/0.5 1/1'"),
    'none': 'null',
}


def voiced_runs(db10, t0, t1, thr=-40.0, gap_max=0.28, min_run=0.12, hop=0.01):
    """Voiced stretches inside [t0, t1): 10 ms RMS frames above thr, gaps under gap_max merged, blips under
    min_run dropped. Cut on the AUDIO: TCE's recognizer stretches a first word over 0.6 s of silence."""
    i0, i1 = max(0, int(round(t0 / hop))), min(len(db10), int(round(t1 / hop)))
    runs, start = [], None
    for k in range(i0, i1):
        on = db10[k] > thr
        if on and start is None:
            start = k
        elif not on and start is not None:
            runs.append([start, k])
            start = None
    if start is not None:
        runs.append([start, i1])
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) * hop < gap_max:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(round(a * hop, 3), round(b * hop, 3)) for a, b in merged if (b - a) * hop >= min_run - 1e-9]


def assign_words(span_words, runs, min_share=0.4, min_abs=0.12):
    """Each word goes to the ONE run it overlaps most (a recognizer-stretched word touching two runs was captioned
    twice: "more" / "more than once?", 10-Nov), and only if enough of it is inside that run (a 0.01 s touch of the
    next take's first word is not that word)."""
    out = [[] for _ in runs]
    for w in span_words:
        best, bo = None, 0.0
        for ri, (v0, v1) in enumerate(runs):
            o = min(w['end_s'], v1) - max(w['start_s'], v0)
            if o > bo:
                best, bo = ri, o
        dur = max(0.01, w['end_s'] - w['start_s'])
        # a word the recognizer started early in the silence still ENDS inside the run: it is the run's first word
        early_first = best is not None and w['start_s'] < runs[best][0] and w['end_s'] >= runs[best][0] + 0.03
        if best is not None and (bo >= min_share * dur or bo >= min_abs or early_first):
            v0, v1 = runs[best]
            out[best].append({'text': w['text'], 'start_s': max(w['start_s'], v0), 'end_s': min(w['end_s'], v1)})
    return out


def run_bounds(v0, v1, t0, t1, pad_in=0.05, pad_out=0.08, edge=0.011):
    """Cut points for one voiced run. Where the voice is still going at the pick's own edge (the next word follows
    with no air, "80%." -> "Honestly"), cut exactly at that edge instead of padding into the next word."""
    s_in = t0 if v0 <= t0 + edge else max(t0, v0 - pad_in)
    s_out = t1 if v1 >= t1 - edge else min(t1, v1 + pad_out)
    return s_in, s_out


REACH = 0.30


def settle(db10, t, step, thr=-40.0, limit=REACH, hop=0.01):
    """Follow the sound running across a pick edge to its first dip under thr, forward (step=+1, where the word
    really stops) or back (step=-1, where it really starts). Only CONTINUOUS sound: a breath after a dip is not the
    word (demo 1 kept a breath when this waited for a long quiet, 10-Nov). Returns (point, wall): the pad may run
    from point up to wall, where the next sound begins. None when there is no dip within `limit`."""
    k0, n = int(round(t / hop)), len(db10)
    lim = int(round(limit / hop))
    if step > 0:
        e = next((k for k in range(k0, min(n, k0 + lim + 1)) if db10[k] <= thr), None)
        if e is None:
            return None
        r = next((k for k in range(e, n) if db10[k] > thr), n)
        return round(e * hop, 3), round(r * hop, 3)
    s = next((k for k in range(k0 - 1, max(-1, k0 - 1 - lim), -1) if db10[k] <= thr), None)
    if s is None:
        return None
    r = next((k for k in range(s, -1, -1) if db10[k] > thr), -1)
    return round((s + 1) * hop, 3), round((r + 1) * hop, 3)


def reach_edges(s_in, s_out, first, last, t0, t1, k, spans, others, g, db10, cfg):
    """TCE ends a word up to 0.25 s before its sound does ("away." ended 67.40, the voice ran to 67.65, the cut
    chopped "-way", 10-Nov). At a pick edge inside running voice, reach out to where the voice really stops, but
    never into a word the pick does not hold or into another pick. Returns (s_in, s_out, hard_in, hard_out)."""
    hard_in = hard_out = False
    if last and s_out == t1:
        got = settle(db10, t1, +1, cfg['thr_db'])
        e, wall = got if got else (None, None)
        if e and e > t1 and not any(w['start_s'] < e - 0.03 and w['end_s'] > t1 + 0.03 for w in others):
            cap = min(e + cfg['pad_out'], wall)
            for j, (a, _b) in enumerate(spans):
                if j != k and t1 <= a < cap:
                    cap, hard_out = min(cap, a), True
            s_out = cap
            g[-1]['end_s'] = max(g[-1]['end_s'], min(e, cap))
    if first and s_in == t0:
        got = settle(db10, t0, -1, cfg['thr_db'])
        s, wall = got if got else (None, None)
        if s is not None and s < t0 and not any(w['end_s'] > s + 0.03 and w['start_s'] < t0 - 0.03 for w in others):
            floor_ = max(s - cfg['pad_in'], wall)
            for j, (_a, b) in enumerate(spans):
                if j != k and floor_ < b <= t0:
                    floor_, hard_in = max(floor_, b), True
            s_in = max(0.0, floor_)
            g[0]['start_s'] = min(g[0]['start_s'], max(s, s_in))
    return s_in, s_out, hard_in, hard_out


MIN_SHOT, TARGET_SHOT, MAX_SHOT = 1.2, 2.4, 3.2
PHRASE_END = ('.', ',', '?', '!', ':', ';', '׃')


def _zoom_points(a, b, inside):
    """Where a kept range longer than MAX_SHOT changes zoom: at a word's end, a phrase end first. The sound and the
    picture run straight on, only the punch-in changes. No word end in reach (a long laugh): the range stays whole."""
    points, start = [], a
    while b - start > MAX_SHOT:
        lo, hi = start + MIN_SHOT, min(start + MAX_SHOT, b - MIN_SHOT)
        ends = [w for w in inside if lo <= w['end_s'] <= hi]
        if not ends:
            break
        phrase = [w for w in ends if w['text'].rstrip('"”\'').endswith(PHRASE_END)]
        t = phrase[-1]['end_s'] if phrase else min(ends, key=lambda w: abs(w['end_s'] - (start + TARGET_SHOT)))['end_s']
        points.append(t)
        start = t
    return points


def build_exact_shots(spans, words, fps=25):
    """The caller already decided what stays (TCE's keep, snapped to the audio by its own tight cut): no re-cut. Each
    range goes on the caller's frame clock (round(second x fps), a range under one frame is dropped, as TCE's
    frame_keep does), so the file's clock IS the caller's. Every shot is its own pick, sentence-sized, so a moment
    cued to a pick lasts about a line. A range with no words (a laugh kept on purpose) stays."""
    shots = []
    for t0, t1 in spans:
        f0, f1 = round(float(t0) * fps), round(float(t1) * fps)
        if f1 <= f0:
            continue
        a, b = f0 / fps, f1 / fps
        inside = [w for w in words if a - 1e-6 <= (w['start_s'] + w['end_s']) / 2 < b]
        frames = [f0] + sorted({f for f in (round(p * fps) for p in _zoom_points(a, b, inside)) if f0 < f < f1}) + [f1]
        for fa, fb in zip(frames, frames[1:]):
            sa, sb = fa / fps, fb / fps
            g = [{'text': w['text'], 'start_s': max(w['start_s'], sa), 'end_s': min(w['end_s'], sb)}
                 for w in inside if sa - 1e-6 <= (w['start_s'] + w['end_s']) / 2 < sb]
            shots.append({'pick': len(shots), 'src_in': sa, 'src_out': sb, 'words': g, 'text': ' '.join(w['text'] for w in g)})
    return shots


def join_fades(shots, eps=1e-6):
    """(fade in?, fade out?) per shot. A join that continues the same moment of the recording gets no fade: two 8 ms
    fades in the middle of a running word are a tick."""
    out = []
    for i, s in enumerate(shots):
        cont_in = i > 0 and abs(shots[i - 1]['src_out'] - s['src_in']) < eps
        cont_out = i + 1 < len(shots) and abs(s['src_out'] - shots[i + 1]['src_in']) < eps
        out.append((not cont_in, not cont_out))
    return out


def build_shots(spans, words, db10, cfg, fps=25):
    shots = []
    for k, (t0, t1) in enumerate(spans):
        span_words = [w for w in words if w['start_s'] >= t0 - 0.05 and w['end_s'] <= t1 + 0.05]
        if not span_words:
            raise planmod.PlanError(f'pick {k} ({t0:.2f}-{t1:.2f} s) holds no words')
        others = [w for w in words if w not in span_words]
        runs = voiced_runs(db10, t0, t1, cfg['thr_db'], cfg['gap_max'], cfg['min_run'])
        groups = assign_words(span_words, runs)
        live = [i for i, g in enumerate(groups) if g]
        made = 0
        for i, ((v0, v1), g) in enumerate(zip(runs, groups)):
            if not g:
                continue
            s_in, s_out = run_bounds(v0, v1, t0, t1, cfg['pad_in'], cfg['pad_out'])
            at_edge_out = s_out == t1
            s_in, s_out, hard_in, hard_out = reach_edges(s_in, s_out, i == live[0], i == live[-1], t0, t1, k, spans,
                                                         others, g, db10, cfg)
            f_in = math.ceil(s_in * fps - 1e-6) if hard_in else math.floor(s_in * fps + 1e-6)
            f_out = math.floor(s_out * fps + 1e-6) if (hard_out or (at_edge_out and s_out == t1)) else math.ceil(s_out * fps - 1e-6)
            shots.append({'pick': k, 'src_in': f_in / fps, 'src_out': max(f_in + 1, f_out) / fps,
                          'words': g, 'text': ' '.join(w['text'] for w in g)})
            made += 1
        if not made:
            raise planmod.PlanError(f'pick {k}: no voice above {cfg["thr_db"]} dB between {t0:.2f} and {t1:.2f} s')
    # first word on frame 1; tail <= 0.2 s
    fw = shots[0]['words'][0]['start_s']
    shots[0]['src_in'] = max(shots[0]['src_in'], math.floor((fw - 0.06) * fps) / fps)
    lw = shots[-1]['words'][-1]['end_s']
    shots[-1]['src_out'] = min(shots[-1]['src_out'], math.ceil((lw + 0.12) * fps) / fps)
    return shots


def plan_scales(shot_picks, wide_picks=(), punch_pick=None):
    """Alternate punch-ins; wide picks stay at 1.0 (sky room for headlines); the punchline pick's first shot gets
    the biggest push; two neighbors never share a scale (that reads as a mistake)."""
    out, k = [], 0
    for i, p in enumerate(shot_picks):
        if p in wide_picks:
            sc = WIDE
        else:
            sc = ALT[k % len(ALT)]
            k += 1
        if out and abs(sc - out[-1]) < 0.05:
            sc = 1.32 if out[-1] < 1.2 else 1.08
        out.append(sc)
    if punch_pick is not None and punch_pick in shot_picks:
        i = shot_picks.index(punch_pick)
        out[i] = PUNCH
    for i in range(1, len(out)):          # a forced 1.0 next to a 1.0 (two wide picks in a row) gets a gentle push
        if abs(out[i] - out[i - 1]) < 0.05:
            out[i] = 1.10 if out[i - 1] < 1.05 else 1.0
    return out


def crop_for(scale, face, w=W, h=H):
    """Crop box [x, y, w, h] for a punch-in, eyes on the upper third; face = [cx, cy, fw, fh] or None."""
    cw, ch = w / scale, h / scale
    if face:
        fx, fy, fw, fh = face
        cx, cy = fx, (fy - fh * 0.12) - ch / 3 + ch / 2
    else:
        cx, cy = w / 2, h / 2
    cx = min(max(cx, cw / 2), w - cw / 2)
    cy = min(max(cy, ch / 2), h - ch / 2)
    return [round(cx - cw / 2), round(cy - ch / 2), round(cw), round(ch)]


def timeline(shots):
    t = 0.0
    for s in shots:
        s['out_in'] = round(t, 4)
        t += s['src_out'] - s['src_in']
        s['out_out'] = round(t, 4)
        off = s['out_in'] - s['src_in']
        s['owords'] = [{'text': w['text'], 's': round(w['start_s'] + off, 3), 'e': round(w['end_s'] + off, 3)} for w in s['words']]
    return round(t, 4)


def wide_picks_from(plan):
    if plan.get('wide') is not None:
        return set(plan['wide'])
    return {planmod.cue_pick(m['at']) for m in plan['moments']
            if m.get('type') == 'headline' and m.get('place', 'sky') == 'sky' and isinstance(m.get('at'), dict)}


# ---------------------------------------------------------------- media (numpy / ffmpeg from here down)
def _db10(path):
    import numpy as np
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    hop = SR // 100
    n = len(a) // hop
    return (20 * np.log10(np.sqrt(np.mean(a[:n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-12)).tolist()


def _faces(mezz, shots):
    try:
        import cv2
    except ImportError:
        return [None] * len(shots)
    cap = cv2.VideoCapture(mezz)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    out = []
    for s in shots:
        found = []
        for k in range(1, 6):
            cap.set(cv2.CAP_PROP_POS_MSEC, (s['src_in'] + (s['src_out'] - s['src_in']) * k / 6) * 1000)
            ok, fr = cap.read()
            if not ok:
                continue
            g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (fr.shape[1] // 3, fr.shape[0] // 3))
            fs = cap_faces = casc.detectMultiScale(g, 1.1, 5, minSize=(60, 60))
            if len(cap_faces):
                x, y, w, h = max(fs, key=lambda f: f[2] * f[3])
                found.append((x * 3 + w * 1.5, y * 3 + h * 1.5, w * 3, h * 3))
        if found:
            found.sort(key=lambda f: f[0])
            mid = found[len(found) // 2]
            out.append([float(v) for v in mid])
        else:
            out.append(None)
    return out


def run(plan):
    work = plan['work']
    os.makedirs(work, exist_ok=True)
    fps = plan['fps']
    words = json.load(open(plan['words'], encoding='utf8'))
    mezz = os.path.join(work, 'mezz.mkv')
    if not os.path.exists(mezz) or os.path.getmtime(mezz) < os.path.getmtime(plan['source']):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', plan['source'], '-vf', f'fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}',
                        '-c:v', 'libx264', '-crf', '12', '-preset', 'veryfast', '-g', str(fps), '-pix_fmt', 'yuv420p',
                        '-c:a', 'pcm_s16le', '-ar', str(SR), '-ac', '1', mezz], check=True)
    spans = planmod.pick_spans(plan['picks'], words)
    if plan.get('exact'):
        shots = build_exact_shots(spans, words, fps)
        if not shots:
            raise planmod.PlanError('every kept range is shorter than one frame')
    else:
        shots = build_shots(spans, words, _db10(mezz), plan, fps)
    faces = _faces(mezz, shots)
    scales = plan_scales([s['pick'] for s in shots], wide_picks_from(plan), plan.get('punchline'))
    for s, f, sc in zip(shots, faces, scales):
        s['face'], s['scale'] = f, sc
        s['crop'] = crop_for(sc, f)
    dur = timeline(shots)
    for s in shots:
        del s['words']
    edit = {'fps': fps, 'duration': dur, 'lang': plan['lang'], 'shots': shots}
    json.dump(edit, open(os.path.join(work, 'edit.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    # graded picture + cut voice
    parts, vl, al = [], [], []
    fades = join_fades(shots)
    for i, s in enumerate(shots):
        x, y, cw, ch = s['crop']
        d = s['src_out'] - s['src_in']
        parts.append(f"[0:v]trim=start={s['src_in']}:end={s['src_out']},setpts=PTS-STARTPTS,crop={cw}:{ch}:{x}:{y},"
                     f"scale={W}:{H}:flags=lanczos,setsar=1[v{i}]")
        afade = ''.join(([',afade=t=in:d=0.008'] if fades[i][0] else []) + ([f',afade=t=out:st={d - 0.008:.3f}:d=0.008'] if fades[i][1] else []))
        parts.append(f"[0:a]atrim=start={s['src_in']}:end={s['src_out']},asetpts=PTS-STARTPTS{afade}[a{i}]")
        vl.append(f'[v{i}]')
        al.append(f'[a{i}]')
    parts.append(''.join(vl) + f"concat=n={len(shots)}:v=1:a=0,{GRADES.get(plan['grade'], 'null')},format=yuv420p[vout]")
    parts.append(''.join(al) + f'concat=n={len(shots)}:v=0:a=1[aout]')
    fscript = os.path.join(work, 'base.filter')
    open(fscript, 'w').write(';\n'.join(parts))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mezz, '-filter_complex_script', fscript,
                    '-map', '[vout]', '-c:v', 'libx264', '-crf', '12', '-preset', 'medium', '-r', str(fps), os.path.join(work, 'base.mp4'),
                    '-map', '[aout]', '-c:a', 'pcm_s16le', '-ar', str(SR), os.path.join(work, 'voice.wav')], check=True)
    print(f'cut: {len(shots)} shots, {dur:.2f} s')
    for i, s in enumerate(shots):
        print(f"  {i:2d} pick {s['pick']:2d} {s['out_in']:6.2f}-{s['out_out']:6.2f} x{s['scale']:.2f}  {s['text']}")
    return edit
