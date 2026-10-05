/* Talking to the editor: the hold-to-talk half of the notes sheet (1-Oct).
 *
 * Design of record: plans/30-Sep-26-talk-to-the-editor.md, section 1 (points 3-8),
 * section 2 (the call is KM BOT's tce seat, embedded) and section 6 (failure modes).
 * This is build step 8, "Sheet, talking".
 *
 * The sheet (the Library player's "Talk to Jennifer" page; 3-Oct, the editor is Jennifer)
 * owns the video, the
 * typed notes and "Make the new version". This file owns the call:
 *
 *   var talk = TceTalkVoice.open({
 *     root: element,        // the hold button and the status line are drawn in here
 *     video: videoElement,  // the player he is watching
 *     sitting: payload,     // POST /production/recordings/{id}/talk: session_id, upload_id, render_ref
 *     notes: listElement,   // optional: the notes, drawn from the rows TCE stores
 *     api: fn,              // optional: workspace.js's api(); a same-shaped one is built in
 *     onSitting: fn(p),     // optional: every fresh read of the sitting (the notes changed)
 *     onStale: fn(ref, p)   // optional: the sitting moved to another render; play p.file_url
 *   });
 *   talk.close();           // the sheet closes: the call ends, every note stays on the server
 *
 * What it keeps, each one a sentence in the design:
 *
 * - /voice-client.js (KM BOT's, on the same host, never under /tce) is loaded only
 *   when the sheet opens. When it answers 401 (the "KM BOT" sign-in is not on this
 *   phone yet) the sheet says so and links to /voice?seat=tce&context=video:<id>.
 * - The call starts muted and silent (greet:false, startMuted:true): nothing talks
 *   until he does, and he talks only while he holds the button.
 * - Press: the video pauses, the page reads currentTime and pins it at once. The
 *   second is the page's, never retyped by a model. Release: the mic mutes and his
 *   words, as the voice transcribed them, are saved on that note.
 * - The editor answers out loud (the call) AND in writing: the written answer is the
 *   note row TCE stores (`understood`), read by polling. Live's own speech is never
 *   drawn, because Live paraphrases and can embellish.
 * - Play hushes the editor and keeps it quiet while the video plays; the mic stays
 *   muted, so the video's sound (his own voice) is never taken as a note.
 * - A screen wake lock is held while the sheet is open.
 * - A call that drops says "Voice dropped - hold to reconnect", and the next hold
 *   starts a fresh call on the same sitting: every pin and every word is already on
 *   the TCE server, and the call is not the record.
 *
 * 1-Oct review fixes, each with its test in tests/unit/test_talk_voice_phone.py:
 * - Live sends no end of turn while his mic is muted, so "the editor is answering"
 *   ends when its words stop for SPEAKING_QUIET_MS, not on turn_end alone.
 * - A press keeps the editor quiet for the whole hold (quiet first, then hush):
 *   K1's quiet(false) plays an element hush() paused, so the old order let the
 *   editor talk over him. Pause lifts the quiet only when he is not holding.
 * - Letting go keeps the mic open RELEASE_GRACE_MS, so the voice hears the end of
 *   his sentence (KM BOT's scenario F lets go the same way, 1.5 s after it).
 * - A second press does not cut the last note short: its late words stay on it
 *   until they stop, then the new note's words start.
 * - Closing the sheet lets the last note's words land before the call ends, and
 *   never takes a note back.
 * - While the notes are being made, the bar shows the batch's own step
 *   (result.status), and how it ended; a hand-back says why, once.
 *
 * 1-Oct final review fixes (tests in test_talk_voice_phone.py, the sheet's in
 * test_workspace_talk_sheet_phone.py):
 * - A pin says it is a hold (by "voice"): the editor's voice reads holds, never a
 *   typed note.
 * - A voice client whose call has no mute and no quiet (KM BOT before K1) is not
 *   kept: the call would be open, greet over the video and throw on every hold.
 * - Once the notes leave the sheet (being made, made), the call hangs up after the
 *   editor finishes saying so, and the screen may sleep. The next hold on notes that
 *   are open again starts a fresh call.
 * - Notes another screen closed: a hold opens them again (the pin does it).
 * - A hold whose settle ended with no words, as the sheet closes, carries nothing of
 *   his: it is taken back before the close is done. One left from an earlier visit
 *   says "No words were caught here", and nothing polls for it.
 * - His words on a hold the editor took as an instruction (make it, yes) say so,
 *   never "Saved".
 */
