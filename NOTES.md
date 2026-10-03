# C1 step log: Agent talk intake (C4, TCE side) + Jennifer name

Branch: feat/agent-talk-jennifer. Plan: kmbot plans/03-Oct-26-jack-cto-selfie-jennifer.md (C4).
Test runner: .tmp/run-tests.sh (dead Postgres URL so nothing can reach a real DB; PYTHONPATH =
src + .testdeps; the live app runs on the system python3, there is no .venv).

## Attempt 1 (died on a usage limit, about 15:43 Israel time)
- Partial clone + branch created (only the clone and the checkout, no commits).
- Test deps installed into .testdeps (pytest 9.1.1, pytest-asyncio 1.4.0, aiosqlite, factory-boy),
  .testdeps/.tmp/.pgtest excluded in .git/info/exclude.
- Baseline suite on master 5495cee: 8 failed, 1822 passed, 30 skipped (7m03s). All 8 failures
  are Playwright browser tests: the headless Chromium binary is not installed on this box
  (environment, not code). No browser install allowed here (disk), so these 8 stay red.

## Attempt 2 (started 15:57 Israel time)
- 15:57 Read the clone state: no NOTES.md, no commits, clean tree, baseline log present.
  Continuing from "read the code, then build".
