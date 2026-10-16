/* Saving a take in the background (12-Oct, Ziv on a call, T-11436): "I need the saving
   process to be in the background and not force me to stay on that page. Like if I
   click back to go back to TCE ... I don't want to wait until you save ... move the
   files with you to another page, continue with the saving."

   The studio used to hold him on a modal ("Please stay on this screen") until the end
   of his last clip had left the phone, and anything still on its way when he left was
   kept only in that page's memory. Now the moment he presses Stop or Finish, what is
   still owed is written down beside the clip's pieces (which already wait in
   IndexedDB until the server has them): which clip, which take set, how long it ran,
   and whether Finish was pressed. This script runs on the studio AND on every
   workspace page, so whichever TCE page he is on sends the pieces left, closes the
   clip, and hands the take set over for editing. Each of those server steps is safe
   to repeat: a chunk it already has, a clip already closed and a take set already
   building all answer as done. One page at a time does the sending (a Web Lock), so
   two open tabs never race each other.

   Progress and a failure show in one status line that pushes the page down, never
   a screen in the way. */
(() => {
  "use strict";

  const pathPrefix = window.location.pathname.startsWith("/tce/") ? "/tce" : "";
  const apiV1 = `${pathPrefix}/api/v1`;
  const KEY = "tce-recording-pending";
  // The studio's own card follows a take set from here once it is handed over.
  const FINISH_KEY = "tce-finish-tracking";
  const RETRY_MS = 5000;
  // A clip he left mid-recording, never stopped, is not this script's to close. Its
  // note is dropped after a week so the list cannot grow for ever.
  const KEEP_MS = 7 * 24 * 3600 * 1000;

  const listeners = [];
  let retryId = null;

  /* ------------------------------------------------------------ what is owed */

  function read() {
    try {
      const data = JSON.parse(localStorage.getItem(KEY) || "null") || {};
      return { clips: data.clips || {}, sessions: data.sessions || {} };
    } catch (error) {
      return { clips: {}, sessions: {} };
    }
  }

  function write(data) {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch { /* private mode */ }
  }

  function rememberClip(entry) {
    const data = read();
    data.clips[entry.clipId] = { ...(data.clips[entry.clipId] || {}), ...entry, at: Date.now() };
    write(data);
  }

  function forgetClip(clipId) {
    const data = read();
    delete data.clips[clipId];
    write(data);
  }

  function rememberFinish(intent) {
    const data = read();
    data.sessions[intent.sessionId] = { ...intent, at: Date.now() };
    write(data);
  }

  // Is anything of this take set still to leave the phone, or not yet handed over?
  function owes(sessionId) {
    const data = read();
    return Boolean(data.sessions[sessionId])
      || Object.values(data.clips).some((clip) => clip.stopped && clip.sessionId === sessionId);
  }

  function owed() {
    const data = read();
    return Object.values(data.clips).some((clip) => clip.stopped) || Object.keys(data.sessions).length > 0;
  }

  /* ------------------------------------------------------- the phone's pieces */

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("tce-recording-v1", 1);
      // The same shape recording.js creates, for a phone whose first TCE page is not the studio.
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore("chunks", { keyPath: "key" });
        store.createIndex("clip", "clipId", { unique: false });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function piecesFor(clipId) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const request = db.transaction("chunks").objectStore("chunks").index("clip").getAll(clipId);
      request.onsuccess = () => { db.close(); resolve(request.result.sort((a, b) => a.sequence - b.sequence)); };
      request.onerror = () => { db.close(); reject(request.error); };
    });
  }

  async function changePieces(work) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("chunks", "readwrite");
      work(tx.objectStore("chunks"));
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }

  /* ---------------------------------------------------------------- sending */

  async function api(path, options = {}) {
    const response = await fetch(`${apiV1}/production${path}`, {
      credentials: "same-origin",
      ...options,
      headers: { ...(options.body instanceof Blob ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || `Request failed with ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function sendClip(entry) {
    const pieces = await piecesFor(entry.clipId);
    for (const piece of pieces.filter((row) => !row.uploaded)) {
      await api(`/recording-clips/${piece.clipId}/chunks/${piece.sequence}`, {
        method: "PUT", body: piece.blob,
        headers: { "Content-Type": piece.blob.type || "application/octet-stream", "X-Chunk-Sha256": piece.sha256 },
      });
      piece.uploaded = true;
      await changePieces((store) => store.put(piece));
    }
    try {
      await api(`/recording-clips/${entry.clipId}/finish`, {
        method: "POST",
        body: JSON.stringify({ active_duration_s: entry.activeSeconds || 0, take_markers: entry.takeMarkers || [] }),
      });
    } catch (error) {
      // The server refused the clip and the phone holds nothing more of it: no retry
      // can bring it back, so it is said plainly rather than tried for ever.
      if (error.status === 422 || error.status === 404) error.lost = true;
      throw error;
    }
    await changePieces((store) => pieces.forEach((piece) => store.delete(piece.key)));
    forgetClip(entry.clipId);
  }

  async function handOver(intent) {
    const session = (await api(`/recording-sessions/${intent.sessionId}`)).session;
    const ready = (session.clips || []).filter((clip) => clip.status === "ready").sort((a, b) => a.position - b.position);
    const data = read();
    delete data.sessions[intent.sessionId];
    if (!ready.length) {
      write(data);
      return { nothing: true };
    }
    await api(`/recording-sessions/${intent.sessionId}/finish`, {
      method: "POST", body: JSON.stringify({ selected_clip_ids: ready.map((clip) => clip.id) }),
    });
    const tracked = { sessionId: intent.sessionId, title: intent.title || "", at: Date.now() };
    try { localStorage.setItem(FINISH_KEY, JSON.stringify(tracked)); } catch { /* private mode */ }
    write(data);
    return { tracked };
  }

  async function drainNow() {
    const data = read();
    const now = Date.now();
    for (const [id, clip] of Object.entries(data.clips)) {
      if (!clip.stopped && now - (clip.at || 0) > KEEP_MS) delete data.clips[id];
    }
    write(data);
    const clips = Object.values(data.clips).filter((clip) => clip.stopped);
    const sessions = Object.values(data.sessions);
    if (!clips.length && !sessions.length) return;
    tell({ kind: "sending" });
    let failed = null;
    for (const clip of clips) {
      try {
        await sendClip(clip);
      } catch (error) {
        if (error.lost) {
          forgetClip(clip.clipId);
          tell({ kind: "lost", sessionId: clip.sessionId, error });
        } else {
          failed = error;
        }
      }
    }
    for (const intent of sessions) {
      // Its own clips first: a take set is never handed over without a clip still on its way.
      if (Object.values(read().clips).some((clip) => clip.stopped && clip.sessionId === intent.sessionId)) continue;
      try {
        const result = await handOver(intent);
        tell(result.nothing ? { kind: "nothing", intent } : { kind: "sent", intent, tracked: result.tracked });
      } catch (error) {
        failed = error;
      }
    }
    if (failed) {
      tell({ kind: "waiting", error: failed });
      clearTimeout(retryId);
      retryId = setTimeout(drain, RETRY_MS);
    }
  }

  function drain() {
    if (!owed()) return Promise.resolve();
    if (navigator.locks && navigator.locks.request) {
      return navigator.locks.request(KEY, () => drainNow()).catch(() => {});
    }
    return drainNow().catch(() => {});
  }

  /* --------------------------------------------- Record without a script */

  /* The no-script recorder keeps its pieces and its Done takes in its own IndexedDB and
     used to send them only when its own page opened again. Every page that loads this
     script now sends them too, the same way that page does: pieces oldest first, then
     the finish of each take whose Done was pressed and whose pieces are all in. Both
     server steps are safe to repeat (a piece already joined answers 409, a finished
     talk answers with the same video). */
  const SOLO_DB = "tce-solo-v1";
  let soloRetryId = null;

  async function soloExists() {
    if (!indexedDB.databases) return true;
    try { return (await indexedDB.databases()).some((db) => db.name === SOLO_DB); } catch { return true; }
  }

  function soloStore(name, mode, work) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(SOLO_DB, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("pieces")) db.createObjectStore("pieces", { keyPath: "key" });
        if (!db.objectStoreNames.contains("takes")) db.createObjectStore("takes", { keyPath: "talkId" });
      };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction(name, mode);
        const out = work(tx.objectStore(name));
        tx.oncomplete = () => { db.close(); resolve(out && out.result !== undefined ? out.result : undefined); };
        tx.onerror = () => { db.close(); reject(tx.error); };
      };
    });
  }

  async function soloDrainNow() {
    if (!(await soloExists())) return;
    const pieces = (await soloStore("pieces", "readonly", (s) => s.getAll()))
      .sort((a, b) => (a.talkId === b.talkId ? a.sequence - b.sequence : a.at - b.at));
    const takes = (await soloStore("takes", "readonly", (s) => s.getAll())).filter((take) => take.done);
    if (!pieces.length && !takes.length) return;
    paintBar({ kind: "sending" });
    let failed = null;
    for (const piece of pieces) {
      try {
        await api(`/agent-talks/${encodeURIComponent(piece.talkId)}/chunks/${piece.sequence}`, {
          method: "PUT", body: piece.blob,
        });
        await soloStore("pieces", "readwrite", (s) => s.delete(piece.key));
      } catch (error) {
        if (error.status === 409 || error.status === 404) await soloStore("pieces", "readwrite", (s) => s.delete(piece.key));
        else { failed = error; break; }
      }
    }
    if (!failed) {
      const left = await soloStore("pieces", "readonly", (s) => s.getAll());
      for (const take of takes) {
        if (left.some((piece) => piece.talkId === take.talkId)) continue;
        try {
          await api(`/agent-talks/${encodeURIComponent(take.talkId)}/finish`, {
            method: "POST",
            body: JSON.stringify({ ended_at: take.endedAt, duration_ms: take.durationMs, edit: true }),
          });
          await soloStore("takes", "readwrite", (s) => s.delete(take.talkId));
          paintBar({ kind: "sent" });
        } catch (error) {
          failed = error;
        }
      }
    }
    if (failed) {
      paintBar({ kind: "waiting", error: failed });
      clearTimeout(soloRetryId);
      soloRetryId = setTimeout(soloDrain, RETRY_MS);
    }
  }

  function soloDrain() {
    if (!window.indexedDB) return Promise.resolve();
    if (navigator.locks && navigator.locks.request) {
      return navigator.locks.request(SOLO_DB, () => soloDrainNow()).catch(() => {});
    }
    return soloDrainNow().catch(() => {});
  }

  /* -------------------------------------------------------------- the status */

  function tell(event) {
    if (listeners.length) listeners.forEach((listen) => listen(event));
    else paintBar(event);
  }

  // Workspace pages: one line under the header, in the page's flow so it pushes the
  // content down rather than sitting over it.
  function paintBar(event) {
    let bar = document.getElementById("tceSavingBar");
    if (!bar) {
      bar = document.createElement("p");
      bar.id = "tceSavingBar";
      bar.setAttribute("role", "status");
      bar.style.cssText = "margin:0;padding:.7rem 1rem;font-size:1rem;line-height:1.4;font-weight:600;";
      const header = document.querySelector("header.topbar");
      if (header) header.after(bar); else document.body.prepend(bar);
    }
    const failed = event.kind === "waiting" || event.kind === "lost";
    bar.style.background = failed ? "#ffe1dc" : "#fff3c4";
    bar.style.color = failed ? "#6b1209" : "#10213b";
    bar.hidden = false;
    clearTimeout(paintBar.timer);
    if (event.kind === "sending") bar.textContent = "Saving your take in the background. You can keep working.";
    if (event.kind === "waiting") bar.textContent = "Your take has not arrived yet. It is kept on this phone and sent again in a few seconds.";
    if (event.kind === "lost") bar.textContent = "A clip did not arrive and could not be saved. The rest of the take is still sent for editing.";
    if (event.kind === "nothing") bar.textContent = "Nothing was recorded, so there was nothing to send for editing.";
    if (event.kind === "sent") {
      bar.textContent = "Your take is saved and on its way to editing. ";
      const link = document.createElement("a");
      link.href = `${pathPrefix}/library?filter=editing`;
      link.textContent = "Open the Library";
      link.style.color = "inherit";
      bar.append(link);
      paintBar.timer = setTimeout(() => { bar.hidden = true; }, 12000);
    }
  }

  window.TCEResume = {
    rememberClip, forgetClip, rememberFinish, owes, drain,
    // The studio paints its own card instead of the bar.
    onStatus(listen) { listeners.push(listen); },
  };

  window.addEventListener("online", drain);
  // The studio registers its card before it calls drain itself; every other page starts here.
  if (!document.getElementById("finishStatus")) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", drain, { once: true });
    else drain();
  }
  // The studio's card follows studio takes only, so these always use the bar.
  window.addEventListener("online", soloDrain);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", soloDrain, { once: true });
  else soloDrain();
})();
