// Pure helpers for the hook chooser. They live outside the studio closure so the
// unit tests can load them in Node without a DOM; nothing here touches the page.
function payoffPhrase(phrases, phraseId) {
  const list = Array.isArray(phrases) ? phrases : [];
  const index = Number(String(phraseId || "").slice(1)) - 1;
  return Number.isInteger(index) && index >= 0 && index < list.length ? list[index] : "";
}

function hookChooserModel(idea, context = {}) {
  const options = Array.isArray(idea?.hook_options) ? idea.hook_options : [];
  const phrases = Array.isArray(idea?.script_phrases) ? idea.script_phrases : [];
  const currentId = idea?.selected_hook_id || options[0]?.id || null;
  const sessionStatus = context.sessionStatus || idea?.active_session_status || null;
  const clipCount = Number(context.clipCount || 0);
  // A take set with clips is bound to this exact packet version: the opening is
  // frozen for it. A draft session (opened, nothing recorded) does not lock.
  const locked = Boolean(context.recorderActive) || clipCount > 0
    || ["recording", "finalizing"].includes(sessionStatus);
  const show = idea?.packet_format === "v2" && options.length >= 2 && !locked;
  return {
    show,
    locked,
    currentId,
    reason: locked ? `Opening locked: this take set has clips on v${idea?.packet_version ?? "?"}.` : "",
    options: options.map((hook, index) => ({
      id: hook.id,
      text: hook.text,
      question: hook.question,
      rationale: hook.rationale,
      payoff: payoffPhrase(phrases, hook.payoff_phrase_id),
      rank: index + 1,
      recommended: index === 0,
      current: hook.id === currentId,
    })),
  };
}

