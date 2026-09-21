/* The editorial workspace.
 *
 * One page, real URLs, six surfaces: Today, Topics, This week, the topic room,
 * the script workshop and the Library. `/record` stays the separate studio and
 * is linked, never absorbed - it is the one screen that must not grow.
 *
 * Conventions, all borrowed from recording.js so the two pages behave alike:
 *
 *   - No framework, no build step. Template literals into innerHTML, with every
 *     interpolated value through `esc`. User content is never concatenated raw.
 *   - Every long operation says what is happening right now. There are no bare
 *     spinners in this file; `working()` always takes a sentence.
 *   - Nothing is applied because the page felt like it. A change is proposed,
 *     shown as a before/after, and written only when he taps the accept button.
 */
(function () {
  "use strict";

  var prefix = window.location.pathname.indexOf("/tce/") === 0 ? "/tce" : "";
  var apiV1 = prefix + "/api/v1";

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    route: null,
    params: {},
    today: null,
    topics: null,
    topicFilter: "best",
    week: null,
    room: null,
    workshop: null,
    workshopTab: "outline",
    library: null,
    libraryFilter: "all",
    pending: null      // a change set awaiting his yes or no
  };

  // ----------------------------------------------------------------- utils

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function toast(message, bad) {
    var existing = document.querySelector(".toast");
    if (existing) existing.remove();
    var node = document.createElement("div");
    node.className = "toast" + (bad ? " is-bad" : "");
    node.setAttribute("role", "status");
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(function () { if (node.parentNode) node.remove(); }, 4600);
  }

  /* FastAPI sends `detail` as a string for plain errors and as an object for
   * ours, which carries the sentence a human should read plus the newer state
   * on a conflict. Both shapes have to end up as something worth showing. */
  function errorText(payload, status) {
    var detail = payload && payload.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
    if (typeof detail === "string" && detail) return detail;
    if (status === 401 || status === 403) return "This workspace refused the request.";
    if (status === 503) return "The engine is not available right now.";
    return "Something went wrong (" + status + ").";
  }

  async function api(path, options) {
    var opts = options || {};
    var init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    var response = await fetch(apiV1 + path, init);
    var payload = null;
    var text = await response.text();
    if (text) { try { payload = JSON.parse(text); } catch (e) { payload = null; } }
    if (!response.ok) {
      var error = new Error(errorText(payload, response.status));
      error.status = response.status;
      error.detail = payload && payload.detail;
      throw error;
    }
    return payload;
  }

  function working(sentence) {
    return '<p class="working">' + esc(sentence) + "</p>";
  }

  function plural(n, one, many) { return n === 1 ? one : (many || one + "s"); }

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return "";
    var total = Math.round(seconds);
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  // ---------------------------------------------------------------- routing

  var ROUTES = [
    { name: "today",    pattern: /^\/today\/?$/,               title: "Today" },
    { name: "topics",   pattern: /^\/topics\/?$/,              title: "Topics" },
    { name: "week",     pattern: /^\/week\/?$/,                title: "This week" },
    { name: "library",  pattern: /^\/library\/?$/,             title: "Library" },
    { name: "room",     pattern: /^\/topics\/([0-9a-f-]{36})\/?$/, title: "Topic" },
    { name: "workshop", pattern: /^\/scripts\/([0-9a-f-]{36})\/?$/, title: "Script" }
  ];

  function parse() {
    var path = window.location.pathname;
    if (prefix && path.indexOf(prefix) === 0) path = path.slice(prefix.length) || "/";
    for (var i = 0; i < ROUTES.length; i++) {
      var match = path.match(ROUTES[i].pattern);
      if (match) return { name: ROUTES[i].name, title: ROUTES[i].title, id: match[1] || null };
    }
    return { name: "today", title: "Today", id: null };
  }

  function go(path, replace) {
    var full = prefix + path;
    if (replace) window.history.replaceState({}, "", full);
    else window.history.pushState({}, "", full);
    render();
  }

  function setChrome(route) {
    $("pageTitle").textContent = route.title;
    var nav = $("bottomNav");
    var active = { today: "today", topics: "topics", week: "week", library: "library",
                   room: "topics", workshop: "week" }[route.name];
    Array.prototype.forEach.call(nav.querySelectorAll("a"), function (a) {
      if (a.dataset.route === active) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  function status(text) { $("pageStatus").textContent = text; }

  // ------------------------------------------------------------------ Today

  async function renderToday() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading your week") + "</div>";
    var data = await api("/editorial/today");
    state.today = data;

    var week = data.week || {};
    var counts = data.attention || {};
    var action = data.next_action || {};
    var primary = week.primary || [];

    var html = '<div class="page">';
    html += '<div class="page-head">';
    html += '<p class="kicker">Editorial workspace</p>';
    html += "<h1>Today</h1>";
    html += '<p class="lede">Your next useful action.</p>';
    html += "</div>";

    if (!(data.worker || {}).online && (data.worker || {}).detail) {
      html += '<p class="notice">' + esc(data.worker.detail) + "</p>";
    }

    html += '<button class="next-action" type="button" data-go="' + esc(action.href || "/topics") + '">';
    html += "<strong>" + esc(action.label || "Choose this week's topics") + "</strong>";
    html += "<span>" + esc(action.detail || "") + "</span>";
    html += "</button>";

    html += '<div class="counts">';
    html += countCard(counts.waiting, "need a decision", "/topics");
    html += countCard(counts.scripts_ready, "scripts ready", "/week");
    html += countCard(counts.editing, "being edited", "/library");
    html += countCard(counts.pending_reviews, "changes to review", "/topics");
    html += "</div>";

    html += "<h2>This week's recording list</h2>";
    if (!primary.length) {
      html += '<div class="empty"><strong>Nothing chosen yet</strong>'
            + "Pick the topics worth recording and they appear here, in order.</div>";
      html += '<div class="actions"><button class="btn primary" type="button" data-go="/topics">Choose this week\'s topics</button></div>';
    } else {
      html += '<p class="section-hint">' + esc(week.mix || "") + "</p>";
      html += '<div class="card-list">';
      primary.forEach(function (item, index) {
        html += weekCard(item, index, false);
      });
      html += "</div>";
      if (week.ready_count > 0) {
        html += '<div class="actions"><a class="btn primary" href="' + prefix + '/record">Start recording</a></div>';
      }
    }
    html += "</div>";
    view.innerHTML = html;
    status(counts.waiting + " " + plural(counts.waiting, "idea") + " waiting");
  }

  function countCard(value, label, href) {
    var n = value || 0;
    return '<button class="count' + (n ? "" : " is-zero") + '" type="button" data-go="' + esc(href) + '">'
         + "<b>" + n + "</b><span>" + esc(label) + "</span></button>";
  }

  // ----------------------------------------------------------------- Topics

  async function renderTopics() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading the ideas waiting for you") + "</div>";
    var data = await api("/editorial/topics?filter=" + encodeURIComponent(state.topicFilter) + "&limit=30");
    state.topics = data;

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Editorial workspace</p><h1>Topics</h1>';
    html += '<p class="lede">Decide what is worth your time. Nothing here asks the engine for anything.</p></div>';

    html += '<div class="chips" role="group" aria-label="Filter topics">';
    (data.filters || []).forEach(function (f) {
      html += '<button class="chip" type="button" data-filter="' + esc(f.key) + '" aria-pressed="'
           + (f.key === data.filter ? "true" : "false") + '">' + esc(f.label) + "</button>";
    });
    html += "</div>";

    if (data.withheld_note) {
      html += '<p class="notice">' + esc(data.withheld_note) + "</p>";
    }

    var topics = data.topics || [];
    if (!topics.length) {
      html += '<div class="empty"><strong>Nothing here</strong>'
            + esc(data.filter === "best"
                 ? "Everything is decided. The next weekly run collects new evidence."
                 : "No ideas match this filter.") + "</div>";
    } else {
      html += '<p class="section-hint">' + topics.length + " of " + data.total + " shown</p>";
      html += '<div class="card-list">';
      topics.forEach(function (topic) { html += topicCard(topic); });
      html += "</div>";
    }
    html += "</div>";
    view.innerHTML = html;
    status(data.total + " " + plural(data.total, "idea") + " " + esc(data.filter_label).toLowerCase());
  }

  function topicCard(topic) {
    var html = '<article class="card' + (topic.decision === "away" ? " is-dim" : "") + '">';
    html += "<h3>" + esc(topic.title) + "</h3>";
    html += '<p class="big-idea">' + esc(topic.big_idea) + "</p>";
    if (topic.why_this_is_yours) {
      html += '<p class="why">' + esc(topic.why_this_is_yours) + "</p>";
    }
    if (topic.provenance) {
      html += '<span class="source">' + esc(topic.provenance) + "</span>";
    }
    if (topic.timely) html += '<span class="tag is-timely">' + esc(topic.freshness_note) + "</span>";
    if (topic.lane_label) html += '<span class="tag is-lane">' + esc(topic.lane_label) + "</span>";
    if (topic.has_script) html += '<span class="tag is-ready">Script written</span>';

    if (topic.decision) {
      html += '<p class="section-hint">' + esc(decisionSentence(topic.decision)) + "</p>";
      html += '<div class="actions">';
      html += '<button class="btn" type="button" data-open-room="' + esc(topic.candidate_id) + '">Open it</button>';
      if (topic.decision !== "this_week") {
        html += '<button class="btn quiet" type="button" data-decide="this_week" data-id="'
             + esc(topic.candidate_id) + '">Put in this week</button>';
      }
      html += "</div>";
    } else {
      /* Four decisions, none of which pays for anything. Asking for the script
         lives in the topic room, after the idea is worth pursuing. */
      html += '<div class="btn-row">';
      html += '<button class="btn primary" type="button" data-decide="this_week" data-id="' + esc(topic.candidate_id) + '">Put in this week</button>';
      html += '<button class="btn" type="button" data-open-room="' + esc(topic.candidate_id) + '">Discuss</button>';
      html += '<button class="btn quiet" type="button" data-decide="later" data-id="' + esc(topic.candidate_id) + '">Save for later</button>';
      html += '<button class="btn quiet" type="button" data-decide="away" data-id="' + esc(topic.candidate_id) + '">Put it away</button>';
      html += "</div>";
    }
    html += "</article>";
    return html;
  }

  function decisionSentence(decision) {
    return {
      this_week: "In this week's list.",
      discuss: "Marked to think about.",
      later: "Saved for later. It will not be offered again until you ask.",
      away: "Put away. It will not be offered again."
    }[decision] || "";
  }

  // -------------------------------------------------------------- This week

  async function renderWeek() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading this week's list") + "</div>";
    var data = await api("/editorial/weeks/current/lineup");
    state.week = data;

    var primary = data.primary || [];
    var reserve = data.reserve || [];

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Week of ' + esc(data.week_start) + "</p>";
    html += "<h1>This week</h1>";
    html += '<p class="lede">' + primary.length + " of " + data.primary_slots
         + " recording " + plural(data.primary_slots, "slot") + " used."
         + (data.mix ? " " + esc(data.mix) + "." : "") + "</p></div>";

    if (!primary.length && !reserve.length) {
      html += '<div class="empty"><strong>Nothing chosen yet</strong>'
            + "Open Topics and put three ideas in this week.</div>";
      html += '<div class="actions"><button class="btn primary" type="button" data-go="/topics">Choose topics</button></div>';
    } else {
      html += "<h2>Record first</h2>";
      html += '<p class="section-hint">The order here is the order you record in.</p>';
      html += '<div class="card-list">';
      primary.forEach(function (item, index) { html += weekCard(item, index, true, primary.length); });
      html += "</div>";

      if (reserve.length) {
        html += "<h2>Possible replacements</h2>";
        html += '<p class="section-hint">Ready to swap in if one of the three stops feeling right.</p>';
        html += '<div class="card-list">';
        reserve.forEach(function (item, index) { html += weekCard(item, index, true, reserve.length, true); });
        html += "</div>";
      }
    }
    html += "</div>";
    view.innerHTML = html;
    status(data.ready_count + " of " + primary.length + " scripts ready");
  }

  function weekCard(item, index, controls, total, isReserve) {
    var html = '<article class="card">';
    html += '<div class="card-title-row"><span class="rank">' + (item.rank || index + 1) + "</span>";
    html += "<h3>" + esc(item.title) + "</h3></div>";
    if (item.reason) html += '<p class="why">' + esc(item.reason) + "</p>";
    if (item.lane_label) html += '<span class="tag is-lane">' + esc(item.lane_label) + "</span>";
    html += '<span class="tag' + (item.script_state === "ready" ? " is-ready" : "") + '">'
         + esc(scriptSentence(item.script_state)) + "</span>";

    if (controls) {
      html += '<div class="order-controls">';
      if (index > 0) {
        html += '<button class="btn" type="button" data-move="first" data-id="' + esc(item.candidate_id) + '">Make first</button>';
        html += '<button class="btn" type="button" data-move="up" data-id="' + esc(item.candidate_id) + '">Move up</button>';
      }
      if (index < (total || 1) - 1) {
        html += '<button class="btn" type="button" data-move="down" data-id="' + esc(item.candidate_id) + '">Move down</button>';
      }
      html += '<button class="btn quiet" type="button" data-slot="' + (isReserve ? "primary" : "reserve")
           + '" data-id="' + esc(item.candidate_id) + '">'
           + (isReserve ? "Put in this week" : "Move to reserve") + "</button>";
      html += '<button class="btn quiet" type="button" data-remove="' + esc(item.candidate_id) + '">Remove</button>';
      html += "</div>";
    }

    html += '<div class="actions">';
    html += '<button class="btn" type="button" data-open-room="' + esc(item.candidate_id) + '">Open the topic</button>';
    if (item.packet_id && item.script_state === "ready") {
      html += '<button class="btn" type="button" data-open-script="' + esc(item.packet_id) + '">Open the script</button>';
    } else if (!item.packet_id) {
      html += '<button class="btn primary" type="button" data-ask-script="' + esc(item.candidate_id) + '">Prepare the script</button>';
    }
    html += "</div></article>";
    return html;
  }

  function scriptSentence(scriptState) {
    return {
      none: "No script yet",
      ready: "Script ready",
      draft: "Script being written",
      exported: "Script ready"
    }[scriptState] || ("Script " + scriptState);
  }

  // ------------------------------------------------------------- Topic room

  async function renderRoom(candidateId) {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Opening the topic") + "</div>";
    var data = await api("/editorial/topics/" + encodeURIComponent(candidateId) + "/room");
    state.room = data;

    var brief = data.brief || {};
    var blocks = brief.blocks || [];

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Topic</p>';
    html += "<h1>" + esc(data.title) + "</h1>";
    if (data.provenance) html += '<p class="lede">' + esc(data.provenance) + "</p>";
    html += "</div>";

    if (data.timely) html += '<span class="tag is-timely">Timely</span>';
    if (data.lane_label) html += '<span class="tag is-lane">' + esc(data.lane_label) + "</span>";
    html += '<span class="tag">Version ' + (brief.version || 1) + "</span>";

    if (data.decision) {
      html += '<p class="section-hint">' + esc(decisionSentence(data.decision)) + "</p>";
    } else {
      html += '<div class="btn-row">';
      html += '<button class="btn primary" type="button" data-decide="this_week" data-id="' + esc(data.candidate_id) + '">Put in this week</button>';
      html += '<button class="btn quiet" type="button" data-decide="later" data-id="' + esc(data.candidate_id) + '">Save for later</button>';
      html += "</div>";
    }

    html += "<h2>The thinking</h2>";
    html += '<p class="section-hint">Change any block yourself. Every change is shown as a before and after before it is kept, and every version stays in the history.</p>';
    blocks.forEach(function (block) { html += briefBlock(block); });

    html += "<h2>The script</h2>";
    if (data.script) {
      html += '<p class="section-hint">Version ' + data.script.version + ", " + esc(data.script.status) + ".</p>";
      html += '<div class="actions"><button class="btn primary" type="button" data-open-script="'
           + esc(data.script.packet_id) + '">Open the script workshop</button></div>';
    } else {
      html += '<p class="section-hint">' + esc(data.script_note) + "</p>";
      html += '<div class="actions"><button class="btn primary" type="button" data-ask-script="'
           + esc(data.candidate_id) + '">Prepare the script</button></div>';
    }

    if ((data.history || []).length > 1) {
      html += "<h2>History</h2>";
      html += '<div class="card-list">';
      data.history.slice().reverse().forEach(function (entry) {
        html += '<article class="card' + (entry.is_current ? "" : " is-dim") + '">';
        html += "<h3>Version " + entry.version + (entry.is_current ? " (current)" : "") + "</h3>";
        html += '<p class="big-idea">' + esc(entry.note || originSentence(entry.origin)) + "</p>";
        html += '<span class="source">' + esc(when(entry.created_at)) + "</span>";
        if (!entry.is_current) {
          html += '<div class="actions"><button class="btn quiet" type="button" data-restore="'
               + entry.version + '">Go back to this version</button></div>';
        }
        html += "</article>";
      });
      html += "</div>";
    }

    html += "</div>";
    view.innerHTML = html;
    status("Version " + (brief.version || 1));
  }

  function originSentence(origin) {
    return {
      seed: "Arranged from the idea as the engine proposed it.",
      change_set: "Changed by you.",
      manual: "Written by you.",
      undo: "Restored from an earlier version."
    }[origin] || "";
  }

  var BLOCK_LABELS = {
    topic: "Topic", audience: "Who it helps", big_idea: "The point",
    why_now: "Why now", why_this_is_yours: "Why this is yours",
    distinctive_perspective: "Your angle", evidence: "What it rests on",
    claims_to_avoid: "Claims to avoid", takeaway: "What they should take away",
    cta: "What to ask for"
  };

  function briefBlock(block) {
    var html = '<section class="block" data-field="' + esc(block.field) + '">';
    html += "<h4>" + esc(BLOCK_LABELS[block.field] || block.field) + "</h4>";
    if (block.written) {
      html += "<p>" + esc(block.value) + "</p>";
    } else {
      html += '<p class="unwritten">Nothing written yet.</p>';
    }
    html += '<div class="block-actions">';
    html += '<button class="btn" type="button" data-change="' + esc(block.field) + '">Change</button>';
    html += "</div></section>";
    return html;
  }

  /* Editing a block does not write it. It builds a proposal, shows the
   * before and after, and waits. Same contract the assistant will use, so the
   * review sheet is proven by hand before anything speaks into it. */
  async function openChange(field) {
    var block = (state.room.brief.blocks || []).filter(function (b) { return b.field === field; })[0];
    if (!block) return;
    var label = BLOCK_LABELS[field] || field;
    var current = block.value || "";
    var next = window.prompt("Change: " + label + "\n\nWrite the new wording. Nothing is saved until you accept it.", current);
    if (next === null) return;
    if (next === current) { toast("That is what it already says."); return; }

    try {
      var proposal = await api("/editorial/change-sets", {
        method: "POST",
        body: {
          target_type: "candidate_brief",
          target_id: state.room.candidate_id,
          base_version: state.room.brief.version,
          summary: "Change " + label.toLowerCase(),
          origin: "quick_action",
          operations: [{ op: "set_field", field: field, after: next }]
        }
      });
      showProposal(proposal, label);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function showProposal(proposal, label) {
    state.pending = proposal;
    var sheet = $("talkSheet");
    $("talkTitle").textContent = "Proposed change";
    $("talkContext").textContent = proposal.summary || label || "";
    var body = $("talkBody");

    var html = "";
    if (!(proposal.validation || {}).ok) {
      ((proposal.validation || {}).issues || []).forEach(function (issue) {
        html += '<p class="notice is-bad">' + esc(issue.message) + "</p>";
      });
    }
    (proposal.operations || []).forEach(function (op) {
      html += '<div class="op">';
      html += '<div class="diff">';
      html += '<div class="diff-half diff-before"><h5>Before</h5><p>'
           + (op.before === null || op.before === undefined || op.before === ""
              ? '<span class="unwritten">Nothing written yet.</span>'
              : esc(op.before)) + "</p></div>";
      html += '<div class="diff-half diff-after"><h5>After</h5><p>' + esc(op.after) + "</p></div>";
      html += "</div>";
      if (op.rationale) html += '<p class="diff-why">' + esc(op.rationale) + "</p>";
      html += "</div>";
    });
    body.innerHTML = html;

    // The review sheet is a decision, not a conversation.
    sheet.querySelector(".sheet-foot").innerHTML =
        '<div class="btn-row">'
      + '<button class="btn primary" type="button" id="acceptChange">Use the new version</button>'
      + '<button class="btn quiet" type="button" id="rejectChange">Keep what I have</button>'
      + "</div>";
    $("acceptChange").addEventListener("click", acceptPending);
    $("rejectChange").addEventListener("click", rejectPending);
    sheet.hidden = false;
  }

  async function acceptPending() {
    if (!state.pending) return;
    var button = $("acceptChange");
    button.disabled = true;
    button.textContent = "Saving the new version";
    try {
      await api("/editorial/change-sets/" + state.pending.id + "/apply", { method: "POST", body: {} });
      closeSheet();
      toast("Saved. The previous version is in the history.");
      await render();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Use the new version";
      // A conflict is the one error worth keeping the sheet open for.
      toast(error.message, true);
      if (error.status === 409) { closeSheet(); await render(); }
    }
  }

  async function rejectPending() {
    if (!state.pending) return;
    try { await api("/editorial/change-sets/" + state.pending.id + "/reject", { method: "POST" }); }
    catch (error) { /* Turning it down must always succeed from his side. */ }
    closeSheet();
    toast("Kept what you had.");
  }

  function closeSheet() {
    var sheet = $("talkSheet");
    sheet.hidden = true;
    state.pending = null;
  }

  // -------------------------------------------------------- Script workshop

  async function renderWorkshop(packetId) {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Opening the script") + "</div>";
    var data = await api("/editorial/packets/" + encodeURIComponent(packetId) + "/workshop");
    state.workshop = data;

    var tabs = [
      { key: "outline", label: "Outline" },
      { key: "script", label: "Full script" },
      { key: "openings", label: "Openings" },
      { key: "posts", label: "Post versions" }
    ];

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Script workshop</p>';
    html += "<h1>Version " + data.version + "</h1>";
    html += '<p class="lede">' + esc(data.outline.length) + " " + plural(data.outline.length, "point")
         + ", " + data.script.length + " " + plural(data.script.length, "line") + ".</p></div>";

    if (data.frozen_reason) html += '<p class="notice">' + esc(data.frozen_reason) + "</p>";
    if ((data.public_safety || {}).status === "issues") {
      html += '<p class="notice is-bad">This version has '
           + (data.public_safety.issues || []).length + " flagged "
           + plural((data.public_safety.issues || []).length, "line") + ". Check before recording.</p>";
    }

    html += '<div class="chips" role="group" aria-label="Parts of the script">';
    tabs.forEach(function (tab) {
      html += '<button class="chip" type="button" data-wtab="' + tab.key + '" aria-pressed="'
           + (state.workshopTab === tab.key ? "true" : "false") + '">' + esc(tab.label) + "</button>";
    });
    html += "</div>";

    if (state.workshopTab === "outline") {
      html += listBlocks(data.outline, "Point");
    } else if (state.workshopTab === "script") {
      html += listBlocks(data.script, "Line");
    } else if (state.workshopTab === "openings") {
      var openings = data.openings || {};
      html += '<p class="section-hint">Three at a time. Asking for more re-ranks them rather than making the list longer.</p>';
      (openings.shown || []).forEach(function (hook, index) {
        html += '<section class="block">';
        html += "<h4>" + (index === 0 ? "Recommended" : "Option " + (index + 1))
             + (hook.id === openings.selected_hook_id ? " &middot; in use" : "") + "</h4>";
        html += "<p>" + esc(hook.text || hook.line || "") + "</p>";
        if (hook.viewer_question) html += '<p class="diff-why">' + esc(hook.viewer_question) + "</p>";
        html += "</section>";
      });
      if (!(openings.shown || []).length) {
        html += '<div class="empty"><strong>No openings yet</strong>They are written with the script.</div>';
      }
    } else {
      var posts = data.posts || {};
      html += '<section class="block"><h4>Facebook</h4><p>'
           + (posts.facebook ? esc(posts.facebook) : '<span class="unwritten">Not written.</span>') + "</p></section>";
      html += '<section class="block"><h4>LinkedIn</h4><p>'
           + (posts.linkedin ? esc(posts.linkedin) : '<span class="unwritten">Not written.</span>') + "</p></section>";
    }

    html += '<div class="actions" style="margin-top:22px">';
    html += '<button class="btn" type="button" data-open-room="' + esc(data.candidate_id) + '">Open the topic</button>';
    html += '<a class="btn primary" href="' + prefix + '/record">Go to the studio</a>';
    html += "</div></div>";
    view.innerHTML = html;
    status("Script version " + data.version);
  }

  function listBlocks(items, label) {
    if (!items.length) {
      return '<div class="empty"><strong>Nothing here yet</strong>This part of the script has not been written.</div>';
    }
    var html = "";
    items.forEach(function (text, index) {
      html += '<section class="block"><h4>' + esc(label) + " " + (index + 1) + "</h4><p>"
           + esc(text) + "</p></section>";
    });
    return html;
  }

  // ---------------------------------------------------------------- Library

  async function renderLibrary() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading what you have recorded") + "</div>";
    var data = await api("/production/library?filter=" + encodeURIComponent(state.libraryFilter));
    state.library = data;

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Editorial workspace</p><h1>Library</h1>';
    html += '<p class="lede">Everything you have recorded, and what happened to it.</p></div>';

    html += '<div class="chips" role="group" aria-label="Filter recordings">';
    (data.filters || []).forEach(function (f) {
      html += '<button class="chip" type="button" data-libfilter="' + esc(f.key) + '" aria-pressed="'
           + (f.key === data.filter ? "true" : "false") + '">' + esc(f.label) + "</button>";
    });
    html += "</div>";

    var items = data.items || [];
    if (!items.length) {
      html += '<div class="empty"><strong>Nothing recorded yet</strong>'
            + "Recordings appear here as soon as the studio finishes uploading them.</div>";
    } else {
      html += '<div class="card-list">';
      items.forEach(function (item) { html += libraryCard(item); });
      html += "</div>";
    }
    html += "</div>";
    view.innerHTML = html;
    status(items.length + " " + plural(items.length, "recording"));
  }

  function libraryCard(item) {
    var html = '<article class="card">';
    html += "<h3>" + esc(item.title) + "</h3>";
    html += '<span class="source">' + esc(when(item.recorded_at))
         + (item.duration_s ? " &middot; " + clock(item.duration_s) : "") + "</span>";
    html += '<p class="big-idea">' + esc(item.state_sentence) + "</p>";
    (item.issues || []).forEach(function (issue) {
      html += '<p class="notice is-bad">' + esc(issue) + "</p>";
    });
    if (item.open_requests) {
      html += '<span class="tag">' + item.open_requests + " open "
           + plural(item.open_requests, "request") + "</span>";
    }

    // Only actions with a real destination. The server already decided which.
    html += '<div class="actions">';
    (item.actions || []).forEach(function (action) {
      if (action.key === "watch_raw") {
        html += '<a class="btn" href="' + apiV1 + "/production/uploads/" + esc(item.upload_id) + '/video">' + esc(action.label) + "</a>";
      } else if (action.key === "watch_edit") {
        html += '<a class="btn primary" href="' + apiV1 + "/production/uploads/" + esc(item.upload_id) + '/edited">' + esc(action.label) + "</a>";
      } else if (action.key === "captions") {
        html += '<a class="btn quiet" href="' + apiV1 + "/production/uploads/" + esc(item.upload_id) + '/captions.srt">' + esc(action.label) + "</a>";
      } else if (action.key === "request_edit") {
        html += '<button class="btn" type="button" data-edit-request="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "re_record" && item.candidate_id) {
        html += '<a class="btn quiet" href="' + prefix + '/record">' + esc(action.label) + "</a>";
      }
    });
    html += "</div></article>";
    return html;
  }

  async function askEditRequest(uploadId) {
    var text = window.prompt("What should change about this video?\n\nSay it the way you would say it to an editor.");
    if (text === null || !text.trim()) return;
    try {
      await api("/production/recordings/" + encodeURIComponent(uploadId) + "/edit-requests", {
        method: "POST",
        body: { request: text.trim(), scope: "whole" }
      });
      toast("Asked. It is on the record against this video.");
      await render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ----------------------------------------------------------------- events

  async function decide(candidateId, decision) {
    try {
      var result = await api("/editorial/topics/" + encodeURIComponent(candidateId) + "/decide", {
        method: "POST", body: { decision: decision }
      });
      if (decision === "this_week" && result.placed) {
        toast(result.placed.slot === "reserve"
          ? "This week is full, so it went to the reserve list."
          : "In this week's list at number " + result.placed.rank + ".");
      } else {
        toast(decisionSentence(decision));
      }
      await render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function moveItem(candidateId, action, slot) {
    var body = { move: { candidate_id: candidateId, action: action },
                 expected_revision: state.week ? state.week.revision : null };
    if (slot) body.move.slot = slot;
    try {
      state.week = await api("/editorial/weeks/current/lineup", { method: "PATCH", body: body });
      await render();
    } catch (error) {
      toast(error.message, true);
      if (error.status === 409) await render();
    }
  }

  async function askForScript(candidateId) {
    try {
      await api("/editorial/candidates/" + encodeURIComponent(candidateId) + "/packet", { method: "POST" });
      toast("Asked. The script is written on your PC worker; it takes a few minutes.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-go],[data-filter],[data-libfilter],[data-decide],"
      + "[data-open-room],[data-open-script],[data-move],[data-slot],[data-remove],"
      + "[data-ask-script],[data-change],[data-restore],[data-wtab],[data-edit-request]");
    if (!target) return;
    var d = target.dataset;

    if (d.go !== undefined) { event.preventDefault(); go(d.go); return; }
    if (d.filter !== undefined) { state.topicFilter = d.filter; render(); return; }
    if (d.libfilter !== undefined) { state.libraryFilter = d.libfilter; render(); return; }
    if (d.wtab !== undefined) { state.workshopTab = d.wtab; render(); return; }
    if (d.decide !== undefined) { decide(d.id, d.decide); return; }
    if (d.openRoom !== undefined) { go("/topics/" + d.openRoom); return; }
    if (d.openScript !== undefined) { go("/scripts/" + d.openScript); return; }
    if (d.move !== undefined) { moveItem(d.id, d.move); return; }
    if (d.slot !== undefined) { moveItem(d.id, "slot", d.slot); return; }
    if (d.remove !== undefined) { moveItem(d.remove, "remove"); return; }
    if (d.askScript !== undefined) { askForScript(d.askScript); return; }
    if (d.change !== undefined) { openChange(d.change); return; }
    if (d.restore !== undefined) { restore(parseInt(d.restore, 10)); return; }
    if (d.editRequest !== undefined) { askEditRequest(d.editRequest); return; }
  });

  async function restore(version) {
    try {
      await api("/editorial/versions/candidate_brief/" + state.room.candidate_id + "/restore", {
        method: "POST", body: { to_version: version }
      });
      toast("Restored. It is saved as a new version, so nothing was lost.");
      await render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // Bottom nav uses real links, so a long press can open one in a new tab. Only
  // the in-app routes are intercepted; /record is a different page on purpose.
  $("bottomNav").addEventListener("click", function (event) {
    var link = event.target.closest("a");
    if (!link || link.dataset.route === "record") return;
    event.preventDefault();
    go(link.getAttribute("href"));
  });

  $("talkClose").addEventListener("click", function () {
    if (state.pending) { rejectPending(); return; }
    closeSheet();
  });

  // Escape closes the sheet. An outside tap does not: there is a decision in it.
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !$("talkSheet").hidden) {
      if (state.pending) rejectPending(); else closeSheet();
    }
  });

  var READER_SIZES = ["normal", "large", "largest"];
  $("readerSize").addEventListener("click", function () {
    var current = document.body.dataset.reader || "normal";
    var next = READER_SIZES[(READER_SIZES.indexOf(current) + 1) % READER_SIZES.length];
    document.body.dataset.reader = next;
    try { localStorage.setItem("tce-workspace-reader", next); } catch (e) { /* private mode */ }
  });

  window.addEventListener("popstate", function () { render(); });

  // ------------------------------------------------------------------ boot

  async function render() {
    var route = parse();
    state.route = route.name;
    setChrome(route);
    try {
      if (route.name === "today") await renderToday();
      else if (route.name === "topics") await renderTopics();
      else if (route.name === "week") await renderWeek();
      else if (route.name === "library") await renderLibrary();
      else if (route.name === "room") await renderRoom(route.id);
      else if (route.name === "workshop") await renderWorkshop(route.id);
      if (route.name === "room") $("pageTitle").textContent = "Topic";
    } catch (error) {
      $("view").innerHTML = '<div class="page"><div class="empty"><strong>Could not open this</strong>'
        + esc(error.message) + '</div><div class="actions">'
        + '<button class="btn" type="button" data-go="/today">Back to Today</button></div></div>';
      status("Could not load");
    }
  }

  try {
    var saved = localStorage.getItem("tce-workspace-reader");
    if (saved) document.body.dataset.reader = saved;
  } catch (e) { /* private mode */ }

  render();
})();
