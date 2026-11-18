#!/usr/bin/env python3
"""How the app starts the new-backgrounds step, under the Creatorz engine's Python.

  python -P cli.py <plan.json> <config.json>

The key comes in the TCE_BACKDROP_KEY environment variable, never on the command line. The
exit code is 0 whenever the base picture is usable afterwards (changed or left as it was);
the report next to it (backdrop.json) says what happened to each scene.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # .../src, so `tce` imports

from tce.production.backdrop import omni, step  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    cfg = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    key = os.environ.pop("TCE_BACKDROP_KEY", "")
    try:
        api = omni.Api(key)
    except omni.OmniError as exc:
        print(f"backdrop: kept the real backgrounds ({exc})")
        return 0
    report = step.run(argv[1], cfg, api=api, say=lambda line: print(line, flush=True))
    if report.get("note"):
        print(f"backdrop: note: {report['note']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
