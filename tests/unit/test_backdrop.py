"""New backgrounds for a walking video: the scene plan, the checks (each with a planted-bad
case it must fail on), the model client's handling of the key, and the whole step run against
a fake model on a synthetic cut where every frame carries its own number."""

from __future__ import annotations

import array
import json
import random
import shutil
import subprocess
import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tce.production.backdrop import checks, clips, looks, omni, scenes, step

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# ------------------------------------------------------------------ the plan
def _cut(lengths: list[float], last_words: list[str]):
    keep, words, t = [], [], 0.0
    for n, (d, word) in enumerate(zip(lengths, last_words, strict=True)):
        keep.append([100.0 + n * 50, 100.0 + n * 50 + d])  # far apart on the recording
        words.append({"text": "so", "start": t + 0.1, "end": t + 0.4})
        words.append({"text": word, "start": t + d - 0.5, "end": t + d - 0.1})
        t += d
    return keep, words


def test_scenes_end_on_a_sentence_and_alternate():
    keep, words = _cut(
        [2.5, 2.5, 3.0, 2.0, 2.5, 2.5, 5.0],
        ["and", "home.", "then", "right?", "but", "ok!", "bye."],
    )
    got = scenes.plan_scenes(keep, words, ["a", "b", "c"])
    assert [s.keeps for s in got] == [[0, 1], [2, 3], [4, 5], [6]]
    assert [s.swap for s in got] == [False, True, False, True]  # the opening stays real
    assert [s.look for s in got if s.swap] == ["a", "b"]
    assert got[0].reason == "opening"


def test_no_scene_passes_the_model_limit_even_without_a_sentence_end():
    keep, words = _cut([6.0] * 6, ["and"] * 6)
    got = scenes.group_scenes(keep, words)
    assert all(s.length_s <= scenes.MAX_SCENE_S for s in got)
    assert sum(len(s.keeps) for s in got) == 6


def test_a_scene_under_a_card_is_left_alone_and_does_not_break_the_rhythm():
    keep, words = _cut([5.0] * 5, ["a.", "b.", "c.", "d.", "e."])
    got = scenes.plan_scenes(keep, words, ["x", "y", "z"], hidden=[(5.0, 9.0)])
    assert [s.swap for s in got] == [False, False, True, False, True]
    assert got[1].reason == "mostly under a card"


def test_a_look_is_never_used_twice_in_one_video():
    keep, words = _cut([5.0] * 9, [f"w{n}." for n in range(9)])
    got = scenes.plan_scenes(keep, words, ["x", "y"])
    used = [s.look for s in got if s.swap]
    assert used == ["x", "y"]
    assert [s.reason for s in got if not s.swap and "no look left" in s.reason]


def test_start_look_moves_which_place_comes_first():
    keep, words = _cut([5.0] * 4, ["a.", "b.", "c.", "d."])
    got = scenes.plan_scenes(keep, words, ["x", "y", "z"], start_look=2)
    assert [s.look for s in got if s.swap] == ["z", "x"]


# ---------------------------------------------------------------- the checks
def test_length_check_allows_a_few_extra_frames_and_refuses_a_short_or_long_result():
    assert checks.length(6.0, 6.1).ok
    assert checks.length(6.0, 6.4).ok  # the extra tail is cut off
    assert checks.length(6.0, 5.85).ok  # the last frame is held for a moment
    assert not checks.length(6.0, 6.6).ok
    assert not checks.length(6.0, 5.7).ok
    assert not checks.length(6.0, 5.0).ok


