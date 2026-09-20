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

// What a run is doing RIGHT NOW, in words, refreshed every 5 s. "Run queued"
// and then silence looked identical to a stuck page while the run was in fact
// waiting for the desktop worker.
const RUN_WORDS = {
  queued: "Queued. It starts within five minutes.",
  collecting: "Collecting evidence from Fathom and GitHub.",
  extracting: "Reading the evidence and pulling out moments.",
  selecting: "Choosing this week's ideas.",
  ranking: "Ranking the finalists.",
  drafting: "Writing the recording packets.",
  exporting: "Writing the Google Docs.",
  ready: "Ready. Reload this page to see the new scripts.",
  cancelled: "Cancelled.",
};

function runWords(run) {
  if (run.state === "waiting_worker" || run.state === "waiting_capacity") {
    return run.error_detail || "Waiting for the desktop subscription worker.";
  }
  if (run.state === "failed") return `Stopped: ${run.error_detail || "see the dashboard"}`;
  if (run.state === "needs_source_choice") return "Waiting for you to choose a source.";
  return RUN_WORDS[run.state] || run.state;
}

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pathPrefix = window.location.pathname.startsWith("/tce/") ? "/tce" : "";
  const apiV1 = `${pathPrefix}/api/v1`;
  const state = {
    ideas: [], idea: null, session: null, stream: null, recorder: null, clip: null,
    mode: "points", sequence: 0, startedAt: 0, activeStartedAt: 0, activeMs: 0,
    timerId: null, pendingWrites: [], pendingSync: new Map(), takeMarkers: [],
    wakeLock: null, pendingIdea: null, textSize: 1, runTimer: null, waiting: [], ideasShown: 5,
    phases: new Map(), rows: new Map(), away: [],
  };
  const supportedMime = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm",
    "video/mp4;codecs=h264,aac", "video/mp4",
  ].find((value) => window.MediaRecorder && MediaRecorder.isTypeSupported(value));

  function setStudioMode(active) {
    document.body.classList.toggle("in-studio", Boolean(active));
  }

  function setRecordingChrome(active) {
    const view = document.getElementById("studioView");
    if (view) view.classList.toggle("is-recording", Boolean(active));
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

  // Ideas the engine proposed that have no script yet. This is the decision he
  // actually makes, and it used to live only in the developer dashboard.
  async function loadIdeas() {
    try {
      const response = await fetch(`${apiV1}/editorial/candidates`, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      const written = new Set(state.ideas.map((idea) => idea.candidate_id));
      const busy = new Set(
        [...(state.phases || new Map())].filter(([, v]) => v.phase !== "ready").map(([id]) => id),
      );
      const all = (data.candidates || []).filter((c) => !/^SYNTHETIC/i.test(c.title || ""));
      const fresh = all
        .filter((c) => (c.status === "proposed" && !written.has(c.id)) || busy.has(c.id))
        .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
      state.away = await loadAwayIdeas();
      // An idea being written, or just put away, stays on screen with its own
      // state until it genuinely moves on.
      state.waiting = fresh;
      renderIdeas();
      renderAway();
    } catch (_) {
      // The queue above is the important half; a failure here stays quiet.
    }
  }

  // Each idea's own state, kept outside the DOM so re-rendering the list (a
  // sibling archived, the queue reloaded) never erases what is in flight.
  function ideaPhase(id) {
    if (!state.phases) state.phases = new Map();
    return state.phases.get(id) || { phase: "waiting", label: "" };
  }

  function setIdeaPhase(id, phase, label) {
    if (!state.phases) state.phases = new Map();
    state.phases.set(id, { phase, label: label || "" });
    paintIdea(id);
  }

  function renderIdeas() {
    const list = $("ideasList");
    const section = $("ideasSection");
    const waiting = state.waiting || [];
    section.hidden = waiting.length === 0;
    const shown = waiting.slice(0, state.ideasShown || 5);
    if (!state.rows) state.rows = new Map();

    // Reuse the row that already exists for an idea: a row being written keeps
    // its progress line and its disabled buttons.
    const keep = new Set(shown.map((c) => c.id));
    for (const [id, row] of state.rows) {
      if (!keep.has(id)) { row.remove(); state.rows.delete(id); }
    }
    shown.forEach((candidate) => {
      let row = state.rows.get(candidate.id);
      if (!row) {
        row = ideaRow(candidate);
        state.rows.set(candidate.id, row);
      }
      list.appendChild(row);  // appending a live node moves it, it does not clone
      paintIdea(candidate.id);
    });

    const being = waiting.filter((c) => ideaPhase(c.id).phase === "writing").length;
    $("ideasCount").textContent = being
      ? `${waiting.length} waiting \u00b7 ${being} being written`
      : `${waiting.length} waiting`;
    const more = $("moreIdeasButton");
    more.hidden = waiting.length <= shown.length;
    more.textContent = `Show more ideas (${waiting.length - shown.length} left)`;
  }

  // Withdrawn ideas are hidden from the default listing, so they are asked for
  // by name; otherwise Put away looked like deletion after a refresh.
  async function loadAwayIdeas() {
    try {
      const response = await fetch(`${apiV1}/editorial/candidates?status=withdrawn`, { credentials: "same-origin" });
      if (!response.ok) return [];
      const data = await response.json();
      return (data.candidates || [])
        .filter((c) => !/^SYNTHETIC/i.test(c.title || ""))
        .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
    } catch (_) {
      return [];
    }
  }

  function renderAway() {
    const away = state.away || [];
    const section = $("awaySection");
    section.hidden = away.length === 0;
    $("awaySummary").textContent = `Put away (${away.length})`;
    const list = $("awayList");
    list.replaceChildren();
    for (const candidate of away.slice(0, 20)) {
      const row = document.createElement("article");
      row.className = "idea-row is-away";
      const title = document.createElement("strong");
      title.textContent = candidate.title;
      const back = document.createElement("button");
      back.type = "button";
      back.className = "idea-row-undo";
      back.textContent = "Bring it back";
      back.addEventListener("click", async () => {
        back.disabled = true;
        await restoreIdea(candidate);
        await loadIdeas();
      });
      row.append(title, back);
      list.appendChild(row);
    }
  }

  function paintIdea(id) {
    const row = state.rows?.get(id);
    if (!row) return;
    const { phase, label } = ideaPhase(id);
    row.dataset.phase = phase;
    row.classList.toggle("is-away", phase === "away");
    row.classList.toggle("is-writing", phase === "writing");
    // A decided idea does not offer the same two choices again.
    row.querySelector(".idea-row-actions").hidden = phase !== "waiting";
    row.querySelector(".idea-row-undo").hidden = phase !== "away";
    row.querySelector(".idea-row-state").textContent = label;
  }

  function ideaRow(candidate) {
    const row = document.createElement("article");
    row.className = "idea-row";
    row.dataset.candidateId = candidate.id;
    const title = document.createElement("strong");
    title.textContent = candidate.title;
    const lesson = document.createElement("p");
    lesson.textContent = candidate.lesson || "";
    const source = document.createElement("span");
    source.className = "idea-source";
    source.textContent = ideaSource(candidate);

    const actions = document.createElement("div");
    actions.className = "idea-row-actions";
    const write = document.createElement("button");
    write.type = "button";
    write.className = "primary";
    // A script may already exist (asked for earlier, or written and never put
    // in the queue). Offering to write it again would pay for the same words.
    const written = (candidate.packet_count || 0) > 0;
    write.textContent = written ? "Put it in the queue" : "Write the script";
    write.addEventListener("click", () => (written ? queueIdea(candidate) : writeScript(candidate)));
    const away = document.createElement("button");
    away.type = "button";
    away.textContent = "Put it away";
    away.addEventListener("click", () => archiveIdea(candidate));
    actions.append(write, away);

    const undo = document.createElement("button");
    undo.type = "button";
    undo.className = "idea-row-undo";
    undo.hidden = true;
    undo.textContent = "Bring it back";
    undo.addEventListener("click", () => restoreIdea(candidate));

    const line = document.createElement("span");
    line.className = "idea-row-state";
    row.append(title, lesson, source, actions, undo, line);
    return row;
  }

  // The engine's own words for what a job is doing, in his.
  function humanActivity(text) {
    const raw = String(text || "");
    if (/queued/i.test(raw)) return "Queued for your PC worker";
    if (/waiting for subscription/i.test(raw)) return "Your PC worker is picking it up";
    if (/waiting for capacity|capacity/i.test(raw)) return "Waiting for subscription capacity";
    if (/validating/i.test(raw)) return "Checking it against the evidence";
    if (/resuming/i.test(raw)) return "Carrying on where it stopped";
    if (/packet ready|done/i.test(raw)) return "Ready";
    return raw || "Writing the script";
  }

  // Where it came from, in the words he would use: a call, or the code.
  function ideaSource(candidate) {
    const citations = candidate.citations_private || [];
    if (!citations.length) return "";
    const names = [];
    let code = 0;
    for (const c of citations) {
      if (c.source_kind === "github_commit_group") { code += 1; continue; }
      const title = (c.source_title || "").trim();
      const when = (c.occurred_at || "").slice(0, 10);
      const label = title ? (when ? `${title} (${when})` : title) : "";
      if (label && !names.includes(label)) names.push(label);
    }
    const parts = [];
    if (names.length) parts.push(`From ${names.slice(0, 2).join(" and ")}`);
    if (code) parts.push(`${code} piece${code === 1 ? "" : "s"} of your code`);
    return parts.join(" \u00b7 ");
  }

  async function queueIdea(candidate) {
    setIdeaPhase(candidate.id, "writing", "Putting it in the queue...");
    try {
      const response = await fetch(`${apiV1}/editorial/candidates/${candidate.id}/feedback`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "approve", created_by: "ziv", note: "Queued from the studio." }),
      });
      if (!response.ok) throw new Error(`Request failed with ${response.status}`);
      setIdeaPhase(candidate.id, "ready", "In the queue above, ready to record.");
      state.waiting = (state.waiting || []).filter((item) => item.id !== candidate.id);
      await loadQueue();
    } catch (error) {
      setIdeaPhase(candidate.id, "waiting", error.message);
    }
  }

  async function writeScript(candidate) {
    setIdeaPhase(candidate.id, "writing", "Asked. It queues behind whatever the worker is already doing.");
    try {
      const response = await fetch(`${apiV1}/editorial/candidates/${candidate.id}/packet`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
      renderIdeas();
      pollScript(candidate);
    } catch (error) {
      setIdeaPhase(candidate.id, "waiting", error.message);
    }
  }

  async function pollScript(candidate, attempt = 0) {
    if (ideaPhase(candidate.id).phase !== "writing") return;  // archived meanwhile
    try {
      const response = await fetch(`${apiV1}/editorial/candidates/${candidate.id}/packet-status`, { credentials: "same-origin" });
      const data = await response.json().catch(() => ({}));
      const job = data.job || {};
      if (job.state === "done") {
        // Asking for the script IS the decision to record it: the idea joins
        // the queue above, which is what the line then claims. Without this the
        // packet existed and the queue stayed empty.
        setIdeaPhase(candidate.id, "writing", "Putting it in the queue...");
        await fetch(`${apiV1}/editorial/candidates/${candidate.id}/feedback`, {
          method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "approve", created_by: "ziv", note: "Asked for the script in the studio." }),
        }).catch(() => null);
        setIdeaPhase(candidate.id, "ready", "The script is ready. It is in the queue above.");
        state.waiting = (state.waiting || []).filter((item) => item.id !== candidate.id);
        await loadQueue();
        return;
      }
      if (job.state === "failed") {
        setIdeaPhase(candidate.id, "waiting", job.detail || job.current_activity || "The script could not be written.");
        renderIdeas();
        return;
      }
      const waited = attempt * 5;
      setIdeaPhase(candidate.id, "writing", humanActivity(job.current_activity) + (waited > 20 ? ` (${waited}s so far)` : ""));
      if (attempt > 144) {
        setIdeaPhase(candidate.id, "writing", "Still queued after twelve minutes. It will finish on its own; check the queue later.");
        return;
      }
      setTimeout(() => pollScript(candidate, attempt + 1), 5000);
    } catch (error) {
      setIdeaPhase(candidate.id, "writing", `Lost contact while waiting: ${error.message}`);
      setTimeout(() => pollScript(candidate, attempt + 1), 15000);
    }
  }

  async function archiveIdea(candidate) {
    setIdeaPhase(candidate.id, "away", "Putting it away...");
    try {
      const response = await fetch(`${apiV1}/editorial/candidates/${candidate.id}/archive`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
      setIdeaPhase(candidate.id, "away", "Put away. It will not be offered again.");
      // It leaves the list on the next load, not under your finger: a mistake
      // stays undoable for as long as the page is open.
    } catch (error) {
      setIdeaPhase(candidate.id, "waiting", error.message);
    }
  }

  async function restoreIdea(candidate) {
    setIdeaPhase(candidate.id, "waiting", "Bringing it back...");
    try {
      const response = await fetch(`${apiV1}/editorial/candidates/${candidate.id}`, {
        method: "PATCH", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "proposed" }),
      });
      if (!response.ok) throw new Error(`Request failed with ${response.status}`);
      setIdeaPhase(candidate.id, "waiting", "Back on the list.");
    } catch (error) {
      setIdeaPhase(candidate.id, "away", error.message);
    }
  }

  async function loadEngineState() {
    try {
      const response = await fetch(`${apiV1}/content-runs/schedule`, { credentials: "same-origin" });
      if (!response.ok) return;
      const worker = (await response.json()).worker || {};
      const line = $("engineState");
      // Only worth saying when it changes what pressing a button will do.
      line.hidden = Boolean(worker.online);
      line.textContent = worker.online
        ? ""
        : `${worker.detail || "No worker is running."} Anything you ask for will start when it checks in.`;
    } catch (_) {
      // Silence here is right: the buttons still work.
    }
  }

  async function loadQueue() {
    try {
      const data = await api("/recording-queue");
      state.ideas = data.ideas || [];
      renderQueue();
      $("syncState").textContent = `${state.ideas.length} ready script${state.ideas.length === 1 ? "" : "s"}`;
      loadIdeas();
      loadEngineState();
    } catch (error) {
      $("syncState").textContent = "Could not load scripts";
      showNotice(error.message);
    }
  }

  async function watchRun(runId) {
    if (!runId) return;
    clearTimeout(state.runTimer);
    const host = $("produceNowState");
    try {
      const response = await fetch(`${apiV1}/content-runs/${runId}`, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`status ${response.status}`);
      const run = await response.json();
      const stages = run.stages || [];
      const done = stages.filter((s) => s.status === "succeeded").length;
      host.textContent = `${runWords(run)} (step ${Math.min(done + 1, stages.length)} of ${stages.length})`;
      const link = $("produceNowLink");
      if (link) {
        // On bot.kivimedia.co the app lives under /tce; an absolute
        // /dashboard link lands on KM BOT's own dashboard instead of the run.
        link.href = `${pathPrefix}${run.focused_path || `/dashboard?content_run=${runId}`}`;
        link.hidden = false;
      }
      if (!["ready", "failed", "cancelled"].includes(run.state)) {
        state.runTimer = setTimeout(() => watchRun(runId), 5000);
      } else if (run.state === "ready") {
        loadQueue();
      }
    } catch (error) {
      host.textContent = `Run created. Could not read its progress just now (${error.message}); it keeps going without this page.`;
      state.runTimer = setTimeout(() => watchRun(runId), 15000);
    }
  }

  async function produceNow() {
    const button = $("produceNowButton");
    button.disabled = true;
    $("produceNowState").textContent = "Creating one durable run. Completed work will be reused.";
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
    try {
      const response = await fetch(`${apiV1}/content-runs/produce-now`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idempotency_key: `recording-studio:${end.toISOString().slice(0, 13)}`,
          scope_kind: "week", window_start: start.toISOString(), window_end: end.toISOString(),
          maximum_candidate_count: 6, target_packet_count: 3,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed with ${response.status}`);
      showNotice("Content run created. Existing evidence and completed jobs stay intact.", 7000);
      watchRun(data.id);
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
      // Points keep their number; spoken phrases do not - "p028" was noise
      // to read past while talking.
      if (state.mode === "points") {
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

  function renderHookPanel(idea, lockNote = "") {
    const hook = selectedHook(idea);
    const panel = $("hookPanel");
    panel.replaceChildren();
    panel.hidden = !hook;
    if (!hook) return;
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
    renderBeats();
    setMode("points");
    updateSessionLabels();
    try {
      await ensureSession();
      // The top half is worth its space only if it shows him: the preview runs
      // from the moment the studio opens, not from the first Record.
      await ensureMedia();
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
      // Pressing Record with the chooser open confirms the current opening; the
      // walking reader carries no editorial detail from here on.
      if (!$("hookChooser").hidden) closeHookChooser();
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
      $("timer").hidden = false;
      $("recordButton").disabled = true;
      $("pauseButton").disabled = false;
      $("finishClipButton").disabled = false;
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
  $("moreHooksButton").addEventListener("click", askForMoreOpenings);
  $("moreIdeasButton").addEventListener("click", () => { state.ideasShown += 5; renderIdeas(); });
  $("textSizeButton").addEventListener("click", changeTextSize);
  $("pointsTab").addEventListener("click", () => setMode("points"));
  $("scriptTab").addEventListener("click", () => setMode("script"));
  $("recordButton").addEventListener("click", startRecording);
  $("pauseButton").addEventListener("click", pauseResume);
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
