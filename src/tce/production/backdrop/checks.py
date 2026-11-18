"""What a redrawn scene must pass before it replaces the real one.

Cheapest first: the length, then the timing of the speech, then where the face sits, then a
model that looks at stills for what the eye would catch (a car, a stranger, a sign, a face that
is no longer theirs). A scene that fails is drawn once more; a second failure keeps the real
background, so a video never waits on this step.

The measuring functions are pure (numbers in, a Finding out) so each one has a test with a
planted-bad case it must fail on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Seconds the result may be longer or shorter than the scene (the tail is trimmed or held).
LENGTH_TOL_S = 0.2
# How far the speech in the result may sit from the real speech, and how far that may wander
# between the first and the second half of the scene.
LAG_TOL_S = 0.06
DRIFT_TOL_S = 0.06
# Below this the two sound tracks are not the same speech at all.
MIN_MATCH = 0.35
# The face: how far its center may move (share of the frame width) and how much it may grow.
FACE_MOVE = 0.10
FACE_GROW = (0.72, 1.38)

ENV_HZ = 500  # the loudness curve is compared in 2 ms steps


@dataclass
class Finding:
    name: str
    ok: bool
    detail: str
    fix: str = ""  # a line added to the next try's instructions

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


# ------------------------------------------------------------------- length
def length(scene_s: float, result_s: float, tol_s: float = LENGTH_TOL_S) -> Finding:
    off = result_s - scene_s
    return Finding(
        "length",
        abs(off) <= tol_s,
        f"scene {scene_s:.2f} s, result {result_s:.2f} s ({off:+.2f} s)",
    )


# ------------------------------------------------------------------- timing
def envelope(samples, rate: int, hz: int = ENV_HZ):
    """Loudness over time: the mean level of every 1/hz second."""
    import numpy as np

    step = max(1, rate // hz)
    n = len(samples) // step
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.abs(samples[: n * step]).reshape(n, step).mean(axis=1)


def lag(real, result, hz: int = ENV_HZ, reach_s: float = 0.3) -> tuple[float, float]:
    """(seconds the result's speech sits after the real speech, how well the two match 0..1)."""
    import numpy as np

    n = min(len(real), len(result))
    reach = int(reach_s * hz)
    if n < 4 * reach or n == 0:
        return 0.0, 0.0
    a = real[:n] - real[:n].mean()
    b = result[:n] - result[:n].mean()
    norm = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if norm <= 1e-12:
        return 0.0, 0.0
    best_k, best = 0, -2.0
    for k in range(-reach, reach + 1):
        score = float((a[max(0, -k) : n - max(0, k)] * b[max(0, k) : n - max(0, -k)]).sum()) / norm
        if score > best:
            best_k, best = k, score
    return best_k / hz, max(0.0, best)


def timing(real, result, hz: int = ENV_HZ) -> Finding:
    """``real`` and ``result`` are loudness curves (``envelope``) of the scene's voice and of
    the sound the model returned. The model keeps the speech, so its sound tells where its
    picture's mouth is: the real voice is laid back over the picture afterwards."""
    whole, match = lag(real, result, hz)
    if match < MIN_MATCH:
        return Finding(
            "timing",
            False,
            f"the speech in the result does not match the scene (match {match:.2f})",
        )
    half = min(len(real), len(result)) // 2
    first, m1 = lag(real[:half], result[:half], hz)
    second, m2 = lag(real[half:], result[half:], hz)
    drift = second - first if min(m1, m2) >= MIN_MATCH else 0.0
    ok = abs(whole) <= LAG_TOL_S and abs(drift) <= DRIFT_TOL_S
    return Finding(
        "timing",
        ok,
        f"speech {whole * 1000:+.0f} ms from the real voice, {drift * 1000:+.0f} ms of wander, match {match:.2f}",
    )


# --------------------------------------------------------------------- face
def detect_faces(jpegs: list[bytes], model: str) -> list[tuple[float, float, float] | None]:
    """The biggest face in each still as (center x, center y, width), all as shares of the
    frame width; None where there is no face."""
    import cv2
    import numpy as np

    found: list[tuple[float, float, float] | None] = []
    det = None
    for data in jpegs:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            found.append(None)
            continue
        h, w = img.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(model, "", (w, h), 0.6, 0.3, 50)
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None or len(faces) == 0:
            found.append(None)
            continue
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
        found.append((float(x + fw / 2) / w, float(y + fh / 2) / w, float(fw) / w))
    return found


def faces(
    real: list[tuple[float, float, float] | None],
    result: list[tuple[float, float, float] | None],
) -> Finding:
    """Same stills, real and redrawn. Where the real one shows a face the redrawn one must show
    one in the same place at about the same size."""
    pairs = [(a, b) for a, b in zip(real, result, strict=False) if a is not None]
    if not pairs:
        return Finding("face", True, "no face in the real scene to compare")
    gone = sum(1 for _a, b in pairs if b is None)
    if gone:
        return Finding(
            "face",
            False,
            f"no face in {gone} of {len(pairs)} stills",
            "Important: the person's face and head must stay fully visible, exactly where they are in the source video.",
        )
    move = max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in pairs)
    grow = [b[2] / a[2] for a, b in pairs if a[2] > 0]
    worst = max(grow, key=lambda g: abs(g - 1.0)) if grow else 1.0
    ok = move <= FACE_MOVE and FACE_GROW[0] <= worst <= FACE_GROW[1]
    return Finding(
        "face",
        ok,
        f"face moved {move * 100:.0f}% of the frame width at most, size x{worst:.2f}",
        ""
        if ok
        else "Important: keep the person's head at exactly the same position and size in the frame as in the source video.",
    )


