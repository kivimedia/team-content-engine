"""Stage 5: the skill's checklist, measured on the finished files. `verdicts()` is pure and tested with planted-bad
inputs (a checker that cannot fail proves nothing)."""
import json
import os
import re
import subprocess


def verdicts(x):
    """x: measured numbers. Returns [(PASS|FAIL, name, detail)]."""
    r = []

    def ok(name, cond, detail):
        r.append(('PASS' if cond else 'FAIL', name, detail))
    dur = x['duration']
    ok('first word at 0.00-0.10 s', x['first_word'] <= 0.10, f"{x['first_word']:.2f} s")
    ok('tail after the last word <= 0.2 s', x['tail'] <= 0.20, f"{x['tail']:.2f} s")
    ok('pauses over 0.3 s: at most 1 per 30 s', len(x['pauses']) <= max(1, int(dur // 30)) if dur >= 30 else len(x['pauses']) <= 1,
       f"{len(x['pauses'])} ({', '.join(f'{p:.2f}' for p in x['pauses']) or 'none'})")
    ok('nothing unchanged for more than 4 s', x['still_max'] <= 4.0, f"longest still stretch {x['still_max']:.2f} s")
    ok('a text moment at least every 5 s', x['text_gap_max'] <= 5.0, f"max gap {x['text_gap_max']:.2f} s")
    ok('neighbor shots never share a scale', all(abs(a - b) >= 0.05 for a, b in zip(x['scales'], x['scales'][1:])),
       ' '.join(f'{s:.2f}' for s in x['scales']))
    lo, hi = x.get('length_range', (20, 90))
    ok(f'length inside {lo}-{hi} s', lo <= dur <= hi, f'{dur:.2f} s')
    ok('loudness -14 LUFS +/- 1', abs(x['lufs'] + 14) <= 1.0, f"{x['lufs']:.2f} LUFS")
    ok('true peak <= -1 dBTP', x['tp'] <= -1.0, f"{x['tp']:.2f} dBTP")
    fps = x.get('fps', 25)
    ok(f'1080x1920 at {fps} fps', x['video'] == f'1080,1920,{fps}/1', x['video'])
    ok('every pop has a sound', not x['silent_pops'], f"silent at {', '.join(f'{t:.2f}' for t in x['silent_pops']) or 'none'}")
    ok('sky text kept readable', all(d['layer'] != 'sky' or ((d['max_hidden'] or 0) <= 0.20 and (d.get('worst_letter') or 0) <= 0.35)
                                     for d in x.get('sky', [])),
       '; '.join(f"{d['text']}: {d['layer']}" for d in x.get('sky', [])) or 'no sky text')
    # the look (10-Nov): what a viewer calls ugly, measured from where every text box and face really is.
    # A reel with no look report fails these lines: a check that saw nothing proves nothing.
    look = x.get('look')

    def seen(key):
        return (look or {}).get(key) or []

    def names(key):
        return ', '.join(f"{i['what'][:24]} at {i['t']:.1f} s" if isinstance(i, dict) else f'{i:.1f} s' for i in seen(key)[:4]) or 'none'
    ok('no text on the face', look is not None and not seen('on_face'), names('on_face') if look is not None else 'no look report')
    ok('text inside the safe area', look is not None and not seen('edge'), names('edge') if look is not None else 'no look report')
    ok('the head stays in the frame', look is not None and not seen('cut_head'), names('cut_head') if look is not None else 'no look report')
    ok('one accent color', look is not None and len(set(seen('accents'))) <= 1,
       ', '.join(seen('accents')) or ('white only' if look is not None else 'no look report'))
    ok('nothing said twice on screen', look is not None and not seen('twice'), names('twice') if look is not None else 'no look report')
    ok('cards stay up long enough to read', look is not None and not seen('short_cards'),
       ', '.join(f"{c['what']} at {c['t']:.1f} s: {c['shown']:.1f} of {c['needs']:.1f} s" for c in seen('short_cards')) or
       ('none' if look is not None else 'no look report'))
    return r


def gaps(marks, dur):
    m = sorted({0.0, dur} | set(marks))
    return max((b - a for a, b in zip(m, m[1:])), default=dur)


def run(plan):
    import numpy as np
    work = plan['work']
    edit = json.load(open(os.path.join(work, 'edit.json'), encoding='utf8'))
    ev = json.load(open(os.path.join(work, 'events.json'), encoding='utf8'))
    dur = edit['duration']
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', os.path.join(work, 'voice.wav'), '-f', 's16le', '-ac', '1', '-ar', '48000', '-'],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    hop = 480
    n = len(a) // hop
    db = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-12)
    on = np.where(db > plan.get('thr_db', -40))[0]
    sd = subprocess.run(['ffmpeg', '-i', os.path.join(work, 'voice.wav'), '-af', 'silencedetect=noise=-35dB:d=0.3', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    ln = subprocess.run(['ffmpeg', '-i', plan['out'], '-af', 'loudnorm=I=-14:TP=-1:print_format=json', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    m = json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}', ln)[-1])
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height,r_frame_rate',
                         '-of', 'csv=p=0', plan['out']], capture_output=True, text=True).stdout.strip()
    pops = ev['moments']
    cues = [t for t, _, _ in ev['sfx']]
    x = {'duration': dur, 'first_word': on[0] * 0.01 if len(on) else 9.9, 'tail': dur - (on[-1] + 1) * 0.01 if len(on) else 9.9,
         'pauses': [float(p) for p in re.findall(r'silence_duration: ([\d.]+)', sd)],
         'still_max': gaps([s['out_in'] for s in edit['shots']] + pops + ev['flashes'], dur),
         'text_gap_max': gaps(pops + ev.get('ticks', []), dur),
         'scales': [s['scale'] for s in edit['shots']], 'lufs': float(m['input_i']), 'tp': float(m['input_tp']), 'video': pr,
         'silent_pops': [t for t in pops if not any(abs(t - c) <= 0.12 for c in cues)], 'sky': ev.get('sky', []),
         'look': ev.get('look'),
         'length_range': tuple(plan.get('length_range', (20, 90))), 'fps': plan.get('fps', 25)}
    res = verdicts(x)
    words = sum(len(s['owords']) for s in edit['shots'])
    res.append(('INFO', 'pace', f'{words / dur * 60:.0f} words/min'))
    json.dump(res, open(os.path.join(work, 'checklist.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    for v in res:
        print(f'{v[0]:4}  {v[1]}: {v[2]}')
    return res
