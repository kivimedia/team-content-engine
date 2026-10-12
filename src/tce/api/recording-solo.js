/* Record without a script (12-Oct, Ziv on a call): "I want to be able to go into TCE,
   click record... record with no script... I see myself... and when I'm done and I
   click on Done, it gets uploaded, transcribed, Jennifer does editing on it, and it
   just behaves as a regular video".

   The take uses the road a filmed agent call already uses: a talk is created under the
   reserved name "_solo", every MediaRecorder slice is sent while he talks, and Done
   joins the pieces into one library video and starts Jennifer's edit. On the server its
   video is a "solo_take": one voice, his, edited like any take, named "Recording, 12 Oct"
   until he renames it in the Library.

   Nothing is lost by leaving early. Each slice is kept on this phone (IndexedDB) until
   the server has it, and a take whose Done was pressed is finished from here the next
   time this page opens. Progress and failures show in one status line, never a screen
   in the way, and Back works at any moment. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pathPrefix = window.location.pathname.startsWith("/tce/") ? "/tce" : "";
  const apiV1 = `${pathPrefix}/api/v1`;
  const SOLO = "_solo";
  const DB_NAME = "tce-solo-v1";
  // Shared with the workspace page, which holds the microphone for voice: while a take
  // is captured it must not listen (the studio's own rule, recording.js).
  const CAMERA_FLAG = "tce-camera-active";
  const SLICE_MS = 3000;
  const RETRY_MS = 4000;

  const supportedMime = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
    "video/mp4;codecs=h264,aac", "video/mp4",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  // The studio's portrait modes first, then whatever the front camera gives.
  const CAMERA_ATTEMPTS = [
    { width: { exact: 1080 }, height: { exact: 1920 } },
    { width: { exact: 720 }, height: { exact: 1280 } },
    { aspectRatio: { exact: 9 / 16 } },
    {},
  ];

  const state = {
    stream: null, recorder: null, talk: null, sequence: 0, startedAt: 0,
    timerId: null, wakeLock: null, sending: false, retryId: null, done: false,
  };

  const cameraFlag = (on) => {
    try {
      if (on) localStorage.setItem(CAMERA_FLAG, String(Date.now()));
      else localStorage.removeItem(CAMERA_FLAG);
    } catch (_) { /* private mode */ }
  };

  function status(text, bad = false) {
    const line = $("soloStatus");
    line.textContent = text;
    line.hidden = !text;
    line.classList.toggle("is-bad", Boolean(bad));
  }

  function top(text) { $("soloState").textContent = text; }

  async function api(path, options = {}) {
    const response = await fetch(`${apiV1}/production${path}`, {
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
      throw error;
    }
    return data;
  }

  /* ---------------------------------------------------------- the phone's copy */

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

  /* ---------------------------------------------------------------- sending */

  async function sendPiece(piece) {
    await api(`/agent-talks/${encodeURIComponent(piece.talkId)}/chunks/${piece.sequence}`, {
      method: "PUT", body: piece.blob,
    });
    await dropPiece(piece.key);
  }

  /* Everything this phone still holds, oldest first; then every take whose Done was
     pressed and whose pieces are all in is finished. Runs again after a failure. */
  async function sendAll() {
    if (state.sending) return;
    state.sending = true;
    clearTimeout(state.retryId);
    let failed = null;
    try {
      const pieces = (await allPieces()).sort((a, b) => (a.talkId === b.talkId ? a.sequence - b.sequence : a.at - b.at));
      for (const piece of pieces) {
        try {
          await sendPiece(piece);
        } catch (error) {
          // 409: that take was already joined, so this piece can never be in it.
          if (error.status === 409 || error.status === 404) await dropPiece(piece.key);
          else { failed = error; break; }
        }
      }
      if (!failed) {
        const left = await allPieces();
        for (const take of await allTakes()) {
          if (!take.done || left.some((p) => p.talkId === take.talkId)) continue;
          try {
            const row = await api(`/agent-talks/${encodeURIComponent(take.talkId)}/finish`, {
              method: "POST",
              body: JSON.stringify({ ended_at: take.endedAt, duration_ms: take.durationMs, edit: true }),
            });
            await dropTake(take.talkId);
            if (state.talk && state.talk.talkId === take.talkId) state.talk = null;
            finished(row);
          } catch (error) {
            failed = error;
          }
        }
      }
    } catch (error) {
      failed = error;
    } finally {
      state.sending = false;
    }
    await showProgress(failed);
    if (failed) state.retryId = setTimeout(sendAll, RETRY_MS);
  }

  async function showProgress(failed) {
    let left = 0;
    try { left = (await allPieces()).length; } catch (_) { left = 0; }
    if (state.recorder && state.recorder.state === "recording") {
      top(failed ? "Recording, sending again shortly" : "Recording, sending as you talk");
      return;
    }
    if (failed && left) {
      status(`Not sent yet: ${left} ${left === 1 ? "part" : "parts"} wait on this phone and are sent again `
        + `in a few seconds (${failed.message}). You can leave: they are sent the next time you open this page.`, true);
    } else if (failed) {
      status(`Sent, but it could not be finished yet (${failed.message}). Trying again in a few seconds.`, true);
    } else if (left) {
      status(`Sending the last ${left} ${left === 1 ? "part" : "parts"}. You can leave this page.`);
    }
  }

  function finished(row) {
    const title = row.title || "your recording";
    status(`In your Library as "${title}". `
      + (row.edit_started ? "Jennifer is editing it now." : (row.detail || "")));
    top("Sent");
    const link = document.createElement("a");
    link.href = `${pathPrefix}/library`;
    link.className = "solo-library-link";
    link.textContent = "Open the Library";
    $("soloStatus").append(" ", link);
  }

  /* ----------------------------------------------------------------- camera */

  async function openCamera() {
    if (state.stream) return state.stream;
    const audio = { echoCancellation: false, noiseSuppression: true };
    let lastError = null;
    for (const attempt of CAMERA_ATTEMPTS) {
      try {
        state.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", ...attempt }, audio });
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (!state.stream) throw lastError || new Error("The camera did not open.");
    const video = $("soloCamera");
    video.srcObject = state.stream;
    await video.play().catch(() => {});
    $("soloCameraEmpty").hidden = true;
    $("soloCameraButton").hidden = true;
    $("soloRecord").disabled = false;
    top("Ready when you are");
    return state.stream;
  }

  async function tryCamera() {
    try {
      await openCamera();
    } catch (error) {
      $("soloCameraHint").textContent = `The camera did not open (${error.name || error.message}). Allow the camera and microphone, then tap Turn on the camera.`;
      $("soloCameraButton").hidden = false;
      top("Camera off");
    }
  }

  function releaseCamera() {
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
    $("soloCamera").srcObject = null;
  }

  /* -------------------------------------------------------------- recording */

  function clock(ms) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  async function startRecording() {
    if (!supportedMime) { status("This browser cannot record video. Try Chrome or Safari.", true); return; }
    $("soloRecord").disabled = true;
    try {
      const stream = await openCamera();
      const startedAt = new Date();
      const talk = await api("/agent-talks", {
        method: "POST",
        body: JSON.stringify({ agent: SOLO, call_id: crypto.randomUUID(), started_at: startedAt.toISOString(), mime: supportedMime }),
      });
      state.talk = { talkId: talk.talk_id, title: talk.title, startedAt: startedAt.toISOString() };
      await putTake({ talkId: talk.talk_id, done: false, startedAt: state.talk.startedAt });
      state.sequence = 0;
      state.startedAt = Date.now();
      state.recorder = new MediaRecorder(stream, { mimeType: supportedMime, videoBitsPerSecond: 8000000, audioBitsPerSecond: 128000 });
      const talkId = talk.talk_id;
      state.recorder.ondataavailable = async (event) => {
        if (!event.data || !event.data.size) return;
        const sequence = state.sequence++;
        await putPiece({ key: `${talkId}:${sequence}`, talkId, sequence, blob: event.data, at: Date.now() });
        sendAll();
      };
      state.recorder.start(SLICE_MS);
      cameraFlag(true);
      try { state.wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { state.wakeLock = null; }
      state.timerId = setInterval(() => { $("soloTimer").textContent = clock(Date.now() - state.startedAt); }, 250);
      $("soloTimer").textContent = "00:00";
      $("soloTimer").hidden = false;
      $("soloFlag").hidden = false;
      $("soloDone").disabled = false;
      $("soloHelp").hidden = true;
      status("");
      top("Recording, sending as you talk");
    } catch (error) {
      $("soloRecord").disabled = false;
      status(`Recording did not start: ${error.message}`, true);
    }
  }

  function stopRecorder() {
    return new Promise((resolve) => {
      const recorder = state.recorder;
      if (!recorder || recorder.state === "inactive") { resolve(); return; }
      // The last slice arrives before stop: wait for both.
      recorder.addEventListener("stop", () => setTimeout(resolve, 0), { once: true });
      recorder.stop();
    });
  }

  async function done() {
    if (!state.talk) return;
    $("soloDone").disabled = true;
    const durationMs = Date.now() - state.startedAt;
    await stopRecorder();
    clearInterval(state.timerId);
    $("soloFlag").hidden = true;
    cameraFlag(false);
    try { await state.wakeLock?.release(); } catch (_) { /* gone */ }
    state.wakeLock = null;
    state.recorder = null;
    await putTake({ talkId: state.talk.talkId, done: true, startedAt: state.talk.startedAt,
                    endedAt: new Date().toISOString(), durationMs });
    releaseCamera();
    $("soloRecord").disabled = false;
    $("soloRecord").textContent = "Record another";
    top("Sending");
    status("Sending the last parts. You can leave this page.");
    sendAll();
  }

  /* ------------------------------------------------------------------ wiring */

  $("soloBack").setAttribute("href", `${pathPrefix}/record`);
  $("soloRecord").addEventListener("click", () => {
    if ($("soloRecord").textContent === "Record another" && !state.stream) {
      $("soloRecord").textContent = "Record";
      $("soloHelp").hidden = false;
      $("soloTimer").hidden = true;
      tryCamera();
      return;
    }
    startRecording();
  });
  $("soloDone").addEventListener("click", done);
  $("soloCameraButton").addEventListener("click", tryCamera);
  window.addEventListener("online", sendAll);
  window.addEventListener("pagehide", () => cameraFlag(false));

  tryCamera();
  // A take from an earlier visit that never finished sending is finished now. One he
  // left while still recording (the tab closed, the phone locked) is kept and edited too:
  // what he said up to then is on this phone or the server.
  allPieces().then((left) => allTakes().then(async (takes) => {
    for (const take of takes.filter((t) => !t.done)) {
      await putTake({ ...take, done: true, endedAt: new Date().toISOString() });
    }
    if (left.length || takes.length) {
      status(`Sending a recording from earlier: ${left.length} ${left.length === 1 ? "part" : "parts"} left.`);
      sendAll();
    }
  })).catch(() => {});
})();