# -------------------------------------------------------------------- judge
JUDGE_PROMPT = (
    "The first image is a still from a real selfie video of a person walking and talking. The "
    "other images are stills from an edited version of the same moment, where only the "
    "background was replaced. Look at the edited stills and answer in JSON with these keys:\n"
    '  "vehicles": true if any car, truck, bus, motorcycle, bicycle, scooter or other vehicle is visible anywhere, parked or moving\n'
    '  "other_people": true if any person other than the speaker is visible\n'
    '  "readable_text": true if any sign, lettering, logo, number plate or other readable text is visible in the background\n'
    '  "same_person": true if the speaker is clearly the same person as in the first image (same face, hair, glasses and facial hair if any, same clothes)\n'
    '  "face_problem": true if the face or hands look distorted, melted, doubled or unnatural in any edited still\n'
    '  "notes": one short sentence on anything that looks wrong, or ""\n'
    "Judge only what is visible. Small or distant things count."
)

_JUDGE_LINES = (
    (
        "vehicles",
        True,
        "a vehicle in the frame",
        "Important: the last attempt showed a vehicle. There must be no cars or vehicles of any kind anywhere, parked or moving.",
    ),
    (
        "other_people",
        True,
        "another person in the frame",
        "Important: the last attempt showed another person. Nobody but the speaker may appear anywhere.",
    ),
    (
        "readable_text",
        True,
        "readable text in the background",
        "Important: the last attempt showed text. There must be no signs, lettering, logos or numbers anywhere.",
    ),
    (
        "same_person",
        False,
        "the speaker no longer looks like the same person",
        "Important: the speaker's face, hair, glasses and clothes must be identical to the source video.",
    ),
    (
        "face_problem",
        True,
        "the face or hands look wrong",
        "Important: the face and hands must look natural and exactly as in the source video.",
    ),
)


def judged(answer: dict[str, Any] | None) -> list[Finding]:
    """The looking model's answer as findings. A missing or non-yes/no answer fails: a check
    that was not answered did not pass."""
    answer = answer if isinstance(answer, dict) else {}
    note = " ".join(str(answer.get("notes") or "").split())[:160]
    out = []
    for key, bad, said, fix in _JUDGE_LINES:
        value = answer.get(key)
        if not isinstance(value, bool):
            out.append(Finding(key, False, "the look at the result gave no answer"))
        elif value == bad:
            out.append(Finding(key, False, said + (f" ({note})" if note else ""), fix))
        else:
            out.append(Finding(key, True, "ok"))
    return out