function packetToIdea(idea, packet) {
  // The choose-hook response is packet_to_json (id/version); the queue speaks
  // packet_id/packet_version. The new version has no session of its own yet.
  return {
    ...idea,
    packet_id: packet.id,
    packet_version: packet.version,
    bullets: packet.bullets || [],
    script_phrases: packet.script_phrases || [],
    hook_options: packet.hook_options || [],
    selected_hook_id: packet.selected_hook_id,
    beats: packet.beats || [],
    interviewer_prompt: packet.interviewer_prompt ?? idea.interviewer_prompt ?? null,
    packet_format: packet.packet_format || idea.packet_format,
    active_session_id: null,
    active_session_status: null,
  };
}

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  /* Shared with the editorial workspace, which can hold the microphone for
     voice on a different page. Set while a clip is being captured, cleared the
     moment the recorder is released, and cleared on unload so a crashed tab
     cannot leave voice locked out forever. */
  const CAMERA_FLAG = "tce-camera-active";
  const cameraFlag = (on) => {
    try {
      if (on) localStorage.setItem(CAMERA_FLAG, String(Date.now()));
      else localStorage.removeItem(CAMERA_FLAG);
    } catch { /* private mode */ }
  };
  const pathPrefix = window.location.pathname.startsWith("/tce/") ? "/tce" : "";
  const apiV1 = `${pathPrefix}/api/v1`;
  const state = {
    ideas: [], idea: null, session: null, stream: null, recorder: null, clip: null,
    mode: "points", sequence: 0, startedAt: 0, activeStartedAt: 0, activeMs: 0,
    timerId: null, pendingWrites: [], pendingSync: new Map(), takeMarkers: [],
    wakeLock: null, pendingIdea: null, textSize: 1,
    sessionPending: null, sessionPendingFor: null,
    rawStream: null, cameraReport: null,
    // Clips that were stopped and are still sending their last pieces. Finish
    // waits for every one of them before it builds the video.
    finalizing: new Set(), cameraSource: null, unfinished: [],
  };
  const supportedMime = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
    "video/mp4;codecs=h264,aac", "video/mp4",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  function setStudioMode(active) {
    document.body.classList.toggle("in-studio", Boolean(active));
    // The nav is hidden in the studio and the house changes meaning with it.
    if (typeof paintHomeButton === "function") paintHomeButton();
  }

  // While the camera runs the screen is video on top and the words below: the
  // header, the title and the full control bar go, and only Pause and Finish
  // stay, as two small buttons. Defined long ago and never called until 22-Sep.
  function setRecordingChrome(active) {
    const view = document.getElementById("studioView");
    if (view) view.classList.toggle("is-recording", Boolean(active));
    document.body.classList.toggle("rec-live", Boolean(active));
    if (state.idea && state.mode === "points") renderReader();
  }

  function showNotice(message, timeout = 4200) {
    const notice = $("notice");
    notice.textContent = message;
    notice.hidden = false;
    clearTimeout(showNotice.timer);
    showNotice.timer = setTimeout(() => { notice.hidden = true; }, timeout);
  }

  async function api(path, options = {}) {
    const response = await fetch(`${apiV1}/production${path}`, {
      credentials: "same-origin",
      ...options,
      headers: { ...(options.body instanceof Blob ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
    return data;
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("tce-recording-v1", 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        const store = db.createObjectStore("chunks", { keyPath: "key" });
        store.createIndex("clip", "clipId", { unique: false });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function idbPut(record) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("chunks", "readwrite");
      tx.objectStore("chunks").put(record);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  async function idbForClip(clipId) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const request = db.transaction("chunks").objectStore("chunks").index("clip").getAll(clipId);
      request.onsuccess = () => resolve(request.result.sort((a, b) => a.sequence - b.sequence));
      request.onerror = () => reject(request.error);
    });
  }

  async function idbDeleteClip(clipId) {
    const db = await openDb();
    const rows = await idbForClip(clipId);
    return new Promise((resolve, reject) => {
      const tx = db.transaction("chunks", "readwrite");
      rows.forEach((row) => tx.objectStore("chunks").delete(row.key));
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  async function sha256(blob) {
    const bytes = await blob.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function updateSyncLabel() {
    const pending = state.pendingSync.size;
    $("syncState").textContent = navigator.onLine
      ? (pending ? `Saving ${pending}` : "Ready")
      : "No signal: kept on this phone";
    updateSessionLabels();
  }

  async function syncChunk(record) {
    const token = `${record.clipId}:${record.sequence}`;
    if (state.pendingSync.has(token)) return state.pendingSync.get(token);
    const work = (async () => {
      try {
        await api(`/recording-clips/${record.clipId}/chunks/${record.sequence}`, {
          method: "PUT", body: record.blob, headers: { "Content-Type": record.blob.type || "application/octet-stream", "X-Chunk-Sha256": record.sha256 },
        });
        record.uploaded = true;
        await idbPut(record);
        return true;
      } catch (error) {
        record.uploaded = false;
        await idbPut(record);
        return false;
      } finally {
        state.pendingSync.delete(token);
        updateSyncLabel();
      }
    })();
    state.pendingSync.set(token, work);
    updateSyncLabel();
    return work;
  }

  async function retryStoredChunks(clipId = null) {
    if (!navigator.onLine) return false;
    const sessionClips = (state.session?.clips || []).map((clip) => clip.id);
    const activeClip = state.clip?.id ? [state.clip.id] : [];
    const clips = clipId ? [clipId] : [...new Set([...sessionClips, ...activeClip])];
    const jobs = [];
    for (const id of clips) {
      const rows = await idbForClip(id);
      rows.filter((row) => !row.uploaded).forEach((row) => jobs.push(syncChunk(row)));
    }
    const result = await Promise.all(jobs);
    return result.every(Boolean);
  }

  function renderQueue() {
    const queue = $("queue");
    queue.replaceChildren();
    $("emptyQueue").hidden = state.ideas.length > 0;
    state.ideas.forEach((idea, index) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "idea-card";
      card.innerHTML = `<strong></strong><span></span><div class="idea-meta"></div>`;
      card.querySelector("strong").textContent = idea.title;
      card.querySelector("span").textContent = idea.big_idea;
      const status = idea.active_session_id ? `Continue take set ${idea.active_session_status}` : "Start a new take set";
      card.querySelector(".idea-meta").textContent = `${index + 1} of ${state.ideas.length} · ${status}`;
      card.addEventListener("click", () => chooseIdea(idea));
      queue.appendChild(card);
    });
  }

  async function loadQueue() {
    try {
      const data = await api("/recording-queue");
      state.ideas = data.ideas || [];
      renderQueue();
      $("syncState").textContent = `${state.ideas.length} ready script${state.ideas.length === 1 ? "" : "s"}`;
    } catch (error) {
      $("syncState").textContent = "Could not load scripts";
      showNotice(error.message);
    }
  }

  function selectedHook(idea) {
    return (idea.hook_options || []).find((hook) => hook.id === idea.selected_hook_id) || idea.hook_options?.[0];
  }

  function renderReader() {
    const idea = state.idea;
    if (!idea) return;
    const reader = $("reader");
    const items = state.mode === "points" ? idea.bullets : idea.script_phrases;
    reader.className = `reader ${state.mode}`;
    reader.replaceChildren();
    // The opening is the first thing he says, so in Points it is the first line,
    // not a panel taking a third of the screen. The full script already starts
    // with it (choosing an opening rewrites the first spoken phrase). When the
    // chosen opening IS the first point almost word for word - which is what
    // choosing the recommended one usually gives - the two are one line, not the
    // same sentence printed twice.
    const hook = state.mode === "points" ? selectedHook(idea) : null;
    const merged = Boolean(hook && items.length && sameLine(hook.text, items[0]));
    if (hook && !merged) reader.appendChild(openingLine(idea, hook.text, "points-opening"));
    items.forEach((text, index) => {
      const line = document.createElement("p");
      line.className = "reader-line";
      line.id = `${state.mode}-${index}`;
      // Points keep their number; spoken phrases do not - "p028" was noise
      // to read past while talking.
      if (state.mode === "points") {
        if (merged && index === 0) {
          reader.appendChild(openingLine(idea, text, "points-0"));
          return;
        }
        const label = document.createElement("span");
        label.className = "reader-index";
        label.textContent = `Point ${index + 1}`;
        line.appendChild(label);
      }
      line.appendChild(document.createTextNode(text));
      reader.appendChild(line);
    });
    const tail = document.createElement("div");
    tail.className = "reader-tail";
    tail.setAttribute("aria-hidden", "true");
    reader.appendChild(tail);
    const saved = Number(localStorage.getItem(`tce-reader-${idea.packet_id}-${state.mode}`) || 0);
    requestAnimationFrame(() => { reader.scrollTop = saved; syncScrollRail(); });
  }

  /* Two lines are the same line when one starts with the other: the opening and
     the first point differ only by a trailing clause ("...on the phone." against
     "...on the phone after the event"). Unicode aware, so a Hebrew script is
     compared, not emptied. */
  function sameLine(a, b) {
    const flat = (text) => String(text || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    const one = flat(a);
    const two = flat(b);
    if (!one || !two) return false;
    return one.startsWith(two) || two.startsWith(one);
  }

  function openingLine(idea, text, id) {
    const line = document.createElement("p");
    line.className = "reader-line opening";
    // Merged into point 1 it IS point 1, so it answers to that point's jump
    // button; standing on its own it needs an id of its own, not a second
    // "points-0" that would swallow the jump to the first point.
    line.id = id;
    const label = document.createElement("span");
    label.className = "reader-index";
    label.textContent = "Opening";
    line.append(label, document.createTextNode(text));
    const recording = Boolean(state.recorder && state.recorder.state !== "inactive");
    if ((idea.hook_options || []).length >= 2 && !state.hookLock && !recording) {
      const change = document.createElement("button");
      change.type = "button";
      change.className = "hook-change opening-change";
      change.textContent = "Change";
      change.addEventListener("click", () => openHookChooser(idea));
      line.appendChild(change);
    }
    return line;
  }

  /* THE POINT NUMBERS PAGE (24-Sep): "if there are more than 5 the sixth one is
     an arrow for the next batch of points and if I click it the top number
     changes to up button". The column holds as many round buttons as fit its
     height, six at most: page one is 1..5 then a down arrow; later pages start
     with an up arrow. A short column (split screen) simply pages sooner rather
     than cutting buttons off. */
  const BEAT_SLOT = 52; // a 42px button plus its gap
  function beatSlots(rail) {
    const room = rail.clientHeight - 28;
    // n buttons take n slots less one gap.
    const fit = room > 0 ? Math.floor((room + 10) / BEAT_SLOT) : 6;
    // Under three there is no room for an arrow, a number and an arrow: a very
    // short split-screen half just scrolls its numbers (the column clips, so
    // nothing ever paints over the bar above it).
    return fit < 3 ? 0 : Math.min(6, fit);
  }
  function beatPages(count, slots) {
    if (slots < 3) return [{ start: 0, end: count, up: false, down: false }];
    // Five numbers at most, as asked; a sixth point turns the sixth slot into an arrow.
    if (count <= Math.min(slots, 5)) return [{ start: 0, end: count, up: false, down: false }];
    const pages = [];
    let start = 0;
    while (start < count) {
      const first = pages.length === 0;
      const room = first ? slots - 1 : slots - 1;
      const left = count - start;
      if (!first && left <= room) {
        pages.push({ start, end: count, up: true, down: false });
        break;
      }
      const numbers = first ? slots - 1 : slots - 2;
      pages.push({ start, end: start + numbers, up: !first, down: true });
      start += numbers;
    }
    return pages;
  }
  function arrowButton(label, direction) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "beat-button beat-arrow";
    button.setAttribute("aria-label", direction > 0 ? "Next points" : "Earlier points");
    button.textContent = label;
    button.addEventListener("click", () => {
      state.beatPage = Math.max(0, (state.beatPage || 0) + direction);
      renderBeats();
    });
    return button;
  }
  function renderBeats() {
    const rail = $("beatRail");
    const beats = state.idea ? (state.idea.beats || []) : [];
    const pages = beatPages(beats.length, beatSlots(rail));
    state.beatPage = Math.min(state.beatPage || 0, pages.length - 1);
    const page = pages[state.beatPage];
    rail.replaceChildren();
    if (page.up) rail.appendChild(arrowButton("\u2191", -1));
    for (let index = page.start; index < page.end; index += 1) {
      const beat = beats[index];
      const button = document.createElement("button");
      button.type = "button";
      button.className = "beat-button" + (index === state.currentBeat ? " is-current" : "");
      button.dataset.beat = String(index);
      button.textContent = index + 1;
      button.title = beat.label;
      button.addEventListener("click", () => jumpToBeat(beat, index));
      rail.appendChild(button);
    }
    if (page.down) rail.appendChild(arrowButton("\u2193", 1));
  }

  function jumpToBeat(beat, index) {
    state.currentBeat = index;
    [...$("beatRail").querySelectorAll("[data-beat]")].forEach((button) => {
      button.classList.toggle("is-current", Number(button.dataset.beat) === index);
    });
    const target = state.mode === "points" ? beat.bullet_index : Math.max(0, Number(beat.start_phrase_id?.slice(1)) - 1);
    const line = $(`${state.mode}-${target}`);
    if (line) {
      line.scrollIntoView({ block: "start", behavior: "smooth" });
      line.classList.add("is-focus");
      setTimeout(() => line.classList.remove("is-focus"), 1200);
    }
  }

  function setMode(mode) {
    state.mode = mode;
    $("pointsTab").classList.toggle("is-active", mode === "points");
    $("scriptTab").classList.toggle("is-active", mode === "script");
    $("pointsTab").setAttribute("aria-selected", String(mode === "points"));
    $("scriptTab").setAttribute("aria-selected", String(mode === "script"));
    renderReader();
  }

  // Several things want the take set open at once (the hook step handing over, the
  // reader, the record button). Without one shared promise they each POST and the
  // second one collides on the take-set key.
  function ensureSession() {
    if (state.session && state.session.packet_id === state.idea.packet_id) {
      return Promise.resolve(state.session);
    }
    if (!state.sessionPending || state.sessionPendingFor !== state.idea.packet_id) {
      state.sessionPendingFor = state.idea.packet_id;
      state.sessionPending = openSession().finally(() => { state.sessionPending = null; });
    }
    return state.sessionPending;
  }

  async function openSession() {
    if (state.idea.active_session_id) {
      const data = await api(`/recording-sessions/${state.idea.active_session_id}`);
      state.session = data.session;
    } else {
      const data = await api("/recording-sessions", {
        method: "POST",
        body: JSON.stringify({
          candidate_id: state.idea.candidate_id,
          packet_id: state.idea.packet_id,
          device_meta: {
            user_agent: navigator.userAgent.slice(0, 300),
            viewport: `${innerWidth}x${innerHeight}`,
            orientation: screen.orientation?.type || "",
            camera: state.cameraReport || null,
          },
        }),
      });
      state.session = data.session;
      state.idea.active_session_id = state.session.id;
    }
    updateSessionLabels();
    return state.session;
  }

  function renderHookPanel(idea, lockNote = "") {
    const hook = selectedHook(idea);
    const panel = $("hookPanel");
    panel.replaceChildren();
    state.hookLock = lockNote;
    // The opening now lives in the reader as its first line (renderReader), so
    // this panel only speaks when the opening is locked and he needs to know why.
    panel.hidden = !hook || !lockNote;
    if (!hook || !lockNote) return;
    const line = document.createElement("div");
    line.className = "hook-line";
    const strong = document.createElement("strong");
    strong.textContent = hook.text;
    const question = document.createElement("span");
    question.className = "hook-line-question";
    question.textContent = hook.question;
    line.append(strong, question);
    if (lockNote) {
      const note = document.createElement("span");
      note.className = "hook-lock";
      note.textContent = lockNote;
      line.appendChild(note);
    }
    panel.appendChild(line);
    // The choice is made once. After that it is one line, and Change brings the
    // options back - so the camera and the script share the screen instead.
    const options = (idea.hook_options || []).length;
    if (options >= 2 && !lockNote) {
      const change = document.createElement("button");
      change.type = "button";
      change.className = "hook-change";
      change.textContent = "Change";
      change.addEventListener("click", () => openHookChooser(idea));
      panel.appendChild(change);
    }
  }

  function hookChosenKey(idea) {
    return `tce-hook-chosen-${idea.candidate_id}-v${idea.packet_version}`;
  }

  function markHookChosen(idea) {
    try { localStorage.setItem(hookChosenKey(idea), "1"); } catch { /* private mode */ }
  }

  function hookAlreadyChosen(idea) {
    try { return localStorage.getItem(hookChosenKey(idea)) === "1"; } catch { return false; }
  }

  function openHookChooser(idea) {
    const model = hookChooserModel(idea, {
      sessionStatus: state.session?.status,
      clipCount: (state.session?.clips || []).length,
      recorderActive: Boolean(state.recorder && state.recorder.state !== "inactive"),
    });
    if (!model.show) {
      showNotice(model.reason || "The opening cannot be changed for this take set.");
      return;
    }
    renderHookChooser(model);
  }

  function renderHookOptions(list, model, onChoose) {
    list.replaceChildren();
    model.options.forEach((option) => {
      const card = document.createElement("article");
      card.className = `hook-option${option.current ? " is-current" : ""}`;
      card.dataset.hookId = option.id;
      const rank = document.createElement("div");
      rank.className = "hook-rank";
      rank.textContent = (option.recommended ? "Recommended" : `Option ${option.rank}`) + (option.current ? " · current opening" : "");
      const text = document.createElement("p");
      text.className = "hook-text";
      text.textContent = option.text;
      const question = document.createElement("p");
      question.className = "hook-detail";
      question.textContent = `Viewer question: ${option.question}`;
      const why = document.createElement("p");
      why.className = "hook-detail hook-why";
      why.textContent = `Why (private): ${option.rationale}`;
      const use = document.createElement("button");
      use.type = "button";
      use.className = "hook-use";
      use.textContent = option.current ? "Keep this opening" : "Use this opening";
      use.addEventListener("click", () => onChoose(option.id));
      card.append(rank, text, question, why, use);
      list.appendChild(card);
    });
  }

  function renderHookChooser(model) {
    renderHookOptions($("hookOptions"), model, (hookId) => applyHookChoice(hookId));
    $("hookChooserHint").textContent = "Pick the first spoken line. The rest of the script stays the same.";
    $("hookPanel").hidden = true;
    $("hookChooser").hidden = false;
  }

  async function askForMoreOpenings() {
    const idea = state.idea;
    if (!idea) return;
    const button = $("moreHooksButton");
    const label = $("moreHooksState");
    button.disabled = true;
    label.textContent = "Asked. The engine writes them on your PC worker; this can take a few minutes if it is busy.";
    try {
      const response = await fetch(`${apiV1}/editorial/packets/${idea.packet_id}/more-hooks`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
      pollMoreOpenings(idea);
    } catch (error) {
      label.textContent = error.message;
      button.disabled = false;
    }
  }

  // The job queues behind whatever the worker is already doing, so the page
  // says where it stands instead of holding a connection open and looking dead.
  async function pollMoreOpenings(idea, attempt = 0) {
    const label = $("moreHooksState");
    const button = $("moreHooksButton");
    try {
      const response = await fetch(`${apiV1}/editorial/packets/${idea.packet_id}/more-hooks-status`, { credentials: "same-origin" });
      const data = await response.json().catch(() => ({}));
      const activity = data.current_activity || "Working";
      if (data.state === "done") {
        const packet = data.result?.packet;
        if (packet) {
          const next = packetToIdea(idea, packet);
          state.ideas = state.ideas.map((item) => (item.candidate_id === next.candidate_id ? next : item));
          state.idea = next;
          const model = hookChooserModel(next, { clipCount: 0 });
          renderHookOptions($("hookViewOptions"), model, (hookId) => {
            markHookChosen(next);
            applyHookChoice(hookId);
          });
        }
        label.textContent = data.detail || "More openings are ready.";
        button.disabled = false;
        return;
      }
      if (data.state === "failed" || data.state === "idle") {
        label.textContent = data.detail || activity;
        button.disabled = false;
        return;
      }
      const waited = attempt * 5;
      label.textContent = waited > 20 ? `${activity} (${waited}s so far)` : activity;
      if (attempt > 120) {
        label.textContent = `${activity}. Still queued after ten minutes; it will finish on its own, check back.`;
        button.disabled = false;
        return;
      }
      setTimeout(() => pollMoreOpenings(idea, attempt + 1), 5000);
    } catch (error) {
      label.textContent = `Lost contact while waiting: ${error.message}`;
      button.disabled = false;
    }
  }

  function closeHookChooser() {
    $("hookChooser").hidden = true;
    if (!$("hookView").hidden && state.idea) {
      enterStudio(state.idea);
      return;
    }
    if (state.idea) renderHookPanel(state.idea);
  }

  async function applyHookChoice(hookId) {
    const idea = state.idea;
    if (!idea) return;
    markHookChosen(idea);
    const buttons = [...$("hookOptions").querySelectorAll("button")];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const currentId = idea.selected_hook_id || idea.hook_options?.[0]?.id;
      if (hookId !== currentId) {
        $("hookChooserHint").textContent = "Creating the packet version with this opening";
        const response = await fetch(`${apiV1}/editorial/packets/${idea.packet_id}/choose-hook`, {
          method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hook_id: hookId }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
        const next = packetToIdea(idea, data);
        state.ideas = state.ideas.map((item) => (item.candidate_id === next.candidate_id ? next : item));
        state.idea = next;
        renderQueue();
        // The draft session (if any) belongs to the previous version; the new
        // version gets its own take set the moment it is needed.
        state.session = null;
        renderBeats();
        setMode(state.mode);
        showNotice(`Opening changed. Packet version ${next.packet_version} is bound to this take set.`, 6000);
      }
      closeHookChooser();
      await ensureSession();
    } catch (error) {
      showNotice(error.message, 7000);
      $("hookChooserHint").textContent = error.message;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  async function openIdea(idea) {
    state.idea = idea;
    state.session = null;
    try {
      // An existing take set is already bound to this packet version; read it
      // before deciding whether the opening may still change.
      if (idea.active_session_id) await ensureSession();
    } catch (error) {
      showNotice(error.message);
    }
    const model = hookChooserModel(idea, {
      sessionStatus: state.session?.status,
      clipCount: (state.session?.clips || []).length,
      recorderActive: Boolean(state.recorder && state.recorder.state !== "inactive"),
    });
    // One decision on its own screen, then the studio is only camera and words.
    if (model.show && !hookAlreadyChosen(idea)) {
      showHookStep(idea, model);
      return;
    }
    enterStudio(idea, model.locked ? model.reason : "");
  }

  function showHookStep(idea, model) {
    $("queueView").hidden = true;
    $("studioView").hidden = true;
    $("hookView").hidden = false;
    setStudioMode(false);
    $("hookViewIdea").textContent = idea.title;
    $("moreHooksState").textContent = "";
    $("moreHooksButton").disabled = false;
    renderHookOptions($("hookViewOptions"), model, (hookId) => {
      markHookChosen(idea);
      applyHookChoice(hookId);
    });
  }

  async function enterStudio(idea, lockNote = "") {
    $("queueView").hidden = true;
    $("hookView").hidden = true;
    $("studioView").hidden = false;
    setStudioMode(true);
    $("scriptTitle").textContent = idea.title;
    $("bigIdea").textContent = idea.big_idea;
    $("hookChooser").hidden = true;
    renderHookPanel(idea, lockNote);
    // A different idea starts its numbers from the first page, nothing marked.
    state.beatPage = 0;
    state.currentBeat = null;
    renderBeats();
    setMode("points");
    updateSessionLabels();
    try {
      // The camera first, so what it actually gave is written into the take set:
      // a phone that has no portrait mode can only be diagnosed from its own data.
      await ensureMedia();
      await ensureSession();
    } catch (error) {
      showNotice(error.message);
    }
  }

  function chooseIdea(idea) {
    if (state.idea?.packet_id === idea.packet_id) { openIdea(idea); return; }
    if (state.recorder && state.recorder.state !== "inactive") {
      state.pendingIdea = idea;
      $("switchDialog").showModal();
      return;
    }
    openIdea(idea);
  }

  /* "a few times today the video turned black and I had to re run it" (24-Sep).
     Android switches the camera off when the screen locks, another app takes it,
     or a call comes in. The 9:16 crop records a canvas, and a canvas stream never
     ends on its own, so `state.stream.active` stayed true over a dead camera: the
     studio never reopened it and only a reload brought the picture back. What
     counts is the CAMERA's own track. */
  function cameraLive() {
    return Boolean(state.rawStream?.getVideoTracks().some((track) => track.readyState === "live"));
  }

  function releaseMedia() {
    state.portraitStopped = true;
    cancelAnimationFrame(state.portraitFrame);
    [state.rawStream, state.stream].forEach((stream) => stream?.getTracks().forEach((track) => track.stop()));
    state.rawStream = null;
    state.stream = null;
    state.cameraSource = null;
  }

  // One opening at a time: Record pressed while the camera is coming back waits
  // for that reopen instead of asking Android for a second camera it refuses.
  function ensureMedia() {
    if (state.stream?.active && cameraLive()) return Promise.resolve(state.stream);
    if (!state.mediaPending) {
      state.mediaPending = openMedia().finally(() => { state.mediaPending = null; });
    }
    return state.mediaPending;
  }

  async function openMedia() {
    if (state.stream) releaseMedia();
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !supportedMime) {
      throw new Error("This browser cannot record camera video with audio.");
    }
    const camera = await openCamera();
    state.rawStream = camera.stream;
    if (!state.rawStream.getAudioTracks().some((track) => track.enabled)) throw new Error("The recording has no active microphone track.");
    state.stream = portraitStream(camera);
    state.cameraSource = camera.element;
    state.rawStream.getVideoTracks().forEach((track) => {
      track.addEventListener("ended", () => { if (state.rawStream === camera.stream) cameraLost(); });
    });
    $("camera").srcObject = state.stream;
    await $("camera").play();
    $("cameraEmpty").hidden = true;
    return state.stream;
  }

  /* The camera died under the studio. Anything being recorded is kept as its
     own clip (a recorder cannot switch cameras mid-file, and recording on would
     only record black), and the picture comes back by itself - now if the page
     is on screen, else the moment he returns to it. */
  function cameraSending() {
    return Boolean(state.rawStream?.getVideoTracks().some((track) => track.readyState === "live" && !track.muted));
  }

  let reopening = null;
  async function cameraLost({ force = false } = {}) {
    if (state.recorder && state.recorder.state !== "inactive" && !state.finalizing.size) {
      // Stopped on the phone now; its pieces keep uploading, and Finish waits for them.
      await finishClip({ waitForServer: false }).catch(() => {});
      showNotice("The phone switched the camera off. What you recorded is kept - press Record to go on.", 8000);
    }
    await reviveCamera({ force });
  }

  function reviveCamera({ force = false } = {}) {
    if (document.hidden || $("studioView").hidden) return Promise.resolve();
    // Never pull the camera out from under a clip that is still being ended.
    if (force && !state.recorder && !state.mediaPending) releaseMedia();
    if (cameraLive()) {
      // Alive but paused while the page was hidden: a paused source paints the
      // same frame forever.
      state.cameraSource?.play().catch(() => {});
      $("camera").play().catch(() => {});
      return Promise.resolve();
    }
    if (!reopening) {
      reopening = ensureMedia()
        .catch((error) => showNotice(`The camera did not come back: ${error.message}`, 7000))
        .finally(() => { reopening = null; });
    }
    return reopening;
  }

  /* Ask the phone for a real portrait camera before settling for cropping one.
     A cropped 16:9 frame is the worst of both: Chrome has already thrown away the
     top and bottom to make it wide, and cropping the sides to 9:16 then throws
     away two thirds of what is left, which is why he saw himself "zoomed in A
     LOT". So: portrait modes first (nothing is cropped at all if one works), then
     the TALLEST frame on offer - 4:3 keeps far more of him than 16:9 - and the
     crop takes its full height. Each attempt that comes back landscape is stopped
     before the next, so the camera light never stacks up. */
  const CAMERA_ATTEMPTS = [
    { width: { exact: 1080 }, height: { exact: 1920 } },
    { width: { exact: 720 }, height: { exact: 1280 } },
    { aspectRatio: { exact: 9 / 16 } },
    // No portrait mode: take the most vertical field of view there is, to crop.
    // The sensor's largest 4:3 mode first (his reports 3056x2296): cropped to
    // 9:16 at its full height that is more than 1080x1920, so the file comes out
    // at full HD vertical instead of 810x1440 from the 1920x1440 mode.
    { width: { ideal: 4096 }, height: { ideal: 3072 }, aspectRatio: { ideal: 4 / 3 } },
    { width: { ideal: 1440 }, height: { ideal: 1920 }, aspectRatio: { ideal: 3 / 4 } },
    { width: { ideal: 1080 }, height: { ideal: 1440 }, aspectRatio: { ideal: 3 / 4 } },
    { width: { ideal: 1080 }, height: { ideal: 1920 } },
  ];

  /* The size a track reports the instant it opens is not the size of its frames.
     Android reported nothing at all on 22-Sep, so `height >= width` was 0 >= 0,
     the frames were called portrait and the crop was skipped: the take came back
     2288x1716, landscape, after the fix was already live. The only number worth
     believing is the one a <video> element gives once it has real frames, so
     every attempt is measured that way and the element is kept for the canvas. */
  function measure(stream) {
    const element = document.createElement("video");
    element.playsInline = true;
    element.muted = true;
    element.srcObject = stream;
    element.play().catch(() => { /* metadata still arrives */ });
    return new Promise((resolve) => {
      const done = () => resolve({
        stream, element, width: element.videoWidth || 0, height: element.videoHeight || 0,
      });
      if (element.videoWidth) { done(); return; }
      element.addEventListener("loadedmetadata", done, { once: true });
      // Never hang the studio on a camera that says nothing: 0x0 falls through
      // to the next attempt, and a 0x0 last resort is passed through uncropped.
      setTimeout(done, 2500);
    });
  }

  /* 🚨 ONE CAMERA AT A TIME. Android opens the camera once: the ladder used to
     keep its best stream so far open while trying the next attempt, so every
     attempt after the first landscape answer failed with NotReadableError - on
     his phone the 720x1280 and exact-9:16 portrait modes were never tried at all
     (camera report, 22-Sep). Each attempt is now measured and CLOSED, and only the
     winner is opened again at the end. */
  async function openCamera() {
    const audio = { echoCancellation: true, noiseSuppression: true };
    const open = (attempt) => navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", ...attempt }, audio,
    }).then(measure);
    const stop = (opened) => opened.stream.getTracks().forEach((track) => track.stop());
    const tried = [];
    let best = null;
    for (const attempt of CAMERA_ATTEMPTS) {
      let opened = null;
      try {
        opened = await open(attempt);
      } catch (error) {
        tried.push({ attempt, error: error.name });
        continue;
      }
      tried.push({ attempt, got: `${opened.width}x${opened.height}` });
      const portrait = opened.width && opened.height && opened.height >= opened.width;
      if (portrait) {
        state.cameraReport = { chose: `${opened.width}x${opened.height}`, portrait: true, tried };
        return describe(opened);
      }
      // The tallest landscape frame is the least zoom once cropped. Remember the
      // ATTEMPT, not the stream: the camera must be free for the next try.
      if (!best || opened.height > best.height) best = { attempt, height: opened.height };
      stop(opened);
    }
    if (!best) throw new Error("The camera did not open.");
    const chosen = await open(best.attempt);
    state.cameraReport = {
      chose: `${chosen.width}x${chosen.height}`,
      portrait: chosen.height >= chosen.width,
      tried,
    };
    return describe(chosen);
  }

  /* What the camera could have given, next to what it gave: the largest mode and
     the screen's rotation are what tell "this phone has no portrait mode" apart
     from "the browser would not hand it over". */
  function describe(opened) {
    try {
      const track = opened.stream.getVideoTracks()[0];
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      state.cameraReport = {
        ...(state.cameraReport || {}),
        max: caps.width && caps.height ? `${caps.width.max}x${caps.height.max}` : "",
        angle: screen.orientation ? screen.orientation.angle : null,
      };
    } catch { /* the report is a diagnosis, never a reason not to record */ }
    return opened;
  }

  /* Every clip this phone recorded on 22-Sep came out 2288x1288: upright, but
     framed landscape, so it cut the top of his head off and could not be posted
     as a vertical video. Chrome on Android gives a landscape camera on a portrait
     phone and ignores the size hints. When that happens the frames are drawn
     through a 9:16 canvas, centre cropped, and the canvas is what gets recorded
     AND previewed - so what he sees is what the file holds. A camera that is
     already portrait is passed straight through and nothing is re-encoded. */
  function portraitStream(camera) {
    const raw = camera.stream;
    const track = raw.getVideoTracks()[0];
    // Measured from real frames, never from getSettings() at open time.
    const width = camera.width;
    const height = camera.height;
    if (!track || !width || !height) return raw;
    // Pass straight through only a frame that is ALREADY a 9:16 video of a size
    // the phone can encode. His phone's first portrait answer was 3000x4000: a
    // 3:4 picture (black bands above and below in a phone-shaped box) at 12
    // megapixels a frame, which it could only record at 20 frames a second
    // (take c2e0b4fb, 23-Sep). Everything else goes through the canvas.
    const TARGET = 9 / 16;
    if (Math.abs(width / height - TARGET) < 0.01 && height <= 1920) return raw;

    const source = camera.element;
    const canvas = document.createElement("canvas");
    // Crop the largest 9:16 area out of the middle: trim the sides of a wide or
    // 3:4 frame, the top and bottom of an over-tall one.
    const cropWidth = width / height > TARGET ? height * TARGET : width;
    const cropHeight = width / height > TARGET ? height : width / TARGET;
    const cropX = (width - cropWidth) / 2;
    const cropY = (height - cropHeight) / 2;
    // Full HD vertical at most: 1080x1920 is what a phone's own camera records,
    // and a quarter of the pixels of the 3000x4000 source keeps it at 30 fps.
    canvas.height = Math.round(Math.min(1920, cropHeight) / 2) * 2;
    canvas.width = Math.round(canvas.height * TARGET / 2) * 2;
    const context = canvas.getContext("2d");

    const draw = () => {
      if (state.portraitStopped) return;
      if (source.readyState >= 2) {
        context.drawImage(source, cropX, cropY, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
      }
      state.portraitFrame = requestAnimationFrame(draw);
    };
    state.portraitStopped = false;
    source.play().catch(() => { /* a paused element still paints once it can */ });
    draw();

    const out = canvas.captureStream(30);
    raw.getAudioTracks().forEach((audio) => out.addTrack(audio));
    // When the camera itself stops, stop painting too.
    track.addEventListener("ended", () => {
      state.portraitStopped = true;
      cancelAnimationFrame(state.portraitFrame);
    });
    return out;
  }

  async function requestWakeLock() {
    try { state.wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { state.wakeLock = null; }
  }

  async function startRecording() {
    try {
      // Pressing Record with the chooser open confirms the current opening; the
      // walking reader carries no editorial detail from here on.
      if (!$("hookChooser").hidden) closeHookChooser();
      // Camera first here too: a take set opened before the camera is described
      // carries no camera report, which is how a landscape take got through.
      const stream = await ensureMedia();
      await ensureSession();
      const localId = crypto.randomUUID();
      const extension = supportedMime.startsWith("video/mp4") ? "mp4" : "webm";
      const response = await api(`/recording-sessions/${state.session.id}/clips`, {
        method: "POST", body: JSON.stringify({ local_clip_id: localId, mime_type: supportedMime, extension }),
      });
      state.clip = response.clip;
      state.sequence = 0;
      state.activeMs = 0;
      state.activeStartedAt = performance.now();
      state.startedAt = Date.now();
      state.takeMarkers = [];
      state.pendingWrites = [];
      state.recorder = new MediaRecorder(stream, { mimeType: supportedMime, videoBitsPerSecond: 8000000, audioBitsPerSecond: 128000 });
      state.recorder.ondataavailable = (event) => {
        if (!event.data?.size) return;
        const sequence = state.sequence++;
        const task = (async () => {
          const digest = await sha256(event.data);
          const record = { key: `${state.clip.id}:${sequence}`, clipId: state.clip.id, sequence, blob: event.data, sha256: digest, uploaded: false };
          await idbPut(record);
          updateSyncLabel();
          syncChunk(record);
        })();
        state.pendingWrites.push(task);
      };
      state.recorder.start(3000);
      // The editorial workspace is a different page that can hold the microphone
      // for voice. Two things must never own the mic at once, and the studio
      // wins: it is capturing a take that cannot be redone. The workspace reads
      // this flag and refuses to start listening while it is set.
      cameraFlag(true);
      await requestWakeLock();
      state.timerId = setInterval(updateTimer, 250);
      $("recordingFlag").hidden = false;
      $("timer").hidden = false;
      $("recordButton").disabled = true;
      $("pauseButton").disabled = false;
      $("finishClipButton").disabled = false;
      // The one button that ends it while recording must never be greyed out.
      $("finishSessionButton").disabled = false;
      $("pauseButton").textContent = "Pause";
      setRecordingChrome(true);
      // No "Recording started" toast: it sat over the red flag and the timer for
      // four seconds, and the red flag already says it.
    } catch (error) {
      showNotice(`Recording did not start: ${error.message}`, 7000);
    }
  }

  function updateTimer() {
    let milliseconds = state.activeMs;
    if (state.recorder?.state === "recording") milliseconds += performance.now() - state.activeStartedAt;
    const total = Math.floor(milliseconds / 1000);
    $("timer").textContent = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }

  function pauseResume() {
    if (!state.recorder) return;
    if (state.recorder.state === "recording") {
      state.activeMs += performance.now() - state.activeStartedAt;
      state.recorder.pause();
      $("pauseButton").textContent = "Resume";
      $("recordingFlag").hidden = true;
      showNotice("Paused. The current clip is still open.");
    } else if (state.recorder.state === "paused") {
      state.activeStartedAt = performance.now();
      state.recorder.resume();
      $("pauseButton").textContent = "Pause";
      $("recordingFlag").hidden = false;
    }
  }

  function currentBeatId() {
    return Number.isInteger(state.currentBeat) ? state.idea.beats[state.currentBeat]?.id : null;
  }

  // Mark take was removed on 20-Sep-2026: the editor finds repeated takes from
  // the words themselves (it dropped a duplicated line unaided in the first real
  // edit), so a button asking the person walking and talking to also log
  // boundaries was work for no gain. The server still accepts take_markers, so
  // an automatic source of them can be added later without a migration.

  function stopRecorderLocally() {
    return new Promise((resolve) => {
      if (!state.recorder || state.recorder.state === "inactive") { resolve(); return; }
      if (state.recorder.state === "recording") state.activeMs += performance.now() - state.activeStartedAt;
      state.recorder.addEventListener("stop", resolve, { once: true });
      state.recorder.stop();
    });
  }

  /* 24-Sep walk: Stop, then Finish a moment later. Stop was still sending the
     last pieces of a 5.6-minute clip, Finish did not wait for it, and the video
     was built from the 3-second clip before it - the walk looked lost. Every
     ending clip is now registered BEFORE its first await, and Finish waits for
     all of them. Each settles true (on the server) or false (still on the phone). */
  function finishClip(options) {
    if (!state.clip || !state.recorder) return Promise.resolve(null);
    let settle;
    const ending = new Promise((resolve) => { settle = resolve; });
    state.finalizing.add(ending);
    ending.then(() => state.finalizing.delete(ending));
    const run = finishClipNow(options, settle);
    run.catch(() => settle(false));
    return run;
  }

  /* Sending a stopped clip is its own step, so it can be retried: a clip whose
     closing call failed (bad signal) stays on the phone in state.unfinished and
     Finish sends it before building the video. */
  async function sendClip(entry) {
    const { clip, session, activeSeconds, takeMarkers } = entry;
    const synced = await retryStoredChunks(clip.id);
    if (!synced) throw new Error("Some of the video is still on this phone. Reconnect and press Finish again.");
    const response = await api(`/recording-clips/${clip.id}/finish`, {
      method: "POST", body: JSON.stringify({ active_duration_s: activeSeconds, take_markers: takeMarkers }),
    });
    await idbDeleteClip(clip.id);
    session.clips = [...(session.clips || []).filter((item) => item.id !== response.clip.id), response.clip].sort((a, b) => a.position - b.position);
    state.unfinished = (state.unfinished || []).filter((item) => item.clip.id !== clip.id);
    return response.clip;
  }

  /* 24-25 Sep: a failed clip finish left Record greyed out for good - the studio
     was stuck until a reload. Whatever happens to the send, the studio is free
     again: the clip is either on the server, kept on the phone for Finish to
     retry, or (no data at all) dropped with a word saying so. */
  function freeStudio(clip) {
    if (state.clip?.id !== clip.id) return;
    state.clip = null;
    state.recorder = null;
    cameraFlag(false);
    state.activeMs = 0;
    updateSessionLabels();
    $("recordButton").disabled = false;
  }

  async function finishClipNow({ waitForServer = true } = {}, settle = () => {}) {
    const clip = state.clip;
    const session = state.session;
    const takeMarkers = [...state.takeMarkers];
    await stopRecorderLocally();
    setRecordingChrome(false);
    const activeSeconds = Number((state.activeMs / 1000).toFixed(3));
    await Promise.all(state.pendingWrites);
    // Pieces of video the recorder actually handed over. A quick Record-then-Stop
    // can hand over none; the server would refuse it as "missing chunk sequences".
    const pieces = state.sequence;
    clearInterval(state.timerId);
    $("recordingFlag").hidden = true;
    $("pauseButton").disabled = true;
    $("finishClipButton").disabled = true;
    const entry = { clip, session, activeSeconds, takeMarkers };
    const finalize = (async () => {
      if (!pieces) {
        await idbDeleteClip(clip.id);
        freeStudio(clip);
        const error = new Error("That take was too short to keep. Press Record again.");
        error.tooShort = true;
        throw error;
      }
      try {
        const saved = await sendClip(entry);
        if (state.clip?.id === clip.id) showNotice("Clip saved and checked for camera and microphone tracks.");
        freeStudio(clip);
        return saved;
      } catch (error) {
        // Kept on the phone; Finish sends it before building the video.
        if (!(state.unfinished || []).some((item) => item.clip.id === clip.id)) {
          state.unfinished = [...(state.unfinished || []), entry];
        }
        freeStudio(clip);
        throw error;
      }
    })();
    // A dropped empty take is not a clip Finish must wait for.
    finalize.then(() => settle(true), (error) => settle(Boolean(error && error.tooShort)));
    if (waitForServer) return finalize.catch((error) => { showNotice(error.message, 7000); if (!error.tooShort) throw error; return null; });
    finalize.catch((error) => showNotice(error.message, 7000));
    freeStudio(clip);
    return clip;
  }

  async function finishSession() {
    try {
      // A clip Stop is already ending must not be ended a second time.
      if (state.recorder && state.recorder.state !== "inactive" && !state.finalizing.size) await finishClip().catch(() => {});
      if (state.finalizing.size) {
        $("syncState").textContent = "Sending the end of the last clip before building the video";
        await Promise.all([...state.finalizing]);
      }
      // Clips whose send failed earlier: send them now, or refuse to build without them.
      for (const entry of [...(state.unfinished || [])]) {
        if (entry.session.id !== state.session?.id) continue;
        $("syncState").textContent = "Sending a clip that did not get through before";
        await sendClip(entry);
      }
      if (!(state.session?.clips || []).some((clip) => clip.status === "ready")) {
        showNotice("Nothing recorded yet, so there is nothing to send for editing.");
        return;
      }
      await ensureSession();
      const ready = (state.session.clips || []).filter((clip) => clip.status === "ready").sort((a, b) => a.position - b.position);
      if (!ready.length) throw new Error("Finish at least one clip before finishing the session.");
      $("syncState").textContent = "Assembling clips and checking audio";
      const response = await api(`/recording-sessions/${state.session.id}/finish`, {
        method: "POST", body: JSON.stringify({ selected_clip_ids: ready.map((clip) => clip.id) }),
      });
      state.session = response.session;
      showNotice("Session saved as one editable recording. Every source clip is retained.", 7000);
      showQueue();
      await loadQueue();
    } catch (error) {
      showNotice(error.message, 7000);
    }
  }

  function updateSessionLabels() {
    // The strip only appears when something needs saying. The clip count was
    // never his problem, and "Phone copy is safe" explained our storage to him
    // rather than telling him anything he could act on.
    const pending = state.pendingSync.size;
    const offline = !navigator.onLine;
    const strip = $("sessionStrip");
    if (!pending && !offline) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    $("clipCount").textContent = offline ? "No signal" : "";
    $("uploadState").textContent = offline
      ? "Keeping everything on this phone until you are back online"
      : `Uploading ${pending} piece${pending === 1 ? "" : "s"}`;
  }

  function showQueue() {
    if (state.recorder?.state === "recording") pauseResume();
    $("studioView").hidden = true;
    $("queueView").hidden = false;
    setStudioMode(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
    // Take sets and packet versions change while the studio is open; the queue
    // must say what is bound now, not what it said when the page loaded.
    loadQueue();
  }

  function syncScrollRail() {
    // The slider this used to drive is gone; where he was reading is still kept.
    const reader = $("reader");
    if (state.idea) localStorage.setItem(`tce-reader-${state.idea.packet_id}-${state.mode}`, String(reader.scrollTop));
  }

  /* Plus and minus, in steps of 10%, remembered on this phone. The old single
     button cycled 85 -> 100 -> 115 -> 130 -> back to 85, so one tap too many
     threw the words back to their smallest mid-take. */
  const TEXT_MIN = .7;
  const TEXT_MAX = 2;
  function applyTextSize() {
    $("reader").style.setProperty("--reader-size", `${(1.55 * state.textSize).toFixed(2)}rem`);
    $("textSizeValue").textContent = `${Math.round(state.textSize * 100)}%`;
    $("textSmaller").disabled = state.textSize <= TEXT_MIN + 1e-9;
    $("textBigger").disabled = state.textSize >= TEXT_MAX - 1e-9;
  }
  function changeTextSize(step) {
    const next = Math.round((state.textSize + step) * 10) / 10;
    state.textSize = Math.min(TEXT_MAX, Math.max(TEXT_MIN, next));
    try { localStorage.setItem("tce-reader-size", String(state.textSize)); } catch { /* private mode */ }
    applyTextSize();
  }
  function restoreTextSize() {
    let saved = NaN;
    try { saved = Number(localStorage.getItem("tce-reader-size")); } catch { /* private mode */ }
    if (saved >= TEXT_MIN && saved <= TEXT_MAX) state.textSize = saved;
    applyTextSize();
  }

  /* The house means home, and home is Today - except inside the studio, where
     the only thing above it is the list you came from and there is no bottom nav
     to get back with. The label always says which, so it is never a guess. */
  function inStudio() { return document.body.classList.contains("in-studio"); }

  function paintHomeButton() {
    const button = $("homeButton");
    if (!button) return;
    button.setAttribute("aria-label", inStudio() ? "Back to the list" : "Back to Today");
    button.title = inStudio() ? "Back to the list" : "Back to Today";
  }

  $("homeButton").addEventListener("click", () => {
    if (inStudio()) { showQueue(); return; }
    window.location.href = `${pathPrefix}/today`;
  });

  // The nav ships absolute hrefs; this page is served at /record and /tce/record.
  document.querySelectorAll("#bottomNav a").forEach((link) => {
    link.setAttribute("href", pathPrefix + link.getAttribute("href"));
  });
  $("moreHooksButton").addEventListener("click", askForMoreOpenings);
  /* Two layout switches on the right rail, remembered on this phone: swap words
     and video, and words over the video (the see-through prompter). */
  function applyLayout() {
    let flipped = false;
    let overlay = false;
    try {
      flipped = localStorage.getItem("tce-layout-flipped") === "1";
      overlay = localStorage.getItem("tce-layout-overlay") === "1";
    } catch { /* private mode: defaults */ }
    document.body.classList.toggle("layout-flipped", flipped);
    document.body.classList.toggle("overlay-mode", overlay);
    $("overlayButton").setAttribute("aria-pressed", String(overlay));
  }
  function toggleLayout(key) {
    try {
      const on = localStorage.getItem(key) === "1";
      localStorage.setItem(key, on ? "0" : "1");
    } catch { /* private mode: the switch still works for this visit */
      document.body.classList.toggle(key === "tce-layout-flipped" ? "layout-flipped" : "overlay-mode");
      return;
    }
    applyLayout();
  }
  $("flipLayoutButton").addEventListener("click", () => toggleLayout("tce-layout-flipped"));
  $("overlayButton").addEventListener("click", () => toggleLayout("tce-layout-overlay"));
  applyLayout();
  /* The background behind the words, five steps from white to black; from the
     third step the letters turn white so they pop (24-Sep). Remembered on this
     phone. In words-over-video mode the same steps set how dark the see-through
     backing is. */
  const SHADE_MAX = 4;
  function applyShade() {
    const level = Math.max(0, Math.min(SHADE_MAX, Number(state.shade) || 0));
    document.querySelector(".reader-shell").dataset.shade = String(level);
    $("shadeLighter").disabled = level === 0;
    $("shadeDarker").disabled = level === SHADE_MAX;
  }
  function changeShade(step) {
    state.shade = Math.max(0, Math.min(SHADE_MAX, (Number(state.shade) || 0) + step));
    try { localStorage.setItem("tce-reader-shade", String(state.shade)); } catch { /* private mode */ }
    applyShade();
  }
  try { state.shade = Number(localStorage.getItem("tce-reader-shade")) || 0; } catch { state.shade = 0; }
  applyShade();
  $("shadeDarker").addEventListener("click", () => changeShade(1));
  $("shadeLighter").addEventListener("click", () => changeShade(-1));
  // The number column pages by its own height, so a resize re-pages it.
  if (window.ResizeObserver) new ResizeObserver(() => { if (state.idea) renderBeats(); }).observe($("beatRail"));
  $("textBigger").addEventListener("click", () => changeTextSize(.1));
  $("textSmaller").addEventListener("click", () => changeTextSize(-.1));
  restoreTextSize();
  $("pointsTab").addEventListener("click", () => setMode("points"));
  $("scriptTab").addEventListener("click", () => setMode("script"));
  $("recordButton").addEventListener("click", startRecording);
  $("pauseButton").addEventListener("click", pauseResume);
  $("finishClipButton").addEventListener("click", () => finishClip());
  $("finishSessionButton").addEventListener("click", finishSession);
  $("reader").addEventListener("scroll", syncScrollRail, { passive: true });
  $("switchDialog").addEventListener("close", async () => {
    if ($("switchDialog").returnValue !== "confirm" || !state.pendingIdea) { state.pendingIdea = null; return; }
    const next = state.pendingIdea;
    state.pendingIdea = null;
    await finishClip({ waitForServer: false });
    openIdea(next);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && state.recorder?.state === "recording") {
      pauseResume();
      $("interruptionFlag").hidden = false;
    } else if (!document.hidden) {
      $("interruptionFlag").hidden = true;
      requestWakeLock();
      // Back on screen: a camera the phone switched off meanwhile comes back now.
      // Android can also hand it back "live" but muted for good, which is just as
      // black, so a camera still muted after a moment is treated as gone.
      if (state.stream) {
        setTimeout(() => {
          if (document.hidden || !state.stream) return;
          if (cameraSending()) reviveCamera();
          else cameraLost({ force: true });
        }, 1200);
      }
    }
  });
  window.addEventListener("online", () => { updateSyncLabel(); retryStoredChunks(); });
  window.addEventListener("offline", updateSyncLabel);
  // A crashed or closed studio tab must not leave voice locked out forever.
  window.addEventListener("pagehide", () => cameraFlag(false));

  window.addEventListener("beforeunload", (event) => {
    if (state.recorder && state.recorder.state !== "inactive") { event.preventDefault(); event.returnValue = ""; }
  });

  /* Deep link straight into one idea.
     Without this, getting from a topic he has already chosen to actually
     recording it meant: open the topic, open the script workshop, go to the
     studio, then find the same card in the queue and tap it again. Four taps to
     reach a screen he had already told us he wanted. `?candidate=<uuid>` (or
     `?packet=<uuid>`) opens it directly; the opening chooser still appears if
     the opening is not settled, because that is a real decision and not a step
     to skip. An id that is not in the queue falls back to the list rather than
     erroring - the script may not be ready yet. */
  function openFromQuery() {
    var params = new URLSearchParams(window.location.search);
    var candidateId = params.get("candidate");
    var packetId = params.get("packet");
    if (!candidateId && !packetId) return false;
    var wanted = state.ideas.find(function (idea) {
      return (candidateId && idea.candidate_id === candidateId)
        || (packetId && idea.packet_id === packetId);
    });
    if (!wanted) {
      showNotice("That script is not ready to record yet. Here is what is.");
      return false;
    }
    // Drop the query so a reload, or the back button, does not reopen it after
    // he has deliberately come back to the list.
    window.history.replaceState({}, "", `${pathPrefix}/record`);
    chooseIdea(wanted);
    return true;
  }

  updateSyncLabel();
  loadQueue().then(function () {
    try { openFromQuery(); } catch (error) { /* the list still works */ }
  });
})();
