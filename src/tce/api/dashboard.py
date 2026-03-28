"""Operator dashboard - single HTML page served at /dashboard."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TCE - Operator Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#e4e4e7;--dim:#9ca3af;--accent:#6366f1;--accent2:#818cf8;--green:#22c55e;--red:#ef4444;--yellow:#eab308;--blue:#3b82f6}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:20px;font-weight:600}
.header .status{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--dim)}
.header .dot{width:8px;height:8px;border-radius:50%;background:var(--green)}
.header .dot.off{background:var(--red)}
.nav{display:flex;gap:4px;background:var(--card);padding:8px 24px;border-bottom:1px solid var(--border)}
.nav button{padding:8px 16px;border:none;background:transparent;color:var(--dim);cursor:pointer;border-radius:6px;font-size:13px;font-weight:500}
.nav button.active{background:var(--accent);color:#fff}
.nav button:hover:not(.active){background:var(--border)}
.main{max-width:1200px;margin:0 auto;padding:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px}
.card h3{font-size:14px;color:var(--dim);margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px}
.card .value{font-size:28px;font-weight:700}
.card .sub{font-size:12px;color:var(--dim);margin-top:4px}
.section{margin-bottom:32px}
.section > h2{font-size:18px;margin-bottom:16px;font-weight:600}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:var(--accent);color:#fff}
.btn-green{background:var(--green);color:#000}
.btn-red{background:var(--red);color:#fff}
.btn-blue{background:var(--blue);color:#fff}
.btn-dim{background:var(--border);color:var(--text)}
.btn-group{display:flex;gap:8px;flex-wrap:wrap}
select,input{padding:8px 12px;border:1px solid var(--border);background:var(--card);color:var(--text);border-radius:6px;font-size:13px;color-scheme:dark}
option{background:var(--card);color:var(--text)}
.pipeline-steps{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.step-badge{padding:6px 12px;border-radius:16px;font-size:12px;font-weight:500;border:1px solid var(--border)}
.step-badge.completed{background:#166534;border-color:#22c55e;color:#bbf7d0}
.step-badge.running{background:#1e3a5f;border-color:#3b82f6;color:#93c5fd}
.step-badge.pending{background:var(--card);color:var(--dim)}
.step-badge.failed{background:#7f1d1d;border-color:#ef4444;color:#fecaca}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{width:20px;height:20px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0}
.plan-steps{display:flex;gap:6px;margin-top:12px}
.plan-step{padding:4px 12px;border-radius:12px;font-size:12px;font-weight:500;border:1px solid var(--border);color:var(--dim)}
.plan-step.active{border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.1)}
.plan-step.done{border-color:var(--green);color:var(--green);background:rgba(34,197,94,0.1)}
.post-preview{background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px;margin:8px 0;white-space:pre-wrap;font-size:14px;line-height:1.6;max-height:300px;overflow-y:auto}
.fb-btn{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border:1px solid var(--border);background:rgba(99,102,241,0.06);color:var(--accent2);cursor:pointer;border-radius:5px;font-size:11px;font-weight:500;vertical-align:middle;margin-left:6px;transition:all .15s}
.fb-btn:hover{border-color:var(--accent);color:#fff;background:var(--accent)}
.fb-popover{position:absolute;z-index:100;background:var(--card);border:1px solid var(--accent);border-radius:8px;padding:12px;width:320px;box-shadow:0 8px 24px rgba(0,0,0,0.4)}
.fb-popover textarea{width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px;resize:vertical;min-height:60px}
.fb-actions{display:flex;gap:6px;margin-top:8px;justify-content:flex-end}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase}
.tag-draft{background:#2d2000;color:var(--yellow)}
.tag-approved{background:#052e16;color:var(--green)}
.tag-rejected{background:#2d0000;color:var(--red)}
.packages-list{display:flex;flex-direction:column;gap:16px}
.pkg-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px}
.pkg-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.pkg-meta{display:flex;gap:16px;font-size:12px;color:var(--dim);margin-bottom:12px}
.tabs{display:flex;gap:4px;margin-bottom:8px}
.tabs button{padding:4px 10px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;border-radius:4px;font-size:12px}
.tabs button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.qa-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-top:12px}
.qa-item{background:#111318;padding:8px;border-radius:6px;font-size:12px}
.qa-item .label{color:var(--dim)}
.qa-item .score{font-size:16px;font-weight:700;margin-top:2px}
.upload-zone{border:2px dashed var(--border);border-radius:10px;padding:40px;text-align:center;cursor:pointer;transition:border-color .15s}
.upload-zone:hover{border-color:var(--accent)}
.upload-zone p{color:var(--dim);margin-top:8px}
.docs-list{display:flex;flex-direction:column;gap:8px}
.doc-row{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--card);border:1px solid var(--border);border-radius:8px}
.doc-info{display:flex;flex-direction:column;gap:2px}
.doc-name{font-weight:500;font-size:14px}
.doc-meta{font-size:12px;color:var(--dim)}
.log{background:#111318;border:1px solid var(--border);border-radius:8px;padding:12px;font-family:monospace;font-size:12px;max-height:200px;overflow-y:auto;line-height:1.5;color:var(--dim)}
.empty{text-align:center;padding:40px;color:var(--dim)}
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:500;z-index:999;animation:slideIn .3s ease}
.toast-ok{background:var(--green);color:#000}
.toast-err{background:var(--red);color:#fff}
@keyframes slideIn{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}
.voice-profile{background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px;margin:8px 0}
.voice-profile h4{color:var(--accent2);margin-bottom:8px;font-size:14px}
.voice-tags{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
.voice-tag{background:var(--border);padding:2px 8px;border-radius:4px;font-size:11px}
.tone-bar{display:flex;align-items:center;gap:8px;margin:2px 0;font-size:12px}
.tone-bar .bar{height:6px;border-radius:3px;background:var(--accent)}
.tone-bar .name{width:90px;color:var(--dim)}
.week-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:16px 0}
.day-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;min-height:180px;display:flex;flex-direction:column}
.day-card.today{border-color:var(--accent);box-shadow:0 0 12px rgba(99,102,241,.2)}
.day-card .day-header{font-size:13px;color:var(--dim);margin-bottom:4px}
.day-card .day-date{font-size:18px;font-weight:700;margin-bottom:8px}
.day-card .day-angle{font-size:12px;color:var(--accent2);background:#1e1b4b;padding:3px 8px;border-radius:4px;display:inline-block;margin-bottom:8px;position:relative}
.tip-icon{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:var(--accent2);color:#1e1b4b;font-size:9px;font-weight:700;font-style:italic;margin-left:4px;cursor:help;vertical-align:middle}
.tip-icon:hover::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);width:260px;padding:10px 12px;background:#1e1b4b;border:1px solid var(--accent);color:var(--text);font-size:12px;font-style:normal;font-weight:400;border-radius:8px;z-index:99;line-height:1.5;white-space:normal;box-shadow:0 4px 16px rgba(0,0,0,.5)}
.day-card .day-topic{font-size:13px;color:var(--text);margin-bottom:8px;flex:1}
.day-card .day-status{font-size:11px;font-weight:600;text-transform:uppercase;padding:2px 6px;border-radius:3px;display:inline-block}
.day-status-planned{background:#1e3a5f;color:#93c5fd}
.day-status-generating{background:#1e3a5f;color:#93c5fd}
.day-status-ready{background:#052e16;color:#bbf7d0}
.day-status-approved{background:#052e16;color:#22c55e}
.day-status-published{background:#1e1b4b;color:#c7d2fe}
.day-status-skipped{background:#2d2000;color:#fbbf24}
.day-status-failed{background:#7f1d1d;color:#fecaca}
.guide-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-top:16px}
.guide-card h3{color:var(--accent2);font-size:16px;margin-bottom:8px}
.guide-meta{display:flex;gap:16px;font-size:12px;color:var(--dim);margin:8px 0}
.guide-stats{display:flex;gap:24px;margin:12px 0}
.guide-stat{text-align:center}
.guide-stat .val{font-size:22px;font-weight:700;color:var(--accent)}
.guide-stat .lbl{font-size:11px;color:var(--dim)}
@media(max-width:900px){.week-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.week-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
  <h1>Team Content Engine</h1>
  <div class="status"><div class="dot" id="health-dot"></div><span id="health-text">Checking...</span></div>
</div>
<div class="nav" id="nav">
  <button class="active" data-tab="week">Week Planner</button>
  <button data-tab="generate">Generate</button>
  <button data-tab="packages">Packages</button>
  <button data-tab="corpus">Corpus</button>
  <button data-tab="voice">Voice Profile</button>
  <button data-tab="creators">Creators</button>
  <button data-tab="agents">Agents</button>
  <button data-tab="costs">Costs</button>
  <button data-tab="analytics">Analytics</button>
</div>
<div class="main" id="app"></div>
<script>
const API = '/api/v1';
let currentTab = 'week';
let activePipelineRun = localStorage.getItem('tce_active_run') || null;
let pollInterval = null;
let verboseMode = localStorage.getItem('tce_verbose') === 'true';
let showArchived = false;
let genAllState = null; // {running, current, total, startTime, results: [{day, status, stepStatus, startTime}]}
const AGENT_LABELS = {
  trend_scout: 'Scanning Trends', story_strategist: 'Building Story Brief',
  research_agent: 'Verifying Research', facebook_writer: 'Writing Facebook Post',
  linkedin_writer: 'Writing LinkedIn Post', cta_agent: 'Crafting CTA & DM Flow',
  creative_director: 'Creating Image Prompts', qa_agent: 'Quality Check',
  corpus_analyst: 'Analyzing Corpus', engagement_scorer: 'Scoring Engagement',
  pattern_miner: 'Mining Patterns', docx_guide_builder: 'Building Guide',
  weekly_planner: 'Planning Week', learning_agent: 'Learning from Feedback',
};

// Nav
document.getElementById('nav').addEventListener('click', e => {
  if (e.target.tagName !== 'BUTTON') return;
  currentTab = e.target.dataset.tab;
  document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === currentTab));
  render();
});

// Health check
async function checkHealth() {
  try {
    const r = await fetch(API + '/health');
    const d = await r.json();
    const dot = document.getElementById('health-dot');
    const text = document.getElementById('health-text');
    if (d.status === 'ok') {
      dot.className = 'dot';
      text.textContent = 'System healthy';
      text.title = 'DB: ' + (d.database || 'ok') + ', Version: ' + (d.version || '?');
    } else {
      dot.className = 'dot off';
      text.textContent = 'System error';
    }
  } catch {
    document.getElementById('health-dot').className = 'dot off';
    document.getElementById('health-text').textContent = 'Offline - check VPS';
  }
}
checkHealth(); setInterval(checkHealth, 30000);

// Toast
function toast(msg, ok = true) {
  const t = document.createElement('div');
  t.className = 'toast ' + (ok ? 'toast-ok' : 'toast-err');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// API helpers
async function api(path, opts = {}) {
  const r = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) {
    const err = await r.text();
    throw new Error('API error ' + r.status + ': ' + err.slice(0, 200));
  }
  return r.json();
}

// WEEK PLANNER TAB
const ANGLE_LABELS = {
  big_shift_explainer: 'Big Shift Explainer',
  tactical_workflow_guide: 'Tactical Workflow',
  contrarian_diagnosis: 'Contrarian Diagnosis',
  case_study_build_story: 'Case Study Build',
  second_order_implication: 'Second Order',
  hidden_feature_shortcut: 'Hidden Feature',
  teardown_myth_busting: 'Teardown / Myth Bust',
  weekly_roundup: 'Weekly Roundup',
  founder_reflection: 'Founder Reflection',
  comment_keyword_cta_guide: 'CTA Guide',
};
const ANGLE_TIPS = {
  big_shift_explainer: 'News hook with paradox or famous name. 2-4 proof blocks showing why a fast-moving AI development matters to the reader. Best for Mondays.',
  tactical_workflow_guide: 'State the outcome first, then 3-5 numbered steps (what + why + mistake to avoid). Immediate utility the reader can use today. Best for Tuesdays.',
  contrarian_diagnosis: 'Challenge a lazy assumption. State conventional wisdom, acknowledge why it feels right, then dismantle it with 2-3 evidence blocks. Best for Wednesdays.',
  case_study_build_story: 'Lead with the result, then 3-4 build blocks showing the real workflow (tool + result). Proof through action, not theory. Best for Thursdays.',
  second_order_implication: 'Start with widely-reported news, then reveal what nobody is talking about. 2-3 second-order analysis blocks. Best for Fridays.',
  hidden_feature_shortcut: 'One specific AI tool trick, explored deep not broad. Vivid metaphor hook, bullet-based feature list. Tuesday alternative.',
  teardown_myth_busting: 'Direct attack on conventional wisdom backed by personal failure as credibility. Problem, evidence, reframe, proof. Wednesday alternative.',
  weekly_roundup: '3-5 curated AI stories with 1-2 sentence take on each. Strong guide CTA at the end. Friday alternative.',
  founder_reflection: 'Personal moment leads to professional realization. Narrative arc: struggle, insight, lesson, actionable takeaway.',
  comment_keyword_cta_guide: 'Optimized for comment-to-DM conversion. Tease value, build desire, then keyword CTA. Facebook-focused.',
};
const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

function getMonday(d) {
  d = new Date(d);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff));
}

function fmtDate(d) {
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}

let weekOffset = 0;

async function renderWeek() {
  const app = document.getElementById('app');
  const now = new Date();
  const monday = getMonday(now);
  monday.setDate(monday.getDate() + weekOffset * 7);
  const friday = new Date(monday); friday.setDate(friday.getDate() + 4);
  const todayStr = fmtDate(new Date());

  app.innerHTML = `
    <div class="section">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:16px">
        <h2>Week of ${monday.toLocaleDateString('en-US',{month:'short',day:'numeric'})} - ${friday.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}</h2>
        <div style="display:flex;align-items:center;gap:12px">
          <span id="week-cost" style="font-size:13px;color:var(--accent2);font-weight:600"></span>
          <div class="btn-group">
            <button class="btn btn-dim" onclick="weekOffset--;renderWeek()">Prev Week</button>
            <button class="btn btn-dim" onclick="weekOffset=0;renderWeek()">This Week</button>
            <button class="btn btn-dim" onclick="weekOffset++;renderWeek()">Next Week</button>
          </div>
        </div>
      </div>
      <div style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:16px">
        <div>
          <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Weekly Theme (optional hint for the planner)</label>
          <input id="week-theme" type="text" placeholder="e.g. Agency scaling without burnout" style="width:320px">
        </div>
        <div style="display:flex;flex-direction:column;gap:4px">
          <button class="btn btn-primary" id="plan-week-btn" onclick="planWeekDeep('${fmtDate(monday)}')">Plan This Week</button>
          <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--dim);cursor:pointer" title="When active, the planner avoids topics that could trivialize human suffering, war metaphors, and fear-based hooks">
            <input type="checkbox" id="sensitive-period-toggle" style="accent-color:var(--accent)">
            Sensitive Period
          </label>
        </div>
        <span id="plan-cost-hint" style="font-size:11px;color:var(--dim);margin-left:6px" title="Trend scout (Sonnet) + Weekly planner (Opus)">~$0.25 per plan</span>
        <button class="btn btn-green" id="gen-all-btn" onclick="generateFromPlan()" ${genAllState?.running ? 'disabled' : ''}>${genAllState?.running ? (genAllState.unified ? 'Running...' : 'Generating...') : 'Generate from Plan'}</button>
      </div>
      <div id="plan-review-panel"></div>
      <div id="gen-all-progress"></div>
      <div class="week-grid" id="week-grid"><div class="empty" style="grid-column:1/-1">Loading calendar...</div></div>
      <div id="guide-section"></div>
    </div>`;

  // Load calendar entries for this week
  try {
    const entries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(friday));
    const byDate = {};
    entries.forEach(e => byDate[e.date] = e);

    // Show persistent weekly plan summary if any entry has _weekly metadata
    const weeklyMeta = entries.find(e => e.plan_context?._weekly)?.plan_context?._weekly;
    if (weeklyMeta && weeklyMeta.weekly_theme) {
      const gift = weeklyMeta.gift_theme || {};
      const giftTitle = typeof gift === 'string' ? gift : (gift.title || '');
      const giftSubtitle = typeof gift === 'string' ? '' : (gift.subtitle || '');
      const sections = weeklyMeta.gift_sections || [];
      const cta = weeklyMeta.cta_keyword || '';
      let summaryHtml = '<div style="background:linear-gradient(135deg,#1a1d27,#1e2235);border:1px solid var(--accent);border-radius:10px;padding:16px 20px;margin-bottom:16px;display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start">';
      summaryHtml += '<div style="flex:1;min-width:200px">';
      summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--accent2);margin-bottom:4px">Weekly Direction</div>';
      summaryHtml += '<div style="font-size:15px;font-weight:600;line-height:1.4">' + escHtml(weeklyMeta.weekly_theme) + '</div>';
      summaryHtml += '</div>';
      if (giftTitle) {
        summaryHtml += '<div style="flex:0 0 auto;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:10px 14px;min-width:180px">';
        summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--green);margin-bottom:4px">Gift of the Week</div>';
        summaryHtml += '<div style="font-size:14px;font-weight:600">' + escHtml(giftTitle) + '</div>';
        if (giftSubtitle) summaryHtml += '<div style="font-size:12px;color:var(--dim);margin-top:2px">' + escHtml(giftSubtitle) + '</div>';
        if (sections.length) summaryHtml += '<div style="font-size:11px;color:var(--dim);margin-top:6px">' + sections.length + ' sections planned</div>';
        summaryHtml += '</div>';
      }
      if (cta) {
        summaryHtml += '<div style="flex:0 0 auto;text-align:center;padding:10px 14px">';
        summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--yellow);margin-bottom:4px">CTA Keyword</div>';
        summaryHtml += '<div style="font-size:20px;font-weight:800;color:var(--yellow)">' + escHtml(cta) + '</div>';
        summaryHtml += '</div>';
      }
      summaryHtml += '<div style="flex:0 0 auto;display:flex;align-items:center"><button class="btn btn-dim" style="padding:8px 14px;font-size:12px;white-space:nowrap" onclick="editWeekPlan()">Edit Plan</button></div>';
      summaryHtml += '</div>';
      document.getElementById('week-grid').insertAdjacentHTML('beforebegin', summaryHtml);
      // Store entries for edit
      window._weekEntries = entries;
      window._weekMondayStr = fmtDate(monday);
    }

    // Update Generate from Plan button based on package state
    const genAllBtn = document.getElementById('gen-all-btn');
    if (genAllBtn && !genAllState?.running) {
      const allHavePackages = entries.length >= 5 && entries.every(e => e.post_package_id);
      const someHavePackages = entries.some(e => e.post_package_id);
      if (allHavePackages) {
        genAllBtn.textContent = 'Regenerate All';
        genAllBtn.className = 'btn btn-dim';
      } else if (someHavePackages) {
        const remaining = entries.filter(e => !e.post_package_id).length;
        genAllBtn.textContent = 'Generate ' + remaining + ' Remaining';
      }
    }

    let html = '';
    for (let i = 0; i < 5; i++) {
      const d = new Date(monday); d.setDate(d.getDate() + i);
      const ds = fmtDate(d);
      const entry = byDate[ds];
      const isToday = ds === todayStr;
      const angle = entry ? entry.angle_type : ['big_shift_explainer','tactical_workflow_guide','contrarian_diagnosis','case_study_build_story','second_order_implication'][i];
      const status = entry ? entry.status : 'unplanned';

      html += '<div class="day-card' + (isToday ? ' today' : '') + '">';
      html += '<div class="day-header">' + DAY_NAMES[i] + (isToday ? ' (TODAY)' : '') + '</div>';
      html += '<div class="day-date">' + d.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + '</div>';
      const tip = ANGLE_TIPS[angle] || '';
      html += '<div class="day-angle" style="position:relative;cursor:help">' + (ANGLE_LABELS[angle] || angle.replace(/_/g,' '));
      if (tip) html += ' <span class="tip-icon" data-tip="' + esc(tip) + '">i</span>';
      html += '</div>';
      if (entry?.topic) html += '<div class="day-topic">' + esc(entry.topic) + '</div>';
      else html += '<div class="day-topic" style="color:var(--dim);font-style:italic">No topic set</div>';
      if (entry?.operator_notes) html += '<div style="font-size:11px;color:var(--dim);margin-bottom:6px">' + esc(entry.operator_notes) + '</div>';

      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;gap:4px;flex-wrap:wrap">';
      if (entry) {
        const hasPackage = !!entry.post_package_id;
        const stLabel = hasPackage && status === 'planned' ? 'READY' : status.toUpperCase();
        const stClass = hasPackage && status === 'planned' ? 'ready' : status;
        html += '<span class="day-status day-status-' + stClass + '">' + stLabel + '</span>';
        if (hasPackage) {
          html += '<button class="btn btn-green" style="padding:4px 10px;font-size:11px" onclick="viewPackage(\\'' + entry.post_package_id + '\\')">Package</button>';
          html += '<button class="btn btn-dim" style="padding:4px 10px;font-size:11px" onclick="runDayPipeline(' + i + ',\\'' + (entry?.id || '') + '\\')">Regenerate</button>';
        } else if (status === 'planned' || status === 'approved') {
          html += '<button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="runDayPipeline(' + i + ',\\'' + (entry?.id || '') + '\\')">Generate</button>';
        }
      } else {
        html += '<span class="day-status" style="background:var(--border);color:var(--dim)">UNPLANNED</span>';
      }
      html += '</div>';
      html += '</div>';
    }
    document.getElementById('week-grid').innerHTML = html;
  } catch (e) {
    document.getElementById('week-grid').innerHTML = '<div class="empty" style="grid-column:1/-1">Error loading calendar: ' + e.message + '</div>';
  }

  // Render generate-all progress bar if active
  renderGenAllProgress();

  // Load daily cost + planning cost
  try {
    const [dailyCost, planCost] = await Promise.all([api('/costs/daily'), api('/costs/planning')]);
    const costEl = document.getElementById('week-cost');
    if (costEl) {
      let parts = [];
      if (dailyCost.total_cost_usd > 0) parts.push('Today: $' + dailyCost.total_cost_usd.toFixed(2));
      if (planCost.last_cost > 0) parts.push('Last plan: $' + planCost.last_cost.toFixed(2));
      if (planCost.total_planning_cost > 0) parts.push('Total planning: $' + planCost.total_planning_cost.toFixed(2));
      costEl.textContent = parts.join(' | ');
    }
    const hint = document.getElementById('plan-cost-hint');
    if (hint && planCost.avg_cost > 0) hint.textContent = '~$' + planCost.avg_cost.toFixed(2) + ' per plan (avg of ' + planCost.plan_runs + ' runs)';
  } catch {}

  // Load weekly guides
  try {
    const showArchivedGuides = document.getElementById('show-archived-guides')?.checked || false;
    const guides = await api('/content/guides' + (showArchivedGuides ? '?include_archived=true' : ''));
    if (guides.length) {
      let html = '<h2 style="margin-top:24px;margin-bottom:12px;display:flex;align-items:center;gap:16px">Gift of the Week (Weekly Guides)';
      html += '<label style="font-size:12px;font-weight:400;color:var(--dim);display:flex;align-items:center;gap:6px;cursor:pointer"><input type="checkbox" id="show-archived-guides" onchange="renderWeek()" ' + (showArchivedGuides ? 'checked' : '') + '> Show Archived</label>';
      html += '</h2>';
      for (const g of guides) {
        const archived = g.is_archived;
        html += '<div class="guide-card" style="' + (archived ? 'opacity:0.5;border-color:var(--dim)' : '') + '">';
        if (archived) html += '<div style="display:inline-block;background:var(--dim);color:#000;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:8px">ARCHIVED</div>';
        html += '<h3>' + esc(g.guide_title) + '</h3>';
        html += '<div class="guide-meta">';
        html += '<span>Week of ' + g.week_start_date + '</span>';
        html += '<span>Theme: ' + esc(g.weekly_theme) + '</span>';
        if (g.cta_keyword) html += '<span>CTA: <strong>' + esc(g.cta_keyword) + '</strong></span>';
        html += '</div>';
        html += '<div class="btn-group" style="margin:12px 0">';
        if (g.docx_path) html += '<a class="btn btn-green" href="' + API + '/content/guides/' + g.id + '/download" target="_blank">Download DOCX</a>';
        if (g.fulfillment_link) html += '<a class="btn btn-blue" href="' + esc(g.fulfillment_link) + '" target="_blank">Fulfillment Link</a>';
        if (archived) {
          html += '<button class="btn btn-dim" onclick="unarchiveGuide(\\'' + g.id + '\\')">Unarchive</button>';
        } else {
          html += '<button class="btn btn-dim" onclick="archiveGuide(\\'' + g.id + '\\')">Archive</button>';
        }
        html += '</div>';
        if (g.markdown_content) {
          html += '<details style="margin-top:8px"><summary style="cursor:pointer;color:var(--accent2);font-size:13px">View Guide Content</summary>';
          html += '<div class="post-preview" style="margin-top:8px;max-height:400px;overflow-y:auto;white-space:pre-wrap">' + esc(g.markdown_content) + '</div>';
          html += '</details>';
        }
        html += '<div class="guide-stats">';
        html += '<div class="guide-stat"><div class="val">' + (g.downloads_count || 0) + '</div><div class="lbl">Downloads</div></div>';
        html += '<div class="guide-stat"><div class="val">' + (g.conversion_rate != null ? (g.conversion_rate * 100).toFixed(1) + '%' : 'N/A') + '</div><div class="lbl">Conversion</div></div>';
        html += '</div>';
        html += '<div style="font-size:11px;color:var(--dim);margin-top:8px">Created: ' + new Date(g.created_at).toLocaleString() + '</div>';
        html += '</div>';
      }
      document.getElementById('guide-section').innerHTML = html;
    } else {
      document.getElementById('guide-section').innerHTML = '<div class="card" style="margin-top:16px;text-align:center;padding:24px"><div style="font-size:14px;color:var(--dim)">No weekly guides yet. Click "Generate Weekly Guide" to create your first gift of the week.</div></div>';
    }
  } catch {}
}

let deepPlanId = null;
let approvedPlan = null;

let planElapsedTimer = null;

async function planWeekDeep(mondayStr) {
  const theme = document.getElementById('week-theme')?.value || null;
  const sensitivePeriod = document.getElementById('sensitive-period-toggle')?.checked || false;
  const btn = document.getElementById('plan-week-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Planning...'; }
  const panel = document.getElementById('plan-review-panel');
  const planStartTime = Date.now();

  // Build progress card with spinner, elapsed timer, and step indicators
  if (panel) panel.innerHTML = '<div class="card" style="padding:20px;margin-bottom:16px;border-left:4px solid var(--accent)">' +
    '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">' +
    '<div class="spinner"></div>' +
    '<div style="flex:1"><div id="plan-progress-text" style="font-weight:600">Starting weekly planning...</div>' +
    '<div style="font-size:12px;color:var(--dim);margin-top:4px">This takes about 60-90 seconds</div></div>' +
    '<div id="plan-elapsed" style="font-size:24px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums">0s</div>' +
    '</div>' +
    '<div class="plan-steps" id="plan-steps">' +
    '<span class="plan-step active" id="ps-trend">Trend Research</span>' +
    '<span class="plan-step" id="ps-strategy">Strategy</span>' +
    '<span class="plan-step" id="ps-saving">Saving Plan</span>' +
    '</div></div>';

  // Start elapsed timer
  if (planElapsedTimer) clearInterval(planElapsedTimer);
  planElapsedTimer = setInterval(() => {
    const el = document.getElementById('plan-elapsed');
    if (el) {
      const secs = Math.floor((Date.now() - planStartTime) / 1000);
      el.textContent = secs < 60 ? secs + 's' : Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
    }
  }, 1000);

  try {
    const r = await api('/calendar/plan-week-deep', {
      method: 'POST',
      body: JSON.stringify({ week_start: mondayStr, weekly_theme: theme || null, sensitive_period: sensitivePeriod }),
    });
    deepPlanId = r.plan_id;

    // Poll for completion
    let done = false;
    let failCount = 0;
    while (!done) {
      await new Promise(ok => setTimeout(ok, 3000));
      try {
        const st = await api('/calendar/plan-week-deep/' + deepPlanId + '/status');
        failCount = 0;
        const progEl = document.getElementById('plan-progress-text');
        if (progEl) {
          const phases = {
            starting: 'Initializing planning engine...',
            trend_research: 'Searching the web for current AI, tech, and business trends...',
            strategist: 'Opus strategist choosing 5 topics, gift theme, and CTA keyword...',
            completed: 'Plan ready for review!',
            failed: 'Planning failed'
          };
          progEl.textContent = phases[st.phase] || st.phase_detail || st.phase;
        }
        // Update step indicators
        const stepMap = { starting: 0, trend_research: 0, strategist: 1, completed: 3, failed: -1 };
        const stepIdx = stepMap[st.phase] !== undefined ? stepMap[st.phase] : 0;
        ['ps-trend', 'ps-strategy', 'ps-saving'].forEach((id, i) => {
          const el = document.getElementById(id);
          if (el) {
            el.className = 'plan-step' + (i < stepIdx ? ' done' : i === stepIdx ? ' active' : '');
          }
        });
        if (st.status === 'completed') {
          done = true;
          showPlanReview(st, mondayStr);
        } else if (st.status === 'failed') {
          done = true;
          if (panel) panel.innerHTML = '<div class="card" style="padding:20px;margin-bottom:16px;border-left:4px solid var(--red)"><b>Planning failed:</b> ' + (st.error || 'Unknown error') + '</div>';
          toast('Planning failed: ' + (st.error || 'Unknown error'), false);
        }
      } catch (e) {
        failCount++;
        if (failCount >= 3) { done = true; if (panel) panel.innerHTML = ''; toast('Lost connection to planner', false); }
      }
    }
  } catch (e) {
    toast('Failed to start planning: ' + e.message, false);
    if (panel) panel.innerHTML = '';
  }
  if (planElapsedTimer) { clearInterval(planElapsedTimer); planElapsedTimer = null; }
  if (btn) { btn.disabled = false; btn.textContent = 'Plan This Week'; }
  // DON'T call renderWeek() here - it would wipe the plan review panel
}

// === AI FEEDBACK BUTTONS ===
function makeFbBtn(fieldId, label) {
  return ' <button class="fb-btn" onclick="openFeedbackPopover(this,\\'' + fieldId + '\\',\\'' + label + '\\')" title="AI feedback on this field">Feedback</button>';
}
function openFeedbackPopover(btn, fieldId, label) {
  // Close any existing popover
  document.querySelectorAll('.fb-popover').forEach(p => p.remove());
  const rect = btn.getBoundingClientRect();
  const pop = document.createElement('div');
  pop.className = 'fb-popover';
  pop.style.top = (rect.bottom + window.scrollY + 4) + 'px';
  pop.style.left = Math.min(rect.left, window.innerWidth - 340) + 'px';
  pop.innerHTML = '<div style="font-size:12px;color:var(--dim);margin-bottom:6px">Tell the AI what to change about <b>' + label + '</b></div>'
    + '<textarea id="fb-input-' + fieldId + '" placeholder="e.g. make it shorter, more provocative, target younger audience..." rows="3"></textarea>'
    + '<div class="fb-actions">'
    + '<button class="btn btn-dim" style="padding:4px 10px;font-size:12px" onclick="this.closest(\\'.fb-popover\\').remove()">Cancel</button>'
    + '<button class="btn btn-primary" style="padding:4px 10px;font-size:12px" onclick="submitFieldFeedback(\\'' + fieldId + '\\',this)">Revise with AI</button>'
    + '</div>';
  document.body.appendChild(pop);
  pop.querySelector('textarea').focus();
}
async function submitFieldFeedback(fieldId, btn) {
  const textarea = document.getElementById('fb-input-' + fieldId);
  if (!textarea) return;
  const feedback = textarea.value.trim();
  if (!feedback) { toast('Please type your feedback', false); return; }
  const field = document.getElementById(fieldId);
  if (!field) return;
  const currentValue = field.value || field.textContent || '';
  btn.disabled = true; btn.textContent = 'Revising...';
  // Gather context
  const ctx = {};
  const themeEl = document.getElementById('pr-weekly-theme');
  if (themeEl) ctx.weekly_theme = themeEl.value;
  // For day fields, grab the topic for context
  const dayMatch = fieldId.match(/pr-day-(\\d+)/);
  if (dayMatch) {
    const topicEl = document.getElementById('pr-day-' + dayMatch[1] + '-topic');
    if (topicEl) ctx.day_topic = topicEl.value;
  }
  try {
    const result = await api('/calendar/ai-revise-field', {
      method: 'POST',
      body: JSON.stringify({ field_name: fieldId, current_value: currentValue, feedback: feedback, context: ctx })
    });
    if (field.tagName === 'TEXTAREA' || field.tagName === 'INPUT') {
      field.value = result.revised;
    } else {
      field.textContent = result.revised;
    }
    field.style.borderColor = 'var(--green)';
    setTimeout(() => { field.style.borderColor = ''; }, 2000);
    toast('Field revised by AI');
    btn.closest('.fb-popover')?.remove();
  } catch (e) {
    toast('AI revision failed: ' + e.message, false);
    btn.disabled = false; btn.textContent = 'Revise with AI';
  }
}
// Also for packages - revise post content with AI
async function aiRevisePost(packageId, platform) {
  const pid = packageId.replace(/-/g, '');
  const previewEl = document.getElementById(platform + '-' + pid);
  if (!previewEl) { toast('Could not find ' + platform.toUpperCase() + ' post element', false); return; }
  const postDiv = previewEl.querySelector('.post-preview');
  if (!postDiv) { toast('No post content found', false); return; }
  const feedback = prompt('What should the AI change about this ' + platform.toUpperCase() + ' post?');
  if (!feedback || !feedback.trim()) return;
  const currentText = postDiv.textContent;
  postDiv.style.opacity = '0.5';
  postDiv.insertAdjacentHTML('afterbegin', '<div class="spinner" style="margin:0 auto 8px"></div>');
  try {
    const result = await api('/calendar/ai-revise-field', {
      method: 'POST',
      body: JSON.stringify({ field_name: platform + '_post', current_value: currentText, feedback: feedback.trim(), context: {} })
    });
    postDiv.textContent = result.revised;
    postDiv.style.opacity = '1';
    toast(platform.toUpperCase() + ' post revised by AI');
  } catch (e) {
    postDiv.style.opacity = '1';
    postDiv.querySelector('.spinner')?.remove();
    toast('AI revision failed: ' + e.message, false);
  }
}

function showPlanReview(planData, mondayStr) {
  const wp = planData.weekly_plan || {};
  const days = wp.days || [];
  const trends = planData.trend_summary || [];
  const giftTheme = wp.gift_theme || {};
  const giftTitle = typeof giftTheme === 'string' ? giftTheme : (giftTheme.title || '');
  const giftSubtitle = typeof giftTheme === 'string' ? '' : (giftTheme.subtitle || '');
  const giftSections = wp.gift_sections || [];
  approvedPlan = { weekly_theme: wp.weekly_theme || '', gift_theme: giftTheme, cta_keyword: wp.cta_keyword || '', days: days };

  let html = '<div style="margin-bottom:24px">';

  // === BIG HEADER: Weekly Direction ===
  html += '<div class="card" style="padding:24px;margin-bottom:16px;border:2px solid var(--accent);border-radius:12px">';
  html += '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:20px">';
  html += '<div><h2 style="margin:0 0 4px 0;color:var(--accent);font-size:20px">Weekly Plan Review</h2>';
  html += '<p style="margin:0;color:var(--dim);font-size:13px">Edit anything below, then approve to start content generation.</p></div>';
  html += '<div style="text-align:right;font-size:12px;color:var(--dim)">Plan ID: ' + (deepPlanId || '').substring(0, 8) + '</div>';
  html += '</div>';

  // Weekly Theme - big and prominent
  html += '<div style="margin-bottom:16px">';
  html += '<label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px;font-weight:600">OVERARCHING DIRECTION - What ties the whole week together?' + makeFbBtn('pr-weekly-theme', 'Weekly Theme') + '</label>';
  html += '<textarea id="pr-weekly-theme" rows="2" style="width:100%;padding:10px;border:1px solid var(--accent);border-radius:6px;background:var(--bg);color:var(--text);font-size:15px;resize:vertical">' + escHtml(wp.weekly_theme || '') + '</textarea>';
  html += '</div>';

  // Gift Theme - prominent box
  html += '<div style="background:rgba(34,197,94,0.08);border:1px solid var(--green);border-radius:8px;padding:16px;margin-bottom:16px">';
  html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="font-size:18px">&#127873;</span><label style="font-size:12px;color:var(--green);font-weight:700;text-transform:uppercase">Weekly Gift / Lead Magnet' + makeFbBtn('pr-gift-theme', 'Gift Theme') + '</label></div>';
  html += '<textarea id="pr-gift-theme" rows="2" style="width:100%;padding:10px;border:1px solid var(--green);border-radius:6px;background:var(--bg);color:var(--text);font-size:14px;resize:vertical">' + escHtml(giftTitle + (giftSubtitle ? ' - ' + giftSubtitle : '')) + '</textarea>';
  if (giftSections.length > 0) {
    html += '<div style="margin-top:8px;font-size:12px;color:var(--dim)"><b>Guide sections:</b> ' + giftSections.map(s => escHtml(s)).join(' / ') + '</div>';
  }
  html += '<div style="display:flex;gap:16px;margin-top:12px">';
  html += '<div style="flex:1"><label style="font-size:11px;color:var(--dim);display:block;margin-bottom:4px">CTA Keyword (what readers comment to get the gift)</label>';
  html += '<input id="pr-cta-keyword" type="text" value="' + escHtml(wp.cta_keyword || '') + '" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);text-transform:uppercase;font-weight:700;font-size:16px;letter-spacing:2px"></div>';
  html += '</div>';
  html += '</div>';
  html += '</div>';

  // === DAY CARDS ===
  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  const angleLabels = { big_shift_explainer: 'Big Shift', tactical_workflow_guide: 'Tactical How-To', contrarian_diagnosis: 'Contrarian Take', case_study_build_story: 'Case Study', second_order_implication: 'Big Picture' };
  const angleColors = { big_shift_explainer: '#6366f1', tactical_workflow_guide: '#22c55e', contrarian_diagnosis: '#ef4444', case_study_build_story: '#eab308', second_order_implication: '#3b82f6' };

  html += '<div style="display:flex;flex-direction:column;gap:12px;margin-bottom:16px">';
  for (let i = 0; i < days.length; i++) {
    const d = days[i].story_brief || days[i];
    const dayNum = days[i].day_of_week !== undefined ? days[i].day_of_week : i;
    const angle = d.angle_type || '';
    const angleLabel = angleLabels[angle] || angle;
    const angleColor = angleColors[angle] || 'var(--accent)';
    html += '<div class="card" style="padding:16px 20px;border-left:4px solid ' + angleColor + '">';
    html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">';
    html += '<span style="font-size:16px;font-weight:700">' + dayNames[dayNum] + '</span>';
    html += '<span style="font-size:12px;padding:3px 10px;border-radius:8px;background:' + angleColor + '22;color:' + angleColor + ';font-weight:600">' + escHtml(angleLabel) + '</span>';
    html += '</div>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">';
    html += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Topic' + makeFbBtn('pr-day-' + i + '-topic', 'Topic') + '</label>';
    html += '<textarea id="pr-day-' + i + '-topic" rows="2" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:14px;resize:vertical;line-height:1.4" placeholder="Write like you would describe it to a friend...">' + escHtml(d.topic || '') + '</textarea></div>';
    html += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Core Argument' + makeFbBtn('pr-day-' + i + '-thesis', 'Thesis') + '</label>';
    html += '<textarea id="pr-day-' + i + '-thesis" rows="2" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px;resize:vertical;line-height:1.4" placeholder="The main takeaway...">' + escHtml(d.thesis || '') + '</textarea></div>';
    html += '</div>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px">';
    html += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Audience' + makeFbBtn('pr-day-' + i + '-audience', 'Audience') + '</label>';
    html += '<input id="pr-day-' + i + '-audience" type="text" value="' + escHtml(d.audience || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px" placeholder="Who is this for?"></div>';
    html += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Belief Shift' + makeFbBtn('pr-day-' + i + '-belief', 'Belief Shift') + '</label>';
    html += '<input id="pr-day-' + i + '-belief" type="text" value="' + escHtml(d.desired_belief_shift || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px" placeholder="FROM x TO y"></div>';
    html += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Gift Connection' + makeFbBtn('pr-day-' + i + '-gift', 'Gift Connection') + '</label>';
    html += '<input id="pr-day-' + i + '-gift" type="text" value="' + escHtml(days[i].connection_to_gift || d.connection_to_gift || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px" placeholder="How does this tie to the gift?"></div>';
    html += '</div>';
    html += '<input id="pr-day-' + i + '-visual" type="hidden" value="' + escHtml(d.visual_job || 'cinematic_symbolic') + '">';
    html += '</div>';
  }
  html += '</div>';

  // Trend brief (collapsible)
  if (trends.length > 0) {
    html += '<details style="margin-bottom:16px"><summary style="cursor:pointer;color:var(--dim);font-size:13px;padding:8px 0">Trend Brief - ' + trends.length + ' trends found (click to expand)</summary>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">';
    trends.forEach(t => {
      html += '<div style="padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:12px">';
      html += '<div style="color:var(--text);margin-bottom:2px">' + escHtml(t.headline) + '</div>';
      html += '<div style="color:var(--dim);font-size:11px">Relevance: ' + t.relevance_score + '/10';
      if (t.source_url) html += ' - <a href="' + escHtml(t.source_url) + '" target="_blank" style="color:var(--accent)">source</a>';
      html += '</div></div>';
    });
    html += '</div></details>';
  }

  // Action buttons - big and clear
  html += '<div style="display:flex;gap:12px;padding:16px 0;border-top:1px solid var(--border)">';
  html += '<button class="btn btn-green" style="padding:12px 24px;font-size:15px;font-weight:600" onclick="approveAndGenerate(\\'' + mondayStr + '\\')">Approve & Generate All 5 Days</button>';
  html += '<button class="btn btn-primary" style="padding:12px 24px" onclick="savePlanOnly(\\'' + mondayStr + '\\')">Save Plan Only</button>';
  html += '<button class="btn btn-dim" style="padding:12px 24px" onclick="dismissPlanReview()">Dismiss</button>';
  html += '</div>';

  html += '</div>';

  const panel = document.getElementById('plan-review-panel');
  if (panel) panel.innerHTML = html;
  // Scroll to the plan review
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function collectEditedPlan() {
  const days = approvedPlan?.days || [];
  const edited = {
    weekly_theme: document.getElementById('pr-weekly-theme')?.value || '',
    gift_theme: document.getElementById('pr-gift-theme')?.value || '',
    cta_keyword: document.getElementById('pr-cta-keyword')?.value || '',
    days: [],
  };
  for (let i = 0; i < days.length; i++) {
    const orig = days[i].story_brief || days[i];
    edited.days.push({
      day_of_week: days[i].day_of_week !== undefined ? days[i].day_of_week : i,
      angle_type: orig.angle_type || '',
      topic: document.getElementById('pr-day-' + i + '-topic')?.value || '',
      thesis: document.getElementById('pr-day-' + i + '-thesis')?.value || '',
      audience: document.getElementById('pr-day-' + i + '-audience')?.value || '',
      desired_belief_shift: document.getElementById('pr-day-' + i + '-belief')?.value || '',
      visual_job: document.getElementById('pr-day-' + i + '-visual')?.value || 'cinematic_symbolic',
      connection_to_gift: document.getElementById('pr-day-' + i + '-gift')?.value || '',
      evidence_requirements: orig.evidence_requirements || [],
      template_id: orig.template_id || '',
      platform_notes: orig.platform_notes || '',
    });
  }
  return edited;
}

async function approveAndGenerate(mondayStr) {
  if (!deepPlanId) { toast('No plan to approve', false); return; }
  const edited = collectEditedPlan();
  try {
    // Approve the plan
    await api('/calendar/plan-week-deep/' + deepPlanId + '/approve', {
      method: 'POST',
      body: JSON.stringify(edited),
    });
    toast('Plan approved! Starting generation...');
    document.getElementById('plan-review-panel').innerHTML = '';
    // Start generation with the approved plan (skip planning phase)
    generateFromApprovedPlan(edited);
  } catch (e) { toast('Approval failed: ' + e.message, false); }
}

async function savePlanOnly(mondayStr) {
  if (!deepPlanId) { toast('No plan to save', false); return; }
  const edited = collectEditedPlan();
  try {
    await api('/calendar/plan-week-deep/' + deepPlanId + '/approve', {
      method: 'POST',
      body: JSON.stringify(edited),
    });
    toast('Plan saved! You can generate later.');
    document.getElementById('plan-review-panel').innerHTML = '';
    await renderWeek();
  } catch (e) { toast('Save failed: ' + e.message, false); }
}

async function generateFromApprovedPlan(plan) {
  genAllState = { running: true, current: -1, total: 5, startTime: Date.now(), results: [], totalCost: 0, unified: true, weekId: null, phase: 'starting', phaseDetail: 'Starting generation from approved plan...', weeklyTheme: plan.weekly_theme, giftTheme: plan.gift_theme, weeklyKeyword: plan.cta_keyword };
  saveGenAllState();
  renderGenAllProgress();
  try {
    const r = await api('/pipeline/generate-week', {
      method: 'POST',
      body: JSON.stringify({ context: {}, skip_planning: true, approved_plan: plan }),
    });
    genAllState.weekId = r.week_id;
    saveGenAllState();
    // Same polling loop as generateAllDays
    let done = false;
    let pollFailCount = 0;
    while (!done) {
      await new Promise(ok => setTimeout(ok, 2500));
      try {
        const st = await api('/pipeline/generate-week/' + r.week_id + '/status');
        pollFailCount = 0;
        genAllState.phase = st.phase || 'unknown';
        genAllState.phaseDetail = st.phase_detail || '';
        genAllState.current = st.current_day >= 0 ? st.current_day : genAllState.current;
        if (st.day_run_ids) {
          for (let idx = 0; idx < st.day_run_ids.length; idx++) {
            if (!genAllState.results[idx]) genAllState.results[idx] = { day: DAY_NAMES[idx], status: 'done', runId: st.day_run_ids[idx] };
          }
        }
        if (st.phase === 'generating_days' && st.current_day >= 0 && st.day_run_ids) {
          const dayRunId = st.day_run_ids[st.current_day];
          if (dayRunId) {
            try {
              const dayStatus = await api('/pipeline/' + dayRunId + '/status');
              if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running' };
              genAllState.results[st.current_day].stepStatus = dayStatus.step_status || {};
            } catch {}
          }
          if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running', stepStatus: {} };
          else genAllState.results[st.current_day].status = 'running';
        }
        done = st.status === 'completed' || st.status === 'failed';
        if (st.status === 'failed') genAllState.errorMsg = st.error || 'Unknown error';
      } catch (pollErr) {
        pollFailCount++;
        if (pollFailCount >= 5) { genAllState.phase = 'failed'; genAllState.phaseDetail = 'Lost connection'; done = true; }
      }
      saveGenAllState();
      renderGenAllProgress();
    }
  } catch (e) {
    genAllState.phase = 'failed';
    genAllState.phaseDetail = 'Failed to start: ' + e.message;
    toast('Generation failed: ' + e.message, false);
  }
  genAllState.running = false;
  saveGenAllState();
  renderGenAllProgress();
  renderWeek();
}

function escHtml(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function dismissPlanReview() { const p = document.getElementById('plan-review-panel'); if (p) p.innerHTML = ''; renderWeek(); }

function editWeekPlan() {
  const entries = window._weekEntries || [];
  const mondayStr = window._weekMondayStr || '';
  if (!entries.length) { toast('No plan data to edit', false); return; }
  const meta = entries.find(e => e.plan_context?._weekly)?.plan_context?._weekly || {};
  const days = entries.filter(e => e.plan_context).map(e => {
    const pc = e.plan_context || {};
    return { day_of_week: e.day_of_week, angle_type: e.angle_type, topic: e.topic || pc.topic || '', thesis: pc.thesis || '', audience: pc.audience || '', desired_belief_shift: pc.desired_belief_shift || '', connection_to_gift: pc.connection_to_gift || '', visual_job: pc.visual_job || 'cinematic_symbolic', evidence_requirements: pc.evidence_requirements || [], platform_notes: pc.platform_notes || '' };
  });
  const planData = { weekly_plan: { weekly_theme: meta.weekly_theme || '', gift_theme: meta.gift_theme || '', gift_sections: meta.gift_sections || [], cta_keyword: meta.cta_keyword || '', days: days }, trend_summary: [] };
  deepPlanId = 'edit-' + Date.now();
  approvedPlan = planData.weekly_plan;
  showPlanReview(planData, mondayStr);
}

async function generateFromPlan() {
  // Check if there is an approved plan in calendar entries
  try {
    const monday = getMondayOfWeek();
    const friday = new Date(monday); friday.setDate(friday.getDate() + 4);
    const entries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(friday));
    const withPlan = entries.filter(e => e.plan_context && ['approved', 'planned'].includes(e.status));
    if (withPlan.length === 0) {
      toast('No plan found for this week. Click "Plan This Week" first.', false);
      return;
    }
    // Reconstruct approved plan from calendar entries
    const plan = {
      weekly_theme: '',
      gift_theme: '',
      cta_keyword: '',
      days: withPlan.map(e => ({
        day_of_week: e.day_of_week,
        ...e.plan_context,
      })),
    };
    // Parse operator_notes for theme/cta
    const notes = withPlan[0].operator_notes || '';
    const themeMatch = notes.match(/Weekly theme: ([^|]+)/);
    const ctaMatch = notes.match(/CTA: ([^|]+)/);
    const giftMatch = notes.match(/Gift: (.+)$/);
    if (themeMatch) plan.weekly_theme = themeMatch[1].trim();
    if (ctaMatch) plan.cta_keyword = ctaMatch[1].trim();
    if (giftMatch) plan.gift_theme = giftMatch[1].trim();
    generateFromApprovedPlan(plan);
  } catch (e) { toast('Error: ' + e.message, false); }
}

function getMondayOfWeek() {
  const now = new Date();
  now.setDate(now.getDate() + (weekOffset || 0) * 7);
  const day = now.getDay();
  const diff = now.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(now.setDate(diff));
}

async function runDayPipeline(dayOfWeek, entryId) {
  try {
    const r = await api('/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({ workflow: 'daily_content', context: { day_of_week: dayOfWeek } }),
    });
    activePipelineRun = r.run_id;
    localStorage.setItem('tce_active_run', r.run_id);
    toast('Pipeline started for ' + DAY_NAMES[dayOfWeek] + ': ' + r.run_id.substring(0, 8));
    // Switch to generate tab to show progress
    currentTab = 'generate';
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === 'generate'));
    render();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollPipeline, 3000);
  } catch (e) { toast('Failed: ' + e.message, false); }
}

function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + 's';
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
}
function renderGenAllProgress() {
  const el = document.getElementById('gen-all-progress');
  if (!el) return;
  if (!genAllState) { el.innerHTML = ''; return; }
  const s = genAllState;
  const elapsed = s.startTime ? formatElapsed(Date.now() - s.startTime) : '';
  let html = '<div class="card" style="margin-bottom:16px;padding:16px">';

  // Phase-aware header
  let headerText = 'Generation complete';
  if (s.running) {
    if (s.unified) {
      if (s.phase === 'planning') headerText = 'Planning the week (trend scout + strategy)...';
      else if (s.phase === 'generating_days') headerText = 'Generating day ' + ((s.current >= 0 ? s.current : 0) + 1) + '/5...';
      else if (s.phase === 'building_guide') headerText = 'Building weekly guide...';
      else headerText = s.phaseDetail || 'Starting unified weekly generation...';
    } else {
      headerText = 'Generating content for all 5 days...';
    }
  }
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">';
  html += '<div style="font-size:13px;font-weight:600">' + headerText + '</div>';
  if (elapsed) html += '<div style="font-size:12px;color:var(--dim);font-family:monospace">' + elapsed + '</div>';
  html += '</div>';

  // Show weekly theme + gift theme once available (unified mode)
  if (s.unified && s.weeklyTheme) {
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:12px">';
    html += '<div style="font-size:11px;color:var(--dim);margin-bottom:4px">WEEKLY THEME</div>';
    html += '<div style="font-size:13px;font-weight:600;color:var(--accent2)">' + esc(s.weeklyTheme) + '</div>';
    if (s.giftTheme) {
      html += '<div style="font-size:11px;color:var(--dim);margin-top:6px">GIFT/GUIDE</div>';
      html += '<div style="font-size:12px;color:var(--green)">' + esc(s.giftTheme) + '</div>';
    }
    if (s.weeklyKeyword) {
      html += '<div style="font-size:11px;color:var(--dim);margin-top:4px">CTA KEYWORD: <span style="color:var(--yellow);font-weight:600">' + esc(s.weeklyKeyword) + '</span></div>';
    }
    html += '</div>';
  }

  // Phase progress bar (unified mode)
  if (s.unified && s.running) {
    const phases = ['planning', 'generating_days', 'building_guide'];
    const phaseLabels = ['Plan Week', 'Generate 5 Days', 'Build Guide'];
    const curIdx = phases.indexOf(s.phase);
    html += '<div style="display:flex;gap:4px;margin-bottom:12px">';
    for (let pi = 0; pi < phases.length; pi++) {
      const pct = pi < curIdx ? '100%' : (pi === curIdx ? (s.phase === 'generating_days' && s.current >= 0 ? Math.round(((s.current + 0.5) / 5) * 100) + '%' : '50%') : '0%');
      const bg = pi < curIdx ? 'var(--green)' : (pi === curIdx ? 'var(--blue)' : 'var(--border)');
      html += '<div style="flex:1;text-align:center">';
      html += '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:4px"><div style="height:100%;background:' + bg + ';width:' + pct + ';transition:width 0.3s"></div></div>';
      html += '<div style="font-size:10px;color:' + (pi === curIdx ? 'var(--text)' : 'var(--dim)') + ';font-weight:' + (pi === curIdx ? '600' : '400') + '">' + phaseLabels[pi] + '</div>';
      html += '</div>';
    }
    html += '</div>';
  }

  // Planner agent detail (during planning phase)
  if (s.unified && s.running && s.phase === 'planning' && s.plannerStepStatus) {
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--accent2);margin-bottom:8px">Weekly Planner - Agent Steps</div>';
    for (const [agent, st] of Object.entries(s.plannerStepStatus)) {
      const label = AGENT_LABELS[agent] || agent.replace(/_/g, ' ');
      let icon, stColor;
      if (st === 'completed') { icon = 'Done'; stColor = 'var(--green)'; }
      else if (st === 'running') { icon = 'Running...'; stColor = 'var(--blue)'; }
      else { icon = 'Waiting'; stColor = 'var(--dim)'; }
      html += '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px">';
      html += '<span style="color:' + (st === 'running' ? 'var(--text)' : 'var(--dim)') + '">' + label + '</span>';
      html += '<span style="color:' + stColor + ';font-weight:600;font-size:11px">' + icon + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  // Day badges
  html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">';
  for (let i = 0; i < 5; i++) {
    const r = s.results[i];
    let bg, color, label;
    if (r?.status === 'done') { bg = 'var(--green)'; color = '#000'; label = DAY_NAMES[i] + ' Done'; }
    else if (r?.status === 'failed') { bg = 'var(--red)'; color = '#fff'; label = DAY_NAMES[i] + ' Failed'; }
    else if (s.running && i === s.current) { bg = 'var(--blue)'; color = '#fff'; label = DAY_NAMES[i] + '...'; }
    else { bg = 'var(--border)'; color = 'var(--dim)'; label = DAY_NAMES[i]; }
    html += '<div style="padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;background:' + bg + ';color:' + color;
    if (s.running && i === s.current) html += ';border-left:3px solid var(--blue)';
    html += '">' + label + '</div>';
  }
  html += '</div>';

  // Current day agent-level detail (during generating_days phase)
  const cur = s.current >= 0 ? s.results[s.current] : null;
  if (s.running && cur?.stepStatus && Object.keys(cur.stepStatus).length > 0) {
    const steps = cur.stepStatus;
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--accent2);margin-bottom:8px">' + DAY_NAMES[s.current] + ' - Pipeline Steps</div>';
    const entries = Object.entries(steps);
    const total = entries.length;
    const completed = entries.filter(([,v]) => v === 'completed' || v === 'skipped').length;
    html += '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:10px">';
    html += '<div style="height:100%;background:var(--green);width:' + Math.round((completed/total)*100) + '%;transition:width 0.3s"></div>';
    html += '</div>';
    for (const [agent, st] of entries) {
      const label = AGENT_LABELS[agent] || agent.replace(/_/g, ' ');
      let icon, stColor;
      if (st === 'completed') { icon = 'Done'; stColor = 'var(--green)'; }
      else if (st === 'running') { icon = 'Running...'; stColor = 'var(--blue)'; }
      else if (st === 'failed') { icon = 'Failed'; stColor = 'var(--red)'; }
      else if (st === 'skipped') { icon = 'Skipped'; stColor = 'var(--yellow)'; }
      else { icon = 'Waiting'; stColor = 'var(--dim)'; }
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:12px">';
      html += '<span style="color:' + (st === 'running' ? 'var(--text)' : 'var(--dim)') + ';font-weight:' + (st === 'running' ? '600' : '400') + '">';
      if (st === 'running') html += '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--blue);margin-right:6px"></span>';
      html += label + '</span>';
      html += '<span style="color:' + stColor + ';font-weight:600;font-size:11px">' + icon + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  if (!s.running) {
    const done = s.results.filter(r => r?.status === 'done').length;
    const fail = s.results.filter(r => r?.status === 'failed').length;
    html += '<div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">';
    if (s.phase === 'failed' || s.phase === 'completed') {
      html += '<span style="font-size:13px;color:' + (s.phase === 'failed' ? 'var(--red)' : 'var(--green)') + ';font-weight:600">' + (s.phase === 'failed' ? 'Failed: ' + (s.errorMsg || s.phaseDetail || 'Unknown error') : done + '/5 completed + guide built') + '</span>';
    } else {
      html += '<span style="font-size:13px;color:var(--green);font-weight:600">' + done + '/5 completed</span>';
      if (fail) html += '<span style="font-size:13px;color:var(--red)">' + fail + ' failed</span>';
    }
    if (s.totalCost) html += '<span style="font-size:13px;color:var(--accent2)">Total: $' + s.totalCost.toFixed(2) + '</span>';
    for (let fi = 0; fi < 5; fi++) {
      if (s.results[fi]?.status === 'failed') {
        html += '<button class="btn btn-red" style="font-size:11px;padding:4px 10px" onclick="retryOneDay(' + fi + ')">Retry ' + DAY_NAMES[fi] + '</button>';
      }
    }
    html += '<button class="btn btn-dim" style="margin-left:auto;font-size:12px" onclick="genAllState=null;saveGenAllState();renderGenAllProgress()">Dismiss</button>';
    html += '</div>';
    // Show error details for failed days
    for (let fi = 0; fi < 5; fi++) {
      if (s.results[fi]?.status === 'failed' && s.results[fi]?.errorMsg) {
        html += '<div style="margin-top:6px;padding:8px 12px;background:#2d0000;border:1px solid var(--red);border-radius:6px;font-size:12px">';
        html += '<span style="color:var(--red);font-weight:600">' + DAY_NAMES[fi] + ':</span> <span style="color:#fecaca">' + esc(s.results[fi].errorMsg.substring(0, 200)) + '</span>';
        html += '</div>';
      }
    }
  }
  html += '</div>';
  el.innerHTML = html;
  // Update button state
  const btn = document.getElementById('gen-all-btn');
  if (btn) {
    btn.disabled = s.running;
    if (s.unified && s.running) {
      if (s.phase === 'planning') btn.textContent = 'Planning week...';
      else if (s.phase === 'generating_days') btn.textContent = 'Day ' + ((s.current >= 0 ? s.current : 0) + 1) + '/5...';
      else if (s.phase === 'building_guide') btn.textContent = 'Building guide...';
      else btn.textContent = 'Starting...';
    } else if (s.running) {
      const curAgent = cur?.stepStatus ? Object.entries(cur.stepStatus).find(([,v]) => v === 'running') : null;
      const agentLabel = curAgent ? (AGENT_LABELS[curAgent[0]] || curAgent[0]) : '';
      btn.textContent = agentLabel ? agentLabel + '... (' + (s.current+1) + '/5)' : 'Generating ' + DAY_NAMES[s.current] + '... (' + (s.current+1) + '/5)';
    } else {
      btn.textContent = 'Generate All Days';
    }
  }
}

function saveGenAllState() {
  if (genAllState) sessionStorage.setItem('genAllState', JSON.stringify(genAllState));
  else sessionStorage.removeItem('genAllState');
}
function restoreGenAllState() {
  try {
    const saved = sessionStorage.getItem('genAllState');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.running) {
        // Only restore if it was actively running - resume polling
        genAllState = parsed;
        if (parsed.unified && parsed.weekId) {
          // Unified flow - resume week polling
          resumeUnifiedGenAll();
        } else {
          resumeGenAll();
        }
        renderGenAllProgress();
      } else {
        // Completed/failed state - don't show stale results on refresh
        sessionStorage.removeItem('genAllState');
      }
    }
  } catch { /* ignore */ }
}
async function resumeUnifiedGenAll() {
  if (!genAllState?.weekId) { genAllState.running = false; saveGenAllState(); renderGenAllProgress(); return; }
  let done = false;
  let failCount = 0;
  while (!done) {
    await new Promise(ok => setTimeout(ok, 2500));
    try {
      const st = await api('/pipeline/generate-week/' + genAllState.weekId + '/status');
      failCount = 0;
      genAllState.phase = st.phase || 'unknown';
      genAllState.phaseDetail = st.phase_detail || '';
      genAllState.current = st.current_day >= 0 ? st.current_day : genAllState.current;
      if (st.weekly_theme) genAllState.weeklyTheme = st.weekly_theme;
      if (st.gift_theme) genAllState.giftTheme = st.gift_theme;
      if (st.weekly_keyword) genAllState.weeklyKeyword = st.weekly_keyword;
      if (st.day_run_ids) {
        for (let i = 0; i < st.day_run_ids.length; i++) {
          if (!genAllState.results[i]) genAllState.results[i] = { day: DAY_NAMES[i], status: 'done', runId: st.day_run_ids[i] };
        }
      }
      done = st.status === 'completed' || st.status === 'failed';
      if (st.status === 'failed') genAllState.errorMsg = st.error || 'Unknown error';
    } catch (e) {
      failCount++;
      if (failCount >= 3) {
        // Server restarted or week ID is stale - stop polling
        genAllState.phase = 'failed';
        genAllState.phaseDetail = 'Lost connection to pipeline (server may have restarted)';
        done = true;
      }
    }
    saveGenAllState();
    renderGenAllProgress();
  }
  genAllState.running = false;
  saveGenAllState();
  renderGenAllProgress();
  renderWeek();
}
async function resumeGenAll() {
  // Resume polling for the current day's run_id
  const cur = genAllState.results[genAllState.current];
  if (!cur?.runId) { genAllState.running = false; saveGenAllState(); renderGenAllProgress(); return; }
  // Poll current day to completion
  let done = false;
  while (!done) {
    await new Promise(ok => setTimeout(ok, 2000));
    try {
      const status = await api('/pipeline/' + cur.runId + '/status');
      cur.stepStatus = status.step_status || {};
      const vals = Object.values(cur.stepStatus);
      done = !vals.some(s => s === 'pending' || s === 'running');
      if (done) {
        const hasFail = vals.some(s => s === 'failed');
        cur.status = hasFail ? 'failed' : 'done';
        toast(DAY_NAMES[genAllState.current] + (hasFail ? ' finished with errors' : ' done!'), !hasFail);
      }
    } catch { done = true; cur.status = 'failed'; }
    saveGenAllState();
    renderGenAllProgress();
  }
  // Continue with remaining days
  for (let i = genAllState.current + 1; i < 5; i++) {
    await runOneDay(i);
  }
  genAllState.running = false;
  saveGenAllState();
  renderGenAllProgress();
  renderWeek();
}
async function runOneDay(i) {
  genAllState.current = i;
  genAllState.results[i] = { day: DAY_NAMES[i], status: 'running', stepStatus: {}, startTime: Date.now() };
  saveGenAllState();
  renderGenAllProgress();
  try {
    const r = await api('/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({ workflow: 'daily_content', context: { day_of_week: i } }),
    });
    genAllState.results[i].runId = r.run_id;
    saveGenAllState();
    let done = false;
    while (!done) {
      await new Promise(ok => setTimeout(ok, 2000));
      try {
        const status = await api('/pipeline/' + r.run_id + '/status');
        genAllState.results[i].stepStatus = status.step_status || {};
        const vals = Object.values(status.step_status || {});
        done = !vals.some(s => s === 'pending' || s === 'running');
        if (done) {
          const hasFail = vals.some(s => s === 'failed');
          genAllState.results[i].status = hasFail ? 'failed' : 'done';
          if (hasFail && status.step_errors) {
            const errParts = Object.entries(status.step_errors).map(([k,v]) => k.replace(/_/g,' ') + ': ' + v);
            genAllState.results[i].errorMsg = errParts.join('; ');
          }
          toast(DAY_NAMES[i] + (hasFail ? ' finished with errors' : ' done!'), !hasFail);
        }
      } catch (pollErr) { done = true; genAllState.results[i].status = 'failed'; genAllState.results[i].errorMsg = pollErr.message || 'Connection lost'; }
      saveGenAllState();
      renderGenAllProgress();
    }
  } catch (e) {
    genAllState.results[i] = { day: DAY_NAMES[i], status: 'failed', errorMsg: e.message || 'Pipeline start failed' };
    toast(DAY_NAMES[i] + ' failed: ' + e.message, false);
    saveGenAllState();
    renderGenAllProgress();
  }
}
async function generateAllDays() {
  genAllState = { running: true, current: -1, total: 5, startTime: Date.now(), results: [], totalCost: 0, unified: true, weekId: null, phase: 'starting', phaseDetail: 'Initializing unified weekly generation...', weeklyTheme: null, giftTheme: null, weeklyKeyword: null };
  saveGenAllState();
  renderGenAllProgress();
  try {
    // Start unified weekly generation
    const r = await api('/pipeline/generate-week', {
      method: 'POST',
      body: JSON.stringify({ context: {} }),
    });
    genAllState.weekId = r.week_id;
    saveGenAllState();
    // Poll for status
    let done = false;
    let pollFailCount = 0;
    while (!done) {
      await new Promise(ok => setTimeout(ok, 2500));
      try {
        const st = await api('/pipeline/generate-week/' + r.week_id + '/status');
        pollFailCount = 0;
        genAllState.phase = st.phase || 'unknown';
        genAllState.phaseDetail = st.phase_detail || '';
        genAllState.current = st.current_day >= 0 ? st.current_day : genAllState.current;
        if (st.weekly_theme) genAllState.weeklyTheme = st.weekly_theme;
        if (st.gift_theme) genAllState.giftTheme = st.gift_theme;
        if (st.weekly_keyword) genAllState.weeklyKeyword = st.weekly_keyword;
        // Map day results from the backend run IDs
        if (st.day_run_ids) {
          for (let i = 0; i < st.day_run_ids.length; i++) {
            if (!genAllState.results[i]) genAllState.results[i] = { day: DAY_NAMES[i], status: 'done', runId: st.day_run_ids[i] };
          }
        }
        // Check active day - try to get agent-level detail
        if (st.phase === 'generating_days' && st.current_day >= 0 && st.day_run_ids) {
          const dayRunId = st.day_run_ids[st.current_day];
          if (dayRunId) {
            try {
              const dayStatus = await api('/pipeline/' + dayRunId + '/status');
              if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running' };
              genAllState.results[st.current_day].stepStatus = dayStatus.step_status || {};
            } catch {}
          }
          // Mark current day as running
          if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running', stepStatus: {} };
          else genAllState.results[st.current_day].status = 'running';
        }
        // Also poll planner run for agent detail during planning phase
        if (st.phase === 'planning' && st.planner_run_id) {
          try {
            const plannerStatus = await api('/pipeline/' + st.planner_run_id + '/status');
            genAllState.plannerStepStatus = plannerStatus.step_status || {};
          } catch {}
        }
        done = st.status === 'completed' || st.status === 'failed';
        if (st.status === 'failed') {
          genAllState.errorMsg = st.error || 'Unknown error';
        }
      } catch (pollErr) {
        pollFailCount++;
        if (pollFailCount >= 5) {
          genAllState.phase = 'failed';
          genAllState.phaseDetail = 'Lost connection to pipeline';
          done = true;
        }
      }
      saveGenAllState();
      renderGenAllProgress();
    }
  } catch (e) {
    genAllState.phase = 'failed';
    genAllState.phaseDetail = 'Failed to start: ' + e.message;
    toast('Weekly generation failed: ' + e.message, false);
  }
  genAllState.running = false;
  saveGenAllState();
  renderGenAllProgress();
  renderWeek();
}

async function retryOneDay(dayIndex) {
  if (!genAllState) return;
  genAllState.running = true;
  genAllState.current = dayIndex;
  genAllState.results[dayIndex] = { day: DAY_NAMES[dayIndex], status: 'running', stepStatus: {}, startTime: Date.now() };
  saveGenAllState();
  renderGenAllProgress();
  await runOneDay(dayIndex);
  genAllState.running = false;
  saveGenAllState();
  renderGenAllProgress();
  renderWeek();
}

function viewPackage(pkgId) {
  // Switch to packages tab and scroll to the specific package
  currentTab = 'packages';
  document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === 'packages'));
  render();
  // After render, try to highlight the package
  setTimeout(() => {
    const cards = document.querySelectorAll('.pkg-card');
    for (const card of cards) {
      if (card.innerHTML.includes(pkgId.substring(0, 8))) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.style.outline = '2px solid var(--accent)';
        setTimeout(() => card.style.outline = '', 3000);
        break;
      }
    }
  }, 500);
}

async function runWeeklyPlanning() {
  try {
    const r = await api('/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({ workflow: 'weekly_planning', context: {} }),
    });
    activePipelineRun = r.run_id;
    localStorage.setItem('tce_active_run', r.run_id);
    toast('Weekly planning started: ' + r.run_id.substring(0, 8));
    currentTab = 'generate';
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === 'generate'));
    render();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollPipeline, 3000);
  } catch (e) { toast('Failed: ' + e.message, false); }
}

// GENERATE TAB
async function renderGenerate() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="section">
      <h2>Run Content Pipeline</h2>
      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;gap:12px;align-items:end;flex-wrap:wrap">
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Workflow</label>
            <select id="wf-select" onchange="updateWfDesc()">
              <option value="daily_content">Daily Content (full pipeline)</option>
              <option value="weekly_planning">Weekly Planning</option>
              <option value="corpus_ingestion">Corpus Ingestion</option>
              <option value="weekly_learning">Weekly Learning</option>
            </select>
            <div id="wf-desc" style="font-size:12px;color:var(--text);margin-top:8px;max-width:500px;line-height:1.6;opacity:0.85"></div>
          </div>
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Day of Week</label>
            <select id="dow-select">
              <option value="0">Mon - Big Shift Explainer</option>
              <option value="1">Tue - Tactical Workflow</option>
              <option value="2">Wed - Contrarian Diagnosis</option>
              <option value="3" selected>Thu - Case Study Build</option>
              <option value="4">Fri - Second Order</option>
            </select>
          </div>
          <button class="btn btn-primary" id="run-btn" onclick="runPipeline()">Run Pipeline</button>
        </div>
      </div>
      <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
        <label style="font-size:12px;color:var(--dim);cursor:pointer;display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="verbose-toggle" ${verboseMode ? 'checked' : ''} onchange="verboseMode=this.checked;localStorage.setItem('tce_verbose',verboseMode);if(activePipelineRun)pollPipeline()">
          Verbose mode (show what each agent is doing)
        </label>
      </div>
      <div id="pipeline-status"></div>
    </div>`;
  if (activePipelineRun) { pollPipeline(); if(!pollInterval) pollInterval = setInterval(pollPipeline, 3000); }
  updateWfDesc();
}

const WF_DESCRIPTIONS = {
  daily_content: 'Generates one complete post package for today. Runs: TrendScout (finds trending stories) -> StoryStrategist (picks angle) -> ResearchAgent (verifies claims) -> FB + LI Writers (draft posts) -> CTA Agent (keyword + DM flow) -> Creative Director (image prompts) -> QA (quality check). Use this daily to produce content.',
  weekly_planning: 'Plans the entire week ahead. Runs: TrendScout (landscape scan) -> StoryStrategist (5-day theme) -> ResearchAgent (evidence bank) -> CTA Agent (weekly keyword) -> Guide Builder (creates downloadable DOCX brief). Use this on Sunday/Monday to set up the week.',
  corpus_ingestion: 'Processes uploaded DOCX files into structured post examples. Runs: CorpusAnalyst (parses posts from docs) -> EngagementScorer (rates each post) -> PatternMiner (extracts reusable templates). Use this after uploading new swipe files / FB profile exports.',
  weekly_learning: 'Reviews the past week and improves the system. Runs: LearningLoop (analyzes what worked, updates templates and scoring). Use this at end of week to refine content quality over time.'
};
function updateWfDesc() {
  const sel = document.getElementById('wf-select');
  const desc = document.getElementById('wf-desc');
  if (sel && desc) desc.textContent = WF_DESCRIPTIONS[sel.value] || '';
}

async function runPipeline() {
  const wf = document.getElementById('wf-select').value;
  const dow = parseInt(document.getElementById('dow-select').value);
  document.getElementById('run-btn').disabled = true;
  document.getElementById('run-btn').textContent = 'Starting...';
  try {
    const r = await api('/pipeline/run', { method: 'POST', body: JSON.stringify({ workflow: wf, context: { day_of_week: dow } }) });
    activePipelineRun = r.run_id;
    localStorage.setItem('tce_active_run', r.run_id);
    toast('Pipeline started: ' + r.run_id.substring(0, 8));
    pollPipeline();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollPipeline, 3000);
  } catch (e) { toast('Failed: ' + e.message, false); }
}

// Track which agent sections are expanded (auto-expand running ones)
let expandedSteps = {};
let pipelineInitialized = false;
let prevLogCounts = {};

function formatLogLine(raw) {
  // Parse "[HH:MM:SS] message" into pretty format
  const m = raw.match(/^\\[(\\d{2}:\\d{2}:\\d{2})\\]\\s*(.*)$/);
  if (!m) return '<div style="padding:4px 0 4px 8px;color:var(--text);font-size:13px;line-height:1.5">' + esc(raw) + '</div>';
  const time = m[1];
  let msg = m[2];
  // Highlight key patterns
  let color = 'var(--text)';
  let icon = '';
  if (msg.startsWith('Starting')) { icon = '▶ '; color = 'var(--blue)'; }
  else if (msg.startsWith('Done') || msg.startsWith('Total')) { icon = '✓ '; color = 'var(--green)'; }
  else if (msg.startsWith('Calling')) { icon = '⟳ '; color = 'var(--yellow)'; }
  else if (msg.startsWith('LLM responded')) { icon = '◆ '; color = 'var(--accent2)'; }
  else if (msg.match(/^\\d+\\./)) { icon = ''; color = '#e4e4e7'; }
  else if (msg.startsWith('  ')) { color = 'var(--dim)'; }
  return '<div style="display:flex;gap:8px;padding:3px 0 3px 8px;font-size:13px;line-height:1.6"><span style="color:var(--dim);font-size:11px;min-width:52px;font-family:monospace">' + time + '</span><span style="color:' + color + '">' + icon + esc(msg) + '</span></div>';
}

function toggleStep(step) {
  expandedSteps[step] = !expandedSteps[step];
  const el = document.getElementById('step-logs-' + step);
  const arrow = document.getElementById('step-arrow-' + step);
  if (el) el.style.display = expandedSteps[step] ? 'block' : 'none';
  if (arrow) arrow.textContent = expandedSteps[step] ? '▾' : '▸';
}

async function pollPipeline() {
  if (!activePipelineRun) return;
  try {
    const r = await api('/pipeline/' + activePipelineRun + '/status');
    const statuses = r.step_status || {};
    const errors = r.step_errors || {};
    const logs = r.step_logs || {};
    const allDone = !Object.values(statuses).some(s => s === 'pending' || s === 'running');

    const container = document.getElementById('pipeline-status');
    if (!container) return;

    // First render: build the skeleton
    if (!pipelineInitialized || !container.querySelector('.pipeline-card')) {
      // Auto-expand running steps
      for (const [step, status] of Object.entries(statuses)) {
        if (status === 'running') expandedSteps[step] = true;
      }
      let html = '<div class="card pipeline-card"><h3 style="margin-bottom:12px">Pipeline: ' + activePipelineRun.substring(0, 8) + '...</h3>';
      // Step badges row
      html += '<div class="pipeline-steps" id="pipeline-badges">';
      for (const [step, status] of Object.entries(statuses)) {
        html += '<div class="step-badge ' + status + '" id="badge-' + step + '" style="cursor:pointer" onclick="toggleStep(\\'' + step + '\\')">' + step.replace(/_/g, ' ') + '</div>';
      }
      html += '</div>';
      // Agent detail sections
      if (verboseMode) {
        html += '<div id="agent-sections" style="margin-top:16px">';
        for (const [step, status] of Object.entries(statuses)) {
          const isExpanded = expandedSteps[step];
          const statusColor = status === 'completed' ? 'var(--green)' : status === 'running' ? 'var(--blue)' : status === 'failed' ? 'var(--red)' : 'var(--dim)';
          html += '<div style="border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden" id="step-section-' + step + '">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;cursor:pointer;background:var(--card);user-select:none" onclick="toggleStep(\\'' + step + '\\')">';
          html += '<div style="display:flex;align-items:center;gap:8px"><span id="step-arrow-' + step + '" style="color:var(--dim);font-size:12px">' + (isExpanded ? '▾' : '▸') + '</span>';
          html += '<span style="font-weight:600;font-size:13px">' + step.replace(/_/g, ' ') + '</span>';
          html += '<span style="font-size:11px;color:' + statusColor + ';font-weight:500" id="step-status-' + step + '">' + status + '</span></div>';
          html += '<span style="font-size:11px;color:var(--dim)" id="step-summary-' + step + '"></span>';
          html += '</div>';
          html += '<div id="step-logs-' + step + '" style="display:' + (isExpanded ? 'block' : 'none') + ';max-height:350px;overflow-y:auto;padding:4px 6px;background:#0d0f14;border-top:1px solid var(--border)"></div>';
          html += '</div>';
        }
        html += '</div>';
      }
      html += '<div id="pipeline-errors"></div>';
      html += '<div id="pipeline-footer"></div>';
      html += '</div>';
      container.innerHTML = html;
      pipelineInitialized = true;
      prevLogCounts = {};
    }

    // Update badges in-place
    for (const [step, status] of Object.entries(statuses)) {
      const badge = document.getElementById('badge-' + step);
      if (badge) { badge.className = 'step-badge ' + status; badge.style.cursor = 'pointer'; }
      // Auto-expand when a step starts running
      if (status === 'running' && !expandedSteps[step]) {
        expandedSteps[step] = true;
        const el = document.getElementById('step-logs-' + step);
        const arrow = document.getElementById('step-arrow-' + step);
        if (el) el.style.display = 'block';
        if (arrow) arrow.textContent = '▾';
      }
    }

    // Update agent sections in-place (append new logs only)
    if (verboseMode) {
      for (const [step, status] of Object.entries(statuses)) {
        const stepLogs = logs[step] || [];
        const statusEl = document.getElementById('step-status-' + step);
        const summaryEl = document.getElementById('step-summary-' + step);
        const logsEl = document.getElementById('step-logs-' + step);
        const sectionEl = document.getElementById('step-section-' + step);

        // Update status text and color
        if (statusEl) {
          const statusColor = status === 'completed' ? 'var(--green)' : status === 'running' ? 'var(--blue)' : status === 'failed' ? 'var(--red)' : 'var(--dim)';
          statusEl.textContent = status;
          statusEl.style.color = statusColor;
        }

        // Update section border for running step
        if (sectionEl) {
          sectionEl.style.borderColor = status === 'running' ? 'var(--blue)' : 'var(--border)';
        }

        // Show latest activity as summary
        if (summaryEl && stepLogs.length) {
          const last = stepLogs[stepLogs.length - 1].replace(/^\\[\\d{2}:\\d{2}:\\d{2}\\]\\s*/, '');
          summaryEl.textContent = last.substring(0, 80) + (last.length > 80 ? '...' : '');
        }

        // Append only NEW log lines
        if (logsEl) {
          const prevCount = prevLogCounts[step] || 0;
          if (stepLogs.length > prevCount) {
            const newLogs = stepLogs.slice(prevCount);
            let newHtml = '';
            for (const log of newLogs) newHtml += formatLogLine(log);
            logsEl.insertAdjacentHTML('beforeend', newHtml);
            // Auto-scroll only if user hasn't scrolled up
            const isNearBottom = logsEl.scrollHeight - logsEl.scrollTop - logsEl.clientHeight < 80;
            if (isNearBottom) logsEl.scrollTop = logsEl.scrollHeight;
          }
          prevLogCounts[step] = stepLogs.length;
        }
      }
    }

    // Update errors in-place
    const errEl = document.getElementById('pipeline-errors');
    if (errEl) {
      const errEntries = Object.entries(errors).filter(([k,v]) => v);
      if (errEntries.length) {
        let eh = '<div class="log" style="border-color:var(--red);margin-top:8px">';
        for (const [step, err] of errEntries) eh += '<div style="color:var(--red);font-size:13px"><strong>' + step.replace(/_/g, ' ') + ':</strong> ' + esc(err).substring(0, 300) + '</div>';
        eh += '</div>';
        errEl.innerHTML = eh;
      }
    }

    // Update footer
    const footerEl = document.getElementById('pipeline-footer');
    if (footerEl && allDone) {
      if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
      localStorage.removeItem('tce_active_run');
      const hasCompleted = Object.values(statuses).some(s => s === 'completed');
      const hasFailed = Object.values(statuses).some(s => s === 'failed');
      let fh = '<div style="margin-top:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">';
      fh += '<span style="color:' + (hasFailed ? 'var(--yellow)' : 'var(--green)') + ';font-weight:600">' + (hasFailed ? 'Pipeline finished with errors' : 'Pipeline complete') + '</span>';
      fh += '<span id="run-cost-badge" style="font-size:13px;color:var(--accent2)"></span>';
      fh += '</div>';
      // Fetch run cost
      if (activePipelineRun) {
        api('/costs/run/' + activePipelineRun).then(c => {
          const badge = document.getElementById('run-cost-badge');
          if (badge && c.total_cost) badge.textContent = 'Cost: $' + c.total_cost.toFixed(2);
        }).catch(() => {});
      }
      fh += '<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">';
      // Check if a guide was produced (docx_guide_builder completed)
      if (statuses.docx_guide_builder === 'completed') {
        fh += '<button class="btn btn-green" style="font-size:14px;padding:10px 20px" onclick="downloadLatestGuide()">Download Guide</button>';
      }
      if (hasCompleted) {
        fh += '<button class="btn btn-dim" style="font-size:13px;padding:8px 16px" onclick="currentTab=\\'packages\\';document.querySelectorAll(\\'.nav button\\').forEach(b=>b.classList.toggle(\\'active\\',b.dataset.tab===\\'packages\\'));render()">View Packages</button>';
      }
      fh += '</div>';
      footerEl.innerHTML = fh;
    }

    const btn = document.getElementById('run-btn');
    if (btn) { btn.disabled = !allDone; btn.textContent = allDone ? 'Run Pipeline' : 'Running...'; }
  } catch (e) {
    if (e.message?.includes('404') || e.message?.includes('not found')) {
      localStorage.removeItem('tce_active_run');
      activePipelineRun = null;
      if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    }
  }
}

// Download the most recent guide DOCX
async function downloadLatestGuide() {
  try {
    const guides = await api('/content/guides');
    if (!guides.length) { alert('No guides found. The guide builder may not have saved to the database.'); return; }
    const latest = guides[0];
    if (!latest.docx_path) { alert('Guide was created but no DOCX file was generated.'); return; }
    window.open(API + '/content/guides/' + latest.id + '/download', '_blank');
  } catch (e) {
    alert('Failed to fetch guide: ' + e.message);
  }
}

// PACKAGES TAB
let pkgDayFilter = Math.min(new Date().getDay() - 1, 4); // Default to today (0=Mon, 4=Fri)
if (pkgDayFilter < 0) pkgDayFilter = 0; // Weekend defaults to Monday
async function renderPackages() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h2>Content Packages</h2><label style="font-size:12px;color:var(--dim);cursor:pointer;display:flex;align-items:center;gap:6px"><input type="checkbox" id="show-archived" ' + (showArchived ? 'checked' : '') + ' onchange="showArchived=this.checked;renderPackages()"> Show archived</label></div><div id="pkg-day-tabs"></div><div id="pkg-list"><div class="empty">Loading...</div></div></div>';
  try {
    const pkgs = await api('/content/packages' + (showArchived ? '?include_archived=true' : ''));
    if (!pkgs.length) { document.getElementById('pkg-list').innerHTML = '<div class="empty">No packages yet. Run a pipeline first.</div>'; return; }

    // Fetch calendar to map packages to days
    const monday = getMondayOfWeek();
    const friday = new Date(monday); friday.setDate(friday.getDate() + 4);
    let calEntries = [];
    try { calEntries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(friday)); } catch {}
    const pkgDayMap = {};
    for (const e of calEntries) {
      if (e.post_package_id) pkgDayMap[e.post_package_id] = { day: e.day_of_week, date: e.date, topic: e.topic, angle: e.angle_type };
    }

    // Build day tabs
    const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
    let tabHtml = '<div style="display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap">';
    for (let d = 0; d < 5; d++) {
      const dayDate = new Date(monday); dayDate.setDate(dayDate.getDate() + d);
      const dateLabel = dayDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      const hasPkg = Object.values(pkgDayMap).some(m => m.day === d);
      const isActive = pkgDayFilter === d;
      const dotColor = hasPkg ? 'var(--green)' : 'var(--border)';
      tabHtml += '<button onclick="pkgDayFilter=' + d + ';renderPackages()" style="padding:8px 14px;border:1px solid ' + (isActive ? 'var(--accent)' : 'var(--border)') + ';background:' + (isActive ? 'var(--accent)' : 'var(--card)') + ';color:' + (isActive ? '#fff' : 'var(--text)') + ';border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;display:flex;align-items:center;gap:6px"><span style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span>' + dayNames[d] + ' ' + dateLabel + '</button>';
    }
    // Other tab for unlinked packages
    const unlinkedCount = pkgs.filter(p => !pkgDayMap[p.id]).length;
    if (unlinkedCount > 0) {
      const isOther = pkgDayFilter === 'other';
      tabHtml += '<button onclick="pkgDayFilter=\\'other\\';renderPackages()" style="padding:8px 14px;border:1px solid ' + (isOther ? 'var(--accent)' : 'var(--border)') + ';background:' + (isOther ? 'var(--accent)' : 'var(--card)') + ';color:' + (isOther ? '#fff' : 'var(--dim)') + ';border-radius:6px;cursor:pointer;font-size:13px">Other (' + unlinkedCount + ')</button>';
    }
    // All tab
    const isAll = pkgDayFilter === null;
    tabHtml += '<button onclick="pkgDayFilter=null;renderPackages()" style="padding:8px 14px;border:1px solid ' + (isAll ? 'var(--accent)' : 'var(--border)') + ';background:' + (isAll ? 'var(--accent)' : 'var(--card)') + ';color:' + (isAll ? '#fff' : 'var(--dim)') + ';border-radius:6px;cursor:pointer;font-size:13px">All (' + pkgs.length + ')</button>';
    tabHtml += '</div>';
    document.getElementById('pkg-day-tabs').innerHTML = tabHtml;

    // Filter packages by selected day
    let filteredPkgs = pkgs;
    if (pkgDayFilter !== null && pkgDayFilter !== 'other') {
      const dayPkgIds = new Set(Object.entries(pkgDayMap).filter(([, m]) => m.day === pkgDayFilter).map(([id]) => id));
      filteredPkgs = pkgs.filter(p => dayPkgIds.has(p.id));
    } else if (pkgDayFilter === 'other') {
      filteredPkgs = pkgs.filter(p => !pkgDayMap[p.id]);
    }

    if (!filteredPkgs.length) { document.getElementById('pkg-list').innerHTML = '<div class="empty" style="padding:24px;text-align:center">No packages for this day yet.</div>'; return; }

    let html = '<div class="packages-list">';
    for (const p of filteredPkgs) {
      // Day context header
      const dayInfo = pkgDayMap[p.id];
      if (dayInfo) {
        const dayLabel = DAY_NAMES[dayInfo.day] || '';
        const angleLabel = ANGLE_LABELS[dayInfo.angle] || (dayInfo.angle || '').replace(/_/g, ' ');
        html += '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;display:flex;align-items:center;gap:8px"><span style="color:var(--accent2);font-weight:600">' + dayLabel + ' ' + dayInfo.date + '</span><span>' + angleLabel + '</span></div>';
      }
      const statusTag = p.approval_status === 'approved' ? 'tag-approved' : p.approval_status === 'rejected' ? 'tag-rejected' : 'tag-draft';
      html += '<div class="pkg-card" id="pkg-' + p.id + '"' + (p.is_archived ? ' style="opacity:0.5"' : '') + '>';
      html += '<div class="pkg-header"><span class="tag ' + statusTag + '">' + p.approval_status + '</span>';
      if (p.is_archived) html += '<span style="font-size:11px;color:var(--dim);background:var(--border);padding:2px 8px;border-radius:4px">ARCHIVED</span>';
      html += '<span style="font-size:12px;color:var(--dim)">' + new Date(p.created_at).toLocaleString() + '</span></div>';
      const pid = p.id.replace(/-/g, '');
      const fbText = p.facebook_post || '';
      const liText = p.linkedin_post || '';
      const fbWc = fbText ? fbText.trim().split(/\\s+/).length : 0;
      const liWc = liText ? liText.trim().split(/\\s+/).length : 0;
      html += '<div class="pkg-meta">';
      if (p.cta_keyword) html += '<span>CTA: <strong>' + p.cta_keyword + '</strong></span>';
      if (fbWc) html += '<span style="color:var(--accent2);font-weight:600">FB: ' + fbWc + ' words</span>';
      if (liWc) html += '<span style="color:var(--accent2);font-weight:600">LI: ' + liWc + ' words</span>';
      if (p.pipeline_run_id) html += '<span>Run: ' + p.pipeline_run_id.substring(0, 8) + '</span>';
      html += '</div>';
      // Tabs
      html += '<div class="tabs">';
      html += '<button class="active" onclick="showPostTab(this,\\'fb-' + pid + '\\')">Facebook</button>';
      html += '<button onclick="showPostTab(this,\\'li-' + pid + '\\')">LinkedIn</button>';
      if (p.hook_variants?.length) html += '<button onclick="showPostTab(this,\\'hooks-' + pid + '\\')">Hooks (' + p.hook_variants.length + ')</button>';
      if (p.quality_scores) html += '<button onclick="showPostTab(this,\\'qa-' + pid + '\\')">QA Scores</button>';
      if (p.dm_flow) html += '<button onclick="showPostTab(this,\\'dm-' + pid + '\\')">DM Flow</button>';
      if (p.image_prompts?.length) html += '<button onclick="showPostTab(this,\\'img-' + pid + '\\')">Images (' + p.image_prompts.length + ')</button>';
      html += '</div>';
      html += '<div id="fb-' + pid + '"><div class="post-preview">' + esc(fbText || 'No Facebook post generated') + '</div></div>';
      html += '<div id="li-' + pid + '" style="display:none"><div class="post-preview">' + esc(liText || 'No LinkedIn post generated') + '</div></div>';
      if (p.hook_variants?.length) {
        html += '<div id="hooks-' + pid + '" class="post-preview" style="display:none">';
        p.hook_variants.forEach((h, i) => html += (i + 1) + '. ' + esc(h) + '\\n\\n');
        html += '</div>';
      }
      if (p.quality_scores) {
        html += '<div id="qa-' + pid + '" style="display:none">';
        // Composite score badge
        const composite = p.quality_scores.composite_score || p.quality_scores.overall;
        if (composite != null) {
          const compVal = typeof composite === 'number' ? composite : (composite?.score || 0);
          const compColor = compVal >= 7 ? 'var(--green)' : compVal >= 5 ? 'var(--yellow)' : 'var(--red)';
          const compLabel = compVal >= 7 ? 'PASS' : compVal >= 5 ? 'CONDITIONAL' : 'FAIL';
          html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:12px;background:#111318;border-radius:8px">';
          html += '<div style="font-size:32px;font-weight:800;color:' + compColor + '">' + (typeof compVal === 'number' ? compVal.toFixed(1) : compVal) + '</div>';
          html += '<div><div style="font-size:14px;font-weight:700;color:' + compColor + '">' + compLabel + '</div><div style="font-size:12px;color:var(--dim)">Composite QA Score</div></div>';
          html += '</div>';
        }
        html += '<div class="qa-grid">';
        for (const [k, v] of Object.entries(p.quality_scores)) {
          if (k === 'composite_score' || k === 'overall') continue;
          const score = typeof v === 'number' ? v : (v?.score || v);
          const justification = typeof v === 'object' ? v?.justification : null;
          const color = score >= 8 ? 'var(--green)' : score >= 6 ? 'var(--yellow)' : 'var(--red)';
          const icon = score >= 7 ? '\\u2713' : score >= 5 ? '\\u26A0' : '\\u2717';
          html += '<div class="qa-item" ' + (justification ? 'title="' + esc(justification) + '" style="cursor:help"' : '') + '>';
          html += '<div class="label">' + icon + ' ' + k.replace(/_/g, ' ') + '</div>';
          html += '<div class="score" style="color:' + color + '">' + (typeof score === 'number' ? score.toFixed(1) : score) + '</div>';
          html += '</div>';
        }
        html += '</div></div>';
      }
      if (p.dm_flow) {
        const dm = p.dm_flow;
        html += '<div id="dm-' + pid + '" style="display:none">';
        html += '<div style="display:flex;flex-direction:column;gap:12px">';
        if (dm.trigger) {
          html += '<div style="background:#1e1b4b;border:1px solid var(--accent);border-radius:8px;padding:14px">';
          html += '<div style="font-size:11px;color:var(--accent2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Trigger Keyword</div>';
          html += '<div style="font-size:20px;font-weight:700;color:var(--accent2)">' + esc(dm.trigger) + '</div>';
          html += '</div>';
        }
        if (dm.ack_message) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="font-size:11px;color:var(--green);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Instant Reply (when they comment)</div>';
          html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(dm.ack_message) + '</div>';
          html += '</div>';
        }
        if (dm.delivery_message) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="font-size:11px;color:var(--blue);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Delivery Message (with the guide)</div>';
          html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(dm.delivery_message) + '</div>';
          html += '</div>';
        }
        if (dm.follow_up) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="font-size:11px;color:var(--yellow);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Follow-up (24-48h later)</div>';
          html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(dm.follow_up) + '</div>';
          html += '</div>';
        }
        // Show any other fields not already covered
        const knownKeys = new Set(["trigger","ack_message","delivery_message","follow_up"]);
        for (const [k,v] of Object.entries(dm)) {
          if (!knownKeys.has(k) && v) {
            html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
            html += '<div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">' + esc(k.replace(/_/g, ' ')) + '</div>';
            html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(typeof v === 'string' ? v : JSON.stringify(v, null, 2)) + '</div>';
            html += '</div>';
          }
        }
        html += '</div>';
        html += '<button class="btn btn-dim" style="margin-top:12px;font-size:12px" onclick="copyDmFlow(this, \\'' + pid + '\\')">Copy All DM Messages</button>';
        html += '</div>';
      }
      if (p.image_prompts?.length) {
        const hasAnyImages = p.image_prompts.some(ip => ip.image_url);
        html += '<div id="img-' + pid + '" style="display:none">';
        // Generate Images button
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">';
        if (!hasAnyImages) {
          html += '<button class="btn btn-blue" id="gen-img-btn-' + pid + '" onclick="generateImages(\\'' + p.id + '\\', this)">Generate Images with AI</button>';
          html += '<span style="font-size:12px;color:var(--dim)">Uses fal.ai Flux Pro (~$0.03/image, ' + p.image_prompts.length + ' images)</span>';
        } else {
          html += '<button class="btn btn-dim" id="gen-img-btn-' + pid + '" onclick="generateImages(\\'' + p.id + '\\', this)">Regenerate Images</button>';
          html += '<span style="font-size:12px;color:var(--green)">Images generated</span>';
        }
        html += '</div>';
        // Progress bar placeholder
        html += '<div id="gen-img-progress-' + pid + '"></div>';
        // Image grid
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px">';
        for (const ip of p.image_prompts) {
          const promptText = ip.prompt_text || ip.detailed_prompt || '';
          const bestPlat = ip.best_platform || 'fal_ai';
          const platColors = { fal_ai: '#16a34a', midjourney: '#a855f7', gemini: '#3b82f6', dall_e: '#f97316' };
          const platLabels = { fal_ai: 'fal.ai', midjourney: 'Midjourney', gemini: 'Gemini', dall_e: 'DALL-E' };
          const platColor = platColors[bestPlat] || '#888';
          const platLabel = platLabels[bestPlat] || bestPlat;
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px">';
          // Header with platform badge
          html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">';
          html += '<div style="font-weight:600;font-size:14px;color:var(--accent2);flex:1">' + esc(ip.prompt_name || ip.visual_job || 'Image') + '</div>';
          html += '<span style="padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;background:' + platColor + '22;color:' + platColor + ';border:1px solid ' + platColor + '44" title="' + esc(ip.best_platform_reason || '') + '">' + platLabel + '</span>';
          html += '</div>';
          // Platform hint message if not fal_ai
          if (bestPlat !== 'fal_ai' && ip.best_platform_reason) {
            html += '<div style="font-size:12px;color:' + platColor + ';margin-bottom:8px;padding:6px 10px;background:' + platColor + '11;border-radius:6px">Try on ' + platLabel + ' - ' + esc(ip.best_platform_reason) + '</div>';
          }
          // Show image first if available
          if (ip.image_url) {
            html += '<div style="margin-bottom:12px;border-radius:8px;overflow:hidden;border:1px solid var(--border)">';
            html += '<img src="' + esc(ip.image_url) + '" style="width:100%;display:block" loading="lazy">';
            html += '</div>';
          }
          if (ip.visual_intent) html += '<div style="font-size:12px;color:var(--text);margin-bottom:8px;font-style:italic">' + esc(ip.visual_intent) + '</div>';
          html += '<div style="font-size:12px;color:var(--dim);margin-bottom:8px;display:flex;gap:12px;flex-wrap:wrap">';
          if (ip.mood) html += '<span>Mood: <strong>' + esc(ip.mood) + '</strong></span>';
          if (ip.aspect_ratio) html += '<span>Ratio: <strong>' + esc(ip.aspect_ratio) + '</strong></span>';
          if (ip.platform_fit) html += '<span>Platform: <strong>' + esc(ip.platform_fit) + '</strong></span>';
          if (ip.color_logic) html += '<span>Colors: ' + esc(String(ip.color_logic).slice(0, 60)) + '</span>';
          html += '</div>';
          // Prompt text always visible
          html += '<div style="font-size:12px;margin-top:8px"><strong style="color:var(--green)">Prompt:</strong></div>';
          html += '<div class="post-preview" style="font-size:12px;margin:4px 0 0;max-height:200px;white-space:pre-wrap;overflow-y:auto">' + esc(promptText) + '</div>';
          if (ip.negative_prompt) {
            html += '<div style="font-size:12px;margin-top:8px"><strong style="color:var(--red)">Negative:</strong></div>';
            html += '<div style="font-size:11px;color:var(--dim);margin-top:4px">' + esc(ip.negative_prompt) + '</div>';
          }
          if (ip.rationale) html += '<div style="font-size:11px;color:var(--dim);margin-top:8px;border-top:1px solid var(--border);padding-top:8px">Rationale: ' + esc(ip.rationale) + '</div>';
          // Copy buttons
          html += '<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">';
          html += '<button class="btn btn-dim" style="font-size:11px" onclick="copyImagePrompt(this)">Copy Prompt</button>';
          if (bestPlat !== 'fal_ai') {
            html += '<button class="btn btn-dim" style="font-size:11px;border-color:' + platColor + '44;color:' + platColor + '" onclick="copyForPlatform(this, \\'' + platLabel + '\\')">Copy for ' + platLabel + '</button>';
          }
          html += '</div>';
          html += '</div>';
        }
        html += '</div></div>';
      }
      // Actions
      html += '<div class="btn-group" style="margin-top:12px">';
      if (p.approval_status === 'draft') {
        html += '<button class="btn btn-green" onclick="approvePackage(\\'' + p.id + '\\')">Approve</button>';
        html += '<button class="btn btn-red" onclick="rejectPackage(\\'' + p.id + '\\')">Reject</button>';
      } else if (p.approval_status === 'approved') {
        html += '<span style="color:var(--green);font-weight:600;font-size:13px;padding:8px 0">Approved</span>';
      } else if (p.approval_status === 'rejected') {
        html += '<span style="color:var(--red);font-weight:600;font-size:13px;padding:8px 0">Rejected</span>';
        html += '<button class="btn btn-dim" onclick="resetPackageStatus(\\'' + p.id + '\\')">Reset to Draft</button>';
      }
      html += '<button class="btn btn-blue" onclick="exportPackage(\\'' + p.id + '\\')">Export</button>';
      html += '<button class="btn btn-dim" onclick="showFeedbackForm(\\'' + p.id + '\\', this)">Feedback</button>';
      html += '<button class="btn btn-dim" style="border-color:var(--accent)" onclick="showRevisedCopyForm(\\'' + p.id + '\\', this)">Edit & Submit Copy</button>';
      html += '<button class="btn btn-dim" style="border-color:var(--yellow);color:var(--yellow)" onclick="aiRevisePost(\\'' + p.id + '\\', \\'fb\\')">AI Revise FB</button>';
      html += '<button class="btn btn-dim" style="border-color:var(--yellow);color:var(--yellow)" onclick="aiRevisePost(\\'' + p.id + '\\', \\'li\\')">AI Revise LI</button>';
      html += '<button class="btn btn-dim" onclick="copyPost(\\'' + pid + '\\', this, \\'Facebook post\\')">Copy FB Post</button>';
      html += '<button class="btn btn-dim" onclick="copyPost(\\'li-' + pid + '\\', this, \\'LinkedIn post\\')">Copy LI Post</button>';
      if (p.is_archived) {
        html += '<button class="btn btn-dim" onclick="unarchivePackage(\\'' + p.id + '\\')">Unarchive</button>';
      } else {
        html += '<button class="btn btn-dim" onclick="archivePackage(\\'' + p.id + '\\')">Archive</button>';
      }
      html += '</div>';
      html += '</div>';
    }
    html += '</div>';
    document.getElementById('pkg-list').innerHTML = html;
  } catch (e) { document.getElementById('pkg-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function showPostTab(btn, id) {
  const card = btn.closest('.pkg-card');
  // Hide all tab content (wrapper divs with IDs and direct post-previews)
  card.querySelectorAll('[id^="fb-"],[id^="li-"],[id^="hooks-"],[id^="qa-"],[id^="img-"],[id^="dm-"]').forEach(el => {
    if (el.closest('.pkg-card') === card) el.style.display = 'none';
  });
  card.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const target = document.getElementById(id);
  if (target) target.style.display = '';
}

async function approvePackage(id) {
  try {
    await api('/content/packages/' + id + '/approve', { method: 'POST' });
    toast('Package approved!');
    await renderPackages();
  } catch (e) {
    toast('Approve failed: ' + e.message, false);
    console.error('Approve error:', e);
  }
}

async function rejectPackage(id) {
  try {
    await api('/content/packages/' + id + '/reject', { method: 'POST' });
    toast('Package rejected', false);
    await renderPackages();
  } catch (e) {
    toast('Reject failed: ' + e.message, false);
    console.error('Reject error:', e);
  }
}

async function archivePackage(id) {
  try {
    await api('/content/packages/' + id + '/archive', { method: 'POST' });
    toast('Package archived');
    await renderPackages();
  } catch (e) { toast('Archive failed: ' + e.message, false); }
}

async function unarchivePackage(id) {
  try {
    await api('/content/packages/' + id + '/unarchive', { method: 'POST' });
    toast('Package unarchived');
    await renderPackages();
  } catch (e) { toast('Unarchive failed: ' + e.message, false); }
}

async function archiveGuide(id) {
  try {
    await api('/content/guides/' + id + '/archive', { method: 'POST' });
    toast('Guide archived');
    await renderWeek();
  } catch (e) { toast('Archive failed: ' + e.message, false); }
}

async function unarchiveGuide(id) {
  try {
    await api('/content/guides/' + id + '/unarchive', { method: 'POST' });
    toast('Guide unarchived');
    await renderWeek();
  } catch (e) { toast('Unarchive failed: ' + e.message, false); }
}

async function resetPackageStatus(id) {
  try {
    await api('/content/packages/' + id, { method: 'PATCH', body: JSON.stringify({ approval_status: 'draft' }) });
    toast('Package reset to draft');
    await renderPackages();
  } catch (e) {
    toast('Reset failed: ' + e.message, false);
  }
}

async function exportPackage(id) {
  const result = await api('/content/packages/' + id + '/export?platform=manual', { method: 'POST' });
  const w = window.open('', '_blank');
  w.document.write('<pre style="font-family:monospace;white-space:pre-wrap;padding:20px;max-width:800px;margin:auto">' + JSON.stringify(result, null, 2) + '</pre>');
}

function copyDmFlow(btn, pid) {
  const container = document.getElementById('dm-' + pid);
  if (!container) return;
  // Collect all message texts
  const parts = [];
  container.querySelectorAll('div > div').forEach(card => {
    const label = card.querySelector('div:first-child');
    const text = card.querySelector('div:last-child');
    if (label && text && label !== text) {
      parts.push(label.textContent.trim() + ':\\n' + text.textContent.trim());
    }
  });
  clipCopy(parts.join('\\n\\n---\\n\\n'));
  btn.textContent = 'Copied!';
  btn.style.background = 'var(--green)';
  btn.style.color = '#000';
  setTimeout(() => { btn.textContent = 'Copy All DM Messages'; btn.style.background = ''; btn.style.color = ''; }, 2000);
  toast('DM flow copied to clipboard');
}

function copyImagePrompt(btn) {
  const card = btn.closest('div').closest('div[style*="background:#111318"]');
  const preview = card.querySelector('.post-preview');
  if (preview) {
    clipCopy(preview.textContent);
    btn.textContent = 'Copied!';
    btn.style.background = 'var(--green)';
    btn.style.color = '#000';
    setTimeout(() => { btn.textContent = 'Copy Prompt'; btn.style.background = ''; btn.style.color = ''; }, 2000);
    toast('Image prompt copied to clipboard');
  }
}

function copyForPlatform(btn, platformName) {
  const card = btn.closest('div').closest('div[style*="background:#111318"]');
  const preview = card.querySelector('.post-preview');
  if (preview) {
    clipCopy(preview.textContent);
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    btn.style.background = 'var(--green)';
    btn.style.color = '#000';
    setTimeout(() => { btn.textContent = orig; btn.style.background = ''; btn.style.color = ''; }, 2000);
    toast('Prompt copied for ' + platformName);
  }
}

async function generateImages(packageId, btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating...';
  btn.style.background = 'var(--yellow)';
  btn.style.color = '#000';

  // Show progress
  const pid = packageId.substring(0, 8);
  const progressEl = document.getElementById('gen-img-progress-' + pid) || btn.parentElement.nextElementSibling;
  if (progressEl) {
    progressEl.innerHTML = '<div style="background:#1e1b4b;border:1px solid var(--accent);border-radius:8px;padding:14px;margin-bottom:12px">' +
      '<div style="font-size:12px;color:var(--accent2);margin-bottom:8px">Generating images with fal.ai Flux Pro...</div>' +
      '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden">' +
      '<div style="height:100%;background:var(--accent2);width:30%;border-radius:2px"></div>' +
      '</div>' +
      '<div style="font-size:11px;color:var(--dim);margin-top:6px">This may take 15-30 seconds per image...</div>' +
      '</div>';
  }

  try {
    const resp = await fetch('/api/v1/content/packages/' + packageId + '/generate-images', { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Generation failed');
    }
    const data = await resp.json();
    const generated = data.results.filter(r => r.status === 'generated').length;
    const failed = data.results.filter(r => r.status === 'failed').length;

    btn.textContent = generated + ' images generated!';
    btn.style.background = 'var(--green)';
    btn.style.color = '#000';
    if (progressEl) progressEl.innerHTML = '';
    toast(generated + ' image(s) generated' + (failed ? ', ' + failed + ' failed' : ''));

    // Refresh packages and jump back to this package's Images tab
    const targetPkgId = packageId;
    setTimeout(async () => {
      await renderPackages();
      // Find the package card and switch to Images tab
      setTimeout(() => {
        const pid = targetPkgId.replace(/-/g, '');
        const imgTab = document.getElementById('img-' + pid);
        if (imgTab) {
          // Find and click the Images tab button
          const card = imgTab.closest('.pkg-card');
          if (card) {
            const imgBtn = Array.from(card.querySelectorAll('.tabs button')).find(b => b.textContent.startsWith('Images'));
            if (imgBtn) showPostTab(imgBtn, 'img-' + pid);
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.style.outline = '2px solid var(--green)';
            setTimeout(() => card.style.outline = '', 3000);
          }
        }
      }, 200);
    }, 500);
  } catch (e) {
    btn.textContent = 'Failed - try again';
    btn.style.background = 'var(--red)';
    btn.style.color = '#fff';
    if (progressEl) progressEl.innerHTML = '';
    toast('Image generation failed: ' + e.message);
    setTimeout(() => {
      btn.textContent = origText;
      btn.style.background = '';
      btn.style.color = '';
      btn.disabled = false;
    }, 3000);
  }
}

function clipCopy(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}
function copyPost(pid, btn, label) {
  // pid may be 'fb-xxx' or 'li-xxx' or just 'xxx' (defaults to fb)
  const el = document.getElementById(pid.startsWith('fb-') || pid.startsWith('li-') ? pid : 'fb-' + pid);
  if (el) {
    const preview = el.querySelector('.post-preview');
    clipCopy(preview ? preview.textContent : el.textContent);
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      btn.style.background = 'var(--green)';
      btn.style.color = '#000';
      setTimeout(() => { btn.textContent = orig; btn.style.background = ''; btn.style.color = ''; }, 2000);
    }
    toast((label || 'Post') + ' copied to clipboard');
  }
}

// CORPUS TAB
async function renderCorpus() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="section">
      <h2>Corpus Documents</h2>
      <div class="upload-zone" id="upload-zone" onclick="document.getElementById('file-input').click()">
        <input type="file" id="file-input" accept=".docx,.txt" style="display:none" onchange="uploadFile(this)">
        <div style="font-size:24px">+</div>
        <p>Click to upload DOCX or TXT file</p>
        <p style="font-size:11px;margin-top:4px">Auto-analyzes corpus (extracts examples, scores engagement, mines patterns)</p>
      </div>
      <div id="docs-list" style="margin-top:16px"><div class="empty">Loading...</div></div>
    </div>`;
  try {
    const docs = await api('/documents/');
    if (!docs.length) { document.getElementById('docs-list').innerHTML = '<div class="empty">No documents uploaded yet.</div>'; return; }
    let html = '<div class="docs-list">';
    for (const d of docs) {
      html += '<div class="doc-row">';
      html += '<div class="doc-info"><div class="doc-name">' + esc(d.file_name) + '</div>';
      html += '<div class="doc-meta">' + d.file_type + ' - ' + (d.pages || '?') + ' pages - ' + new Date(d.created_at).toLocaleDateString() + '</div></div>';
      html += '<button class="btn btn-dim" onclick="viewExamples(\\'' + d.id + '\\',\\'' + esc(d.file_name) + '\\')">View Examples</button>';
      html += '</div>';
    }
    html += '</div>';
    document.getElementById('docs-list').innerHTML = html;
  } catch (e) { document.getElementById('docs-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}

async function uploadFile(input) {
  const file = input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  document.getElementById('upload-zone').innerHTML = '<p>Uploading ' + file.name + '...</p>';
  try {
    const r = await fetch(API + '/documents/upload?auto_analyze=true', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.text();
      throw new Error('Server error ' + r.status + ': ' + err.slice(0, 200));
    }
    const d = await r.json();
    toast('Uploaded: ' + d.file_name + ' (' + d.pages + ' pages). Analysis running in background.');
    renderCorpus();
  } catch (e) {
    toast('Upload failed: ' + e.message, false);
    document.getElementById('upload-zone').innerHTML = '<input type="file" id="file-input" accept=".docx,.txt" style="display:none" onchange="uploadFile(this)"><div style="font-size:24px">+</div><p>Click to upload DOCX or TXT file</p><p style="font-size:11px;margin-top:4px">Auto-analyzes corpus</p>';
    renderCorpus();
  }
}

async function viewExamples(docId, name) {
  try {
    const examples = await api('/documents/' + docId + '/examples');
    // Fetch full creator profiles for name + style data
    let creatorMap = {};
    try { const creators = await api('/profiles/creators'); for (const c of creators) creatorMap[c.id] = c; } catch(e) {}
    const w = window.open('', '_blank');
    let h = '<html><head><style>body{font-family:-apple-system,sans-serif;padding:20px;max-width:1000px;margin:auto;background:#0f1117;color:#e4e4e7}h1{font-size:20px;margin-bottom:16px}.ex{border:1px solid #2a2d3a;border-radius:10px;padding:20px;margin:16px 0;background:#1a1d27}.meta{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:12px;color:#71717a}.badge{background:#2a2d3a;padding:2px 8px;border-radius:4px;font-size:11px}.score-box{display:inline-block;background:#6366f1;color:#fff;padding:4px 10px;border-radius:6px;font-weight:700;font-size:14px;margin-right:8px}.post-text{background:#0f1117;border:1px solid #2a2d3a;border-radius:6px;padding:12px;margin:8px 0;white-space:pre-wrap;font-size:13px;line-height:1.6;direction:rtl;text-align:right;max-height:200px;overflow-y:auto}.section-label{font-size:11px;color:#6366f1;text-transform:uppercase;letter-spacing:.5px;margin-top:12px;margin-bottom:4px}.tags{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0}.tag{background:#1e3a5f;color:#60a5fa;padding:2px 6px;border-radius:3px;font-size:11px}.tag.topic{background:#1e3a2f;color:#4ade80}.engagement{display:flex;gap:16px;margin-top:8px;font-size:12px;color:#71717a}.expand-btn{background:none;border:1px solid #2a2d3a;color:#818cf8;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;margin-top:6px}.inspire-btn{background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin-top:10px;transition:opacity .2s}.inspire-btn:hover{opacity:.85}.inspire-btn:disabled{opacity:.5;cursor:not-allowed}.inspire-status{font-size:11px;color:#a78bfa;margin-top:6px;min-height:16px}</style></head><body>';
    // Embed examples data for the inspire function
    h += '<script>const EXAMPLES_DATA = ' + JSON.stringify(examples.map(ex => ({
      id: ex.id, creator_id: ex.creator_id, post_text_raw: ex.post_text_raw,
      hook_type: ex.hook_type, body_structure: ex.body_structure, story_arc: ex.story_arc,
      cta_type: ex.cta_type, tone_tags: ex.tone_tags, topic_tags: ex.topic_tags,
      hook_text: ex.hook_text, cta_text: ex.cta_text
    }))) + ';\\n';
    h += 'const CREATOR_MAP = ' + JSON.stringify(Object.fromEntries(
      Object.entries(creatorMap).map(([id, c]) => [id, {
        creator_name: c.creator_name, style_notes: c.style_notes,
        allowed_influence_weight: c.allowed_influence_weight, top_patterns: c.top_patterns
      }])
    )) + ';\\n';
    h += `
async function inspireFromExample(idx) {
  const ex = EXAMPLES_DATA[idx];
  if (!ex || !ex.post_text_raw) { alert('No post text available'); return; }
  const btn = document.getElementById('inspire-btn-' + idx);
  const status = document.getElementById('inspire-status-' + idx);
  btn.disabled = true;
  btn.textContent = 'Starting pipeline...';
  status.textContent = 'Launching daily_content pipeline with creator inspiration...';
  const creator = CREATOR_MAP[ex.creator_id] || {};
  const wordCount = ex.post_text_raw.trim().split(/\\s+/).length;
  const body = {
    workflow: 'daily_content',
    context: {
      day_of_week: new Date().getDay() === 0 ? 4 : Math.min(new Date().getDay() - 1, 4),
      creator_inspiration: {
        creator_name: creator.creator_name || 'Unknown',
        post_text: ex.post_text_raw,
        hook_text: ex.hook_text || '',
        hook_type: ex.hook_type || '',
        body_structure: ex.body_structure || '',
        story_arc: ex.story_arc || '',
        cta_type: ex.cta_type || '',
        tone_tags: ex.tone_tags || [],
        topic_tags: ex.topic_tags || [],
        style_notes: creator.style_notes || '',
        influence_weight: Math.round((creator.allowed_influence_weight || 0.2) * 100),
        word_count: wordCount
      }
    }
  };
  try {
    const r = await fetch('/api/v1/pipeline/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!r.ok) { const err = await r.text(); throw new Error(err.slice(0, 200)); }
    const data = await r.json();
    const runId = data.run_id;
    btn.textContent = 'Pipeline running...';
    status.textContent = 'Run ID: ' + runId.substring(0, 8) + ' - polling status...';
    // Poll status
    const poll = setInterval(async () => {
      try {
        const sr = await fetch('/api/v1/pipeline/' + runId + '/status');
        const st = await sr.json();
        const steps = st.step_status || {};
        const running = Object.entries(steps).filter(([,v]) => v === 'running').map(([k]) => k);
        const done = Object.entries(steps).filter(([,v]) => v === 'completed').length;
        const total = Object.keys(steps).length;
        if (running.length) status.textContent = 'Running: ' + running.join(', ') + ' (' + done + '/' + total + ' done)';
        if (st.status === 'completed') {
          clearInterval(poll);
          btn.textContent = 'Done! View in dashboard';
          btn.disabled = false;
          btn.onclick = () => { window.opener?.location.reload(); };
          status.textContent = 'Pipeline completed. All agents finished. Click button to refresh dashboard.';
          status.style.color = '#4ade80';
        } else if (st.status === 'failed') {
          clearInterval(poll);
          btn.textContent = 'Failed';
          btn.disabled = false;
          status.textContent = 'Error: ' + (st.error_message || 'Unknown error');
          status.style.color = '#ef4444';
        }
      } catch(e) { status.textContent = 'Polling error: ' + e.message; }
    }, 3000);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Inspire Post';
    status.textContent = 'Error: ' + e.message;
    status.style.color = '#ef4444';
  }
}
<\\/script>`;
    h += '<h1>' + name + ' - ' + examples.length + ' examples</h1>';
    for (let i = 0; i < examples.length; i++) {
      const ex = examples[i];
      const creatorObj = creatorMap[ex.creator_id];
      const creator = creatorObj ? creatorObj.creator_name : 'Unknown';
      h += '<div class="ex">';
      // Header row with score and classification
      h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
      h += '<div style="font-weight:600;font-size:14px">#' + (i+1) + ' - ' + creator + '</div>';
      if (ex.final_score != null) h += '<div class="score-box">' + ex.final_score.toFixed(2) + '</div>';
      else if (ex.raw_score != null) h += '<div class="score-box" style="background:#71717a">Raw: ' + ex.raw_score.toFixed(2) + '</div>';
      h += '</div>';
      // Word count
      const wordCount = ex.post_text_raw ? ex.post_text_raw.trim().split(/\\s+/).length : 0;
      if (wordCount > 0) h += '<div style="font-size:11px;color:#71717a;margin-bottom:8px">' + wordCount + ' words</div>';
      // Classification badges
      h += '<div class="meta">';
      if (ex.hook_type) h += '<span class="badge">Hook: ' + ex.hook_type + '</span>';
      if (ex.body_structure) h += '<span class="badge">Body: ' + ex.body_structure + '</span>';
      if (ex.story_arc) h += '<span class="badge">Arc: ' + ex.story_arc + '</span>';
      if (ex.tension_type) h += '<span class="badge">Tension: ' + ex.tension_type + '</span>';
      if (ex.cta_type) h += '<span class="badge">CTA: ' + ex.cta_type + '</span>';
      if (ex.visual_type) h += '<span class="badge">Visual: ' + ex.visual_type + '</span>';
      h += '</div>';
      // Hook text
      if (ex.hook_text) {
        h += '<div class="section-label">Hook</div>';
        h += '<div style="font-size:13px;direction:rtl;text-align:right;padding:6px 0;border-bottom:1px solid #2a2d3a">' + ex.hook_text + '</div>';
      }
      // Full post text (collapsible)
      if (ex.post_text_raw) {
        h += '<div class="section-label">Full Post</div>';
        h += '<div class="post-text">' + ex.post_text_raw + '</div>';
      }
      // CTA text
      if (ex.cta_text) {
        h += '<div class="section-label">CTA</div>';
        h += '<div style="font-size:13px;direction:rtl;text-align:right;padding:6px 0;color:#eab308">' + ex.cta_text + '</div>';
      }
      // Tags
      if (ex.tone_tags?.length || ex.topic_tags?.length) {
        h += '<div style="margin-top:8px">';
        if (ex.tone_tags?.length) { h += '<div class="tags">'; for (const t of ex.tone_tags) h += '<span class="tag">' + t + '</span>'; h += '</div>'; }
        if (ex.topic_tags?.length) { h += '<div class="tags">'; for (const t of ex.topic_tags) h += '<span class="tag topic">' + t + '</span>'; h += '</div>'; }
        h += '</div>';
      }
      // Engagement data
      h += '<div class="engagement">';
      h += '<span>Confidence: ' + (ex.engagement_confidence || '?') + '</span>';
      if (ex.visible_comments != null) h += '<span>Comments: ' + ex.visible_comments + '</span>';
      if (ex.visible_shares != null) h += '<span>Shares: ' + ex.visible_shares + '</span>';
      h += '</div>';
      // Inspire Post button
      if (ex.post_text_raw) {
        h += '<div style="margin-top:12px;padding-top:10px;border-top:1px solid #2a2d3a">';
        h += '<button class="inspire-btn" id="inspire-btn-' + i + '" onclick="inspireFromExample(' + i + ')">Inspire Post</button>';
        h += '<div class="inspire-status" id="inspire-status-' + i + '">Generate a new post inspired by this creator\\\'s style</div>';
        h += '</div>';
      }
      h += '</div>';
    }
    w.document.write(h + '</body></html>');
  } catch (e) { toast('Error: ' + e.message, false); }
}

// VOICE PROFILE TAB
async function renderVoice() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Founder Voice Profiles</h2><div id="voice-list"><div class="empty">Loading...</div></div></div>';
  try {
    const profiles = await api('/profiles/founder-voice');
    if (!profiles.length) { document.getElementById('voice-list').innerHTML = '<div class="empty">No voice profiles yet. Extract from a book via Corpus tab.</div>'; return; }
    let html = '';
    for (const p of profiles) {
      html += '<div class="voice-profile">';
      html += '<h4>Profile from: ' + (p.source_document_ids?.join(', ') || 'unknown').substring(0, 36) + '...</h4>';
      // Tone range bars
      if (p.tone_range) {
        html += '<div style="margin:8px 0">';
        for (const [k, v] of Object.entries(p.tone_range)) {
          html += '<div class="tone-bar"><span class="name">' + k + '</span><div class="bar" style="width:' + (v * 10) + '%"></div><span>' + v + '/10</span></div>';
        }
        html += '</div>';
      }
      if (p.humor_type) html += '<div style="font-size:13px;margin:4px 0">Humor: <strong>' + p.humor_type + '</strong></div>';
      if (p.values_and_beliefs?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Core Values (' + p.values_and_beliefs.length + ')</div>';
        html += '<div class="voice-tags">';
        p.values_and_beliefs.slice(0, 8).forEach(v => html += '<span class="voice-tag">' + esc(v.substring(0, 60)) + '</span>');
        if (p.values_and_beliefs.length > 8) html += '<span class="voice-tag">+' + (p.values_and_beliefs.length - 8) + ' more</span>';
        html += '</div></div>';
      }
      if (p.metaphor_families?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Metaphor Families</div>';
        html += '<div class="voice-tags">';
        p.metaphor_families.forEach(m => html += '<span class="voice-tag">' + esc(m) + '</span>');
        html += '</div></div>';
      }
      if (p.taboos?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Taboos</div>';
        html += '<div class="voice-tags">';
        p.taboos.slice(0, 6).forEach(t => html += '<span class="voice-tag" style="background:#2d0000;color:#fecaca">' + esc(t.substring(0, 50)) + '</span>');
        html += '</div></div>';
      }
      if (p.vocabulary_signature?.phrases?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Signature Phrases (' + p.vocabulary_signature.phrases.length + ')</div>';
        html += '<div class="voice-tags">';
        p.vocabulary_signature.phrases.slice(0, 10).forEach(ph => html += '<span class="voice-tag" style="background:#1e1b4b;color:#c7d2fe">' + esc(ph) + '</span>');
        if (p.vocabulary_signature.phrases.length > 10) html += '<span class="voice-tag">+' + (p.vocabulary_signature.phrases.length - 10) + ' more</span>';
        html += '</div></div>';
      }
      html += '<div style="font-size:11px;color:var(--dim);margin-top:8px">Created: ' + new Date(p.created_at).toLocaleString() + '</div>';
      html += '</div>';
    }
    document.getElementById('voice-list').innerHTML = html;
  } catch (e) { document.getElementById('voice-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}

// CREATORS TAB
async function renderCreators() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Creator Profiles</h2><div id="creators-list"><div class="empty">Loading...</div></div></div>';
  try {
    const creators = await api('/profiles/creators');
    if (!creators.length) { document.getElementById('creators-list').innerHTML = '<div class="empty">No creators configured.</div>'; return; }
    let html = '<div class="grid">';
    for (const c of creators) {
      html += '<div class="card">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center"><h3 style="text-transform:none">' + esc(c.creator_name) + '</h3>';
      html += '<span style="font-size:20px;font-weight:700;color:var(--accent)">' + ((c.allowed_influence_weight || 0.2) * 100).toFixed(0) + '%</span></div>';
      if (c.style_notes) html += '<p style="font-size:13px;color:var(--dim);margin-top:8px">' + esc(c.style_notes) + '</p>';
      if (c.top_patterns?.length) {
        html += '<div style="margin-top:8px"><div class="voice-tags">';
        c.top_patterns.forEach(p => html += '<span class="voice-tag">' + p + '</span>');
        html += '</div></div>';
      }
      if (c.voice_axes && Object.keys(c.voice_axes).length) {
        html += '<div style="margin-top:8px">';
        for (const [k, v] of Object.entries(c.voice_axes)) {
          html += '<div class="tone-bar"><span class="name">' + k + '</span><div class="bar" style="width:' + (v * 10) + '%;background:var(--blue)"></div><span>' + v + '</span></div>';
        }
        html += '</div>';
      } else {
        html += '<div style="margin-top:12px;padding:12px;border:1px dashed #2a2d3a;border-radius:6px;text-align:center;color:#71717a;font-size:12px">No voice axes data yet.<br><button class="btn btn-primary" style="margin-top:8px;padding:6px 14px;font-size:12px" onclick="analyzeVoice(\\'' + c.id + '\\')">Analyze Voice from Posts</button></div>';
      }
      html += '</div>';
    }
    html += '</div>';
    document.getElementById('creators-list').innerHTML = html;
  } catch (e) { document.getElementById('creators-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}

async function analyzeVoice(creatorId) {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Analyzing...';
  try {
    await api('/profiles/creators/' + creatorId + '/analyze-voice', { method: 'POST' });
    toast('Voice analysis complete!');
    renderCreators();
  } catch (e) {
    toast('Analysis failed: ' + e.message, false);
    btn.disabled = false;
    btn.textContent = 'Analyze Voice from Posts';
  }
}

// AGENTS TAB
const MODEL_LABELS = {
  'claude-haiku-4-5-20251001': 'Haiku 4.5',
  'claude-sonnet-4-20250514': 'Sonnet 4',
  'claude-opus-4-20250514': 'Opus 4',
};
const MODEL_IDS = Object.keys(MODEL_LABELS);
const MODEL_COLORS = {
  'claude-haiku-4-5-20251001': '#22c55e',
  'claude-sonnet-4-20250514': '#6366f1',
  'claude-opus-4-20250514': '#f59e0b',
};
const MODEL_COSTS = {
  'claude-haiku-4-5-20251001': '$0.80/1M in, $4/1M out',
  'claude-sonnet-4-20250514': '$3/1M in, $15/1M out',
  'claude-opus-4-20250514': '$15/1M in, $75/1M out',
};

async function renderAgents() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Agent Model Configuration</h2><p style="color:var(--dim);font-size:13px;margin-bottom:16px">Change which LLM model each agent uses. Changes take effect immediately (no restart needed).</p><div id="agents-list"><div class="empty">Loading...</div></div></div>';
  try {
    const agents = await api('/admin/agents');
    let html = '<div style="display:flex;flex-direction:column;gap:12px">';
    for (const a of agents) {
      const color = MODEL_COLORS[a.model] || 'var(--dim)';
      const label = MODEL_LABELS[a.model] || a.model;
      html += '<div class="card" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:16px 20px">';
      html += '<div style="flex:1;min-width:200px">';
      html += '<div style="font-weight:600;font-size:15px">' + a.name.replace(/_/g, ' ') + '</div>';
      html += '<div style="font-size:12px;color:var(--dim)">' + a.class + '</div>';
      html += '</div>';
      html += '<div style="display:flex;gap:6px;align-items:center">';
      for (const mid of MODEL_IDS) {
        const isActive = a.model === mid;
        const mcolor = MODEL_COLORS[mid];
        const mlabel = MODEL_LABELS[mid];
        html += '<button class="btn" style="' + (isActive ? 'background:' + mcolor + ';color:#000;font-weight:700' : 'background:var(--border);color:var(--dim)') + '" onclick="setAgentModel(\\'' + a.name + '\\',\\'' + mid + '\\')" title="' + MODEL_COSTS[mid] + '">' + mlabel + '</button>';
      }
      html += '</div>';
      html += '</div>';
    }
    html += '</div>';
    // Cost legend
    html += '<div class="card" style="margin-top:16px"><h3>Model Cost Reference</h3><div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:8px">';
    for (const mid of MODEL_IDS) {
      html += '<div style="font-size:13px"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + MODEL_COLORS[mid] + ';margin-right:6px"></span><strong>' + MODEL_LABELS[mid] + '</strong>: ' + MODEL_COSTS[mid] + '</div>';
    }
    html += '</div></div>';
    document.getElementById('agents-list').innerHTML = html;
  } catch (e) { document.getElementById('agents-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}

async function setAgentModel(agent, model) {
  try {
    const r = await api('/admin/agents/' + agent + '/model', { method: 'PATCH', body: JSON.stringify({ model }) });
    toast(r.agent.replace(/_/g, ' ') + ' switched to ' + MODEL_LABELS[model]);
    renderAgents();
  } catch (e) { toast('Failed: ' + e.message, false); }
}

// COSTS TAB
async function renderCosts() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Cost Dashboard</h2><div id="costs-content"><div class="empty">Loading cost data...</div></div></div>';
  try {
    const [daily, monthly, byAgent, modelDist, perPost] = await Promise.all([
      api('/costs/daily'),
      api('/costs/monthly'),
      api('/costs/by-agent'),
      api('/costs/model-distribution'),
      api('/costs/per-post'),
    ]);
    let html = '';
    // Top cards row
    html += '<div class="grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px">';
    // Today's spending
    html += '<div class="card"><h3>Today</h3>';
    html += '<div class="value" style="color:' + (daily.budget_pct_used > 80 ? 'var(--red)' : daily.budget_pct_used > 50 ? 'var(--yellow)' : 'var(--green)') + '">$' + daily.total_cost_usd.toFixed(2) + '</div>';
    html += '<div class="sub">Budget: $' + daily.daily_budget_usd.toFixed(2) + ' (' + daily.budget_pct_used.toFixed(0) + '% used)</div>';
    html += '<div style="height:6px;background:var(--border);border-radius:3px;margin-top:8px;overflow:hidden"><div style="height:100%;background:' + (daily.budget_pct_used > 80 ? 'var(--red)' : daily.budget_pct_used > 50 ? 'var(--yellow)' : 'var(--green)') + ';width:' + Math.min(daily.budget_pct_used, 100) + '%;border-radius:3px"></div></div>';
    html += '</div>';
    // This month
    html += '<div class="card"><h3>This Month</h3>';
    html += '<div class="value" style="color:' + (monthly.budget_pct_used > 80 ? 'var(--red)' : monthly.budget_pct_used > 50 ? 'var(--yellow)' : 'var(--green)') + '">$' + monthly.total_cost_usd.toFixed(2) + '</div>';
    html += '<div class="sub">Budget: $' + monthly.monthly_budget_usd.toFixed(2) + ' (' + monthly.budget_pct_used.toFixed(0) + '% used)</div>';
    html += '<div style="height:6px;background:var(--border);border-radius:3px;margin-top:8px;overflow:hidden"><div style="height:100%;background:' + (monthly.budget_pct_used > 80 ? 'var(--red)' : monthly.budget_pct_used > 50 ? 'var(--yellow)' : 'var(--green)') + ';width:' + Math.min(monthly.budget_pct_used, 100) + '%;border-radius:3px"></div></div>';
    html += '</div>';
    // Cost per post
    html += '<div class="card"><h3>Avg Cost/Post</h3>';
    html += '<div class="value">$' + perPost.avg_cost_per_run.toFixed(2) + '</div>';
    html += '<div class="sub">' + perPost.total_runs + ' runs in ' + perPost.period_days + ' days</div>';
    if (perPost.total_runs > 0) html += '<div class="sub">Range: $' + perPost.min_cost.toFixed(2) + ' - $' + perPost.max_cost.toFixed(2) + '</div>';
    html += '</div>';
    // Total spent
    html += '<div class="card"><h3>Total Spent (30d)</h3>';
    html += '<div class="value">$' + perPost.total_cost.toFixed(2) + '</div>';
    html += '<div class="sub">' + perPost.total_runs + ' pipeline runs</div>';
    html += '</div>';
    html += '</div>';
    // Agent breakdown table
    html += '<div class="card" style="margin-bottom:16px"><h3>Agent Cost Breakdown (' + byAgent.date + ')</h3>';
    if (byAgent.agents.length) {
      html += '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">';
      html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Agent</th><th style="text-align:right;padding:8px 12px">Cost</th><th style="text-align:right;padding:8px 12px">Input Tokens</th><th style="text-align:right;padding:8px 12px">Output Tokens</th><th style="text-align:right;padding:8px 12px">Calls</th></tr>';
      let totalCost = 0;
      for (const a of byAgent.agents) {
        totalCost += a.cost_usd;
        html += '<tr style="border-bottom:1px solid var(--border)">';
        html += '<td style="padding:8px 12px;font-weight:500">' + a.agent.replace(/_/g, ' ') + '</td>';
        html += '<td style="text-align:right;padding:8px 12px;color:var(--accent2);font-weight:600">$' + a.cost_usd.toFixed(4) + '</td>';
        html += '<td style="text-align:right;padding:8px 12px;color:var(--dim)">' + (a.input_tokens || 0).toLocaleString() + '</td>';
        html += '<td style="text-align:right;padding:8px 12px;color:var(--dim)">' + (a.output_tokens || 0).toLocaleString() + '</td>';
        html += '<td style="text-align:right;padding:8px 12px">' + a.call_count + '</td>';
        html += '</tr>';
      }
      html += '<tr style="font-weight:700"><td style="padding:8px 12px">Total</td><td style="text-align:right;padding:8px 12px;color:var(--green)">$' + totalCost.toFixed(4) + '</td><td colspan="3"></td></tr>';
      html += '</table>';
    } else {
      html += '<div class="empty" style="padding:16px">No cost data for today. Run a pipeline to see costs.</div>';
    }
    html += '</div>';
    // Model distribution
    html += '<div class="card"><h3>Model Distribution (Last ' + modelDist.period_days + ' Days)</h3>';
    if (modelDist.models.length) {
      const totalModelCost = modelDist.models.reduce((s, m) => s + m.cost_usd, 0);
      html += '<div style="display:flex;gap:16px;margin-top:12px;flex-wrap:wrap">';
      for (const m of modelDist.models) {
        const pct = totalModelCost > 0 ? (m.cost_usd / totalModelCost * 100) : 0;
        const color = MODEL_COLORS[m.model] || 'var(--accent)';
        const label = MODEL_LABELS[m.model] || m.model;
        html += '<div style="flex:1;min-width:200px;background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px">';
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="width:12px;height:12px;border-radius:50%;background:' + color + ';display:inline-block"></span><span style="font-weight:600">' + label + '</span></div>';
        html += '<div style="font-size:22px;font-weight:700;color:' + color + '">$' + m.cost_usd.toFixed(2) + '</div>';
        html += '<div style="font-size:12px;color:var(--dim);margin-top:4px">' + pct.toFixed(0) + '% of total - ' + m.call_count + ' calls</div>';
        html += '<div style="font-size:12px;color:var(--dim)">' + (m.input_tokens || 0).toLocaleString() + ' in / ' + (m.output_tokens || 0).toLocaleString() + ' out</div>';
        html += '</div>';
      }
      html += '</div>';
    } else {
      html += '<div class="empty" style="padding:16px">No model usage data yet.</div>';
    }
    html += '</div>';
    // Optimization Recommendations
    try {
      const optRecs = await api('/costs/optimization-recommendations?days=7');
      html += '<div class="card" style="margin-top:16px"><h3 style="display:flex;align-items:center;justify-content:space-between">Optimization Recommendations (7d)<span style="font-size:13px;font-weight:600;color:var(--green)">Potential savings: $' + optRecs.total_potential_savings_usd.toFixed(2) + '</span></h3>';
      if (optRecs.recommendations.length) {
        const typeIcon = { model_downgrade: 'arrow-down', improve_caching: 'zap', batch_api: 'layers' };
        const typeColor = { model_downgrade: 'var(--accent2)', improve_caching: 'var(--yellow)', batch_api: 'var(--blue)' };
        const typeLabel = { model_downgrade: 'Model Downgrade', improve_caching: 'Cache Improvement', batch_api: 'Batch API' };
        html += '<div style="display:flex;flex-direction:column;gap:10px;margin-top:14px">';
        for (const rec of optRecs.recommendations) {
          const color = typeColor[rec.type] || 'var(--accent)';
          const label = typeLabel[rec.type] || rec.type;
          html += '<div style="display:flex;align-items:flex-start;gap:14px;background:#111318;border:1px solid var(--border);border-left:3px solid ' + color + ';border-radius:8px;padding:14px 16px">';
          html += '<div style="min-width:fit-content"><span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;background:' + color + '22;color:' + color + ';white-space:nowrap">' + label + '</span></div>';
          html += '<div style="flex:1"><div style="font-size:13px;color:var(--text);line-height:1.5">' + esc(rec.message) + '</div>';
          html += '<div style="font-size:12px;color:var(--dim);margin-top:4px">Agent: <span style="color:var(--text);font-weight:500">' + (rec.agent || '').replace(/_/g, ' ') + '</span>';
          if (rec.current_model) html += ' - Current: <span style="color:var(--dim)">' + (MODEL_LABELS[rec.current_model] || rec.current_model) + '</span>';
          if (rec.current_cache_rate != null) html += ' - Cache rate: <span style="color:var(--yellow)">' + (rec.current_cache_rate * 100).toFixed(0) + '%</span>';
          html += '</div></div>';
          html += '<div style="text-align:right;min-width:70px"><div style="font-size:16px;font-weight:700;color:var(--green)">$' + rec.savings_usd.toFixed(2) + '</div><div style="font-size:11px;color:var(--dim)">savings</div></div>';
          html += '</div>';
        }
        html += '</div>';
      } else {
        html += '<div style="padding:20px;text-align:center;color:var(--dim);font-size:14px">No optimization recommendations right now. Costs look efficient.</div>';
      }
      html += '</div>';
    } catch {}
    // Recent pipeline runs (from pipeline/runs endpoint)
    try {
      const runs = await api('/pipeline/runs?limit=10');
      if (runs.length) {
        html += '<div class="card" style="margin-top:16px"><h3>Recent Pipeline Runs</h3>';
        html += '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">';
        html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Run ID</th><th style="text-align:left;padding:8px 12px">Workflow</th><th style="text-align:left;padding:8px 12px">Status</th><th style="text-align:left;padding:8px 12px">Day</th><th style="text-align:left;padding:8px 12px">Started</th><th style="text-align:left;padding:8px 12px">Error</th></tr>';
        for (const r of runs) {
          const stColor = r.status === 'completed' ? 'var(--green)' : r.status === 'failed' ? 'var(--red)' : 'var(--blue)';
          html += '<tr style="border-bottom:1px solid var(--border)">';
          html += '<td style="padding:8px 12px;font-family:monospace;font-size:12px">' + r.run_id.substring(0, 8) + '</td>';
          html += '<td style="padding:8px 12px">' + r.workflow + '</td>';
          html += '<td style="padding:8px 12px;color:' + stColor + ';font-weight:600">' + r.status + '</td>';
          html += '<td style="padding:8px 12px">' + (r.day_of_week != null ? DAY_NAMES[r.day_of_week] || r.day_of_week : '-') + '</td>';
          html += '<td style="padding:8px 12px;color:var(--dim)">' + (r.started_at ? new Date(r.started_at).toLocaleString() : '-') + '</td>';
          html += '<td style="padding:8px 12px;color:var(--red);font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(r.error_message || '') + '">' + esc((r.error_message || '').substring(0, 80)) + '</td>';
          html += '</tr>';
        }
        html += '</table></div>';
      }
    } catch {}
    document.getElementById('costs-content').innerHTML = html;
  } catch (e) {
    document.getElementById('costs-content').innerHTML = '<div class="empty">Error loading costs: ' + e.message + '</div>';
  }
}

// FEEDBACK FORM for packages
const FEEDBACK_TAGS = [
  'hook_too_aggressive', 'hook_too_weak', 'thesis_unclear', 'thesis_off_brand',
  'cta_unfulfillable', 'cta_too_pushy', 'tone_mismatch', 'too_long', 'too_short',
  'factual_error', 'formatting_issue', 'image_mismatch', 'dm_flow_weak',
  'great_hook', 'strong_thesis', 'perfect_tone', 'good_images'
];

function showFeedbackForm(packageId, btn) {
  const existing = document.getElementById('feedback-form-' + packageId);
  if (existing) { existing.remove(); return; }
  let html = '<div id="feedback-form-' + packageId + '" style="background:#111318;border:1px solid var(--accent);border-radius:8px;padding:16px;margin-top:12px">';
  html += '<div style="font-size:14px;font-weight:600;color:var(--accent2);margin-bottom:12px">Package Feedback</div>';
  html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">';
  for (const tag of FEEDBACK_TAGS) {
    const isPositive = tag.startsWith('great_') || tag.startsWith('strong_') || tag.startsWith('perfect_') || tag.startsWith('good_');
    html += '<label style="display:flex;align-items:center;gap:4px;padding:4px 10px;border:1px solid var(--border);border-radius:4px;font-size:12px;cursor:pointer;background:var(--card)">';
    html += '<input type="checkbox" class="fb-tag" value="' + tag + '" style="accent-color:' + (isPositive ? 'var(--green)' : 'var(--yellow)') + '"> ';
    html += '<span style="color:' + (isPositive ? 'var(--green)' : 'var(--text)') + '">' + tag.replace(/_/g, ' ') + '</span>';
    html += '</label>';
  }
  html += '</div>';
  html += '<textarea id="fb-notes-' + packageId + '" placeholder="Additional notes (optional)..." style="width:100%;height:60px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px;font-size:13px;resize:vertical"></textarea>';
  html += '<div style="display:flex;gap:8px;margin-top:8px">';
  html += '<select id="fb-action-' + packageId + '" style="padding:6px 10px"><option value="approved">Approved</option><option value="revised">Revised</option><option value="rejected">Rejected</option></select>';
  html += '<button class="btn btn-primary" onclick="submitFeedback(\\'' + packageId + '\\')">Submit Feedback</button>';
  html += '<button class="btn btn-dim" onclick="document.getElementById(\\'feedback-form-' + packageId + '\\').remove()">Cancel</button>';
  html += '</div></div>';
  btn.closest('.pkg-card').insertAdjacentHTML('beforeend', html);
}

async function submitFeedback(packageId) {
  const form = document.getElementById('feedback-form-' + packageId);
  const tags = Array.from(form.querySelectorAll('.fb-tag:checked')).map(c => c.value);
  const notes = document.getElementById('fb-notes-' + packageId).value;
  const action = document.getElementById('fb-action-' + packageId).value;
  try {
    await api('/feedback/', {
      method: 'POST',
      body: JSON.stringify({
        package_id: packageId,
        feedback_tags: tags.length ? tags : null,
        feedback_notes: notes || null,
        action_taken: action,
      }),
    });
    toast('Feedback submitted');
    form.remove();
    renderPackages();
  } catch (e) { toast('Feedback failed: ' + e.message, false); }
}

// REVISED COPY FORM
function showRevisedCopyForm(packageId, btn) {
  const existing = document.getElementById('revised-form-' + packageId);
  if (existing) { existing.remove(); return; }
  // Find the package data from the card
  const card = btn.closest('.pkg-card');
  const fbDiv = card.querySelector('[id^="fb-"]');
  const liDiv = card.querySelector('[id^="li-"]');
  const fbText = fbDiv ? fbDiv.querySelector('.post-preview')?.textContent || '' : '';
  const liText = liDiv ? liDiv.querySelector('.post-preview')?.textContent || '' : '';
  const fbWords = fbText.trim().split(/\\s+/).length;
  const liWords = liText.trim().split(/\\s+/).length;
  let html = '<div id="revised-form-' + packageId + '" style="background:#111318;border:1px solid var(--accent);border-radius:8px;padding:16px;margin-top:12px">';
  html += '<div style="font-size:14px;font-weight:600;color:var(--accent2);margin-bottom:4px">Submit Revised Copy</div>';
  html += '<div style="font-size:12px;color:var(--dim);margin-bottom:12px">Paste what you actually published. The system learns from your edits to match your voice.</div>';
  // Facebook
  html += '<div style="margin-bottom:12px">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><label style="font-size:13px;font-weight:600;color:var(--green)">Facebook Post</label><span id="rev-fb-wc-' + packageId + '" style="font-size:11px;color:var(--dim)">' + fbWords + ' words</span></div>';
  html += '<textarea id="rev-fb-' + packageId + '" style="width:100%;min-height:200px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px;font-size:13px;resize:vertical;line-height:1.5" oninput="updateWordCount(this, \\'rev-fb-wc-' + packageId + '\\')">' + esc(fbText) + '</textarea>';
  html += '</div>';
  // LinkedIn
  html += '<div style="margin-bottom:12px">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><label style="font-size:13px;font-weight:600;color:var(--blue, #3b82f6)">LinkedIn Post</label><span id="rev-li-wc-' + packageId + '" style="font-size:11px;color:var(--dim)">' + liWords + ' words</span></div>';
  html += '<textarea id="rev-li-' + packageId + '" style="width:100%;min-height:200px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px;font-size:13px;resize:vertical;line-height:1.5" oninput="updateWordCount(this, \\'rev-li-wc-' + packageId + '\\')">' + esc(liText) + '</textarea>';
  html += '</div>';
  // Diff preview area
  html += '<div id="rev-diff-' + packageId + '" style="display:none;margin-bottom:12px"></div>';
  // Buttons
  html += '<div style="display:flex;gap:8px">';
  html += '<button class="btn btn-primary" onclick="submitRevisedCopy(\\'' + packageId + '\\')">Submit Revised Copy</button>';
  html += '<button class="btn btn-dim" onclick="previewDiff(\\'' + packageId + '\\')">Preview Changes</button>';
  html += '<button class="btn btn-dim" onclick="document.getElementById(\\'revised-form-' + packageId + '\\').remove()">Cancel</button>';
  html += '</div></div>';
  card.insertAdjacentHTML('beforeend', html);
}

function updateWordCount(textarea, wcId) {
  const wc = textarea.value.trim() ? textarea.value.trim().split(/\\s+/).length : 0;
  document.getElementById(wcId).textContent = wc + ' words';
}

function previewDiff(packageId) {
  const form = document.getElementById('revised-form-' + packageId);
  const card = form.closest('.pkg-card');
  const fbDiv = card.querySelector('[id^="fb-"]');
  const liDiv = card.querySelector('[id^="li-"]');
  const origFb = fbDiv ? fbDiv.querySelector('.post-preview')?.textContent || '' : '';
  const origLi = liDiv ? liDiv.querySelector('.post-preview')?.textContent || '' : '';
  const newFb = document.getElementById('rev-fb-' + packageId).value;
  const newLi = document.getElementById('rev-li-' + packageId).value;
  const diffArea = document.getElementById('rev-diff-' + packageId);
  let html = '';
  if (origFb !== newFb) {
    html += '<div style="margin-bottom:8px"><strong style="color:var(--green);font-size:12px">Facebook changes:</strong></div>';
    html += '<div style="font-size:12px;background:#0d1117;padding:10px;border-radius:6px;border:1px solid var(--border);margin-bottom:12px">' + wordDiff(origFb, newFb) + '</div>';
  }
  if (origLi !== newLi) {
    html += '<div style="margin-bottom:8px"><strong style="color:#3b82f6;font-size:12px">LinkedIn changes:</strong></div>';
    html += '<div style="font-size:12px;background:#0d1117;padding:10px;border-radius:6px;border:1px solid var(--border);margin-bottom:12px">' + wordDiff(origLi, newLi) + '</div>';
  }
  if (!html) html = '<div style="font-size:12px;color:var(--dim);padding:8px">No changes detected.</div>';
  diffArea.innerHTML = html;
  diffArea.style.display = '';
}

function wordDiff(oldText, newText) {
  const oldWords = oldText.split(/\\b/);
  const newWords = newText.split(/\\b/);
  // Simple LCS-based word diff
  const m = oldWords.length, n = newWords.length;
  // For performance, if texts are very long use simplified approach
  if (m > 500 || n > 500) {
    return '<span style="color:var(--red);text-decoration:line-through">' + esc(oldText.slice(0, 200)) + '...</span> <span style="color:var(--green)">' + esc(newText.slice(0, 200)) + '...</span>';
  }
  const dp = Array.from({length: m + 1}, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) for (let j = 1; j <= n; j++) {
    dp[i][j] = oldWords[i-1] === newWords[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
  }
  const result = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldWords[i-1] === newWords[j-1]) {
      result.unshift(esc(oldWords[i-1]));
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
      result.unshift('<span style="color:var(--green);background:#05200e">' + esc(newWords[j-1]) + '</span>');
      j--;
    } else {
      result.unshift('<span style="color:var(--red);text-decoration:line-through;background:#200505">' + esc(oldWords[i-1]) + '</span>');
      i--;
    }
  }
  return result.join('');
}

async function submitRevisedCopy(packageId) {
  const form = document.getElementById('revised-form-' + packageId);
  const card = form.closest('.pkg-card');
  const fbDiv = card.querySelector('[id^="fb-"]');
  const liDiv = card.querySelector('[id^="li-"]');
  const origFb = fbDiv ? fbDiv.querySelector('.post-preview')?.textContent || '' : '';
  const origLi = liDiv ? liDiv.querySelector('.post-preview')?.textContent || '' : '';
  const newFb = document.getElementById('rev-fb-' + packageId).value;
  const newLi = document.getElementById('rev-li-' + packageId).value;
  // Auto-generate revision summary
  const fbChanged = origFb !== newFb;
  const liChanged = origLi !== newLi;
  if (!fbChanged && !liChanged) { toast('No changes detected', false); return; }
  let summary = '';
  if (fbChanged) summary += 'FB post edited';
  if (liChanged) summary += (summary ? ', ' : '') + 'LI post edited';
  try {
    await api('/feedback/', {
      method: 'POST',
      body: JSON.stringify({
        package_id: packageId,
        action_taken: 'revised',
        revision_summary: summary,
        revised_facebook_post: fbChanged ? newFb : null,
        revised_linkedin_post: liChanged ? newLi : null,
        feedback_notes: 'Copy revision submitted via dashboard',
      }),
    });
    toast('Revised copy submitted - system will learn from your edits');
    // Show diff inline after submit
    previewDiff(packageId);
    // Disable submit button
    const submitBtn = form.querySelector('.btn-primary');
    if (submitBtn) { submitBtn.textContent = 'Submitted'; submitBtn.disabled = true; submitBtn.style.background = 'var(--green)'; submitBtn.style.color = '#000'; }
  } catch (e) { toast('Submit failed: ' + e.message, false); }
}

// ANALYTICS TAB
async function renderAnalytics() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Analytics & Performance</h2><div id="analytics-content"><div class="empty">Loading analytics...</div></div></div>';
  try {
    const [pkgs, feedback, learning, runs] = await Promise.all([
      api('/content/packages').catch(() => []),
      api('/feedback/').catch(() => []),
      api('/feedback/learning').catch(() => []),
      api('/pipeline/runs?limit=20').catch(() => []),
    ]);
    let html = '';
    // Summary cards
    const approved = pkgs.filter(p => p.approval_status === 'approved').length;
    const rejected = pkgs.filter(p => p.approval_status === 'rejected').length;
    const draft = pkgs.filter(p => p.approval_status === 'draft').length;
    const fbCount = feedback.length;
    const successRuns = runs.filter(r => r.status === 'completed').length;
    const failedRuns = runs.filter(r => r.status === 'failed').length;
    html += '<div class="grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px">';
    html += '<div class="card"><h3>Packages</h3><div class="value">' + pkgs.length + '</div>';
    html += '<div class="sub" style="color:var(--green)">' + approved + ' approved</div>';
    html += '<div class="sub">' + draft + ' draft, ' + rejected + ' rejected</div></div>';
    html += '<div class="card"><h3>Pipeline Runs</h3><div class="value">' + runs.length + '</div>';
    html += '<div class="sub" style="color:var(--green)">' + successRuns + ' successful</div>';
    if (failedRuns) html += '<div class="sub" style="color:var(--red)">' + failedRuns + ' failed</div>';
    html += '</div>';
    html += '<div class="card"><h3>Feedback Submitted</h3><div class="value">' + fbCount + '</div>';
    html += '<div class="sub">Operator reviews</div></div>';
    html += '<div class="card"><h3>Learning Events</h3><div class="value">' + learning.length + '</div>';
    html += '<div class="sub">Performance data points</div></div>';
    html += '</div>';
    // Recent packages table
    html += '<div class="card" style="margin-bottom:16px"><h3>Recent Packages</h3>';
    if (pkgs.length) {
      html += '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">';
      html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Date</th><th style="text-align:left;padding:8px 12px">Status</th><th style="text-align:left;padding:8px 12px">CTA</th><th style="text-align:left;padding:8px 12px">QA Score</th><th style="text-align:left;padding:8px 12px">Feedback</th></tr>';
      for (const p of pkgs.slice(0, 15)) {
        const stColor = p.approval_status === 'approved' ? 'var(--green)' : p.approval_status === 'rejected' ? 'var(--red)' : 'var(--yellow)';
        const qa = p.quality_scores?.composite_score || p.quality_scores?.overall;
        const qaVal = qa != null ? (typeof qa === 'number' ? qa.toFixed(1) : (qa?.score || '-')) : '-';
        const fb = feedback.find(f => f.package_id === p.id);
        html += '<tr style="border-bottom:1px solid var(--border)">';
        html += '<td style="padding:8px 12px">' + new Date(p.created_at).toLocaleDateString() + '</td>';
        html += '<td style="padding:8px 12px;color:' + stColor + ';font-weight:600">' + p.approval_status + '</td>';
        html += '<td style="padding:8px 12px">' + esc(p.cta_keyword || '-') + '</td>';
        html += '<td style="padding:8px 12px;font-weight:600">' + qaVal + '</td>';
        html += '<td style="padding:8px 12px">' + (fb ? '<span style="color:var(--green)">Yes</span>' : '<span style="color:var(--dim)">-</span>') + '</td>';
        html += '</tr>';
      }
      html += '</table>';
    } else {
      html += '<div class="empty" style="padding:16px">No packages yet.</div>';
    }
    html += '</div>';
    // Feedback tags distribution
    if (feedback.length) {
      const tagCounts = {};
      for (const fb of feedback) {
        for (const tag of (fb.feedback_tags || [])) {
          tagCounts[tag] = (tagCounts[tag] || 0) + 1;
        }
      }
      if (Object.keys(tagCounts).length) {
        html += '<div class="card" style="margin-bottom:16px"><h3>Feedback Tag Distribution</h3>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px">';
        const sorted = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]);
        for (const [tag, count] of sorted) {
          const isPositive = tag.startsWith('great_') || tag.startsWith('strong_') || tag.startsWith('perfect_') || tag.startsWith('good_');
          html += '<div style="padding:6px 12px;border-radius:6px;font-size:13px;background:' + (isPositive ? '#052e16' : '#2d2000') + ';color:' + (isPositive ? 'var(--green)' : 'var(--yellow)') + '">';
          html += tag.replace(/_/g, ' ') + ' <strong>(' + count + ')</strong>';
          html += '</div>';
        }
        html += '</div></div>';
      }
    }
    // Voice Learning section
    const revisedFeedback = feedback.filter(f => f.revised_facebook_post || f.revised_linkedin_post);
    html += '<div class="card" style="margin-bottom:16px"><h3 style="color:var(--accent2)">Voice Learning</h3>';
    html += '<div style="margin-top:12px">';
    if (revisedFeedback.length) {
      html += '<div style="display:flex;gap:16px;margin-bottom:12px">';
      html += '<div style="padding:12px 20px;background:#0d1117;border-radius:8px;border:1px solid var(--border);text-align:center">';
      html += '<div style="font-size:24px;font-weight:700;color:var(--accent2)">' + revisedFeedback.length + '</div>';
      html += '<div style="font-size:12px;color:var(--dim)">Revised copies submitted</div></div>';
      const fbRevised = revisedFeedback.filter(f => f.revised_facebook_post).length;
      const liRevised = revisedFeedback.filter(f => f.revised_linkedin_post).length;
      html += '<div style="padding:12px 20px;background:#0d1117;border-radius:8px;border:1px solid var(--border);text-align:center">';
      html += '<div style="font-size:24px;font-weight:700;color:var(--green)">' + fbRevised + '</div>';
      html += '<div style="font-size:12px;color:var(--dim)">FB posts edited</div></div>';
      html += '<div style="padding:12px 20px;background:#0d1117;border-radius:8px;border:1px solid var(--border);text-align:center">';
      html += '<div style="font-size:24px;font-weight:700;color:#3b82f6">' + liRevised + '</div>';
      html += '<div style="font-size:12px;color:var(--dim)">LI posts edited</div></div>';
      html += '</div>';
      html += '<div style="font-size:12px;color:var(--dim);padding:8px;background:#0d1117;border-radius:6px">The Learning Loop agent analyzes your edits to identify voice patterns and adjust future content generation. More revisions = smarter content.</div>';
    } else {
      html += '<div class="empty" style="padding:16px">No revised copies submitted yet. Use the "Edit & Submit Copy" button on packages to teach the system your voice.</div>';
    }
    html += '</div></div>';
    // DM Fulfillment section
    html += '<div class="card"><h3>DM Fulfillment Status</h3>';
    html += '<div style="margin-top:12px">';
    const pkgsWithDm = pkgs.filter(p => p.dm_flow);
    if (pkgsWithDm.length) {
      html += '<table style="width:100%;border-collapse:collapse;font-size:13px">';
      html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Package Date</th><th style="text-align:left;padding:8px 12px">CTA Keyword</th><th style="text-align:left;padding:8px 12px">Trigger</th><th style="text-align:left;padding:8px 12px">Has DM Flow</th></tr>';
      for (const p of pkgsWithDm.slice(0, 10)) {
        const dm = p.dm_flow || {};
        html += '<tr style="border-bottom:1px solid var(--border)">';
        html += '<td style="padding:8px 12px">' + new Date(p.created_at).toLocaleDateString() + '</td>';
        html += '<td style="padding:8px 12px;font-weight:600;color:var(--accent2)">' + esc(p.cta_keyword || '-') + '</td>';
        html += '<td style="padding:8px 12px">' + esc(dm.trigger || '-') + '</td>';
        html += '<td style="padding:8px 12px;color:var(--green)">Yes - ' + Object.keys(dm).length + ' steps</td>';
        html += '</tr>';
      }
      html += '</table>';
    } else {
      html += '<div class="empty" style="padding:16px">No packages with DM flows yet. DM flows are generated by the CTA Agent during pipeline runs.</div>';
    }
    html += '</div></div>';
    document.getElementById('analytics-content').innerHTML = html;
  } catch (e) {
    document.getElementById('analytics-content').innerHTML = '<div class="empty">Error loading analytics: ' + e.message + '</div>';
  }
}

// Router
function render() {
  const map = { week: renderWeek, generate: renderGenerate, packages: renderPackages, corpus: renderCorpus, voice: renderVoice, creators: renderCreators, agents: renderAgents, costs: renderCosts, analytics: renderAnalytics };
  (map[currentTab] || renderGenerate)();
}
restoreGenAllState();
// Tick elapsed timer every second when generating
setInterval(() => { if (genAllState?.running) renderGenAllProgress(); }, 1000);
render();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the operator dashboard."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        content=DASHBOARD_HTML,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )
