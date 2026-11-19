"""Acoustic cleanup for the first preview, on the original recording's clock."""

from __future__ import annotations

from typing import Any

from tce.production.tightcut import HOP_S


def cleanup(
    words: list[dict[str, Any]],
    levels: list[float],
    voice: list[float],
    laughs: list[list[float]],
) -> dict[str, Any]:
    """Find long, wordless gaps with evidence in the full and speech bands.

    Only the interior of a gap is eligible. A brief speech-band peak or a protected
    laugh vetoes the trim. Persistent low-frequency noise in multiple gaps is the
    evidence for light denoising; a single transient never changes the whole mix.
    """
    result: dict[str, Any] = {"trim": [], "denoise": None}
    n = min(len(levels), len(voice))
    if not n or len(words) < 2:
        return result
    spans = sorted(
        (float(w["start_s"]), float(w["end_s"]))
        for w in words
        if w.get("start_s") is not None and w.get("end_s") is not None
    )
    if len(spans) < 2:
        return result

    # Measure speech on the same microphone. Long, stretched ASR words otherwise
    # contribute mostly silence, so sample only short words with complete timestamps.
    sample = [
        x
        for a, b in spans
        if 0.06 <= b - a <= 1.0
        for x in voice[max(0, round(a / HOP_S)) : min(n, round(b / HOP_S)) : 5]
    ]
    if len(sample) < 12:
        return result
    sample.sort()
    speech = sample[int(0.75 * (len(sample) - 1))]
    if speech < -60:
        return result

    windy_gaps = 0
    wind_seconds = 0.0
    prev_end = spans[0][1]
    for start, end in spans[1:]:
        left, right = prev_end + 0.16, start - 0.16
        prev_end = max(prev_end, end)
        if right - left < 0.9 or right > n * HOP_S:
            continue
        if any(a < right and b > left for a, b, *_ in laughs):
            continue
        i, j = round(left / HOP_S), round(right / HOP_S)
        middle = voice[i:j]
        if not middle or max(middle) > speech - 16:
            continue
        wide = sorted(levels[i:j])
        quiet = wide[int(0.90 * (len(wide) - 1))] < -45
        wind = (
            sum(1 for full, band in zip(levels[i:j], middle) if full > -36 and full - band >= 14)
            / len(middle)
            >= 0.65
        )
        if quiet or wind:
            result["trim"].append([round(left, 3), round(right, 3)])
        if wind:
            windy_gaps += 1
            wind_seconds += right - left
    if windy_gaps >= 2 and wind_seconds >= 2.5:
        result["denoise"] = "light"
    return result
