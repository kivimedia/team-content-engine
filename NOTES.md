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
- 18:11 full suite #3 (bca484d): 4 failed, 1893 passed, 3 skipped (8m43s). The same 4
  browser tests as on master (3 notes-sheet "Your note at 0:00", 1 recording studio
  textBigger covered). Nothing else red. C1 is complete on this branch.

# C2 step log: Jennifer checks every edit, and learns rules from his notes (phase 6)

Same branch, same runner (.tmp/run-tests.sh for the full suite; .tmp/c2rt.sh for targeted
runs). Builder edits a mirror of src/tests on the PC and ships it with tar over ssh.

## Attempt 1 (started about 18:40 Israel time)
- Read C1's report (complete, branch at c361a90, clean tree) and the code the role names:
  tightcut.pause_stats, autoedit (word_marks, apply_batch, review prompt), retakes,
  media.render_edit, wordbox, relisten, llm provider/queue, alembic 056/057, the skill file.
- Design:
  - production/qc.py: pure checks on the RENDERED file. gaps (10 ms levels of the
    render, quiet runs minus kept words, plus "nobody speaks" stretches when the
    recogniser's second listen has times), loudness (ffmpeg ebur128 I and true peak),
    captions (the caption data the render was drawn from, written beside the edit as
    <name>.render.json, checked against the plan's kept words), audibility (word_marks
    clipped and phone-cut, plus the render re-transcribed through the local ASR worker in
    clip mode; a word is inaudible only when the recogniser missed it AND the level at
    that word stays under speech level), leftover asides (one llm job, video_qc_asides,
    proven by quoting, agent words protected, more than 25% = not a check).
  - Fix or hold: loudness is fixed INSIDE the render (two-pass loudnorm, -14 LUFS, TP
    -1, filter aims at -1.5; the first pass only listens to the cut audio, so the picture
    is encoded once). Gaps become a new override "trim" (a cut only drops words, so dead
    air between words needed its own override; merge_overrides keeps it, a restore lifts
    it), asides become "cut", clipped words become "hold". Then ONE re-render and one
    re-check (round 1). Anything still failing, or unfixable (phone-cut word, inaudible
    word, caption missing or mismatched, loudness off after the render), holds the video
    as needs_review with ONE line. Pass = "Checked by Jennifer: <numbers>".
  - Status "checking" while she works (live step on the card), recording_uploads.qc holds
    the newest verdict, render_checks keeps every check. Held videos cannot be posted
    until a note fixes them or he taps "It is fine, let it through". Settings:
    production_qc (fix | report | off), production_qc_asides_wait_s, production_qc_listen,
    production_learn_rules. The suite's conftest switches qc and learning off; the
    Jennifer tests switch them on.
  - Rules: production/rules.py (distill job editor_rule_distill: rule | this_video |
    covered, cleaned to one plain sentence, no time stamps), editorial/editor_rules.py
    (rows, deactivate, applied counts per video once), injected after the skill file in
    the review and the asides check, numbered R1..Rn, capped at 3000 chars with the
    oldest left out and a log line (editor_rules.cap_hit). A removal or aside whose why
    names (Rn) counts that video for the rule. Learning runs after an applied typed
    request and after a sitting whose notes changed the video; restart-safe
    (learned.state asking).
  - Migration 058: recording_uploads.qc, render_checks, editor_rules. Additive.
  - UI: card shows her line (green when checked, red when held), "Ask Jennifer to check
    it again", "It is fine, let it through", what she learned from each note; new page
    /library/rules (Jennifer's rules) with source video link and Delete. Voice: tools
    tce_video_check and tce_video_rules, seat brief and tce.json updated, the moment's
    rules include her learned rules, tce_recordings says "held by Jennifer".
- 18:51 full suite on the first cut (qc off in conftest): 6 failed, 1891 passed, 3 skipped.
  4 = the browser baseline. 2 mine: test_render_edit_cuts_kept_ranges (new status line,
  updated) and the seat installer count (tools 20 -> 25, updated).
- Fixture lessons: lavfi aevalsrc needs the expression quoted (commas); a tone has no
  "s", so words ending on a hiss are flagged phone-cut (fixtures avoid them); the asides
  check refuses an answer over 25% of the words, so fixtures need longer talk.
- 19:25 targeted (test_jennifer_qc, test_jennifer_flow, test_jennifer_rules,
  test_production_media, the installer test): 83 passed.
- 19:3x committed f6dbbcb, 307355a, 26f6d80, 708f5ac, a8c8f97 and pushed.
- 19:47 full suite on a8c8f97: 7 failed, 1963 passed, 3 skipped (26m37s, box loaded).
  4 = browser baseline. 3 new in test_mcp_voice_protocol (JSONDecodeError at about
  16.3 KB): the harness printed the tool list with console.log and exited at once, and
  a pipe write is asynchronous in node, so the two new tool descriptions pushed it past
  the first 16 KB chunk and the rest was lost. Fix in the harness (write, then exit in
  the write callback). test_mcp_voice_protocol.py after the fix: 5 passed.
- Ad hoc (not committed): a real MP4 with word-box captions through _plan_and_render with
  the check on: edited, "Checked by Jennifer", captions mode wordbox 9 of 9.
- 20:3x full suite on 9f1a5a1: 4 failed, 1966 passed, 3 skipped (20m24s). The 4 are the
  browser baseline (3 notes-sheet "Your note at 0:00", 1 recording studio textBigger),
  same as master. C2 is complete on this branch; nothing deployed, migration 058 run only
  on the test database.

# C3 step log: adversarial review and fixes of C1 + C2

Reviewer: C3. Start: branch at 16562a0, clean tree, local == origin. Same runner (.tmp/run-tests.sh).
- 20:23 start: read the plan (DECIDED 6 to 8, C4), the full diff vs origin/master (src 5874 lines,
  tests 3045 lines), C1 and C2 reports. Disk at start: 55 GB free (91%).
- Baseline before any change (8 files C1/C2 own: agent talks, voices, migration, jennifer qc/flow/rules/name,
  production media): 121 passed in 143.8 s (.tmp/c3-base.log).
- Hygiene scan of git diff origin/master...HEAD: no emails, IPs or personal paths in added lines; names
  only Maple/Rain (already in 3 master src files) and the C4 wire value "ziv" (contract, 5 lines);
  commit identity is the repo's own (same as master). Dashes only in detection constants.
- Findings and fixes (this round):
  F1 a waiting review asked with a rule he later deleted re-used its saved rules: the deleted rule
     reached the review and its cut was applied. Fixed: _await_review asks again with the rules in
     force; _review drops an answer whose rule was deleted while it read (waits, re-asks); her asides
     reading is not used when a rule it read was deleted; mark_applied skips an inactive rule.
  F2 the distilling job and her voice seat listed EVERY active rule (no cap): a long list blew up
     those prompts. Fixed: editor_rules.in_block, the same 3000-char cap as the review; the rules page
     says which rules are past the cap ("Not used right now"), the voice tool payload is capped at 20.
  F3 her hold line could carry an em dash from the subscription's own reason or a quoted caption.
     Fixed: qc.plain on every line, problem detail and fix sentence; also the error and stop lines.
  F4 a chunk PUT without Content-Length was read whole into memory before the 64 MB check. Fixed:
     streamed with the limit.
  F5 pieces and joins could fill the disk (VPS at 91%). Fixed: a 2 GB free-space floor (507) on a
     piece, and a join refused before it writes when 2x the talk would cross the floor; pieces kept.
  F6 a talk whose finish never came stayed pieces on disk forever, never a video. Fixed: TCE backstop
     finishes talks idle 6 h (startup, and when a new talk is created); a later relay finish still
     brings the transcript. No-piece talks say so (failed).
  F7 a far-out sequence number built a list of up to a million missing numbers in join_meta. Fixed:
     counted gap by gap, first 200 kept plus missing_count.
  F8 the rule record did not say why a note became a rule. Fixed: learned.why for rule and covered.
- Proof of the two-voice rule: tests/unit/test_agent_talk_dog_lines.py (agent says "Um, sorry, my
  dog question first. I heard Maple, come here." and his own "Maple, come here!"): rules path, review
  path, her asides check and the whole auto edit keep every agent word and cut his call.
- Independent QC numbers: tests/unit/test_jennifer_qc_guards.py re-reads loudness, peak, longest pause,
  dead air and the caption count with ffmpeg ebur128/silencedetect and the .srt; all agree.
- 20:43 targeted run after the fixes: 130 passed in 91 s (.tmp/c3-t1.log). The same new tests on the
  pre-fix code (worktree .tmp/c3-pre at 16562a0): 17 failed, 35 passed, each failure for the bug it
  guards (whole body read, deleted rule in the review system text, 'done' instead of 'waiting',
  em dash in her line, rule counted after delete, no floor/backstop/cap functions).
- Commit e240f98 pushed. Full suite on e240f98 (.tmp/c3-full1.log): 4 failed, 1997 passed, 3 skipped in
  8m12s (1966 + 31 new). The 4 are the browser baseline; I ran those 4 on master 5495cee myself
  (.tmp/master-wt): the same 4 fail with the same assertions ("Your note at 0:00" x3, textBigger
  covered by the topbar).
- 20:57 second round: an auth test for every new Jennifer route (check, release, rules list, rule delete:
  401 without the key or with a wrong one); the dash regexes in qc.py and rules.py written with \u
  escapes, so the source holds no dash characters. QC + rules files: 70 passed.
- Live folder /home/ziv/team-content-engine read only: HEAD 5495cee, untracked files only, untouched.
- 21:07 final full suite on ab3ad9a (.tmp/c3-full2.log): 4 failed, 1998 passed, 3 skipped in 9m36s; the 4
  are the browser baseline that fails the same way on master. Branch pushed. Left for cleanup (recursive
  delete is gated): the worktree .tmp/c3-pre (git worktree prune after), and the PC scratch folder c3.
