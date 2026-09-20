(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    ideas: [], idea: null, session: null, stream: null, recorder: null, clip: null,
    mode: "points", sequence: 0, startedAt: 0, activeStartedAt: 0, activeMs: 0,
    timerId: null, pendingWrites: [], pendingSync: new Map(), takeMarkers: [],
    wakeLock: null, pendingIdea: null, textSize: 1,
  };
  const supportedMime = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
    "video/mp4;codecs=h264,aac", "video/mp4",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  function showNotice(message, timeout = 4200) {
    const notice = $("notice");
    notice.textContent = message;
    notice.hidden = false;
    clearTimeout(showNotice.timer);
    showNotice.timer = setTimeout(() => { notice.hidden = true; }, timeout);
  }

  async function api(path, options = {}) {
    const response = await fetch(`/api/v1/production${path}`, {
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
    $("uploadState").textContent = pending ? `Uploading: ${pending}` : "Phone copy is safe";
    $("syncState").textContent = navigator.onLine ? (pending ? `Uploading ${pending} chunk${pending === 1 ? "" : "s"}` : "Ready") : "Offline: keeping chunks on this phone";
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

  async function produceNow() {
    const button = $("produceNowButton");
    button.disabled = true;
    $("produceNowState").textContent = "Creating one durable run. Completed work will be reused.";
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
    try {
      const response = await fetch("/api/v1/content-runs/produce-now", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idempotency_key: `recording-studio:${end.toISOString().slice(0, 13)}`,
          scope_kind: "week", window_start: start.toISOString(), window_end: end.toISOString(),
          maximum_candidate_count: 12, target_packet_count: 3,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
      $("produceNowState").textContent = `Run ${data.state}. You can leave this page and return.`;
      showNotice("Content run created. Existing evidence and completed jobs stay intact.", 7000);
    } catch (error) {
      $("produceNowState").textContent = error.message;
      showNotice(error.message, 7000);
    } finally {
      button.disabled = false;
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
    items.forEach((text, index) => {
      const line = document.createElement("p");
      line.className = "reader-line";
      line.id = `${state.mode}-${index}`;
      const label = document.createElement("span");
      label.className = "reader-index";
      label.textContent = state.mode === "points" ? `Point ${index + 1}` : `Phrase p${String(index + 1).padStart(3, "0")}`;
      line.append(label, document.createTextNode(text));
      reader.appendChild(line);
    });
    const saved = Number(localStorage.getItem(`tce-reader-${idea.packet_id}-${state.mode}`) || 0);
    requestAnimationFrame(() => { reader.scrollTop = saved; syncScrollRail(); });
  }

  function renderBeats() {
    const rail = $("beatRail");
    rail.replaceChildren();
    (state.idea.beats || []).forEach((beat, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "beat-button";
      button.textContent = index + 1;
      button.title = beat.label;
      button.addEventListener("click", () => jumpToBeat(beat, index));
      rail.appendChild(button);
    });
  }

  function jumpToBeat(beat, index) {
    [...$("beatRail").children].forEach((button, i) => button.classList.toggle("is-current", i === index));
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

  async function ensureSession() {
    if (state.session && state.session.packet_id === state.idea.packet_id) return state.session;
    if (state.idea.active_session_id) {
      const data = await api(`/recording-sessions/${state.idea.active_session_id}`);
      state.session = data.session;
    } else {
      const data = await api("/recording-sessions", {
        method: "POST",
        body: JSON.stringify({
          candidate_id: state.idea.candidate_id,
          packet_id: state.idea.packet_id,
          device_meta: { user_agent: navigator.userAgent.slice(0, 300), viewport: `${innerWidth}x${innerHeight}` },
        }),
      });
      state.session = data.session;
      state.idea.active_session_id = state.session.id;
    }
    updateSessionLabels();
    return state.session;
  }

  function openIdea(idea) {
    state.idea = idea;
    state.session = null;
    $("queueView").hidden = true;
    $("studioView").hidden = false;
    $("scriptTitle").textContent = idea.title;
    $("bigIdea").textContent = idea.big_idea;
    const hook = selectedHook(idea);
    $("hookPanel").hidden = !hook;
    if (hook) {
      $("hookPanel").replaceChildren();
      const strong = document.createElement("strong");
      strong.textContent = `Opening: ${hook.text}`;
      const span = document.createElement("span");
      span.textContent = `Viewer question: ${hook.question}`;
      $("hookPanel").append(strong, span);
    }
    renderBeats();
    setMode("points");
    updateSessionLabels();
    ensureSession().catch((error) => showNotice(error.message));
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

  async function ensureMedia() {
    if (state.stream?.active) return state.stream;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !supportedMime) {
      throw new Error("This browser cannot record camera video with audio.");
    }
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1080 }, height: { ideal: 1920 } },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    if (!state.stream.getAudioTracks().some((track) => track.enabled)) throw new Error("The recording has no active microphone track.");
    $("camera").srcObject = state.stream;
    await $("camera").play();
    $("cameraEmpty").hidden = true;
    return state.stream;
  }

  async function requestWakeLock() {
    try { state.wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { state.wakeLock = null; }
  }

  async function startRecording() {
    try {
      await ensureSession();
      const stream = await ensureMedia();
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
      state.recorder = new MediaRecorder(stream, { mimeType: supportedMime, videoBitsPerSecond: 3500000, audioBitsPerSecond: 128000 });
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
      await requestWakeLock();
      state.timerId = setInterval(updateTimer, 250);
      $("recordingFlag").hidden = false;
      $("recordButton").disabled = true;
      $("pauseButton").disabled = false;
      $("markerButton").disabled = false;
      $("finishClipButton").disabled = false;
      $("finishSessionButton").disabled = true;
      $("pauseButton").textContent = "Pause";
      showNotice("Recording started. Tabs and point jumps stay available.");
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
    const active = $("beatRail").querySelector(".is-current");
    return active ? state.idea.beats[[...$("beatRail").children].indexOf(active)]?.id : null;
  }

  function markTake() {
    let elapsed = state.activeMs;
    if (state.recorder?.state === "recording") elapsed += performance.now() - state.activeStartedAt;
    state.takeMarkers.push({ at_s: Number((elapsed / 1000).toFixed(2)), beat_id: currentBeatId(), hint: "take_boundary" });
    showNotice(`Take marker ${state.takeMarkers.length} saved as an editing hint.`);
  }

  function stopRecorderLocally() {
    return new Promise((resolve) => {
      if (!state.recorder || state.recorder.state === "inactive") { resolve(); return; }
      if (state.recorder.state === "recording") state.activeMs += performance.now() - state.activeStartedAt;
      state.recorder.addEventListener("stop", resolve, { once: true });
      state.recorder.stop();
    });
  }

  async function finishClip({ waitForServer = true } = {}) {
    if (!state.clip || !state.recorder) return null;
    const clip = state.clip;
    const session = state.session;
    const takeMarkers = [...state.takeMarkers];
    await stopRecorderLocally();
    const activeSeconds = Number((state.activeMs / 1000).toFixed(3));
    await Promise.all(state.pendingWrites);
    clearInterval(state.timerId);
    $("recordingFlag").hidden = true;
    $("pauseButton").disabled = true;
    $("markerButton").disabled = true;
    $("finishClipButton").disabled = true;
    const finalize = (async () => {
      const synced = await retryStoredChunks(clip.id);
      if (!synced) throw new Error("Some chunks are still on this phone. Reconnect and press Finish clip again.");
      const response = await api(`/recording-clips/${clip.id}/finish`, {
        method: "POST", body: JSON.stringify({ active_duration_s: activeSeconds, take_markers: takeMarkers }),
      });
      await idbDeleteClip(clip.id);
      session.clips = [...(session.clips || []).filter((item) => item.id !== response.clip.id), response.clip].sort((a, b) => a.position - b.position);
      if (state.session?.id === session.id && state.clip?.id === clip.id) {
        state.clip = null;
        state.recorder = null;
        state.activeMs = 0;
        updateSessionLabels();
        $("recordButton").disabled = false;
        $("finishSessionButton").disabled = false;
        showNotice("Clip saved and checked for camera and microphone tracks.");
      }
      return response.clip;
    })();
    if (waitForServer) return finalize.catch((error) => { showNotice(error.message, 7000); throw error; });
    finalize.catch((error) => showNotice(error.message, 7000));
    state.clip = null;
    state.recorder = null;
    $("recordButton").disabled = false;
    return clip;
  }

  async function finishSession() {
    try {
      if (state.recorder && state.recorder.state !== "inactive") await finishClip();
      await ensureSession();
      const ready = (state.session.clips || []).filter((clip) => clip.status === "ready").sort((a, b) => a.position - b.position);
      if (!ready.length) throw new Error("Finish at least one clip before finishing the session.");
      $("finishSessionButton").disabled = true;
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
      $("finishSessionButton").disabled = false;
    }
  }

  function updateSessionLabels() {
    const clips = state.session?.clips || [];
    $("clipCount").textContent = clips.length ? `${clips.length} clip${clips.length === 1 ? "" : "s"} in this take set` : "No clips yet";
    $("finishSessionButton").disabled = !clips.some((clip) => clip.status === "ready");
  }

  function showQueue() {
    if (state.recorder?.state === "recording") pauseResume();
    $("studioView").hidden = true;
    $("queueView").hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function syncScrollRail() {
    const reader = $("reader");
    const max = Math.max(1, reader.scrollHeight - reader.clientHeight);
    $("scrollPosition").value = String(Math.round(reader.scrollTop / max * 100));
    if (state.idea) localStorage.setItem(`tce-reader-${state.idea.packet_id}-${state.mode}`, String(reader.scrollTop));
  }

  function changeTextSize() {
    state.textSize = state.textSize >= 1.4 ? .85 : state.textSize + .15;
    $("reader").style.setProperty("--reader-size", `${(1.55 * state.textSize).toFixed(2)}rem`);
    showNotice(`Reader text size ${Math.round(state.textSize * 100)}%.`);
  }

  $("homeButton").addEventListener("click", showQueue);
  $("produceNowButton").addEventListener("click", produceNow);
  $("textSizeButton").addEventListener("click", changeTextSize);
  $("pointsTab").addEventListener("click", () => setMode("points"));
  $("scriptTab").addEventListener("click", () => setMode("script"));
  $("recordButton").addEventListener("click", startRecording);
  $("pauseButton").addEventListener("click", pauseResume);
  $("markerButton").addEventListener("click", markTake);
  $("finishClipButton").addEventListener("click", () => finishClip());
  $("finishSessionButton").addEventListener("click", finishSession);
  $("reader").addEventListener("scroll", syncScrollRail, { passive: true });
  $("scrollUp").addEventListener("click", () => $("reader").scrollBy({ top: -innerHeight * .28, behavior: "smooth" }));
  $("scrollDown").addEventListener("click", () => $("reader").scrollBy({ top: innerHeight * .28, behavior: "smooth" }));
  $("scrollPosition").addEventListener("input", (event) => {
    const reader = $("reader");
    reader.scrollTop = (reader.scrollHeight - reader.clientHeight) * Number(event.target.value) / 100;
  });
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
    }
  });
  window.addEventListener("online", () => { updateSyncLabel(); retryStoredChunks(); });
  window.addEventListener("offline", updateSyncLabel);
  window.addEventListener("beforeunload", (event) => {
    if (state.recorder && state.recorder.state !== "inactive") { event.preventDefault(); event.returnValue = ""; }
  });

  updateSyncLabel();
  loadQueue();
})();
