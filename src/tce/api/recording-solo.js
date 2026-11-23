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
  // 23-Nov-2026 (wait-less B9): how often the page asks how a finish TCE took in the
  // background is going.
  const FINISH_POLL_MS = 3000;

  // 19-Nov-2026: H.264 first (hardware on a phone), VP9 last; the studio's order (recording.js).
  const supportedMime = [
    "video/mp4;codecs=avc1,mp4a.40.2", "video/mp4;codecs=avc1", "video/mp4;codecs=h264,aac",
    "video/webm;codecs=h264,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4",
    "video/webm;codecs=vp9,opus",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  // 20-Nov-2026: the 4:3 mode at 1920x1440 before the sensor's largest, as the studio has done
  // since 19-Nov (recording.js FULL_HD_4_3): Chrome on Android returns it as a portrait 1440x1920
  // that crops to exactly 1080x1920, same framing, a quarter of the 12-megapixel redraw. His
  // solo take of 20-Nov from the 3000x4000 mode came out at 22 pictures a second.
  const FULL_HD_4_3 = { width: { ideal: 1920 }, height: { ideal: 1440 }, aspectRatio: { ideal: 4 / 3 } };
  // The studio's ladder (recording.js): portrait modes first, then the tallest frame on offer,
  // which is cropped to 9:16 below. The old last resort, {}, handed back a raw landscape frame.
  const CAMERA_ATTEMPTS = [
    { width: { exact: 1080 }, height: { exact: 1920 } },
    { width: { exact: 720 }, height: { exact: 1280 } },
    { aspectRatio: { exact: 9 / 16 } },
    FULL_HD_4_3,
    { width: { ideal: 4096 }, height: { ideal: 3072 }, aspectRatio: { ideal: 4 / 3 } },
    { width: { ideal: 1440 }, height: { ideal: 1920 }, aspectRatio: { ideal: 3 / 4 } },
    { width: { ideal: 1080 }, height: { ideal: 1440 }, aspectRatio: { ideal: 3 / 4 } },
    { width: { ideal: 1080 }, height: { ideal: 1920 } },
  ];
  const TARGET = 9 / 16;

  const state = {
    stream: null, recorder: null, talk: null, sequence: 0, startedAt: 0,
    timerId: null, wakeLock: null, raw: null, paintId: 0, painting: false, sending: false, retryId: null, starting: false,
    held: new Set(),
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
          if (!take.done || left.some((p) => p.talkId === take.talkId) || state.held.has(take.talkId)) continue;
          try {
            const row = await finishTake(take);
            if (!row) continue; // TCE holds its finish: readFinish says how it ends
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

  /* 23-Nov-2026 (wait-less B9): Done answers at once. The finish asks TCE to put the take
     together in the background; TCE writes the finish down, answers 202 "finishing", and
     this page reads the talk every few seconds until it says how it ended. An older TCE
     ignores "background" and answers with the video, as before. Returns the finished row,
     or null while TCE holds the finish. */
  async function finishTake(take) {
    const row = await api(`/agent-talks/${encodeURIComponent(take.talkId)}/finish`, {
      method: "POST",
      body: JSON.stringify({ ended_at: take.endedAt, duration_ms: take.durationMs, edit: true, background: true }),
    });
    if (row.state !== "finishing" || row.upload_id) return row;
    if (!state.held.has(take.talkId)) {
      state.held.add(take.talkId);
      if (!state.starting && !state.recorder) {
        top("Putting it together");
        status("Your recording is being put together into its video now. You can leave this page.");
      }
      setTimeout(() => readFinish(take.talkId), FINISH_POLL_MS);
    }
    return null;
  }

  /* How the finish TCE holds is going: finished shows what a finish has always shown,
     failed is the refusal a finish has always given (tried again in a few seconds), and
     none means TCE holds no finish for it, so it is asked again. */
  async function readFinish(talkId) {
    let talk;
    try {
      talk = await api(`/agent-talks/${encodeURIComponent(talkId)}`);
    } catch (error) {
      if (error.status !== 404) { setTimeout(() => readFinish(talkId), RETRY_MS); return; }
      talk = null;
    }
    const finish = talk && talk.finish;
    const how = finish && finish.state;
    if (how === "finishing") { setTimeout(() => readFinish(talkId), FINISH_POLL_MS); return; }
    state.held.delete(talkId);
    if (how === "finished" && finish.result && finish.result.upload_id) {
      try { await dropTake(talkId); } catch (_) { /* the next visit asks, and hears it is finished */ }
      if (state.talk && state.talk.talkId === talkId) state.talk = null;
      finished(finish.result);
      return;
    }
    if (how === "failed") {
      const refused = new Error((finish.error && finish.error.detail) || "The video could not be put together");
      refused.status = (finish.error && finish.error.status) || 422;
      await showProgress(refused);
      clearTimeout(state.retryId);
      state.retryId = setTimeout(sendAll, RETRY_MS);
      return;
    }
    sendAll();
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
    // An earlier take can finish uploading while the next one is already rolling.
    if (state.starting || (state.talk && state.talk.talkId !== row.talk_id && state.recorder)) return;
    const title = row.title || "your recording";
    status(`In your Library as "${title}". `
      + (row.edit_started ? "Jennifer is editing it now." : (row.detail || "")));
    top("Sent");
    const link = document.createElement("a");
    link.href = `${pathPrefix}/library`;
    link.className = "solo-library-link";
    link.textContent = "Open the Library";
    $("soloStatus").append(" ", link);
    if (row.upload_id && !row.already_finished && !row.missing_pieces?.length) {
      window.TCETakeReward?.show(row.talk_id, $("soloStatus"));
    }
  }

  /* ----------------------------------------------------------------- camera */

  /* The size a <video> reports once it has real frames, not the size the track claims at open. */
  function measure(stream) {
    const element = document.createElement("video");
    element.playsInline = true;
    element.muted = true;
    element.srcObject = stream;
    element.play().catch(() => {});
    return new Promise((resolve) => {
      const done = () => resolve({ stream, element, width: element.videoWidth || 0, height: element.videoHeight || 0 });
      if (element.videoWidth) { done(); return; }
      element.addEventListener("loadedmetadata", done, { once: true });
      setTimeout(done, 2500);
    });
  }

  /* A camera that is not already 9:16 is drawn through a 9:16 canvas, centre cropped, and the
     canvas is what is previewed AND recorded, so the file is what he sees (as recording.js). */
  function portraitStream(camera) {
    const raw = camera.stream;
    const { width, height } = camera;
    if (!width || !height) return raw;
    if (Math.abs(width / height - TARGET) < 0.01 && height <= 1920) return raw;
    const cropWidth = width / height > TARGET ? height * TARGET : width;
    const cropHeight = width / height > TARGET ? height : width / TARGET;
    const cropX = (width - cropWidth) / 2;
    const cropY = (height - cropHeight) / 2;
    const canvas = document.createElement("canvas");
    canvas.height = Math.round(Math.min(1920, cropHeight) / 2) * 2;
    canvas.width = Math.round(canvas.height * TARGET / 2) * 2;
    const context = canvas.getContext("2d");
    const source = camera.element;
    state.painting = true;
    const draw = () => {
      if (!state.painting) return;
      if (source.readyState >= 2) context.drawImage(source, cropX, cropY, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
      state.paintId = requestAnimationFrame(draw);
    };
    draw();
    const out = canvas.captureStream(30);
    raw.getAudioTracks().forEach((audio) => out.addTrack(audio));
    return out;
  }

  async function openCamera() {
    if (state.stream) return state.stream;
    const audio = { echoCancellation: false, noiseSuppression: true };
    const open = (attempt) => navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", ...attempt }, audio }).then(measure);
    const stop = (opened) => opened.stream.getTracks().forEach((track) => track.stop());
    let chosen = null;
    let best = null;
    let lastError = null;
    // One camera at a time: Android opens it once, so each attempt is measured and closed.
    for (const attempt of CAMERA_ATTEMPTS) {
      let opened = null;
      try { opened = await open(attempt); } catch (error) { lastError = error; continue; }
      // The 4:3 full-HD ask counts only when tall enough to crop 1080x1920 from (as recording.js).
      if (attempt === FULL_HD_4_3 && opened.height >= opened.width && opened.height < 1920) { stop(opened); continue; }
      if (opened.width && opened.height && opened.height >= opened.width) { chosen = opened; break; }
      if (!best || opened.height > best.height) best = { attempt, height: opened.height };
      stop(opened);
    }
    if (!chosen && best) chosen = await open(best.attempt);
    if (!chosen) throw lastError || new Error("The camera did not open.");
    state.raw = chosen.stream;
    state.stream = portraitStream(chosen);
    const video = $("soloCamera");
    video.srcObject = state.stream;
    await video.play().catch(() => {});
    $("soloCameraEmpty").hidden = true;
    $("soloCameraButton").hidden = true;
    $("soloRecord").disabled = state.starting;
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
    state.painting = false;
    cancelAnimationFrame(state.paintId);
    if (state.raw) state.raw.getTracks().forEach((track) => track.stop());
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    state.raw = null;
    state.stream = null;
    $("soloCamera").srcObject = null;
  }

  /* -------------------------------------------------------------- recording */

  function clock(ms) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  async function startRecording() {
    if (state.starting || (state.recorder && state.recorder.state !== "inactive")) return;
    if (!supportedMime) { status("This browser cannot record video. Try Chrome or Safari.", true); return; }
    state.starting = true;
    document.body.classList.remove("between-takes");
    $("soloTimer").hidden = true;
    $("soloRecord").disabled = true;
    top(state.stream ? "Starting recording" : "Opening the camera");
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
      document.body.classList.add("solo-recording");
      $("soloRecord").textContent = "Record";
      cameraFlag(true);
      try { state.wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { state.wakeLock = null; }
      state.timerId = setInterval(() => { $("soloTimer").textContent = clock(Date.now() - state.startedAt); }, 250);
      $("soloTimer").textContent = "00:00";
      $("soloTimer").hidden = false;
      $("soloFlag").hidden = false;
      $("soloDone").disabled = false;
      $("soloHelp").hidden = true;
      $("soloTip").hidden = true;
      status("");
      top("Recording, sending as you talk");
    } catch (error) {
      $("soloRecord").disabled = false;
      status(`Recording did not start: ${error.message}`, true);
      top(state.stream ? "Ready to try again" : "Camera off");
    } finally {
      state.starting = false;
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
    document.body.classList.remove("solo-recording");
    document.body.classList.add("between-takes");
    $("soloCameraHint").textContent = "The camera will open when you record again.";
    $("soloCameraEmpty").hidden = false;
    $("soloHelp").textContent = `${clock(durationMs)} recorded`;
    $("soloHelp").hidden = false;
    $("soloTip").hidden = false;
    $("soloRecord").disabled = false;
    $("soloRecord").textContent = "Record another";
    top("Sending");
    status("Sending the last parts. You can leave this page.");
    sendAll();
  }

  /* ------------------------------------------------------------------ wiring */

  $("soloBack").setAttribute("href", `${pathPrefix}/record`);
  $("soloRecord").addEventListener("click", startRecording);
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
