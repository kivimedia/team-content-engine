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
    pending: null,     // a change set awaiting his yes or no
    thread: null,      // the open conversation
    talkMode: "discuss",
    talkTimer: null,
    talkContext: null, // {type, id, label} for the current page
    notifyConfig: null
  };

  // The conversation footer markup, captured before anything replaces it. The
  // review sheet reuses the same shell with different controls, so it has to be
  // able to put this back.
  var TALK_FOOTER = null;

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
    // Best effort. Today must still paint if the push config cannot be read.
    try { state.notifyConfig = await api("/editorial/notifications/config"); }
    catch (e) { state.notifyConfig = null; }

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

    // Offered right under the counts, where the waiting is: a script takes
    // minutes and today it finishes on a page he is not looking at.
    html += notifyRow(state.notifyConfig);

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

    var topics = data.topics || [];
    if (!topics.length) {
      if (data.withheld_note) {
        html += '<p class="notice">' + esc(data.withheld_note) + "</p>";
      }
      html += '<div class="empty"><strong>Nothing here</strong>'
            + esc(data.filter === "best"
                 ? "Everything is decided. The next weekly run collects new evidence."
                 : "No ideas match this filter.") + "</div>";
    } else {
      // The count and what was held back are one line, not a line plus a banner.
      // Both are still said; they just do not cost him the first card.
      html += '<p class="section-hint">' + topics.length + " of " + data.total + " shown"
           + (data.withheld_note ? ". " + esc(data.withheld_note) : "") + "</p>";
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
    html += '<button class="btn quiet" type="button" data-rewrite="' + esc(block.field) + '">Ask for a rewrite</button>';
    html += "</div></section>";
    return html;
  }

  /* Quick rewrites are the same conversation, with the instruction written for
   * him and the field named precisely. No second backend path: whatever comes
   * back is a proposal, reviewed exactly like one he typed himself. */
  var QUICK_ACTIONS = [
    ["practical", "Make it more practical"],
    ["plain", "Make it less corporate"],
    ["me", "Make it sound more like me"],
    ["shorter", "Make it shorter"],
    ["opinion", "Make it more opinionated"],
    ["coaching", "Tie it harder to coaching"],
    ["nosell", "Take the sales angle out"]
  ];

  var QUICK_INSTRUCTIONS = {
    practical: "more practical: say what to actually do, not what to understand",
    plain: "less corporate: plain words a coach would say out loud",
    me: "more like me: direct, opinionated, no hedging, no consultant vocabulary",
    shorter: "shorter: same point, fewer words, nothing padded",
    opinion: "more opinionated: take a clear position instead of presenting options",
    coaching: "tied harder to coaching: make the cost to their clients explicit",
    nosell: "with the sales angle removed: teach the point, do not pitch"
  };

  async function openRewrite(field) {
    var label = BLOCK_LABELS[field] || field;
    state.talkMode = "propose";
    var sheet = $("talkSheet");
    $("talkTitle").textContent = "Ask for a rewrite";
    $("talkContext").textContent = label;
    $("talkBody").innerHTML = working("Opening the conversation");
    sheet.hidden = false;

    try {
      state.thread = await api("/editorial/threads", {
        method: "POST",
        body: { context_type: "topic", context_id: state.room.candidate_id,
                label: state.room.title }
      });
    } catch (error) {
      $("talkBody").innerHTML = '<p class="notice is-bad">' + esc(error.message) + "</p>";
      return;
    }

    // Quick actions replace the mode row: in here the mode is not a choice, it
    // is the whole point, so offering Discuss would only be a way to get nothing.
    var foot = sheet.querySelector(".sheet-foot");
    var chips = '<div class="chips">' + QUICK_ACTIONS.map(function (a) {
      return '<button class="chip" type="button" data-quick="' + a[0] + '">' + esc(a[1]) + "</button>";
    }).join("") + "</div>";
    foot.innerHTML = chips
      + '<textarea id="talkInput" rows="2" placeholder="Or say exactly what you want changed..."></textarea>'
      + '<div class="talk-controls">'
      + '<button class="btn" id="voiceBtn" type="button" aria-pressed="false">Speak</button>'
      + '<button class="btn quiet" id="speakBtn" type="button" aria-pressed="false">Read aloud</button>'
      + '<button class="btn primary" id="talkSend" type="button">Ask for it</button>'
      + '</div>';

    foot.querySelectorAll("[data-quick]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        sendRewrite(field, label, QUICK_INSTRUCTIONS[chip.dataset.quick]);
      });
    });
    $("talkSend").addEventListener("click", function () {
      var custom = $("talkInput").value.trim();
      if (!custom) { toast("Pick one, or say what you want changed."); return; }
      if (voice.listening) stopVoice();
      sendRewrite(field, label, custom);
    });
    bindVoiceControls(foot);

    renderTalk();
  }

  async function sendRewrite(field, label, instruction) {
    // The field key is named explicitly so the model cannot drift onto another
    // block, and `changes.propose` refuses it if it does anyway.
    var text = 'Rewrite the "' + label + '" block (field key `' + field + '`) to be '
             + instruction + ". Propose a change to that field only.";
    $("talkBody").innerHTML = working("Asking for a rewrite of " + label.toLowerCase());
    try {
      var result = await api("/editorial/threads/" + state.thread.thread_id + "/messages", {
        method: "POST", body: { text: text, mode: "propose" }
      });
      state.thread.messages = (state.thread.messages || []).concat(result.messages);
      renderTalk();
      startTalkPoll();
    } catch (error) {
      toast(error.message, true);
    }
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
    if (voice.listening) stopVoice();
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) { /**/ } }
    sheet.hidden = true;
    state.pending = null;
    state.thread = null;
    if (state.talkTimer) { clearInterval(state.talkTimer); state.talkTimer = null; }
  }

  // ----------------------------------------------------------- conversation

  /* The assistant runs on the desktop worker at roughly one job a minute, so
   * every turn is: store it, show it as thinking, poll. There is no spinner in
   * here without a sentence attached to it. */

  function restoreTalkFooter() {
    var foot = $("talkSheet").querySelector(".sheet-foot");
    foot.innerHTML = TALK_FOOTER;
    foot.querySelectorAll("[data-mode]").forEach(function (chip) {
      chip.setAttribute("aria-pressed", chip.dataset.mode === state.talkMode ? "true" : "false");
      chip.addEventListener("click", function () {
        state.talkMode = chip.dataset.mode;
        foot.querySelectorAll("[data-mode]").forEach(function (c) {
          c.setAttribute("aria-pressed", c.dataset.mode === state.talkMode ? "true" : "false");
        });
      });
    });
    var send = foot.querySelector("#talkSend");
    if (send) send.addEventListener("click", sendTalk);
    bindVoiceControls(foot);
  }

  /* The footer markup is rebuilt whenever the sheet changes purpose, so the
     voice controls are bound from one place rather than once at boot. */
  function bindVoiceControls(foot) {
    var mic = foot.querySelector("#voiceBtn");
    if (mic) {
      if (!speechSupported() || cameraBusy()) {
        mic.disabled = true;
        mic.title = cameraBusy()
          ? "The studio is recording. Voice waits until the take is finished."
          : "This browser cannot listen.";
      }
      mic.addEventListener("click", startVoice);
    }
    var speaker = foot.querySelector("#speakBtn");
    if (speaker) {
      var on = false;
      try { on = localStorage.getItem("tce-speak-replies") === "1"; } catch (e) { /**/ }
      speaker.setAttribute("aria-pressed", on ? "true" : "false");
      speaker.addEventListener("click", toggleSpeakReplies);
    }
    paintVoiceButton();
  }

  async function openTalk() {
    var context = state.talkContext;
    if (!context) return;
    var sheet = $("talkSheet");
    $("talkTitle").textContent = "Talk about this";
    $("talkContext").textContent = context.label || "";
    $("talkBody").innerHTML = working("Opening the conversation");
    restoreTalkFooter();
    sheet.hidden = false;
    try {
      state.thread = await api("/editorial/threads", {
        method: "POST",
        body: { context_type: context.type, context_id: context.id, label: context.label }
      });
      state.talkMode = state.thread.last_mode === "propose" ? "propose" : "discuss";
      restoreTalkFooter();
      renderTalk();
      if (state.thread.pending) startTalkPoll();
    } catch (error) {
      $("talkBody").innerHTML = '<p class="notice is-bad">' + esc(error.message) + "</p>";
    }
  }

  function renderTalk() {
    var body = $("talkBody");
    var messages = (state.thread && state.thread.messages) || [];
    if (!messages.length) {
      body.innerHTML = '<div class="empty"><strong>Nothing said yet</strong>'
        + "Think out loud. In Discuss nothing changes, whatever you ask for.</div>";
      return;
    }
    var html = "";
    messages.forEach(function (m) {
      var who = m.role === "editor" ? "You" : "TCE";
      html += '<div class="msg is-' + esc(m.role)
           + (m.status === "queued" ? " is-queued" : "") + '">';
      html += '<div class="who">' + esc(who) + "</div>";
      html += '<div class="bubble">';
      if (m.status === "queued") {
        html += esc(m.status_detail || "Thinking about this.");
      } else if (m.status === "failed") {
        html += esc(m.status_detail || "That turn did not finish.");
      } else {
        html += esc(m.text);
      }
      html += "</div>";
      if (m.change_set_id) {
        html += '<div class="actions"><button class="btn primary" type="button" '
             + 'data-review="' + esc(m.change_set_id) + '">Review the change</button></div>';
      }
      html += "</div>";
    });
    body.innerHTML = html;
    body.scrollTop = body.scrollHeight;
  }

  function startTalkPoll() {
    if (state.talkTimer) clearInterval(state.talkTimer);
    var started = Date.now();
    state.talkTimer = setInterval(async function () {
      if (!state.thread || $("talkSheet").hidden) {
        clearInterval(state.talkTimer); state.talkTimer = null; return;
      }
      try {
        var fresh = await api("/editorial/threads/" + state.thread.thread_id);
        var wasPending = state.thread.pending;
        state.thread = fresh;
        renderTalk();
        if (!fresh.pending) {
          clearInterval(state.talkTimer); state.talkTimer = null;
          if (wasPending) {
            var last = (fresh.messages || []).filter(function (m) {
              return m.role === "assistant" && m.status === "complete";
            }).pop();
            if (last) speak(last.text);
          }
        }
      } catch (error) { /* a dropped poll is not worth a toast; the next one retries */ }
      // Five minutes is well past the worker's usual minute. Stop guessing and
      // let the row say what it says.
      if (Date.now() - started > 300000) {
        clearInterval(state.talkTimer); state.talkTimer = null;
      }
    }, 4000);
  }

  async function sendTalk() {
    var input = $("talkInput");
    var text = input && input.value.trim();
    if (!text) { toast("Say something first."); return; }
    var send = $("talkSend");
    if (send) { send.disabled = true; send.textContent = "Sending"; }
    try {
      var result = await api("/editorial/threads/" + state.thread.thread_id + "/messages", {
        method: "POST", body: { text: text, mode: state.talkMode }
      });
      input.value = "";
      if (voice.listening) stopVoice();
      state.thread.messages = (state.thread.messages || []).concat(result.messages);
      renderTalk();
      startTalkPoll();
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (send) { send.disabled = false; send.textContent = "Send"; }
    }
  }

  // ------------------------------------------------------------------ voice

  /* Voice is an input method over the conversation contract, not a second
   * assistant. That is the plan's own decision and it is also the only honest
   * design here: every model call in TCE is a job leased by the desktop worker
   * at about one a minute, so there is no sub-second back-and-forth to be had.
   * What voice removes is the typing, which is the part that is actually hard
   * while walking with a phone at arm's length.
   *
   * So: speak, watch the words appear, FIX them if the recogniser misheard, and
   * send. Everything after that is the path already proven by typing - discuss
   * changes nothing, propose produces a diff you accept.
   *
   * Recognition runs in the browser. No audio leaves the page to us, nothing is
   * stored, and it costs nothing.
   */

  var CAMERA_FLAG = "tce-camera-active";

  function cameraBusy() {
    try {
      var stamp = parseInt(localStorage.getItem(CAMERA_FLAG) || "0", 10);
      // A stale flag from a tab that died without firing pagehide must not lock
      // voice out permanently. Anything older than an hour is not a live take.
      return stamp > 0 && (Date.now() - stamp) < 3600000;
    } catch (e) { return false; }
  }

  function speechSupported() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  var voice = { rec: null, listening: false, base: "", heard: "" };

  function stopVoice(reason) {
    if (voice.rec) {
      try { voice.rec.onend = null; voice.rec.stop(); } catch (e) { /* already dead */ }
    }
    voice.rec = null;
    voice.listening = false;
    paintVoiceButton();
    if (reason) toast(reason);
  }

  function paintVoiceButton() {
    var btn = $("voiceBtn");
    if (!btn) return;
    btn.setAttribute("aria-pressed", voice.listening ? "true" : "false");
    btn.textContent = voice.listening ? "Stop listening" : "Speak";
  }

  function startVoice() {
    if (voice.listening) { stopVoice(); return; }
    if (!speechSupported()) {
      toast("This browser cannot listen. Type it instead.", true);
      return;
    }
    if (cameraBusy()) {
      toast("The studio is recording. Voice waits until the take is finished.", true);
      return;
    }
    var input = $("talkInput");
    var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    var rec = new Recognition();
    rec.lang = "en-GB";
    rec.continuous = true;
    // Interim results are the point: he has to see it getting him right or
    // wrong while he is still talking, not after.
    rec.interimResults = true;

    // Keep whatever he had already typed; voice appends to it.
    voice.base = (input.value || "").trim();
    voice.heard = "";

    rec.onresult = function (event) {
      var settled = "";
      var pending = "";
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) settled += chunk;
        else pending += chunk;
      }
      if (settled) voice.heard = (voice.heard + " " + settled).trim();
      var joined = (voice.base + " " + voice.heard + " " + pending).trim();
      input.value = joined;
      // The transcript is an ordinary textarea, so correcting it is just
      // editing. The acceptance test asks for visible AND correctable.
      input.scrollTop = input.scrollHeight;
    };

    rec.onerror = function (event) {
      if (event.error === "no-speech" || event.error === "aborted") return;
      if (event.error === "not-allowed") {
        stopVoice("The microphone is blocked in your browser settings.");
        return;
      }
      // Network loss is the interesting one: what he already said stays in the
      // box and he can finish by typing.
      stopVoice("Lost the microphone. What you said is still in the box.");
    };

    rec.onend = function () {
      // Some browsers end the session on a pause; restart while he still wants
      // to talk, unless the camera claimed the mic in the meantime.
      if (voice.listening && !cameraBusy()) {
        try { rec.start(); return; } catch (e) { /* fall through to stopped */ }
      }
      voice.listening = false;
      paintVoiceButton();
    };

    try {
      rec.start();
    } catch (e) {
      toast("Could not start listening: " + e.message, true);
      return;
    }
    voice.rec = rec;
    voice.listening = true;
    paintVoiceButton();
  }

  /* Say the reply out loud. Browser speech, so it costs nothing and needs no
   * key. Off unless he turned it on, because a phone that starts talking in a
   * quiet room is a worse surprise than a silent one. */
  function speak(text) {
    if (!window.speechSynthesis) return;
    var on = false;
    try { on = localStorage.getItem("tce-speak-replies") === "1"; } catch (e) { /**/ }
    if (!on || !text) return;
    try {
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      window.speechSynthesis.speak(utterance);
    } catch (e) { /* never let speech break the page */ }
  }

  function toggleSpeakReplies() {
    var on = false;
    try {
      on = localStorage.getItem("tce-speak-replies") === "1";
      localStorage.setItem("tce-speak-replies", on ? "0" : "1");
    } catch (e) { /**/ }
    if (on && window.speechSynthesis) window.speechSynthesis.cancel();
    toast(on ? "Replies stay silent." : "Replies will be read out loud.");
    var btn = $("speakBtn");
    if (btn) btn.setAttribute("aria-pressed", on ? "false" : "true");
  }

  async function reviewFromThread(changeSetId) {
    try {
      var proposal = await api("/editorial/change-sets/" + changeSetId);
      if (proposal.state !== "proposed") {
        toast("That one is already " + proposal.state + ".");
        return;
      }
      showProposal(proposal, proposal.summary);
    } catch (error) {
      toast(error.message, true);
    }
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

  // ---------------------------------------------------------- notifications

  /* Why this is a button he presses and not something that happens on load: a
   * permission prompt he did not ask for gets denied once and then the browser
   * never asks again. It is offered where the waiting actually hurts - Today,
   * under the counts - and it says plainly when it cannot work. */

  function base64ToUint8(base64) {
    var padded = (base64 + "=".repeat((4 - base64.length % 4) % 4))
      .replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(padded);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // iOS delivers web push only to a site added to the Home Screen. Saying so is
  // the difference between a feature that looks broken and one he can turn on.
  function iosNeedsInstall() {
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
      || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    var installed = window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true;
    return ios && !installed;
  }

  function notifyState() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return { can: false, why: "This browser cannot do notifications." };
    }
    if (iosNeedsInstall()) {
      return {
        can: false,
        why: "On iPhone, add this page to your Home Screen first (Share, then Add to "
           + "Home Screen). Notifications only work from there."
      };
    }
    if (Notification.permission === "denied") {
      return { can: false, why: "Notifications are blocked in your browser settings." };
    }
    return { can: true, why: "" };
  }

  async function enableNotifications() {
    var status = notifyState();
    if (!status.can) { toast(status.why, true); return; }
    try {
      var config = await api("/editorial/notifications/config");
      if (!config.available || !config.public_key) {
        toast(config.reason || "Push is not configured on the server.", true);
        return;
      }
      var permission = await Notification.requestPermission();
      if (permission !== "granted") { toast("Left off."); return; }

      var registration = await navigator.serviceWorker.register(
        prefix + "/workspace-sw.js", { scope: prefix + "/" }
      );
      await navigator.serviceWorker.ready;
      var existing = await registration.pushManager.getSubscription();
      var subscription = existing || await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64ToUint8(config.public_key)
      });
      var json = subscription.toJSON();
      await api("/editorial/notifications/subscribe", {
        method: "POST",
        body: {
          endpoint: json.endpoint,
          p256dh: json.keys.p256dh,
          auth: json.keys.auth,
          user_agent: navigator.userAgent
        }
      });
      toast("On. You will get a buzz when a script or an edit is ready.");
      await render();
    } catch (error) {
      toast("Could not turn them on: " + error.message, true);
    }
  }

  async function disableNotifications() {
    try {
      var registration = await navigator.serviceWorker.getRegistration(prefix + "/");
      var subscription = registration && await registration.pushManager.getSubscription();
      if (subscription) {
        await api("/editorial/notifications/unsubscribe", {
          method: "POST", body: { endpoint: subscription.endpoint }
        });
        await subscription.unsubscribe();
      }
      toast("Off.");
      await render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function notifyRow(config) {
    if (!config) return "";
    var status = notifyState();
    if (config.subscribed) {
      return '<p class="section-hint">Notifications are on for this device. '
           + '<button class="btn quiet" type="button" data-notify="off" '
           + 'style="min-height:38px;margin-left:6px">Turn off</button></p>';
    }
    if (!status.can) {
      return '<p class="notice">' + esc(status.why) + "</p>";
    }
    if (!config.available) return "";
    return '<div class="actions"><button class="btn quiet" type="button" data-notify="on">'
         + "Tell me when a script is ready</button></div>";
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
    if (d.review !== undefined) { reviewFromThread(d.review); return; }
    if (d.rewrite !== undefined) { openRewrite(d.rewrite); return; }
    if (d.notify !== undefined) {
      if (d.notify === "on") enableNotifications(); else disableNotifications();
      return;
    }
  });

  $("talkFab").addEventListener("click", openTalk);

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

  /* The nav ships absolute hrefs so the markup reads plainly, but this page is
   * served at BOTH /today and /tce/today (bot.kivimedia.co mounts the whole app
   * under /tce). The in-app routes survive because `go()` prepends the prefix;
   * Record does not, because it is a real navigation to another page and is
   * deliberately not intercepted. Without this it landed on
   * bot.kivimedia.co/record, which is the KM BOT app and a 404. */
  Array.prototype.forEach.call($("bottomNav").querySelectorAll("a"), function (a) {
    a.setAttribute("href", prefix + a.getAttribute("href"));
  });

  // Bottom nav uses real links, so a long press can open one in a new tab. Only
  // the in-app routes are intercepted; /record is a different page on purpose.
  $("bottomNav").addEventListener("click", function (event) {
    var link = event.target.closest("a");
    if (!link || link.dataset.route === "record") return;
    event.preventDefault();
    // From the route, not the href: the href now carries the prefix and `go`
    // adds it again. The four in-app routes are named exactly like their paths.
    go("/" + link.dataset.route);
  });

  /* Closing is not deciding. A proposal he walks away from stays `proposed` and
   * shows up in Today's "changes to review", which is what he wants: only the
   * explicit "Keep what I have" turns one down. */
  $("talkClose").addEventListener("click", closeSheet);

  // Escape closes the sheet. An outside tap does not: there is a decision in it.
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !$("talkSheet").hidden) closeSheet();
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

  /* The button appears only where there is a specific thing to discuss, and its
   * label names that thing. A conversation that does not know what is on screen
   * is a general chat window, which is the thing this deliberately is not. */
  function setTalkContext(route) {
    var fab = $("talkFab");
    if (route.name === "room" && state.room) {
      state.talkContext = { type: "topic", id: route.id, label: state.room.title };
    } else if (route.name === "workshop" && state.workshop) {
      state.talkContext = {
        type: "packet", id: route.id,
        label: "Script version " + state.workshop.version
      };
    } else if (route.name === "week") {
      state.talkContext = { type: "week", id: null, label: "This week's list" };
    } else if (route.name === "topics") {
      // The editorial room: cross-topic planning, no single object to change.
      state.talkContext = { type: "room", id: null, label: "Editorial room" };
    } else {
      state.talkContext = null;
    }
    fab.hidden = !state.talkContext;
    // The bar is fixed, so the page has to reserve its height or the last card
    // sits underneath it.
    document.body.classList.toggle("has-talk", !!state.talkContext);
    if (state.talkContext) {
      fab.textContent = state.talkContext.type === "room"
        ? "Talk it through" : "Talk about this";
    }
  }

  async function render() {
    var route = parse();
    state.route = route.name;
    setChrome(route);
    $("talkFab").hidden = true;
    document.body.classList.remove("has-talk");
    try {
      if (route.name === "today") await renderToday();
      else if (route.name === "topics") await renderTopics();
      else if (route.name === "week") await renderWeek();
      else if (route.name === "library") await renderLibrary();
      else if (route.name === "room") await renderRoom(route.id);
      else if (route.name === "workshop") await renderWorkshop(route.id);
      if (route.name === "room") $("pageTitle").textContent = "Topic";
      setTalkContext(route);
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

  TALK_FOOTER = $("talkSheet").querySelector(".sheet-foot").innerHTML;

  render();
})();
