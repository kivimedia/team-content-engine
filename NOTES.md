# C1 step log: Agent talk intake (C4, TCE side) + Jennifer name

Branch: feat/agent-talk-jennifer. Plan: the KM BOT build plan of 3-Oct-2026, contract C4
(agent-talk intake) and the Jennifer name.
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
- 16:4x voices + Jennifer tests 21 passed; commits 293cee9 (intake), 83513f1 (voices),
  6bcc94f (Jennifer).
- 16:45 full suite #1 (branch): 7 failed, 1887 passed, 3 skipped (7m39s). NOTE the box
  now HAS the Playwright Chromium (baseline had 30 skipped and 8 browser failures; those
  8 now pass). Failures:
  - 2 mine: _compute_plan on a SimpleNamespace row (no .source) -> getattr. Fixed.
  - 1 mine: test_no_ungated_topic_source forbids TopicCandidate(...) outside the
    selector and the calibration writer. Moved the talk's row into
    editorial/agent_talk_topics.py (origin and status pinned), added it to the guard's
    allowed set with a new pinning test (origin agent_talk, status recorded, hidden).
  - 4 browser tests (3 test_workspace_talk_sheet_phone "Your note at 0:00", 1
    test_recording_studio_mobile textBigger covered) FAIL THE SAME WAY ON MASTER 5495cee
    (worktree .tmp/master-wt, log .tmp/master-browser.log): environment, not this branch.
- 17:0x also: speakers ("HOST:", "ATLAS:") in the typed-request and sitting prompts, a
  talk context line in every job's context, finish recovers a joined file after a crash
  between the join and the row. Targeted run: 159 passed. Commit 1844488, branch pushed.
- 17:05 full suite #2 (1844488): 4 failed, 1892 passed, 3 skipped (8m42s). The 4 are the
  browser tests that fail identically on master (see above). Everything else green.
- 17:1x a later finish that brings the call's transcript keeps it on the video (the
  sweeper may finish first without it); the voice tools' own text says "your standing
  rules for you, his video editor" and "Last word on the edit" (Jennifer reads them).

## Attempt 3 (started 18:00 Israel time)
- 18:00 Read NOTES.md and the uncommitted diff: the last step of attempt 2 was complete in
  the tree (a later finish keeps the call's transcript; the voice tools' text).
- 18:05 targeted run (agent talk, voices, Jennifer and every test file that names them):
  254 passed, 3 failed, 3 skipped. The 3 are the notes-sheet browser tests that fail the
  same way on master. Committed and pushed; full suite #3 follows.
