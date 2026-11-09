/* The Book (9-Nov-2026, T-19730). Ziv: "I will access it through TCE. There will be a
   book button. There will be an option to record a video... just like on TCE".

   Listening: a chapter is read one paragraph at a time. Each paragraph's narration comes
   from /api/v1/book/.../audio/<i> (a stock ElevenLabs voice, cached on the server); when
   the server says no narration may be bought yet (409, device_voice), this device's own
   voice reads it instead, which costs nothing. Pause stops at once; Play goes on from
   the same paragraph. Talk to the editor pauses and opens the book editor's call.

   Filming: the agent talk road Record without a script uses (POST a talk, PUT every
   MediaRecorder slice while he listens, POST finish), under the reserved name the
   server hands out ("_book_7" is "Book session, episode 7"). The narration is mixed
   into the recording, and finish carries each paragraph read as a "narrator" line, so
   the edit keeps the reading and never cuts it as a retake. Jennifer edits it (edit:
   true); Archived in the Library is one tap away as for every talk. Slices wait on
   this device until the server has them, exactly as the solo take's do. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const prefix = window.location.pathname.startsWith("/tce/") ? "/tce" : "";
  const apiV1 = `${prefix}/api/v1`;
  const DB_NAME = "tce-book-v1";
  const CAMERA_FLAG = "tce-camera-active";
  const SLICE_MS = 3000;
  const RETRY_MS = 4000;

  const supportedMime = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
    "video/mp4;codecs=h264,aac", "video/mp4",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  const state = {
    chapters: [], narration: null, seat: "tce",
    chapter: null, index: 0, playing: false, mode: "", audio: null, utterance: null, token: 0,
    film: null, sending: false, retryId: null,
  };

  /* ------------------------------------------------------------------ api */

  async function api(path, options = {}) {
    const response = await fetch(`${apiV1}${path}`, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body instanceof Blob ? {} : { "Content-Type": "application/json" }),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || `Request failed with ${response.status}`);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function status(text, bad = false) {
    const line = $("bookStatus");
    line.textContent = text || "";
    line.hidden = !text;
    line.classList.toggle("bad", Boolean(bad));
  }
  const top = (text) => { $("bookState").textContent = text; };

  /* ---------------------------------------------------------------- list */

  function chip(el, s, words) {
    el.className = `status-chip ${s}`;
    el.textContent = words;
  }

  function narrationLine(n) {
    if (!n) return "";
    if (n.on) return "Read by a stock ElevenLabs voice. What has been read once replays free.";
    const dollars = n.book_cost_usd ? ` (reading all ${n.book_chars.toLocaleString()} characters is about $${Number(n.book_cost_usd).toFixed(2)})` : "";
    return `Read by this device's own voice for now: the ElevenLabs voice is switched on only after you OK its cost${dollars}.`;
  }

  const isNew = (c) => c.group === "new";
  const label = (c) => (isNew(c) ? `Episode ${c.n}` : `Chapter ${c.n}`);
  const itemsWords = (items) => (items && items.length ? (items.length === 1 ? `item ${items[0]}` : `items ${items.join(", ")}`) : "");

  function chapterButton(c) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.chapter = String(c.n);
    b.innerHTML = `<span class="num"></span><span class="title"></span><span class="status-chip"></span><span class="length"></span>`;
    const where = [label(c), c.part, itemsWords(c.layout_items) ? `layout ${itemsWords(c.layout_items)}` : ""].filter(Boolean).join(" - ");
    b.querySelector(".num").textContent = where;
    b.querySelector(".title").textContent = c.title;
    chip(b.querySelector(".status-chip"), c.status, c.status_words);
    b.querySelector(".length").textContent = c.status === "to_write"
      ? "Not written yet"
      : `About ${c.minutes} min read aloud${c.version > 1 ? `, version ${c.version}` : ""}`;
    if (c.status === "to_write") {
      b.classList.add("unwritten");
      if (c.layout_text) {
        const peek = document.createElement("span");
        peek.className = "layout-peek";
        peek.textContent = c.layout_text;
        b.appendChild(peek);
      }
    }
    b.addEventListener("click", () => go(c.n));
    li.appendChild(b);
    return li;
  }

  async function loadList() {
    const data = await api("/book/chapters");
    state.chapters = data.chapters;
    state.narration = data.narration;
    state.seat = data.editor_seat || "tce";
    $("narrationNote").textContent = narrationLine(data.narration);
    const fresh = data.chapters.filter(isNew);
    const written = data.chapters.filter((c) => !isNew(c));
    const list = $("chapterList");
    const fold = $("writtenList");
    list.textContent = "";
    fold.textContent = "";
    // No new episode in the record yet: everything is one list, as before.
    const grouped = fresh.length > 0;
    for (const c of grouped ? fresh : data.chapters) list.appendChild(chapterButton(c));
    if (grouped) for (const c of written) fold.appendChild(chapterButton(c));
    $("newHead").hidden = !grouped;
    $("writtenFold").hidden = !grouped || !written.length;
    if (grouped) {
      const approvedW = written.filter((c) => c.status === "approved").length;
      $("writtenSummary").textContent = `Part one, already written (${written.length} chapters, ${approvedW} approved)`;
      const toWrite = fresh.filter((c) => c.status === "to_write").length;
      const approvedN = fresh.filter((c) => c.status === "approved").length;
      const ready = fresh.length - toWrite - approvedN;
      $("progressLine").textContent = `${fresh.length - toWrite} of ${fresh.length} written: ${ready} to check, ${approvedN} approved, ${toWrite} still to write.`;
      $("progressLine").hidden = false;
      top(`${fresh.length - toWrite} of ${fresh.length} new episodes written, ${approvedN} approved`);
    } else {
      $("progressLine").hidden = true;
      const approved = data.chapters.filter((c) => c.status === "approved").length;
      top(`${data.chapters.length} chapters, ${approved} approved`);
    }
    if (!data.chapters.length) status("No chapters are in the Book yet: the manuscript was not found on the server.", true);
    return data;
  }

  /* -------------------------------------------------------------- chapter */

  async function openChapter(n) {
    stop();
    const c = await api(`/book/chapters/${n}`);
    state.chapter = c;
    state.index = 0;
    state.narration = c.narration;
    state.seat = c.editor_seat || state.seat;
    $("chapterPart").textContent = [c.part, c.version > 1 ? `version ${c.version}` : ""].filter(Boolean).join(" - ");
    $("chapterTitle").textContent = `${label(c)}: ${c.title}`;
    $("bookTitle").textContent = label(c);
    $("approveButton").textContent = isNew(c) ? "Approve this episode" : "Approve this chapter";
    $("layoutBox").hidden = !c.layout_text;
    $("layoutSummary").textContent = `From your layout${itemsWords(c.layout_items) ? `, ${itemsWords(c.layout_items)}` : ""}`;
    $("layoutText").textContent = c.layout_text || "";
    $("notWritten").hidden = c.status !== "to_write";
    showStatus(c.status, c.status_words);
    const box = $("paragraphs");
    box.textContent = "";
    c.paragraphs.forEach((text, i) => {
      const p = document.createElement("p");
      p.textContent = text;
      p.dataset.i = String(i);
      p.addEventListener("click", () => { state.index = i; play(); });
      box.appendChild(p);
    });
    $("prevChapter").disabled = c.previous == null;
    $("nextChapter").disabled = c.next == null;
    $("listView").hidden = true;
    $("chapterView").hidden = false;
    const readable = c.paragraphs.length > 0;
    $("player").hidden = !readable;
    document.body.classList.toggle("has-player", readable);
    top(readable ? `${c.paragraphs.length} paragraphs, ${narrationShort()}` : "Not written yet");
    mark();
    window.scrollTo(0, 0);
  }

  const narrationShort = () => (state.narration && state.narration.on ? "stock voice" : "device voice");

  function showStatus(s, words) {
    chip($("chapterStatus"), s, words);
    $("approveButton").hidden = s === "approved" || s === "to_write";
    $("unapproveButton").hidden = s !== "approved";
  }

  async function setStatus(s) {
    if (!state.chapter) return;
    const n = state.chapter.n;
    $("approveButton").disabled = true;
    $("unapproveButton").disabled = true;
    try {
      const row = await api(`/book/chapters/${n}/status`, { method: "POST", body: JSON.stringify({ status: s }) });
      state.chapter.status = row.status;
      showStatus(row.status, row.status_words);
      const name = label(state.chapter);
      status(row.status === "approved" ? `${name} is approved.` : `${name} is back in review.`);
    } catch (error) {
      status(`That did not save: ${error.message}`, true);
    } finally {
      $("approveButton").disabled = false;
      $("unapproveButton").disabled = false;
    }
  }

  function mark() {
    const nodes = $("paragraphs").children;
    for (let i = 0; i < nodes.length; i += 1) {
      nodes[i].classList.toggle("now", i === state.index);
      nodes[i].classList.toggle("read", i < state.index);
    }
    const now = nodes[state.index];
    if (now && state.playing) now.scrollIntoView({ block: "center", behavior: "smooth" });
    $("playButton").innerHTML = state.playing ? "&#10074;&#10074;" : "&#9654;";
    $("playButton").setAttribute("aria-label", state.playing ? "Pause" : "Play");
  }

  /* -------------------------------------------------------------- reading */

  function stop() {
    state.token += 1;
    state.playing = false;
    if (state.audio) { state.audio.pause(); }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    state.utterance = null;
    if (state.chapter) mark();
  }

  function audioElement() {
    if (state.audio) return state.audio;
    const audio = new Audio();
    audio.preload = "auto";
    audio.crossOrigin = "use-credentials";
    state.audio = audio;
    return audio;
  }

  function deviceSpeak(text, token) {
    return new Promise((resolve, reject) => {
      if (!window.speechSynthesis) { reject(new Error("This browser has no voice to read with")); return; }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-US";
      u.rate = 1;
      u.onend = () => resolve();
      u.onerror = (e) => (e.error === "interrupted" || e.error === "canceled" ? resolve() : reject(new Error(e.error || "speech failed")));
      state.utterance = u;
      if (token === state.token) window.speechSynthesis.speak(u);
    });
  }

  async function readParagraph(i, token) {
    const text = state.chapter.paragraphs[i];
    filmLine(text);
    const url = `${apiV1}/book/chapters/${state.chapter.n}/audio/${i}`;
    if (state.narration && state.narration.on) {
      const response = await fetch(url, { credentials: "same-origin" });
      if (token !== state.token) return;
      if (response.ok) {
        const blob = await response.blob();
        const audio = audioElement();
        if (audio.dataset.src) URL.revokeObjectURL(audio.dataset.src);
        audio.dataset.src = URL.createObjectURL(blob);
        audio.src = audio.dataset.src;
        mixNarration();
        state.mode = "voice";
        await new Promise((resolve, reject) => {
          audio.onended = () => resolve();
          audio.onerror = () => reject(new Error("The narration did not play"));
          audio.play().catch(reject);
        });
        return;
      }
      const data = await response.json().catch(() => ({}));
      if (!data.device_voice) throw new Error(data.detail || `Narration failed with ${response.status}`);
      state.narration = { ...state.narration, on: false };
      status(data.detail || "This device reads it aloud.");
    }
    state.mode = "device";
    await deviceSpeak(text, token);
  }

  async function play() {
    if (!state.chapter) return;
    if (state.playing) { stop(); top("Paused"); return; }
    const token = ++state.token;
    state.playing = true;
    // A paused stock-voice paragraph goes on from where it stopped.
    if (state.mode === "voice" && state.audio && state.audio.src && !state.audio.ended && state.audio.currentTime > 0 && state.audio.dataset.i === String(state.index)) {
      mark();
      top(`Reading paragraph ${state.index + 1}`);
      try {
        await new Promise((resolve, reject) => {
          state.audio.onended = () => resolve();
          state.audio.onerror = () => reject(new Error("The narration did not play"));
          state.audio.play().catch(reject);
        });
        if (token !== state.token) return;
        state.index += 1;
      } catch (error) { status(error.message, true); stop(); return; }
    }
    while (token === state.token && state.index < state.chapter.paragraphs.length) {
      mark();
      top(`Reading paragraph ${state.index + 1} of ${state.chapter.paragraphs.length}`);
      try {
        if (state.audio) state.audio.dataset.i = String(state.index);
        await readParagraph(state.index, token);
      } catch (error) {
        status(`Reading stopped: ${error.message}`, true);
        stop();
        return;
      }
      if (token !== state.token) return;
      state.index += 1;
    }
    if (token === state.token) {
      state.playing = false;
      state.index = Math.max(0, state.chapter.paragraphs.length - 1);
      mark();
      top("End of the chapter");
      status(state.chapter.status === "approved" ? "End of the chapter." : "End of the chapter. Approve it when it reads right.");
    }
  }

  function step(delta) {
    if (!state.chapter) return;
    const was = state.playing;
    stop();
    state.mode = "";
    state.index = Math.min(Math.max(0, state.index + delta), state.chapter.paragraphs.length - 1);
    mark();
    if (was) play();
  }

  function talk() {
    stop();
    top("Paused for the editor");
    // The book editor's own seat opens on the chapter (its "book" context takes the number
    // padded to six digits, as a seat context id must be); TCE's general seat, used until
    // that one exists, has no book context and opens on its default.
    const n = state.chapter ? String(state.chapter.n).padStart(6, "0") : "";
    const context = state.seat !== "tce" && n ? `book:${n}` : "default";
    const href = `/voice?seat=${encodeURIComponent(state.seat)}&context=${context}`;
    window.open(href, "_blank", "noopener");
    status(state.film ? "The editor opens in a new tab. Filming goes on here; come back and press Play to carry on."
      : "The editor opens in a new tab. Come back and press Play to carry on.");
  }

  /* -------------------------------------------------------------- filming */

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("pieces")) db.createObjectStore("pieces", { keyPath: "key" });
        if (!db.objectStoreNames.contains("takes")) db.createObjectStore("takes", { keyPath: "talkId" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  async function store(name, mode, work) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(name, mode);
      const out = work(tx.objectStore(name));
      tx.oncomplete = () => { db.close(); resolve(out && out.result !== undefined ? out.result : undefined); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }
  const putPiece = (piece) => store("pieces", "readwrite", (s) => s.put(piece));
  const dropPiece = (key) => store("pieces", "readwrite", (s) => s.delete(key));
  const allPieces = () => store("pieces", "readonly", (s) => s.getAll());
  const putTake = (take) => store("takes", "readwrite", (s) => s.put(take));
  const dropTake = (talkId) => store("takes", "readwrite", (s) => s.delete(talkId));
  const allTakes = () => store("takes", "readonly", (s) => s.getAll());

  async function sendAll() {
    if (state.sending) return;
    state.sending = true;
    clearTimeout(state.retryId);
    let failed = null;
    try {
      const pieces = (await allPieces()).sort((a, b) => (a.talkId === b.talkId ? a.sequence - b.sequence : a.at - b.at));
      for (const piece of pieces) {
        try {
          await api(`/production/agent-talks/${encodeURIComponent(piece.talkId)}/chunks/${piece.sequence}`, { method: "PUT", body: piece.blob });
          await dropPiece(piece.key);
        } catch (error) {
          if (error.status === 409 || error.status === 404) await dropPiece(piece.key);
          else { failed = error; break; }
        }
      }
      if (!failed) {
        const left = await allPieces();
        for (const take of await allTakes()) {
          if (!take.done || left.some((p) => p.talkId === take.talkId)) continue;
          try {
            const row = await api(`/production/agent-talks/${encodeURIComponent(take.talkId)}/finish`, {
              method: "POST",
              body: JSON.stringify({ ended_at: take.endedAt, duration_ms: take.durationMs, transcript: take.lines || [], edit: true }),
            });
            await dropTake(take.talkId);
            status(row.status || `${take.title || "The book session"} is in your Library and Jennifer is editing it.`);
          } catch (error) { failed = error; }
        }
      }
    } catch (error) {
      failed = error;
    } finally {
      state.sending = false;
    }
    if (failed) {
      status(`Sending paused (${failed.message}). Trying again in a few seconds; nothing is lost.`, true);
      state.retryId = setTimeout(sendAll, RETRY_MS);
    }
  }

  /* Each paragraph read while filming becomes a narrator line, timed on the recording's clock. */
  function filmLine(text) {
    const film = state.film;
    if (!film) return;
    film.lines.push({ who: "narrator", text, t_ms: Date.now() - film.startedAt });
    putTake({ ...film.take, lines: film.lines }).catch(() => {});
  }

  /* The narration plays through the recording's mix as well as the speaker, so the
     reading is in the video at full quality. The device voice cannot be routed: the
     microphone hears it from the speaker instead. */
  function mixNarration() {
    const film = state.film;
    const audio = state.audio;
    if (!film || !audio || audio.dataset.mixed === "1") return;
    try {
      const source = film.ctx.createMediaElementSource(audio);
      source.connect(film.mix);
      source.connect(film.ctx.destination);
      audio.dataset.mixed = "1";
    } catch (_) { /* already routed or not allowed: the microphone hears it */ }
  }

  function clock(ms) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  async function startFilm() {
    if (!supportedMime) { status("This browser cannot record video. Try Chrome or Safari.", true); return; }
    $("filmButton").disabled = true;
    try {
      const camera = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1080 }, height: { ideal: 1920 } },
        audio: { echoCancellation: false, noiseSuppression: true },
      });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const mix = ctx.createMediaStreamDestination();
      ctx.createMediaStreamSource(camera).connect(mix);
      const stream = new MediaStream([...camera.getVideoTracks(), ...mix.stream.getAudioTracks()]);
      const session = await api("/book/sessions", { method: "POST", body: "{}" });
      const startedAt = new Date();
      const talk = await api("/production/agent-talks", {
        method: "POST",
        body: JSON.stringify({ agent: session.agent, call_id: crypto.randomUUID(), started_at: startedAt.toISOString(), mime: supportedMime }),
      });
      const take = { talkId: talk.talk_id, title: session.title, done: false, startedAt: startedAt.toISOString(), lines: [] };
      await putTake(take);
      const recorder = new MediaRecorder(stream, { mimeType: supportedMime, videoBitsPerSecond: 6000000, audioBitsPerSecond: 128000 });
      state.film = { camera, ctx, mix, stream, recorder, take, lines: [], sequence: 0, startedAt: Date.now(), timer: 0, wakeLock: null };
      // A narration element routed before filming plays only to the speaker; a fresh one joins the mix.
      if (state.audio) { state.audio.pause(); state.audio = null; state.mode = ""; }
      recorder.ondataavailable = async (event) => {
        if (!event.data || !event.data.size || !state.film) return;
        const sequence = state.film.sequence++;
        await putPiece({ key: `${take.talkId}:${sequence}`, talkId: take.talkId, sequence, blob: event.data, at: Date.now() });
        sendAll();
      };
      recorder.start(SLICE_MS);
      try { localStorage.setItem(CAMERA_FLAG, String(Date.now())); } catch (_) { /* private mode */ }
      try { state.film.wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { /* none */ }
      $("filmCamera").srcObject = camera;
      $("filmCamera").play().catch(() => {});
      $("filmLabel").textContent = session.title;
      $("filmStrip").hidden = false;
      $("filmButton").setAttribute("aria-pressed", "true");
      $("filmButton").textContent = "Filming";
      state.film.timer = setInterval(() => { $("filmClock").textContent = clock(Date.now() - state.film.startedAt); }, 250);
      status(`Filming ${session.title}. Press Play to start the reading.`);
      if (state.playing) { const i = state.index; stop(); state.index = i; play(); }
    } catch (error) {
      status(`Filming did not start: ${error.message}`, true);
    } finally {
      $("filmButton").disabled = false;
    }
  }

  async function doneFilm() {
    const film = state.film;
    if (!film) return;
    $("filmDone").disabled = true;
    stop();
    const durationMs = Date.now() - film.startedAt;
    await new Promise((resolve) => {
      if (film.recorder.state === "inactive") { resolve(); return; }
      film.recorder.addEventListener("stop", () => setTimeout(resolve, 0), { once: true });
      film.recorder.stop();
    });
    clearInterval(film.timer);
    film.camera.getTracks().forEach((t) => t.stop());
    try { await film.wakeLock?.release(); } catch (_) { /* gone */ }
    try { film.ctx.close(); } catch (_) { /* closed */ }
    try { localStorage.removeItem(CAMERA_FLAG); } catch (_) { /* private mode */ }
    await putTake({ ...film.take, lines: film.lines, done: true, endedAt: new Date().toISOString(), durationMs });
    state.film = null;
    state.audio = null;
    state.mode = "";
    $("filmCamera").srcObject = null;
    $("filmStrip").hidden = true;
    $("filmDone").disabled = false;
    $("filmButton").setAttribute("aria-pressed", "false");
    $("filmButton").textContent = "Film this session";
    status("Sending the last parts. You can leave this page; it finishes the next time the Book opens.");
    sendAll();
  }

  /* ------------------------------------------------------------- routing */

  function n_from_path() {
    const m = window.location.pathname.match(/\/book\/(\d+)\/?$/);
    return m ? Number(m[1]) : null;
  }

  async function go(n, push = true) {
    try {
      if (n == null) {
        stop();
        state.chapter = null;
        $("chapterView").hidden = true;
        $("player").hidden = true;
        document.body.classList.remove("has-player");
        $("listView").hidden = false;
        $("bookTitle").textContent = "Book";
        if (push) history.pushState({}, "", `${prefix}/book`);
        await loadList();
      } else {
        if (push) history.pushState({}, "", `${prefix}/book/${n}`);
        await openChapter(n);
      }
    } catch (error) {
      top("Could not open");
      status(`The book did not open: ${error.message}`, true);
    }
  }

  $("bookBack").addEventListener("click", (event) => {
    if (state.chapter) { event.preventDefault(); go(null); }
  });
  $("bookBack").setAttribute("href", `${prefix}/today`);
  $("playButton").addEventListener("click", play);
  $("backPara").addEventListener("click", () => step(-1));
  $("nextPara").addEventListener("click", () => step(1));
  $("talkButton").addEventListener("click", talk);
  $("approveButton").addEventListener("click", () => setStatus("approved"));
  $("unapproveButton").addEventListener("click", () => setStatus("in_review"));
  $("prevChapter").addEventListener("click", () => state.chapter && state.chapter.previous != null && go(state.chapter.previous));
  $("nextChapter").addEventListener("click", () => state.chapter && state.chapter.next != null && go(state.chapter.next));
  $("filmButton").addEventListener("click", () => (state.film ? doneFilm() : startFilm()));
  $("filmDone").addEventListener("click", doneFilm);
  window.addEventListener("popstate", () => go(n_from_path(), false));
  window.addEventListener("online", sendAll);
  window.addEventListener("pagehide", () => { try { localStorage.removeItem(CAMERA_FLAG); } catch (_) { /* */ } });
  $("filmButton").hidden = !supportedMime;

  go(n_from_path(), false).then(() => {
    // A session from an earlier visit that never finished sending is finished now.
    allPieces().then((left) => allTakes().then(async (takes) => {
      for (const take of takes.filter((t) => !t.done)) await putTake({ ...take, done: true, endedAt: new Date().toISOString() });
      if (left.length || takes.length) { status(`Sending a book session from earlier: ${left.length} parts left.`); sendAll(); }
    })).catch(() => {});
  });
})();
