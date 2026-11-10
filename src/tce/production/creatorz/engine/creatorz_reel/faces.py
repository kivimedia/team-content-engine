"""Where the speaker's face is in every shot (media: OpenCV + numpy). YuNet first (the model sits in engine/models; it
finds tilted selfie faces the old Haar cascade missed, which left punch-ins centered and cut foreheads, 10-Nov), then
Haar on OpenCV 4, then nothing: every caller treats None as "no face found" and falls back to centered defaults."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(os.path.dirname(HERE), 'models', 'face_yunet.onnx')
DET_W, DET_H = 360, 640           # detection runs on a small copy; boxes are scaled back to the frame
MAX_SAMPLES = 16


def summarize(found, n_samples):
    """One shot's face from its samples. Each found item: dict(k, x0, y0, x1, y1, eye_y, mouth_y, luma). The center and
    size are medians (for the crop); top / chin / sides are the EXTREMES (for layout: text must clear the face in every
    frame, not on average). Pure. None when fewer than a third of the samples found a face."""
    if not found or len(found) * 3 < n_samples:
        return None

    def med(vals):
        v = sorted(vals)
        return v[len(v) // 2]
    fw, fh = med([f['x1'] - f['x0'] for f in found]), med([f['y1'] - f['y0'] for f in found])
    return {
        'cx': med([(f['x0'] + f['x1']) / 2 for f in found]), 'cy': med([(f['y0'] + f['y1']) / 2 for f in found]),
        'fw': fw, 'fh': fh, 'eye_y': med([f['eye_y'] for f in found]),
        'top': min(f['y0'] for f in found), 'chin': max(f['y1'] for f in found),
        'left': min(f['x0'] for f in found), 'right': max(f['x1'] for f in found),
        'mouth': max(f['mouth_y'] for f in found),
        'luma': med([f['luma'] for f in found]) if all(f.get('luma') is not None for f in found) else None,
        'track': [[f['k'], round((f['x0'] + f['x1']) / 2, 1), round(f['eye_y'], 1)] for f in found],
    }


def _detector():
    try:
        import cv2
    except ImportError:
        return None, None
    if hasattr(cv2, 'FaceDetectorYN') and os.path.exists(MODEL):
        try:
            return 'yunet', cv2.FaceDetectorYN.create(MODEL, '', (DET_W, DET_H), 0.6, 0.3, 50)
        except Exception:
            pass
    if hasattr(cv2, 'CascadeClassifier'):
        return 'haar', cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    return None, None


def _one(kind, det, frame):
    """the biggest face in one BGR frame as (x0, y0, x1, y1, eye_y, mouth_y) in frame pixels, or None"""
    import cv2
    h, w = frame.shape[:2]
    small = frame if (w, h) == (DET_W, DET_H) else cv2.resize(frame, (DET_W, DET_H))
    sx, sy = w / DET_W, h / DET_H
    if kind == 'yunet':
        _n, rows = det.detect(small)
        if rows is None or not len(rows):
            return None
        r = max(rows, key=lambda r: r[2] * r[3])
        x, y, bw, bh = r[0], r[1], r[2], r[3]
        eye_y, mouth_y = (r[5] + r[7]) / 2, (r[11] + r[13]) / 2
        return x * sx, y * sy, (x + bw) * sx, (y + bh) * sy, eye_y * sy, mouth_y * sy
    faces = det.detectMultiScale(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(40, 40))
    if not len(faces):
        return None
    x, y, bw, bh = max(faces, key=lambda f: f[2] * f[3])
    return x * sx, y * sy, (x + bw) * sx, (y + bh) * sy, (y + bh * 0.38) * sy, (y + bh * 0.78) * sy


RATE = 5                           # samples a second


def shot_samples(shots, t_first, n, rate=RATE):
    """Which of the n evenly spaced samples (sample k is at t_first + k / rate) belong to each shot: [[k, ...], ...].
    A shot shorter than a sample gap takes the nearest sample, so no shot goes unseen. Pure."""
    out = []
    for s in shots:
        ks = [k for k in range(n) if s['src_in'] <= t_first + k / rate < s['src_out']][:MAX_SAMPLES * 2]
        if not ks and n:
            mid = (s['src_in'] + s['src_out']) / 2
            ks = [min(n - 1, max(0, round((mid - t_first) * rate)))]
        out.append(ks)
    return out


def detect(mezz, shots, fps, w=1080, h=1920):
    """Per shot: summarize() of its samples, or None. Also returns the mean background color of the reel (RGB, outside
    the faces), which picks the accent color. The footage is read ONCE, straight through, small and at RATE frames a
    second: seeking to every sample decoded a second of video each time and took minutes (10-Nov)."""
    kind, det = _detector()
    if det is None or not shots:
        return [None] * len(shots), None
    import subprocess
    import numpy as np
    t_first = max(0.0, min(s['src_in'] for s in shots))
    t_last = max(s['src_out'] for s in shots)
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{t_first:.3f}', '-i', mezz, '-t', f'{t_last - t_first + 0.3:.3f}',
                             '-vf', f'fps={RATE},scale={DET_W}:{DET_H}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                            stdout=subprocess.PIPE)
    seen, bg = [], []
    size = DET_W * DET_H * 3
    sx, sy = w / DET_W, h / DET_H
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(DET_H, DET_W, 3).copy()
        got = _one(kind, det, fr)
        if not got:
            seen.append(None)
            continue
        x0, y0, x1, y1, eye_y, mouth_y = [float(v) for v in got]
        ix0, iy0, ix1, iy1 = max(0, int(x0)), max(0, int(y0)), min(DET_W, int(x1)), min(DET_H, int(y1))
        luma = None
        if ix1 > ix0 and iy1 > iy0:
            patch = fr[iy0:iy1, ix0:ix1]
            luma = float((patch[..., 0] * 0.114 + patch[..., 1] * 0.587 + patch[..., 2] * 0.299).mean() / 255.0)
            m = np.ones((DET_H, DET_W), bool)
            m[iy0:iy1 + 1, ix0:ix1 + 1] = False
            m[DET_H // 2:, :] = False                          # the lower half is mostly the speaker's shirt
            if m.any():
                bg.append(fr[m].mean(0)[::-1])                 # BGR -> RGB
        seen.append({'x0': x0 * sx, 'y0': y0 * sy, 'x1': x1 * sx, 'y1': y1 * sy, 'eye_y': eye_y * sy,
                     'mouth_y': mouth_y * sy, 'luma': luma})
    proc.stdout.close()
    proc.wait()
    out = []
    for s, ks in zip(shots, shot_samples(shots, t_first, len(seen))):
        found = [dict(seen[k], k=max(0, round((t_first + k / RATE - s['src_in']) * fps))) for k in ks if seen[k]]
        out.append(summarize(found, len(ks)))
    back = [float(v) for v in np.mean(bg, axis=0)] if bg else None
    return out, back
