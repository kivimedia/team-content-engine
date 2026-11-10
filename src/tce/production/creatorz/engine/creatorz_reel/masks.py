"""Stage 2: person masks (rembg u2net_human_seg, local, free) for the frames where a headline sits in the sky.
Optional: without rembg, sky headlines fall back to the front at the top of the frame (compose decides)."""
import hashlib
import json
import os
import subprocess
import time

from . import compose_plan

W2, H2 = 540, 960


def cut_stamp(edit):
    """what the base.mp4 frames depend on: every shot's source range and crop"""
    key = json.dumps([(s['src_in'], s['src_out'], s['crop']) for s in edit['shots']])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def run(plan):
    work = plan['work']
    edit = json.load(open(os.path.join(work, 'edit.json'), encoding='utf8'))
    fps = edit['fps']
    frames = set()
    for t0, t1 in compose_plan.sky_intervals(plan, edit):
        frames.update(range(int(t0 * fps), int(t1 * fps) + 1))
    mdir = os.path.join(work, 'masks')
    os.makedirs(mdir, exist_ok=True)
    # masks are cached by frame number: a re-cut moves every frame, so a changed cut clears the cache
    stamp = cut_stamp(edit)
    sp = os.path.join(mdir, 'cut.txt')
    if not os.path.exists(sp) or open(sp).read().strip() != stamp:
        for f in os.listdir(mdir):
            if f.endswith('.png'):
                os.remove(os.path.join(mdir, f))
        open(sp, 'w').write(stamp + '\n')
    if not frames:
        print('masks: no sky headlines, nothing to mask')
        return 0
    try:
        from rembg import new_session, remove
        from PIL import Image
    except ImportError:
        open(os.path.join(mdir, 'NO_REMBG.txt'), 'w').write('rembg not installed: sky headlines go to the front\n')
        print('masks: rembg not installed; sky headlines will sit in front of the speaker')
        return 0
    sess = new_session('u2net_human_seg')
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', os.path.join(work, 'base.mp4'), '-vf', f'scale={W2}:{H2}',
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    t0, done, idx = time.time(), 0, 0
    while True:
        buf = proc.stdout.read(W2 * H2 * 3)
        if len(buf) < W2 * H2 * 3:
            break
        if idx in frames and not os.path.exists(os.path.join(mdir, f'f{idx:05d}.png')):
            m = remove(Image.frombytes('RGB', (W2, H2), buf), session=sess, only_mask=True, post_process_mask=True)
            m.save(os.path.join(mdir, f'f{idx:05d}.png'))
            done += 1
            if done % 100 == 0:
                print(f'masks: {done}/{len(frames)} ({time.time() - t0:.0f} s)', flush=True)
        idx += 1
    proc.wait()
    print(f'masks: {done} new frames in {time.time() - t0:.0f} s')
    return done
