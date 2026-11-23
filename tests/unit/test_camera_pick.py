"""The camera opens on the rung of the ladder it took last time (23-Nov, wait-less item F12).

Each page's own openCamera and ladder (the studio, Record without a script, the Book) runs
in node against a simulated phone: what each open asked the phone for, in order. The first
open walks the ladder as before; the next one asks once. A different camera, a different
size, a changed ladder, a new browser, no camera id, or no storage (private browsing) walks
the whole ladder again, and the phone never holds two cameras open. Synthetic devices only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
NODE = shutil.which("node")
PAGES = ["recording.js", "recording-solo.js", "book.js"]


def _block(js: str, start: str) -> str:
    """`start` through the brace that closes the block it opens."""
    i = js.index(start)
    depth = 0
    for k in range(js.index("{", i), len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i : k + 1]
    raise AssertionError(f"{start} never closes")


def _camera_code(name: str) -> str:
    js = (API / name).read_text(encoding="utf-8")
    full_hd = next(line.strip() for line in js.splitlines() if line.strip().startswith("const FULL_HD_4_3 = "))
    ladder = "const CAMERA_ATTEMPTS = [" + js.split("const CAMERA_ATTEMPTS = [", 1)[1].split("];", 1)[0] + "];"
    opener = "async function openCamera("
    helper = js[js.index("const CAMERA_PICK") : js.index(opener)] if "const CAMERA_PICK" in js else ""
    return "\n".join([full_hd, ladder, helper, _block(js, opener)])


HARNESS = r"""
function phone(opts) {
  // His phone: the exact portrait asks are refused, the 4:3 full-HD ask comes back as a
  // portrait 1440x1920. opts.landscape: every ask that opens comes back 1920x1080.
  const p = { camera: "front-1", ua: "Phone browser 1", landscape: false, tall: 1920, live: [], asks: [], busy: 0, ...opts };
  p.getUserMedia = async (constraints) => {
    const { facingMode, ...video } = constraints.video || {};
    p.asks.push(JSON.stringify(video));
    if (p.live.some((t) => t.readyState === "live")) { p.busy += 1; throw Object.assign(new Error("busy"), { name: "NotReadableError" }); }
    const exact = Object.values(video).some((v) => v && typeof v === "object" && "exact" in v);
    if (exact) throw Object.assign(new Error("no such mode"), { name: "OverconstrainedError" });
    const [w, h] = p.landscape ? [1920, 1080] : [p.tall * 3 / 4, p.tall];
    const track = { readyState: "live", stop() { this.readyState = "ended"; },
      getSettings: () => (p.camera ? { deviceId: p.camera } : {}) };
    p.live.push(track);
    return { __w: w, __h: h, getTracks: () => [track], getVideoTracks: () => [track], getAudioTracks: () => [] };
  };
  return p;
}
function storage(privateTab) {
  const m = new Map();
  const no = () => { throw Object.assign(new Error("denied"), { name: "SecurityError" }); };
  return privateTab ? { getItem: no, setItem: no, removeItem: no }
    : { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
}
function page(p, localStorage, change) {
  const navigator = { userAgent: p.ua, mediaDevices: { getUserMedia: p.getUserMedia } };
  const measure = async (stream) => ({ stream, element: {}, width: stream.__w, height: stream.__h });
  const state = {};
  const describe = (o) => o;
  const portraitStream = (c) => c.stream;
  const portraitVideo = () => [];
  const top = () => {};
  const $ = () => ({ play: async () => {}, hidden: false, disabled: false });
  CODE
  if (change) change(CAMERA_ATTEMPTS);
  return async () => {
    state.stream = null;
    const from = p.asks.length;
    await openCamera();
    p.live.forEach((t) => t.stop());   // the take ends; the next open is a new visit
    return p.asks.slice(from).map((a) => CAMERA_ATTEMPTS.findIndex((x) => JSON.stringify(x) === a));
  };
}
(async () => {
  const out = {};
  const run = async (name, opts, steps) => {
    const p = phone(opts.phone || {});
    const store = storage(Boolean(opts.privateTab));
    const seen = [];
    for (const step of steps) {
      if (step.phone) Object.assign(p, step.phone);
      seen.push(await page(p, store, step.ladder ? (l) => l.unshift({ width: { exact: 2160 }, height: { exact: 3840 } }) : null)());
    }
    out[name] = { asks: seen, busy: p.busy };
  };
  await run("his phone", {}, [{}, {}, {}]);
  await run("another camera", {}, [{}, { phone: { camera: "front-2" } }, {}]);
  await run("another size", {}, [{}, { phone: { tall: 2400 } }, {}]);
  await run("a new browser", {}, [{}, { phone: { ua: "Phone browser 2" } }, {}]);
  await run("a changed ladder", {}, [{}, { ladder: true }]);
  await run("no camera id", { phone: { camera: "" } }, [{}, {}]);
  await run("private tab", { privateTab: true }, [{}, {}]);
  await run("landscape only", { phone: { landscape: true } }, [{}, {}]);
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); });
"""

WALK = [0, 1, 2, 3]  # his phone: three exact asks refused, then the 4:3 full-HD one, portrait


@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("name", PAGES)
def test_the_camera_asks_for_last_times_rung_first_and_walks_the_ladder_when_anything_changed(name):
    script = HARNESS.replace("CODE", _camera_code(name))
    got = json.loads(subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True,
                                    timeout=60).stdout)
    assert "error" not in got, got.get("error")
    assert got["his phone"]["asks"] == [WALK, [3], [3]]
    # Another camera, or the same one at another size: last time's rung is tried, let go, and
    # the whole ladder walked; from then on the new answer is the remembered one.
    assert got["another camera"]["asks"] == [WALK, [3, *WALK], [3]]
    assert got["another size"]["asks"] == [WALK, [3, *WALK], [3]]
    assert got["a new browser"]["asks"] == [WALK, WALK, [3]]
    # A ladder with a new first rung never jumps to the old number: it starts at the new top.
    assert got["a changed ladder"]["asks"] == [WALK, [0, 1, 2, 3, 4]]
    assert got["no camera id"]["asks"] == [WALK, WALK]
    assert got["private tab"]["asks"] == [WALK, WALK]
    # No portrait mode at all: every rung, then the tallest reopened; next time, one ask.
    assert got["landscape only"]["asks"] == [[0, 1, 2, 3, 4, 5, 6, 7, 3], [3]]
    for case in got.values():
        assert case["busy"] == 0, "a camera was asked for while the page still held one open"
