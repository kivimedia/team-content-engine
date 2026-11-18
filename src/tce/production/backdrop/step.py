"""The whole step for one render: plan the scenes, have the chosen ones redrawn, check each,
and put the base picture back together with exactly the frames it had.

It runs between the engine's ``cut`` stage and its ``masks`` stage, so captions, cards, zooms
and music are made on top of the new picture and the real voice is never touched. Whatever
goes wrong here, the base picture is left as the cut made it: the render goes on with the real
backgrounds and the report says why.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import checks, clips, omni
from . import looks as looksmod
from . import scenes as scenesmod

VERSION = 1
REPORT = "backdrop.json"
JUDGE_STILLS = 8
FACE_STILLS = 5
FACE_MODEL = Path("models") / "face_yunet.onnx"


def engine_view(
    plan_path: str | Path, engine_dir: str | Path
) -> tuple[dict, dict, list[tuple[float, float]]]:
    """The engine's own reading of the plan and of its cut, and the stretches of the cut where
    a full-screen card will cover the picture (no point paying for what nobody sees)."""
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
    from creatorz_reel import plan as planmod  # type: ignore[import-not-found]

    plan = planmod.load(str(plan_path))
    edit = json.loads((Path(plan["work"]) / "edit.json").read_text(encoding="utf-8"))
    hidden: list[tuple[float, float]] = []
    try:
        from creatorz_reel import compose_plan  # type: ignore[import-not-found]

        spec = compose_plan.build(plan, edit)
        hidden = [
            (float(a), float(b))
            for item in spec["items"]
            if item.get("layer") == "scene"
            for a, b in item.get("windows") or []
        ]
    except Exception:  # noqa: BLE001 - the cards are an economy, never a reason to stop
        hidden = []
    return plan, edit, hidden


def frame_spans(shots: list[dict], fps: int) -> list[tuple[int, int]]:
    """Where each shot sits in the base picture, in frames, counted the way the cut encodes them."""
    spans, at = [], 0
    for shot in shots:
        n = max(1, round((float(shot["src_out"]) - float(shot["src_in"])) * fps))
        spans.append((at, at + n))
        at += n
    return spans


def words_on_cut(
    plan: dict, shots: list[dict], spans: list[tuple[int, int]], fps: int
) -> list[dict]:
    """The spoken words with their times on the cut."""
    out: list[dict] = []
    per_shot = [shot.get("words") for shot in shots]
    if not any(per_shot):
        try:
            spoken = json.loads(Path(plan["words"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            spoken = []
        per_shot = [
            [
                w
                for w in spoken
                if shot["src_in"] <= (w["start_s"] + w["end_s"]) / 2 < shot["src_out"]
            ]
            for shot in shots
        ]
    for shot, (a, _b), spoken in zip(shots, spans, per_shot, strict=True):
        for w in spoken or []:
            start = a / fps + max(0.0, float(w["start_s"]) - float(shot["src_in"]))
            end = a / fps + max(0.0, float(w["end_s"]) - float(shot["src_in"]))
            out.append({"text": str(w.get("text", "")), "start": start, "end": end})
    return out


def scene_key(
    source_id: str,
    plan: dict,
    shots: list[dict],
    fps: int,
    look_print: str,
    model: str,
    resolution: str,
) -> str:
    """Names one redrawn scene. The same stretch of the same recording, cut and framed the same
    way and sent to the same place, is never paid for twice."""
    told = {
        "v": VERSION,
        "src": source_id,
        "grade": plan.get("grade"),
        "fps": fps,
        "look": look_print,
        "model": model,
        "res": resolution,
        "shots": [
            [
                round(float(s["src_in"]), 4),
                round(float(s["src_out"]), 4),
                s.get("crop"),
                s.get("follow"),
                s.get("scale"),
                s.get("gamma"),
            ]
            for s in shots
        ],
    }
    return hashlib.sha256(json.dumps(told, sort_keys=True, default=str).encode()).hexdigest()[:32]


def spent_since(ledger: str | Path | None, hours: float = 24.0) -> float:
    """Dollars the step spent, for every video, in the last ``hours`` (from its own ledger)."""
    if not ledger:
        return 0.0
    since = datetime.now(UTC).timestamp() - hours * 3600
    total = 0.0
    try:
        lines = Path(ledger).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            row = json.loads(line)
            if datetime.fromisoformat(row["at"]).timestamp() >= since:
                total += float(row["cost_usd"])
        except (ValueError, KeyError, TypeError):
            continue
    return total


def _stills(path: Path, seconds: float, count: int) -> list[bytes]:
    edge = min(0.15, seconds / 4)
    gap = (seconds - 2 * edge) / max(1, count - 1)
    return [clips.jpeg(path, edge + i * gap) for i in range(count)]


class _Run:
    """One render's pass over its scenes."""

    def __init__(
        self, cfg: dict[str, Any], api: Any, say, plan: dict, edit: dict, size: tuple[int, int]
    ) -> None:
        self.cfg, self.api, self.say, self.plan, self.size = cfg, api, say, plan, size
        self.fps = int(edit["fps"])
        self.shots: list[dict] = edit["shots"]
        self.work = Path(plan["work"])
        self.tmp = self.work / "backdrop"
        self.tmp.mkdir(parents=True, exist_ok=True)
        # Frames are found by number through their real times, never by n / fps (clips.frame_times).
        self.times = clips.frame_times(self.work / "base.mp4")
        self.cache = Path(cfg["cache_dir"]) if cfg.get("cache_dir") else None
        self.model = str(cfg.get("model") or "gemini-omni-1.2-flash")
        self.judge_model = str(cfg.get("judge_model") or "")
        self.resolution = str(cfg.get("resolution") or "1080p")
        self.max_usd = float(cfg.get("max_usd") or 0.0)
        self.face_model = str(Path(cfg["engine_dir"]) / FACE_MODEL)
        self.spent = 0.0
        self.drawn_s = 0.0
        self._refs: dict[str, list[str]] = {}
        source = Path(plan["source"])
        self.source_id = f"{source.name}:{source.stat().st_size if source.exists() else 0}"

    def refs(self, look: looksmod.Look) -> list[str]:
        if look.id not in self._refs:
            self._refs[look.id] = [self.api.upload(ref) for ref in look.refs]
        return self._refs[look.id]

    # ------------------------------------------------------------ the checks
    def check(
        self, clip: Path, raw: Path, fitted: Path, frames: int, size: tuple[int, int]
    ) -> list[checks.Finding]:
        seconds = frames / self.fps
        found = [checks.length(seconds, clips.info(raw)["seconds"])]
        if not found[-1].ok:
            return found
        if not clips.has_sound(raw):
            return [
                *found,
                checks.Finding("timing", False, "the result has no sound to time the speech by"),
            ]
        found.append(
            checks.timing(
                checks.envelope(clips.sound(clip), 8000),
                checks.envelope(clips.sound(raw), 8000),
            )
        )
        clips.conform(raw, frames, self.fps, size, fitted)
        real = _stills(clip, seconds, FACE_STILLS)
        new = _stills(fitted, seconds, FACE_STILLS)
        real_faces = checks.detect_faces(real, self.face_model)
        found.append(checks.faces(real_faces, checks.detect_faces(new, self.face_model)))
        found.append(checks.replaced(checks.background_change(real, new, real_faces)))
        if not all(f.ok for f in found):
            return found
        answer = None
        for _ in range(2):  # the look is cheap; a paid redraw is not, so ask the look twice first
            try:
                answer = self.api.look(
                    self.judge_model,
                    [real[len(real) // 2], *_stills(fitted, seconds, JUDGE_STILLS)],
                    checks.JUDGE_PROMPT,
                )
                self.spent += omni.LOOK_USD
                break
            except omni.OmniError:
                continue
        if answer is None:
            return [*found, checks.Finding("look", False, "the look at the result did not answer")]
        return found + checks.judged(answer)

    # ------------------------------------------------------------- one scene
    def scene(
        self,
        scene: scenesmod.Scene,
        a: int,
        b: int,
        look: looksmod.Look,
        speaker: str,
        n: int,
        total: int,
    ) -> dict[str, Any]:
        """Returns the report entry; entry["clip"] is the fitted file when the scene changed."""
        frames, seconds = b - a, (b - a) / self.fps
        size = self.size
        entry: dict[str, Any] = {"look": look.id, "attempts": [], "cost_usd": 0.0}
        key = scene_key(
            self.source_id,
            self.plan,
            [self.shots[i] for i in scene.keeps],
            self.fps,
            looksmod.fingerprint(look, speaker),
            self.model,
            self.resolution,
        )
        fitted = self.tmp / f"scene{scene.index:02d}.mkv"
        saved = self.cache / f"{key}.mp4" if self.cache else None
        if saved and saved.exists():
            try:
                clips.conform(saved, frames, self.fps, size, fitted)
                self.say(f"backdrop: scene {n}/{total} look {look.id} from an earlier render")
                return {**entry, "result": "new", "cached": True, "clip": str(fitted)}
            except clips.ClipError:
                pass  # a broken saved file is drawn again
        # A scene that was drawn twice and refused twice is not paid for a third time: the same
        # stretch, sent to the same place with the same words, fails the same way. It is tried
        # again when the cut, the look or the instructions change (that changes its name).
        refused = saved.with_suffix(".refused.json") if saved else None
        if refused and refused.exists():
            try:
                before = str(json.loads(refused.read_text(encoding="utf-8")).get("why") or "")
            except (OSError, ValueError):
                before = ""
            self.say(f"backdrop: scene {n}/{total} kept real (refused on an earlier render)")
            return {
                **entry,
                "result": "real",
                "refused_before": True,
                "why": f"refused on an earlier render: {before}"[:240],
            }
        clip = self.tmp / f"scene{scene.index:02d}-real.mp4"
        clips.scene_clip(
            self.work / "base.mp4", self.work / "voice.wav", a, b, self.fps, clip, self.times
        )
        video_uri, fix, why = None, "", ""
        for attempt in (1, 2):
            if self.spent + omni.estimate_usd(seconds, self.resolution) > self.max_usd:
                why = f"the spend limit for one video (${self.max_usd:.2f}) was reached"
                self.say(f"backdrop: scene {n}/{total} kept real (spend limit)")
                break
            raw = self.tmp / f"scene{scene.index:02d}-try{attempt}.mp4"
            began = time.monotonic()
            self.say(
                f"backdrop: scene {n}/{total} look {look.id} sent (try {attempt}, {seconds:.1f} s)"
            )
            try:
                video_uri = video_uri or self.api.upload(clip, "video/mp4")
                usage = self.api.edit(
                    video_uri,
                    self.refs(look),
                    looksmod.prompt(look, speaker, fix),
                    model=self.model,
                    resolution=self.resolution,
                    out=raw,
                )
            except omni.OmniError as exc:
                why = str(exc)[:200]
                entry["attempts"].append({"try": attempt, "cost_usd": 0.0, "error": why})
                self.say(
                    f"backdrop: scene {n}/{total} {'retry' if attempt == 1 else 'kept real'} (the model did not answer)"
                )
                continue
            cost = omni.cost_usd(usage) or omni.estimate_usd(seconds, self.resolution)
            self.spent += cost
            self.drawn_s += seconds
            before = self.spent
            try:
                found = self.check(clip, raw, fitted, frames, size)
            except clips.ClipError as exc:
                found = [checks.Finding("read", False, str(exc)[:160])]
            cost += self.spent - before  # the look, when it ran
            entry["cost_usd"] = round(entry["cost_usd"] + cost, 4)
            entry["attempts"].append(
                {
                    "try": attempt,
                    "cost_usd": round(cost, 4),
                    "took_s": round(time.monotonic() - began),
                    "checks": [f.as_dict() for f in found],
                }
            )
            bad = [f for f in found if not f.ok]
            if not bad:
                if saved:
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    part = saved.with_suffix(".part")
                    part.write_bytes(raw.read_bytes())
                    part.replace(saved)
                    saved.with_suffix(".json").write_text(
                        json.dumps(
                            {
                                "look": look.id,
                                "seconds": round(seconds, 3),
                                "cost_usd": entry["cost_usd"],
                                "model": self.model,
                                "resolution": self.resolution,
                                "checks": [f.as_dict() for f in found],
                            },
                            indent=1,
                        ),
                        encoding="utf-8",
                    )
                self.say(f"backdrop: scene {n}/{total} ok")
                return {**entry, "result": "new", "cached": False, "clip": str(fitted)}
            why = "; ".join(f.detail for f in bad)[:240]
            fix = " ".join(dict.fromkeys(f.fix for f in bad if f.fix))
            # Nobody could look at it: a second paid draw would not be looked at either.
            last = attempt == 2 or any(f.name == "look" for f in bad)
            self.say(
                f"backdrop: scene {n}/{total} {'kept real' if last else 'retry'} ({bad[0].detail[:80]})"
            )
            if last:
                break
        checked = [a for a in entry["attempts"] if a.get("checks")]
        looked = all(c["name"] != "look" for a in checked for c in a["checks"])
        if refused and len(checked) >= 2 and looked:
            refused.parent.mkdir(parents=True, exist_ok=True)
            refused.write_text(
                json.dumps(
                    {
                        "look": look.id,
                        "why": why,
                        "cost_usd": entry["cost_usd"],
                        "attempts": entry["attempts"],
                    },
                    indent=1,
                ),
                encoding="utf-8",
            )
        return {**entry, "result": "real", "why": why or "it did not pass the checks"}


def run(
    plan_path: str | Path, cfg: dict[str, Any], *, api: Any = None, say=print
) -> dict[str, Any]:
    """Runs the step and returns its report (also written to ``<work>/backdrop.json``)."""
    plan, edit, hidden = engine_view(plan_path, cfg["engine_dir"])
    work = Path(plan["work"])
    report: dict[str, Any] = {
        "version": VERSION,
        "model": cfg.get("model"),
        "resolution": cfg.get("resolution"),
        "scenes": [],
        "asked": 0,
        "changed": 0,
        "cost_usd": 0.0,
        "note": "",
    }
    state: _Run | None = None

    def close(note: str = "") -> dict[str, Any]:
        report["note"] = note
        if state is not None:
            report["cost_usd"] = round(state.spent, 4)
            ledger = cfg.get("ledger")
            if ledger and state.spent > 0:
                line = {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "label": cfg.get("label") or "",
                    "model": state.model,
                    "resolution": state.resolution,
                    "drawn_s": round(state.drawn_s, 2),
                    "cost_usd": round(state.spent, 4),
                    "changed": report["changed"],
                    "asked": report["asked"],
                }
                try:
                    Path(ledger).parent.mkdir(parents=True, exist_ok=True)
                    with open(ledger, "a", encoding="utf-8") as f:
                        f.write(json.dumps(line) + "\n")
                except OSError:
                    pass
        (work / REPORT).write_text(
            json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        return report

    lookset = looksmod.load(cfg.get("looks_dir"))
    if lookset is None:
        return close("there is no set of looks for this workspace")
    base, voice = work / "base.mp4", work / "voice.wav"
    if not base.exists() or not voice.exists():
        return close("the cut left no picture or voice to work on")
    fps = int(edit["fps"])
    spans = frame_spans(edit["shots"], fps)
    picture = clips.info(base)
    if not spans or spans[-1][1] != picture["frames"]:
        return close("the cut's picture does not match its list of shots")
    words = words_on_cut(plan, edit["shots"], spans, fps)
    planned = scenesmod.plan_scenes(
        [[a / fps, b / fps] for a, b in spans],
        words,
        lookset.ids,
        hidden=hidden,
        start_look=int(cfg.get("start_look") or 0),
    )
    todo = [s for s in planned if s.swap]
    report["asked"] = len(todo)
    say(f"backdrop: {len(planned)} scenes, {len(todo)} to change")
    if not todo:
        report["scenes"] = [_entry(s) for s in planned]
        return close("no scene to change in this cut")
    # A video that is made again and again (a note, a fix, another note) must not add up
    # without anyone looking: all renders together stop at the day's limit.
    day = float(cfg.get("day_usd") or 0.0)
    if day > 0:
        left = day - spent_since(cfg.get("ledger"))
        if left <= 0:
            report["scenes"] = [_entry(s) for s in planned]
            say("backdrop: kept the real backgrounds (the day's spend limit was reached)")
            return close(f"the spend limit for one day (${day:.2f}) was reached")
        cfg = {**cfg, "max_usd": min(float(cfg.get("max_usd") or 0.0), left)}
    state = _Run(cfg, api, say, plan, edit, (int(picture["width"]), int(picture["height"])))
    swaps: list[tuple[int, int, str]] = []
    nth = 0
    try:
        for s in planned:
            entry = _entry(s)
            if s.swap:
                a, b = spans[s.keeps[0]][0], spans[s.keeps[-1]][1]
                look = lookset.get(s.look or "")
                nth += 1
                try:
                    got = state.scene(s, a, b, look, lookset.speaker, nth, len(todo))
                except clips.ClipError as exc:
                    got = {
                        "look": s.look,
                        "result": "real",
                        "why": str(exc)[:200],
                        "attempts": [],
                        "cost_usd": 0.0,
                    }
                clip = got.pop("clip", None)
                entry.update(got)
                if clip:
                    swaps.append((a, b, clip))
            report["scenes"].append(entry)
        report["changed"] = len(swaps)
        if swaps:
            new = clips.rebuild(base, swaps, fps, state.tmp)
            clips.replace(new, base, keep_as=work / "base.real.mp4")
        say(f"backdrop: joined {len(swaps)}/{len(todo)}, ${state.spent:.2f}")
    except clips.ClipError as exc:
        report["changed"] = 0
        say(f"backdrop: kept the real backgrounds ({str(exc)[:120]})")
        return close(f"the picture could not be put back together: {str(exc)[:200]}")
    return close()


def _entry(s: scenesmod.Scene) -> dict[str, Any]:
    return {
        "index": s.index,
        "start_s": round(s.start_s, 3),
        "end_s": round(s.end_s, 3),
        "result": "real",
        "why": s.reason,
        "look": s.look,
    }