def _speech(seed: int, n: int = 3000):
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(seed)
    return np.repeat(rng.random(n // 25), 25).astype("float32")  # 50 ms syllables at 500 Hz


def test_timing_passes_on_the_same_speech_a_little_late():
    np = pytest.importorskip("numpy")
    real = _speech(1)
    late = np.concatenate([np.full(20, real[0]), real])[: len(real)]  # 40 ms late
    found = checks.timing(real, late)
    assert found.ok, found.detail
    assert "+40 ms" in found.detail


def test_timing_fails_on_speech_150_ms_late():
    np = pytest.importorskip("numpy")
    real = _speech(1)
    late = np.concatenate([np.full(75, real[0]), real])[: len(real)]
    found = checks.timing(real, late)
    assert not found.ok
    assert "+150 ms" in found.detail


def test_timing_fails_on_other_speech():
    found = checks.timing(_speech(1), _speech(2))
    assert not found.ok
    assert "does not match" in found.detail


def test_timing_fails_when_the_speech_wanders():
    np = pytest.importorskip("numpy")
    real = _speech(3)
    half = len(real) // 2
    slow = np.concatenate([real[:half], np.full(50, real[half]), real[half:]])[: len(real)]
    found = checks.timing(real, slow)  # second half 100 ms later than the first
    assert not found.ok


def test_face_check():
    here = (0.5, 0.6, 0.3)
    assert checks.faces([here, here], [here, (0.52, 0.61, 0.31)]).ok
    moved = checks.faces([here], [(0.72, 0.6, 0.3)])
    assert not moved.ok and moved.fix
    assert not checks.faces([here], [(0.5, 0.6, 0.45)]).ok  # the head grew by half
    gone = checks.faces([here, here], [here, None])
    assert not gone.ok and "no face in 1 of 2" in gone.detail
    assert checks.faces([None], [None]).ok  # nothing to compare is not a failure of the scene


def test_background_check_fails_when_one_still_kept_the_old_place():
    assert checks.replaced([0.5, 0.4, 0.62]).ok
    bad = checks.replaced([0.5, 0.03, 0.62])
    assert not bad.ok and "3% of the background" in bad.detail and "very first frame" in bad.fix
    assert checks.replaced([None, 0.5]).ok  # a still where the head fills the frame says nothing
    assert checks.replaced([None, None]).ok and "too little" in checks.replaced([None]).detail
    assert not checks.replaced([None, 0.0]).ok


def test_background_change_measures_what_is_beside_the_head():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(3)
    scene = cv2.resize(
        rng.integers(0, 255, (24, 14), dtype=np.uint8), (540, 960), interpolation=cv2.INTER_NEAREST
    )
    other = cv2.resize(
        rng.integers(0, 255, (24, 14), dtype=np.uint8), (540, 960), interpolation=cv2.INTER_NEAREST
    )
    body = scene.copy()
    body[400:, :] = 90  # the speaker fills everything from the chin down, in both
    moved = other.copy()
    moved[400:, :] = 90
    jpg = lambda img: cv2.imencode(".jpg", img)[1].tobytes()  # noqa: E731
    face = (0.5, 0.6, 0.3)
    same, new = checks.background_change(
        [jpg(body), jpg(body)], [jpg(body), jpg(moved)], [face, face]
    )
    assert same < 0.02 and new > 0.4
    close = (0.5, 0.9, 1.4)  # the head fills the frame: nothing to compare
    assert checks.background_change([jpg(body)], [jpg(moved)], [close]) == [None]


GOOD = {
    "vehicles": False,
    "other_people": False,
    "readable_text": False,
    "same_person": True,
    "face_problem": False,
    "notes": "",
}


def test_the_look_fails_on_a_car_and_says_what_to_fix():
    assert all(f.ok for f in checks.judged(GOOD))
    found = checks.judged({**GOOD, "vehicles": True, "notes": "a parked car at the left edge"})
    bad = [f for f in found if not f.ok]
    assert [f.name for f in bad] == ["vehicles"]
    assert "parked car" in bad[0].detail and "no cars" in bad[0].fix
    assert [f.name for f in checks.judged({**GOOD, "same_person": False}) if not f.ok] == [
        "same_person"
    ]


def test_a_look_that_did_not_answer_is_not_a_pass():
    assert not any(f.ok for f in checks.judged(None))
    assert [f.name for f in checks.judged({**GOOD, "readable_text": "maybe"}) if not f.ok] == [
        "readable_text"
    ]
    missing = dict(GOOD)
    del missing["other_people"]
    assert [f.name for f in checks.judged(missing) if not f.ok] == ["other_people"]


# ----------------------------------------------------------------- the looks
def _look_set(folder: Path, **extra) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "roof.png").write_bytes(b"roof")
    (folder / "pines.png").write_bytes(b"pines")
    (folder / looks.FILE).write_text(
        json.dumps(
            {
                "speaker": "short dark hair, a beard",
                "looks": [
                    {
                        "id": "lane",
                        "name": "Lane",
                        "place": "They are now walking down a lane.",
                        "refs": ["roof.png", "gone.png"],
                    },
                    {
                        "id": "pines",
                        "place": "They are now walking under pines.",
                        "refs": ["pines.png", "../../etc/passwd"],
                    },
                    {"id": "empty", "place": ""},
                    {"id": "lane", "place": "A second lane."},
                ],
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return folder


def test_look_set_loads_what_is_usable(tmp_path):
    found = looks.load(_look_set(tmp_path / "set"))
    assert found is not None
    assert found.ids == ["lane", "pines"]  # no paragraph, or a repeated id: left out
    assert [r.name for r in found.get("lane").refs] == ["roof.png"]  # the missing still is dropped
    assert [r.name for r in found.get("pines").refs] == [
        "pines.png"
    ]  # never a path outside the set
    assert looks.load(tmp_path / "nothing") is None
    assert looks.load(None) is None


def test_prompt_names_the_speaker_and_the_fix_and_the_fingerprint_follows_the_stills(tmp_path):
    found = looks.load(_look_set(tmp_path / "set"))
    lane = found.get("lane")
    text = looks.prompt(lane, found.speaker, "Important: no cars.")
    assert "face, short dark hair, a beard, expression" in text
    assert "They are now walking down a lane." in text
    assert text.endswith("Important: no cars.")
    before = looks.fingerprint(lane, found.speaker)
    (tmp_path / "set" / "roof.png").write_bytes(b"another roof")
    assert looks.fingerprint(looks.load(tmp_path / "set").get("lane"), found.speaker) != before


# ----------------------------------------------------------------- the model
def test_cost_is_counted_from_the_tokens_the_answer_reports():
    usage = {"total_input_tokens": 30513, "total_output_tokens": 40545, "total_thought_tokens": 750}
    assert omni.cost_usd(usage) == pytest.approx(0.5413, abs=1e-4)  # the 4.7 s scene of 18-Nov
    assert omni.cost_usd(None) == 0.0
    assert omni.estimate_usd(10, "1080p") == pytest.approx(1.14)


class _Answer:
    def __init__(self, body: bytes = b"{}", headers: dict | None = None):
        self._body, self.headers = body, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_key_goes_in_a_header_to_googles_host_only(tmp_path, monkeypatch):
    seen = []

    def fake(req, timeout=None):
        seen.append(req)
        if req.full_url.endswith("/upload/v1beta/files"):
            return _Answer(headers={"X-Goog-Upload-URL": "https://upload.example/session/1"})
        return _Answer(
            json.dumps(
                {"file": {"state": "ACTIVE", "uri": "https://g/files/abc", "name": "files/abc"}}
            ).encode()
        )

    monkeypatch.setattr(omni.urllib.request, "urlopen", fake)
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x" * 10)
    api = omni.Api("SECRET-KEY")
    assert api.upload(clip, "video/mp4") == "https://g/files/abc"
    start, finish = seen
    assert start.get_header("X-goog-api-key") == "SECRET-KEY"
    assert finish.get_header("X-goog-api-key") is None  # the upload address is not the API host
    assert all("SECRET-KEY" not in r.full_url for r in seen)
    with pytest.raises(omni.OmniError, match="another host"):
        api._call("x", "GET", "https://elsewhere.example/v1beta/files/abc")


def test_no_key_is_an_error_before_any_call():
    with pytest.raises(omni.OmniError):
        omni.Api("")


def test_an_http_error_never_carries_the_key(monkeypatch):
    import urllib.error
    from io import BytesIO

    def fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many", {}, BytesIO(b'{"error":"quota"}')
        )

    monkeypatch.setattr(omni.urllib.request, "urlopen", fake)
    with pytest.raises(omni.OmniError) as caught:
        omni.Api("SECRET-KEY").look("m", [b"jpg"], "p")
    assert "429" in str(caught.value) and "SECRET-KEY" not in str(caught.value)


# ------------------------------------------------------------ the whole step
FPS, W, H, SHOT_S, SHOTS = 30, 90, 160, 2.5, 8  # 20 s, 600 frames; frame N is one flat gray


def _code(n: int) -> int:
    return 40 + (n * 7) % 160


def _levels(path: Path) -> list[tuple[int, int]]:
    """(top half, bottom half) brightness of every frame."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=2:2:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return [
        ((raw[i] + raw[i + 1]) // 2, (raw[i + 2] + raw[i + 3]) // 2) for i in range(0, len(raw), 4)
    ]


@pytest.fixture
def cut(tmp_path, monkeypatch):
    """A work folder as the engine's cut stage leaves it.

    The frames sit a little early on the clock, more so toward the end (16 ms by the last
    frame), like a real cut joined from many short pieces: on 19-Nov a real cut was 14 ms
    early by its end, cutting it by time landed one frame late, and every scene after the
    middle came back shifted by a frame. Frames are addressed by number, never by n / 30."""
    pytest.importorskip("numpy")
    if not HAS_FFMPEG:
        pytest.skip("needs ffmpeg")
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=gray:s={W}x{H}:r={FPS}:d={SHOT_S * SHOTS},format=yuv420p,geq=lum='40+mod(N*7,160)':cb=128:cr=128",
            "-vf",
            "setpts=PTS*0.9992",
            "-fps_mode",
            "passthrough",
            "-video_track_timescale",
            "16000",
            "-c:v",
            "libx264",
            "-crf",
            "12",
            "-preset",
            "veryfast",
            "-bf",
            "0",
            "-g",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(work / "base.mp4"),
        ],
        check=True,
    )
    rng = random.Random(7)
    samples = array.array("h")
    for _ in range(int(SHOT_S * SHOTS * 20)):  # 50 ms syllables
        level = rng.choice([0, 0, 3000, 9000, 20000])
        samples.extend(int(rng.uniform(-level, level)) for _ in range(2400))
    with wave.open(str(work / "voice.wav"), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframes(samples.tobytes())
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"the recording")
    shots = [
        {
            "src_in": 10.0 * i,
            "src_out": 10.0 * i + SHOT_S,
            "crop": [0, 0, W, H],
            "scale": 1.0,
            "words": [
                {"text": "word", "start_s": 10.0 * i + 0.2, "end_s": 10.0 * i + 0.6},
                {"text": "end.", "start_s": 10.0 * i + 1.8, "end_s": 10.0 * i + 2.3},
            ],
        }
        for i in range(SHOTS)
    ]
    plan = {
        "work": str(work),
        "source": str(src),
        "grade": "none",
        "words": str(work / "words.json"),
    }
    edit = {"fps": FPS, "shots": shots}
    monkeypatch.setattr(step, "engine_view", lambda plan_path, engine_dir: (plan, edit, []))
    monkeypatch.setattr(checks, "detect_faces", lambda jpegs, model: [(0.5, 0.6, 0.3)] * len(jpegs))
    monkeypatch.setattr(checks, "background_change", lambda real, new, faces: [0.6] * len(real))
    cfg = {
        "looks_dir": str(_look_set(tmp_path / "set")),
        "cache_dir": str(tmp_path / "cache"),
        "engine_dir": str(tmp_path),
        "model": "omni-test",
        "judge_model": "flash-test",
        "resolution": "1080p",
        "max_usd": 8.0,
        "ledger": str(tmp_path / "spend.jsonl"),
        "label": "test",
    }
    return work, cfg


class FakeModel:
    """Stands in for the paid model: 'redraws' a scene by painting its top half white, at the
    model's own 24 fps, and keeps the sound."""

    def __init__(
        self, *, cut_s: float = 0.0, answers: list[dict] | None = None, fail_edit: int = 0
    ):
        self.cut_s, self.answers, self.fail_edit = cut_s, list(answers or []), fail_edit
        self.edits: list[dict] = []
        self.looked = 0

    def upload(self, path, mime=None):
        return str(path)

    def edit(self, video_uri, ref_uris, prompt, *, model, resolution, out):
        self.edits.append(
            {"prompt": prompt, "refs": [Path(r).name for r in ref_uris], "model": model}
        )
        if len(self.edits) <= self.fail_edit:
            raise omni.OmniError("edit: HTTP 503")
        seconds = clips.info(video_uri)["seconds"] - self.cut_s
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                video_uri,
                "-t",
                f"{seconds:.3f}",
                "-vf",
                "drawbox=x=0:y=0:w=iw:h=ih/2:color=white:t=fill,fps=24",
                "-c:v",
                "libx264",
                "-crf",
                "14",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ],
            check=True,
        )
        return {"total_input_tokens": 30000, "total_output_tokens": 40000}

    def look(self, model, images, prompt):
        self.looked += 1
        return self.answers.pop(0) if self.answers else dict(GOOD)


def test_the_step_changes_every_other_scene_and_not_one_frame_more(cut):
    work, cfg = cut
    model, said = FakeModel(), []
    report = step.run(work / "plan.json", cfg, api=model, say=said.append)
    assert report["asked"] == 2 and report["changed"] == 2 and report["note"] == ""
    assert [e["result"] for e in report["scenes"]] == ["real", "new", "real", "new"]
    assert [e["look"] for e in report["scenes"] if e["result"] == "new"] == ["lane", "pines"]
    assert (
        model.edits[0]["refs"] == ["roof.png"] and "walking down a lane" in model.edits[0]["prompt"]
    )
    after, before = _levels(work / "base.mp4"), _levels(work / "base.real.mp4")
    assert len(after) == len(before) == 600
    for n in (0, 1, 148, 149, 300, 301, 448, 449):  # real scenes, at their very edges too
        assert abs(after[n][0] - before[n][0]) <= 3 and abs(after[n][1] - before[n][1]) <= 3, n
    for n in (150, 151, 225, 298, 299, 450, 520, 598, 599):  # changed scenes, edges too
        assert after[n][0] > 215, n  # the fake model's white top half
        assert abs(after[n][1] - before[n][1]) <= 12, (
            n
        )  # the rest still follows the scene's own frames
    assert report["cost_usd"] == pytest.approx(2 * (0.525 + omni.LOOK_USD), abs=1e-3)
    assert said[0] == "backdrop: 4 scenes, 2 to change" and said[-1].startswith(
        "backdrop: joined 2/2, $"
    )
    spent = [json.loads(line) for line in Path(cfg["ledger"]).read_text().splitlines()]
    assert len(spent) == 1 and spent[0]["changed"] == 2 and spent[0]["drawn_s"] == 10.0
    assert json.loads((work / step.REPORT).read_text(encoding="utf-8"))["changed"] == 2


def test_a_second_render_of_the_same_cut_is_not_paid_for_again(cut):
    work, cfg = cut
    step.run(work / "plan.json", cfg, api=FakeModel())
    shutil.copy(
        work / "base.real.mp4", work / "base.mp4"
    )  # the cut stage runs again on a re-render
    again = FakeModel()
    report = step.run(work / "plan.json", cfg, api=again)
    assert report["changed"] == 2 and report["cost_usd"] == 0.0 and again.edits == []
    assert all(e["cached"] for e in report["scenes"] if e["result"] == "new")
    assert _levels(work / "base.mp4")[200][0] > 215


def test_a_result_that_is_a_second_short_is_refused_twice_and_the_scene_stays_real(cut):
    work, cfg = cut
    model, said = FakeModel(cut_s=1.0), []
    report = step.run(work / "plan.json", cfg, api=model, say=said.append)
    assert report["changed"] == 0 and report["asked"] == 2
    assert len(model.edits) == 4 and model.looked == 0  # two tries a scene, never looked at
    assert all(e["result"] == "real" for e in report["scenes"])
    assert "result 4.0" in report["scenes"][1]["why"]
    assert not (work / "base.real.mp4").exists()  # the cut's picture was never touched
    assert _levels(work / "base.mp4")[200][0] < 215
    assert any("retry" in line for line in said) and any("kept real" in line for line in said)
    assert report["cost_usd"] > 2.0  # refused results are still paid for, and still counted


def test_a_scene_refused_twice_is_not_paid_for_a_third_time(cut):
    work, cfg = cut
    first = step.run(work / "plan.json", cfg, api=FakeModel(cut_s=1.0))
    assert first["changed"] == 0 and first["cost_usd"] > 2.0
    again = FakeModel()  # this one would pass, but the same scenes are not sent again
    report = step.run(work / "plan.json", cfg, api=again)
    assert again.edits == [] and report["cost_usd"] == 0.0 and report["changed"] == 0
    assert report["scenes"][1]["why"].startswith(
        "refused on an earlier render: scene 5.00 s, result 4.0"
    )
    other = _look_set(Path(cfg["looks_dir"]))  # the look's stills change: a new try is fair
    (other / "roof.png").write_bytes(b"a different roof")
    (other / "pines.png").write_bytes(b"different pines")
    report = step.run(work / "plan.json", cfg, api=again)
    assert len(again.edits) == 2 and report["changed"] == 2


def test_a_model_that_did_not_answer_is_asked_again_on_the_next_render(cut):
    work, cfg = cut
    step.run(work / "plan.json", cfg, api=FakeModel(fail_edit=2))  # scene 2 never got an answer
    again = FakeModel()
    report = step.run(work / "plan.json", cfg, api=again)
    assert (
        len(again.edits) == 1 and report["changed"] == 2
    )  # scene 2 is drawn now, scene 4 was saved


def test_a_result_that_opens_on_the_old_background_is_drawn_again(cut, monkeypatch):
    work, cfg = cut
    answers = [[0.02, 0.6, 0.6, 0.6, 0.6]]
    monkeypatch.setattr(
        checks,
        "background_change",
        lambda real, new, faces: answers.pop(0) if answers else [0.6] * 5,
    )
    model = FakeModel()
    report = step.run(work / "plan.json", cfg, api=model)
    assert report["changed"] == 2 and len(model.edits) == 3 and model.looked == 2
    assert "from the very first frame" in model.edits[1]["prompt"]
    first = report["scenes"][1]["attempts"][0]["checks"]
    assert [c["name"] for c in first if not c["ok"]] == ["background"]


def test_a_car_in_the_result_is_drawn_again_with_the_fix_in_the_instructions(cut):
    work, cfg = cut
    model = FakeModel(answers=[{**GOOD, "vehicles": True, "notes": "a parked car"}])
    report = step.run(work / "plan.json", cfg, api=model)
    assert report["changed"] == 2 and len(model.edits) == 3
    assert "no cars or vehicles of any kind" not in model.edits[0]["prompt"]
    assert "no cars or vehicles of any kind" in model.edits[1]["prompt"]
    first = report["scenes"][1]["attempts"]
    assert [c["name"] for c in first[0]["checks"] if not c["ok"]] == ["vehicles"]
    assert all(c["ok"] for c in first[1]["checks"])


def test_the_spend_limit_stops_before_the_call_that_would_pass_it(cut):
    work, cfg = cut
    model = FakeModel()
    report = step.run(work / "plan.json", {**cfg, "max_usd": 0.9}, api=model)
    assert len(model.edits) == 1 and report["changed"] == 1
    assert "spend limit" in report["scenes"][3]["why"]


def test_a_model_that_does_not_answer_leaves_the_real_scene(cut):
    work, cfg = cut
    model = FakeModel(fail_edit=2)
    report = step.run(work / "plan.json", cfg, api=model)
    assert report["scenes"][1]["result"] == "real" and "503" in report["scenes"][1]["why"]
    assert report["scenes"][3]["result"] == "new"


def test_no_look_set_means_nothing_happens(cut):
    work, cfg = cut
    model = FakeModel()
    report = step.run(work / "plan.json", {**cfg, "looks_dir": str(work / "none")}, api=model)
    assert report["note"] == "there is no set of looks for this workspace"
    assert model.edits == [] and not (work / "base.real.mp4").exists()


def test_the_days_limit_counts_every_video_and_forgets_yesterday(cut):
    work, cfg = cut
    now = datetime.now(UTC).isoformat(timespec="seconds")
    old = json.dumps({"at": "2026-01-01T00:00:00+00:00", "cost_usd": 100.0})
    today = json.dumps({"at": now, "cost_usd": 24.6})
    Path(cfg["ledger"]).write_text("\n".join([old, today, "not json", ""]))
    assert step.spent_since(cfg["ledger"]) == pytest.approx(24.6)
    model = FakeModel()
    report = step.run(work / "plan.json", {**cfg, "day_usd": 25.0}, api=model)
    assert model.edits == [] and report["changed"] == 0  # 40 cents left: not enough for one scene
    assert "spend limit" in report["scenes"][1]["why"]
    Path(cfg["ledger"]).write_text(json.dumps({"at": now, "cost_usd": 25.5}))
    report = step.run(work / "plan.json", {**cfg, "day_usd": 25.0}, api=model)
    assert (
        report["note"] == "the spend limit for one day ($25.00) was reached" and model.edits == []
    )
    assert [e["result"] for e in report["scenes"]] == ["real"] * 4
