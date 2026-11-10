"""Stage 4: voice on top, the bed ducked under it, every sound cue (whoosh, tick, ding, flash, riser) from
events.json, two-pass loudnorm to -14 LUFS with a -1.5 dBTP ceiling; then mux with overlay.mp4 -> the reel."""
import json
import os
import re
import subprocess

SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sfx')


def run(plan):
    work = plan['work']
    ev = json.load(open(os.path.join(work, 'events.json'), encoding='utf8'))
    dur = json.load(open(os.path.join(work, 'edit.json'), encoding='utf8'))['duration']
    names = sorted({n for _, n, _ in ev['sfx']})
    for n in names:
        if not os.path.exists(os.path.join(SFX_DIR, f'{n}.mp3')):
            raise FileNotFoundError(f'sound "{n}" has no file {SFX_DIR}/{n}.mp3')
    inputs = ['-i', os.path.join(work, 'voice.wav')]
    bed = plan.get('bed')
    if bed:
        inputs += ['-stream_loop', '-1', '-i', bed]
    first_sfx = inputs.count('-i')          # count inputs, not args: -stream_loop adds two
    inputs += sum([['-i', os.path.join(SFX_DIR, f'{n}.mp3')] for n in names], [])
    idx = {n: first_sfx + k for k, n in enumerate(names)}
    parts = ["[0:a]highpass=f=85,acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=3,"
             "equalizer=f=3200:t=q:w=1.2:g=2,aresample=48000,asplit=2[vo][vkey]"]
    mixin = ['[vo]']
    if bed:
        parts.append(f"[1:a]aresample=48000,atrim=0:{dur},asetpts=PTS-STARTPTS,volume={plan.get('bed_gain_db', -15)}dB,"
                     f"afade=t=out:st={max(0.0, dur - 0.15):.2f}:d=0.15[bedraw]")
        parts.append('[bedraw][vkey]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=250[bed]')
        mixin.append('[bed]')
    else:
        parts.append('[vkey]anullsink')
    counts = {n: sum(1 for _, m, _ in ev['sfx'] if m == n) for n in names}
    for n in names:
        labs = ''.join(f'[{n}{k}]' for k in range(counts[n]))
        parts.append(f"[{idx[n]}:a]aresample=48000,asplit={counts[n]}{labs}" if counts[n] > 1 else f"[{idx[n]}:a]aresample=48000[{n}0]")
    seen = {n: 0 for n in names}
    for j, (t, n, g) in enumerate(ev['sfx']):
        k = seen[n]
        seen[n] += 1
        ms = max(0, int((t - (0.05 if n == 'whoosh' else 0.0)) * 1000))
        parts.append(f"[{n}{k}]adelay={ms}|{ms},volume={g - 4}dB[s{j}]")
        mixin.append(f'[s{j}]')
    parts.append(f"{''.join(mixin)}amix=inputs={len(mixin)}:normalize=0:duration=first,atrim=0:{dur}[mixraw]")
    base = ';\n'.join(parts)

    def go(tail, out):
        fs = os.path.join(work, 'mix.filter')
        open(fs, 'w').write(base + f';\n[mixraw]{tail}[mout]')
        r = subprocess.run(['ffmpeg', '-v', 'info', '-y'] + inputs + ['-filter_complex_script', fs, '-map', '[mout]'] + out,
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-1500:])
        return r
    r = go('loudnorm=I=-14:TP=-1.5:LRA=9:print_format=json', ['-f', 'null', '-'])
    m = json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr)[-1])
    go(f"loudnorm=I=-14:TP=-1.5:LRA=9:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
       f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,alimiter=limit=0.84:level=false,aresample=48000",
       ['-c:a', 'pcm_s16le', os.path.join(work, 'mix.wav')])
    out = plan['out']
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.join(work, 'overlay.mp4'), '-i', os.path.join(work, 'mix.wav'),
                    '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart',
                    '-shortest', out], check=True)
    print(f"mix: {len(ev['sfx'])} cues, bed {'on' if bed else 'off'} -> {out}")
    return out
