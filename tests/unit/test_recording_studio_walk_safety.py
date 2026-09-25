"""The walk that looked lost and the camera that went black, on a phone. Synthetic data.

24-Sep: "just did a walking trip. 1 video of over 4 minutes were not saved" and
"a few times today the video turned black on the web app and I had to re run it".
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import PHONE, studio  # noqa: F401 - fixture

pytest.importorskip("playwright.sync_api")

# Android's camera: landscape, so it goes through the 9:16 canvas like his phone.
# Every camera opened is kept on window.__raw so the test can switch it off the
# way the phone does (the track ends and says so).
LANDSCAPE_CAMERA = """
window.__raw = [];
const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (constraints) => {
  const stream = await real(constraints);
  stream.getVideoTracks().forEach((t) => t.stop());
  const canvas = document.createElement('canvas');
  canvas.width = 1280; canvas.height = 720;
  const ctx = canvas.getContext('2d');
  const paint = () => { ctx.fillStyle = '#246'; ctx.fillRect(0, 0, 1280, 720); requestAnimationFrame(paint); };
  paint();
  const made = canvas.captureStream(30);
  stream.getAudioTracks().forEach((t) => made.addTrack(t));
  window.__raw.push(made);
  return made;
};
window.__killCamera = () => {
  const track = window.__raw[window.__raw.length - 1].getVideoTracks()[0];
  track.stop();
  track.dispatchEvent(new Event('ended'));
};
"""

# A slow last upload: every clip's closing call waits, like the end of a long
# clip on a phone signal during a walk.
SLOW_CLIP_FINISH = """
const realFetch = window.fetch.bind(window);
window.__slowFinish = 0;
window.fetch = async (url, options) => {
  if (window.__slowFinish && /recording-clips\\/[^/]+\\/finish/.test(String(url))) {
    await new Promise((r) => setTimeout(r, window.__slowFinish));
  }
  return realFetch(url, options);
};
"""


def _studio_page(pw, base, *scripts):
    browser = pw.chromium.launch(
        headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
    )
    context = browser.new_context(
        viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
        permissions=["camera", "microphone"],
    )
    page = context.new_page()
    for script in scripts:
        page.add_init_script(script)
    page.goto(f"{base}/record")
    page.wait_for_selector(".idea-card")
    page.click(".idea-card")
    page.locator("#hookView .hook-option").first.locator(".hook-use").click()
    page.wait_for_selector("#studioView:not([hidden])")
    # The camera ladder tries several modes first; wait for the one it kept.
    page.wait_for_function(
        "() => document.getElementById('camera').srcObject && document.getElementById('cameraEmpty').hidden",
        timeout=30000,
    )
    return browser, context, page


def _record(page, seconds):
    page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=60000)
    page.click("#recordButton")
    page.wait_for_function(
        "() => document.getElementById('studioView').classList.contains('is-recording')", timeout=30000
    )
    page.wait_for_timeout(int(seconds * 1000))


def test_finish_right_after_stop_keeps_the_clip_that_was_still_uploading(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, SLOW_CLIP_FINISH)
        # A false start, stopped and saved: the 3-second clip of the morning.
        _record(page, 2)
        with page.expect_response(lambda r: "/finish" in r.url and "recording-clips" in r.url, timeout=60000):
            page.click("#finishClipButton")
        # The real take, whose end is still on its way when Finish is pressed.
        _record(page, 4)
        page.evaluate("() => { window.__slowFinish = 4000; }")
        with page.expect_request(
            lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"), timeout=90000
        ) as finished:
            page.evaluate(
                "() => { document.getElementById('finishClipButton').click();"
                " setTimeout(() => document.getElementById('finishSessionButton').click(), 300); }"
            )
        chosen = finished.value.post_data_json["selected_clip_ids"]
        assert len(chosen) == 2, f"the video was built without the clip still uploading: {chosen}"
        context.close()
        browser.close()


def test_a_camera_the_phone_switches_off_comes_back_by_itself(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        # Idle in the studio: the phone takes the camera away.
        before = page.evaluate("() => window.__raw.length")
        page.evaluate("() => window.__killCamera()")
        page.wait_for_function(
            f"() => window.__raw.length > {before} && window.__raw.at(-1).getVideoTracks()[0].readyState === 'live'",
            timeout=30000,
        )
        # While recording: what was recorded is kept as a clip, and the camera returns.
        _record(page, 3)
        opened = page.evaluate("() => window.__raw.length")
        with page.expect_response(
            lambda r: "recording-clips" in r.url and r.url.endswith("/finish"), timeout=60000
        ) as kept:
            page.evaluate("() => window.__killCamera()")
        assert kept.value.status == 200, "the part recorded before the camera died was not kept"
        page.wait_for_function(
            f"() => window.__raw.length > {opened} && window.__raw.at(-1).getVideoTracks()[0].readyState === 'live'",
            timeout=30000,
        )
        # What he SEES: the preview itself is showing a live camera again.
        page.wait_for_function(
            "() => document.getElementById('camera').srcObject.getVideoTracks()[0].readyState === 'live'",
            timeout=30000,
        )
        # And Record goes on from here, on that same camera, with no second one opened.
        count = page.evaluate("() => window.__raw.length")
        _record(page, 2)
        assert page.evaluate("() => window.__raw.length") == count, "Record opened another camera"
        context.close()
        browser.close()


# The phone's side of a failure: the clip's closing call fails once (a bad signal),
# or the recorder hands over no data at all (a quick Record-then-Stop).
FLAKY_FINISH = r"""
const realFetch2 = window.fetch.bind(window);
window.__failFinish = 0;
window.__finishCalls = 0;
window.fetch = async (url, options) => {
  if (/recording-clips\/[^/]+\/finish/.test(String(url))) {
    window.__finishCalls += 1;
    if (window.__failFinish > 0) {
      window.__failFinish -= 1;
      return new Response(JSON.stringify({detail: "network dropped"}), {status: 503});
    }
  }
  return realFetch2(url, options);
};
const desc = Object.getOwnPropertyDescriptor(MediaRecorder.prototype, "ondataavailable");
Object.defineProperty(MediaRecorder.prototype, "ondataavailable", {
  configurable: true,
  get() { return desc.get.call(this); },
  set(fn) { desc.set.call(this, (e) => { if (!window.__noData) fn(e); }); },
});
"""


def test_a_stop_whose_finish_fails_gives_record_back_and_finish_retries_it(studio):  # noqa: F811
    """24-25 Sep: after a failed clip finish, Record stayed greyed out forever - the
    studio was stuck until a reload ("I am stuck", 23-Sep)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, FLAKY_FINISH)
        _record(page, 4)
        page.evaluate("() => { window.__failFinish = 1; }")
        page.click("#finishClipButton")
        page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=15000)
        assert page.evaluate("() => window.__finishCalls") == 1
        # Finish sends the clip that failed before it builds the video, and includes it.
        with page.expect_request(
            lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"), timeout=60000
        ) as finished:
            page.click("#finishSessionButton")
        assert page.evaluate("() => window.__finishCalls") == 2
        assert len(finished.value.post_data_json["selected_clip_ids"]) == 1
        context.close()
        browser.close()


def test_a_take_with_no_video_data_is_dropped_and_record_comes_back(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, FLAKY_FINISH)
        page.evaluate("() => { window.__noData = true; }")
        _record(page, 1)
        page.click("#finishClipButton")
        page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=15000)
        assert page.evaluate("() => window.__finishCalls") == 0, "an empty take was sent to the server"
        notice = page.evaluate("() => (document.getElementById('notice') || {}).textContent || ''")
        assert "too short" in notice, notice
        context.close()
        browser.close()
