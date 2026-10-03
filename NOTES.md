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
- Design: an agent talk gets its own table (agent_talks) and its pieces live on disk
  (one file per seq, sha compared on a resend: same bytes = 200, different = 409). Finish
  joins by byte concatenation + ffmpeg remux (-c copy, webm then mp4 then mkv), never a
  re-encode, deletes the pieces once the joined file holds them, and creates a
  TopicCandidate (origin agent_talk, status recorded, title "Talk with <Agent>, <d Mon>")
  plus a RecordingUpload (source agent_talk, agent_name, call_transcript). The candidate
  keeps every upload code path working (candidate_id is NOT NULL); the idea lists
  (inbox HIDDEN_ORIGINS, editorial candidates list, selector on_the_list) leave it out.
- Two voices: production/agent_talks.voices() aligns whisper words with the call lines by
  text (SequenceMatcher), maps the call clock with a median offset, fills the rest by
  neighbours or by the line playing at that time. No usable call transcript = every word
  protected (only pauses cut). protected = the agent's word indices, passed to plan_edit
  (rules run per host turn, agent words never cut except by his own requested cut),
  validate_removals (removals shrink around agent words) and the review prompt (HOST: /
  AGENT-NAME: lines + conversation rules).
- 16:4x step 1 committed (244e45a): table + migration 057 + migration test (4 passed).
- 17:0x intake tests: tests/unit/test_agent_talks.py 12 passed (real ffmpeg webm and
  fragmented mp4 joins, idempotent create and pieces, kill switch, library card).
