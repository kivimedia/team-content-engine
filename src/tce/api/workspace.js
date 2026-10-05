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
    libraryFilter: "todo",
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
    // 3-Oct: the rules Jennifer learned from his notes, each with its source video.
    { name: "rules",    pattern: /^\/library\/rules\/?$/,      title: "Jennifer's rules" },
    { name: "settings", pattern: /^\/settings\/?$/,            title: "Settings" },
    { name: "room",     pattern: /^\/topics\/([0-9a-f-]{36})\/?$/, title: "Topic" },
    { name: "workshop", pattern: /^\/scripts\/([0-9a-f-]{36})\/?$/, title: "Script" },
    // 1-Oct: the notes sheet of one video, over its Library.
    { name: "talk",     pattern: /^\/library\/([0-9a-f-]{36})\/talk\/?$/, title: "Library" }
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
    takeFilterFromUrl();
    render();
  }

  /* A link can name the list it opens: Today's "being edited" card goes to
     /library?filter=editing, the list it counted (28-Sep), not to Everything.
     Read when the page is reached (a tap, Back, or the link opened directly),
     not on every render, so a chip tapped afterwards still changes the list. */
  function takeFilterFromUrl() {
    var wanted = new URLSearchParams(window.location.search).get("filter");
    if (!wanted) return;
    var name = parse().name;
    if (name === "library") state.libraryFilter = wanted;
    else if (name === "topics") state.topicFilter = wanted;
  }

  function setChrome(route) {
    $("pageTitle").textContent = route.title;
    var nav = $("bottomNav");
    var active = { today: "today", topics: "topics", week: "week", library: "library",
                   room: "topics", workshop: "week", talk: "library", rules: "library" }[route.name];
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
    html += countCard(counts.editing, "being edited", "/library?filter=editing");
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
      var readyFirst = primary.filter(toFilmNow)[0];
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
      html += '<p class="section-hint">' + esc(topic.set_aside_by_engine
        ? "Set aside by the engine: a newer run replaced it, or its news went stale. Putting it in the week brings it back."
        : decisionSentence(topic.decision)) + "</p>";
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
    // A filmed topic stays on the list but its script is used: "ready" counts
    // only what is still to film, and the filmed ones are named apart.
    var filmed = primary.filter(function (i) { return i.filmed; }).length;
    status(data.ready_count + " of " + (primary.length - filmed) + " scripts ready"
           + (filmed ? ", " + filmed + " filmed" : ""));
  }

  /* A topic he can start filming now: its script is ready and he has not filmed
     it yet. 28-Sep: a filmed topic stays in its week, and must never say
     "Start recording" again. */
  function toFilmNow(item) {
    return item.script_state === "ready" && !item.filmed;
  }

  function weekCard(item, index, controls, total, isReserve) {
    var html = '<article class="card">';
    html += '<div class="card-title-row"><span class="rank">' + (item.rank || index + 1) + "</span>";
    html += "<h3>" + esc(item.title) + "</h3></div>";
    if (item.reason) html += '<p class="why">' + esc(item.reason) + "</p>";
    if (item.lane_label) html += '<span class="tag is-lane">' + esc(item.lane_label) + "</span>";
    /* 28-Sep: a script asked for while his Claude limit was used up waited two
       days, and the card said "No script yet" with "Prepare the script" all
       along. A script on its way says when it comes, and is not offered again. */
    var request = item.script_request || null;
    var coming = !!(request && request.pending);
    if (item.filmed) {
      html += '<span class="tag is-ready">Filmed</span>';
    } else if (request && !item.packet_id) {
      html += '<span class="tag">' + esc(request.label) + "</span>";
      html += '<p class="section-hint">' + esc(request.sentence) + "</p>";
    } else {
      html += '<span class="tag' + (item.script_state === "ready" ? " is-ready" : "") + '">'
           + esc(scriptSentence(item.script_state)) + "</span>";
      /* Review, 28-Sep: a new script on its way over the one he has was not
         shown, so nothing told him that filming this one first keeps the new
         one aside. The server sends one only while it is on its way. */
      if (coming) {
        html += '<span class="tag">' + esc(request.label) + "</span>";
        html += '<p class="section-hint">' + esc(request.sentence) + "</p>";
      }
    }

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
    if (item.filmed) {
      // Done: the script is still his to read, but nothing asks him to film it.
      if (item.packet_id) {
        html += '<button class="btn" type="button" data-open-script="' + esc(item.packet_id) + '">Open the script</button>';
      }
    } else if (item.packet_id && item.script_state === "ready") {
      html += '<a class="btn primary" href="' + prefix + "/record?candidate="
           + esc(item.candidate_id) + '">Record this one</a>';
      html += '<button class="btn" type="button" data-open-script="' + esc(item.packet_id) + '">Open the script</button>';
    } else if (!item.packet_id && !coming) {
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
      // A new script on its way over this one says so, and what filming first does.
      if (data.script_request && data.script_request.pending) {
        html += '<p class="section-hint">' + esc(data.script_request.sentence) + "</p>";
      }
      // Recording lives in the bar at the bottom of the screen, one tap from
      // here. This is for reading and changing the words, which is a different
      // errand.
      html += '<div class="actions"><button class="btn" type="button" data-open-script="'
           + esc(data.script.packet_id) + '">Read and change the script</button></div>';
    } else {
      html += '<p class="section-hint">' + esc(data.script_note) + "</p>";
      // A script already on its way saves itself; asking again changes nothing.
      if (!(data.script_request && data.script_request.pending)) {
        html += '<div class="actions"><button class="btn primary" type="button" data-ask-script="'
             + esc(data.candidate_id) + '">Prepare the script</button></div>';
      }
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
      showCurrentScript();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Use the new version";
      // A conflict is the one error worth keeping the sheet open for.
      toast(error.message, true);
      if (error.status === 409) { closeSheet(); await render(); showCurrentScript(); }
    }
  }

  /* An accepted script edit is a new version with its own address. The page used
     to stay on the version it opened, so the next edit was made on the old text
     and is now refused as a conflict (review, 28-Sep-2026). Move to the current
     version instead; History still opens the old ones. */
  function showCurrentScript() {
    var route = parse();
    if (route.name !== "workshop" || !state.workshop) return;
    var versions = state.workshop.versions || [];
    for (var i = 0; i < versions.length; i++) {
      if (versions[i].status === "superseded") continue;
      if (versions[i].packet_id !== route.id) go("/scripts/" + versions[i].packet_id, true);
      return;
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
    try { state.notifyConfig = await api("/editorial/notifications/config"); }
    catch (e) { state.notifyConfig = null; }
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
    html += "</article>";
    html += '<article class="card"><h3>Notifications</h3>' + (notifyRow(state.notifyConfig)
         || '<p class="section-hint">Notifications are not available on this device.</p>') + "</article>";
    html += "</div>";
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
    state.libraryStale = false;
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading what you have recorded") + "</div>";
    var data = await api("/production/library?filter=" + encodeURIComponent(state.libraryFilter));
    state.library = data;

    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Editorial workspace</p><h1>Library</h1>';
    html += '<p class="lede">' + esc(LIBRARY_LEDE[data.filter] || LIBRARY_LEDE.all) + "</p>";
    // 3-Oct: Jennifer checks every edit and learns from his notes; her rules have a page.
    html += '<p class="lede"><a href="library/rules" data-go="/library/rules">Jennifer\'s rules</a>'
          + ": what she learned from your notes, and applies to every next video.</p></div>";

    html += '<div class="chips" role="group" aria-label="Filter recordings">';
    (data.filters || []).forEach(function (f) {
      html += '<button class="chip" type="button" data-libfilter="' + esc(f.key) + '" aria-pressed="'
           + (f.key === data.filter ? "true" : "false") + '">' + esc(f.label) + "</button>";
    });
    html += "</div>";

    var items = data.items || [];
    if (!items.length && data.filter === "todo") {
      html += '<div class="empty"><strong>Nothing waiting on you</strong>'
            + "Everything you recorded has gone out. Published videos are under Published.</div>";
    } else if (!items.length && data.filter === "archived") {
      html += '<div class="empty"><strong>Nothing archived</strong>'
            + "A recording you archive, or choose not to edit after a talk, waits here.</div>";
    } else if (!items.length && data.filter === "published") {
      html += '<div class="empty"><strong>Nothing published yet</strong>'
            + "A video moves here once one of its posts goes out or is scheduled.</div>";
    } else if (!items.length) {
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

  /* 28-Sep: the Library opens on what still needs pushing through; what went out
     has its own chip. The line under the heading says which list this is. */
  var LIBRARY_LEDE = {
    todo: "What still needs you: recorded, being edited, or waiting to go out.",
    published: "Videos that have gone out, or are scheduled to.",
    all: "Everything you have recorded, and what happened to it.",
    // 4-Oct: a talk he chose to archive after Stop lands here, unedited.
    archived: "Recordings you set aside. Nothing here is edited or posted. Edit this now starts the edit of one that was never edited."
  };

  /* TCE edits by itself now (25-Sep), so a card changes while he looks at it. While
     anything is being edited, re-read quietly every 8 s and redraw only when
     something changed and no video is playing. */
  var LIBRARY_LIVE = ["transcribing", "transcribed", "proofreading", "planned", "rendering", "checking"];
  function libraryBusy(items) {
    var now = Date.now();
    return items.some(function (i) {
      var writing = state.pubWriting && state.pubWriting[i.upload_id]
        && !(i.publishing || []).length && now - state.pubWriting[i.upload_id] < 10 * 60000;
      return LIBRARY_LIVE.indexOf(i.status) >= 0
        || (i.last_request && i.last_request.state === "in_progress")
        // 1-Oct: his notes being made into a new version.
        || (i.notes_made && NOTES_WORKING.indexOf(i.notes_made.state) >= 0)
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
    // 3-Oct: a voice call with an agent he filmed says so, and with whom.
    if (item.source === "agent_talk") {
      html += '<span class="tag is-talk">' + esc(item.source_label || "Agent talk")
           + (item.agent ? " with " + esc(item.agent) : "") + "</span> ";
    }
    // The edit is what he comes here for: say so on the card (25-Sep).
    if (item.has_edit) html += '<span class="tag is-ready">Edited video</span> ';
    html += '<span class="source">' + esc(when(item.recorded_at))
         + (item.duration_s ? " &middot; " + clock(item.duration_s) : "") + "</span>";
    html += '<p class="big-idea">' + esc(item.state_sentence) + "</p>";
    if (item.source_line) html += '<p class="source">' + esc(item.source_line) + "</p>";
    html += checkHtml(item);
    (item.issues || []).forEach(function (issue) {
      html += '<p class="notice is-bad">' + esc(issue) + "</p>";
    });
    // What the subscription changed on its own, and what it did with his last
    // request (25-Sep: TCE edits by itself). Nothing changes unseen.
    (item.proofread || []).forEach(function (fix) {
      html += '<p class="notice">Proofread fixed: \u201c' + esc(fix.heard) + '\u201d \u2192 \u201c'
           + esc(fix.replacement || "(removed)") + '\u201d</p>';
    });
    if (item.review_note) html += '<p class="notice">' + esc(item.review_note) + "</p>";
    // 30-Sep: the phone cut the end of a word ("cou" for "course"). No cut can bring it
    // back, so he hears it here first, with where it is in the edit.
    var cutShort = item.phone_cut || [];
    if (cutShort.length) {
      html += '<p class="notice is-bad"><strong>Your phone cut ' + (cutShort.length === 1 ? "a word" : cutShort.length + " words")
           + ' short:</strong> ' + cutShort.map(function (c) {
             return "\u201c" + esc(c.text) + "\u201d at " + esc(clock(c.edit_s || 0));
           }).join(", ")
           + '. Say the line again, or ask for a patch in Request an editing change.</p>';
    }
    // 28-Sep: what the editor took out (lines said twice, talk to the dogs), so
    // nothing disappears unseen. Bringing one back is an editing request.
    var removed = item.removed || [];
    if (removed.length) {
      html += '<details class="removed"><summary>Took out ' + removed.length + " "
           + plural(removed.length, "thing") + "</summary><ul>";
      removed.forEach(function (r) {
        html += "<li><span class=\"source\">" + esc(clock(r.start || 0)) + "</span> \u201c"
             + esc(r.text) + "\u201d <span class=\"source\">" + esc(r.why || r.reason || "") + "</span></li>";
      });
      html += '</ul><p class="source">To bring one back, use Request an editing change.</p></details>';
    }
    // 1-Oct: the last notes he gave in the notes sheet, every one with what came of it.
    var made = item.notes_made;
    if (made) html += notesMadeHtml(made, item);
    // Notes given in the sheet that wait for his "make it" (the sheet was closed).
    if (item.waiting_notes) {
      html += '<button class="btn primary waiting-notes" type="button" data-talk-edit="' + esc(item.upload_id) + '">'
           + esc(noteWord(item.waiting_notes)) + " waiting - Make the new version</button>";
    }
    var last = item.last_request;
    // A note of those sittings is already in the list above.
    if (last && made && last.session_id && last.session_id === made.session_id) last = null;
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
        // 28-Sep: the phone plays the light 720p copy; the full edit is the download.
        // 30-Sep: the render's own id on the address, so a new edit never plays from
        // pieces of the old one the phone kept.
        var query = [];
        if (action.key === "watch_edit" && item.has_preview) query.push("preview=1");
        if (action.key === "watch_edit" && item.render_ref) query.push("v=" + encodeURIComponent(item.render_ref));
        var play = file + (query.length ? "?" + query.join("&") : "");
        html += '<button class="btn' + (action.key === "watch_edit" ? " primary" : "")
             + '" type="button" data-watch="' + play + '">' + esc(action.label) + "</button>";
        html += '<a class="btn quiet" href="' + file + '?download=1" download>'
             + (action.key === "watch_edit" ? "Download the edit" : "Download") + "</a>";
      } else if (action.key === "captions") {
        html += '<a class="btn quiet" href="' + apiV1 + "/production/uploads/" + esc(item.upload_id) + '/captions.srt">' + esc(action.label) + "</a>";
      } else if (action.key === "talk_edit") {
        // 1-Oct: the notes sheet, at /library/<id>/talk.
        html += '<button class="btn" type="button" data-talk-edit="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "request_edit") {
        html += '<button class="btn" type="button" data-edit-request="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "edit_now") {
        // 4-Oct: never edited, archived by his choice after Stop or brought back. One tap edits it.
        html += '<button class="btn primary" type="button" data-edit-now="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "edit_again") {
        html += '<button class="btn quiet" type="button" data-edit-again="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "check_again") {
        // 3-Oct: Jennifer's check, on demand.
        html += '<button class="btn quiet" type="button" data-check-again="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "release_hold") {
        html += '<button class="btn" type="button" data-release-hold="' + esc(item.upload_id) + '">' + esc(action.label) + "</button>";
      } else if (action.key === "re_record" && item.candidate_id) {
        // To this topic, not to the list: the studio lists only what is left to
        // film, so a topic he filmed is reached by name (28-Sep review).
        html += '<a class="btn quiet" href="' + prefix + "/record?candidate="
             + esc(item.candidate_id) + '">' + esc(action.label) + "</a>";
      }
    });
    // 27-Sep: "need to be able to archive". Kept on the server; Archived brings it back.
    html += item.archived
      ? '<div class="actions"><button class="btn" type="button" data-unarchive="' + esc(item.upload_id) + '">Bring it back</button></div>'
      : '<div class="actions"><button class="btn quiet" type="button" data-archive="' + esc(item.upload_id) + '">Archive</button></div>';
    html += '</div><div class="player" hidden></div>';
    if (item.has_edit && !item.archived) html += publishSection(item);
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
    linkedin: [["message", "Post", 10], ["hashtags", "Hashtags (comma separated)", 1]],
    // A client workspace's fourth platform (5-Oct); owners never have one.
    tiktok: [["caption", "Caption", 4]]
  };
  var PUB_STATUS = { draft: "Ready to post", posting: "Posting now", scheduled: "Scheduled",
                     posted: "Posted", failed: "Did not go out", revising: "Being changed" };

  function publishSection(item) {
    if (state.library && state.library.post_by_hand) return handPostSection(item);
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

  /* 5-Oct (Ziv): "Publishing optional: he downloads the finished video and the post copy
     and posts himself." A client's card: the finished video to download, and each
     platform's post to copy (as it reads on screen, so his own edits go with it). No
     Post, no Schedule: TCE never posts for a client (the server refuses it too). */
  var HAND_STATUS = { draft: "Ready to copy", failed: "Ready to copy", revising: "Being changed" };

  function handPostSection(item) {
    var pubs = item.publishing || [];
    var id = esc(item.upload_id);
    var file = apiV1 + "/production/uploads/" + id + "/edited";
    var html = '<section class="publish" data-pub-upload="' + id + '"><h4>Your video and posts</h4>';
    html += '<p class="section-hint">' + esc(state.library.post_by_hand) + "</p>";
    html += '<div class="actions"><a class="btn primary" href="' + file + '?download=1" download>Download</a></div>';
    if (!pubs.length) {
      var writing = state.pubWriting && state.pubWriting[item.upload_id];
      html += writing
        ? '<p class="notice">Writing your posts. This card fills in when they are ready.</p>'
        : '<div class="actions"><button class="btn" type="button" data-pub-draft="' + id + '">Write the posts</button></div>';
      return html + "</section>";
    }
    pubs.forEach(function (p) {
      var busy = p.status === "revising";
      html += '<div class="pub-platform" data-platform="' + esc(p.platform) + '">';
      html += '<div class="pub-head"><strong>' + esc(p.label) + "</strong>"
           + '<span class="tag">' + esc(HAND_STATUS[p.status] || PUB_STATUS[p.status] || p.status) + "</span></div>";
      if (p.detail) html += '<p class="source">' + esc(p.detail) + "</p>";
      (PUB_FIELDS[p.platform] || []).forEach(function (f) {
        var value = p.copy[f[0]];
        if (Array.isArray(value)) value = value.join(", ");
        html += '<label class="pub-field"><span>' + esc(f[1]) + "</span>";
        html += f[2] > 1
          ? '<textarea rows="' + f[2] + '" data-pub-field="' + f[0] + '"' + (busy ? " readonly" : "") + ">" + esc(value || "") + "</textarea>"
          : '<input type="text" data-pub-field="' + f[0] + '" value="' + esc(value || "") + '"' + (busy ? " readonly" : "") + ">";
        html += "</label>";
      });
      html += '<div class="actions"><button class="btn" type="button" data-pub-copy="' + esc(p.platform) + '">Copy</button></div>';
      html += "</div>";
    });
    if (pubs.some(function (p) { return p.status === "draft" || p.status === "failed"; })) {
      html += '<label class="pub-field"><span>Ask for a change to the posts</span>'
           + '<textarea rows="2" class="pub-change" placeholder="For example: shorter, and open with the question"></textarea></label>'
           + '<div class="actions"><button class="btn" type="button" data-pub-revise="' + id + '">Change the posts</button>'
           + '<button class="btn quiet" type="button" data-pub-draft="' + id + '">Write them again</button></div>';
    }
    return html + "</section>";
  }

  // What one platform's post reads on screen, field after field, ready to paste.
  function handCopyText(section, platform) {
    var box = section.querySelector('.pub-platform[data-platform="' + platform + '"]');
    var parts = [];
    box.querySelectorAll("[data-pub-field]").forEach(function (el) {
      var v = (el.value || "").trim();
      if (v) parts.push(v);
    });
    return parts.join("\n\n");
  }

  async function copyPost(button) {
    var section = button.closest("[data-pub-upload]");
    var text = handCopyText(section, button.getAttribute("data-pub-copy"));
    var ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (e) {
      // An older phone browser: the classic way.
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
      ta.remove();
    }
    if (!ok) { toast("Could not copy. Select the text and copy it yourself.", true); return; }
    button.textContent = "Copied";
    toast("Copied. Paste it in the app.");
    setTimeout(function () { if (button.isConnected) button.textContent = "Copy"; }, 2500);
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

  /* 3-Oct: what Jennifer found when she checked this edit. A pass shows "Checked by
     Jennifer" with its numbers; a hold shows her one line as the thing that needs him
     (the card's own sentence already says it, so here are only the other findings);
     while she checks, the card's sentence is her live step. */
  function checkHtml(item) {
    var c = item.qc;
    if (!c || c.state === "checking") return "";
    if (c.state === "held") {
      var more = (c.problems || []).slice(1);
      var held = '<p class="notice is-bad"><strong>' + esc(c.label || "Jennifer is holding this") + ".</strong> "
               + "Give her a note to fix it, or let it through if it is fine as it is.</p>";
      if (more.length) {
        held += '<details class="removed"><summary>' + more.length + " more " + plural(more.length, "thing")
              + " she found</summary><ul>";
        more.forEach(function (p) { held += "<li>" + esc(p) + "</li>"; });
        held += "</ul></details>";
      }
      return held;
    }
    var good = c.state === "passed" || c.state === "fixed";
    return '<p class="notice' + (good ? " is-good" : "") + '">' + esc(c.line || c.label || "") + "</p>";
  }

  async function checkAgain(uploadId) {
    try {
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/check", { method: "POST" });
      toast("Jennifer is checking this edit. The card shows each thing she checks as she goes.");
      await refreshLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function releaseHold(uploadId) {
    if (!window.confirm("Let this video through as it is? Jennifer's finding stays on its record.")) return;
    try {
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/check/release", { method: "POST" });
      toast("Let through. The video is ready, and its posts are being written.");
      await refreshLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ------------------------------------------------- Jennifer's rules (3-Oct)

  /* "Every note to Jennifer becomes a rule applied to every next video; a Jennifer's
     rules page lists each rule with its source video; he can delete any rule."
     Delete switches the rule off on the server (the row is kept there). */
  async function renderRules() {
    var view = $("view");
    view.innerHTML = '<div class="page">' + working("Reading the rules Jennifer learned from your notes") + "</div>";
    var data = await api("/production/editor-rules");
    var rules = data.rules || [];
    var html = '<div class="page">';
    html += '<div class="page-head"><p class="kicker">Library</p><h1>Jennifer\'s rules</h1>';
    html += '<p class="lede">Each rule came from a note you gave on a video. Jennifer applies them to every '
          + "next video, when she edits it and when she checks it. Delete one and she stops using it.</p></div>";
    if (!rules.length) {
      html += '<div class="empty"><strong>No rules yet</strong>'
            + "When a note you give Jennifer on a video is about more than that one video, it shows up here.</div>";
    } else {
      html += '<div class="card-list">';
      rules.forEach(function (r) {
        html += '<article class="card rule-card">';
        html += "<h3>" + esc(r.text) + "</h3>";
        var used = r.times_applied
          ? "Applied on " + r.times_applied + " " + plural(r.times_applied, "video")
          : "Not applied on a video yet";
        html += '<p class="source">' + esc(used) + (r.created_at ? " &middot; learned " + esc(when(r.created_at)) : "") + "</p>";
        if (r.in_use === false) {
          // 3-Oct review: older than the newest rules that fit in what she reads.
          html += '<p class="source">Not used right now: Jennifer reads only the newest rules that fit, '
                + "and this one is older. Delete a rule you no longer need to bring it back.</p>";
        }
        if (r.source_note) {
          html += '<p class="source">From your note: &#8220;' + esc(r.source_note) + "&#8221;</p>";
        }
        html += '<div class="actions">';
        if (r.source_upload_id && r.source_has_edit) {
          // One link, one destination: that video's own notes sheet, not the list.
          html += '<button class="btn" type="button" data-go="/library/' + esc(r.source_upload_id) + '/talk">'
                + "Open the video it came from: " + esc(r.source_title || "untitled") + "</button>";
        } else if (r.source_title) {
          html += '<span class="source">From the video: ' + esc(r.source_title) + "</span>";
        } else {
          html += '<span class="source">The video it came from is no longer in your Library.</span>';
        }
        html += '<button class="btn quiet" type="button" data-rule-delete="' + esc(r.id) + '">Delete this rule</button>';
        html += "</div></article>";
      });
      html += "</div>";
    }
    html += '<div class="actions"><button class="btn" type="button" data-go="/library">Back to the Library</button></div>';
    html += "</div>";
    view.innerHTML = html;
    status(rules.length + " " + plural(rules.length, "rule"));
  }

  async function deleteRule(ruleId) {
    if (!window.confirm("Delete this rule? Jennifer stops applying it from the next video on.")) return;
    try {
      await api("/production/editor-rules/" + encodeURIComponent(ruleId), { method: "DELETE" });
      toast("Deleted. Jennifer no longer applies that rule.");
      await renderRules();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function editAgain(uploadId) {
    if (!window.confirm("Edit this video again with the tight cut and the new captions? The current edit is replaced when the new one is ready.")) return;
    try {
      await api("/production/uploads/" + encodeURIComponent(uploadId) + "/auto-edit", { method: "POST" });
      toast("Editing it again. The card shows each step as it happens.");
      renderLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // 4-Oct review: one tap, one edit. A second tap while the first is on its way does
  // nothing here, and the server answers a repeat with the edit already running.
  var editNowSent = {};
  async function editNow(uploadId) {
    if (editNowSent[uploadId]) return;
    editNowSent[uploadId] = true;
    try {
      var row = await api("/production/uploads/" + encodeURIComponent(uploadId) + "/auto-edit", { method: "POST" });
      var fromArchive = String((row && row.status_detail) || "").indexOf("Taken out of Archived") === 0;
      toast(fromArchive
        ? "Editing it now. It left Archived: find it under Still to do, where the card shows each step."
        : "Editing it now. The card shows each step as it happens.");
      renderLibrary();
    } catch (error) {
      toast(error.message, true);
    } finally {
      delete editNowSent[uploadId];
    }
  }

  async function archiveRecording(uploadId, archived) {
    try {
      await api("/production/recordings/" + encodeURIComponent(uploadId) + "/archive", {
        method: "POST", body: { archived: archived }
      });
      toast(archived ? "Archived. It is under the Archived filter, and nothing was deleted."
                     : "Back in your Library.");
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
    if (!box.hidden && box.getAttribute("data-src") === src) { putPlayerAway(box); return; }
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
  // He put the player away himself: a change made while it played is drawn now (refreshLibrary).
  function putPlayerAway(box) {
    closePlayer(box);
    if (state.libraryStale && parse().name === "library") renderLibrary();
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
    var text = window.prompt("What should change about this video?\n\nSay it the way you would say it to Jennifer, your video editor.");
    if (text === null || !text.trim()) return;
    try {
      var saved = await api("/production/recordings/" + encodeURIComponent(uploadId) + "/edit-requests", {
        method: "POST",
        body: { request: text.trim(), scope: "whole" }
      });
      // 30-Sep: while he is giving notes on this video, a typed request waits with them.
      toast(saved && saved.joined_sitting
        ? "Added to the notes you are giving on this video. It is made with them when you tap Make the new version."
        : "Asked. TCE is making the change now on your subscription; this card updates as it goes.");
      // 1-Oct (design step 5): never by redrawing the page under a video he is watching.
      await refreshLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  }

  /* After a change made from a card: the Library is drawn again, unless a video is
     playing in one of its cards. Redrawing would take that player away mid-watch
     (it used to: "Request an editing change" called render()), so the redraw waits
     until he puts the player away. */
  async function refreshLibrary() {
    if (document.querySelector(".player:not([hidden])")) {
      state.libraryStale = true;
      clearTimeout(state.libraryPoll);
      state.libraryPoll = setTimeout(pollLibrary, 8000);
      return;
    }
    state.libraryStale = false;
    await renderLibrary();
  }

  // ------------------------------------------- Talk to the editor (1-Oct)

  /* The notes sheet, at /library/<id>/talk (plans/30-Sep-26-talk-to-the-editor.md,
   * section 1, build step 5). He watches the edit, pauses, says or types what is
   * wrong, and plays on. Each note is pinned to the paused second, and nothing
   * changes until he taps Make the new version and says yes to the read-back; then
   * one job reads every note and the video renders once.
   *
   * The sheet lives outside #view, so drawing a page never touches its player:
   * opening it again for the same video changes nothing, and only its own close,
   * Escape or Back takes the player away. The talking half is talk-voice.js
   * (TceTalkVoice), started when the sheet opens: it draws the hold bar and the
   * notes, and reads the sitting every few seconds. This part owns the video,
   * typing, Make the new version, and closing. */

  var NOTE_WAITING = ["listening", "held"];
  var NOTES_WORKING = ["thinking", "rendering"];
  var NOTES_RETRY_MS = 5000;   // the video is being edited: try opening the notes again
  var NOTES_SAY_MS = 9000;     // how long a sentence of the sheet's own stays

  function noteWord(n) { return n + " " + plural(n, "note"); }

  // 0:38, the way the pins say it (whole seconds, never rounded up).
  function atClock(seconds) {
    var total = Math.floor(Math.max(0, Number(seconds) || 0));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  // Notes that go to the editor at "make it": waiting, with his words or a reading.
  function readyNotes(sitting) {
    return ((sitting && sitting.notes) || []).filter(function (n) {
      return NOTE_WAITING.indexOf(n.state) >= 0
        && (String(n.request || "").trim() || String(n.understood || "").trim());
    });
  }

  /* The card's account of the last notes made into a new version: the batch's own
     step while it runs, then every note with what came of it. */
  function notesMadeHtml(made, item) {
    var notes = made.notes || [];
    if (NOTES_WORKING.indexOf(made.state) >= 0) {
      return '<p class="notice"><strong>Making the new version from your ' + esc(noteWord(notes.length))
           + ":</strong> " + esc(made.status || item.state_sentence || "Jennifer is reading them.") + "</p>";
    }
    var needs = notes.filter(function (n) { return n.state === "needs_you"; }).length;
    var html = '<details class="removed notes-made"' + (needs ? " open" : "") + "><summary>Your last "
             + esc(noteWord(notes.length)) + (needs ? ": " + needs + (needs === 1 ? " needs" : " need") + " you" : "")
             + "</summary>";
    if (made.status) html += '<p class="source">' + esc(made.status) + "</p>";
    html += "<ul>";
    notes.forEach(function (n) {
      var said = String(n.said || "").trim() || n.understood || "";
      var outcome = n.undone ? ["Put back", "The version from before these notes was put back."]
        : n.state === "needs_you" ? ["Needs you", n.question || n.reply || "Jennifer has a question."]
        : n.state === "done" ? ["Done", n.reply || "Done."]
        : null;
      html += '<li><span class="source">' + esc(n.where) + "</span>&#8220;" + esc(said) + "&#8221;";
      if (outcome) html += "<br><strong>" + outcome[0] + ":</strong> " + esc(outcome[1]);
      // 3-Oct: what Jennifer took from this note for the next videos.
      if (n.learned && n.learned.line && !n.undone) {
        html += '<br><span class="source">' + esc(n.learned.line) + "</span>";
      }
      html += "</li>";
    });
    return html + "</ul></details>";
  }

  // The card's "Talk to the editor" (or "3 notes waiting"): the sheet gets its own address.
  function openNotesFromCard(uploadId) {
    window.history.pushState({ notesFrom: "library" }, "", prefix + "/library/" + uploadId + "/talk");
    render();
  }

  async function renderNotesRoute(uploadId) {
    // The Library stays under the sheet: closing it lands on this video's card.
    if (!document.querySelector("[data-libfilter]")) {
      try { await renderLibrary(); }
      catch (error) {
        $("view").innerHTML = '<div class="page"><div class="empty"><strong>Could not open the Library</strong>'
          + esc(error.message) + "</div></div>";
      }
    }
    openNotesSheet(uploadId);
  }

  function openNotesSheet(uploadId) {
    var open = state.notesSheet;
    // Never built twice: a page drawn again must not take the player away mid-sitting.
    if (open && open.uploadId === uploadId) return;
    if (open) closeNotesSheet();
    // One video at a time: a player open in a card stops.
    document.querySelectorAll(".player").forEach(function (box) { if (!box.hidden) closePlayer(box); });
    var sheet = {
      uploadId: uploadId, sitting: null, talk: null, video: null,
      typed: null,       // {saving}: the typed note being written
      readBack: null,    // {text, check, count}: waiting for his yes
      busy: false, retry: null, sayTimer: null, noteCount: 0
    };
    state.notesSheet = sheet;
    $("notesContext").textContent = libraryTitle(uploadId);
    if (!$("notesContext").textContent) {
      // Opened from a link, on a list that does not show this video: ask for its name.
      api("/production/library?filter=all").then(function (data) {
        var item = (data.items || []).filter(function (i) { return i.upload_id === uploadId; })[0];
        if (item && state.notesSheet === sheet) $("notesContext").textContent = item.title;
      }).catch(function () { /* the title is a nicety */ });
    }
    var body = $("notesBody");
    body.className = "notes-body is-message";
    body.innerHTML = working("Opening your notes on this video");
    $("notesFoot").innerHTML = "";
    $("notesFoot").hidden = true;
    $("notesSheet").hidden = false;
    document.body.classList.add("notes-open");
    openSitting(sheet);
  }

  function libraryTitle(uploadId) {
    var items = (state.library && state.library.items) || [];
    var item = items.filter(function (i) { return i.upload_id === uploadId; })[0];
    return item ? item.title : "";
  }

  // A sentence in place of the sheet: why the notes did not open, or what they wait for.
  function notesMessage(sheet, title, text, step) {
    if (state.notesSheet !== sheet) return;
    var body = $("notesBody");
    body.className = "notes-body is-message";
    body.innerHTML = '<div class="empty"><strong>' + esc(title) + "</strong>" + esc(text) + "</div>"
      + (step ? working(step) : "")
      + '<div class="actions"><button class="btn" type="button" data-ns-leave>Back to the Library</button></div>';
  }

  async function openSitting(sheet) {
    clearTimeout(sheet.retry);
    var payload;
    try {
      payload = await api("/production/recordings/" + encodeURIComponent(sheet.uploadId) + "/talk", { method: "POST" });
    } catch (error) {
      if (state.notesSheet !== sheet) return;
      if (error.status === 409 && (error.detail || {}).code === "busy") {
        // 3-second rule: what is editing the video right now, and that the notes follow it.
        notesMessage(sheet, "Your notes open when this is done", error.message,
          "Checking again every few seconds");
        sheet.retry = setTimeout(function () { openSitting(sheet); }, NOTES_RETRY_MS);
        return;
      }
      notesMessage(sheet, "Your notes did not open", error.message);
      return;
    }
    if (state.notesSheet !== sheet) {
      // Closed while it opened. An empty sitting closes again; one with notes stays (409).
      api("/production/talk/" + payload.session_id + "/close", { method: "POST" }).catch(function () {});
      return;
    }
    buildNotesSheet(sheet, payload);
  }

  function buildNotesSheet(sheet, payload) {
    sheet.sitting = payload;
    var body = $("notesBody");
    body.className = "notes-body";
    /* Native fullscreen hides every button of the sheet, and picture in picture takes
       the video out of it, so both are off. playsinline keeps it in the page. */
    body.innerHTML =
        '<video class="ns-player" controls playsinline webkit-playsinline controlslist="nofullscreen"'
      + ' disablepictureinpicture preload="metadata"></video>'
      + '<div class="ns-notes">'
      + '<p class="notice ns-message" role="status" hidden></p>'
      + '<div class="ns-panel ns-readback" hidden></div>'
      + '<div class="ns-panel ns-typed" hidden></div>'
      + '<ol class="ns-list" aria-label="Your notes on this video"></ol>'
      + "</div>";
    var foot = $("notesFoot");
    foot.hidden = false;
    foot.innerHTML = '<div class="ns-talk"></div><div class="ns-make-row"></div>';
    sheet.video = body.querySelector(".ns-player");
    setNotesVideo(sheet, payload.file_url);
    // The typed note says the second it will be pinned to, as the player moves.
    ["pause", "seeked", "timeupdate"].forEach(function (type) {
      sheet.video.addEventListener(type, function () { if (sheet.typed) paintTypedSecond(sheet); });
    });
    startTalking(sheet, payload);
    paintMake(sheet);
    /* 1-Oct final review: an earlier re-edit's cut waits for his eyes, so no new version
       can be made from notes yet. He hears it now, not first at Make. */
    if (payload.blocked) notesSay(sheet, payload.blocked, true);
  }

  // The hold bar and the notes list: talk-voice.js, on this sitting.
  function startTalking(sheet, payload) {
    var root = $("notesFoot").querySelector(".ns-talk");
    var list = $("notesBody").querySelector(".ns-list");
    if (!window.TceTalkVoice) {
      root.innerHTML = '<p class="notice is-bad">Hold to talk did not load on this page. Reload it to talk; '
        + "Type still saves a note.</p>";
      return;
    }
    sheet.noteCount = (payload.notes || []).filter(function (n) { return n.state !== "rejected"; }).length;
    sheet.talk = window.TceTalkVoice.open({
      root: root,
      video: sheet.video,
      sitting: payload,
      notes: list,
      api: api,
      onSitting: function (p) { if (state.notesSheet === sheet) tookSitting(sheet, p); },
      onStale: function (ref, p) { if (state.notesSheet === sheet) newRender(sheet, p); }
    });
  }

  // Every fresh read of the sitting: the Make button, and the newest note in sight.
  function tookSitting(sheet, p) {
    var was = sheet.sitting ? sheet.sitting.state : null;
    sheet.sitting = p;
    var count = (p.notes || []).filter(function (n) { return n.state !== "rejected"; }).length;
    var region = $("notesBody").querySelector(".ns-notes");
    if (NOTES_WORKING.indexOf(was) >= 0 && (p.state === "done" || p.state === "needs_you")) {
      // Made: the bar says so, and each note says what was done. The notes start at the first.
      var box = region && region.querySelector(".ns-message");
      if (box) box.hidden = true;
      if (region) region.scrollTop = 0;
    } else if (count > sheet.noteCount && region) {
      // The newest note is the last one: bring it into the notes strip.
      region.scrollTop = region.scrollHeight;
    }
    sheet.noteCount = count;
    if (sheet.readBack && p.state !== "open") hideReadBack(sheet);
    paintMake(sheet);
  }

  /* The sitting is on another render: its own new version, or the video was edited
     again under the sheet (the pins moved with it). The player loads that file. */
  function newRender(sheet, p) {
    setNotesVideo(sheet, p.file_url);
    // Its own new version needs no sentence here: the bar says it was made.
    if (p.state === "done" || p.state === "needs_you") return;
    notesSay(sheet, "The video was edited again, so the new version is in the player now. Your notes moved with it.");
  }

  // The address carries the render's id, so a new render never plays from the old one's cached pieces.
  function setNotesVideo(sheet, url) {
    var video = sheet.video;
    if (!video) return;
    if (!url) { notesSay(sheet, "There is no edited file to play yet.", true); return; }
    var src = url.indexOf("/api/") === 0 ? prefix + url : url;
    if (video.getAttribute("src") === src) return;
    if (!video.paused) video.pause();
    video.setAttribute("src", src);
    video.load();
  }

  // A sentence of the sheet's own, at the top of the notes (never a toast over the bar).
  function notesSay(sheet, text, bad) {
    if (state.notesSheet !== sheet) return;
    var box = $("notesBody").querySelector(".ns-message");
    if (!box) return;
    box.textContent = text;
    box.classList.toggle("is-bad", Boolean(bad));
    box.hidden = false;
    var region = box.closest(".ns-notes");
    if (region) region.scrollTop = 0;
    clearTimeout(sheet.sayTimer);
    sheet.sayTimer = setTimeout(function () { box.hidden = true; }, NOTES_SAY_MS);
  }

  // Typing or the read-back needs room: the video gives some up until it is done.
  function roomForNotes(sheet) {
    $("notesBody").classList.toggle("is-writing", Boolean(sheet.typed || sheet.readBack));
  }

  /* The bar's second row. Taking notes: Type, and Make the new version (N notes).
     Read back: Not yet, and Yes, make it. Being made: what it is doing is the status
     line above it. Made: give notes on the new version. A fixed height, so the hold
     button above never moves whatever this says. */
  function paintMake(sheet) {
    var row = $("notesFoot").querySelector(".ns-make-row");
    if (!row) return;
    var p = sheet.sitting || {};
    var html, one = false;
    if (p.state === "open") {
      if (sheet.readBack) {
        html = '<button class="btn quiet" type="button" data-ns-not-yet>Not yet</button>'
             + '<button class="btn primary" type="button" data-ns-confirm' + (sheet.busy ? " disabled" : "") + ">"
             + (sheet.busy ? "Starting the new version" : "Yes, make it (" + noteWord(sheet.readBack.count) + ")")
             + "</button>";
      } else {
        var n = readyNotes(p).length;
        html = '<button class="btn" type="button" data-ns-type aria-label="Type a note at the paused second"'
             + ' aria-pressed="' + (sheet.typed ? "true" : "false") + '">Type</button>'
             + '<button class="btn primary" type="button" data-ns-make' + (n && !sheet.busy ? "" : " disabled") + ">"
             + (sheet.busy ? "Reading your notes back"
                : n ? "Make the new version (" + noteWord(n) + ")"
                : "Make the new version (no notes yet)")
             + "</button>";
      }
    } else if (NOTES_WORKING.indexOf(p.state) >= 0) {
      var making = ((p.result || {}).notes || []).length;
      html = '<button class="btn primary" type="button" disabled>Making the new version'
           + (making ? " (" + noteWord(making) + ")" : "") + "</button>";
      one = true;
    } else {
      html = '<button class="btn primary" type="button" data-ns-again>'
           + (p.state === "closed" ? "Open the notes again" : "Give notes on the new version") + "</button>";
      one = true;
    }
    row.classList.toggle("is-one", one);
    if (row.innerHTML !== html) row.innerHTML = html;
  }

  function onNotesClick(event) {
    var sheet = state.notesSheet;
    var target = event.target.closest && event.target.closest(
      "[data-ns-type],[data-ns-save],[data-ns-cancel],[data-ns-make],[data-ns-confirm],"
      + "[data-ns-not-yet],[data-ns-again],[data-ns-leave]");
    if (!target || !sheet) return;
    var d = target.dataset;
    if (d.nsLeave !== undefined) { leaveNotesSheet(); return; }
    if (d.nsType !== undefined) { if (sheet.typed) cancelTyped(sheet); else startTyped(sheet); return; }
    if (d.nsSave !== undefined) { saveTyped(sheet); return; }
    if (d.nsCancel !== undefined) { cancelTyped(sheet); return; }
    if (d.nsMake !== undefined) { askReadBack(sheet); return; }
    if (d.nsConfirm !== undefined) { confirmMake(sheet); return; }
    if (d.nsNotYet !== undefined) { hideReadBack(sheet); paintMake(sheet); return; }
    if (d.nsAgain !== undefined) { notesAgain(sheet); return; }
  }

  // ---- typing: a note pinned to the second the player is paused on

  function startTyped(sheet) {
    if (!sheet.sitting || sheet.sitting.state !== "open") return;
    if (sheet.video && !sheet.video.paused) sheet.video.pause();
    hideReadBack(sheet);
    sheet.typed = { saving: false };
    var panel = $("notesBody").querySelector(".ns-typed");
    panel.innerHTML =
        '<label class="ns-typed-label" for="nsTyped">Your note at <span data-ns-at></span></label>'
      + '<textarea id="nsTyped" rows="3" placeholder="What is wrong at this moment? For example: cut the second basically."></textarea>'
      + '<div class="btn-row"><button class="btn quiet" type="button" data-ns-cancel>Cancel</button>'
      + '<button class="btn primary" type="button" data-ns-save>Save the note at <span data-ns-at></span></button></div>';
    panel.hidden = false;
    paintTypedSecond(sheet);
    roomForNotes(sheet);
    paintMake(sheet);
    var region = panel.closest(".ns-notes");
    if (region) region.scrollTop = 0;
    var box = $("nsTyped");
    if (box) box.focus();
  }

  function typedSecond(sheet) { return sheet.video ? Number(sheet.video.currentTime) || 0 : 0; }

  function paintTypedSecond(sheet) {
    if (!sheet.typed || sheet.typed.saving) return;
    var at = atClock(typedSecond(sheet));
    $("notesBody").querySelectorAll(".ns-typed [data-ns-at]").forEach(function (el) {
      if (el.textContent !== at) el.textContent = at;
    });
  }

  function cancelTyped(sheet) {
    sheet.typed = null;
    var panel = $("notesBody").querySelector(".ns-typed");
    if (panel) { panel.hidden = true; panel.innerHTML = ""; }
    roomForNotes(sheet);
    paintMake(sheet);
  }

  async function saveTyped(sheet) {
    if (!sheet.typed || sheet.typed.saving) return;
    var box = $("nsTyped");
    var text = box ? box.value.trim() : "";
    if (!text) { notesSay(sheet, "Write what is wrong at this moment first.", true); return; }
    // The note goes where the player is paused, and the player stays paused there.
    if (sheet.video && !sheet.video.paused) sheet.video.pause();
    var t = typedSecond(sheet);
    var save = $("notesBody").querySelector("[data-ns-save]");
    sheet.typed.saving = true;
    if (save) { save.disabled = true; save.textContent = "Saving the note at " + atClock(t); }
    var sid = sheet.sitting.session_id;
    var ref = sheet.talk ? sheet.talk.renderRef : sheet.sitting.render_ref;
    var pinned = null;
    try {
      pinned = await api("/production/talk/" + sid + "/notes", {
        method: "POST", body: { edit_s: Math.round(t * 100) / 100, render_ref: ref || null }
      });
      await api("/production/talk/" + sid + "/notes/" + pinned.note_id, {
        method: "PATCH", body: { heard: text }
      });
    } catch (error) {
      if (pinned) {
        // The words did not land: the empty pin is taken back, and his words stay in the box.
        api("/production/talk/" + sid + "/notes/" + pinned.note_id, { method: "PATCH", body: { drop: true } })
          .catch(function () { /* it reads "listening" until the next try */ });
      }
      if (state.notesSheet !== sheet || !sheet.typed) return;
      sheet.typed.saving = false;
      if (save) { save.disabled = false; save.innerHTML = "Save the note at <span data-ns-at></span>"; }
      paintTypedSecond(sheet);
      if (error.status === 409 && (error.detail || {}).code === "stale_render") {
        await reopenNotes(sheet);
        notesSay(sheet, "The video was edited again, so the new version is in the player now. "
          + "Your words are still in the box: pause where they belong and save again.", true);
      } else {
        notesSay(sheet, error.message || "That note could not be saved. Your words are still in the box.", true);
      }
      return;
    }
    if (state.notesSheet !== sheet) return;
    cancelTyped(sheet);
    notesSay(sheet, "Saved your note at " + (pinned.clock || atClock(t)) + ".");
    if (sheet.talk) sheet.talk.refresh();
  }

  /* The video was edited under the notes: opening them again moves the sitting and its
     notes onto the new render, and the next read of it loads that file in the player. */
  async function reopenNotes(sheet) {
    try {
      await api("/production/recordings/" + encodeURIComponent(sheet.uploadId) + "/talk", { method: "POST" });
    } catch (error) {
      notesSay(sheet, error.message, true);
      return;
    }
    if (sheet.talk) await sheet.talk.refresh();
  }

  // ---- Make the new version: read back, then his yes with the read-back's check code

  async function askReadBack(sheet) {
    if (sheet.busy || !sheet.sitting) return;
    if (sheet.video && !sheet.video.paused) sheet.video.pause();
    sheet.busy = true;
    paintMake(sheet);
    try {
      var preview = await api("/production/talk/" + sheet.sitting.session_id + "/submit");
      if (state.notesSheet !== sheet) return;
      showReadBack(sheet, preview.read_back, preview.check, preview.count, false);
    } catch (error) {
      if (state.notesSheet !== sheet) return;
      await makeRefused(sheet, error);
    } finally {
      sheet.busy = false;
      paintMake(sheet);
    }
  }

  function showReadBack(sheet, text, check, count, changed) {
    if (sheet.typed && !sheet.typed.saving) cancelTyped(sheet);
    sheet.readBack = { text: text, check: check, count: count };
    // The read-back is the news now: an older sentence would push it out of sight.
    var said = $("notesBody").querySelector(".ns-message");
    if (said) said.hidden = true;
    var panel = $("notesBody").querySelector(".ns-readback");
    panel.innerHTML = "<h3>" + (changed ? "Your notes changed, so here they are again"
                                        : "Make the new version from these notes?") + "</h3>"
      + "<p>" + esc(text) + "</p>"
      + '<p class="source">Nothing changes until you tap Yes. Then Jennifer reads every note, '
      + "and the video renders once.</p>";
    panel.hidden = false;
    roomForNotes(sheet);
    var region = panel.closest(".ns-notes");
    if (region) region.scrollTop = 0;
  }

  function hideReadBack(sheet) {
    sheet.readBack = null;
    var panel = $("notesBody").querySelector(".ns-readback");
    if (panel) { panel.hidden = true; panel.innerHTML = ""; }
    roomForNotes(sheet);
  }

  async function confirmMake(sheet) {
    if (!sheet.readBack || sheet.busy) return;
    sheet.busy = true;
    paintMake(sheet);
    try {
      var payload = await api("/production/talk/" + sheet.sitting.session_id + "/submit", {
        method: "POST", body: { check: sheet.readBack.check }
      });
      if (state.notesSheet !== sheet) return;
      hideReadBack(sheet);
      sheet.sitting = payload;
      notesSay(sheet, "Jennifer is reading every note now. The bar says each step, "
        + "and each note says what was done with it.");
      if (sheet.talk) {
        // 1-Oct final review: nothing more is said on the call while the notes are made,
        // so it ends (Live bills every minute, silence too) and the screen may sleep.
        sheet.talk.hangUp();
        sheet.talk.refresh();
      }
    } catch (error) {
      if (state.notesSheet !== sheet) return;
      var d = error.detail || {};
      if (error.status === 409 && d.code === "changed" && d.check && d.read_back) {
        // A note came, went or was re-said since the read-back: he hears the new one.
        var n = parseInt(String(d.read_back), 10);
        showReadBack(sheet, d.read_back, d.check, isNaN(n) ? sheet.readBack.count : n, true);
      } else {
        hideReadBack(sheet);
        await makeRefused(sheet, error);
      }
    } finally {
      sheet.busy = false;
      paintMake(sheet);
    }
  }

  async function makeRefused(sheet, error) {
    var code = (error.detail || {}).code;
    if (error.status === 409 && code === "stale_render") {
      await reopenNotes(sheet);
      notesSay(sheet, "The video was edited again after these notes. They moved to the new version, "
        + "which is in the player now: check them, then make the new version.", true);
      return;
    }
    if (error.status === 409 && code === "no_notes") {
      notesSay(sheet, "There are no notes with words yet. Hold to talk, or tap Type.", true);
      return;
    }
    notesSay(sheet, error.message, true);
    if (sheet.talk) sheet.talk.refresh();
  }

  // The notes were made: a fresh sitting on the version he has now.
  async function notesAgain(sheet) {
    if (sheet.busy) return;
    sheet.busy = true;
    var old = sheet.talk;
    sheet.talk = null;
    if (old) old.close();
    var root = $("notesFoot").querySelector(".ns-talk");
    root.innerHTML = working("Opening new notes on this version");
    try {
      var payload = await api("/production/recordings/" + encodeURIComponent(sheet.uploadId) + "/talk", { method: "POST" });
      if (state.notesSheet !== sheet) return;
      sheet.sitting = payload;
      setNotesVideo(sheet, payload.file_url);
      root.innerHTML = "";
      startTalking(sheet, payload);
    } catch (error) {
      if (state.notesSheet !== sheet) return;
      root.innerHTML = '<p class="notice is-bad">' + esc(error.message) + "</p>";
    } finally {
      sheet.busy = false;
      paintMake(sheet);
    }
  }

  // ---- closing: every note stays on the server

  function closeNotesSheet() {
    var sheet = state.notesSheet;
    if (!sheet) return;
    state.notesSheet = null;
    clearTimeout(sheet.retry);
    clearTimeout(sheet.sayTimer);
    var talk = sheet.talk;
    sheet.talk = null;
    // The call ends once his last words have landed on their note (talk-voice.js).
    var ended = talk ? talk.close() : null;
    if (sheet.video) {
      try { sheet.video.pause(); sheet.video.removeAttribute("src"); sheet.video.load(); }
      catch (e) { /* already gone */ }
    }
    $("notesSheet").hidden = true;
    $("notesBody").innerHTML = "";
    $("notesFoot").innerHTML = "";
    document.body.classList.remove("notes-open");
    var sid = sheet.sitting && sheet.sitting.session_id;
    if (!sid) return;
    /* A sitting with nothing waiting closes, so nothing joins it and its hold on the
       video lapses at once. One with notes waiting stays open (the route answers 409),
       and its card says "N notes waiting - Make the new version". */
    Promise.resolve(ended).then(function () {
      return api("/production/talk/" + sid + "/close", { method: "POST" });
    }).catch(function () { /* notes wait in it: it stays open, as it should */ });
  }

  function leaveNotesSheet() {
    var fromLibrary = window.history.state && window.history.state.notesFrom === "library";
    closeNotesSheet();
    // Back to the Library he came from, so Back does not open the sheet again.
    if (fromLibrary) window.history.back();
    else go("/library", true);
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
    // 27-Sep: new topics found after he hangs up reach him here, not only scripts.
    return '<div class="actions"><button class="btn primary" type="button" data-notify="on">'
         + "Turn on notifications on this phone</button></div>"
         + '<p class="section-hint">New topics you asked for, scripts and edits: a buzz when each is ready.</p>';
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
      var asked = await api("/editorial/candidates/" + encodeURIComponent(candidateId) + "/packet", { method: "POST" });
      // The server says when it comes: "a few minutes" was wrong for two days
      // while his Claude limit was used up (28-Sep).
      var said = (asked && asked.said) || "Asked. The script is written on your PC worker; it takes a few minutes.";
      toast(said);
      // The button is done: it becomes what was said, in place, so the list
      // does not jump back to the top on his phone.
      document.querySelectorAll('[data-ask-script="' + candidateId + '"]').forEach(function (button) {
        var note = document.createElement("p");
        note.className = "section-hint";
        note.textContent = said;
        button.replaceWith(note);
      });
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
    "videos-step", "save-settings", "pub-draft", "pub-post", "pub-schedule", "pub-revise", "pub-copy",
    "save-rules", "archive", "unarchive", "edit-again", "talk-edit", "edit-now"
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
    if (d.pubCopy !== undefined) { copyPost(target); return; }
    if (d.saveRules !== undefined) { saveRules(); return; }
    if (d.archive !== undefined) { archiveRecording(d.archive, true); return; }
    if (d.unarchive !== undefined) { archiveRecording(d.unarchive, false); return; }
    if (d.editAgain !== undefined) { editAgain(d.editAgain); return; }
    if (d.editNow !== undefined) { editNow(d.editNow); return; }
    if (d.checkAgain !== undefined) { checkAgain(d.checkAgain); return; }
    if (d.releaseHold !== undefined) { releaseHold(d.releaseHold); return; }
    if (d.ruleDelete !== undefined) { deleteRule(d.ruleDelete); return; }
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
    if (d.watchClose !== undefined) { putPlayerAway(target.closest(".player")); return; }
    if (d.talkEdit !== undefined) { openNotesFromCard(d.talkEdit); return; }
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
    if (event.key !== "Escape") return;
    if (!$("talkSheet").hidden) { closeSheet(); return; }
    var notes = state.notesSheet;
    if (!notes) return;
    // In the typed note, Escape puts the note away first, not the whole sheet.
    if (notes.typed && document.activeElement && document.activeElement.id === "nsTyped") {
      cancelTyped(notes);
      return;
    }
    leaveNotesSheet();
  });

  // The notes sheet's own close. Its notes stay on the server, and the card says so.
  $("notesClose").addEventListener("click", leaveNotesSheet);
  $("notesSheet").addEventListener("click", onNotesClick);

  var READER_SIZES = ["normal", "large", "largest"];
  /* A step each way that stops at the ends: the old single button cycled, so
     one tap past "largest" threw the page back to the smallest. */
  function stepReader(delta) {
    var current = READER_SIZES.indexOf(document.body.dataset.reader || "normal");
    var next = Math.max(0, Math.min(READER_SIZES.length - 1, (current < 0 ? 0 : current) + delta));
    document.body.dataset.reader = READER_SIZES[next];
    // The buttons left the header on 29-Sep; the saved size still applies.
    if ($("readerSmaller")) $("readerSmaller").disabled = next === 0;
    if ($("readerBigger")) $("readerBigger").disabled = next === READER_SIZES.length - 1;
    try { localStorage.setItem("tce-workspace-reader", READER_SIZES[next]); } catch (e) { /* private mode */ }
  }

  window.addEventListener("popstate", function () { takeFilterFromUrl(); render(); });

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
    /* The header microphone: the same call as the bar's Talk button, or the
       week when this page has nothing specific to talk about. */
    $("talkHeader").href = voiceCallUrl(state.talkContext ? state.talkContext.voice : "week");
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
        /* 5-Oct: a client's own login has no voice call (KM BOT's /voice is outside
           its fence); typing to the editor stays. */
        (window.TCE_SCOPED ? "" : '<a class="bar-btn is-talk" id="talkFab" href="'
        + esc(voiceCallUrl(state.talkContext.voice)) + '">'
        + esc(state.talkContext.action) + "</a>")
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
    return (week.primary || []).filter(toFilmNow)[0] || null;
  }

  async function render() {
    var route = parse();
    // The notes sheet belongs to its own address: any other page puts it away, and
    // its notes stay on the server. On its own address nothing here touches it.
    if (route.name !== "talk") closeNotesSheet();
    state.route = route.name;
    setChrome(route);
    $("actionBar").hidden = true;
    document.body.classList.remove("has-talk");
    try {
      if (route.name === "today") await renderToday();
      else if (route.name === "topics") await renderTopics();
      else if (route.name === "week") await renderWeek();
      else if (route.name === "library") await renderLibrary();
      else if (route.name === "rules") await renderRules();
      else if (route.name === "settings") await renderSettings();
      else if (route.name === "room") await renderRoom(route.id);
      else if (route.name === "workshop") await renderWorkshop(route.id);
      else if (route.name === "talk") await renderNotesRoute(route.id);
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

  takeFilterFromUrl();
  render();
})();
