"""Stage 1: the cut. Footage -> 25 fps master -> voiced runs inside each pick -> shots with alternating punch-ins ->
graded base.mp4 + voice.wav + edit.json. The pure helpers (voiced_runs, plan_scales, crop_for, timeline) carry no numpy."""
import json
import math
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import faces as facesmod
from . import layout
from . import plan as planmod

W, H = 1080, 1920
SR = 48000
ALT = (1.18, 1.26, 1.12, 1.22)
WIDE, PUNCH = 1.0, 1.48
GRADES = {
    # golden hour outdoors: warm skin and mids, deeper blacks, and a soft SHOULDER on the highlights. The first grade
    # lifted them (0.92 -> 0.95) and burned the sky; vibrance lifts the dull colors and leaves skin alone.
    'golden': ("eq=contrast=1.06:gamma=0.99,vibrance=intensity=0.22,"
               "colorbalance=rs=0.03:bs=-0.04:rm=0.03:gm=0.0:bm=-0.03:rh=-0.02:gh=0.0:bh=0.02,"
               "curves=all='0/0 0.08/0.055 0.5/0.5 0.86/0.845 1/0.97'"),
    # studio: teal-cyan shadows and background, warm skin, deep blacks
    'studio': ("eq=contrast=1.08,vibrance=intensity=0.12,"
               "colorbalance=rs=-0.04:gs=0.0:bs=0.05:rm=0.03:gm=0.0:bm=-0.02,"
               "curves=all='0/0 0.1/0.055 0.5/0.5 0.88/0.865 1/0.97'"),
    'none': 'null',
}
FINISH = 'unsharp=5:5:0.35:5:5:0.0,vignette=angle=0.38'      # a punch-in softens the picture; the edges fall off a little
PUSH_PER_S, PUSH_MAX, FOLLOW_MAX = 0.011, 0.03, 48


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


def video_segment_cmd(mezz, shot, fps, grade, out):
    """One shot of the base picture as its own short job. One graph with a trim branch per shot makes ffmpeg hold the
    decoded frames of every later branch (3 MB a frame: past 6 GB on a 2 minute recording, killed by the kernel on the
    server, 10-Nov). The seek sits a quarter frame early, so the frame at src_in is the first one kept. A shot with
    `follow` keys moves its crop with the face (the eyes stay put while the phone drifts); `gamma` matches its
    brightness to the rest of the reel."""
    frames = max(1, round((shot['src_out'] - shot['src_in']) * fps))
    x, y, cw, ch = shot['crop']
    seek = max(0.0, shot['src_in'] - 0.25 / fps)
    keys = shot.get('follow') or []
    if keys:
        crop = f"crop=w={cw}:h={ch}:x='{x}+({layout.piecewise(keys, 1)})':y='{y}+({layout.piecewise(keys, 2)})'"
    else:
        crop = f'crop={cw}:{ch}:{x}:{y}'
    gamma = shot.get('gamma') or 1.0
    match = f'eq=gamma={gamma},' if abs(gamma - 1.0) > 1e-6 else ''
    return ['ffmpeg', '-v', 'error', '-y', '-ss', f'{seek:.6f}', '-i', mezz, '-map', '0:v:0', '-frames:v', str(frames),
            '-vf', f'{crop},scale={W}:{H}:flags=lanczos,setsar=1,{match}{grade},format=yuv420p', '-r', str(fps),
            '-c:v', 'libx264', '-crf', '12', '-preset', 'veryfast', '-bf', '0', '-g', str(fps), '-threads', '4',
            '-pix_fmt', 'yuv420p', '-an', out]


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


def frame_shots(shots, faces, scales, fps, plan, target_luma):
    """Scale, crop, face-follow, brightness match and slow push for every shot, from its face. Pure."""
    for s, f, sc in zip(shots, faces, scales):
        s['scale'] = sc
        s['crop'] = layout.crop_for(sc, f)
        fo = layout.to_out(f, s['crop'])
        s['face'] = {k: round(v, 1) for k, v in fo.items()} if fo else None
        s['gamma'] = layout.exposure_gamma(f.get('luma') if f else None, target_luma)
        x, y, cw, ch = s['crop']
        room = min(x, W - x - cw, y, H - y - ch)
        frames = max(1, round((s['src_out'] - s['src_in']) * fps))
        steady = bool(f) and plan.get('steady', True) and room >= 6
        s['follow'] = layout.smooth_track(f['track'], frames, min(room, FOLLOW_MAX)) if steady else []
        d = s['src_out'] - s['src_in']
        s['push'] = round(min(PUSH_MAX, PUSH_PER_S * d), 4) if (plan.get('push', True) and d >= 0.8) else 0.0
    return shots


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
    faces, back = facesmod.detect(mezz, shots, fps)
    picks = [s['pick'] for s in shots]
    punch = picks.index(plan['punchline']) if plan.get('punchline') in picks else None
    scales = layout.fit_scales(plan_scales(picks, wide_picks_from(plan), plan.get('punchline')), faces, punch)
    lumas = sorted(f['luma'] for f in faces if f and f.get('luma'))
    frame_shots(shots, faces, scales, fps, plan, lumas[len(lumas) // 2] if lumas else None)
    dur = timeline(shots)
    for s in shots:
        del s['words']
    edit = {'fps': fps, 'duration': dur, 'lang': plan['lang'], 'shots': shots,
            'accent': plan.get('accent') or layout.pick_accent(back), 'background': [round(v) for v in back] if back else None}
    json.dump(edit, open(os.path.join(work, 'edit.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    # graded picture + cut voice
    parts, al = [], []
    fades = join_fades(shots)
    for i, s in enumerate(shots):
        d = s['src_out'] - s['src_in']
        afade = ''.join(([',afade=t=in:d=0.008'] if fades[i][0] else []) + ([f',afade=t=out:st={d - 0.008:.3f}:d=0.008'] if fades[i][1] else []))
        parts.append(f"[0:a]atrim=start={s['src_in']}:end={s['src_out']},asetpts=PTS-STARTPTS{afade}[a{i}]")
        al.append(f'[a{i}]')
    parts.append(''.join(al) + f'concat=n={len(shots)}:v=0:a=1[aout]')
    fscript = os.path.join(work, 'base.filter')
    open(fscript, 'w').write(';\n'.join(parts))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mezz, '-filter_complex_script', fscript, '-map', '[aout]', '-c:a', 'pcm_s16le',
                    '-ar', str(SR), os.path.join(work, 'voice.wav')], check=True)
    segments = os.path.join(work, 'segments')
    os.makedirs(segments, exist_ok=True)
    names = [os.path.join(segments, f's{i:04d}.mkv') for i in range(len(shots))]
    grade = GRADES.get(plan['grade'], 'null')
    if plan['grade'] != 'none':
        grade = f'{grade},{FINISH}'
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda job: subprocess.run(video_segment_cmd(mezz, job[0], fps, grade, job[1]), check=True), zip(shots, names)))
    listing = os.path.join(segments, 'list.txt')
    with open(listing, 'w', encoding='utf8') as f:
        f.write(''.join(f"file '{os.path.basename(n)}'\n" for n in names))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', os.path.join(work, 'base.mp4')],
                   check=True)
    shutil.rmtree(segments, ignore_errors=True)
    print(f"cut: {len(shots)} shots, {dur:.2f} s, faces in {sum(1 for s in shots if s['face'])}, accent {edit['accent']}")
    for i, s in enumerate(shots):
        print(f"  {i:2d} pick {s['pick']:2d} {s['out_in']:6.2f}-{s['out_out']:6.2f} x{s['scale']:.2f}  {s['text']}")
    return edit