(function (global) {
  "use strict";

  // KM BOT's voice client. Absolute: /tce/voice-client.js does not exist.
  var VOICE_SCRIPT = "/voice-client.js";
  var TAP_MS = 350;            // a press shorter than this is a tap, not a note
  var RELEASE_GRACE_MS = 1500; // after he lets go the mic stays open this long: the voice hears his sentence end
  var SETTLE_QUIET_MS = 1200;  // after release: this long with no new words ends the note
  var SETTLE_MAX_MS = 3500;    // ...and never longer than this (the moment route waits 4 s)
  var HANDOFF_QUIET_MS = 600;  // pressed again while the last note's words still arrive: this long with none ends it
  var HANDOFF_MAX_MS = 1500;   // ...and never later than this after the new press
  var SPEAKING_QUIET_MS = 1500; // no new words from the editor for this long: it has stopped talking
  var POLL_FAST_MS = 2000;     // while a note waits for its words or the editor's reading
  var POLL_SLOW_MS = 30000;    // otherwise: the sheet's heartbeat (a sitting is "active" for 120 s)
  var AWAIT_MS = 120000;       // the seat brain's own turn cap: past it, "not confirmed yet"
  var NOTICE_MS = 7000;        // how long a one-off sentence stays before the status returns
  var WAITING = ["listening", "held"];
  var WORKING = ["thinking", "rendering"];
  var VIDEO_BUSY = ["transcribing", "rendering"];  // the upload's own step is live (production.BUSY_STATUSES)
  var HANGUP_WAIT_MS = 10000;  // the notes left the sheet: the editor has this long to start saying so
  var DROPPED = "Voice dropped - hold to reconnect";
  // In place of the voice client's raw "Voice error: {json}" (the whole error is logged).
  // 3-Oct: the editor has a name. Every sentence he reads says Jennifer.
  var EDITOR = "Jennifer";
  var VOICE_PROBLEM = EDITOR + "'s voice reported a problem. Your notes are saved.";
  // KM BOT's voice client on this box has no mute or quiet for the call yet (K1).
  var OLD_VOICE = EDITOR + "'s voice on this box is older than the notes sheet, so holding to talk "
    + "waits for its update. Typing still works.";
  var CLOSED_ELSEWHERE = "These notes were closed on another screen. Hold to talk opens them again.";
  var NO_WORDS_HERE = "No words were caught here.";
  // Design section 6: a note the editor never read still goes to it as he said it.
  var UNCONFIRMED = EDITOR + " has not confirmed this one. It is still made as you said it.";
  var NOT_A_NOTE = "That hold was not kept as a note.";
  // A client's own login (5-Oct, Ziv: no mic on his login): typed notes only.
  var TYPED_ONLY = "Pause where something is wrong, then tap Type to write a note.";

  var prefix = global.location.pathname.indexOf("/tce/") === 0 ? "/tce" : "";
  var apiV1 = prefix + "/api/v1";

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function clock(seconds) {
    var total = Math.floor(Math.max(0, Number(seconds) || 0));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  function norm(text) { return String(text || "").replace(/\s+/g, " ").trim(); }

  // The sitting's own sentence: the batch's live step, how it ended, or why it was handed back.
  function statusOf(payload) { return norm(payload && payload.result && payload.result.status); }

  /* An error the voice client reports, as a sentence for him. Live's own errors come
     as "Voice error: {json}", which is not a sentence: it goes to the console. */
  function plainError(text) {
    var t = norm(text);
    if (/^Voice error\b/i.test(t) || /[{}]/.test(t)) {
      try { global.console.warn("[talk-voice] " + t); } catch (e) { /* no console */ }
      return VOICE_PROBLEM;
    }
    return t;
  }

  // The end of a long run of words: the box keeps two lines at 390 px, and the newest words matter.
  function tail(words, max) {
    max = max || 64;
    if (words.length <= max) return words;
    var cut = words.slice(-max);
    var space = cut.indexOf(" ");
    return "..." + (space > 0 && space < 20 ? cut.slice(space + 1) : cut);
  }

  /* The same shape as workspace.js's api(): the sentence to show on error.message,
     the status and the server's detail (code, render_ref) on the error. */
  async function defaultApi(path, options) {
    var o = options || {};
    var init = { method: o.method || "GET", credentials: "same-origin", headers: {} };
    if (o.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(o.body);
    }
    var response = await fetch(apiV1 + path, init);
    var text = await response.text();
    var payload = null;
    if (text) { try { payload = JSON.parse(text); } catch (e) { payload = null; } }
    if (!response.ok) {
      var detail = payload && payload.detail;
      var message = detail && typeof detail === "object" && detail.message ? detail.message
        : typeof detail === "string" && detail ? detail
        : "Something went wrong (" + response.status + ").";
      var error = new Error(message);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return payload;
  }

  // ------------------------------------------------------ loading the voice

  /* Loaded once per page, and only when a sheet opens. The probe comes first: a
     <script> that fails says nothing about why, and a 401 needs its own answer (the
     "KM BOT" sign-in, which this page's "TCE editor" sign-in does not cover). The
     probe is also where the browser asks for that sign-in, once. */
  var loading = null;
  function loadVoiceClient(src) {
    src = src || VOICE_SCRIPT;
    if (global.KmVoice) return Promise.resolve({ ok: true });
    if (loading) return loading;
    loading = (async function () {
      var status = 0;
      try {
        var probe = await fetch(src, { credentials: "same-origin", cache: "no-cache" });
        status = probe.status;
      } catch (e) { status = 0; }
      if (status < 200 || status >= 300) return { ok: false, status: status };
      return await new Promise(function (resolve) {
        var tag = document.createElement("script");
        tag.src = src;
        tag.async = true;
        tag.onload = function () { resolve(global.KmVoice ? { ok: true } : { ok: false, status: 0 }); };
        tag.onerror = function () { tag.remove(); resolve({ ok: false, status: 0 }); };
        document.head.appendChild(tag);
      });
    })();
    // A refusal is not remembered: after he signs in, the next open tries again.
    loading.then(function (r) { if (!r.ok) loading = null; });
    return loading;
  }

  // ------------------------------------------------------- his words, per note

  /* The voice client reports his words two ways (KM BOT web/voice-client.js):
     "hearing" carries the whole running buffer, and "said" carries it once, when
     it is flushed - when the editor starts to answer, when Live hands the words to
     the backend (which can be mid-sentence), or when the call closes. The buffer
     can still hold the previous note's words when he presses again, so a note is
     what came AFTER the press. */
  function Capture() {
    this.buffer = "";  // the voice's running buffer, as last reported
    this.on = false;
    this.owner = null; // the press whose words these are
    this.base = "";    // the buffer at the press: not this note's words
    this.done = "";    // flushed while this note was open
    this.live = "";    // in the buffer since the press
  }
  Capture.prototype.start = function (owner) {
    this.on = true;
    this.owner = owner || null;
    this.base = this.buffer;
    this.done = "";
    this.live = "";
  };
  Capture.prototype.stop = function () { this.on = false; this.owner = null; };
  Capture.prototype.hearing = function (text) {
    var n = norm(text);
    // A buffer that no longer starts with what it held at the press started over.
    if (this.base && n.indexOf(this.base) !== 0) this.base = "";
    this.buffer = n;
    if (this.on) this.live = norm(n.slice(this.base.length));
    return this.on;
  };
  Capture.prototype.said = function (text) {
    var n = norm(text);
    var mine = this.base && n.indexOf(this.base) === 0 ? n.slice(this.base.length) : n;
    this.buffer = "";
    this.base = "";
    if (!this.on) return false;
    this.done = norm(this.done + " " + mine);
    this.live = "";
    return true;
  };
  Capture.prototype.words = function () { return norm(this.done + " " + this.live); };

  // ------------------------------------------------------------ the note rows

  /* What one note row says. `pending` is "reading" while this page waits for the
     editor's reading of a note it pinned, "unconfirmed" once that wait ran out. */
  function noteView(note, pending) {
    var r = note.result || {};
    var view = {
      when: note.start_s !== null && note.start_s !== undefined ? clock(note.start_s) : (note.where || ""),
      said: norm(note.request),
      answer: "",
      kind: "",
      moved: r.moved || ""
    };
    if (note.understood) { view.answer = note.understood; view.kind = "understood"; }
    if (note.state === "done") {
      view.answer = r.reply || view.answer || "Done."; view.kind = "done";
    } else if (note.state === "needs_you") {
      view.answer = r.question || r.reply || "This one needs you."; view.kind = "needs_you";
    } else if (note.state === "in_progress" || note.state === "queued") {
      view.answer = r.status || "Being made into the new version."; view.kind = "working";
    } else if (!note.understood && WAITING.indexOf(note.state) >= 0 && view.said) {
      if (pending === "reading") { view.answer = EDITOR + " is reading this note."; view.kind = "reading"; }
      else if (pending === "unconfirmed") {
        /* 1-Oct final review: "hold and say it again" pinned a second copy, which also
           went unread. The note already goes to the editor as he said it. */
        view.answer = UNCONFIRMED; view.kind = "unconfirmed";
      }
    }
    return view;
  }

  /* `listeningTo(id)`: this page is listening for that pin's words right now. A pin
     with no words that nothing listens for (left by an earlier visit, or another
     screen) says so, with its x, instead of "Listening for your words". */
  function notesHtml(notes, pendingOf, listeningTo) {
    var shown = (notes || []).filter(function (n) { return n.state !== "rejected"; });
    if (!shown.length) {
      return '<li class="tv-empty">No notes yet. Pause where something is wrong, then hold to talk.</li>';
    }
    return shown.map(function (n) {
      var v = noteView(n, pendingOf(n.id));
      var canDrop = WAITING.indexOf(n.state) >= 0;
      var html = '<li class="tv-note' + (v.kind ? " is-" + v.kind : "") + '" data-note-id="' + esc(n.id) + '">';
      html += '<div class="tv-note-head"><span class="tv-when">' + esc(v.when) + "</span>";
      if (canDrop) {
        html += '<button class="tv-drop" type="button" data-tv-drop="' + esc(n.id)
             + '" aria-label="Take back the note at ' + esc(v.when) + '">&#10005;</button>';
      }
      html += "</div>";
      var said = v.said ? "You said: “" + esc(v.said) + "”"
        : listeningTo && listeningTo(n.id) ? "Listening for your words"
        : n.understood ? ""
        : NO_WORDS_HERE;
      if (said) html += '<p class="tv-said">' + said + "</p>";
      if (v.answer) {
        html += '<p class="tv-answer">' + (v.kind === "understood"
          ? "<strong>" + EDITOR + ":</strong> “" + esc(v.answer) + "”"
          : esc(v.answer)) + "</p>";
      }
      if (v.moved) html += '<p class="tv-moved">' + esc(v.moved) + "</p>";
      return html + "</li>";
    }).join("");
  }

  // --------------------------------------------------------------- the sheet

  function open(opts) {
    var root = opts.root;
    var video = opts.video || null;
    var api = opts.api || defaultApi;
    var start = opts.sitting || {};
    var sitting = {
      id: start.session_id,
      upload: start.upload_id,
      ref: start.render_ref || null,
      state: start.state || "open",
      step: start.video_step || "",                          // the upload's own step line
      videoBusy: VIDEO_BUSY.indexOf(start.video_status) >= 0, // ...and whether it is live now
      status: statusOf(start)                                 // the sitting's own sentence
    };
    var closed = false;
    var closing = null;      // close() was called: {promise, resolve}. His last words still land.
    // loading | signin | unavailable | old (no mute on this box) | idle (no call: the notes
    // are not taking new ones) | connecting | ready | dropped | failed
    // typedOnly (5-Oct): a client's own login. No hold button, no sign-in link, and
    // KM BOT's voice client is never fetched: the voice is "off" for the whole sheet.
    var typedOnly = Boolean(opts.typedOnly);
    var voice = typedOnly ? "off" : "loading";
    var hangUp = null;       // the notes left the sheet: {since, spoke, force, timer} until the call ends
    var hangUpWait = opts.hangUpWaitMs || HANGUP_WAIT_MS;
    var voiceWhy = "";       // the sentence for failed / unavailable
    var call = null;         // the KmVoice handle of the call in use
    var callToken = null;    // events from any other call (an old one) are ignored
    var hold = null;         // the press in progress
    var settling = null;     // released: {h, quiet, max, maxAt, handoff}, its words still arriving
    var capture = new Capture();
    var awaited = {};        // note id -> when this page pinned it (waiting for a reading)
    var unconfirmed = {};    // note id -> true: the wait ran out
    var saved = {};          // note id -> the words last saved on it
    var savingWords = {};    // note id -> true while its words are on their way to TCE
    var notes = start.notes || [];
    var notesKey = "";
    var speaking = false;    // the editor is talking (its words are arriving)
    var speakingTimer = null;
    var muteTimer = null;    // the mic closes RELEASE_GRACE_MS after he lets go
    var notice = null;       // {text, until}
    var noticeTimer = null;
    var pollTimer = null;
    var epoch = 0;           // bumped when the sitting is reopened on a new edit
    var wakeLock = null;
    var shownStatus = "";    // the sitting's own sentence, last said as a notice

    /* The bar keeps the same height whatever it says (1-Oct review: the words box
       appearing mid-hold moved the button 73 px under his thumb): the status line has
       three lines, and the words box (or the sign-in link) has a slot of its own. */
    root.innerHTML =
        '<div class="tv" data-tv>'
      + '<p class="tv-status" role="status" aria-live="polite"></p>'
      + '<div class="tv-slot">'
      + '<p class="tv-words is-empty"></p>'
      + '<a class="btn tv-signin" target="_blank" rel="noopener" hidden>Sign in to the voice</a>'
      + "</div>"
      + '<button class="tv-hold" type="button" aria-pressed="false">Hold to talk</button>'
      + "</div>";
    if (opts.notes) opts.notes.classList.add("tv-notes");
    var statusEl = root.querySelector(".tv-status");
    var wordsEl = root.querySelector(".tv-words");
    var signinEl = root.querySelector(".tv-signin");
    var button = root.querySelector(".tv-hold");
    if (typedOnly) {
      button.hidden = true;
      root.querySelector(".tv-slot").hidden = true;
    }
    signinEl.href = "/voice?seat=tce&context=video:" + encodeURIComponent(sitting.upload || "")
      + "&return=" + encodeURIComponent(global.location.pathname + global.location.search);

    // ------------------------------------------------------------ painting

    function gone() { return closed || Boolean(closing); }

    // Notes he can still add to: open, or closed on another screen (a hold opens them again).
    function takingNotes() { return sitting.state === "open" || sitting.state === "closed"; }

    // Voice states in which a hold cannot be used at all.
    var NO_HOLD = ["loading", "signin", "unavailable", "old", "off"];

    function say(text) {
      if (gone()) return;
      notice = { text: text, until: Date.now() + NOTICE_MS };
      clearTimeout(noticeTimer);
      noticeTimer = setTimeout(paint, NOTICE_MS + 50);
      paint();
    }

    function playing() { return Boolean(video && !video.paused && !video.ended); }

    function statusText() {
      var state = sitting.state;
      if (state === "thinking") {
        // The batch's own live step ("Reading your 3 notes on the subscription",
        // "Waiting for the subscription worker"), never a spinner and never the
        // upload's line from the render before.
        return sitting.status || "Your notes are being made into a new version.";
      }
      if (state === "rendering") {
        // The upload's own step while it is live ("Cutting and burning in your captions",
        // then the render's progress); before that, the batch's own.
        return (sitting.videoBusy && sitting.step) || sitting.status || "Your new version is being made.";
      }
      if (!takingNotes()) {
        // How it ended ("New version made from your 3 notes. 1 of them needs you.").
        return sitting.status || "These notes were handed to " + EDITOR + ". Open the notes again for new ones.";
      }
      if (voice === "off") return TYPED_ONLY;
      if (voice === "loading") return "Loading " + EDITOR + "'s voice";
      if (voice === "signin") {
        return EDITOR + "'s voice needs its own sign-in on this phone. Sign in, then come back. Typing still works.";
      }
      if (voice === "unavailable") {
        return EDITOR + "'s voice did not load" + (voiceWhy ? " (" + voiceWhy + ")" : "") + ". Typing still works.";
      }
      if (voice === "old") return OLD_VOICE;
      if (hold) {
        var at = clock(hold.t);
        if (voice === "ready") return "Listening at " + at;
        return "Connecting " + EDITOR + "'s voice. Keep holding: listening at " + at + " starts when it is ready.";
      }
      if (settling) {
        return (muteTimer ? "Finishing what you said at " : "Saving what you said at ") + clock(settling.h.t);
      }
      if (notice && notice.until > Date.now()) return notice.text;
      if (state === "closed") return CLOSED_ELSEWHERE;
      if (voice === "dropped") return DROPPED;
      if (voice === "failed") return (voiceWhy || EDITOR + "'s voice stopped").replace(/\.$/, "") + ". Hold to try again.";
      if (voice === "connecting") return "Connecting " + EDITOR + "'s voice...";
      if (playing()) return EDITOR + " stays quiet while the video plays. Pause, then hold to talk.";
      if (speaking) return EDITOR + " is answering out loud. Her answer is written on the note below.";
      return "Pause where something is wrong, then hold to talk.";
    }

    // The words of the note the status line is about: the one he holds, else the one being saved.
    function shownWords() {
      var owner = capture.on ? capture.owner : null;
      if (hold) return owner === hold ? capture.words() : "";
      if (settling && owner === settling.h) return capture.words();
      return "";
    }

    function paint() {
      if (gone()) return;
      var text = statusText();
      statusEl.textContent = text;
      statusEl.title = text;   // three lines are shown; the whole sentence is here
      var words = shownWords();
      var signin = voice === "signin";
      signinEl.hidden = !signin;
      wordsEl.hidden = signin;
      wordsEl.classList.toggle("is-empty", !words);
      wordsEl.textContent = words ? "“" + tail(words) + "”"
        : hold ? "Say what is wrong at " + clock(hold.t) + "."
        : "Your words show here while you hold.";
      var usable = takingNotes() && NO_HOLD.indexOf(voice) < 0;
      button.disabled = !usable && !hold;
      button.setAttribute("aria-pressed", hold ? "true" : "false");
      button.classList.toggle("is-holding", Boolean(hold));
      button.textContent = hold ? "Listening - let go when done"
        : voice === "dropped" || voice === "failed" ? "Hold to reconnect"
        : "Hold to talk";
    }

    function pendingOf(id) {
      if (awaited[id]) return "reading";
      if (unconfirmed[id]) return "unconfirmed";
      return "";
    }

    // This page is listening for that pin's words right now (a hold, its words landing,
    // or being saved), so a poll in between never says no words were caught.
    function listeningTo(id) {
      return Boolean(id && ((hold && hold.noteId === id) || (settling && settling.h.noteId === id)
        || savingWords[id]));
    }

    function drawNotes() {
      if (!opts.notes || gone()) return;
      var html = notesHtml(notes, pendingOf, listeningTo);
      if (html === notesKey) return;
      notesKey = html;
      opts.notes.innerHTML = html;
    }

    // --------------------------------------------------------- the sitting

    function take(payload) {
      if (!payload || gone()) return;
      var was = sitting.state;
      notes = payload.notes || [];
      sitting.state = payload.state || sitting.state;
      sitting.step = payload.video_step || "";
      sitting.videoBusy = VIDEO_BUSY.indexOf(payload.video_status) >= 0;
      sitting.status = statusOf(payload);
      var now = Date.now();
      Object.keys(awaited).forEach(function (id) {
        var row = notes.filter(function (n) { return n.id === id; })[0];
        if (!row || row.understood || WAITING.indexOf(row.state) < 0) { delete awaited[id]; return; }
        if (now - awaited[id] > AWAIT_MS) { delete awaited[id]; unconfirmed[id] = true; }
      });
      if (payload.render_ref !== undefined && (payload.render_ref || null) !== sitting.ref) {
        // The sitting is on another render now (reopened on a new edit, or its own new
        // version): the player loads payload.file_url, and pins go to that render.
        sitting.ref = payload.render_ref || null;
        if (opts.onStale) opts.onStale(sitting.ref, payload);
      }
      drawNotes();
      /* The notes left the sheet (being made, or made): nothing more can be said to the
         editor here, so the call (billed by the minute, silence too) ends once it has
         said so, and the screen may sleep (1-Oct final review). Taking notes again (a
         hand-back): the screen stays on, and the next hold starts a fresh call. */
      if (takingNotes()) {
        if (hangUp && !hangUp.force) cancelHangUp();
        lockScreen();
      } else if (call || wakeLock) {
        hangUpSoon(false);
      }
      if (opts.onSitting) opts.onSitting(payload);
      tellHandBack(WORKING.indexOf(was) >= 0);
      paint();
    }

    /* Handed back with nothing changed (the worker could not read the notes, the
       words moved...): the sitting takes notes again, and says why once. */
    function tellHandBack(wasWorking) {
      if (sitting.state !== "open" || !sitting.status) return;
      if (sitting.status === shownStatus && !wasWorking) return;
      shownStatus = sitting.status;
      say(sitting.status);
    }

    async function refresh() {
      clearTimeout(pollTimer);
      if (gone()) return;
      var asked = epoch;
      try {
        var payload = await api("/production/talk/" + sitting.id);
        // A read sent before the sitting was reopened on a new edit would move it back.
        if (asked === epoch) take(payload);
      } catch (error) { /* the next beat tries again */ }
      schedule();
    }

    function schedule() {
      clearTimeout(pollTimer);
      if (gone()) return;
      /* Fast while this page waits on something: a reading of a note it pinned, a hold,
         or the batch. A pin with no words that nothing listens for (an earlier visit's)
         is not waited on (1-Oct final review: it kept the 2 s poll going for good). */
      var waiting = Object.keys(awaited).length || hold || settling || WORKING.indexOf(sitting.state) >= 0;
      pollTimer = setTimeout(refresh, waiting ? POLL_FAST_MS : POLL_SLOW_MS);
    }

    function refreshSoon() {
      if (gone()) return;
      clearTimeout(pollTimer);
      pollTimer = setTimeout(refresh, 250);
    }

    async function reopen() {
      epoch += 1;
      try { take(await api("/production/recordings/" + sitting.upload + "/talk", { method: "POST" })); }
      catch (error) { say(error.message || "The notes could not be opened on the new edit."); }
    }

    // ------------------------------------------------------------- the call

    function startCall() {
      if (gone() || !global.KmVoice) return;
      // A call only while he can add notes: never on notes being made, or made.
      if (!takingNotes()) { voice = "idle"; paint(); return; }
      cancelHangUp();
      var token = {};
      callToken = token;
      stopSpeaking();
      voice = "connecting";
      try {
        call = global.KmVoice.start({
          seat: "tce",
          context: "video:" + sitting.upload,
          api: "live",
          greet: false,       // nothing talks until he does
          startMuted: true,   // and he talks only while he holds
          on: function (type, data) { if (callToken === token) onVoice(type, data || {}); }
        });
      } catch (error) {
        call = null;
        voice = "failed";
        voiceWhy = plainError(error && error.message || error);
      }
      /* 1-Oct final review: KM BOT's voice client before K1 has no mute and no quiet, and
         ignores greet:false and startMuted. Its call would be open the whole time, greet
         over the video and hear it, and every hold would throw before its pin. Not kept. */
      if (call && (typeof call.mute !== "function" || typeof call.quiet !== "function")) {
        var old = call;
        call = null;
        callToken = null;
        try { old.stop(); } catch (e) { /* already down */ }
        voice = "old";
        paint();
        return;
      }
      if (call && playing()) { call.quiet(true); }
      paint();
    }

    // ------------------------------------------------------- hanging up

    /* The notes left the sheet. The call ends once the editor has said so out loud
       (its words stopped), or after `hangUpWait` with nothing said; never mid-hold.
       `force` (Make tapped on the sheet): nothing more will be said, end it now. */
    function hangUpSoon(force) {
      if (hangUp && !force) return;
      cancelHangUp();
      hangUp = { since: Date.now(), spoke: speaking, force: Boolean(force), timer: null };
      checkHangUp();
    }

    function checkHangUp() {
      var h = hangUp;
      if (!h) return;
      clearTimeout(h.timer);
      h.timer = null;
      if (gone() || (takingNotes() && !h.force)) { hangUp = null; return; }
      if (speaking) h.spoke = true;
      var said = h.force || h.spoke || Date.now() - h.since >= hangUpWait;
      if (!hold && !settling && !speaking && said) {
        hangUp = null;
        endCall();
        return;
      }
      h.timer = setTimeout(checkHangUp, 250);
    }

    function cancelHangUp() {
      if (!hangUp) return;
      clearTimeout(hangUp.timer);
      hangUp = null;
    }

    // The call ends and the screen may sleep; the sitting is still read (its live step).
    function endCall() {
      var old = call;
      call = null;
      callToken = null;
      stopSpeaking();
      clearTimeout(muteTimer);
      muteTimer = null;
      if (old) { try { old.stop(); } catch (e) { /* already down */ } }
      if (NO_HOLD.indexOf(voice) < 0) voice = "idle";
      releaseScreen();
      paint();
    }

    function releaseScreen() {
      if (wakeLock) { wakeLock.release().catch(function () {}); wakeLock = null; }
    }

    // The call is gone (dropped, or ended by the voice service). The next hold starts
    // a new one on the same sitting.
    function lostCall(state, why) {
      var old = call;
      call = null;
      callToken = null;
      stopSpeaking();
      clearTimeout(muteTimer);
      muteTimer = null;
      voice = state;
      voiceWhy = why || "";
      notice = null;   // the drop is the news now
      if (old) { try { old.stop(); } catch (e) { /* already down */ } }
      // Read when the note ends with no words: the voice dropped, not his words.
      if (hold) hold.voiceLost = true;
      if (settling) settling.h.voiceLost = true;
      paint();
    }

    function stopSpeaking() {
      clearTimeout(speakingTimer);
      speakingTimer = null;
      speaking = false;
    }

    function onVoice(type, d) {
      // His words, first: they still land on his last note while the sheet closes.
      if (type === "hearing") {
        capture.hearing(d.text);
        if (settling && capture.owner === settling.h) armQuiet();
        paint();
        return;
      }
      if (type === "said") {
        if (!capture.said(d.text)) return;
        // Flushed: the voice handed his words over (or the call is closing). A note
        // being saved is complete now; a note being held is saved so far.
        if (settling && capture.owner === settling.h) { finishSettle(); return; }
        if (hold && capture.owner === hold) { saveWords(hold); paint(); }
        return;
      }
      if (gone()) return;   // the sheet is closed: nothing else is shown
      if (type === "connecting") { voice = "connecting"; paint(); return; }
      if (type === "ear") {
        if (d.open) {
          voice = "ready";
          if (hold) hold.heardReady = true;
        }
        paint();
        return;
      }
      // The editor talking. Its words are Live's paraphrase and are never drawn:
      // the written answer is the note row (understood).
      if (type === "partial") {
        // What is happening now beats the last one-off sentence ("Saved at 0:38").
        if (!speaking) { speaking = true; notice = null; }
        /* Live writes no end of turn while his mic is muted (it flushes only when he
           speaks again, or the call closes), so the editor's words stopping is the
           end of its answer (1-Oct review: the bar said it was answering for minutes). */
        clearTimeout(speakingTimer);
        speakingTimer = setTimeout(function () { stopSpeaking(); paint(); refreshSoon(); }, SPEAKING_QUIET_MS);
        paint();
        return;
      }
      if (type === "turn_end") { stopSpeaking(); paint(); refreshSoon(); return; }
      if (type === "tool") { refreshSoon(); return; }
      if (type === "error") {
        if (d.fatal) { lostCall("failed", plainError(d.text)); return; }
        if (/connection dropped/i.test(d.text || "")) { lostCall("dropped"); return; }
        if (d.text) say(plainError(d.text));
        return;
      }
      if (type === "closed" || type === "stopped") {
        if (voice !== "failed") lostCall("dropped");
        return;
      }
    }

    // ------------------------------------------------------------ the press

    function press() {
      // Closed on another screen counts: the pin opens those notes again.
      if (gone() || hold || !takingNotes()) return;
      if (NO_HOLD.indexOf(voice) >= 0) return;
      notice = null;
      var t = video ? Number(video.currentTime) || 0 : 0;
      hold = { t: t, at: Date.now(), noteId: null, failed: "", heardReady: voice === "ready" };
      if (video && !video.paused) video.pause();
      // He is talking again: the mic that was about to close after his last note stays open.
      clearTimeout(muteTimer);
      muteTimer = null;
      /* The last note's words can still be on their way (the transcript trails his
         voice): they stay on it until they stop, and this note's words start after
         them (1-Oct review: the end of one note landed on the next). */
      if (settling) handOff(); else capture.start(hold);
      // A dropped or stopped call comes back on this press, on the same sitting.
      if (!call) startCall();
      if (voice === "old") {
        // The press found the box's voice too old to hold: nothing was pinned.
        var none = hold;
        hold = null;
        if (capture.owner === none) capture.stop();
        paint();
        return;
      }
      if (call) {
        /* Nothing of the editor is heard while he holds. Quiet first, then hush: K1's
           quiet(false) plays an element that hush() paused, so hush then quiet(false)
           let the editor talk on over his "no, I meant..." (1-Oct review). */
        call.quiet(true);
        if (speaking) call.hush();   // he is talking over the editor: cut it off
        call.mute(false);
      }
      stopSpeaking();
      hold.pinning = pin(hold);
      paint();
    }

    async function pin(h) {
      try {
        var r = await api("/production/talk/" + sitting.id + "/notes", {
          method: "POST",
          // A hold: the editor's voice reads holds, never a typed note (1-Oct final review).
          body: { edit_s: Math.round(h.t * 100) / 100, render_ref: sitting.ref, by: "voice" }
        });
        h.noteId = r.note_id;
        awaited[r.note_id] = Date.now();
        if (r.note) notes = notes.concat([r.note]);
        drawNotes();
        refreshSoon();
        return r.note_id;
      } catch (error) {
        var detail = error.detail || {};
        if (error.status === 409 && detail.code === "stale_render") {
          // Re-rendered under the sheet (section 6): opening the notes again moves the
          // sitting and its notes onto the new edit, and take() hands the sheet the
          // new file to load.
          reopen();
          h.failed = "This is an older edit of the video. The new one is loading; pause and hold again.";
        } else {
          h.failed = error.message || "That note could not be saved.";
        }
        if (hold === h) {
          // Nowhere to put his words: stop listening now rather than after he lets go.
          hold = null;
          if (capture.owner === h) capture.stop();
          muteNow();
        }
        say(h.failed);
        if (detail.code === "not_open") refresh();
        return null;
      }
    }

    /* `keep`: the sheet is closing. What he was saying is kept, never taken back as a tap. */
    function release(keep) {
      if (!hold) return;
      var h = hold;
      hold = null;
      // The video is still paused: his answer may be heard now.
      if (call && !playing()) call.quiet(false);
      if (!keep && Date.now() - h.at < TAP_MS) {
        muteNow();
        if (capture.owner === h) capture.stop();
        h.pinning.then(function (id) { if (id) dropNote(id); });
        say("Keep the button held while you talk. Nothing was saved.");
        return;
      }
      /* The mic stays open a moment after he lets go, so the voice hears the end of his
         sentence (1-Oct review: KM BOT's scenario F lets go 1.5 s after the phrase; the
         sheet now does what the receipt proves). Play shuts it at once. */
      muteSoon();
      if (settling) finishSettle();   // the note before this one ends now
      if (capture.owner !== h) capture.start(h);
      settling = { h: h, quiet: null, max: null, maxAt: Date.now() + SETTLE_MAX_MS, handoff: false };
      settling.max = setTimeout(maxDue, SETTLE_MAX_MS);
      armQuiet();
      paint();
    }

    function muteSoon() {
      clearTimeout(muteTimer);
      muteTimer = setTimeout(function () {
        muteTimer = null;
        if (!hold && call) call.mute(true);
        paint();
      }, RELEASE_GRACE_MS);
    }

    function muteNow() {
      clearTimeout(muteTimer);
      muteTimer = null;
      if (call) call.mute(true);
    }

    function armQuiet() {
      if (!settling) return;
      clearTimeout(settling.quiet);
      settling.quiet = setTimeout(quietDue, settling.handoff ? HANDOFF_QUIET_MS : SETTLE_QUIET_MS);
    }

    // Pressed again before the last note's words stopped: they get a short while more.
    function handOff() {
      var s = settling;
      s.handoff = true;
      clearTimeout(s.max);
      s.max = setTimeout(maxDue, Math.max(0, Math.min(HANDOFF_MAX_MS, s.maxAt - Date.now())));
      armQuiet();
    }

    function quietDue() {
      if (!settling) return;
      // The mic is still open after he let go: more of his sentence may come.
      if (muteTimer) { armQuiet(); return; }
      settleNow();
    }

    function maxDue() { if (settling) settleNow(); }

    function settleNow() {
      if (!closing) { finishSettle(); return; }
      /* The sheet is closing. stop() hands over what the voice still holds as one
         "said" (its own flush), which lands on this note while the call's events
         still count; the call is stopped here, once. */
      var old = call;
      call = null;
      if (old) { try { old.stop(); } catch (e) { /* already down */ } }
      finishSettle();
    }

    function finishSettle() {
      var s = settling;
      if (!s) return;
      settling = null;
      clearTimeout(s.quiet);
      clearTimeout(s.max);
      var h = s.h;
      var words = capture.owner === h ? capture.words() : "";
      if (capture.owner === h) capture.stop();
      h.words = words;
      // A press that waited for these words to end: its own words start here.
      if (hold && !closing) capture.start(hold);
      var done = h.pinning.then(function (id) {
        if (!id) return null;
        if (words) return saveWords(h, true);
        if (saved[id]) return null;
        /* The sheet is closing and the settle is over: the quiet window ran out and the
           voice's own last flush (stop) gave nothing. The pin carries nothing of his, so
           it is taken back before the close is done (1-Oct final review: it kept the
           notes open for good, and later typed requests waited in them). */
        if (gone()) return dropQuietly(id);
        dropNote(id);
        say(h.voiceLost
          ? "The voice dropped while you talked at " + clock(h.t) + ", so that note was taken back. Hold to reconnect and say it again."
          : h.heardReady || voice === "ready"
            ? "No words were caught at " + clock(h.t) + ", so that note was taken back. Hold and say it again."
            : "The voice was still connecting, so nothing was heard at " + clock(h.t)
              + " and that note was taken back. Hold again.");
        return null;
      });
      // Closing: the call is let go once his words (or the empty pin) are dealt with, so
      // the sheet's close finds the notes as they really are.
      if (closing) done.then(finishClose, finishClose);
      else paint();
    }

    function dropQuietly(id) {
      delete awaited[id];
      return api("/production/talk/" + sitting.id + "/notes/" + id, { method: "PATCH", body: { drop: true } })
        .catch(function () { /* the close route then keeps the notes open, as before */ });
    }

    /* His words on the note, as the voice transcribed them. Saved when the voice
       flushes them mid-hold (it can hand them to the editor mid-sentence, and the
       editor reads the saved words), and again, whole, after he lets go. */
    function saveWords(h, final) {
      var words = final ? h.words : capture.words();
      if (!words) return Promise.resolve(null);
      return h.pinning.then(async function (id) {
        if (!id || saved[id] === words) return;
        saved[id] = words;
        savingWords[id] = true;
        try {
          var row = await api("/production/talk/" + sitting.id + "/notes/" + id, {
            method: "PATCH", body: { heard: words }
          });
          delete savingWords[id];
          if (gone()) return;   // saved; the sheet has nothing left to draw it on
          notes = notes.map(function (n) { return n.id === id ? row : n; });
          drawNotes();
          if (row && row.state === "rejected") {
            /* The editor took this hold as an instruction ("make it", his "yes"), or it
               was left out: his words are kept on it, and it is not a note (1-Oct final
               review: the bar said "Saved"). */
            delete awaited[id];
            var why = (row.result || {});
            say(norm(why.taken || why.left_out) || NOT_A_NOTE);
            refreshSoon();
            return;
          }
          if (final) say("Saved at " + clock(h.t) + ". " + EDITOR + " answers out loud, and in writing on the note.");
          refreshSoon();
        } catch (error) {
          delete saved[id];
          delete savingWords[id];
          say(error.message || "Your words at " + clock(h.t) + " could not be saved.");
        }
      });
    }

    async function dropNote(id) {
      delete awaited[id];
      try {
        await api("/production/talk/" + sitting.id + "/notes/" + id, { method: "PATCH", body: { drop: true } });
      } catch (error) {
        if (error.status !== 409) say(error.message);
      }
      refresh();
    }

    // ------------------------------------------------------------- the video

    function onPlay() {
      // He played it: he is not talking any more, and the editor goes quiet.
      if (hold) release();
      muteNow();   // the video's sound (his own voice) is never taken as a note
      if (call) { call.hush(); call.quiet(true); }
      stopSpeaking();
      paint();
    }
    function onPause() {
      // The answer may be heard again, but never while he holds: his press paused it.
      if (call && !gone() && !hold) call.quiet(false);
      paint();
    }

    // ----------------------------------------------------------- the screen

    var locking = false;
    async function lockScreen() {
      if (gone() || wakeLock || locking || !global.navigator.wakeLock || document.visibilityState !== "visible") return;
      // Only while he can give notes: being made takes minutes to hours, and he may put the phone down.
      if (!takingNotes() || hangUp) return;
      locking = true;
      try {
        var lock = await global.navigator.wakeLock.request("screen");
        if (gone() || !takingNotes() || hangUp) { lock.release().catch(function () {}); return; }
        wakeLock = lock;
        if (lock.addEventListener) lock.addEventListener("release", function () { if (wakeLock === lock) wakeLock = null; });
      } catch (error) { /* a phone in power saving can refuse; the sheet still works */ }
      finally { locking = false; }
    }

    function onVisible() {
      if (document.visibilityState !== "visible" || gone()) return;
      lockScreen();
      // Back from signing in to the voice in the other tab: try again.
      if (!typedOnly && (voice === "signin" || voice === "unavailable")) loadVoice();
      refresh();
    }

    // ------------------------------------------------------------ the wiring

    function onPointerDown(event) {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      event.preventDefault();
      try { button.setPointerCapture(event.pointerId); } catch (e) { /* synthetic pointer */ }
      press();
    }
    function onRelease() { release(false); }
    function onKeyDown(event) {
      if ((event.key === " " || event.key === "Enter") && !event.repeat) { event.preventDefault(); press(); }
    }
    function onKeyUp(event) {
      if (event.key === " " || event.key === "Enter") { event.preventDefault(); release(false); }
    }
    function noMenu(event) { event.preventDefault(); }
    function onNotesClick(event) {
      var x = event.target.closest && event.target.closest("[data-tv-drop]");
      if (!x) return;
      x.disabled = true;
      dropNote(x.getAttribute("data-tv-drop"));
    }

    button.addEventListener("pointerdown", onPointerDown);
    // pointercancel (the phone took the gesture over) is a release, not a discard:
    // what he said is kept.
    button.addEventListener("pointerup", onRelease);
    button.addEventListener("pointercancel", onRelease);
    button.addEventListener("lostpointercapture", onRelease);
    button.addEventListener("keydown", onKeyDown);
    button.addEventListener("keyup", onKeyUp);
    button.addEventListener("contextmenu", noMenu);
    button.addEventListener("click", noMenu);
    if (video) {
      video.addEventListener("play", onPlay);
      video.addEventListener("pause", onPause);
      video.addEventListener("ended", onPause);
    }
    if (opts.notes) opts.notes.addEventListener("click", onNotesClick);
    document.addEventListener("visibilitychange", onVisible);

    async function loadVoice() {
      voice = "loading";
      paint();
      var result = await loadVoiceClient(opts.voiceScript);
      if (gone()) return;
      if (!result.ok) {
        voice = result.status === 401 || result.status === 403 ? "signin" : "unavailable";
        voiceWhy = result.status ? "the voice answered " + result.status : "no connection to the voice";
        paint();
        return;
      }
      startCall();
    }

    function finishClose() {
      if (closed) return;
      closed = true;
      clearTimeout(muteTimer);
      muteTimer = null;
      var old = call;
      call = null;
      callToken = null;
      if (old) { try { old.stop(); } catch (e) { /* already down */ } }
      if (closing && closing.resolve) closing.resolve();
    }

    /* The sheet closes. The bar goes at once; the call ends once the last note's words
       have landed (1-Oct review: a close right after letting go took the note back, or
       saved it without its last words). Every note stays on the server. Returns a
       promise of the moment the call is let go. */
    function close() {
      if (closing) return closing.promise;
      if (hold) release(true);
      var resolve;
      closing = { promise: new Promise(function (r) { resolve = r; }) };
      closing.resolve = resolve;
      clearTimeout(pollTimer);
      clearTimeout(noticeTimer);
      cancelHangUp();
      stopSpeaking();
      button.removeEventListener("pointerdown", onPointerDown);
      button.removeEventListener("pointerup", onRelease);
      button.removeEventListener("pointercancel", onRelease);
      button.removeEventListener("lostpointercapture", onRelease);
      if (video) {
        video.removeEventListener("play", onPlay);
        video.removeEventListener("pause", onPause);
        video.removeEventListener("ended", onPause);
      }
      if (opts.notes) opts.notes.removeEventListener("click", onNotesClick);
      document.removeEventListener("visibilitychange", onVisible);
      if (wakeLock) { wakeLock.release().catch(function () {}); wakeLock = null; }
      root.innerHTML = "";
      if (!settling) finishClose();
      return closing.promise;
    }

    drawNotes();
    paint();
    tellHandBack(false);
    lockScreen();
    if (!typedOnly) loadVoice();
    schedule();

    return {
      close: close,
      refresh: refresh,
      // Make was tapped on the sheet: nothing more is said on this call, so it ends now
      // (after a hold or its words, if one is in progress) and the screen may sleep.
      hangUp: function () { hangUpSoon(true); },
      get voice() { return voice; },
      get holding() { return Boolean(hold); },
      get speaking() { return speaking; },
      get renderRef() { return sitting.ref; },
      // For the sheet's own "reload the new video" path: pins go to that render now.
      setRenderRef: function (ref) { sitting.ref = ref || null; }
    };
  }

  global.TceTalkVoice = {
    open: open,
    load: loadVoiceClient,
    Capture: Capture,
    noteView: noteView,
    notesHtml: notesHtml,
    clock: clock,
    plainError: plainError,
    VOICE_SCRIPT: VOICE_SCRIPT,
    DROPPED: DROPPED,
    VOICE_PROBLEM: VOICE_PROBLEM,
    OLD_VOICE: OLD_VOICE,
    CLOSED_ELSEWHERE: CLOSED_ELSEWHERE,
    RELEASE_GRACE_MS: RELEASE_GRACE_MS,
    SPEAKING_QUIET_MS: SPEAKING_QUIET_MS
  };
})(window);
