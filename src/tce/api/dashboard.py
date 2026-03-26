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
:root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#e4e4e7;--dim:#71717a;--accent:#6366f1;--accent2:#818cf8;--green:#22c55e;--red:#ef4444;--yellow:#eab308;--blue:#3b82f6}
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
select,input{padding:8px 12px;border:1px solid var(--border);background:var(--card);color:var(--text);border-radius:6px;font-size:13px}
.pipeline-steps{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.step-badge{padding:6px 12px;border-radius:16px;font-size:12px;font-weight:500;border:1px solid var(--border)}
.step-badge.completed{background:#166534;border-color:#22c55e;color:#bbf7d0}
.step-badge.running{background:#1e3a5f;border-color:#3b82f6;color:#93c5fd;animation:pulse 1.5s infinite}
.step-badge.pending{background:var(--card);color:var(--dim)}
.step-badge.failed{background:#7f1d1d;border-color:#ef4444;color:#fecaca}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.post-preview{background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px;margin:8px 0;white-space:pre-wrap;font-size:14px;line-height:1.6;max-height:300px;overflow-y:auto}
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
.day-card .day-angle{font-size:12px;color:var(--accent2);background:#1e1b4b;padding:3px 8px;border-radius:4px;display:inline-block;margin-bottom:8px}
.day-card .day-topic{font-size:13px;color:var(--text);margin-bottom:8px;flex:1}
.day-card .day-status{font-size:11px;font-weight:600;text-transform:uppercase;padding:2px 6px;border-radius:3px;display:inline-block}
.day-status-planned{background:#1e3a5f;color:#93c5fd}
.day-status-generating{background:#1e3a5f;color:#93c5fd;animation:pulse 1.5s infinite}
.day-status-ready{background:#052e16;color:#bbf7d0}
.day-status-approved{background:#052e16;color:#22c55e}
.day-status-published{background:#1e1b4b;color:#c7d2fe}
.day-status-skipped{background:#2d2000;color:#fbbf24}
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
</div>
<div class="main" id="app"></div>
<script>
const API = '/api/v1';
let currentTab = 'week';
let activePipelineRun = localStorage.getItem('tce_active_run') || null;
let pollInterval = null;
let verboseMode = localStorage.getItem('tce_verbose') === 'true';

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
    document.getElementById('health-dot').className = d.status === 'ok' ? 'dot' : 'dot off';
    document.getElementById('health-text').textContent = d.status === 'ok' ? 'System healthy' : 'System error';
  } catch { document.getElementById('health-dot').className = 'dot off'; document.getElementById('health-text').textContent = 'Offline'; }
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
        <div class="btn-group">
          <button class="btn btn-dim" onclick="weekOffset--;renderWeek()">Prev Week</button>
          <button class="btn btn-dim" onclick="weekOffset=0;renderWeek()">This Week</button>
          <button class="btn btn-dim" onclick="weekOffset++;renderWeek()">Next Week</button>
        </div>
      </div>
      <div style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:16px">
        <div>
          <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Weekly Theme</label>
          <input id="week-theme" type="text" placeholder="Optional - e.g. Agency scaling without burnout" style="width:320px">
        </div>
        <button class="btn btn-primary" onclick="planWeek('${fmtDate(monday)}')">Plan This Week</button>
        <button class="btn btn-blue" onclick="runWeeklyPlanning()">Generate Weekly Guide</button>
      </div>
      <div class="week-grid" id="week-grid"><div class="empty" style="grid-column:1/-1">Loading calendar...</div></div>
      <div id="guide-section"></div>
    </div>`;

  // Load calendar entries for this week
  try {
    const entries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(friday));
    const byDate = {};
    entries.forEach(e => byDate[e.date] = e);

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
      html += '<div class="day-angle">' + (ANGLE_LABELS[angle] || angle.replace(/_/g,' ')) + '</div>';
      if (entry?.topic) html += '<div class="day-topic">' + esc(entry.topic) + '</div>';
      else html += '<div class="day-topic" style="color:var(--dim);font-style:italic">No topic set</div>';
      if (entry?.operator_notes) html += '<div style="font-size:11px;color:var(--dim);margin-bottom:6px">' + esc(entry.operator_notes) + '</div>';

      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto">';
      if (entry) {
        html += '<span class="day-status day-status-' + status + '">' + status + '</span>';
        if (status === 'planned' || status === 'ready') {
          html += '<button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="runDayPipeline(' + i + ',\\'' + (entry?.id || '') + '\\')">Generate</button>';
        }
        if (entry.post_package_id) {
          html += '<button class="btn btn-dim" style="padding:4px 10px;font-size:11px" onclick="currentTab=\\'packages\\';document.querySelectorAll(\\'.nav button\\').forEach(b=>b.classList.toggle(\\'active\\',b.dataset.tab===\\'packages\\'));render()">View Post</button>';
        }
      } else {
        html += '<span class="day-status" style="background:var(--border);color:var(--dim)">unplanned</span>';
      }
      html += '</div>';
      html += '</div>';
    }
    document.getElementById('week-grid').innerHTML = html;
  } catch (e) {
    document.getElementById('week-grid').innerHTML = '<div class="empty" style="grid-column:1/-1">Error loading calendar: ' + e.message + '</div>';
  }

  // Load weekly guides
  try {
    const guides = await api('/content/guides');
    if (guides.length) {
      let html = '<h2 style="margin-top:24px;margin-bottom:12px">Gift of the Week (Weekly Guides)</h2>';
      for (const g of guides.slice(0, 4)) {
        html += '<div class="guide-card">';
        html += '<h3>' + esc(g.guide_title) + '</h3>';
        html += '<div class="guide-meta">';
        html += '<span>Week of ' + g.week_start_date + '</span>';
        html += '<span>Theme: ' + esc(g.weekly_theme) + '</span>';
        if (g.cta_keyword) html += '<span>CTA: <strong>' + esc(g.cta_keyword) + '</strong></span>';
        html += '</div>';
        html += '<div class="btn-group" style="margin:12px 0">';
        if (g.docx_path) html += '<a class="btn btn-green" href="' + API + '/content/guides/' + g.id + '/download" target="_blank">Download DOCX</a>';
        if (g.fulfillment_link) html += '<a class="btn btn-blue" href="' + esc(g.fulfillment_link) + '" target="_blank">Fulfillment Link</a>';
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

async function planWeek(mondayStr) {
  const theme = document.getElementById('week-theme')?.value || null;
  try {
    const entries = await api('/calendar/plan-week', {
      method: 'POST',
      body: JSON.stringify({ week_start: mondayStr, weekly_theme: theme || null }),
    });
    if (entries.length === 0) {
      toast('Week already planned! All 5 days exist.');
    } else {
      toast('Week planned: ' + entries.length + ' days created');
    }
    await renderWeek();
  } catch (e) { toast('Error: ' + e.message, false); }
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
            <div id="wf-desc" style="font-size:11px;color:var(--dim);margin-top:6px;max-width:400px;line-height:1.5"></div>
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

async function pollPipeline() {
  if (!activePipelineRun) return;
  try {
    const r = await api('/pipeline/' + activePipelineRun + '/status');
    const statuses = r.step_status || {};
    const errors = r.step_errors || {};
    const logs = r.step_logs || {};
    const allDone = !Object.values(statuses).some(s => s === 'pending' || s === 'running');

    let html = '<div class="card"><h3>Pipeline: ' + activePipelineRun.substring(0, 8) + '...</h3>';
    html += '<div class="pipeline-steps">';
    for (const [step, status] of Object.entries(statuses)) {
      const lastLog = (logs[step] || []).slice(-1)[0] || '';
      const tooltip = lastLog ? ' title="' + esc(lastLog) + '"' : '';
      html += '<div class="step-badge ' + status + '"' + tooltip + '>' + step.replace(/_/g, ' ') + '</div>';
    }
    html += '</div>';

    // Verbose mode: show live agent logs
    if (verboseMode) {
      html += '<div class="log" style="max-height:400px;margin-top:12px">';
      for (const [step, status] of Object.entries(statuses)) {
        const stepLogs = logs[step] || [];
        if (stepLogs.length === 0 && status === 'pending') continue;
        const color = status === 'completed' ? 'var(--green)' : status === 'running' ? 'var(--blue)' : status === 'failed' ? 'var(--red)' : 'var(--dim)';
        html += '<div style="color:' + color + ';font-weight:600;margin-top:8px">' + step.replace(/_/g, ' ') + ' [' + status + ']</div>';
        for (const log of stepLogs) {
          html += '<div style="padding-left:12px;color:var(--dim)">' + esc(log) + '</div>';
        }
      }
      html += '</div>';
    }

    if (Object.keys(errors).length) {
      html += '<div class="log" style="border-color:var(--red);margin-top:8px">';
      for (const [step, err] of Object.entries(errors)) html += '<div style="color:var(--red)">' + step + ': ' + esc(err) + '</div>';
      html += '</div>';
    }
    if (allDone) {
      html += '<div style="margin-top:12px;color:var(--green);font-weight:600">Pipeline complete</div>';
      if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
      localStorage.removeItem('tce_active_run');
      const hasCompleted = Object.values(statuses).some(s => s === 'completed');
      if (hasCompleted) html += '<button class="btn btn-blue" style="margin-top:8px" onclick="currentTab=\\'packages\\';document.querySelectorAll(\\'.nav button\\').forEach(b=>b.classList.toggle(\\'active\\',b.dataset.tab===\\'packages\\'));render()">View Packages</button>';
    }
    html += '</div>';
    document.getElementById('pipeline-status').innerHTML = html;
    const btn = document.getElementById('run-btn');
    if (btn) { btn.disabled = !allDone; btn.textContent = allDone ? 'Run Pipeline' : 'Running...'; }
  } catch (e) {
    // Run might have completed and been cleaned up - clear localStorage
    if (e.message?.includes('404') || e.message?.includes('not found')) {
      localStorage.removeItem('tce_active_run');
      activePipelineRun = null;
      if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    }
  }
}

// PACKAGES TAB
async function renderPackages() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Content Packages</h2><div id="pkg-list"><div class="empty">Loading...</div></div></div>';
  try {
    const pkgs = await api('/content/packages');
    if (!pkgs.length) { document.getElementById('pkg-list').innerHTML = '<div class="empty">No packages yet. Run a pipeline first.</div>'; return; }
    let html = '<div class="packages-list">';
    for (const p of pkgs) {
      const statusTag = p.approval_status === 'approved' ? 'tag-approved' : p.approval_status === 'rejected' ? 'tag-rejected' : 'tag-draft';
      html += '<div class="pkg-card" id="pkg-' + p.id + '">';
      html += '<div class="pkg-header"><span class="tag ' + statusTag + '">' + p.approval_status + '</span>';
      html += '<span style="font-size:12px;color:var(--dim)">' + new Date(p.created_at).toLocaleString() + '</span></div>';
      html += '<div class="pkg-meta">';
      if (p.cta_keyword) html += '<span>CTA: <strong>' + p.cta_keyword + '</strong></span>';
      if (p.pipeline_run_id) html += '<span>Run: ' + p.pipeline_run_id.substring(0, 8) + '</span>';
      html += '</div>';
      // Tabs
      const pid = p.id.replace(/-/g, '');
      html += '<div class="tabs">';
      html += '<button class="active" onclick="showPostTab(this,\\'fb-' + pid + '\\')">Facebook</button>';
      html += '<button onclick="showPostTab(this,\\'li-' + pid + '\\')">LinkedIn</button>';
      if (p.hook_variants?.length) html += '<button onclick="showPostTab(this,\\'hooks-' + pid + '\\')">Hooks (' + p.hook_variants.length + ')</button>';
      if (p.quality_scores) html += '<button onclick="showPostTab(this,\\'qa-' + pid + '\\')">QA Scores</button>';
      if (p.dm_flow) html += '<button onclick="showPostTab(this,\\'dm-' + pid + '\\')">DM Flow</button>';
      if (p.image_prompts?.length) html += '<button onclick="showPostTab(this,\\'img-' + pid + '\\')">Images (' + p.image_prompts.length + ')</button>';
      html += '</div>';
      html += '<div id="fb-' + pid + '" class="post-preview">' + esc(p.facebook_post || 'No Facebook post generated') + '</div>';
      html += '<div id="li-' + pid + '" class="post-preview" style="display:none">' + esc(p.linkedin_post || 'No LinkedIn post generated') + '</div>';
      if (p.hook_variants?.length) {
        html += '<div id="hooks-' + pid + '" class="post-preview" style="display:none">';
        p.hook_variants.forEach((h, i) => html += (i + 1) + '. ' + esc(h) + '\\n\\n');
        html += '</div>';
      }
      if (p.quality_scores) {
        html += '<div id="qa-' + pid + '" style="display:none"><div class="qa-grid">';
        for (const [k, v] of Object.entries(p.quality_scores)) {
          const score = typeof v === 'number' ? v : (v?.score || v);
          const color = score >= 8 ? 'var(--green)' : score >= 6 ? 'var(--yellow)' : 'var(--red)';
          html += '<div class="qa-item"><div class="label">' + k.replace(/_/g, ' ') + '</div><div class="score" style="color:' + color + '">' + (typeof score === 'number' ? score.toFixed(1) : score) + '</div></div>';
        }
        html += '</div></div>';
      }
      if (p.dm_flow) {
        html += '<div id="dm-' + pid + '" class="post-preview" style="display:none">' + esc(JSON.stringify(p.dm_flow, null, 2)) + '</div>';
      }
      if (p.image_prompts?.length) {
        html += '<div id="img-' + pid + '" style="display:none">';
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px">';
        for (const ip of p.image_prompts) {
          const promptText = ip.prompt_text || ip.detailed_prompt || '';
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:16px">';
          html += '<div style="font-weight:600;font-size:14px;color:var(--accent2);margin-bottom:8px">' + esc(ip.prompt_name || ip.visual_job || 'Image') + '</div>';
          if (ip.visual_intent) html += '<div style="font-size:12px;color:var(--text);margin-bottom:8px;font-style:italic">' + esc(ip.visual_intent) + '</div>';
          html += '<div style="font-size:12px;color:var(--dim);margin-bottom:8px;display:flex;gap:12px;flex-wrap:wrap">';
          if (ip.mood) html += '<span>Mood: <strong>' + esc(ip.mood) + '</strong></span>';
          if (ip.aspect_ratio) html += '<span>Ratio: <strong>' + esc(ip.aspect_ratio) + '</strong></span>';
          if (ip.platform_fit) html += '<span>Platform: <strong>' + esc(ip.platform_fit) + '</strong></span>';
          if (ip.color_logic) html += '<span>Colors: ' + esc(String(ip.color_logic).slice(0, 60)) + '</span>';
          html += '</div>';
          html += '<div style="font-size:12px;margin-bottom:8px"><strong style="color:var(--green)">Full Prompt:</strong></div>';
          html += '<div class="post-preview" style="font-size:12px;margin:0;max-height:none;white-space:pre-wrap">' + esc(promptText) + '</div>';
          if (ip.negative_prompt) {
            html += '<div style="font-size:12px;margin-top:8px"><strong style="color:var(--red)">Negative:</strong></div>';
            html += '<div style="font-size:11px;color:var(--dim);margin-top:4px">' + esc(ip.negative_prompt) + '</div>';
          }
          if (ip.rationale) html += '<div style="font-size:11px;color:var(--dim);margin-top:8px;border-top:1px solid var(--border);padding-top:8px">Rationale: ' + esc(ip.rationale) + '</div>';
          if (ip.image_url) html += '<img src="' + esc(ip.image_url) + '" style="width:100%;border-radius:6px;margin-top:8px" loading="lazy">';
          html += '<button class="btn btn-dim" style="margin-top:8px;font-size:11px" onclick="navigator.clipboard.writeText(\\'' + esc(promptText).replace(/'/g, "\\\\'").replace(/\\n/g, " ") + '\\');toast(\\'Prompt copied\\')">Copy Prompt</button>';
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
      html += '<button class="btn btn-dim" onclick="copyPost(\\'' + pid + '\\')">Copy FB Post</button>';
      html += '<button class="btn btn-dim" onclick="copyPost(\\'li-' + pid + '\\')">Copy LI Post</button>';
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
  card.querySelectorAll('.post-preview, .qa-grid').forEach(el => el.style.display = 'none');
  // Also hide qa wrapper divs
  card.querySelectorAll('[id^="qa-"]').forEach(el => el.style.display = 'none');
  card.querySelectorAll('[id^="img-"]').forEach(el => el.style.display = 'none');
  card.querySelectorAll('[id^="dm-"]').forEach(el => el.style.display = 'none');
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

function copyPost(pid) {
  const el = document.getElementById('fb-' + pid);
  if (el) { navigator.clipboard.writeText(el.textContent); toast('Copied to clipboard'); }
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
    const d = await r.json();
    toast('Uploaded: ' + d.file_name + ' (' + d.pages + ' pages)');
    renderCorpus();
  } catch (e) { toast('Upload failed: ' + e.message, false); renderCorpus(); }
}

async function viewExamples(docId, name) {
  try {
    const examples = await api('/documents/' + docId + '/examples');
    // Also fetch creators for name lookup
    let creatorMap = {};
    try { const creators = await api('/profiles/creators'); for (const c of creators) creatorMap[c.id] = c.creator_name; } catch(e) {}
    const w = window.open('', '_blank');
    let h = '<html><head><style>body{font-family:-apple-system,sans-serif;padding:20px;max-width:1000px;margin:auto;background:#0f1117;color:#e4e4e7}h1{font-size:20px;margin-bottom:16px}.ex{border:1px solid #2a2d3a;border-radius:10px;padding:20px;margin:16px 0;background:#1a1d27}.meta{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:12px;color:#71717a}.badge{background:#2a2d3a;padding:2px 8px;border-radius:4px;font-size:11px}.score-box{display:inline-block;background:#6366f1;color:#fff;padding:4px 10px;border-radius:6px;font-weight:700;font-size:14px;margin-right:8px}.post-text{background:#0f1117;border:1px solid #2a2d3a;border-radius:6px;padding:12px;margin:8px 0;white-space:pre-wrap;font-size:13px;line-height:1.6;direction:rtl;text-align:right;max-height:200px;overflow-y:auto}.section-label{font-size:11px;color:#6366f1;text-transform:uppercase;letter-spacing:.5px;margin-top:12px;margin-bottom:4px}.tags{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0}.tag{background:#1e3a5f;color:#60a5fa;padding:2px 6px;border-radius:3px;font-size:11px}.tag.topic{background:#1e3a2f;color:#4ade80}.engagement{display:flex;gap:16px;margin-top:8px;font-size:12px;color:#71717a}.expand-btn{background:none;border:1px solid #2a2d3a;color:#818cf8;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;margin-top:6px}</style></head><body>';
    h += '<h1>' + name + ' - ' + examples.length + ' examples</h1>';
    for (let i = 0; i < examples.length; i++) {
      const ex = examples[i];
      const creator = creatorMap[ex.creator_id] || 'Unknown';
      h += '<div class="ex">';
      // Header row with score and classification
      h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
      h += '<div style="font-weight:600;font-size:14px">#' + (i+1) + ' - ' + creator + '</div>';
      if (ex.final_score != null) h += '<div class="score-box">' + ex.final_score.toFixed(2) + '</div>';
      else if (ex.raw_score != null) h += '<div class="score-box" style="background:#71717a">Raw: ' + ex.raw_score.toFixed(2) + '</div>';
      h += '</div>';
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
      if (c.voice_axes) {
        html += '<div style="margin-top:8px">';
        for (const [k, v] of Object.entries(c.voice_axes)) {
          html += '<div class="tone-bar"><span class="name">' + k + '</span><div class="bar" style="width:' + (v * 10) + '%;background:var(--blue)"></div><span>' + v + '</span></div>';
        }
        html += '</div>';
      }
      html += '</div>';
    }
    html += '</div>';
    document.getElementById('creators-list').innerHTML = html;
  } catch (e) { document.getElementById('creators-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
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

// Router
function render() {
  const map = { week: renderWeek, generate: renderGenerate, packages: renderPackages, corpus: renderCorpus, voice: renderVoice, creators: renderCreators, agents: renderAgents };
  (map[currentTab] || renderGenerate)();
}
render();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the operator dashboard."""
    return DASHBOARD_HTML
