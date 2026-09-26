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
    { name: "settings", pattern: /^\/settings\/?$/,            title: "Settings" },
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
    /* The studio is a different page, not one of this shell's routes. Pushing
       it would change the URL and then re-render Today, because `parse` has no
       pattern for /record - the address bar would say one thing and the screen
       another. Anything outside the shell gets a real navigation. */
    if (path.indexOf("/record") === 0) {
      window.location.href = prefix + path;
      return;
    }
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
    var voiceItems = await voiceActivity();
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

    // What the voice agent changed, right where he lands after a call.
    html += voicePanel(voiceItems);

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
      var readyFirst = primary.filter(function (i) { return i.script_state === "ready"; })[0];
      if (readyFirst) {
        html += '<div class="actions"><a class="btn primary" href="' + prefix
             + "/record?candidate=" + esc(readyFirst.candidate_id)
             + '">Start recording</a></div>';
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

  // ------------------------------------------------------ Changes by voice

  /* Everything the voice agent wrote in the last day, newest first, in plain
   * words, each with the one button that takes it back. It applies what he
   * agreed to at once, so this list is the review: nothing it did is hidden. */
  async function voiceActivity() {
    try {
      var data = await api("/editorial/voice/activity?hours=24");
      return (data && data.items) || [];
    } catch (e) {
      return [];  // The page must paint even if this cannot be read.
    }
  }

  function voiceTime(iso) {
    if (!iso) return "";
    // The server's timestamps are UTC without a zone mark.
    var d = new Date(/Z$|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function voicePanel(items) {
    if (!items || !items.length) return "";
    var html = '<section class="voice-panel" id="voicePanel" aria-labelledby="voicePanelTitle">';
    html += '<h2 id="voicePanelTitle">Changes by voice</h2>';
    html += '<p class="section-hint">What the voice agent changed in the last 24 hours, newest first. '
         + "Undo takes one back and keeps both versions in the history.</p>";
    html += '<ul class="voice-list">';
    items.forEach(function (item) {
      var done = item.kind === "change" && item.undone;
      html += '<li class="voice-item' + (done ? " is-undone" : "") + '">';
      html += '<div class="voice-text">';
      html += '<span class="voice-meta">' + esc(voiceTime(item.at))
           + (item.title ? " - " + esc(item.title) : "") + "</span>";
      (item.lines || []).forEach(function (line) {
        html += "<p>" + esc(line) + "</p>";
      });
      if (done) html += '<p class="voice-state">Undone.</p>';
      if (item.is_undo) html += '<p class="voice-state">This put an earlier change back.</p>';
      html += "</div>";
      if (item.kind === "change" && item.can_undo && !item.is_undo) {
        html += '<button class="btn quiet voice-btn" type="button" data-voice-undo="'
             + esc(item.id) + '">Undo</button>';
      } else if (item.kind === "decision" && item.can_restore) {
        html += '<button class="btn quiet voice-btn" type="button" data-voice-restore="'
             + esc(item.candidate_id) + '">Restore</button>';
      }
      html += "</li>";
    });
    html += "</ul></section>";
    return html;
  }

  async function undoVoiceChange(button, changeSetId) {
    button.disabled = true;
    button.textContent = "Undoing";
    try {
      var result = await api("/editorial/change-sets/" + encodeURIComponent(changeSetId) + "/undo", {
        method: "POST", body: { by: "ziv" }
      });
      toast(result.said || "Undone.");
      await render();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Undo";
      // A refusal carries the text as it is now; say it rather than a code.
      var current = error.detail && typeof error.detail.current === "string"
        ? ' It now says: "' + error.detail.current + '".' : "";
      toast(error.message + current, true);
    }
  }

  async function restoreVoiceIdea(button, candidateId) {
    button.disabled = true;
    button.textContent = "Restoring";
    try {
      var result = await api("/editorial/topics/" + encodeURIComponent(candidateId) + "/restore", {
        method: "POST", body: { by: "ziv" }
      });
      toast(result.said || "Brought back.");
      await render();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Restore";
      toast(error.message, true);
    }
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
    // 26-Sep: his number is his usual week, not a wall. Past it is a good week.
    var usual = data.primary_slots;
    var lede = data.over_by > 0
      ? primary.length + " videos this week, " + data.over_by + " more than your usual "
        + usual + ". A good week."
      : primary.length + " of " + usual + " " + plural(usual, "video") + " planned.";
    html += '<p class="lede">' + lede + (data.mix ? " " + esc(data.mix) + "." : "")
         + ' <a href="settings" data-go="/settings">Change how many a week</a></p></div>';

    if (!primary.length && !reserve.length) {
      html += '<div class="empty"><strong>Nothing chosen yet</strong>'
            + "Open Topics and put " + data.primary_slots + " "
            + plural(data.primary_slots, "idea") + " in this week, or more on a good week.</div>";
      html += '<div class="actions"><button class="btn primary" type="button" data-go="/topics">Choose topics</button></div>';
    } else {
      html += "<h2>Record first</h2>";
      html += '<p class="section-hint">The order here is the order you record in.</p>';
      html += '<div class="card-list">';
      primary.forEach(function (item, index) { html += weekCard(item, index, true, primary.length); });
      html += "</div>";

      if (reserve.length) {
        html += "<h2>Possible replacements</h2>";
        html += '<p class="section-hint">Ready to swap in, or add to the week if it is a good one.</p>';
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
           + (isReserve ? "Record it this week" : "Not this week, keep as a spare") + "</button>";
      html += '<button class="btn quiet" type="button" data-remove="' + esc(item.candidate_id)
           + '">Take out of the week</button>';
      html += "</div>";
    }

    html += '<div class="actions">';
    html += '<button class="btn" type="button" data-open-room="' + esc(item.candidate_id) + '">Open the topic</button>';
    if (item.packet_id && item.script_state === "ready") {
      html += '<a class="btn primary" href="' + prefix + "/record?candidate="
           + esc(item.candidate_id) + '">Record this one</a>';
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
    var voiceItems = (await voiceActivity()).filter(function (item) {
      return item.candidate_id === data.candidate_id;
    });

    var brief = data.brief || {};
    var blocks = brief.blocks || [];

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Topic</p>';
    html += "<h1>" + esc(data.title) + "</h1>";
    if (data.provenance) html += '<p class="lede">' + esc(data.provenance) + "</p>";
    html += "</div>";

    html += pairTabs("topic", data.candidate_id, data.script ? data.script.packet_id : null);
    html += voicePanel(voiceItems);

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
      // Recording lives in the bar at the bottom of the screen, one tap from
      // here. This is for reading and changing the words, which is a different
      // errand.
      html += '<div class="actions"><button class="btn" type="button" data-open-script="'
           + esc(data.script.packet_id) + '">Read and change the script</button></div>';
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

  /* One switcher, on both screens. They are two views of the same idea - the
     thinking and the words - and moving between them was a button that read like
     leaving the page. */
  function pairTabs(active, candidateId, packetId) {
    if (!candidateId) return "";
    var html = '<div class="chips" role="group" aria-label="This idea">';
    html += '<button class="chip" type="button" data-open-room="' + esc(candidateId)
         + '" aria-pressed="' + (active === "topic" ? "true" : "false") + '">The topic</button>';
    if (packetId) {
      html += '<button class="chip" type="button" data-open-script="' + esc(packetId)
           + '" aria-pressed="' + (active === "script" ? "true" : "false") + '">The script</button>';
    } else {
      html += '<button class="chip" type="button" disabled '
           + 'title="No script yet">The script</button>';
    }
    return html + "</div>";
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
    html += '<button class="icon-btn" type="button" data-edit="' + esc(block.field)
         + '" aria-label="Edit ' + esc(BLOCK_LABELS[block.field] || block.field)
         + '" title="Edit">&#9998;</button>';
    html += '<button class="btn quiet" type="button" data-rewrite="' + esc(block.field) + '">Ask for a rewrite</button>';
    html += "</div></section>";
    return html;
  }

  /* Edit in place. This was a window.prompt, which on a phone is a cramped
     single-line box over a greyed page - the worst possible surface for the
     paragraph he is actually rewriting. Now the block turns into a textarea
     sized to its own content, and Save writes a new version directly.

     No diff sheet for his own typing: the diff exists so an assistant cannot
     change his words without showing him, and he is looking at the words he
     just typed. History and restore are untouched. */
  function openInlineEdit(field) {
    var section = document.querySelector('.block[data-field="' + field + '"]');
    if (!section || section.dataset.editing === "1") return;
    var block = (state.room.brief.blocks || []).filter(function (b) {
      return b.field === field;
    })[0];
    if (!block) return;

    section.dataset.editing = "1";
    var label = BLOCK_LABELS[field] || field;
    var current = block.value || "";
    var body = section.querySelector("p");
    var actions = section.querySelector(".block-actions");
    if (body) body.hidden = true;
    if (actions) actions.hidden = true;

    var editor = document.createElement("div");
    editor.className = "block-editor";
    editor.innerHTML =
      '<textarea class="block-input" aria-label="' + esc(label) + '"></textarea>'
      + '<div class="block-actions">'
      + '<button class="btn primary" type="button" data-save="1">Save</button>'
      + '<button class="btn quiet" type="button" data-cancel="1">Cancel</button>'
      + "</div>";
    section.appendChild(editor);

    var input = editor.querySelector(".block-input");
    input.value = current;
    // Grow to the text rather than making him scroll a three-line window.
    var grow = function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight + 4, 400) + "px";
    };
    input.addEventListener("input", grow);
    grow();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);

    var close = function () {
      editor.remove();
      if (body) body.hidden = false;
      if (actions) actions.hidden = false;
      delete section.dataset.editing;
    };

    editor.querySelector("[data-cancel]").addEventListener("click", close);
    editor.querySelector("[data-save]").addEventListener("click", async function () {
      var next = input.value;
      if (next === current) { close(); return; }
      var save = editor.querySelector("[data-save]");
      save.disabled = true;
      save.textContent = "Saving";
      try {
        var result = await api("/editorial/topics/" + state.room.candidate_id + "/brief", {
          method: "POST",
          body: { field: field, value: next, base_version: state.room.brief.version }
        });
        state.room = result.room;
        toast("Saved as version " + result.version + ". The old one is in History.");
        await render();
      } catch (error) {
        save.disabled = false;
        save.textContent = "Save";
        toast(error.message, true);
        if (error.status === 409) await render();
      }
    });
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
     read-aloud control is bound from one place rather than once at boot.
     Dictation is gone: talking is the voice call now (voiceCallUrl). */
  function bindVoiceControls(foot) {
    var speaker = foot.querySelector("#speakBtn");
    if (speaker) {
      var on = false;
      try { on = localStorage.getItem("tce-speak-replies") === "1"; } catch (e) { /**/ }
      speaker.setAttribute("aria-pressed", on ? "true" : "false");
      speaker.addEventListener("click", toggleSpeakReplies);
    }
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
      var isRoom = state.talkContext && state.talkContext.type === "room";
      var opener = isRoom
        ? "Talk about the ideas as a set, before you pick one. Which of these is "
          + "actually strongest? Is the mix wrong? Does any of this say what I "
          + "really do? Nothing here changes a topic."
        : "Think out loud. In Discuss nothing changes, whatever you ask for.";
      body.innerHTML = '<div class="empty"><strong>'
        + (isRoom ? "Talk it through first" : "Nothing said yet") + "</strong>"
        + esc(opener) + "</div>";
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

  /* Talking used to be dictation into the typed box. That path is gone: the
   * Talk button opens a real voice call (voiceCallUrl), where an agent hears
   * him, applies what he agrees to and says what it did. Typed chat stays, and
   * replies can still be read out loud. */

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

    html += pairTabs("script", data.candidate_id, data.packet_id);

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
        var inUse = hook.id === openings.selected_hook_id;
        html += '<section class="block' + (inUse ? " is-current" : "") + '">';
        html += "<h4>" + (index === 0 ? "Recommended" : "Option " + (index + 1))
             + (inUse ? " &middot; in use" : "") + "</h4>";
        html += "<p>" + esc(hook.text || hook.line || "") + "</p>";
        if (hook.question || hook.viewer_question) {
          html += '<p class="diff-why">' + esc(hook.question || hook.viewer_question) + "</p>";
        }
        // Choosing was the whole point of the tab and there was no way to do it.
        html += '<div class="block-actions">';
        if (inUse) {
          html += '<span class="tag is-ready">This is the one you open with</span>';
        } else if (data.frozen_reason) {
          html += '<span class="tag">Locked: this script has been recorded</span>';
        } else {
          html += '<button class="btn primary" type="button" data-choose-hook="'
               + esc(hook.id) + '">Use this opening</button>';
        }
        html += "</div></section>";
      });
      if (!(openings.shown || []).length) {
        html += '<div class="empty"><strong>No openings yet</strong>They are written with the script.</div>';
      } else if (!data.frozen_reason) {
        html += '<div class="actions"><button class="btn quiet" type="button" '
             + 'data-more-hooks="1">Ask for different openings</button></div>';
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

  // --------------------------------------------------------------- Settings

  /* 26-Sep: "I need a setting page that allows me to promote more than 3 videos a
     week (choose how many videos)". One number: his usual week. Going past it on a
     good week is always allowed, so the page says that too. */
  async function renderSettings() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading your settings") + "</div>";
    var data = await api("/editorial/settings");
    state.settings = data;
    state.videosDraft = data.videos_per_week;
    paintSettings();
  }

  function paintSettings() {
    var data = state.settings, n = state.videosDraft;
    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Editorial workspace</p><h1>Settings</h1></div>';
    html += '<article class="card"><h3>Videos a week</h3>';
    html += '<p class="big-idea">How many videos you usually record in a week. Each new week '
         + "starts with this many places, and this week changes too.</p>";
    html += '<div class="stepper">'
         + '<button class="btn" type="button" data-videos-step="-1" aria-label="One fewer"'
         + (n <= data.min ? " disabled" : "") + ">&#8722;</button>"
         + '<span class="count" id="videosCount" aria-live="polite">' + n + "</span>"
         + '<button class="btn" type="button" data-videos-step="1" aria-label="One more"'
         + (n >= data.max ? " disabled" : "") + ">+</button></div>";
    html += '<p class="section-hint">Had a good week? Put more in the week anyway. This number '
         + "is your usual week, not a limit.</p>";
    html += '<div class="actions"><button class="btn primary" type="button" data-save-settings'
         + (n === data.videos_per_week ? " disabled" : "") + ">Save " + n + " a week</button>"
         + '<button class="btn quiet" type="button" data-go="/week">Open this week</button></div>';
    html += "</article>";
    // 26-Sep: "I want to build an audience without asking anyone for anything."
    html += '<article class="card"><h3>How your posts read</h3>';
    html += '<p class="big-idea">Every post TCE writes for you follows this, in your words. '
         + "Change it any time; the next posts follow the new version.</p>";
    html += '<label class="pub-field"><span>Your post rules</span><textarea rows="6" id="postRules">'
         + esc(data.post_rules || "") + "</textarea></label>";
    html += '<div class="actions"><button class="btn primary" type="button" data-save-rules>Save the rules</button></div>';
    html += "</article></div>";
    $("view").innerHTML = html;
    status(data.videos_per_week + " " + plural(data.videos_per_week, "video") + " a week");
  }

  async function saveRules() {
    try {
      state.settings = await api("/editorial/settings", {
        method: "PUT", body: { post_rules: $("postRules").value }
      });
      toast("Saved. The next posts follow these rules.");
      paintSettings();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function saveSettings() {
    try {
      state.settings = await api("/editorial/settings", {
        method: "PUT", body: { videos_per_week: state.videosDraft }
      });
      toast("Saved. Your week is now " + state.settings.videos_per_week + " "
            + plural(state.settings.videos_per_week, "video") + ".");
      paintSettings();
    } catch (error) {
      toast(error.message, true);
    }
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
    scheduleLibraryPoll(items);
  }

  /* TCE edits by itself now (25-Sep), so a card changes while he looks at it. While
     anything is being edited, re-read quietly every 8 s and redraw only when
     something changed and no video is playing. */
  var LIBRARY_LIVE = ["transcribing", "transcribed", "proofreading", "planned", "rendering"];
  function libraryBusy(items) {
    var now = Date.now();
    return items.some(function (i) {
      var writing = state.pubWriting && state.pubWriting[i.upload_id]
        && !(i.publishing || []).length && now - state.pubWriting[i.upload_id] < 10 * 60000;
      return LIBRARY_LIVE.indexOf(i.status) >= 0
        || (i.last_request && i.last_request.state === "in_progress")
        || writing
        || (i.publishing || []).some(function (p) { return p.status === "posting" || p.status === "revising"; });
    });
  }
  function scheduleLibraryPoll(items) {
    clearTimeout(state.libraryPoll);
    if (libraryBusy(items)) state.libraryPoll = setTimeout(pollLibrary, 8000);
  }
  async function pollLibrary() {
    if (!document.querySelector("[data-libfilter]")) return;  // he left the Library
    var before = JSON.stringify((state.library || {}).items || []);
    var data;
    try { data = await api("/production/library?filter=" + encodeURIComponent(state.libraryFilter)); }
    catch (error) { state.libraryPoll = setTimeout(pollLibrary, 8000); return; }
    var playing = document.querySelector(".player:not([hidden])");
    var typing = document.activeElement && document.activeElement.closest
      && document.activeElement.closest(".publish");
    if (JSON.stringify(data.items || []) !== before && !playing && !typing) { renderLibrary(); return; }
    scheduleLibraryPoll(data.items || []);
  }

  function libraryCard(item) {
    var html = '<article class="card">';
    html += "<h3>" + esc(item.title) + "</h3>";
    // The edit is what he comes here for: say so on the card (25-Sep).
    if (item.has_edit) html += '<span class="tag is-ready">Edited video</span> ';
    html += '<span class="source">' + esc(when(item.recorded_at))
         + (item.duration_s ? " &middot; " + clock(item.duration_s) : "") + "</span>";
    html += '<p class="big-idea">' + esc(item.state_sentence) + "</p>";
    (item.issues || []).forEach(function (issue) {
      html += '<p class="notice is-bad">' + esc(issue) + "</p>";
    });
    // What the subscription changed on its own, and what it did with his last
    // request (25-Sep: TCE edits by itself). Nothing changes unseen.
    (item.proofread || []).forEach(function (fix) {
      html += '<p class="notice">Proofread fixed: \u201c' + esc(fix.heard) + '\u201d \u2192 \u201c'
           + esc(fix.replacement || "(removed)") + '\u201d</p>';
    });
    var last = item.last_request;
    if (last) {
      var res = last.result || {};
      var says = last.state === "done" ? (res.reply || "Done.")
               : last.state === "needs_you" ? (res.question || res.reply || "Needs you.")
               : (res.status || "Working on it.");
      html += '<p class="notice' + (last.state === "needs_you" ? " is-bad" : "") + '"><strong>'
           + (last.state === "done" ? "Your request is done" : last.state === "needs_you" ? "Needs you"
              : "Working on your request") + ':</strong> ' + esc(says)
           + ' <span class="source">(you asked: ' + esc(last.request) + ')</span></p>';
    }

    // Only actions with a real destination. The server already decided which.
    html += '<div class="actions">';
    (item.actions || []).forEach(function (action) {
      // Watch plays it here; Download saves it. They used to be one link, so
      // every Watch downloaded the file ("have a download button do that",
      // 23-Sep). The server serves inline with byte ranges so the player seeks.
      if (action.key === "watch_raw" || action.key === "watch_edit") {
        var file = apiV1 + "/production/uploads/" + esc(item.upload_id)
                 + (action.key === "watch_edit" ? "/edited" : "/video");
        html += '<button class="btn' + (action.key === "watch_edit" ? " primary" : "")
             + '" type="button" data-watch="' + file + '">' + esc(action.label) + "</button>";
        html += '<a class="btn quiet" href="' + file + '?download=1" download>'
             + (action.key === "watch_edit" ? "Download the edit" : "Download") + "</a>";
      } else if (action.key === "captions") {
        html += '<a class="btn quiet" href="' + apiV1 + "/production/uploads/" + esc(item.upload_id) + '/captions.srt">' + esc(action.label) + "</a>";
      } else if (action.key === "request_edit") {
        html += '<button class="btn" type="button" data-edit-request="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "re_record" && item.candidate_id) {
        html += '<a class="btn quiet" href="' + prefix + '/record">' + esc(action.label) + "</a>";
      }
    });
    html += '</div><div class="player" hidden></div>';
    if (item.has_edit) html += publishSection(item);
    html += "</article>";
    return html;
  }

  /* 26-Sep: "I want tce to be able to do the full publishing and to show me the post
     in the library". The four posts, written from what he says in the edit, each
     editable; his tap posts or schedules them; a posted one links to the live post. */
  var PUB_FIELDS = {
    instagram: [["caption", "Caption", 9]],
    facebook: [["message", "Post", 10]],
    youtube: [["title", "Title", 1], ["description", "Description", 5], ["tags", "Tags (comma separated)", 1]],
    linkedin: [["message", "Post", 10], ["hashtags", "Hashtags (comma separated)", 1]]
  };
  var PUB_STATUS = { draft: "Ready to post", posting: "Posting now", scheduled: "Scheduled",
                     posted: "Posted", failed: "Did not go out", revising: "Being changed" };

  function publishSection(item) {
    var pubs = item.publishing || [];
    var id = esc(item.upload_id);
    var html = '<section class="publish" data-pub-upload="' + id + '"><h4>Publish</h4>';
    if (!pubs.length) {
      var writing = state.pubWriting && state.pubWriting[item.upload_id];
      html += writing
        ? '<p class="notice">Writing the Instagram, Facebook, YouTube and LinkedIn posts from what you say in this video, on your subscription. This card fills in when they are ready.</p>'
        : '<p class="section-hint">TCE writes the four posts from what you say in the edit. You read them, change anything, then post.</p>'
          + '<div class="actions"><button class="btn primary" type="button" data-pub-draft="' + id + '">Write the posts</button></div>';
      return html + "</section>";
    }
    pubs.forEach(function (p) {
      var done = p.status === "posted" || p.status === "scheduled" || p.status === "posting"
        || p.status === "revising";
      html += '<div class="pub-platform" data-platform="' + esc(p.platform) + '">';
      html += '<div class="pub-head"><label class="pub-pick"><input type="checkbox" data-pub-pick="' + esc(p.platform) + '"'
           + (done ? " disabled" : " checked") + "> <strong>" + esc(p.label) + "</strong></label>"
           + '<span class="tag' + (p.status === "posted" ? " is-ready" : p.status === "failed" ? " is-timely" : "") + '">'
           + esc(PUB_STATUS[p.status] || p.status) + "</span></div>";
      if (p.status === "posted" && p.url) {
        html += '<p><a class="btn quiet" href="' + esc(p.url) + '" target="_blank" rel="noopener">See it on '
             + esc(p.label.split(" ")[0]) + " &#8599;</a></p>";
      }
      if (p.status === "scheduled" && p.scheduled_for) {
        html += '<p class="source">Goes out ' + esc(new Date(p.scheduled_for + "Z").toLocaleString()) + "</p>";
      }
      if (p.detail && p.status !== "posted") html += '<p class="source">' + esc(p.detail) + "</p>";
      (PUB_FIELDS[p.platform] || []).forEach(function (f) {
        var value = p.copy[f[0]];
        if (Array.isArray(value)) value = value.join(", ");
        html += '<label class="pub-field"><span>' + esc(f[1]) + "</span>";
        html += f[2] > 1
          ? '<textarea rows="' + f[2] + '" data-pub-field="' + f[0] + '"' + (done ? " readonly" : "") + ">" + esc(value || "") + "</textarea>"
          : '<input type="text" data-pub-field="' + f[0] + '" value="' + esc(value || "") + '"' + (done ? " readonly" : "") + ">";
        html += "</label>";
      });
      html += "</div>";
    });
    var open = pubs.some(function (p) { return p.status === "draft" || p.status === "failed"; });
    if (open) {
      // 26-Sep: "I need a way to request a change to the posts".
      html += '<label class="pub-field"><span>Ask for a change to the posts</span>'
           + '<textarea rows="2" class="pub-change" placeholder="For example: shorter, and start with the 9 a.m. line"></textarea></label>'
           + '<div class="actions"><button class="btn" type="button" data-pub-revise="' + id + '">Change the posts</button>'
           + '<a class="btn quiet" href="settings" data-go="/settings">How your posts read</a></div>';
      html += '<div class="actions pub-actions">'
           + '<button class="btn primary" type="button" data-pub-post="' + id + '">Post the ticked ones now</button>'
           + '<input type="datetime-local" class="pub-when" aria-label="When to post">'
           + '<button class="btn" type="button" data-pub-schedule="' + id + '">Schedule the ticked ones</button>'
           + '<button class="btn quiet" type="button" data-pub-draft="' + id + '">Write them again</button></div>';
    }
    return html + "</section>";
  }

  function publishFields(section, platform) {
    var box = section.querySelector('.pub-platform[data-platform="' + platform + '"]');
    var out = {};
    box.querySelectorAll("[data-pub-field]").forEach(function (el) {
      var key = el.getAttribute("data-pub-field");
      out[key] = (key === "tags" || key === "hashtags")
        ? el.value.split(",").map(function (t) { return t.trim(); }).filter(Boolean)
        : el.value;
    });
    return out;
  }

  async function publishStart(uploadId, schedule) {
    var section = document.querySelector('[data-pub-upload="' + uploadId + '"]');
    var picked = [].slice.call(section.querySelectorAll("[data-pub-pick]:checked"))
      .map(function (el) { return el.getAttribute("data-pub-pick"); });
    if (!picked.length) { toast("Tick at least one place to post.", true); return; }
    var at = null;
    if (schedule) {
      var when = section.querySelector(".pub-when").value;
      if (!when) { toast("Choose when to post first.", true); return; }
      at = new Date(when).toISOString();
    }
    var names = picked.map(function (p) { return p.charAt(0).toUpperCase() + p.slice(1); }).join(", ");
    if (!window.confirm((schedule ? "Schedule this video on " : "Post this video now on ") + names + "?")) return;
    try {
      // Save what he changed first: the post goes out exactly as it reads on screen.
      for (var i = 0; i < picked.length; i++) {
        await api("/production/uploads/" + encodeURIComponent(uploadId) + "/publishing/" + picked[i], {
          method: "PUT", body: { fields: publishFields(section, picked[i]) }
        });
      }
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/publishing/publish", {
        method: "POST", body: { platforms: picked, at: at }
      });
      toast(schedule ? "Scheduling. The card shows each one as it is booked." : "Posting. The card shows each link as it goes live.");
      renderLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function publishRevise(uploadId) {
    var section = document.querySelector('[data-pub-upload="' + uploadId + '"]');
    var text = (section.querySelector(".pub-change") || {}).value || "";
    if (text.trim().length < 2) { toast("Say what should change first.", true); return; }
    try {
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/publishing/revise", {
        method: "POST", body: { request: text.trim() }
      });
      toast("Changing the posts on your subscription. This card updates when they are ready.");
      renderLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function publishDraft(uploadId) {
    try {
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/publishing/draft", { method: "POST" });
      state.pubWriting = state.pubWriting || {};
      state.pubWriting[uploadId] = Date.now();
      toast("Writing the posts on your subscription. This card fills in when they are ready.");
      renderLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  /* The player opens inside the card it belongs to, under its buttons: one
     video at a time, and Close (or tapping Watch again) puts it away. */
  function toggleWatch(button) {
    var card = button.closest("article");
    var box = card && card.querySelector(".player");
    if (!box) return;
    var src = button.getAttribute("data-watch");
    if (!box.hidden && box.getAttribute("data-src") === src) { closePlayer(box); return; }
    document.querySelectorAll(".player").forEach(function (other) { if (other !== box) closePlayer(other); });
    box.setAttribute("data-src", src);
    box.innerHTML = '<video controls playsinline preload="metadata" src="' + src + '"></video>'
                  + '<button class="btn quiet" type="button" data-watch-close>Close</button>';
    box.hidden = false;
    var video = box.querySelector("video");
    video.play().catch(function () { /* the controls are there to press */ });
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function closePlayer(box) {
    var video = box.querySelector("video");
    if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
    box.innerHTML = "";
    box.hidden = true;
    box.removeAttribute("data-src");
  }

  async function chooseHook(hookId) {
    try {
      // Choosing writes a new immutable script version, the same as any other
      // change to the words. The workshop reloads onto it.
      var packet = await api(
        "/editorial/packets/" + state.workshop.packet_id + "/choose-hook",
        { method: "POST", body: { hook_id: hookId } }
      );
      toast("That is your opening now. Saved as version " + packet.version + ".");
      go("/scripts/" + packet.id, true);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function askMoreHooks() {
    try {
      await api("/editorial/packets/" + state.workshop.packet_id + "/more-hooks",
                { method: "POST" });
      toast("Asked. New openings are written on your PC worker; it takes a few minutes.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function askEditRequest(uploadId) {
    var text = window.prompt("What should change about this video?\n\nSay it the way you would say it to an editor.");
    if (text === null || !text.trim()) return;
    try {
      await api("/production/recordings/" + encodeURIComponent(uploadId) + "/edit-requests", {
        method: "POST",
        body: { request: text.trim(), scope: "whole" }
      });
      toast("Asked. TCE is making the change now on your subscription; this card updates as it goes.");
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
          ? "In the reserve list."
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

  /* Every clickable data-attribute, in one list, with the selector DERIVED from
     it. It used to be a hand-written selector string beside a hand-written set
     of branches, and the two drifted: `rewrite`, `review` and `notify` had
     branches but were missing from the string, so "Ask for a rewrite", "Review
     the change" and the notifications toggle were silently dead. Nothing threw,
     nothing logged - the click simply matched nothing. Adding an action here is
     now the only step. */
  var CLICK_ACTIONS = [
    "go", "filter", "libfilter", "decide", "open-room", "open-script", "move",
    "slot", "remove", "ask-script", "change", "edit", "restore", "wtab",
    "edit-request", "review", "rewrite", "notify", "choose-hook", "more-hooks",
    "watch", "watch-close", "voice-undo", "voice-restore",
    "videos-step", "save-settings", "pub-draft", "pub-post", "pub-schedule", "pub-revise",
    "save-rules"
  ];
  var CLICK_SELECTOR = CLICK_ACTIONS.map(function (name) {
    return "[data-" + name + "]";
  }).join(",");

  document.addEventListener("click", function (event) {
    var target = event.target.closest(CLICK_SELECTOR);
    if (!target) return;
    var d = target.dataset;

    if (d.go !== undefined) { event.preventDefault(); go(d.go); return; }
    if (d.videosStep !== undefined) {
      var s = state.settings;
      state.videosDraft = Math.max(s.min, Math.min(s.max, state.videosDraft + Number(d.videosStep)));
      paintSettings();
      return;
    }
    if (d.saveSettings !== undefined) { saveSettings(); return; }
    if (d.pubDraft !== undefined) { publishDraft(d.pubDraft); return; }
    if (d.pubPost !== undefined) { publishStart(d.pubPost, false); return; }
    if (d.pubSchedule !== undefined) { publishStart(d.pubSchedule, true); return; }
    if (d.pubRevise !== undefined) { publishRevise(d.pubRevise); return; }
    if (d.saveRules !== undefined) { saveRules(); return; }
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
    if (d.edit !== undefined) { openInlineEdit(d.edit); return; }
    if (d.change !== undefined) { openChange(d.change); return; }
    if (d.restore !== undefined) { restore(parseInt(d.restore, 10)); return; }
    if (d.editRequest !== undefined) { askEditRequest(d.editRequest); return; }
    if (d.watch !== undefined) { toggleWatch(target); return; }
    if (d.watchClose !== undefined) { closePlayer(target.closest(".player")); return; }
    if (d.review !== undefined) { reviewFromThread(d.review); return; }
    if (d.chooseHook !== undefined) { chooseHook(d.chooseHook); return; }
    if (d.moreHooks !== undefined) { askMoreHooks(); return; }
    if (d.rewrite !== undefined) { openRewrite(d.rewrite); return; }
    if (d.voiceUndo !== undefined) { undoVoiceChange(target, d.voiceUndo); return; }
    if (d.voiceRestore !== undefined) { restoreVoiceIdea(target, d.voiceRestore); return; }
    if (d.notify !== undefined) {
      if (d.notify === "on") enableNotifications(); else disableNotifications();
      return;
    }
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
  /* A step each way that stops at the ends: the old single button cycled, so
     one tap past "largest" threw the page back to the smallest. */
  function stepReader(delta) {
    var current = READER_SIZES.indexOf(document.body.dataset.reader || "normal");
    var next = Math.max(0, Math.min(READER_SIZES.length - 1, (current < 0 ? 0 : current) + delta));
    document.body.dataset.reader = READER_SIZES[next];
    $("readerSmaller").disabled = next === 0;
    $("readerBigger").disabled = next === READER_SIZES.length - 1;
    try { localStorage.setItem("tce-workspace-reader", READER_SIZES[next]); } catch (e) { /* private mode */ }
  }
  $("readerSmaller").addEventListener("click", function () { stepReader(-1); });
  $("readerBigger").addEventListener("click", function () { stepReader(1); });

  window.addEventListener("popstate", function () { render(); });

  // ------------------------------------------------------------------ boot

  /* The voice call. It belongs to KM BOT, on the same host as /tce, so the path
   * is absolute and never takes this page's /tce prefix (the same reason the
   * nav's Record link is handled apart). `context` is "week" or "topic:<id>".
   * `return` is where the call page's "Back to TCE" should land. Change the
   * call's address here and nowhere else. */
  function voiceCallUrl(context) {
    var here = window.location.pathname + window.location.search;
    return "/voice?seat=tce&context=" + (context || "week")
      + "&return=" + encodeURIComponent(here);
  }

  /* The button appears only where there is a specific thing to discuss, and its
   * label names that thing. A conversation that does not know what is on screen
   * is a general chat window, which is the thing this deliberately is not. */
  function setTalkContext(route) {
    if (route.name === "room" && state.room) {
      state.talkContext = {
        type: "topic", id: route.id, label: state.room.title,
        action: "Talk about this topic", voice: "topic:" + route.id
      };
    } else if (route.name === "workshop" && state.workshop) {
      state.talkContext = {
        type: "packet", id: route.id,
        label: "Script version " + state.workshop.version,
        action: "Talk about this script",
        // The call is about the idea; the agent opens its current script.
        voice: state.workshop.candidate_id ? "topic:" + state.workshop.candidate_id : "week"
      };
    } else if (route.name === "week") {
      state.talkContext = {
        type: "week", id: null, label: "This week's list",
        action: "Talk about this week", voice: "week"
      };
    } else if (route.name === "topics" || route.name === "today") {
      /* The editorial room: the whole week and everything still waiting, before
         he has picked anything. This is the conversation he wants FIRST - which
         one is strongest, is the mix wrong, none of these says what I do - and
         it was reachable but unnamed, so it read as just another "talk about
         this" and he could not tell it was the cross-topic one. */
      state.talkContext = {
        type: "room", id: null, label: "All your ideas and this week",
        action: "Talk about the whole week", voice: "week"
      };
    } else {
      state.talkContext = null;
    }
    /* The bar carries the thing he most wants to do here, not just Talk.
       Recording was four taps from a topic he had already chosen; when a script
       is ready it is now one, from wherever he happens to be. */
    var record = recordTarget(route);
    var bar = $("actionBar");
    bar.innerHTML = "";
    if (record) {
      bar.insertAdjacentHTML("beforeend",
        '<a class="bar-btn is-record" href="' + esc(record.href) + '">'
        + esc(record.label) + "</a>");
    }
    if (state.talkContext) {
      /* Talk is a real call now: a link to the voice page, same tab, so the
         browser's Back and the call page's own way back both land here. Typed
         chat stays one tap away beside it for when talking out loud is wrong. */
      bar.insertAdjacentHTML("beforeend",
        '<a class="bar-btn is-talk" id="talkFab" href="'
        + esc(voiceCallUrl(state.talkContext.voice)) + '">'
        + esc(state.talkContext.action) + "</a>"
        + '<button class="bar-btn is-type" type="button" id="typeFab"'
        + ' aria-label="Type instead of talking">Type</button>');
      $("typeFab").addEventListener("click", openTalk);
    }
    var show = !!(record || state.talkContext);
    bar.hidden = !show;
    bar.classList.toggle("is-split", !!(record && state.talkContext));
    // The bar is fixed, so the page has to reserve its height or the last card
    // sits underneath it.
    document.body.classList.toggle("has-talk", show);
  }

  /* Where "Start recording" should go from this page, or null when there is
     nothing ready to record. Deep links into the studio so he lands on the idea
     rather than on the list he already chose from. */
  function recordTarget(route) {
    if (route.name === "room" && state.room && state.room.script
        && ["ready", "exported"].indexOf(state.room.script.status) !== -1) {
      return { href: prefix + "/record?candidate=" + state.room.candidate_id,
               label: "Start recording" };
    }
    if (route.name === "workshop" && state.workshop
        && ["ready", "exported"].indexOf(state.workshop.status) !== -1) {
      return { href: prefix + "/record?candidate=" + state.workshop.candidate_id,
               label: "Start recording" };
    }
    var first = firstReadyThisWeek();
    if ((route.name === "week" || route.name === "today") && first) {
      return { href: prefix + "/record?candidate=" + first.candidate_id,
               label: "Start recording" };
    }
    return null;
  }

  function firstReadyThisWeek() {
    var week = (state.route === "today" && state.today) ? state.today.week : state.week;
    if (!week) return null;
    return (week.primary || []).filter(function (item) {
      return item.script_state === "ready";
    })[0] || null;
  }

  async function render() {
    var route = parse();
    state.route = route.name;
    setChrome(route);
    $("actionBar").hidden = true;
    document.body.classList.remove("has-talk");
    try {
      if (route.name === "today") await renderToday();
      else if (route.name === "topics") await renderTopics();
      else if (route.name === "week") await renderWeek();
      else if (route.name === "library") await renderLibrary();
      else if (route.name === "settings") await renderSettings();
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
  // After the restore, or the saved size would be overwritten with "normal".
  stepReader(0);

  TALK_FOOTER = $("talkSheet").querySelector(".sheet-foot").innerHTML;

  render();
})();
