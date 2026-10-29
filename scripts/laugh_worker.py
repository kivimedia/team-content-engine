"""Where a recording laughs (29-Oct-2026, Ziv on Connie's videos: "dont cut out her laughs!").

Run by the laugh detector's own Python (scripts/setup-laughs.sh builds it), never by the
API's, so torch and librosa stay out of the server. Reads one recording and prints JSON:

    {"laughs": [[start_s, end_s, peak], ...], "step_s": 0.093, "seconds": 59.9}

The model is Gillick et al.'s laughter detector (github.com/jrgillick/laughter-detection,
MIT license, a ResNet on mel spectrograms trained on Switchboard phone calls with AudioSet
noise), pinned in setup-laughs.sh. A general sound tagger (AudioSet AST) scored her laughs
0.00-0.01, hearing them as speech or a gasp; this one scored the laugh the edit cut from
"Get your ask in gear" (0:38.9) 0.98.

No upstream code runs: the network below is a copy of its ResNetBigger (models.py at the
pinned commit, MIT, (c) Jon Gillick), and the checkpoint is read with torch's tensor-only
loader (weights_only=True), never unpickled as code.

Usage: python laugh_worker.py <model dir> <recording> [--ffmpeg PATH] [--threads N]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np

SR = 8000  # the model's sample rate
HOP = 186  # the model's frames: 43 a second
WINDOW = 44  # frames the model reads at once, about one second
STEP = 4  # every 4th window is scored: 0.093 s apart, finer than any laugh, 4x faster
BATCH = 32
ON = 0.5  # a window this sure is laughter
MERGE_S = 0.2  # laughter this close together is one laugh
MIN_PEAK = 0.6  # a run of windows never this sure is not reported


CHECKPOINT = "checkpoints/in_use/resnet_with_augmentation/best.pth.tar"


def network():
    """Upstream ResNetBigger(dropout_rate=0, linear_layer_size=128,
    filter_sizes=[128, 64, 32, 32]): the layer names match its state dict."""
    from torch import nn

    class Residual(nn.Module):
        def __init__(self, cin: int, cout: int, stride: int = 1) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(cin, cout, (3, 3), stride=stride, padding=1, bias=True)
            self.bn1 = nn.BatchNorm2d(cout)
            self.conv2 = nn.Conv2d(cout, cout, (3, 3), stride=1, padding=1, bias=True)
            self.bn2 = nn.BatchNorm2d(cout)
            self.shortcut = nn.Sequential()
            if stride != 1 or cin != cout:
                self.shortcut = nn.Sequential(
                    nn.Conv2d(cin, cout, (1, 1), stride=stride, bias=False), nn.BatchNorm2d(cout)
                )

        def forward(self, x):
            out = nn.functional.relu(self.bn1(self.conv1(x)))
            out = self.bn2(self.conv2(out)) + self.shortcut(x)
            return nn.functional.relu(out)

    class Laughter(nn.Module):
        def __init__(self, sizes=(128, 64, 32, 32), linear: int = 128) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(1, 64, (3, 3), stride=1, padding=1, bias=False)
            self.bn1 = nn.BatchNorm2d(64)
            ins = (64,) + tuple(sizes[:-1])
            for n, (cin, cout, stride) in enumerate(zip(ins, sizes, (1, 2, 2, 2)), 1):
                setattr(self, f"block{n}", nn.Sequential(Residual(cin, cout, stride), Residual(cout, cout)))
            self.bn2 = nn.BatchNorm1d(linear)
            self.bn3 = nn.BatchNorm1d(32)
            self.linear1 = nn.Linear(linear, 32)
            self.linear2 = nn.Linear(32, 1)

        def forward(self, x):
            out = nn.functional.relu(self.bn1(self.conv1(x)))
            for block in (self.block1, self.block2, self.block3, self.block4):
                out = block(out)
            out = nn.functional.avg_pool2d(out, 4).flatten(1)
            out = nn.functional.relu(self.bn3(self.linear1(self.bn2(out))))
            return self.linear2(out).sigmoid()

    return Laughter()


def runs(times: list[float], probs: list[float], step_s: float) -> list[list[float]]:
    """[start, end, peak] for each stretch of windows over ON, joined across short dips."""
    out: list[list[float]] = []
    for t, p in zip(times, probs, strict=True):
        if p <= ON:
            continue
        lo, hi = t - step_s / 2, t + step_s / 2
        if out and lo - out[-1][1] <= MERGE_S:
            out[-1][1] = hi
            out[-1][2] = max(out[-1][2], p)
        else:
            out.append([lo, hi, p])
    return [[round(max(0.0, a), 3), round(b, 3), round(p, 3)] for a, b, p in out if p >= MIN_PEAK]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("recording")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()

    import librosa
    import torch

    torch.set_num_threads(max(1, args.threads))
    model = network()
    # The checkpoint also stores its training loss as a numpy number: the tensor-only
    # loader may rebuild numpy scalars and dtypes (data, not code), nothing else.
    safe = [(np._core.multiarray.scalar, "numpy.core.multiarray.scalar"), np.dtype]
    safe += [getattr(np.dtypes, n) for n in ("Float64DType", "Float32DType", "Int64DType")]
    with torch.serialization.safe_globals(safe):
        checkpoint = torch.load(f"{args.model_dir}/{CHECKPOINT}", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    raw = subprocess.run(
        [args.ffmpeg, "-v", "error", "-i", args.recording, "-vn", "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    y = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    seconds = len(y) / SR
    step_s = STEP * HOP / SR
    if len(y) < SR:
        print(json.dumps({"laughs": [], "step_s": step_s, "seconds": round(seconds, 3)}))
        return 0
    # The model's own features: librosa's mel spectrogram in dB against the loudest bin.
    feats = librosa.amplitude_to_db(
        librosa.feature.melspectrogram(y=y, sr=SR, hop_length=HOP).T, ref=np.max
    ).astype(np.float32)
    starts = list(range(0, max(0, len(feats) - WINDOW), STEP))
    probs: list[float] = []
    with torch.no_grad():
        for k in range(0, len(starts), BATCH):
            chunk = np.stack([feats[i : i + WINDOW] for i in starts[k : k + BATCH]])[:, None]
            probs.extend(float(p) for p in model(torch.from_numpy(chunk)).reshape(-1))
    # A window's score belongs to its middle.
    times = [(i + WINDOW / 2) * HOP / SR for i in starts]
    print(json.dumps({
        "laughs": runs(times, probs, step_s),
        "step_s": round(step_s, 4),
        "seconds": round(seconds, 3),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
