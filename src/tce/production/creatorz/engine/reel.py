#!/usr/bin/env python3
"""Creatorz reel engine CLI.

  python reel.py all     <plan.json>              cut -> masks -> compose -> mix -> measure
  python reel.py cut     <plan.json>              shots + base.mp4 + voice.wav + edit.json (prints the shot list)
  python reel.py masks   <plan.json>              person masks for sky headlines (needs rembg; optional)
  python reel.py stills  <plan.json> 2.4 7.6 ...  render chosen output times to <work>/stills/*.png to look first
  python reel.py compose <plan.json>              overlay.mp4 + events.json
  python reel.py mix     <plan.json>              the finished reel (plan "out")
  python reel.py measure <plan.json>              the checklist -> <work>/checklist.json (exit 1 on any FAIL)
  python reel.py check   <plan.json>              validate the plan + resolve every cue against edit.json (no render)

Needs ffmpeg, numpy and Pillow; OpenCV (face-centered punch-ins) and rembg (text behind the head) are optional.
The plan format is in SKILL.md ("Tools: the reel engine")."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from creatorz_reel import plan as planmod  # noqa: E402


def main(argv):
    if len(argv) < 3 or argv[1] not in ('all', 'cut', 'masks', 'stills', 'compose', 'mix', 'measure', 'check'):
        print(__doc__)
        return 2
    cmd, plan = argv[1], planmod.load(argv[2])
    if cmd in ('cut', 'all'):
        from creatorz_reel import cut
        cut.run(plan)
    if cmd == 'check':
        import json
        from creatorz_reel import compose_plan
        edit = json.load(open(os.path.join(plan['work'], 'edit.json'), encoding='utf8'))
        spec = compose_plan.build(plan, edit)
        print(f"check: {len(spec['items'])} moments, {len(spec['sfx'])} sound cues, {len(spec['captions'])} caption lines - all cues resolve")
        return 0
    if cmd in ('masks', 'all'):
        from creatorz_reel import masks
        masks.run(plan)
    if cmd == 'stills':
        from creatorz_reel import compose
        compose.run(plan, stills=argv[3:])
        print(f"stills: {os.path.join(plan['work'], 'stills')}")
        return 0
    if cmd in ('compose', 'all'):
        from creatorz_reel import compose
        compose.run(plan)
    if cmd in ('mix', 'all'):
        from creatorz_reel import mix
        mix.run(plan)
    if cmd in ('measure', 'all'):
        from creatorz_reel import measure
        res = measure.run(plan)
        return 1 if any(v[0] == 'FAIL' for v in res) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
