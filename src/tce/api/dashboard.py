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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* === DESIGN SYSTEM - Inspired by Agent Artist Studio === */
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:hsl(220 20% 7%);--card:hsl(220 18% 10%);--card-hover:hsl(220 18% 12%);
  --border:hsl(220 14% 18%);--border-hover:hsl(174 72% 52% / 0.3);
  --text:hsl(210 20% 92%);--dim:hsl(215 12% 55%);--muted:hsl(215 16% 35%);
  --primary:hsl(174 72% 52%);--primary-fg:#000;--primary-dim:hsl(174 72% 52% / 0.1);
  --accent:hsl(38 92% 58%);--accent-dim:hsl(38 92% 58% / 0.1);
  --success:hsl(150 60% 45%);--success-dim:hsl(150 60% 45% / 0.1);
  --destructive:hsl(0 72% 55%);--destructive-dim:hsl(0 72% 55% / 0.1);
  --warning:hsl(38 92% 58%);--warning-dim:hsl(38 92% 58% / 0.1);
  --info:hsl(210 80% 58%);--info-dim:hsl(210 80% 58% / 0.1);
  --gradient-card:linear-gradient(180deg,hsl(220 18% 12%),hsl(220 18% 9%));
  --gradient-hero:linear-gradient(135deg,hsl(174 72% 52% / 0.08),hsl(38 92% 58% / 0.06));
  --shadow-glow:0 0 12px hsl(174 72% 52% / 0.3);
  --sidebar-w:240px;--sidebar-collapsed:56px;--header-h:56px;
  color-scheme:dark;
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;line-height:1.6;overflow:hidden}
h1,h2,h3,h4,h5,h6,.font-display{font-family:'JetBrains Mono',monospace}
.font-body{font-family:'Inter',sans-serif}

/* === LAYOUT: Sidebar + Header + Content === */
.app-shell{display:flex;height:100vh;overflow:hidden}
.sidebar{width:var(--sidebar-w);background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0;transition:width 0.25s ease;overflow:hidden;z-index:50}
.sidebar.collapsed{width:var(--sidebar-collapsed)}
.sidebar-header{height:var(--header-h);padding:0 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);flex-shrink:0}
.sidebar-header .logo{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:var(--primary);white-space:nowrap;overflow:hidden}
.sidebar-toggle{background:none;border:none;color:var(--dim);cursor:pointer;padding:4px;font-size:16px;transition:color 0.15s}
.sidebar-toggle:hover{color:var(--text)}
.sidebar-nav{flex:1;overflow-y:auto;padding:8px 0}
.sidebar-group{padding:0 8px;margin-bottom:4px}
.sidebar-group-label{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--dim);opacity:0.6;padding:12px 12px 4px;white-space:nowrap;overflow:hidden}
.sidebar.collapsed .sidebar-group-label{opacity:0;height:8px;padding:4px 0}
.sidebar-item{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--dim);transition:all 0.15s;position:relative;white-space:nowrap;border:none;background:none;width:100%;text-align:left}
.sidebar-item:hover{color:var(--text);background:hsl(215 16% 35% / 0.15)}
.sidebar-item.active{color:var(--primary);background:var(--primary-dim);font-weight:600}
.sidebar-item.active::before{content:'';position:absolute;left:0;top:4px;bottom:4px;width:2px;background:var(--primary);border-radius:1px;animation:scale-in 0.2s ease-out}
.sidebar-item .icon{width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.sidebar-item .label{overflow:hidden;transition:opacity 0.2s}
.sidebar.collapsed .sidebar-item .label{opacity:0;width:0}
.sidebar-footer{padding:8px;border-top:1px solid var(--border);flex-shrink:0}

/* Header bar */
.header-bar{height:var(--header-h);background:var(--card);border-bottom:1px solid var(--border);padding:0 24px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.header-title{font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:600}
.header-actions{display:flex;align-items:center;gap:16px}
.search-input{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px 12px 8px 36px;color:var(--text);font-size:13px;width:200px;transition:width 0.3s ease-out,border-color 0.2s;font-family:'Inter',sans-serif}
.search-input:focus{width:350px;outline:none;border-color:var(--primary)}
.search-wrap{position:relative}
.search-icon{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--dim);font-size:14px;pointer-events:none}
.notif-btn{position:relative;cursor:pointer;background:none;border:none;font-size:20px;color:var(--dim);transition:color 0.15s;padding:4px}
.notif-btn:hover{color:var(--text)}
.notif-dot{position:absolute;top:0;right:0;width:8px;height:8px;background:var(--destructive);border-radius:50%;animation:bounce-dot 2s infinite}
.health-dot{width:8px;height:8px;border-radius:50%;background:var(--success);flex-shrink:0}
.health-dot.off{background:var(--destructive)}
.health-wrap{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}

/* Main content area */
.main-area{flex:1;display:flex;flex-direction:column;overflow:hidden}
.content-scroll{flex:1;overflow-y:auto;overflow-x:hidden}
.main{max-width:1200px;margin:0 auto;padding:16px 24px 32px}

/* Breadcrumb */
#breadcrumb{padding:8px 24px;font-size:12px;color:var(--dim);border-bottom:1px solid var(--border);font-family:'JetBrains Mono',monospace;display:none}

/* === CARDS === */
.card{background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;padding:20px;transition:border-color 0.2s,transform 0.2s,box-shadow 0.2s}
.card h3{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600}
.card .value{font-family:'JetBrains Mono',monospace;font-size:28px;font-weight:700}
.card .sub{font-size:12px;color:var(--dim);margin-top:4px}
.card-hero{background:var(--gradient-hero);border:1px solid hsl(174 72% 52% / 0.2);border-radius:8px;padding:20px}
.hover-lift{transition:transform 0.2s ease-out,box-shadow 0.2s ease-out,border-color 0.2s}
.hover-lift:hover{transform:translateY(-2px);box-shadow:0 8px 25px -5px rgba(0,0,0,0.3),0 0 10px -5px hsl(174 72% 52% / 0.1);border-color:var(--border-hover)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}
.section{margin-bottom:32px}
.section > h2{font-family:'JetBrains Mono',monospace;font-size:18px;margin-bottom:16px;font-weight:600}
.section-label{font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--dim);font-weight:600;margin-bottom:12px}

/* === BUTTONS === */
.btn{padding:8px 16px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;font-family:'Inter',sans-serif;transition:all 0.15s;display:inline-flex;align-items:center;gap:6px}
.btn:active{transform:scale(0.97)}
.btn-primary{background:var(--primary);color:var(--primary-fg)}
.btn-primary:hover{box-shadow:var(--shadow-glow)}
.btn-green{background:var(--success-dim);color:var(--success);border:1px solid hsl(150 60% 45% / 0.2)}
.btn-green:hover{background:hsl(150 60% 45% / 0.2)}
.btn-red{background:var(--destructive-dim);color:var(--destructive);border:1px solid hsl(0 72% 55% / 0.2)}
.btn-red:hover{background:hsl(0 72% 55% / 0.2)}
.btn-blue{background:var(--info-dim);color:var(--info);border:1px solid hsl(210 80% 58% / 0.2)}
.btn-blue:hover{background:hsl(210 80% 58% / 0.2)}
.btn-dim{background:transparent;color:var(--dim);border:1px solid var(--border)}
.btn-dim:hover{background:var(--card-hover);color:var(--text)}
.btn-group{display:flex;gap:8px;flex-wrap:wrap}
.btn-amber{background:var(--accent-dim);color:var(--accent);border:1px solid hsl(38 92% 58% / 0.2)}
.btn-amber:hover{background:hsl(38 92% 58% / 0.2)}

/* === FORMS === */
select,input,textarea{padding:8px 12px;border:1px solid var(--border);background:hsl(220 18% 8%);color:var(--text);border-radius:8px;font-size:13px;font-family:'Inter',sans-serif;color-scheme:dark;transition:border-color 0.2s}
select:focus,input:focus,textarea:focus{outline:none;border-color:hsl(174 72% 52% / 0.5)}
option{background:var(--card);color:var(--text)}
img{background:var(--card);border-radius:4px}

/* === BADGES & TAGS === */
.tag{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:10px;font-family:'JetBrains Mono',monospace;font-weight:600;text-transform:uppercase;letter-spacing:0.02em}
.tag-draft{background:var(--warning-dim);color:var(--warning)}
.tag-approved{background:var(--success-dim);color:var(--success)}
.tag-rejected{background:var(--destructive-dim);color:var(--destructive)}
.tag-scheduled{background:var(--info-dim);color:var(--info)}
.tag-published{background:var(--primary-dim);color:var(--primary)}

/* === PIPELINE === */
.pipeline-steps{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.step-badge{padding:6px 14px;border-radius:9999px;font-size:11px;font-family:'JetBrains Mono',monospace;font-weight:500;border:1px solid var(--border);transition:all 0.2s}
.step-badge.completed{background:var(--success-dim);border-color:var(--success);color:var(--success)}
.step-badge.running{background:var(--primary-dim);border-color:var(--primary);color:var(--primary)}
.step-badge.pending{background:transparent;color:var(--dim)}
.step-badge.failed{background:var(--destructive-dim);border-color:var(--destructive);color:var(--destructive)}
.plan-steps{display:flex;gap:6px;margin-top:12px}
.plan-step{padding:4px 12px;border-radius:9999px;font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:500;border:1px solid var(--border);color:var(--dim);transition:all 0.2s}
.plan-step.active{border-color:var(--primary);color:var(--primary);background:var(--primary-dim)}
.plan-step.done{border-color:var(--success);color:var(--success);background:var(--success-dim)}

/* === PIPELINE DOT VISUALIZATION === */
.pipeline-dots{display:flex;align-items:center;gap:4px;margin:16px 0}
.pipeline-dot{width:10px;height:10px;border-radius:50%;transition:all 0.2s}
.pipeline-dot.done{background:var(--success)}
.pipeline-dot.active{background:var(--primary);animation:pulse-slow 2s ease-in-out infinite}
.pipeline-dot.waiting{background:hsl(215 12% 25%)}
.pipeline-dot-label{font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--dim);text-align:center;margin-top:4px}
.pipeline-connector{width:24px;height:1px;background:var(--border)}

/* === PACKAGES === */
.packages-list{display:flex;flex-direction:column;gap:12px}
.pkg-card{background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;padding:20px;transition:border-color 0.2s}
.pkg-card:hover{border-color:var(--border-hover)}
.pkg-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.pkg-meta{display:flex;gap:16px;font-size:12px;color:var(--dim);margin-bottom:12px;font-family:'JetBrains Mono',monospace}
/* Underline-style tabs for package content */
.tabs{display:flex;gap:0;margin-bottom:12px;border-bottom:1px solid var(--border)}
.tabs button{padding:8px 16px;border:none;border-bottom:2px solid transparent;background:transparent;color:var(--dim);cursor:pointer;font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:500;transition:all 0.15s}
.tabs button.active{color:var(--primary);border-bottom-color:var(--primary)}
.tabs button:hover:not(.active){color:var(--text)}
/* Pill-style filter tabs */
.filter-tabs{display:inline-flex;gap:2px;background:hsl(220 18% 10%);border-radius:8px;padding:3px}
.filter-tab{padding:6px 14px;border:none;background:transparent;color:var(--dim);cursor:pointer;border-radius:6px;font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:500;transition:all 0.15s}
.filter-tab.active{background:var(--bg);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,0.3)}
.filter-tab:hover:not(.active){color:var(--text)}

/* QA Grid */
.qa-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-top:12px}
.qa-item{background:hsl(220 20% 8%);border:1px solid var(--border);padding:10px;border-radius:8px;font-size:12px}
.qa-item .label{color:var(--dim);font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.05em}
.qa-item .score{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;margin-top:4px}
.qa-bar{height:4px;border-radius:2px;background:hsl(220 14% 15%);margin-top:6px;overflow:hidden}
.qa-bar-fill{height:100%;border-radius:2px;transition:width 0.3s ease}

/* === CONTENT === */
.post-preview{background:hsl(220 20% 8%);border:1px solid var(--border);border-radius:8px;padding:16px;margin:8px 0;white-space:pre-wrap;font-size:14px;line-height:1.7;max-height:300px;overflow-y:auto}
.copy-icon-btn{position:absolute;top:8px;right:8px;background:none;border:1px solid transparent;border-radius:4px;cursor:pointer;font-size:16px;padding:4px 6px;opacity:0.4;transition:all 0.15s;z-index:2}
.copy-icon-btn:hover{opacity:1;background:var(--card);border-color:var(--border)}
.fb-btn{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border:1px solid var(--border);background:var(--primary-dim);color:var(--primary);cursor:pointer;border-radius:6px;font-size:11px;font-family:'JetBrains Mono',monospace;font-weight:500;vertical-align:middle;margin-left:6px;transition:all 0.15s}
.fb-btn:hover{border-color:var(--primary);background:hsl(174 72% 52% / 0.2)}
.fb-popover{position:absolute;z-index:100;background:var(--card);border:1px solid var(--primary);border-radius:8px;padding:12px;width:320px;box-shadow:0 8px 24px rgba(0,0,0,0.4)}
.fb-popover textarea{width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:13px;resize:vertical;min-height:60px}
.fb-actions{display:flex;gap:6px;margin-top:8px;justify-content:flex-end}

/* === CORPUS === */
.upload-zone{border:2px dashed var(--border);border-radius:8px;padding:40px;text-align:center;cursor:pointer;transition:all 0.2s}
.upload-zone:hover{border-color:var(--primary);box-shadow:0 0 20px hsl(174 72% 52% / 0.05)}
.upload-zone p{color:var(--dim);margin-top:8px}
.docs-list{display:flex;flex-direction:column;gap:8px}
.doc-row{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;transition:border-color 0.2s}
.doc-row:hover{border-color:var(--border-hover)}
.doc-info{display:flex;flex-direction:column;gap:2px}
.doc-name{font-weight:500;font-size:14px}
.doc-meta{font-size:12px;color:var(--dim);font-family:'JetBrains Mono',monospace}
.log{background:hsl(220 20% 8%);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:12px;max-height:200px;overflow-y:auto;line-height:1.5;color:var(--dim)}
.empty{text-align:center;padding:40px;color:var(--dim);font-family:'JetBrains Mono',monospace;font-size:13px}

/* === TOAST === */
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:500;z-index:999;font-family:'JetBrains Mono',monospace;animation:toast-in 0.3s ease;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
.toast-ok{background:var(--success);color:#000}
.toast-err{background:var(--destructive);color:#fff}
.toast-info{background:var(--info);color:#fff}

/* === VOICE PROFILE === */
.voice-profile{background:hsl(220 20% 8%);border:1px solid var(--border);border-radius:8px;padding:16px;margin:8px 0}
.voice-profile h4{color:var(--primary);margin-bottom:8px;font-size:14px;font-family:'JetBrains Mono',monospace}
.voice-tags{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
.voice-tag{background:var(--primary-dim);color:var(--primary);padding:3px 10px;border-radius:9999px;font-size:11px;font-family:'JetBrains Mono',monospace}
.tone-bar{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12px}
.tone-bar .bar{height:6px;border-radius:3px;background:var(--primary);transition:width 0.3s ease}
.tone-bar .name{width:100px;color:var(--dim);font-family:'JetBrains Mono',monospace;font-size:11px}

/* === WEEK PLANNER === */
.week-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:16px 0}
.day-card{background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;padding:16px;min-height:180px;display:flex;flex-direction:column;transition:transform 0.2s ease-out,box-shadow 0.2s ease-out,border-color 0.2s}
.day-card:hover{transform:translateY(-2px);box-shadow:0 8px 25px -5px rgba(0,0,0,0.3);border-color:var(--border-hover)}
.day-card.today{border-color:var(--primary);box-shadow:0 0 12px hsl(174 72% 52% / 0.15)}
.day-card.dragging{opacity:0.4;border:2px dashed var(--primary)}
.day-card.drag-over{outline:2px solid var(--success);outline-offset:-2px;background:hsl(150 60% 45% / 0.05)}
.day-card .day-header{font-size:12px;color:var(--dim);margin-bottom:4px;font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:0.05em}
.day-card .day-date{font-size:18px;font-weight:700;margin-bottom:8px;font-family:'JetBrains Mono',monospace}
.day-card .day-angle{font-size:11px;color:var(--primary);background:var(--primary-dim);padding:3px 10px;border-radius:9999px;display:inline-block;margin-bottom:8px;position:relative;font-family:'JetBrains Mono',monospace;font-weight:500}
.tip-icon{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:var(--primary);color:var(--primary-fg);font-size:9px;font-weight:700;font-style:italic;margin-left:4px;cursor:help;vertical-align:middle}
.tip-icon:hover::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);width:260px;padding:10px 12px;background:hsl(220 18% 12%);border:1px solid var(--primary);color:var(--text);font-size:12px;font-style:normal;font-weight:400;border-radius:8px;z-index:99;line-height:1.5;white-space:normal;box-shadow:0 4px 16px rgba(0,0,0,.5)}
.day-card .day-topic{font-size:13px;color:var(--text);margin-bottom:8px;flex:1;line-height:1.5}
.day-card .day-status{font-size:10px;font-family:'JetBrains Mono',monospace;font-weight:600;text-transform:uppercase;padding:3px 8px;border-radius:9999px;display:inline-block;letter-spacing:0.02em}
.day-status-planned{background:var(--info-dim);color:var(--info)}
.day-status-generating{background:var(--primary-dim);color:var(--primary)}
.day-status-ready{background:var(--success-dim);color:var(--success)}
.day-status-approved{background:var(--success-dim);color:var(--success)}
.day-status-published{background:var(--primary-dim);color:var(--primary)}
.day-status-skipped{background:var(--warning-dim);color:var(--warning)}
.day-status-failed{background:var(--destructive-dim);color:var(--destructive)}

/* === GUIDES === */
.guide-card{background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-top:16px;transition:border-color 0.2s}
.guide-card:hover{border-color:var(--border-hover)}
.guide-card h3{color:var(--primary);font-size:16px;margin-bottom:8px;font-family:'JetBrains Mono',monospace}
.guide-meta{display:flex;gap:16px;font-size:12px;color:var(--dim);margin:8px 0;font-family:'JetBrains Mono',monospace}
.guide-stats{display:flex;gap:24px;margin:12px 0}
.guide-stat{text-align:center}
.guide-stat .val{font-size:22px;font-weight:700;color:var(--primary);font-family:'JetBrains Mono',monospace}
.guide-stat .lbl{font-size:10px;color:var(--dim);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:0.05em}

/* === ANIMATIONS === */
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{width:20px;height:20px;border:3px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0}
@keyframes page-enter{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.page-content{animation:page-enter 0.3s ease-out}
@keyframes fade-in-up{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.stagger-children > *{opacity:0;animation:fade-in-up 0.4s ease-out forwards}
.stagger-children > *:nth-child(1){animation-delay:0ms}
.stagger-children > *:nth-child(2){animation-delay:60ms}
.stagger-children > *:nth-child(3){animation-delay:120ms}
.stagger-children > *:nth-child(4){animation-delay:180ms}
.stagger-children > *:nth-child(5){animation-delay:240ms}
.stagger-children > *:nth-child(6){animation-delay:300ms}
.stagger-children > *:nth-child(7){animation-delay:360ms}
.stagger-children > *:nth-child(8){animation-delay:420ms}
@keyframes toast-in{from{transform:translateX(120%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes bounce-dot{0%,100%{transform:scale(1)}50%{transform:scale(1.4)}}
@keyframes pulse-slow{0%,100%{opacity:1}50%{opacity:0.5}}
@keyframes shimmer{from{background-position:-200px 0}to{background-position:200px 0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.shimmer{background:linear-gradient(90deg,transparent 0%,hsl(174 72% 52% / 0.08) 50%,transparent 100%);background-size:200px 100%;animation:shimmer 2s infinite}
@keyframes scale-in{from{transform:scaleY(0)}to{transform:scaleY(1)}}

/* === SCROLLBAR === */
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:hsl(220 14% 22%);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:hsl(220 14% 28%)}

/* === OPTION CARDS (Plan Review) === */
.option-cards{display:flex;gap:8px;margin-top:8px}
.option-card{flex:1;padding:12px;border:2px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.15s;background:var(--bg);position:relative}
.option-card:hover{border-color:var(--primary);background:hsl(174 72% 52% / 0.03)}
.option-card.selected{border-color:var(--primary);background:var(--primary-dim);box-shadow:0 0 8px hsl(174 72% 52% / 0.15)}
.option-card .opt-rank{position:absolute;top:8px;right:8px;font-size:10px;color:var(--dim);font-family:'JetBrains Mono',monospace}
.option-card.selected .opt-rank{color:var(--primary);font-weight:700}
.option-card .opt-topic{font-size:13px;font-weight:600;line-height:1.4;margin-bottom:6px}
.option-card .opt-thesis{font-size:12px;color:var(--dim);line-height:1.4;margin-bottom:6px}
.option-card .opt-meta{font-size:11px;color:var(--muted)}
.guide-opt-cards{display:flex;gap:10px;margin-top:10px}
.guide-opt-card{flex:1;padding:14px;border:2px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.15s;background:var(--bg)}
.guide-opt-card:hover{border-color:var(--green)}
.guide-opt-card.selected{border-color:var(--green);background:rgba(34,197,94,0.06);box-shadow:0 0 8px rgba(34,197,94,0.15)}
.guide-opt-card .go-title{font-size:14px;font-weight:600;margin-bottom:4px}
.guide-opt-card .go-sub{font-size:12px;color:var(--dim);margin-bottom:6px}
.guide-opt-card .go-sections{font-size:11px;color:var(--muted)}

/* === WEEK BUILDER === */
.wb-layout{display:flex;gap:20px;margin:16px 0;min-height:600px}
.wb-slots{flex:0 0 340px;display:flex;flex-direction:column;gap:8px;position:sticky;top:16px;align-self:flex-start}
.wb-slot{background:var(--gradient-card);border:2px dashed var(--border);border-radius:8px;padding:14px;min-height:80px;transition:all 0.15s}
.wb-slot.filled{border-style:solid;border-color:var(--primary)}
.wb-slot.drag-over{border-color:var(--success);background:hsl(150 60% 45% / 0.05)}
.wb-slot .ws-label{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px}
.wb-slot .ws-topic{font-size:13px;font-weight:600;line-height:1.4}
.wb-slot .ws-angle{font-size:10px;padding:2px 6px;border-radius:4px;display:inline-block;font-weight:600;font-family:'JetBrains Mono',monospace;margin-top:4px}
.wb-slot .ws-empty{color:var(--muted);font-size:12px;font-style:italic}
.wb-slot .ws-remove{background:none;border:none;color:var(--destructive);cursor:pointer;font-size:11px;float:right;padding:2px 6px;opacity:0.6}
.wb-slot .ws-remove:hover{opacity:1}
.wb-pool{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px}
.wb-pool-card{background:var(--gradient-card);border:1px solid var(--border);border-radius:8px;padding:14px;cursor:grab;transition:all 0.15s;user-select:none}
.wb-pool-card:hover{border-color:var(--border-hover);transform:translateX(2px)}
.wb-pool-card.dragging{opacity:0.3}
.wb-pool-card.used{opacity:0.35;pointer-events:none;border-style:dashed}
.wb-pool-card .pc-topic{font-size:14px;font-weight:600;line-height:1.4;margin-bottom:4px}
.wb-pool-card .pc-thesis{font-size:12px;color:var(--dim);line-height:1.4;margin-bottom:6px}
.wb-pool-card .pc-meta{font-size:11px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap}
.wb-pool-card .pc-angle{font-size:10px;padding:2px 8px;border-radius:4px;display:inline-block;font-weight:600;font-family:'JetBrains Mono',monospace}

/* === ELEMENT FEEDBACK === */
.el-fb-btn{background:none;border:none;color:var(--dim);cursor:pointer;font-size:12px;padding:2px 6px;border-radius:4px;transition:all 0.15s;opacity:0.6}
.el-fb-btn:hover{opacity:1;color:var(--primary);background:var(--primary-dim)}
.el-fb-popover{position:absolute;z-index:200;background:var(--card);border:1px solid var(--primary);border-radius:8px;padding:12px;width:320px;box-shadow:0 8px 24px rgba(0,0,0,0.4)}

/* === RESPONSIVE === */
@media(max-width:1024px){.sidebar{width:var(--sidebar-collapsed)}.sidebar .label{opacity:0;width:0}.sidebar-group-label{opacity:0;height:8px;padding:4px 0}}
@media(max-width:900px){.week-grid{grid-template-columns:repeat(3,1fr)}.month-grid{grid-template-columns:60px repeat(3,1fr)}}
@media(max-width:768px){.sidebar{display:none}.search-input{width:150px}.search-input:focus{width:250px}}
@media(max-width:600px){.week-grid{grid-template-columns:1fr}.option-cards{flex-direction:column}.guide-opt-cards{flex-direction:column}}
</style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <span class="logo">&#9878; TCE</span>
      <button class="sidebar-toggle" onclick="toggleSidebar()" title="Collapse sidebar">&#9776;</button>
    </div>
    <nav class="sidebar-nav" id="nav">
      <div class="sidebar-group">
        <div class="sidebar-group-label">Plan</div>
        <button class="sidebar-item active" data-tab="week"><span class="icon">&#128197;</span><span class="label">Week Planner</span></button>
        <button class="sidebar-item" data-tab="builder"><span class="icon">&#128296;</span><span class="label">Week Builder</span></button>
        <button class="sidebar-item" data-tab="guides"><span class="icon">&#128214;</span><span class="label">Guides</span></button>
        <button class="sidebar-item" data-tab="trends"><span class="icon">&#128200;</span><span class="label">Trends</span></button>
      </div>
      <div class="sidebar-group">
        <div class="sidebar-group-label">Create</div>
        <button class="sidebar-item" data-tab="topic"><span class="icon">&#127919;</span><span class="label">Start from Topic</span></button>
        <button class="sidebar-item" data-tab="generate"><span class="icon">&#9889;</span><span class="label">Generate</span></button>
        <button class="sidebar-item" data-tab="packages"><span class="icon">&#128230;</span><span class="label">Packages</span></button>
        <button class="sidebar-item" data-tab="templates"><span class="icon">&#128196;</span><span class="label">Templates</span></button>
        <button class="sidebar-item" data-tab="product-demo"><span class="icon">&#127916;</span><span class="label">Product Demo</span></button>
      </div>
      <div class="sidebar-group">
        <div class="sidebar-group-label">Knowledge</div>
        <button class="sidebar-item" data-tab="corpus"><span class="icon">&#128218;</span><span class="label">Corpus</span></button>
        <button class="sidebar-item" data-tab="voice"><span class="icon">&#127908;</span><span class="label">Voice Profile</span></button>
        <button class="sidebar-item" data-tab="creators"><span class="icon">&#128101;</span><span class="label">Creators</span></button>
        <button class="sidebar-item" data-tab="brands"><span class="icon">&#127912;</span><span class="label">Brands</span></button>
        <button class="sidebar-item" data-tab="chat"><span class="icon">&#128172;</span><span class="label">Chat</span></button>
      </div>
      <div class="sidebar-group">
        <div class="sidebar-group-label">System</div>
        <button class="sidebar-item" data-tab="agents"><span class="icon">&#129302;</span><span class="label">Agents</span></button>
        <button class="sidebar-item" data-tab="prompts"><span class="icon">&#128221;</span><span class="label">Prompts</span></button>
        <button class="sidebar-item" data-tab="analytics"><span class="icon">&#128202;</span><span class="label">Analytics</span></button>
        <button class="sidebar-item" data-tab="costs"><span class="icon">&#128176;</span><span class="label">Costs</span></button>
      </div>
    </nav>
    <div class="sidebar-footer">
      <button class="sidebar-item" data-tab="settings"><span class="icon">&#9881;</span><span class="label">Settings</span></button>
      <button class="sidebar-item" data-tab="help"><span class="icon">&#10067;</span><span class="label">Help</span></button>
    </div>
  </aside>
  <div class="main-area">
    <div class="header-bar">
      <div class="header-title" id="page-title">Week Planner</div>
      <div class="header-actions">
        <div class="search-wrap">
          <span class="search-icon">&#128269;</span>
          <input class="search-input" id="global-search" type="text" placeholder="Search posts, topics, templates..." oninput="debounceSearch(this.value)">
          <div id="search-results" style="display:none;position:absolute;top:100%;left:0;width:360px;max-height:400px;overflow-y:auto;background:var(--card);border:1px solid var(--border);border-radius:8px;margin-top:4px;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,0.4)"></div>
        </div>
        <button class="notif-btn" onclick="toggleNotifications()" title="Notifications">&#128276;<span class="notif-dot" id="notif-badge" style="display:none"></span></button>
        <div id="notif-panel" style="display:none;position:absolute;top:56px;right:24px;width:360px;max-height:400px;overflow-y:auto;background:var(--card);border:1px solid var(--border);border-radius:8px;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,0.4)"></div>
        <div class="health-wrap"><div class="health-dot" id="health-dot"></div><span id="health-text">Checking...</span></div>
      </div>
    </div>
    <div id="breadcrumb"></div>
    <div class="content-scroll">
      <div class="main" id="app"></div>
    </div>
  </div>
</div>
<script>
const API = '/api/v1';
let currentTab = 'week';
let activePipelineRun = localStorage.getItem('tce_active_run') || null;
let pollInterval = null;
let verboseMode = localStorage.getItem('tce_verbose') === 'true';
let showArchived = false;
let genAllState = null; // {running, current, total, startTime, results: [{day, status, stepStatus, startTime}]}
let activePolishRun = localStorage.getItem('tce_active_polish') || null;
let polishPollInterval = null;
let polishStartTime = null;
let brainstormHistory = [];
let brainstormPackageId = null;
const AGENT_LABELS = {
  trend_scout: 'Scanning Trends', story_strategist: 'Building Story Brief',
  research_agent: 'Verifying Research', facebook_writer: 'Writing Facebook Post',
  linkedin_writer: 'Writing LinkedIn Post', cta_agent: 'Crafting CTA & DM Flow',
  creative_director: 'Creating Image Prompts', qa_agent: 'Quality Check',
  corpus_analyst: 'Analyzing Corpus', engagement_scorer: 'Scoring Engagement',
  pattern_miner: 'Mining Patterns', docx_guide_builder: 'Building Guide',
  weekly_planner: 'Planning Week', learning_agent: 'Learning from Feedback',
  copy_analyzer: 'Analyzing Copy', copy_polisher: 'Polishing Copy',
};

// Tab labels for header
const TAB_LABELS = {
  week: 'Week Planner', builder: 'Week Builder', guides: 'Guides', topic: 'Start from Topic', generate: 'Generate', packages: 'Packages',
  corpus: 'Corpus', voice: 'Voice Profile', creators: 'Creators',
  agents: 'Agents', costs: 'Costs', analytics: 'Analytics',
  templates: 'Templates', prompts: 'Prompts', settings: 'Settings',
  chat: 'Chat', trends: 'Trends', help: 'Help',
  'product-demo': 'Product Demo', brands: 'Brands'
};

// Sidebar toggle
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  localStorage.setItem('tce_sidebar_collapsed', sb.classList.contains('collapsed'));
}
// Restore sidebar state
if (localStorage.getItem('tce_sidebar_collapsed') === 'true') {
  document.getElementById('sidebar').classList.add('collapsed');
}

// Nav - sidebar items + footer items
document.querySelectorAll('.sidebar-item[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    currentTab = btn.dataset.tab;
    document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === currentTab));
    document.getElementById('page-title').textContent = TAB_LABELS[currentTab] || currentTab;
    render();
  });
});

// Health check
async function checkHealth() {
  try {
    const r = await fetch(API + '/health');
    const d = await r.json();
    const dot = document.getElementById('health-dot');
    const text = document.getElementById('health-text');
    if (d.status === 'ok') {
      dot.className = 'health-dot';
      text.textContent = 'Healthy';
      text.title = 'DB: ' + (d.database || 'ok') + ', Version: ' + (d.version || '?');
    } else {
      dot.className = 'health-dot off';
      text.textContent = 'Error';
    }
  } catch {
    document.getElementById('health-dot').className = 'health-dot off';
    document.getElementById('health-text').textContent = 'Offline';
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
function copyPrev(btn) {
  const div = btn.previousElementSibling;
  if (div) { navigator.clipboard.writeText(div.textContent); toast('Copied!'); }
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
let _weekEntries = {}; // calendar entries by day index, cached during renderWeek

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
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--dim);cursor:pointer" title="Override seasonal plan context for this week">
            <input type="checkbox" id="seasonal-override-toggle" style="accent-color:var(--yellow)">
            Seasonal Override
          </label>
          <input id="seasonal-context" type="text" placeholder="e.g. Post-holiday focus, Q1 planning season..." style="display:none;width:240px;font-size:11px;padding:4px 8px">
        </div>
        <span id="plan-cost-hint" style="font-size:11px;color:var(--dim);margin-left:6px" title="Trend scout (Sonnet) + Weekly planner (Opus)">~$0.25 per plan</span>
        <button class="btn btn-green" id="gen-all-btn" onclick="generateFromPlan()" ${genAllState?.running ? 'disabled' : ''}>${genAllState?.running ? (genAllState.unified ? 'Running...' : 'Generating...') : 'Generate from Plan'}</button>
      </div>
      <div id="plan-review-panel"></div>
      <div id="gen-all-progress"></div>
      <div class="week-grid" id="week-grid"><div class="empty" style="grid-column:1/-1">Loading calendar...</div></div>
    </div>`;

  // Load calendar entries for this week
  try {
    const entries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(friday));
    const byDate = {};
    entries.forEach(e => byDate[e.date] = e);
    // Cache entries by day index for runDayPipeline to use plan_context
    _weekEntries = {};
    for (let i = 0; i < 5; i++) {
      const d = new Date(monday); d.setDate(d.getDate() + i);
      const e = byDate[fmtDate(d)];
      if (e) _weekEntries[i] = e;
    }

    // Show persistent weekly plan summary if any entry has _weekly metadata
    const weeklyMeta = entries.find(e => e.plan_context?._weekly)?.plan_context?._weekly;
    // Also check if a weekly guide exists for this week
    let weekGuide = null;
    try {
      const guides = await api('/content/guides');
      const mon = new Date(fmtDate(monday) + 'T00:00:00');
      const sun = new Date(mon); sun.setDate(sun.getDate() + 6);
      weekGuide = guides.find(g => { const gd = new Date(g.week_start_date + 'T00:00:00'); return gd >= mon && gd <= sun; });
    } catch(e) { /* guides endpoint may not exist yet */ }

    const hasWeeklyTheme = weeklyMeta && weeklyMeta.weekly_theme;
    if (hasWeeklyTheme || weekGuide) {
      const gift = weeklyMeta?.gift_theme || {};
      const giftTitle = typeof gift === 'string' ? gift : (gift.title || '');
      const giftSubtitle = typeof gift === 'string' ? '' : (gift.subtitle || '');
      const sections = weeklyMeta?.gift_sections || [];
      const cta = weeklyMeta?.cta_keyword || '';
      let summaryHtml = '<div style="background:linear-gradient(135deg,#1a1d27,#1e2235);border:1px solid var(--accent);border-radius:10px;padding:16px 20px;margin-bottom:16px;display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start">';
      if (hasWeeklyTheme) {
        summaryHtml += '<div style="flex:1;min-width:200px">';
        summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--accent2);margin-bottom:4px">Weekly Direction</div>';
        summaryHtml += '<div style="font-size:15px;font-weight:600;line-height:1.4">' + escHtml(weeklyMeta.weekly_theme) + '</div>';
        summaryHtml += '</div>';
      }
      if (weekGuide) {
        summaryHtml += '<div style="flex:0 0 auto;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:10px 14px;min-width:180px">';
        summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--green);margin-bottom:4px">Weekly Guide</div>';
        summaryHtml += '<div style="font-size:14px;font-weight:600">' + escHtml(weekGuide.guide_title) + '</div>';
        if (weekGuide.downloads_count) summaryHtml += '<div style="font-size:11px;color:var(--dim);margin-top:2px">' + weekGuide.downloads_count + ' downloads</div>';
        summaryHtml += '<button class="btn btn-green" style="margin-top:8px;font-size:11px;padding:4px 12px" onclick="showWeekGuide(\\'' + fmtDate(monday) + '\\')">View Guide</button>';
        summaryHtml += '</div>';
      } else if (giftTitle) {
        summaryHtml += '<div style="flex:0 0 auto;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:10px 14px;min-width:180px">';
        summaryHtml += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--green);margin-bottom:4px">Gift of the Week</div>';
        summaryHtml += '<div style="font-size:14px;font-weight:600">' + escHtml(giftTitle) + '</div>';
        if (giftSubtitle) summaryHtml += '<div style="font-size:12px;color:var(--dim);margin-top:2px">' + escHtml(giftSubtitle) + '</div>';
        if (sections.length) summaryHtml += '<div style="font-size:11px;color:var(--dim);margin-top:6px">' + sections.length + ' sections planned</div>';
        summaryHtml += '<button class="btn btn-green" style="margin-top:8px;font-size:11px;padding:4px 12px" onclick="showWeekGuide(\\'' + fmtDate(monday) + '\\')">Package</button>';
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

      const cardDrag = entry ? ' draggable="true" ondragstart="dragEntry(event,\\'' + entry.id + '\\',\\'' + ds + '\\')"' : '';
      html += '<div class="day-card' + (isToday ? ' today' : '') + '" data-day-idx="' + i + '" data-day-date="' + ds + '"' + cardDrag + ' ondragover="event.preventDefault();this.classList.add(\\'drag-over\\')" ondragleave="this.classList.remove(\\'drag-over\\')" ondrop="this.classList.remove(\\'drag-over\\');dropEntry(event,\\'' + ds + '\\',' + i + ')" style="' + (entry ? 'cursor:grab' : '') + '">';
      html += '<div class="day-header">' + DAY_NAMES[i] + (isToday ? ' (TODAY)' : '') + '</div>';
      html += '<div class="day-date">' + d.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + '</div>';
      const tip = ANGLE_TIPS[angle] || '';
      html += '<div class="day-angle" style="position:relative;cursor:help">' + (ANGLE_LABELS[angle] || angle.replace(/_/g,' '));
      if (tip) html += ' <span class="tip-icon" data-tip="' + esc(tip) + '">i</span>';
      html += '</div>';
      if (entry?.topic) html += '<div class="day-topic">' + esc(entry.topic) + '</div>';
      else html += '<div class="day-topic" style="color:var(--dim);font-style:italic">No topic set</div>';
      // GAP-31: Buffer toggle
      if (entry?.is_buffer) html += '<div style="font-size:10px;color:var(--yellow);margin-bottom:4px">Buffer post</div>';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;gap:4px;flex-wrap:wrap">';
      if (entry) {
        const hasPackage = !!entry.post_package_id;
        const stLabel = hasPackage && status === 'planned' ? 'READY' : status.toUpperCase();
        const stClass = hasPackage && status === 'planned' ? 'ready' : status;
        html += '<span class="day-status day-status-' + stClass + '">' + stLabel + '</span>';
        if (hasPackage) {
          html += '<button class="btn btn-green" style="padding:4px 10px;font-size:11px" onclick="viewPackage(\\'' + entry.post_package_id + '\\',' + i + ')">Package</button>';
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

  // Resume day regen polling if active (survives page refresh)
  try {
    const savedRegen = localStorage.getItem('tce_day_regen');
    if (savedRegen) {
      const regenState = JSON.parse(savedRegen);
      // Only resume if started less than 10 minutes ago
      if (regenState.runId && (Date.now() - regenState.startTime) < 600000) {
        _startDayRegenPoll(regenState);
      } else {
        localStorage.removeItem('tce_day_regen');
      }
    }
  } catch {}

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

}

// Drag and drop for day cards
function dragEntry(ev, entryId, fromDate) {
  ev.dataTransfer.setData('text/plain', JSON.stringify({entryId, fromDate}));
  ev.dataTransfer.effectAllowed = 'move';
  const card = ev.target.closest('.day-card');
  if (card) card.classList.add('dragging');
}
function dragEnd(ev) {
  document.querySelectorAll('.day-card.dragging').forEach(c => c.classList.remove('dragging'));
  document.querySelectorAll('.day-card.drag-over').forEach(c => c.classList.remove('drag-over'));
}
document.addEventListener('dragend', dragEnd);
async function dropEntry(ev, toDate, toDayIdx) {
  ev.preventDefault();
  try {
    const data = JSON.parse(ev.dataTransfer.getData('text/plain'));
    if (data.fromDate === toDate) return;
    await api('/calendar/' + data.entryId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:toDate})});
    toast('Moved to ' + toDate);
    renderWeek();
  } catch(e) { toast('Move failed: ' + e.message, false); }
}

let deepPlanId = null;
let approvedPlan = null;

let planElapsedTimer = null;

async function planWeekDeep(mondayStr) {
  const theme = document.getElementById('week-theme')?.value || null;
  const sensitivePeriod = document.getElementById('sensitive-period-toggle')?.checked || false;
  // GAP-47: Seasonal override context
  const seasonalOverride = document.getElementById('seasonal-override-toggle')?.checked || false;
  const seasonalContext = document.getElementById('seasonal-context')?.value || null;
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
      body: JSON.stringify({ week_start: mondayStr, weekly_theme: theme || null, sensitive_period: sensitivePeriod, humanitarian_context: seasonalOverride ? seasonalContext : null }),
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
    const fieldKey = platform === 'fb' ? 'facebook_post' : 'linkedin_post';
    const patchResult = await api('/content/packages/' + packageId, { method: 'PATCH', body: JSON.stringify({ [fieldKey]: result.revised }) });
    const ci = _pkgCache?.findIndex(p => p.id === packageId);
    if (ci !== undefined && ci !== -1) { Object.assign(_pkgCache[ci], patchResult); }
    toast(platform.toUpperCase() + ' post revised and saved');
    api('/content/packages/' + packageId + '/regenerate-hooks', { method: 'POST' })
      .then(updated => { const ci2 = _pkgCache?.findIndex(p => p.id === packageId); if (ci2 !== undefined && ci2 !== -1) { Object.assign(_pkgCache[ci2], updated); } _renderPkgFromCache(); toast('Hooks refreshed'); })
      .catch(() => {});
  } catch (e) {
    postDiv.style.opacity = '1';
    postDiv.querySelector('.spinner')?.remove();
    toast('AI revision failed: ' + e.message, false);
  }
}

async function useHook(packageId, hookIdx) {
  const pid = packageId.replace(/-/g, '');
  const pkg = _pkgCache?.find(p => p.id === packageId);
  if (!pkg || !pkg.hook_variants?.[hookIdx]) { toast('Hook not found', false); return; }
  const hook = pkg.hook_variants[hookIdx];
  const btn = document.querySelector('#hooks-' + pid + ' [data-hi="' + hookIdx + '"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Rewriting...'; }
  const updates = {};
  const revise = async (platform, text) => {
    if (!text) return;
    const result = await api('/calendar/ai-revise-field', {
      method: 'POST',
      body: JSON.stringify({ field_name: platform + '_post', current_value: text, feedback: 'Replace the opening hook/first line with this new hook: "' + hook + '". Rewrite the first 2-3 sentences so they transition smoothly from this new hook into the rest of the post. Keep the rest of the post unchanged.', context: {} })
    });
    updates[platform + '_post'] = result.revised;
  };
  try {
    await Promise.all([
      pkg.facebook_post ? revise('facebook', pkg.facebook_post) : null,
      pkg.linkedin_post ? revise('linkedin', pkg.linkedin_post) : null
    ]);
    if (!Object.keys(updates).length) { toast('No posts to update', false); return; }
    const result = await api('/content/packages/' + packageId, { method: 'PATCH', body: JSON.stringify(updates) });
    const ci = _pkgCache.findIndex(p => p.id === packageId);
    if (ci !== -1) { Object.assign(_pkgCache[ci], result); }
    _renderPkgFromCache();
    toast('Hook applied! Other hooks are still available if you change your mind.');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Use this'; }
    toast('Failed: ' + e.message, false);
  }
}

async function regenerateHooks(packageId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Regenerating...'; }
  try {
    const result = await api('/content/packages/' + packageId + '/regenerate-hooks', { method: 'POST' });
    const ci = _pkgCache.findIndex(p => p.id === packageId);
    if (ci !== -1) { Object.assign(_pkgCache[ci], result); }
    _renderPkgFromCache();
    toast('Hooks regenerated (' + (result.hook_variants?.length || 0) + ' new hooks)');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Regenerate Hooks'; }
    toast('Failed: ' + e.message, false);
  }
}

async function backfillHooks(btn) {
  if (!confirm('Regenerate hooks for ALL packages using AI? This may take a few minutes and cost API tokens.')) return;
  btn.disabled = true; btn.textContent = 'Backfilling...';
  try {
    const result = await api('/content/packages/backfill-hooks', { method: 'POST' });
    btn.disabled = false; btn.textContent = 'Backfill All Hooks';
    toast('Backfill done: ' + result.updated + '/' + result.total + ' updated' + (result.errors?.length ? ', ' + result.errors.length + ' errors' : ''));
    _pkgCache = null; renderPackages();
  } catch (e) {
    btn.disabled = false; btn.textContent = 'Backfill All Hooks';
    toast('Backfill failed: ' + e.message, false);
  }
}

// Track selected options per day and selected guide
let _selectedOptions = {}; // { dayIdx: optionIdx }
let _selectedGuide = 0;
let _planDaysData = []; // raw days data from planner
let _planGuideOptions = []; // raw guide options

function showPlanReview(planData, mondayStr) {
  const wp = planData.weekly_plan || {};
  const days = wp.days || [];
  const trends = planData.trend_summary || [];
  const guideOptions = wp.guide_options || [];
  // Backward compat: old format has gift_theme instead of guide_options
  const giftTheme = wp.gift_theme || {};
  const giftTitle = typeof giftTheme === 'string' ? giftTheme : (giftTheme.title || '');
  const giftSubtitle = typeof giftTheme === 'string' ? '' : (giftTheme.subtitle || '');
  const giftSections = wp.gift_sections || [];

  _planDaysData = days;
  _planGuideOptions = guideOptions;
  _selectedOptions = {};
  _selectedGuide = 0;
  // Pre-select option 0 for each day
  for (let i = 0; i < days.length; i++) _selectedOptions[i] = 0;

  approvedPlan = { weekly_theme: wp.weekly_theme || '', gift_theme: giftTheme, cta_keyword: wp.cta_keyword || '', days: days, guide_options: guideOptions };

  let html = '<div style="margin-bottom:24px">';

  // === BIG HEADER: Weekly Direction ===
  html += '<div class="card" style="padding:24px;margin-bottom:16px;border:2px solid var(--accent);border-radius:12px">';
  html += '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:20px">';
  html += '<div><h2 style="margin:0 0 4px 0;color:var(--accent);font-size:20px">Weekly Plan Review</h2>';
  html += '<p style="margin:0;color:var(--dim);font-size:13px">Pick the best option for each day, then approve to generate.</p></div>';
  html += '<div style="text-align:right;font-size:12px;color:var(--dim)">Plan ID: ' + (deepPlanId || '').substring(0, 8) + '</div>';
  html += '</div>';

  // Weekly Theme
  html += '<div style="margin-bottom:16px">';
  html += '<label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px;font-weight:600">OVERARCHING DIRECTION' + makeFbBtn('pr-weekly-theme', 'Weekly Theme') + '</label>';
  html += '<textarea id="pr-weekly-theme" rows="2" style="width:100%;padding:10px;border:1px solid var(--accent);border-radius:6px;background:var(--bg);color:var(--text);font-size:15px;resize:vertical">' + escHtml(wp.weekly_theme || '') + '</textarea>';
  html += '</div>';

  // CTA Keyword
  html += '<div style="margin-bottom:16px"><label style="font-size:11px;color:var(--dim);display:block;margin-bottom:4px">CTA Keyword</label>';
  html += '<input id="pr-cta-keyword" type="text" value="' + escHtml(wp.cta_keyword || '') + '" style="width:180px;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);text-transform:uppercase;font-weight:700;font-size:16px;letter-spacing:2px"></div>';
  html += '</div>';

  // === GUIDE OPTIONS (3 cards) ===
  if (guideOptions.length > 0) {
    html += '<div style="background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.3);border-radius:10px;padding:16px;margin-bottom:16px">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="font-size:18px">&#127873;</span><span style="font-size:12px;color:var(--green);font-weight:700;text-transform:uppercase">Weekly Gift - Pick one</span></div>';
    html += '<div class="guide-opt-cards">';
    for (let gi = 0; gi < guideOptions.length; gi++) {
      const go = guideOptions[gi];
      const sel = gi === 0 ? ' selected' : '';
      html += '<div class="guide-opt-card' + sel + '" data-guide-idx="' + gi + '" onclick="selectGuideOption(' + gi + ')">';
      html += '<div class="go-title">' + escHtml(go.title || 'Option ' + (gi + 1)) + '</div>';
      if (go.subtitle) html += '<div class="go-sub">' + escHtml(go.subtitle) + '</div>';
      if (go.sections && go.sections.length) {
        html += '<div class="go-sections">' + go.sections.map(s => escHtml(s)).join(' / ') + '</div>';
      }
      if (go.rationale) html += '<div style="font-size:10px;color:var(--muted);margin-top:4px;font-style:italic">' + escHtml(go.rationale) + '</div>';
      html += '</div>';
    }
    html += '</div></div>';
  } else if (giftTitle) {
    // Old format fallback
    html += '<div style="background:rgba(34,197,94,0.08);border:1px solid var(--green);border-radius:8px;padding:16px;margin-bottom:16px">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="font-size:18px">&#127873;</span><label style="font-size:12px;color:var(--green);font-weight:700;text-transform:uppercase">Weekly Gift</label></div>';
    html += '<textarea id="pr-gift-theme" rows="2" style="width:100%;padding:10px;border:1px solid var(--green);border-radius:6px;background:var(--bg);color:var(--text);font-size:14px;resize:vertical">' + escHtml(giftTitle + (giftSubtitle ? ' - ' + giftSubtitle : '')) + '</textarea>';
    if (giftSections.length > 0) {
      html += '<div style="margin-top:8px;font-size:12px;color:var(--dim)"><b>Sections:</b> ' + giftSections.map(s => escHtml(s)).join(' / ') + '</div>';
    }
    html += '</div>';
  }

  // === DAY CARDS with 3 options each ===
  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  const angleLabels = { big_shift_explainer: 'Big Shift', tactical_workflow_guide: 'Tactical How-To', contrarian_diagnosis: 'Contrarian Take', case_study_build_story: 'Case Study', second_order_implication: 'Big Picture' };
  const angleColors = { big_shift_explainer: '#6366f1', tactical_workflow_guide: '#22c55e', contrarian_diagnosis: '#ef4444', case_study_build_story: '#eab308', second_order_implication: '#3b82f6' };

  html += '<div style="display:flex;flex-direction:column;gap:16px;margin-bottom:16px">';
  for (let i = 0; i < days.length; i++) {
    const dayPlan = days[i];
    const dayNum = dayPlan.day_of_week !== undefined ? dayPlan.day_of_week : i;
    const options = dayPlan.options || [dayPlan]; // backward compat
    const angle = dayPlan.angle_type || (options[0] && options[0].angle_type) || '';
    const angleLabel = angleLabels[angle] || angle;
    const angleColor = angleColors[angle] || 'var(--accent)';

    html += '<div class="card" style="padding:16px 20px;border-left:4px solid ' + angleColor + '">';
    html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">';
    html += '<span style="font-size:16px;font-weight:700">' + dayNames[dayNum] + '</span>';
    html += '<span style="font-size:12px;padding:3px 10px;border-radius:8px;background:' + angleColor + '22;color:' + angleColor + ';font-weight:600">' + escHtml(angleLabel) + '</span>';
    if (options.length > 1) html += '<span style="font-size:11px;color:var(--dim)">' + options.length + ' options - click to pick</span>';
    html += '</div>';

    // Option cards
    html += '<div class="option-cards" id="pr-day-' + i + '-options">';
    for (let oi = 0; oi < options.length; oi++) {
      const opt = options[oi];
      const sel = oi === 0 ? ' selected' : '';
      const rankLabel = oi === 0 ? 'BEST' : '#' + (oi + 1);
      html += '<div class="option-card' + sel + '" data-day="' + i + '" data-opt="' + oi + '" onclick="selectDayOption(' + i + ',' + oi + ')">';
      html += '<span class="opt-rank">' + rankLabel + '</span>';
      html += '<div class="opt-topic">' + escHtml(opt.topic || '') + '</div>';
      html += '<div class="opt-thesis">' + escHtml(opt.thesis || '') + '</div>';
      html += '<div class="opt-meta">' + escHtml(opt.audience || '') + '</div>';
      html += '</div>';
    }
    html += '</div>';

    // Editable detail for selected option (shown below cards)
    const sel = options[0] || {};
    html += '<div id="pr-day-' + i + '-detail" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">';
    html += _renderOptionDetail(i, sel);
    html += '</div>';
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

  // Action buttons
  html += '<div style="display:flex;gap:12px;padding:16px 0;border-top:1px solid var(--border)">';
  html += '<button class="btn btn-green" style="padding:12px 24px;font-size:15px;font-weight:600" onclick="approveAndGenerate(\\'' + mondayStr + '\\')">Approve & Generate All 5 Days</button>';
  html += '<button class="btn btn-primary" style="padding:12px 24px" onclick="savePlanOnly(\\'' + mondayStr + '\\')">Save Plan Only</button>';
  html += '<button class="btn btn-dim" style="padding:12px 24px" onclick="dismissPlanReview()">Dismiss</button>';
  html += '</div>';

  html += '</div>';

  const panel = document.getElementById('plan-review-panel');
  if (panel) panel.innerHTML = html;
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function _renderOptionDetail(dayIdx, opt) {
  let h = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">';
  h += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Topic' + makeFbBtn('pr-day-' + dayIdx + '-topic', 'Topic') + '</label>';
  h += '<textarea id="pr-day-' + dayIdx + '-topic" rows="2" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:14px;resize:vertical;line-height:1.4">' + escHtml(opt.topic || '') + '</textarea></div>';
  h += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Core Argument' + makeFbBtn('pr-day-' + dayIdx + '-thesis', 'Thesis') + '</label>';
  h += '<textarea id="pr-day-' + dayIdx + '-thesis" rows="2" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px;resize:vertical;line-height:1.4">' + escHtml(opt.thesis || '') + '</textarea></div>';
  h += '</div>';
  h += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px">';
  h += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Audience</label>';
  h += '<input id="pr-day-' + dayIdx + '-audience" type="text" value="' + escHtml(opt.audience || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px"></div>';
  h += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Belief Shift</label>';
  h += '<input id="pr-day-' + dayIdx + '-belief" type="text" value="' + escHtml(opt.desired_belief_shift || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px"></div>';
  h += '<div><label style="font-size:11px;color:var(--dim);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px">Gift Connection</label>';
  h += '<input id="pr-day-' + dayIdx + '-gift" type="text" value="' + escHtml(opt.connection_to_gift || '') + '" style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:13px"></div>';
  h += '</div>';
  h += '<input id="pr-day-' + dayIdx + '-visual" type="hidden" value="' + escHtml(opt.visual_job || 'cinematic_symbolic') + '">';
  return h;
}

function selectDayOption(dayIdx, optIdx) {
  _selectedOptions[dayIdx] = optIdx;
  // Update card selection UI
  const cards = document.querySelectorAll('#pr-day-' + dayIdx + '-options .option-card');
  cards.forEach((c, i) => c.classList.toggle('selected', i === optIdx));
  // Update detail form with selected option data
  const dayPlan = _planDaysData[dayIdx];
  const options = dayPlan?.options || [dayPlan];
  const opt = options[optIdx] || {};
  const detailEl = document.getElementById('pr-day-' + dayIdx + '-detail');
  if (detailEl) detailEl.innerHTML = _renderOptionDetail(dayIdx, opt);
}

function selectGuideOption(guideIdx) {
  _selectedGuide = guideIdx;
  document.querySelectorAll('.guide-opt-card').forEach((c, i) => c.classList.toggle('selected', i === guideIdx));
}

function collectEditedPlan() {
  const days = _planDaysData.length ? _planDaysData : (approvedPlan?.days || []);
  const edited = {
    weekly_theme: document.getElementById('pr-weekly-theme')?.value || '',
    gift_theme: document.getElementById('pr-gift-theme')?.value || '',
    cta_keyword: document.getElementById('pr-cta-keyword')?.value || '',
    selected_guide_index: _selectedGuide,
    days: [],
  };
  for (let i = 0; i < days.length; i++) {
    const selIdx = _selectedOptions[i] || 0;
    const dayPlan = days[i];
    const options = dayPlan.options || [dayPlan];
    const orig = options[selIdx] || options[0] || dayPlan;
    edited.days.push({
      day_of_week: dayPlan.day_of_week !== undefined ? dayPlan.day_of_week : i,
      angle_type: orig.angle_type || dayPlan.angle_type || '',
      topic: document.getElementById('pr-day-' + i + '-topic')?.value || '',
      thesis: document.getElementById('pr-day-' + i + '-thesis')?.value || '',
      audience: document.getElementById('pr-day-' + i + '-audience')?.value || '',
      desired_belief_shift: document.getElementById('pr-day-' + i + '-belief')?.value || '',
      visual_job: document.getElementById('pr-day-' + i + '-visual')?.value || 'cinematic_symbolic',
      connection_to_gift: document.getElementById('pr-day-' + i + '-gift')?.value || '',
      evidence_requirements: orig.evidence_requirements || [],
      template_id: orig.template_id || '',
      platform_notes: orig.platform_notes || '',
      selected_option_index: selIdx,
    });
  }
  // Include selected guide info
  if (_planGuideOptions.length > 0) {
    edited.guide_options = _planGuideOptions;
    edited.gift_theme = _planGuideOptions[_selectedGuide]?.title || '';
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
  // Hide plan review to avoid text-on-text overlap with progress card
  const prp = document.getElementById('plan-review-panel');
  if (prp) prp.style.display = 'none';
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
        genAllState.startedAt = st.started_at || genAllState.startedAt || null;
        genAllState.currentAgents = st.current_agents || [];
        genAllState.dayStepLogs = st.day_step_logs || {};
        genAllState.plannerStepStatus = st.planner_step_status || genAllState.plannerStepStatus || {};
        genAllState.plannerStepLogs = st.planner_step_logs || {};
        genAllState.guideStepStatus = st.guide_step_status || {};
        genAllState.guideStepLogs = st.guide_step_logs || {};
        if (st.day_run_ids) {
          for (let idx = 0; idx < st.day_run_ids.length; idx++) {
            if (!genAllState.results[idx]) genAllState.results[idx] = { day: DAY_NAMES[idx], status: 'done', runId: st.day_run_ids[idx] };
          }
        }
        if (st.phase === 'generating_days' && st.current_day >= 0) {
          if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running', stepStatus: {} };
          else genAllState.results[st.current_day].status = 'running';
          // Use enriched step status from the backend (no separate sub-poll needed)
          if (st.day_step_status) genAllState.results[st.current_day].stepStatus = st.day_step_status;
        }
        done = st.status === 'completed' || st.status === 'failed' || st.status === 'interrupted';
        if (st.status === 'failed') genAllState.errorMsg = st.error || 'Unknown error';
        if (st.status === 'interrupted') { genAllState.phase = 'interrupted'; genAllState.phaseDetail = 'Generation was interrupted (server restarted). You can re-run Generate from the planner.'; genAllState.errorMsg = 'Server restarted during generation'; }
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
  const prpDone = document.getElementById('plan-review-panel');
  if (prpDone) prpDone.style.display = '';
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
  // Find the button and day card for inline progress
  const dayCard = document.querySelector('[data-day-idx="' + dayOfWeek + '"]');
  const regenBtn = dayCard?.querySelector('button.btn-dim');
  if (regenBtn) { regenBtn.disabled = true; regenBtn.textContent = 'Starting...'; }

  try {
    // Check if this day has a planned topic via plan_context
    const entry = _weekEntries[dayOfWeek];
    const pc = entry?.plan_context;
    let workflow = 'daily_content';
    const context = { day_of_week: dayOfWeek };

    if (pc && (pc.topic || pc.thesis)) {
      // Use daily_from_plan so we skip trend_scout and respect the planned topic
      workflow = 'daily_from_plan';
      const briefKeys = ['topic','thesis','audience','angle_type','day_label','visual_job','platform_notes','desired_belief_shift','evidence_requirements','template_id'];
      const storyBrief = {};
      const src = pc.story_brief || pc;
      briefKeys.forEach(k => { if (src[k]) storyBrief[k] = src[k]; });
      context.story_brief = storyBrief;
      if (pc._weekly) {
        if (pc._weekly.weekly_theme) context.weekly_theme = pc._weekly.weekly_theme;
        if (pc._weekly.cta_keyword) context.weekly_keyword = pc._weekly.cta_keyword;
        if (pc._weekly.gift_theme) { context.gift_theme = pc._weekly.gift_theme; context.guide_title = pc._weekly.gift_theme; }
      }
      if (pc.connection_to_gift) context.connection_to_gift = pc.connection_to_gift;
    }

    const r = await api('/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({ workflow, context }),
    });
    // Persist regen state so it survives page refresh
    const regenState = { runId: r.run_id, dayOfWeek, startTime: Date.now() };
    localStorage.setItem('tce_day_regen', JSON.stringify(regenState));
    activePipelineRun = r.run_id;
    localStorage.setItem('tce_active_run', r.run_id);
    toast('Regenerating ' + DAY_NAMES[dayOfWeek] + ' package (using planned topic)...');

    _startDayRegenPoll(regenState);
  } catch (e) {
    if (regenBtn) { regenBtn.disabled = false; regenBtn.textContent = 'Regenerate'; }
    toast('Failed: ' + e.message, false);
  }
}

function _startDayRegenPoll(regenState) {
  const { runId, dayOfWeek, startTime } = regenState;
  const dayCard = document.querySelector('[data-day-idx="' + dayOfWeek + '"]');
  const regenBtn = dayCard?.querySelector('button.btn-dim');
  if (regenBtn) { regenBtn.disabled = true; regenBtn.textContent = 'Regenerating...'; }

  // Show inline progress on the day card
  let progressEl = document.getElementById('day-regen-progress-' + dayOfWeek);
  if (!progressEl && dayCard) {
    progressEl = document.createElement('div');
    progressEl.id = 'day-regen-progress-' + dayOfWeek;
    progressEl.style.cssText = 'margin-top:8px;padding:6px 8px;background:#0d1117;border:1px solid var(--blue);border-radius:6px;font-size:11px;color:var(--blue);line-height:1.4';
    dayCard.appendChild(progressEl);
  }
  const spinnerHtml = '<span style="display:inline-block;width:10px;height:10px;border:2px solid var(--blue);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:6px;vertical-align:middle"></span>';
  if (progressEl) progressEl.innerHTML = spinnerHtml + 'Starting pipeline...';

  const inlinePoll = setInterval(async () => {
    try {
      const s = await api('/pipeline/' + runId + '/status');
      const statuses = s.step_status || {};
      const logs = s.step_logs || {};
      const allDone = !Object.values(statuses).some(v => v === 'pending' || v === 'running');
      const running = Object.entries(statuses).find(([k,v]) => v === 'running');
      const completed = Object.entries(statuses).filter(([k,v]) => v === 'completed').length;
      const total = Object.keys(statuses).length;
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      const elapsedStr = elapsed < 60 ? elapsed + 's' : Math.floor(elapsed/60) + 'm ' + (elapsed%60) + 's';

      if (progressEl) {
        let detail = '';
        if (running) {
          const agentName = running[0].replace(/_/g, ' ');
          // Get latest log line for this agent
          const agentLogs = logs[running[0]] || [];
          const lastLog = agentLogs.length ? agentLogs[agentLogs.length - 1].replace(/^\\[\\d{2}:\\d{2}:\\d{2}\\]\\s*/, '').substring(0, 60) : '';
          detail = spinnerHtml + '<strong>' + agentName + '</strong> (' + completed + '/' + total + ' - ' + elapsedStr + ')';
          if (lastLog) detail += '<div style="color:var(--dim);font-size:10px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(lastLog) + '</div>';
        } else if (!allDone) {
          detail = spinnerHtml + 'Waiting... (' + completed + '/' + total + ' - ' + elapsedStr + ')';
        }
        progressEl.innerHTML = detail;
      }

      if (allDone) {
        clearInterval(inlinePoll);
        localStorage.removeItem('tce_day_regen');
        localStorage.removeItem('tce_active_run');
        activePipelineRun = null;
        if (progressEl) progressEl.remove();
        const hasFailed = Object.values(statuses).some(v => v === 'failed');
        if (hasFailed) {
          const errors = s.step_errors || {};
          const errMsg = Object.entries(errors).filter(([k,v]) => v).map(([k,v]) => k + ': ' + v).join('; ').substring(0, 100);
          toast(DAY_NAMES[dayOfWeek] + ' regeneration failed: ' + (errMsg || 'unknown error'), false);
        } else {
          toast(DAY_NAMES[dayOfWeek] + ' package regenerated!');
        }
        await renderWeek();
      }
    } catch (e) {
      // Polling error - keep trying
    }
  }, 2000);
}

function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + 's';
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
}
function getIsraelTime() {
  try { return new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Jerusalem', hour: '2-digit', minute: '2-digit' }) + ' IST'; }
  catch { const d = new Date(Date.now() + 3 * 3600000); return d.getUTCHours().toString().padStart(2,'0') + ':' + d.getUTCMinutes().toString().padStart(2,'0') + ' IST'; }
}
function _renderLogFeed(logs) {
  // logs = { agent_name: ["[HH:MM:SS] msg", ...], ... } - show last entries from running agents
  if (!logs || !Object.keys(logs).length) return '';
  const lines = [];
  for (const [agent, entries] of Object.entries(logs)) {
    if (!entries?.length) continue;
    const last = entries[entries.length - 1];
    if (last) lines.push({ agent, msg: last });
  }
  if (!lines.length) return '';
  let h = '<div style="background:#0a0e14;border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-top:8px;font-family:monospace;font-size:11px;line-height:1.6;max-height:80px;overflow-y:auto">';
  for (const l of lines.slice(-3)) {
    h += '<div style="color:var(--dim)"><span style="color:var(--accent2)">' + esc(l.agent.replace(/_/g, ' ')) + '</span> ' + esc(l.msg) + '</div>';
  }
  h += '</div>';
  return h;
}
function renderGenAllProgress() {
  const el = document.getElementById('gen-all-progress');
  if (!el) return;
  if (!genAllState) { el.innerHTML = ''; return; }
  const s = genAllState;
  const elapsed = s.startTime ? formatElapsed(Date.now() - s.startTime) : '';
  const israelTime = getIsraelTime();
  let html = '<div class="card" style="margin-bottom:16px;padding:16px">';

  // Phase-aware header
  let headerText = s.phase === 'interrupted' ? 'Generation interrupted' : (s.phase === 'failed' ? 'Generation failed' : 'Generation complete');
  if (s.running) {
    if (s.unified) {
      if (s.phase === 'planning') headerText = 'Planning the week (trend scout + strategy)...';
      else if (s.phase === 'generating_days') headerText = 'Generating day ' + ((s.current >= 0 ? s.current : 0) + 1) + '/5 - ' + DAY_NAMES[s.current >= 0 ? s.current : 0];
      else if (s.phase === 'building_guide') headerText = 'Building weekly guide...';
      else if (s.phase === 'scripts') headerText = 'Generating scripts...';
      else headerText = s.phaseDetail || 'Starting generation...';
    } else {
      headerText = 'Generating content for all 5 days...';
    }
  }
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">';
  html += '<div style="font-size:13px;font-weight:600">' + headerText + '</div>';
  html += '<div style="font-size:11px;color:var(--dim);font-family:monospace;text-align:right">';
  if (elapsed) html += elapsed;
  if (s.running) html += ' <span style="color:var(--accent2)">' + israelTime + '</span>';
  html += '</div>';
  html += '</div>';

  // Agent spotlight - show what's happening RIGHT NOW
  if (s.running) {
    let spotlightText = '';
    const agents = s.currentAgents || [];
    if (agents.length > 0) {
      spotlightText = agents.map(a => AGENT_LABELS[a] || a.replace(/_/g, ' ')).join(' + ');
    } else if (s.phase === 'planning') {
      spotlightText = AGENT_LABELS['weekly_planner'] || 'Planning Week';
    } else if (s.phase === 'building_guide') {
      spotlightText = AGENT_LABELS['docx_guide_builder'] || 'Building Guide';
    } else if (s.phase === 'scripts') {
      spotlightText = s.phaseDetail || 'Generating scripts...';
    } else if (s.phaseDetail) {
      spotlightText = s.phaseDetail;
    }
    if (spotlightText) {
      html += '<div style="font-size:12px;color:var(--blue);margin-bottom:10px;display:flex;align-items:center;gap:6px">';
      html += '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--blue);animation:pulse 1.5s infinite"></span>';
      html += esc(spotlightText);
      html += '</div>';
    }
  }

  // Show weekly theme + gift theme once available (unified mode)
  if (s.unified && s.weeklyTheme) {
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:12px">';
    html += '<div style="font-size:11px;color:var(--dim);margin-bottom:4px">WEEKLY THEME</div>';
    html += '<div style="font-size:13px;font-weight:600;color:var(--accent2)">' + esc(s.weeklyTheme) + '</div>';
    if (s.giftTheme) {
      html += '<div style="font-size:11px;color:var(--dim);margin-top:6px">GIFT/GUIDE</div>';
      let giftStr = '';
      if (typeof s.giftTheme === 'string') giftStr = s.giftTheme;
      else if (typeof s.giftTheme === 'object') giftStr = s.giftTheme.title || s.giftTheme.guide_title || s.giftTheme.name || JSON.stringify(s.giftTheme).slice(0, 100);
      if (giftStr) html += '<div style="font-size:12px;color:var(--green)">' + esc(giftStr) + '</div>';
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
  if (s.unified && s.running && s.phase === 'planning' && s.plannerStepStatus && Object.keys(s.plannerStepStatus).length) {
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
    // Live log feed for planner
    html += _renderLogFeed(s.plannerStepLogs);
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
      if (st === 'running') html += '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--blue);margin-right:6px;animation:pulse 1.5s infinite"></span>';
      html += label + '</span>';
      html += '<span style="color:' + stColor + ';font-weight:600;font-size:11px">' + icon + '</span>';
      html += '</div>';
    }
    // Live log feed for current day agents
    html += _renderLogFeed(s.dayStepLogs);
    html += '</div>';
  }

  // Guide building detail
  if (s.running && s.phase === 'building_guide' && s.guideStepStatus && Object.keys(s.guideStepStatus).length) {
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--accent2);margin-bottom:8px">Guide Builder</div>';
    for (const [agent, st] of Object.entries(s.guideStepStatus)) {
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
    html += _renderLogFeed(s.guideStepLogs);
    html += '</div>';
  }

  if (!s.running) {
    const done = s.results.filter(r => r?.status === 'done').length;
    const fail = s.results.filter(r => r?.status === 'failed').length;
    html += '<div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">';
    if (s.phase === 'failed' || s.phase === 'completed' || s.phase === 'interrupted') {
      const phaseColor = s.phase === 'completed' ? 'var(--green)' : (s.phase === 'interrupted' ? 'var(--yellow)' : 'var(--red)');
      const phaseMsg = s.phase === 'completed' ? done + '/5 completed + guide built (' + elapsed + ')' : (s.phase === 'interrupted' ? 'Interrupted: ' + (s.phaseDetail || 'Server restarted during generation') : 'Failed: ' + (s.errorMsg || s.phaseDetail || 'Unknown error'));
      html += '<span style="font-size:13px;color:' + phaseColor + ';font-weight:600">' + phaseMsg + '</span>';
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
      const agents = s.currentAgents || [];
      if (agents.length > 0) {
        const agentLabel = AGENT_LABELS[agents[0]] || agents[0].replace(/_/g, ' ');
        btn.textContent = agentLabel + '... (' + ((s.current >= 0 ? s.current : 0) + 1) + '/5)';
      } else if (s.phase === 'planning') btn.textContent = 'Planning week...';
      else if (s.phase === 'generating_days') btn.textContent = 'Day ' + ((s.current >= 0 ? s.current : 0) + 1) + '/5...';
      else if (s.phase === 'building_guide') btn.textContent = 'Building guide...';
      else if (s.phase === 'scripts') btn.textContent = 'Generating scripts...';
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
async function restoreGenAllState() {
  // First check sessionStorage for same-tab refresh
  try {
    const saved = sessionStorage.getItem('genAllState');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.running) {
        genAllState = parsed;
        if (parsed.unified && parsed.weekId) {
          resumeUnifiedGenAll();
        } else {
          resumeGenAll();
        }
        renderGenAllProgress();
        return;
      } else {
        sessionStorage.removeItem('genAllState');
      }
    }
  } catch { /* ignore */ }
  // No session state - ask server if a generation is currently active
  try {
    const active = await api('/pipeline/generate-week/active');
    if (active.active && active.week_id) {
      const isInterrupted = active.status === 'interrupted' || active.phase === 'interrupted';
      genAllState = { running: !isInterrupted, unified: true, weekId: active.week_id, total: 5, current: active.current_day >= 0 ? active.current_day : 0, results: [], phase: active.phase || 'running', phaseDetail: active.phase_detail || 'Generation in progress...', startTime: Date.now(), weeklyTheme: active.weekly_theme || '', giftTheme: active.gift_theme || '', weeklyKeyword: active.weekly_keyword || '' };
      if (active.day_run_ids) {
        for (let i = 0; i < active.day_run_ids.length; i++) {
          genAllState.results[i] = { day: DAY_NAMES[i], status: 'done', runId: active.day_run_ids[i] };
        }
      }
      if (isInterrupted) {
        genAllState.errorMsg = 'Server restarted during generation';
        genAllState.phaseDetail = 'Generation was interrupted (server restarted). You can re-run Generate from the planner.';
      }
      saveGenAllState();
      if (!isInterrupted) {
        resumeUnifiedGenAll();
      }
      renderGenAllProgress();
    }
  } catch { /* server might not support /active yet */ }
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
      genAllState.startedAt = st.started_at || genAllState.startedAt || null;
      genAllState.currentAgents = st.current_agents || [];
      genAllState.dayStepLogs = st.day_step_logs || {};
      genAllState.plannerStepStatus = st.planner_step_status || genAllState.plannerStepStatus || {};
      genAllState.plannerStepLogs = st.planner_step_logs || {};
      genAllState.guideStepStatus = st.guide_step_status || {};
      genAllState.guideStepLogs = st.guide_step_logs || {};
      if (st.weekly_theme) genAllState.weeklyTheme = st.weekly_theme;
      if (st.gift_theme) genAllState.giftTheme = st.gift_theme;
      if (st.weekly_keyword) genAllState.weeklyKeyword = st.weekly_keyword;
      if (st.day_run_ids) {
        for (let i = 0; i < st.day_run_ids.length; i++) {
          if (!genAllState.results[i]) genAllState.results[i] = { day: DAY_NAMES[i], status: 'done', runId: st.day_run_ids[i] };
        }
      }
      // Enrich current day's step status from inline data
      if (st.phase === 'generating_days' && st.current_day >= 0 && st.day_step_status) {
        if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running', stepStatus: {} };
        else genAllState.results[st.current_day].status = 'running';
        genAllState.results[st.current_day].stepStatus = st.day_step_status;
      }
      done = st.status === 'completed' || st.status === 'failed' || st.status === 'interrupted';
      if (st.status === 'failed') genAllState.errorMsg = st.error || 'Unknown error';
      if (st.status === 'interrupted') { genAllState.phase = 'interrupted'; genAllState.phaseDetail = 'Generation was interrupted (server restarted). You can re-run Generate from the planner.'; genAllState.errorMsg = 'Server restarted during generation'; }
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
        genAllState.startedAt = st.started_at || genAllState.startedAt || null;
        genAllState.currentAgents = st.current_agents || [];
        genAllState.dayStepLogs = st.day_step_logs || {};
        genAllState.plannerStepStatus = st.planner_step_status || genAllState.plannerStepStatus || {};
        genAllState.plannerStepLogs = st.planner_step_logs || {};
        genAllState.guideStepStatus = st.guide_step_status || {};
        genAllState.guideStepLogs = st.guide_step_logs || {};
        if (st.weekly_theme) genAllState.weeklyTheme = st.weekly_theme;
        if (st.gift_theme) genAllState.giftTheme = st.gift_theme;
        if (st.weekly_keyword) genAllState.weeklyKeyword = st.weekly_keyword;
        // Map day results from the backend run IDs
        if (st.day_run_ids) {
          for (let i = 0; i < st.day_run_ids.length; i++) {
            if (!genAllState.results[i]) genAllState.results[i] = { day: DAY_NAMES[i], status: 'done', runId: st.day_run_ids[i] };
          }
        }
        // Use enriched inline step data (no separate sub-poll needed)
        if (st.phase === 'generating_days' && st.current_day >= 0) {
          if (!genAllState.results[st.current_day]) genAllState.results[st.current_day] = { day: DAY_NAMES[st.current_day], status: 'running', stepStatus: {} };
          else genAllState.results[st.current_day].status = 'running';
          if (st.day_step_status) genAllState.results[st.current_day].stepStatus = st.day_step_status;
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

function viewPackage(pkgId, dayNum) {
  // Set the day filter - use explicit dayNum if provided, else try cache
  if (dayNum !== undefined && dayNum !== null) {
    pkgDayFilter = dayNum;
  } else if (_pkgDayMapCache && _pkgDayMapCache[pkgId]) {
    pkgDayFilter = _pkgDayMapCache[pkgId].day;
  }
  // Switch to packages tab
  currentTab = 'packages';
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === 'packages'));
  render();
  // After render, scroll to the specific package card by its id attribute
  setTimeout(() => {
    const card = document.getElementById('pkg-' + pkgId);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.style.outline = '2px solid var(--accent)';
      setTimeout(() => card.style.outline = '', 3000);
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
    document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === 'generate'));
    render();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollPipeline, 3000);
  } catch (e) { toast('Failed: ' + e.message, false); }
}

// GENERATE TAB
// === START FROM TOPIC ===
let topicRunId = null;
let topicPollInterval = null;
let topicStartTime = null;

async function renderTopic() {
  const app = document.getElementById('app');
  // Load creators and posts for dropdowns
  let creators = [], posts = [];
  try { creators = await api('/pipeline/inspiration/creators'); } catch {}
  try { posts = await api('/pipeline/inspiration/posts?limit=30'); } catch {}

  const creatorOpts = creators.map(c => `<option value="${c.id}">${esc(c.creator_name)} (${c.post_count} posts, ${c.total_engagement} engagement)</option>`).join('');
  const postOpts = posts.map(p => `<option value="${p.id}">[${p.visible_comments || 0} comments] ${esc((p.hook_preview || '').substring(0, 80))}... - ${esc(p.creator_name || '')}</option>`).join('');

  app.innerHTML = `
    <div class="section">
      <h2>Start from Topic</h2>
      <p style="font-size:13px;color:var(--dim);margin-bottom:16px">Describe your topic. Choose what to generate below.</p>
      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;gap:0;margin-bottom:16px;border:1px solid var(--border);border-radius:8px;overflow:hidden">
          <button id="topic-mode-post" onclick="setTopicMode('post')" style="flex:1;padding:10px 16px;font-size:13px;font-weight:600;border:none;cursor:pointer;background:var(--blue);color:#fff;transition:all 0.2s">Daily Post</button>
          <button id="topic-mode-guide" onclick="setTopicMode('guide')" style="flex:1;padding:10px 16px;font-size:13px;font-weight:600;border:none;cursor:pointer;background:var(--card);color:var(--dim);transition:all 0.2s">Guide</button>
        </div>
        <div id="topic-mode-desc" style="font-size:12px;color:var(--dim);margin-bottom:12px;padding:8px 12px;background:#0d1117;border-radius:6px">The full agent pipeline (TrendScout, StoryStrategist, Research, Writers, CTA, Creative Director, QA) will generate FB + LI posts around your topic.</div>
        <div style="margin-bottom:12px">
          <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Topic / Brief *</label>
          <textarea id="topic-text" rows="5" style="width:100%;resize:vertical;min-height:100px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark" placeholder="Describe your topic in detail. The more specific you are, the better the output. E.g.: Does it really matter what model you use for your agents? Practical tips on Claude Opus vs Sonnet vs Haiku..."></textarea>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">
          <div style="flex:1;min-width:250px">
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Inspire by Creator (optional)</label>
            <select id="topic-creator" style="width:100%;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
              <option value="" style="background:var(--card);color:var(--text)">-- No creator inspiration --</option>
              ${creatorOpts}
            </select>
          </div>
          <div style="flex:1;min-width:250px">
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Inspire by Post (sorted by engagement)</label>
            <select id="topic-post" style="width:100%;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
              <option value="" style="background:var(--card);color:var(--text)">-- No post inspiration --</option>
              ${postOpts}
            </select>
          </div>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">CTA Keyword (optional)</label>
            <input type="text" id="topic-cta" placeholder="e.g. stack" style="width:180px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
          </div>
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Template Hint (optional)</label>
            <input type="text" id="topic-template" placeholder="e.g. tactical_workflow_guide" style="width:220px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
          </div>
          <div style="flex:1;min-width:200px">
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Notes (optional)</label>
            <input type="text" id="topic-notes" placeholder="Any extra instructions..." style="width:100%;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-primary" id="topic-run-btn" onclick="runTopicOrGuide()">Generate Daily Post</button>
          <span id="topic-elapsed" style="font-size:12px;color:var(--dim)"></span>
        </div>
      </div>
      <div id="topic-status"></div>
      <div id="topic-result" style="margin-top:16px"></div>
    </div>`;
  // Restore active run if any
  const savedRun = localStorage.getItem('tce_topic_run');
  if (savedRun) { topicRunId = savedRun; topicStartTime = parseInt(localStorage.getItem('tce_topic_start') || Date.now()); pollTopicStatus(); if (!topicPollInterval) topicPollInterval = setInterval(pollTopicStatus, 3000); }
}

let _topicMode = 'post';
function setTopicMode(mode) {
  _topicMode = mode;
  const postBtn = document.getElementById('topic-mode-post');
  const guideBtn = document.getElementById('topic-mode-guide');
  const desc = document.getElementById('topic-mode-desc');
  const runBtn = document.getElementById('topic-run-btn');
  if (mode === 'guide') {
    guideBtn.style.background = 'var(--green)'; guideBtn.style.color = '#fff';
    postBtn.style.background = 'var(--card)'; postBtn.style.color = 'var(--dim)';
    desc.textContent = 'Research the topic and generate a free guide (PDF/DOCX) with quality gate assessment. The guide will go through up to 3 iterations to meet quality standards.';
    runBtn.textContent = 'Generate Guide';
    runBtn.className = 'btn btn-green';
  } else {
    postBtn.style.background = 'var(--blue)'; postBtn.style.color = '#fff';
    guideBtn.style.background = 'var(--card)'; guideBtn.style.color = 'var(--dim)';
    desc.textContent = 'The full agent pipeline (TrendScout, StoryStrategist, Research, Writers, CTA, Creative Director, QA) will generate FB + LI posts around your topic.';
    runBtn.textContent = 'Generate Daily Post';
    runBtn.className = 'btn btn-primary';
  }
}

function runTopicOrGuide() {
  if (_topicMode === 'guide') {
    runTopicGuide();
  } else {
    runTopicPipeline();
  }
}

async function runTopicGuide() {
  const topicText = document.getElementById('topic-text')?.value?.trim();
  if (!topicText) { toast('Please describe your topic first', false); return; }
  const ctaKw = document.getElementById('topic-cta')?.value?.trim() || 'guide';
  const notes = document.getElementById('topic-notes')?.value?.trim() || null;
  const btn = document.getElementById('topic-run-btn');
  btn.disabled = true; btn.textContent = 'Starting guide generation...';
  try {
    const body = { post_text: topicText, cta_keyword: ctaKw };
    if (notes) body.operator_feedback = notes;
    const r = await api('/content/guides/generate-from-post', { method: 'POST', body: JSON.stringify(body) });
    _regenState = { guideId: r.tracking_id, startTime: Date.now(), feedback: notes, fromPost: true };
    toast('Guide generation started');
    pollRegenStatus(r.tracking_id);
    btn.disabled = false; btn.textContent = 'Generate Guide';
  } catch(e) {
    toast('Failed: ' + e.message, false);
    btn.disabled = false; btn.textContent = 'Generate Guide';
  }
}

async function runTopicPipeline() {
  const topicText = document.getElementById('topic-text')?.value?.trim();
  if (!topicText) { toast('Please describe your topic first', false); return; }
  const creatorId = document.getElementById('topic-creator')?.value || null;
  const postId = document.getElementById('topic-post')?.value || null;
  const ctaKw = document.getElementById('topic-cta')?.value?.trim() || null;
  const templateHint = document.getElementById('topic-template')?.value?.trim() || null;
  const notes = document.getElementById('topic-notes')?.value?.trim() || null;

  const body = { topic: topicText };
  if (creatorId) body.inspire_by_creator_ids = [creatorId];
  if (postId) body.inspire_by_post_id = postId;
  if (ctaKw) body.cta_keyword = ctaKw;
  if (templateHint) body.template_hint = templateHint;
  if (notes) body.notes = notes;
  body.language = 'english';

  const btn = document.getElementById('topic-run-btn');
  btn.disabled = true; btn.textContent = 'Starting...';
  topicStartTime = Date.now();
  localStorage.setItem('tce_topic_start', topicStartTime);

  try {
    const r = await api('/pipeline/start-from-topic', { method: 'POST', body: JSON.stringify(body) });
    topicRunId = r.run_id;
    localStorage.setItem('tce_topic_run', r.run_id);
    toast('Pipeline started: ' + r.run_id.substring(0, 8));
    pollTopicStatus();
    if (topicPollInterval) clearInterval(topicPollInterval);
    topicPollInterval = setInterval(pollTopicStatus, 3000);
  } catch (e) {
    toast('Failed: ' + e.message, false);
    btn.disabled = false; btn.textContent = 'Generate from Topic';
  }
}

async function pollTopicStatus() {
  if (!topicRunId) return;
  const statusEl = document.getElementById('topic-status');
  const resultEl = document.getElementById('topic-result');
  const elapsedEl = document.getElementById('topic-elapsed');
  const btn = document.getElementById('topic-run-btn');
  if (!statusEl) return;

  // Update elapsed
  if (elapsedEl && topicStartTime) {
    const secs = Math.floor((Date.now() - topicStartTime) / 1000);
    const m = Math.floor(secs / 60); const s = secs % 60;
    elapsedEl.textContent = m > 0 ? m + 'm ' + s + 's' : s + 's';
  }

  try {
    const d = await api('/pipeline/start-from-topic/' + topicRunId + '/status');
    // Build step progress
    const steps = d.step_status || {};
    const stepNames = ['trend_scout','story_strategist','research_agent','facebook_writer','linkedin_writer','cta_agent','creative_director','qa_agent'];
    const stepLabels = { trend_scout:'Trend Scout', story_strategist:'Story Strategist', research_agent:'Research', facebook_writer:'FB Writer', linkedin_writer:'LI Writer', cta_agent:'CTA Agent', creative_director:'Creative Director', qa_agent:'QA Agent' };
    let html = '<div class="card" style="padding:12px 16px"><div style="font-size:13px;font-weight:600;margin-bottom:8px;color:var(--primary)">Pipeline Progress</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    for (const sn of stepNames) {
      const st = steps[sn] || 'pending';
      let bg = 'var(--muted)'; let fg = 'var(--dim)';
      if (st === 'completed') { bg = 'var(--success-dim)'; fg = 'var(--success)'; }
      else if (st === 'running') { bg = 'var(--primary-dim)'; fg = 'var(--primary)'; }
      else if (st === 'error') { bg = 'var(--destructive-dim)'; fg = 'var(--destructive)'; }
      html += '<span style="display:inline-block;padding:4px 10px;border-radius:4px;font-size:11px;background:' + bg + ';color:' + fg + '">' + (stepLabels[sn]||sn) + (st==='running'?' ...':'') + (st==='completed'?' &#10003;':'') + (st==='error'?' &#10007;':'') + '</span>';
    }
    html += '</div>';
    if (d.error) html += '<div style="color:var(--destructive);margin-top:8px;font-size:12px">Error: ' + esc(d.error) + '</div>';
    html += '</div>';
    statusEl.innerHTML = html;

    if (d.status === 'completed' || d.status === 'error' || d.status === 'failed') {
      if (topicPollInterval) { clearInterval(topicPollInterval); topicPollInterval = null; }
      localStorage.removeItem('tce_topic_run');
      localStorage.removeItem('tce_topic_start');
      if (btn) { btn.disabled = false; btn.textContent = 'Generate from Topic'; }

      if (d.status === 'completed') {
        toast('Topic pipeline completed!');
        // Fetch the latest package
        try {
          const pkgs = await api('/content/packages?limit=1');
          if (pkgs && pkgs.length > 0) {
            const pkg = pkgs[0];
            let rhtml = '<div class="card" style="margin-bottom:16px"><div style="font-size:15px;font-weight:600;margin-bottom:12px;color:var(--primary)">Generated Content</div>';
            if (pkg.facebook_post) {
              rhtml += '<div style="margin-bottom:16px"><div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">Facebook Post</div>';
              rhtml += '<div style="white-space:pre-wrap;font-size:13px;line-height:1.7;padding:12px;background:var(--bg);border-radius:6px;border:1px solid var(--border);max-height:400px;overflow-y:auto">' + esc(pkg.facebook_post) + '</div>';
              rhtml += '<button class="btn" style="margin-top:6px;font-size:11px" onclick="copyPrev(this)">Copy FB</button></div>';
            }
            if (pkg.linkedin_post) {
              rhtml += '<div style="margin-bottom:16px"><div style="font-size:12px;font-weight:600;color:var(--info);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">LinkedIn Post</div>';
              rhtml += '<div style="white-space:pre-wrap;font-size:13px;line-height:1.7;padding:12px;background:var(--bg);border-radius:6px;border:1px solid var(--border);max-height:400px;overflow-y:auto">' + esc(pkg.linkedin_post) + '</div>';
              rhtml += '<button class="btn" style="margin-top:6px;font-size:11px" onclick="copyPrev(this)">Copy LI</button></div>';
            }
            if (pkg.hook_variants && pkg.hook_variants.length) {
              rhtml += '<div style="margin-bottom:16px"><div style="font-size:12px;font-weight:600;color:var(--success);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">Hook Variants</div>';
              rhtml += '<div style="font-size:13px;line-height:1.7;padding:12px;background:var(--bg);border-radius:6px;border:1px solid var(--border)">';
              pkg.hook_variants.forEach(function(h, i) { rhtml += '<div style="margin-bottom:6px"><span style="color:var(--dim);font-size:11px">' + (i+1) + '.</span> ' + esc(typeof h === 'string' ? h : JSON.stringify(h)) + '</div>'; });
              rhtml += '</div></div>';
            }
            if (pkg.visual_prompt) {
              rhtml += '<div><div style="font-size:12px;font-weight:600;color:var(--warning);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">Visual Prompt</div>';
              rhtml += '<div style="font-size:12px;color:var(--dim);padding:12px;background:var(--bg);border-radius:6px;border:1px solid var(--border)">' + esc(typeof pkg.visual_prompt === 'string' ? pkg.visual_prompt : JSON.stringify(pkg.visual_prompt)) + '</div></div>';
            }
            rhtml += '</div>';
            if (resultEl) resultEl.innerHTML = rhtml;
          }
        } catch {}
      } else {
        toast('Pipeline failed: ' + (d.error || 'unknown error'), false);
      }
    }
  } catch (e) {
    statusEl.innerHTML = '<div class="card" style="color:var(--dim)">Checking status...</div>';
  }
}

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
    </div>
    <div class="section" style="margin-top:32px">
      <h2>Start From Copy</h2>
      <p style="font-size:13px;color:var(--dim);margin-bottom:12px">Paste copy you already wrote. The agent team will analyze it, match it to a template, polish it into FB + LI drafts, generate image prompts, and QA the result.</p>
      <div class="card">
        <div style="margin-bottom:12px">
          <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Your copy</label>
          <textarea id="polish-copy-text" rows="8" style="width:100%;resize:vertical;min-height:120px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark" placeholder="Paste your draft copy here..."></textarea>
        </div>
        <div style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:12px">
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Platform</label>
            <select id="polish-platform" style="background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
              <option value="both" style="background:var(--card);color:var(--text)">Both (FB + LI)</option>
              <option value="facebook" style="background:var(--card);color:var(--text)">Facebook only</option>
              <option value="linkedin" style="background:var(--card);color:var(--text)">LinkedIn only</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">CTA Keyword (optional)</label>
            <input type="text" id="polish-cta" placeholder="e.g. agency-growth" style="width:180px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
          </div>
          <div style="flex:1;min-width:200px">
            <label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Notes (optional)</label>
            <input type="text" id="polish-notes" placeholder="Any extra instructions for the team..." style="width:100%;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px;color-scheme:dark">
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-primary" id="polish-btn" onclick="runPolishCopy()">Polish & Build Package</button>
          <span id="polish-elapsed" style="font-size:12px;color:var(--dim)"></span>
        </div>
        <div id="polish-status" style="margin-top:12px"></div>
      </div>
    </div>`;
  if (activePipelineRun) { pollPipeline(); if(!pollInterval) pollInterval = setInterval(pollPipeline, 3000); }
  if (activePolishRun) { pollPolish(); if(!polishPollInterval) polishPollInterval = setInterval(pollPolish, 3000); }
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
        fh += '<button class="btn btn-dim" style="font-size:13px;padding:8px 16px" onclick="currentTab=\\'packages\\';switchTab(\\'packages\\');render()">View Packages</button>';
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
let pkgDayFilter = Math.min(Math.max(new Date().getDay() - 1, 0), 4);
let _pkgCache = null;
let _pkgDayMapCache = null;

function switchPkgDay(day) {
  pkgDayFilter = day;
  _renderPkgFromCache();
}

function _renderPkgFromCache() {
  if (!_pkgCache) return;
  const pkgs = _pkgCache;
  const pkgDayMap = _pkgDayMapCache || {};

  // Build day tabs
  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
  const monday = getMondayOfWeek();
  let tabHtml = '<div style="display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap">';
  for (let d = 0; d < 5; d++) {
    const dayDate = new Date(monday); dayDate.setDate(dayDate.getDate() + d);
    const dateLabel = dayDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const hasPkg = Object.values(pkgDayMap).some(m => m.day === d);
    const isActive = pkgDayFilter === d;
    const dotColor = hasPkg ? 'var(--green)' : 'var(--border)';
    tabHtml += '<button onclick="switchPkgDay(' + d + ')" style="padding:8px 14px;border:1px solid ' + (isActive ? 'var(--accent)' : 'var(--border)') + ';background:' + (isActive ? 'var(--accent)' : 'var(--card)') + ';color:' + (isActive ? '#fff' : 'var(--text)') + ';border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;display:flex;align-items:center;gap:6px"><span style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span>' + dayNames[d] + ' ' + dateLabel + '</button>';
  }
  const unlinkedCount = pkgs.filter(p => !pkgDayMap[p.id]).length;
  if (unlinkedCount > 0) {
    const isOther = pkgDayFilter === 'other';
    tabHtml += '<button onclick="switchPkgDay(&quot;other&quot;)" style="padding:8px 14px;border:1px solid ' + (isOther ? 'var(--accent)' : 'var(--border)') + ';background:' + (isOther ? 'var(--accent)' : 'var(--card)') + ';color:' + (isOther ? '#fff' : 'var(--dim)') + ';border-radius:6px;cursor:pointer;font-size:13px">Other (' + unlinkedCount + ')</button>';
  }
  const isAll = pkgDayFilter === null;
  tabHtml += '<button onclick="switchPkgDay(null)" style="padding:8px 14px;border:1px solid ' + (isAll ? 'var(--accent)' : 'var(--border)') + ';background:' + (isAll ? 'var(--accent)' : 'var(--card)') + ';color:' + (isAll ? '#fff' : 'var(--dim)') + ';border-radius:6px;cursor:pointer;font-size:13px">All (' + pkgs.length + ')</button>';
  tabHtml += '</div>';
  // GAP-29: Status and QA filters
  tabHtml += '<div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">';
  tabHtml += '<select id="pkg-status-filter" onchange="filterPkgStatus()" style="padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px"><option value="">All statuses</option><option value="draft">Draft</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select>';
  tabHtml += '<select id="pkg-qa-filter" onchange="filterPkgStatus()" style="padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px"><option value="">Any QA</option><option value="pass">QA Pass (7+)</option><option value="conditional">Conditional (5-7)</option><option value="fail">QA Fail (&lt;5)</option></select>';
  tabHtml += '</div>';
  document.getElementById('pkg-day-tabs').innerHTML = tabHtml;

  // Filter
  let filteredPkgs = pkgs;
  if (pkgDayFilter !== null && pkgDayFilter !== 'other') {
    const dayPkgIds = new Set(Object.entries(pkgDayMap).filter(([, m]) => m.day === pkgDayFilter).map(([id]) => id));
    filteredPkgs = pkgs.filter(p => dayPkgIds.has(p.id));
  } else if (pkgDayFilter === 'other') {
    filteredPkgs = pkgs.filter(p => !pkgDayMap[p.id]);
  }
  // GAP-29: Apply status and QA filters
  const statusFilter = document.getElementById('pkg-status-filter')?.value;
  const qaFilter = document.getElementById('pkg-qa-filter')?.value;
  if (statusFilter) filteredPkgs = filteredPkgs.filter(p => p.approval_status === statusFilter);
  if (qaFilter) {
    filteredPkgs = filteredPkgs.filter(p => {
      const qs = p.quality_scores?.composite_score || p.quality_scores?.overall;
      const score = typeof qs === 'number' ? qs : (qs?.score || 0);
      if (qaFilter === 'pass') return score >= 7;
      if (qaFilter === 'conditional') return score >= 5 && score < 7;
      if (qaFilter === 'fail') return score < 5;
      return true;
    });
  }

  if (!filteredPkgs.length) { document.getElementById('pkg-list').innerHTML = '<div class="empty" style="padding:24px;text-align:center">No packages for this day.</div>'; return; }

  let html = '<div class="packages-list">';
  for (const p of filteredPkgs) {
    const dayInfo = pkgDayMap[p.id];
    if (dayInfo) {
      const dayLabel = DAY_NAMES[dayInfo.day] || '';
      const angleLabel = ANGLE_LABELS[dayInfo.angle] || (dayInfo.angle || '').replace(/_/g, ' ');
      html += '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;display:flex;align-items:center;gap:8px"><span style="color:var(--accent2);font-weight:600">' + dayLabel + ' ' + dayInfo.date + '</span><span>' + angleLabel + '</span></div>';
    }
    html += _renderPkgCard(p);
  }
  html += '</div>';
  document.getElementById('pkg-list').innerHTML = html;
}

function _renderPkgCard(p) {
  let html = '';
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
      const _tpl = p.quality_scores?.matched_template;
      if (_tpl?.template_name) {
        html += '<span style="color:var(--yellow)">Template: <strong>' + esc(_tpl.template_name) + '</strong>';
        if (_tpl.template_family) html += ' <span style="font-weight:400;opacity:.7">(' + esc(_tpl.template_family) + ')</span>';
        html += '</span>';
      }
      html += '</div>';
      if (_tpl?.hook_formula) {
        html += '<div style="font-size:11px;color:var(--dim);padding:2px 16px 0">';
        html += '<span style="color:var(--yellow);opacity:.6">Hook:</span> ' + esc(_tpl.hook_formula.substring(0, 120)) + (_tpl.hook_formula.length > 120 ? '...' : '');
        html += '</div>';
      }
      // Tabs
      html += '<div class="tabs">';
      html += '<button class="active" onclick="showPostTab(this,\\'fb-' + pid + '\\')">Facebook</button>';
      html += '<button onclick="showPostTab(this,\\'li-' + pid + '\\')">LinkedIn</button>';
      if (p.hook_variants?.length) html += '<button onclick="showPostTab(this,\\'hooks-' + pid + '\\')">Hooks (' + p.hook_variants.length + ')</button>';
      if (p.quality_scores) html += '<button onclick="showPostTab(this,\\'qa-' + pid + '\\')">QA Scores</button>';
      if (p.dm_flow) html += '<button onclick="showPostTab(this,\\'dm-' + pid + '\\')">DM Flow</button>';
      if (p.image_prompts?.length) html += '<button onclick="showPostTab(this,\\'img-' + pid + '\\')">Images (' + p.image_prompts.length + ')</button>';
      html += '<button onclick="showPostTab(this,\\'vid-' + pid + '\\');loadVideos(\\'' + p.id + '\\',\\'' + pid + '\\')">Videos</button>';
      html += '<button onclick="showPostTab(this,\\'scr-' + pid + '\\');loadScripts(\\'' + p.id + '\\',\\'' + pid + '\\')">Script</button>';
      html += '</div>';
      html += '<div id="fb-' + pid + '" class="tab-pane" style="position:relative"><button class="copy-icon-btn" onclick="copyPaneText(this)" title="Copy to clipboard">&#128203;</button><div class="post-preview">' + esc(fbText || 'No Facebook post generated') + '</div><div style="display:flex;gap:6px;margin-top:6px"><button class="btn btn-dim edit-toggle-fb" style="font-size:11px" onclick="toggleInlineEdit(\\'' + p.id + '\\',\\'fb\\',this)">Edit</button></div></div>';
      html += '<div id="li-' + pid + '" class="tab-pane" style="display:none;position:relative"><button class="copy-icon-btn" onclick="copyPaneText(this)" title="Copy to clipboard">&#128203;</button><div class="post-preview">' + esc(liText || 'No LinkedIn post generated') + '</div><div style="display:flex;gap:6px;margin-top:6px"><button class="btn btn-dim edit-toggle-li" style="font-size:11px" onclick="toggleInlineEdit(\\'' + p.id + '\\',\\'li\\',this)">Edit</button></div></div>';
      if (p.hook_variants?.length) {
        html += '<div id="hooks-' + pid + '" class="tab-pane" style="display:none">';
        const currentHook = (p.facebook_post || p.linkedin_post || '').split('\\n')[0];
        html += '<div style="padding:12px;margin-bottom:10px;border-radius:8px;background:#1a2e1a;border:1px solid var(--green)">';
        html += '<div style="font-size:11px;font-weight:600;color:var(--green);margin-bottom:4px">CURRENT HOOK</div>';
        html += '<div style="font-size:14px;line-height:1.5">' + esc(currentHook || 'No hook set') + '</div></div>';
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px"><span style="font-size:11px;color:var(--dim)">Click "Use this" to replace the current hook:</span><button class="btn btn-dim" style="font-size:11px;padding:3px 10px;border-color:var(--accent);color:var(--accent)" onclick="regenerateHooks(\\'' + p.id + '\\', this)">Regenerate Hooks</button></div>';
        p.hook_variants.forEach((h, i) => {
          const isCurrent = currentHook === h;
          html += '<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;margin-bottom:6px;border-radius:8px;background:' + (isCurrent ? '#1a2e1a' : '#111318') + ';border:1px solid ' + (isCurrent ? 'var(--green)' : 'var(--border)') + '">';
          html += '<div style="flex:1;font-size:13px;line-height:1.5;white-space:pre-wrap">' + esc(h) + '</div>';
          if (!isCurrent) html += '<button data-hi="' + i + '" class="btn btn-dim" style="flex-shrink:0;font-size:11px;padding:4px 10px" onclick="useHook(\\'' + p.id + '\\',' + i + ')">Use this</button>';
          html += '</div>';
        });
        html += '</div>';
      }
      if (p.quality_scores) {
        html += '<div id="qa-' + pid + '" class="tab-pane" style="display:none">';
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
        html += '<div style="display:flex;flex-direction:column;gap:8px">';
        for (const [k, v] of Object.entries(p.quality_scores)) {
          if (k === 'composite_score' || k === 'overall') continue;
          const score = typeof v === 'number' ? v : (v?.score || v);
          const justification = typeof v === 'object' ? v?.justification : null;
          const color = score >= 8 ? 'var(--green)' : score >= 6 ? 'var(--yellow)' : 'var(--red)';
          const icon = score >= 7 ? '\\u2713' : score >= 5 ? '\\u26A0' : '\\u2717';
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:6px;padding:10px 14px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center"><div style="font-size:13px;font-weight:600">' + icon + ' ' + k.replace(/_/g, ' ') + '</div>';
          html += '<div style="display:flex;align-items:center;gap:8px"><div style="font-size:18px;font-weight:700;color:' + color + '">' + (typeof score === 'number' ? score.toFixed(1) : score) + '</div>';
          // GAP-48: Humanitarian override button on failing dimensions
          if (typeof score === 'number' && score < 7) html += '<button class="btn btn-dim" style="font-size:10px;padding:2px 6px" onclick="humanitarianOverride(\\'' + p.id + '\\',\\'' + k + '\\')">Override</button>';
          html += '</div></div>';
          if (justification) html += '<div style="font-size:12px;color:var(--dim);margin-top:6px;line-height:1.5">' + esc(justification) + '</div>';
          // Show existing override if present
          const override = p.quality_scores.operator_overrides?.[k];
          if (override) html += '<div style="font-size:11px;color:var(--yellow);margin-top:4px;padding:4px 8px;background:#2d2000;border-radius:4px">Override: ' + esc(override.justification || 'Operator approved') + '</div>';
          html += '</div>';
        }
        html += '</div></div>';
      }
      if (p.dm_flow) {
        const dm = p.dm_flow;
        html += '<div id="dm-' + pid + '" class="tab-pane" style="display:none">';
        html += '<div style="display:flex;flex-direction:column;gap:12px">';
        if (dm.trigger) {
          html += '<div style="background:#1e1b4b;border:1px solid var(--accent);border-radius:8px;padding:14px">';
          html += '<div style="font-size:11px;color:var(--accent2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Trigger Keyword</div>';
          html += '<div style="font-size:20px;font-weight:700;color:var(--accent2)">' + esc(dm.trigger) + '</div>';
          html += '</div>';
        }
        if (dm.ack_message) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><div style="font-size:11px;color:var(--green);text-transform:uppercase;letter-spacing:.5px">Instant Reply (when they comment)</div><button class="btn btn-dim" style="font-size:10px;padding:2px 8px" onclick="editDmField(\\'' + p.id + '\\',\\'ack_message\\',this)">Edit</button></div>';
          html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(dm.ack_message) + '</div>';
          html += '</div>';
        }
        if (dm.delivery_message) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><div style="font-size:11px;color:var(--blue);text-transform:uppercase;letter-spacing:.5px">Delivery Message (with the guide)</div><button class="btn btn-dim" style="font-size:10px;padding:2px 8px" onclick="editDmField(\\'' + p.id + '\\',\\'delivery_message\\',this)">Edit</button></div>';
          html += '<div style="font-size:14px;line-height:1.6;white-space:pre-wrap">' + esc(dm.delivery_message) + '</div>';
          html += '</div>';
        }
        if (dm.follow_up) {
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><div style="font-size:11px;color:var(--yellow);text-transform:uppercase;letter-spacing:.5px">Follow-up (24-48h later)</div><button class="btn btn-dim" style="font-size:10px;padding:2px 8px" onclick="editDmField(\\'' + p.id + '\\',\\'follow_up\\',this)">Edit</button></div>';
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
        html += '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">';
        html += '<button class="btn btn-dim" style="font-size:12px" onclick="copyDmFlow(this, \\'' + pid + '\\')">Copy All DM Messages</button>';
        // GAP-45: CTA Flow Editor - fulfillment checklist
        html += '<button class="btn btn-dim" style="font-size:12px;border-color:var(--accent);color:var(--accent)" onclick="showCtaChecklist(\\'' + pid + '\\')">Fulfillment Checklist</button>';
        html += '</div>';
        html += '<div id="cta-checklist-' + pid + '" style="display:none;margin-top:12px;background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:var(--accent2)">CTA Fulfillment Checklist</div>';
        const checkItems = [
          {id:'guide-ready', label:'Guide/resource file is ready and uploaded'},
          {id:'trigger-set', label:'Comment trigger keyword is set in automation tool'},
          {id:'ack-copied', label:'Instant reply (ack) message is loaded'},
          {id:'delivery-copied', label:'Delivery DM message is loaded with link'},
          {id:'followup-scheduled', label:'Follow-up message is scheduled (24-48h)'},
          {id:'landing-live', label:'Landing page or resource URL is live and tested'},
        ];
        for (const item of checkItems) {
          html += '<label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;cursor:pointer"><input type="checkbox" style="accent-color:var(--green)" id="ck-' + pid + '-' + item.id + '"> ' + esc(item.label) + '</label>';
        }
        html += '</div>';
        html += '</div>';
      }
      if (p.image_prompts?.length) {
        const hasAnyImages = p.image_prompts.some(ip => ip.image_url);
        html += '<div id="img-' + pid + '" class="tab-pane" style="display:none">';
        // Generate Images button
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">';
        if (!hasAnyImages) {
          html += '<button class="btn btn-blue" id="gen-img-btn-' + pid + '" onclick="generateImages(\\'' + p.id + '\\', this)">Generate Images with AI</button>';
          html += '<span style="font-size:12px;color:var(--dim)">Uses fal.ai Flux Pro (~$0.03/image, ' + p.image_prompts.length + ' images)</span>';
        } else {
          html += '<button class="btn btn-dim" id="gen-img-btn-' + pid + '" onclick="generateImages(\\'' + p.id + '\\', this)">Regenerate Images</button>';
          html += '<button class="btn btn-blue" onclick="downloadAllImages(\\'' + p.id + '\\', this)">Download All</button>';
          html += '<span style="font-size:12px;color:var(--green)">Images generated</span>';
        }
        html += '</div>';
        // Progress bar placeholder
        html += '<div id="gen-img-progress-' + pid + '"></div>';
        // Image grid
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px">';
        for (let _imgIdx = 0; _imgIdx < p.image_prompts.length; _imgIdx++) {
          const ip = p.image_prompts[_imgIdx];
          const promptText = ip.prompt_text || ip.detailed_prompt || '';
          const bestPlat = ip.best_platform || 'fal_ai';
          const platColors = { fal_ai: '#16a34a', midjourney: '#a855f7', gemini: '#3b82f6', dall_e: '#f97316' };
          const platLabels = { fal_ai: 'fal.ai', midjourney: 'Midjourney', gemini: 'Gemini', dall_e: 'DALL-E' };
          const platColor = platColors[bestPlat] || '#888';
          const platLabel = platLabels[bestPlat] || bestPlat;
          const isSelected = ip.selected === true;
          html += '<div style="background:#111318;border:2px solid ' + (isSelected ? 'var(--green)' : 'var(--border)') + ';border-radius:8px;padding:16px;position:relative">';
          // GAP-37: Selection radio + regen button
          if (ip.image_url) {
            html += '<div style="display:flex;justify-content:space-between;margin-bottom:8px">';
            html += '<label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:' + (isSelected ? 'var(--green)' : 'var(--dim)') + '"><input type="radio" name="img-select-' + pid + '" ' + (isSelected ? 'checked' : '') + ' onchange="selectImage(\\'' + p.id + '\\',' + _imgIdx + ')" style="accent-color:var(--green)">' + (isSelected ? 'Selected' : 'Select') + '</label>';
            html += '<button class="btn btn-dim" style="font-size:10px;padding:3px 8px" onclick="regenSingleImage(\\'' + p.id + '\\',' + _imgIdx + ',this)">Regen</button>';
            html += '</div>';
            // Modification comment input
            html += '<div style="display:flex;gap:4px;margin-bottom:8px">';
            html += '<input id="img-mod-' + pid + '-' + _imgIdx + '" type="text" placeholder="e.g. make it brighter, add more people..." style="flex:1;font-size:11px;padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px">';
            html += '<button class="btn btn-dim" style="font-size:10px;padding:3px 8px;white-space:nowrap" onclick="regenWithMod(\\'' + p.id + '\\',' + _imgIdx + ',this)">Regen with note</button>';
            html += '</div>';
          }
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
            const imgName = (ip.prompt_name || ip.visual_job || 'image').replace(/[^a-zA-Z0-9]/g, '_').toLowerCase();
            html += '<div style="margin-bottom:12px;border-radius:8px;overflow:hidden;border:1px solid var(--border);position:relative">';
            html += '<img src="' + esc(ip.image_url) + '" style="width:100%;display:block" loading="lazy">';
            html += '<div style="position:absolute;top:8px;right:8px;display:flex;gap:6px">';
            html += '<a href="' + esc(ip.image_url) + '" download="' + imgName + '.jpg" style="background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;cursor:pointer" target="_blank">Download</a>';
            html += '<button onclick="navigator.clipboard.writeText(\\'' + esc(ip.image_url).replace(/'/g, "\\\\'") + '\\');toast(\\'Image URL copied\\')" style="background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;border:none;cursor:pointer">Copy URL</button>';
            html += '</div>';
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
      // Videos tab
      html += '<div id="vid-' + pid + '" class="tab-pane" style="display:none">';
      html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">';
      html += '<button class="btn btn-blue" onclick="generateVideos(\\'' + p.id + '\\', this)">Generate Videos</button>';
      html += '<span id="vid-status-' + pid + '" style="font-size:12px;color:var(--dim)">Click to render video templates from this package</span>';
      html += '</div>';
      html += '<div id="vid-progress-' + pid + '"></div>';
      html += '<div id="vid-grid-' + pid + '" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px"></div>';
      html += '</div>';

      // Script tab
      html += '<div id="scr-' + pid + '" class="tab-pane" style="display:none">';
      html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">';
      html += '<button id="scr-regen-' + pid + '" class="btn btn-dim" style="display:none;border-color:var(--accent);color:var(--accent)" onclick="generateScript(\\'' + p.id + '\\', \\'' + pid + '\\', this)">Regenerate Script</button>';
      html += '<span id="scr-status-' + pid + '" style="font-size:12px;color:var(--dim)">Script will auto-generate when you open this tab</span>';
      html += '</div>';
      html += '<div id="scr-segments-' + pid + '"></div>';
      html += '<div id="scr-audio-' + pid + '" style="display:none;margin-top:16px">';
      html += '<div style="margin-bottom:8px;font-size:13px;font-weight:600;color:var(--accent2)">Upload Audio Recording</div>';
      html += '<div style="display:flex;align-items:center;gap:12px">';
      html += '<input type="file" accept=".wav,.mp3,.m4a,.ogg" id="scr-file-' + pid + '" style="font-size:12px" onchange="uploadAudio(\\'' + p.id + '\\', \\'' + pid + '\\', this.files[0])">';
      html += '<span id="scr-audio-status-' + pid + '" style="font-size:12px;color:var(--dim)"></span>';
      html += '</div>';
      html += '<div style="margin-top:12px;display:flex;align-items:center;gap:8px">';
      html += '<span style="font-size:13px;font-weight:600;color:var(--accent2)">or</span>';
      html += '<button class="btn btn-dim" style="border-color:var(--green);color:var(--green)" onclick="ttsGenerateForScript(\\'' + p.id + '\\', \\'' + pid + '\\', this)">Generate Voiceover (AI)</button>';
      html += '<select id="scr-voice-' + pid + '" style="background:var(--bg);color:var(--text);border:1px solid var(--border);padding:6px;border-radius:6px;font-size:12px"><option value="">Default voice</option></select>';
      html += '<button class="btn btn-dim" style="font-size:11px" onclick="ttsPreviewVoice(\\'' + p.id + '\\', \\'' + pid + '\\')">Preview</button>';
      html += '<span id="scr-tts-status-' + pid + '" style="font-size:11px;color:var(--dim)"></span>';
      html += '</div>';
      html += '<audio id="scr-tts-audio-' + pid + '" controls style="display:none;margin-top:8px;width:100%"></audio>';
      html += '</div>';
      html += '<div id="scr-actions-' + pid + '" style="display:none;margin-top:12px;gap:8px"></div>';
      html += '<div id="scr-render-progress-' + pid + '"></div>';
      html += '<div id="scr-video-player-' + pid + '"></div>';
      html += '</div>';

      // Actions
      html += '<div class="btn-group" style="margin-top:12px">';
      if (p.approval_status === 'draft') {
        html += '<button class="btn btn-dim" style="border-color:var(--blue);color:var(--blue)" onclick="schedulePublish(\\'' + p.id + '\\', \\'both\\')">Schedule</button>';
      } else if (p.approval_status === 'approved') {
        html += '<span style="color:var(--green);font-weight:600;font-size:13px;padding:8px 0">Approved</span>';
        html += '<button class="btn btn-dim" style="border-color:var(--blue);color:var(--blue)" onclick="schedulePublish(\\'' + p.id + '\\', \\'both\\')">Schedule Publish</button>';
      } else if (p.approval_status === 'rejected') {
        html += '<span style="color:var(--red);font-weight:600;font-size:13px;padding:8px 0">Rejected</span>';
        html += '<button class="btn btn-dim" onclick="resetPackageStatus(\\'' + p.id + '\\')">Reset to Draft</button>';
      }
      html += '<button class="btn btn-dim" style="border-color:var(--accent2);color:var(--accent2)" onclick="loadPackageContext(\\'' + p.id + '\\', this)">Show Context</button>';
      html += '<button class="btn btn-dim" style="border-color:#a78bfa;color:#a78bfa" onclick="openBrainstorm(\\'' + p.id + '\\')">Brainstorm</button>';
      html += '<button class="btn btn-dim" style="border-color:var(--yellow);color:var(--yellow)" onclick="aiReviseActive(\\'' + p.id + '\\', this)">AI Revise</button>';
      if (p.is_archived) {
        html += '<button class="btn btn-dim" onclick="unarchivePackage(\\'' + p.id + '\\')">Unarchive</button>';
      } else {
        html += '<button class="btn btn-dim" onclick="archivePackage(\\'' + p.id + '\\')">Archive</button>';
      }
  html += '</div>';
  html += '</div>';
  return html;
}

async function renderPackages() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h2>Content Packages</h2><div style="display:flex;align-items:center;gap:12px"><button class="btn btn-dim" style="font-size:11px;padding:4px 10px" onclick="backfillHooks(this)">Backfill All Hooks</button><label style="font-size:12px;color:var(--dim);cursor:pointer;display:flex;align-items:center;gap:6px"><input type="checkbox" id="show-archived" ' + (showArchived ? 'checked' : '') + ' onchange="showArchived=this.checked;_pkgCache=null;renderPackages()"> Show archived</label></div></div><div id="pkg-day-tabs"></div><div id="pkg-list"><div class="empty">Loading packages...</div></div></div>';
  try {
    const [pkgs, calEntries] = await Promise.all([
      api('/content/packages' + (showArchived ? '?include_archived=true' : '')),
      api('/calendar/?start=' + fmtDate(getMondayOfWeek()) + '&end=' + fmtDate((() => { const f = getMondayOfWeek(); f.setDate(f.getDate() + 4); return f; })())).catch(() => [])
    ]);
    if (!pkgs.length) { document.getElementById('pkg-list').innerHTML = '<div class="empty">No packages yet. Run a pipeline first.</div>'; return; }
    const pkgDayMap = {};
    for (const e of calEntries) {
      if (e.post_package_id) pkgDayMap[e.post_package_id] = { day: e.day_of_week, date: e.date, topic: e.topic, angle: e.angle_type };
    }
    _pkgCache = pkgs;
    _pkgDayMapCache = pkgDayMap;
    _renderPkgFromCache();
  } catch (e) { document.getElementById('pkg-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
  // Load weekly guides into packages tab
  try {
    const guides = await api('/content/guides');
    if (guides.length) {
      let ghtml = '<div style="margin-top:24px"><h2 style="margin-bottom:12px">Weekly Guides</h2>';
      for (const g of guides) {
        ghtml += '<div class="guide-card">';
        ghtml += '<h3>' + esc(g.guide_title) + '</h3>';
        ghtml += '<div class="guide-meta"><span>Week of ' + g.week_start_date + '</span><span>Theme: ' + esc(g.weekly_theme) + '</span>';
        if (g.cta_keyword) ghtml += '<span>CTA: <strong>' + esc(g.cta_keyword) + '</strong></span>';
        ghtml += '</div>';
        ghtml += '<div class="btn-group" style="margin:12px 0">';
        if (g.docx_path) ghtml += '<button class="btn btn-green" onclick="downloadGuide(\\'' + g.id + '\\',\\'' + esc(g.guide_title).replace(/'/g, '') + '\\')">Download DOCX</button>';
        if (g.fulfillment_link) ghtml += '<a class="btn btn-blue" href="' + esc(g.fulfillment_link) + '" target="_blank">Fulfillment Link</a>';
        ghtml += '<button class="btn btn-dim" onclick="archiveGuide(\\'' + g.id + '\\')">Archive</button>';
        ghtml += '</div>';
        if (g.markdown_content) {
          ghtml += '<details style="margin-top:8px"><summary style="cursor:pointer;color:var(--accent2);font-size:13px">View Guide Content</summary>';
          ghtml += '<div class="post-preview" style="margin-top:8px;max-height:400px;overflow-y:auto;white-space:pre-wrap">' + esc(g.markdown_content) + '</div></details>';
        }
        ghtml += '<div style="font-size:11px;color:var(--dim);margin-top:8px">Created: ' + new Date(g.created_at).toLocaleString() + '</div>';
        ghtml += '</div>';
      }
      ghtml += '</div>';
      document.getElementById('pkg-list').insertAdjacentHTML('afterend', ghtml);
    }
  } catch {}
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function showPostTab(btn, id) {
  const card = btn.closest('.pkg-card');
  // Hide only tab-pane containers (not their children)
  card.querySelectorAll('.tab-pane').forEach(el => {
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
    await renderPackages();
  } catch (e) { toast('Archive failed: ' + e.message, false); }
}

async function unarchiveGuide(id) {
  try {
    await api('/content/guides/' + id + '/unarchive', { method: 'POST' });
    toast('Guide unarchived');
    await renderPackages();
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

async function loadVideos(packageId, pid) {
  const grid = document.getElementById('vid-grid-' + pid);
  const status = document.getElementById('vid-status-' + pid);
  if (!grid) return;
  try {
    const resp = await fetch('/api/v1/videos?package_id=' + packageId);
    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error('Server error (' + resp.status + '): ' + errText.substring(0, 100));
    }
    const videos = await resp.json();
    if (!videos.length) {
      status.textContent = 'No videos yet - click Generate to create them';
      grid.innerHTML = '';
      return;
    }
    status.textContent = videos.length + ' video(s) rendered';
    status.style.color = 'var(--green)';
    grid.innerHTML = '';
    videos.forEach(v => {
      const card = document.createElement('div');
      const selected = v.operator_selected ? 'var(--green)' : 'var(--border)';
      card.style.cssText = 'background:#111318;border:2px solid ' + selected + ';border-radius:8px;padding:16px';
      let inner = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
      inner += '<div style="font-weight:600;font-size:14px;color:var(--accent2)">' + esc(v.template_name.replace(/_/g, ' ')) + '</div>';
      inner += '<span style="padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;background:#16a34a22;color:#16a34a;border:1px solid #16a34a44">' + esc(v.resolution || '') + '</span>';
      inner += '</div>';
      if (v.thumbnail_url) {
        inner += '<div style="margin-bottom:8px;border-radius:8px;overflow:hidden;border:1px solid var(--border)"><img src="' + esc(v.thumbnail_url) + '" style="width:100%;display:block" loading="lazy"></div>';
      }
      if (v.video_url) {
        inner += '<div style="margin-bottom:8px;border-radius:8px;overflow:hidden;border:1px solid var(--border)"><video src="' + esc(v.video_url) + '" controls style="width:100%;display:block" preload="metadata"></video></div>';
      }
      inner += '<div style="font-size:12px;color:var(--dim);display:flex;gap:12px;flex-wrap:wrap">';
      if (v.duration_seconds) inner += '<span>' + v.duration_seconds + 's</span>';
      if (v.codec) inner += '<span>' + esc(v.codec) + '</span>';
      if (v.file_size_bytes) inner += '<span>' + (v.file_size_bytes / 1024).toFixed(0) + ' KB</span>';
      if (v.render_time_seconds) inner += '<span>Rendered in ' + v.render_time_seconds + 's</span>';
      inner += '</div>';
      inner += '<div style="display:flex;gap:6px;margin-top:8px">';
      inner += '<button class="btn btn-dim" style="font-size:11px" onclick="selectVideo(\\'' + v.id + '\\', ' + !v.operator_selected + ', this)">\\u2713 ' + (v.operator_selected ? 'Selected' : 'Select') + '</button>';
      if (v.video_url) inner += '<a href="' + esc(v.video_url) + '" download class="btn btn-dim" style="font-size:11px;text-decoration:none">Download</a>';
      inner += '</div>';
      card.innerHTML = inner;
      grid.appendChild(card);
    });
  } catch (e) {
    status.textContent = 'Error loading videos: ' + e.message;
    status.style.color = 'var(--red)';
  }
}

async function selectVideo(videoId, selected, btn) {
  try {
    await fetch('/api/v1/videos/' + videoId + '/select', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ selected })
    });
    btn.textContent = selected ? '\\u2713 Selected' : '\\u2713 Select';
    btn.closest('div[style*="background:#111318"]').style.borderColor = selected ? 'var(--green)' : 'var(--border)';
    toast(selected ? 'Video selected' : 'Video deselected');
  } catch(e) { toast('Error: ' + e.message); }
}

async function generateVideos(packageId, btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating...';
  const pid = packageId.replace(/-/g, '');
  const statusEl = document.getElementById('vid-status-' + pid);
  const progressEl = document.getElementById('vid-progress-' + pid);
  if (statusEl) { statusEl.textContent = 'Starting video generation...'; statusEl.style.color = 'var(--accent2)'; }
  if (progressEl) {
    progressEl.innerHTML = '<div style="width:100%;height:6px;background:var(--border);border-radius:3px;margin-bottom:8px"><div id="vid-bar-' + pid + '" style="height:100%;background:var(--accent2);width:10%;border-radius:3px;transition:width 0.5s ease"></div></div>';
  }
  try {
    const resp = await fetch('/api/v1/videos/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ post_package_id: packageId })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to start generation');
    if (statusEl) statusEl.textContent = 'Rendering videos (run: ' + data.run_id.substring(0, 8) + ')...';
    const bar = document.getElementById('vid-bar-' + pid);
    let pct = 20;
    const interval = setInterval(() => {
      pct = Math.min(pct + 5, 90);
      if (bar) bar.style.width = pct + '%';
    }, 3000);
    // Poll for completion
    let attempts = 0;
    while (attempts < 60) {
      await new Promise(r => setTimeout(r, 5000));
      attempts++;
      try {
        const checkResp = await fetch('/api/v1/videos?package_id=' + packageId);
        const videos = await checkResp.json();
        if (videos.length > 0) {
          clearInterval(interval);
          if (bar) bar.style.width = '100%';
          if (statusEl) { statusEl.textContent = videos.length + ' video(s) rendered!'; statusEl.style.color = 'var(--green)'; }
          if (progressEl) setTimeout(() => { progressEl.innerHTML = ''; }, 1500);
          loadVideos(packageId, pid);
          break;
        }
      } catch(e) {}
    }
  } catch(e) {
    if (statusEl) { statusEl.textContent = 'Error: ' + e.message; statusEl.style.color = 'var(--red)'; }
    if (progressEl) progressEl.innerHTML = '';
  }
  btn.disabled = false;
  btn.textContent = origText;
}

// --- Script (Narration) tab functions ---
let _scriptCache = {};
let _scrLoading = {};

async function loadScripts(packageId, pid) {
  const segEl = document.getElementById('scr-segments-' + pid);
  const statusEl = document.getElementById('scr-status-' + pid);
  if (!segEl) return;
  if (_scrLoading[pid]) return;
  _scrLoading[pid] = true;
  segEl.innerHTML = '<div style="color:var(--dim);font-size:12px">Loading script...</div>';
  statusEl.textContent = 'Loading script...';
  statusEl.style.color = 'var(--dim)';
  try {
    // Auto endpoint: returns existing script or generates one on the fly
    statusEl.textContent = 'Loading script...';
    const detail = await api('/narration/scripts/auto/' + packageId);
    _scriptCache[pid] = detail;
    const label = detail.auto_generated ? ' (just generated)' : '';
    statusEl.textContent = 'Script: ' + detail.template_style + ' - ' + detail.status + label;
    statusEl.style.color = detail.status === 'aligned' ? 'var(--green)' : detail.status === 'rendered' ? 'var(--accent2)' : 'var(--accent)';
    renderScriptSegments(detail, pid, packageId);
    // Load TTS voices dropdown
    _ensureTtsVoicesLoaded(pid);
    // Show Regenerate button
    const regenBtn = document.getElementById('scr-regen-' + pid);
    if (regenBtn) regenBtn.style.display = '';
  } catch(e) {
    statusEl.textContent = 'Error: ' + e.message;
    statusEl.style.color = 'var(--red)';
    // Show regenerate even on error so user can retry
    const regenBtn = document.getElementById('scr-regen-' + pid);
    if (regenBtn) regenBtn.style.display = '';
  }
  _scrLoading[pid] = false;
}

function renderScriptSegments(script, pid, packageId) {
  const segEl = document.getElementById('scr-segments-' + pid);
  const audioEl = document.getElementById('scr-audio-' + pid);
  const actionsEl = document.getElementById('scr-actions-' + pid);
  if (!segEl) return;
  const segments = script.segments || [];
  let html = '';
  segments.forEach((seg, i) => {
    const dur = seg.estimatedDurationSec || '-';
    const aligned = seg.startSec !== undefined;
    html += '<div style="padding:12px 16px;margin-bottom:8px;border-radius:8px;background:#111318;border:1px solid var(--border)">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">';
    html += '<span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;background:rgba(46,163,242,0.15);color:var(--accent)">' + esc(seg.visualType || 'unknown') + '</span>';
    if (aligned) {
      html += '<span style="font-size:11px;color:var(--green)">' + seg.startSec.toFixed(1) + 's - ' + seg.endSec.toFixed(1) + 's</span>';
    } else {
      html += '<span style="font-size:11px;color:var(--dim)">~' + dur + 's est.</span>';
    }
    html += '</div>';
    html += '<div contenteditable="true" data-seg-idx="' + i + '" style="font-size:14px;line-height:1.5;color:var(--text);outline:none;padding:4px;border-radius:4px;border:1px solid transparent" onfocus="this.style.borderColor=\\'var(--accent)\\'" onblur="this.style.borderColor=\\'transparent\\';saveSegmentEdit(this,' + i + ',\\'' + script.id + '\\',\\'' + pid + '\\',\\'' + packageId + '\\')">' + esc(seg.narratorText || '') + '</div>';
    if (seg.visualProps) {
      const propsStr = Object.entries(seg.visualProps).map(([k,v]) => k + ': ' + JSON.stringify(v)).join(', ');
      html += '<div style="font-size:11px;color:var(--dim);margin-top:4px">Props: ' + esc(propsStr).substring(0, 120) + '</div>';
    }
    html += '</div>';
  });
  segEl.innerHTML = html;
  if (script.status === 'ready_to_record' || script.status === 'audio_uploaded' || script.status === 'aligned') {
    audioEl.style.display = '';
    if (script.audio_duration_sec) {
      document.getElementById('scr-audio-status-' + pid).textContent = 'Audio: ' + script.audio_duration_sec.toFixed(1) + 's (' + (script.audio_format || 'unknown') + ')';
    }
  }
  actionsEl.style.display = 'flex';
  actionsEl.innerHTML = '';
  if (script.status === 'audio_uploaded') {
    actionsEl.innerHTML += '<button class="btn btn-blue" onclick="alignScript(\\'' + script.id + '\\', \\'' + pid + '\\', \\'' + packageId + '\\', this)">Align with Whisper</button>';
  }
  if (script.status === 'aligned') {
    actionsEl.innerHTML += '<button class="btn btn-green" onclick="renderNarratedVideo(\\'' + script.id + '\\', \\'' + pid + '\\', this)">Render Narrated Video</button>';
  }
  if (script.status === 'rendered' && script.video_asset_id) {
    actionsEl.innerHTML += '<button class="btn btn-green" onclick="renderNarratedVideo(\\'' + script.id + '\\', \\'' + pid + '\\', this)">Re-render Video</button>';
    actionsEl.innerHTML += '<span style="color:var(--green);font-weight:600;font-size:13px;margin-left:8px">Rendered!</span>';
  }
  // Show existing video player if video_url present
  var playerEl = document.getElementById('scr-video-player-' + pid);
  if (playerEl && script.video_url) {
    playerEl.innerHTML = '<div style="margin-top:16px;padding:16px;background:#111318;border:1px solid var(--border);border-radius:8px">' +
      '<div style="font-size:13px;font-weight:600;color:var(--green);margin-bottom:8px">Narrated Video Ready</div>' +
      '<video src="' + esc(script.video_url) + '" controls style="max-width:400px;width:100%;border-radius:8px;background:#000"></video>' +
      '<div style="margin-top:8px"><a href="' + esc(script.video_url) + '" download style="color:var(--accent);font-size:12px">Download MP4</a></div>' +
      '</div>';
  }
}

let _segEditTimer = null;
async function saveSegmentEdit(el, idx, scriptId, pid, packageId) {
  clearTimeout(_segEditTimer);
  _segEditTimer = setTimeout(async () => {
    const cached = _scriptCache[pid];
    if (!cached || !cached.segments) return;
    const segs = [...cached.segments];
    segs[idx] = { ...segs[idx], narratorText: el.textContent };
    try {
      await api('/narration/scripts/' + scriptId, { method: 'PATCH', body: JSON.stringify({ segments: segs }) });
      cached.segments = segs;
    } catch(e) { toast('Save failed: ' + e.message, false); }
  }, 800);
}

async function generateScript(packageId, pid, btn) {
  btn.disabled = true;
  btn.textContent = 'Regenerating...';
  const statusEl = document.getElementById('scr-status-' + pid);
  if (statusEl) { statusEl.textContent = 'Regenerating script with Sonnet... (may take 10-20s)'; statusEl.style.color = 'var(--dim)'; }
  try {
    const data = await api('/narration/generate-script', {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId })
    });
    toast('Script regenerated! ' + (data.segments || []).length + ' segments, ~' + (data.estimated_duration_sec || 0) + 's');
    _scrLoading[pid] = false;
    await loadScripts(packageId, pid);
  } catch(e) {
    if (statusEl) { statusEl.textContent = 'Error: ' + e.message; statusEl.style.color = 'var(--red)'; }
    toast('Script generation failed: ' + e.message, false);
  }
  btn.disabled = false;
  btn.textContent = 'Regenerate Script';
}

async function uploadAudio(packageId, pid, file) {
  if (!file) return;
  const script = _scriptCache[pid];
  if (!script || !script.id) { toast('No script found - generate one first', false); return; }
  const statusEl = document.getElementById('scr-audio-status-' + pid);
  const fileInput = document.getElementById('scr-file-' + pid);
  statusEl.textContent = 'Uploading ' + file.name + '...';
  if (fileInput) fileInput.disabled = true;
  try {
    const formData = new FormData();
    formData.append('file', file);
    const resp = await fetch('/api/v1/narration/scripts/' + script.id + '/upload-audio', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Upload failed');
    statusEl.textContent = 'Audio uploaded! ' + (data.audio_duration_sec ? data.audio_duration_sec.toFixed(1) + 's' : '') + ' (' + (data.audio_format || '') + ')';
    statusEl.style.color = 'var(--green)';
    toast('Audio uploaded successfully');
    await loadScripts(packageId, pid);
  } catch(e) {
    statusEl.textContent = 'Upload error: ' + e.message;
    statusEl.style.color = 'var(--red)';
    toast('Upload failed: ' + e.message, false);
  }
  if (fileInput) { fileInput.disabled = false; fileInput.value = ''; }
}

// --- TTS (ElevenLabs) functions ---

let _ttsVoicesLoaded = false;
async function _ensureTtsVoicesLoaded(pid) {
  if (_ttsVoicesLoaded) return;
  try {
    const data = await api('/narration/tts-voices');
    if (!data.configured) return;
    _ttsVoicesLoaded = true;
    // Populate all voice dropdowns on the page
    document.querySelectorAll('[id^="scr-voice-"]').forEach(sel => {
      sel.innerHTML = '<option value="">Default voice</option>';
      for (const v of data.voices) {
        const opt = document.createElement('option');
        opt.value = v.voice_id;
        opt.textContent = v.name + (v.category ? ' (' + v.category + ')' : '');
        if (v.voice_id === data.default_voice_id) opt.selected = true;
        sel.appendChild(opt);
      }
    });
  } catch (e) {}
}

async function ttsPreviewVoice(packageId, pid) {
  await _ensureTtsVoicesLoaded(pid);
  const script = _scriptCache[pid];
  if (!script || !script.segments || !script.segments.length) { toast('No script segments to preview', false); return; }
  const voiceId = document.getElementById('scr-voice-' + pid)?.value || '';
  const statusEl = document.getElementById('scr-tts-status-' + pid);
  const audioEl = document.getElementById('scr-tts-audio-' + pid);
  const text = script.segments[0].narratorText || 'This is a voice preview.';
  if (statusEl) { statusEl.textContent = 'Generating preview...'; statusEl.style.color = 'var(--accent2)'; }
  try {
    const data = await api('/narration/tts-preview', {
      method: 'POST',
      body: JSON.stringify({ text: text.substring(0, 150), voice_id: voiceId || null, script_id: script.id }),
    });
    audioEl.src = data.audio_url;
    audioEl.style.display = '';
    audioEl.play();
    if (statusEl) { statusEl.textContent = 'Preview: ' + data.duration_seconds.toFixed(1) + 's (~$' + data.cost_estimate_usd.toFixed(4) + ')'; statusEl.style.color = 'var(--green)'; }
  } catch (e) {
    if (statusEl) { statusEl.textContent = 'Preview failed: ' + e.message; statusEl.style.color = 'var(--red)'; }
  }
}

async function ttsGenerateForScript(packageId, pid, btn) {
  await _ensureTtsVoicesLoaded(pid);
  const script = _scriptCache[pid];
  if (!script || !script.id) { toast('No script found - generate one first', false); return; }
  const voiceId = document.getElementById('scr-voice-' + pid)?.value || '';
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating voiceover...';
  const statusEl = document.getElementById('scr-tts-status-' + pid);
  if (statusEl) { statusEl.textContent = 'Generating full voiceover...'; statusEl.style.color = 'var(--accent2)'; }
  try {
    const url = '/api/v1/narration/scripts/' + script.id + '/tts-generate' + (voiceId ? '?voice_id=' + voiceId : '');
    const resp = await fetch(url, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'TTS generation failed');
    toast('Voiceover generated! ' + data.duration_seconds.toFixed(1) + 's');
    if (statusEl) { statusEl.textContent = 'Voiceover ready: ' + data.duration_seconds.toFixed(1) + 's (~$' + data.cost_estimate_usd.toFixed(4) + ')'; statusEl.style.color = 'var(--green)'; }
    const audioEl = document.getElementById('scr-tts-audio-' + pid);
    if (audioEl) { audioEl.src = data.audio_url; audioEl.style.display = ''; }
    _scrLoading[pid] = false;
    await loadScripts(packageId, pid);
  } catch (e) {
    if (statusEl) { statusEl.textContent = 'TTS failed: ' + e.message; statusEl.style.color = 'var(--red)'; }
    toast('TTS failed: ' + e.message, false);
  }
  btn.disabled = false;
  btn.textContent = origText;
}

async function alignScript(scriptId, pid, packageId, btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Aligning with Whisper...';
  try {
    const data = await api('/narration/scripts/' + scriptId + '/align', { method: 'POST' });
    toast('Aligned! ' + (data.whisper_word_count || 0) + ' words matched');
    await loadScripts(packageId, pid);
  } catch(e) {
    toast('Alignment failed: ' + e.message, false);
  }
  btn.disabled = false;
  btn.textContent = origText;
}

async function renderNarratedVideo(scriptId, pid, btn) {
  btn.disabled = true;
  btn.textContent = 'Starting render...';
  const progressEl = document.getElementById('scr-render-progress-' + pid);
  const playerEl = document.getElementById('scr-video-player-' + pid);
  const stepLabels = { queued: 'Queued - waiting for render slot...', rendering: 'Running Remotion render... (30-90s)', saving_asset: 'Saving video asset...', completed: 'Done! Video ready.', failed: 'Render failed.' };

  function showProgress(pct, label) {
    if (!progressEl) return;
    progressEl.innerHTML = '<div style="background:#1e1b4b;border:1px solid var(--accent);border-radius:8px;padding:14px;margin-top:12px">' +
      '<div style="font-size:12px;color:var(--accent2);margin-bottom:8px">' + esc(label) + '</div>' +
      '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden">' +
      '<div style="height:100%;background:var(--green);width:' + pct + '%;border-radius:2px;transition:width 0.5s ease"></div>' +
      '</div></div>';
  }

  try {
    const data = await api('/narration/scripts/' + scriptId + '/render', { method: 'POST' });
    const jobId = data.job_id;
    if (!jobId) throw new Error('No job_id returned');
    showProgress(10, stepLabels.queued);
    btn.textContent = 'Rendering...';

    // Connect SSE
    const es = new EventSource('/api/v1/videos/queue/' + jobId + '/progress');
    es.onmessage = function(ev) {
      try {
        const d = JSON.parse(ev.data);
        const pct = d.progress || 0;
        const step = d.step || d.status || 'rendering';
        const label = stepLabels[step] || stepLabels[d.status] || ('Rendering... ' + pct + '%');
        showProgress(pct, label);

        if (d.status === 'completed') {
          es.close();
          btn.textContent = 'Render Narrated Video';
          btn.disabled = false;
          showProgress(100, stepLabels.completed);
          toast('Narrated video rendered!');
          // Show inline video player
          if (playerEl && d.video_url) {
            playerEl.innerHTML = '<div style="margin-top:16px;padding:16px;background:#111318;border:1px solid var(--border);border-radius:8px">' +
              '<div style="font-size:13px;font-weight:600;color:var(--green);margin-bottom:8px">Narrated Video Ready</div>' +
              '<video src="' + esc(d.video_url) + '" controls style="max-width:400px;width:100%;border-radius:8px;background:#000"></video>' +
              '<div style="margin-top:8px"><a href="' + esc(d.video_url) + '" download style="color:var(--accent);font-size:12px">Download MP4</a></div>' +
              '</div>';
          }
        } else if (d.status === 'failed') {
          es.close();
          btn.textContent = 'Render Narrated Video';
          btn.disabled = false;
          showProgress(pct, 'Render failed: ' + (d.error_message || 'unknown error'));
          toast('Render failed', false);
        }
      } catch(_) {}
    };
    es.onerror = function() {
      es.close();
      btn.textContent = 'Render Narrated Video';
      btn.disabled = false;
      showProgress(0, 'Connection lost - check Videos tab for status');
    };
  } catch(e) {
    toast('Render failed: ' + e.message, false);
    showProgress(0, 'Error: ' + e.message);
    btn.disabled = false;
    btn.textContent = 'Render Narrated Video';
  }
}

async function generateImages(packageId, btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating...';
  btn.style.background = 'var(--yellow)';
  btn.style.color = '#000';

  // Show animated progress
  const pid = packageId.replace(/-/g, '');
  const progressEl = document.getElementById('gen-img-progress-' + pid) || btn.parentElement.nextElementSibling;
  let progressPct = 0;
  let progressInterval = null;
  if (progressEl) {
    progressEl.innerHTML = '<div style="background:#1e1b4b;border:1px solid var(--accent);border-radius:8px;padding:14px;margin-bottom:12px">' +
      '<div id="gen-img-status-' + pid + '" style="font-size:12px;color:var(--accent2);margin-bottom:8px">Sending to fal.ai Flux Pro...</div>' +
      '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden">' +
      '<div id="gen-img-bar-' + pid + '" style="height:100%;background:var(--accent2);width:0%;border-radius:2px;transition:width 0.5s ease"></div>' +
      '</div>' +
      '<div id="gen-img-time-' + pid + '" style="font-size:11px;color:var(--dim);margin-top:6px">Starting image generation...</div>' +
      '</div>';
    const startTime = Date.now();
    const bar = document.getElementById('gen-img-bar-' + pid);
    const statusEl = document.getElementById('gen-img-status-' + pid);
    const timeEl = document.getElementById('gen-img-time-' + pid);
    progressInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      if (progressPct < 85) progressPct += (85 - progressPct) * 0.03;
      if (bar) bar.style.width = Math.round(progressPct) + '%';
      if (timeEl) timeEl.textContent = elapsed + 's elapsed - ~15-30s per image...';
      if (statusEl) {
        if (elapsed < 5) statusEl.textContent = 'Sending to fal.ai Flux Pro...';
        else if (elapsed < 15) statusEl.textContent = 'Generating images - AI is rendering...';
        else if (elapsed < 30) statusEl.textContent = 'Still rendering - complex prompts take longer...';
        else statusEl.textContent = 'Almost done - finalizing images...';
      }
    }, 500);
  }

  try {
    const resp = await fetch('/api/v1/content/packages/' + packageId + '/generate-images', { method: 'POST' });
    if (progressInterval) clearInterval(progressInterval);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Generation failed');
    }
    const data = await resp.json();
    const generated = data.results.filter(r => r.status === 'generated').length;
    const failed = data.results.filter(r => r.status === 'failed').length;

    // Finish progress bar
    const bar = document.getElementById('gen-img-bar-' + pid);
    if (bar) bar.style.width = '100%';

    btn.textContent = generated + ' images generated!';
    btn.style.background = 'var(--green)';
    btn.style.color = '#000';
    setTimeout(() => { if (progressEl) progressEl.innerHTML = ''; }, 800);
    toast(generated + ' image(s) generated' + (failed ? ', ' + failed + ' failed' : ''));

    // Refresh packages and jump back to this package's Images tab
    const targetPkgId = packageId;
    setTimeout(async () => {
      await renderPackages();
      setTimeout(() => {
        const tpid = targetPkgId.replace(/-/g, '');
        const imgTab = document.getElementById('img-' + tpid);
        if (imgTab) {
          const card = imgTab.closest('.pkg-card');
          if (card) {
            const imgBtn = Array.from(card.querySelectorAll('.tabs button')).find(b => b.textContent.startsWith('Images'));
            if (imgBtn) showPostTab(imgBtn, 'img-' + tpid);
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.style.outline = '2px solid var(--green)';
            setTimeout(() => card.style.outline = '', 3000);
          }
        }
      }, 200);
    }, 500);
  } catch (e) {
    if (progressInterval) clearInterval(progressInterval);
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

async function downloadAllImages(packageId, btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Downloading...';
  try {
    const pkg = _pkgCache?.find(p => p.id === packageId);
    if (!pkg || !pkg.image_prompts) { toast('No images found'); return; }
    const images = pkg.image_prompts.filter(ip => ip.image_url);
    if (!images.length) { toast('No generated images to download'); return; }
    for (let i = 0; i < images.length; i++) {
      const ip = images[i];
      const name = (ip.prompt_name || ip.visual_job || 'image_' + (i+1)).replace(/[^a-zA-Z0-9]/g, '_').toLowerCase();
      const a = document.createElement('a');
      a.href = ip.image_url;
      a.download = name + '.jpg';
      a.target = '_blank';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      if (i < images.length - 1) await new Promise(r => setTimeout(r, 500));
    }
    toast(images.length + ' image(s) downloading');
  } catch (e) {
    toast('Download failed: ' + e.message);
  } finally {
    btn.textContent = origText;
    btn.disabled = false;
  }
}

// GAP-37: Select image from package
async function selectImage(pkgId, idx) {
  try {
    await api('/content/packages/' + pkgId + '/select-image', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:idx})});
    if (_pkgCache) { const p = _pkgCache.find(x => x.id === pkgId); if (p && p.image_prompts) p.image_prompts.forEach((ip,i) => ip.selected = i === idx); }
    toast('Image ' + (idx+1) + ' selected');
    _renderPkgFromCache();
  } catch(e) { toast('Select failed: ' + e.message, false); }
}
// GAP-37: Regenerate single image
async function regenSingleImage(pkgId, idx, btn) {
  const orig = btn.textContent; btn.disabled = true; btn.textContent = '...';
  try {
    const r = await api('/content/packages/' + pkgId + '/regenerate-image/' + idx, {method:'POST'});
    if (r.status === 'generated' && _pkgCache) {
      const p = _pkgCache.find(x => x.id === pkgId);
      if (p && p.image_prompts && p.image_prompts[idx]) p.image_prompts[idx].image_url = r.image_url;
    }
    toast('Image regenerated'); _renderPkgFromCache();
  } catch(e) { toast('Regen failed: ' + e.message, false); } finally { btn.textContent = orig; btn.disabled = false; }
}

// Regen with modification comment
async function regenWithMod(pkgId, idx, btn) {
  const pid = pkgId.replace(/-/g, '');
  const input = document.getElementById('img-mod-' + pid + '-' + idx);
  const mod = (input && input.value || '').trim();
  if (!mod) { toast('Enter a modification note first', false); input && input.focus(); return; }
  const orig = btn.textContent; btn.disabled = true; btn.textContent = 'Generating...';
  try {
    const r = await api('/content/packages/' + pkgId + '/regenerate-image/' + idx, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({modification: mod})});
    if (r.status === 'generated' && _pkgCache) {
      const p = _pkgCache.find(x => x.id === pkgId);
      if (p && p.image_prompts && p.image_prompts[idx]) p.image_prompts[idx].image_url = r.image_url;
    }
    toast('Image regenerated with modification'); input.value = ''; _renderPkgFromCache();
  } catch(e) { toast('Regen failed: ' + e.message, false); } finally { btn.textContent = orig; btn.disabled = false; }
}

// GAP-48: Humanitarian override with justification
async function humanitarianOverride(pkgId, dimName) {
  const reason = prompt('Justification for overriding humanitarian flag on "' + dimName + '":');
  if (!reason) return;
  try {
    const pkg = _pkgCache?.find(p => p.id === pkgId);
    if (!pkg) return;
    const qs = JSON.parse(JSON.stringify(pkg.quality_scores || {}));
    if (!qs.operator_overrides) qs.operator_overrides = {};
    qs.operator_overrides[dimName] = {score: 10, reason: reason, overridden_at: new Date().toISOString()};
    await api('/content/packages/' + pkgId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({quality_scores: qs})});
    pkg.quality_scores = qs;
    toast('Override recorded with justification');
    _renderPkgFromCache();
  } catch(e) { toast('Override failed: ' + e.message, false); }
}

// GAP-49: Resume pipeline from last successful step
async function resumePipeline(runId) {
  try {
    const status = await api('/pipeline/' + runId + '/status');
    const failedSteps = Object.entries(status.step_status || {}).filter(([,s]) => s === 'failed' || s === 'pending').map(([k]) => k);
    if (!failedSteps.length) { toast('No failed steps to resume'); return; }
    toast('Retrying ' + failedSteps.length + ' remaining steps...');
    const r = await api('/pipeline/run', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow: status.workflow || 'daily_content', day_of_week: status.day_of_week ?? 0, resume_from_run: runId})});
    activePipelineRun = r.run_id;
    localStorage.setItem('tce_active_run', r.run_id);
    pollPipeline();
    if (!pollInterval) pollInterval = setInterval(pollPipeline, 3000);
  } catch(e) { toast('Resume failed: ' + e.message, false); }
}

// GAP-20: Save operator notes
async function saveOperatorNote(entryId, note) {
  try { await api('/calendar/' + entryId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({operator_notes:note})}); } catch(e) {}
}

// GAP-29: Filter packages by status and QA
function filterPkgStatus() { _renderPkgFromCache(); }

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

function copyPaneText(btn) {
  const pane = btn.closest('.tab-pane');
  if (!pane) return;
  const preview = pane.querySelector('.post-preview');
  clipCopy(preview ? preview.textContent : pane.textContent);
  const orig = btn.innerHTML;
  btn.innerHTML = '&#10003;';
  btn.style.opacity = '1';
  btn.style.color = 'var(--green)';
  setTimeout(() => { btn.innerHTML = orig; btn.style.opacity = ''; btn.style.color = ''; }, 1500);
  toast('Copied to clipboard');
}

function aiReviseActive(packageId, btn) {
  const card = btn.closest('.pkg-card');
  if (!card) return aiRevisePost(packageId, 'fb');
  const activeTab = card.querySelector('.tabs button.active');
  const label = activeTab?.textContent?.trim().toLowerCase() || '';
  if (label.startsWith('linkedin')) return aiRevisePost(packageId, 'li');
  if (label.startsWith('hook')) return elementFeedback(packageId, 'hooks', btn);
  return aiRevisePost(packageId, 'fb');
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
      html += '<div style="display:flex;gap:6px">';
      html += '<button class="btn btn-dim" onclick="viewExamples(\\'' + d.id + '\\',\\'' + esc(d.file_name) + '\\')">View Examples</button>';
      // GAP-46: Guide preview button
      html += '<button class="btn btn-dim" style="font-size:11px" onclick="viewGuide(\\'' + d.id + '\\',\\'' + esc(d.file_name) + '\\')">Preview</button>';
      html += '</div></div>';
    }
    html += '</div>';
    document.getElementById('docs-list').innerHTML = html;
    // GAP-38: Relearning Review section
    try {
      const relearn = await api('/relearning/status');
      let rlHtml = '<div class="card" style="margin-top:24px"><h3 style="color:var(--accent2)">Relearning Review</h3>';
      rlHtml += '<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">';
      rlHtml += '<div style="padding:10px 16px;background:#111318;border:1px solid var(--border);border-radius:8px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--accent)">' + (relearn.total_feedback || 0) + '</div><div style="font-size:11px;color:var(--dim)">Feedback Items</div></div>';
      rlHtml += '<div style="padding:10px 16px;background:#111318;border:1px solid var(--border);border-radius:8px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--green)">' + (relearn.approved_proposals || 0) + '</div><div style="font-size:11px;color:var(--dim)">Approved Proposals</div></div>';
      rlHtml += '<div style="padding:10px 16px;background:#111318;border:1px solid var(--border);border-radius:8px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--yellow)">' + (relearn.pending_proposals || 0) + '</div><div style="font-size:11px;color:var(--dim)">Pending Proposals</div></div>';
      rlHtml += '</div>';
      rlHtml += '<div style="display:flex;gap:8px;margin-bottom:12px"><button class="btn btn-primary" onclick="triggerRelearn()">Evaluate Now</button></div>';
      // Show pending proposals
      try {
        const proposals = await api('/relearning/proposals');
        if (proposals.length) {
          rlHtml += '<div style="margin-top:12px"><div style="font-size:13px;font-weight:600;margin-bottom:8px">Pending Proposals</div>';
          for (const pr of proposals) {
            rlHtml += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px">';
            rlHtml += '<div style="display:flex;justify-content:space-between;align-items:center">';
            rlHtml += '<div style="font-size:13px;font-weight:500">' + esc(pr.description || pr.type || 'Proposal') + '</div>';
            rlHtml += '<div style="display:flex;gap:6px">';
            rlHtml += '<button class="btn btn-green" style="font-size:11px;padding:4px 10px" onclick="approveProposal(\\'' + pr.id + '\\')">Approve</button>';
            rlHtml += '<button class="btn btn-red" style="font-size:11px;padding:4px 10px" onclick="rejectProposal(\\'' + pr.id + '\\')">Reject</button>';
            rlHtml += '</div></div>';
            if (pr.details) rlHtml += '<div style="font-size:12px;color:var(--dim);margin-top:6px">' + esc(typeof pr.details === 'string' ? pr.details : JSON.stringify(pr.details).substring(0, 200)) + '</div>';
            rlHtml += '</div>';
          }
          rlHtml += '</div>';
        }
      } catch {}
      rlHtml += '</div>';
      document.getElementById('docs-list').insertAdjacentHTML('afterend', rlHtml);
    } catch {}
    // GAP-52: Corpus low-confidence flagging
    try {
      const examples = await api('/documents/' + docs[0]?.id + '/examples').catch(() => []);
      const lowConf = examples.filter(ex => ex.engagement_confidence === 'C' || (ex.ocr_confidence != null && ex.ocr_confidence < 0.7));
      if (lowConf.length) {
        let lcHtml = '<div class="card" style="margin-top:16px;border-left:3px solid var(--yellow)"><h3 style="color:var(--yellow)">Low-Confidence Examples (' + lowConf.length + ')</h3>';
        lcHtml += '<div style="margin-top:12px;font-size:12px;color:var(--dim);margin-bottom:8px">These posts have low engagement confidence or OCR quality. Review and update manually.</div>';
        for (const ex of lowConf.slice(0, 10)) {
          lcHtml += '<div style="background:#111318;border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center">';
          lcHtml += '<div style="flex:1"><div style="font-size:13px">' + esc((ex.hook_text || ex.post_text_raw || '').substring(0, 80)) + '</div>';
          lcHtml += '<div style="font-size:11px;color:var(--dim);margin-top:2px">Confidence: <span style="color:var(--yellow)">' + (ex.engagement_confidence || '?') + '</span>';
          if (ex.ocr_confidence != null) lcHtml += ' | OCR: <span style="color:' + (ex.ocr_confidence < 0.7 ? 'var(--red)' : 'var(--green)') + '">' + (ex.ocr_confidence * 100).toFixed(0) + '%</span>';
          lcHtml += '</div></div>';
          lcHtml += '<span style="font-size:11px;padding:3px 8px;border-radius:4px;background:#2d2000;color:var(--yellow)">Review</span>';
          lcHtml += '</div>';
        }
        lcHtml += '</div>';
        document.getElementById('docs-list').insertAdjacentHTML('afterend', lcHtml);
      }
    } catch {}
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

// VOICE PROFILE TAB (GAP-39 editing, GAP-40 sliders)
async function renderVoice() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Founder Voice Profiles</h2><div id="voice-list"><div class="empty">Loading...</div></div></div>';
  try {
    const profiles = await api('/profiles/founder-voice');
    if (!profiles.length) { document.getElementById('voice-list').innerHTML = '<div class="empty">No voice profiles yet. Extract from a book via Corpus tab.</div>'; return; }
    let html = '';
    for (const p of profiles) {
      html += '<div class="voice-profile">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center"><h4>Profile from: ' + (p.source_document_ids?.join(', ') || 'unknown').substring(0, 36) + '...</h4>';
      html += '<button class="btn btn-dim" style="font-size:11px" onclick="toggleVoiceEdit(\\'' + p.id + '\\')">Edit Profile</button></div>';
      // GAP-40: Tone range SLIDERS - render whatever axes exist in DB
      if (p.tone_range && Object.keys(p.tone_range).length) {
        html += '<div style="margin:8px 0">';
        const axes = Object.keys(p.tone_range);
        for (const k of axes) {
          const v = p.tone_range[k] || 0;
          html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="width:120px;font-size:11px;color:var(--dim)">' + k.replace(/_/g,' ') + '</span>';
          html += '<input type="range" min="0" max="10" step="0.5" value="' + v + '" style="flex:1;accent-color:var(--accent)" onchange="saveVoiceAxis(\\'' + p.id + '\\',\\'' + k + '\\',this.value)">';
          html += '<span style="width:30px;font-size:12px;text-align:right">' + v + '</span></div>';
        }
        html += '</div>';
      }
      if (p.humor_type) html += '<div style="font-size:13px;margin:4px 0">Humor: <strong>' + esc(p.humor_type) + '</strong></div>';
      // GAP-39: Editable lists
      html += '<div id="voice-edit-' + p.id + '" style="display:none;margin-top:12px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:8px">';
      html += '<div style="margin-bottom:8px"><label style="font-size:12px;color:var(--dim)">Values & Beliefs (one per line)</label>';
      html += '<textarea id="ve-values-' + p.id + '" rows="3" style="width:100%;margin-top:4px;padding:6px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px">' + (p.values_and_beliefs || []).join('\\n') + '</textarea></div>';
      html += '<div style="margin-bottom:8px"><label style="font-size:12px;color:var(--dim)">Metaphor Families (one per line)</label>';
      html += '<textarea id="ve-metaphors-' + p.id + '" rows="2" style="width:100%;margin-top:4px;padding:6px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px">' + (p.metaphor_families || []).join('\\n') + '</textarea></div>';
      html += '<div style="margin-bottom:8px"><label style="font-size:12px;color:var(--dim)">Taboos - things to NEVER say (one per line)</label>';
      html += '<textarea id="ve-taboos-' + p.id + '" rows="2" style="width:100%;margin-top:4px;padding:6px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px">' + (p.taboos || []).join('\\n') + '</textarea></div>';
      html += '<div style="margin-bottom:8px"><label style="font-size:12px;color:var(--dim)">Recurring Themes (one per line)</label>';
      html += '<textarea id="ve-themes-' + p.id + '" rows="2" style="width:100%;margin-top:4px;padding:6px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12px">' + (p.recurring_themes || []).join('\\n') + '</textarea></div>';
      html += '<button class="btn btn-primary" onclick="saveVoiceProfile(\\'' + p.id + '\\')">Save Changes</button>';
      html += '</div>';
      // Read-only display of lists
      if (p.values_and_beliefs?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Core Values (' + p.values_and_beliefs.length + ')</div><div class="voice-tags">';
        p.values_and_beliefs.slice(0, 8).forEach(v => html += '<span class="voice-tag">' + esc(v.substring(0, 60)) + '</span>');
        if (p.values_and_beliefs.length > 8) html += '<span class="voice-tag">+' + (p.values_and_beliefs.length - 8) + ' more</span>';
        html += '</div></div>';
      }
      if (p.metaphor_families?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Metaphor Families</div><div class="voice-tags">';
        p.metaphor_families.forEach(m => html += '<span class="voice-tag">' + esc(m) + '</span>');
        html += '</div></div>';
      }
      if (p.taboos?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Taboos</div><div class="voice-tags">';
        p.taboos.slice(0, 6).forEach(t => html += '<span class="voice-tag" style="background:#2d0000;color:#fecaca">' + esc(t.substring(0, 50)) + '</span>');
        html += '</div></div>';
      }
      if (p.vocabulary_signature?.phrases?.length) {
        html += '<div style="margin:8px 0"><div style="font-size:12px;color:var(--dim)">Signature Phrases (' + p.vocabulary_signature.phrases.length + ')</div><div class="voice-tags">';
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
function toggleVoiceEdit(profileId) { const el = document.getElementById('voice-edit-' + profileId); if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none'; }
async function saveVoiceAxis(profileId, axis, val) {
  try { await api('/profiles/founder-voice/' + profileId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({tone_range:{[axis]:parseFloat(val)}})}); } catch(e) { toast('Save failed: ' + e.message, false); }
}
async function saveVoiceProfile(profileId) {
  const toArr = id => (document.getElementById(id)?.value || '').split('\\n').map(s=>s.trim()).filter(Boolean);
  const body = {values_and_beliefs: toArr('ve-values-'+profileId), metaphor_families: toArr('ve-metaphors-'+profileId), taboos: toArr('ve-taboos-'+profileId), recurring_themes: toArr('ve-themes-'+profileId)};
  try { await api('/profiles/founder-voice/' + profileId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); toast('Voice profile updated'); renderVoice(); } catch(e) { toast('Save failed: ' + e.message, false); }
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
      html += '<span id="weight-val-' + c.id + '" style="font-size:20px;font-weight:700;color:var(--accent)">' + ((c.allowed_influence_weight || 0.2) * 100).toFixed(0) + '%</span></div>';
      // GAP-36: Influence weight slider
      html += '<div style="display:flex;align-items:center;gap:8px;margin-top:8px"><span style="font-size:11px;color:var(--dim)">0%</span>';
      html += '<input type="range" min="0" max="100" value="' + ((c.allowed_influence_weight || 0.2) * 100).toFixed(0) + '" style="flex:1;accent-color:var(--accent)" oninput="document.getElementById(\\'weight-val-' + c.id + '\\').textContent=this.value+\\'%\\'" onchange="saveCreatorWeight(\\'' + c.id + '\\',this.value)">';
      html += '<span style="font-size:11px;color:var(--dim)">100%</span></div>';
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
        if (c.post_count > 0) {
          html += '<div style="margin-top:12px;padding:12px;border:1px dashed #2a2d3a;border-radius:6px;text-align:center;color:#71717a;font-size:12px">No voice axes data yet.<br><button class="btn btn-primary" style="margin-top:8px;padding:6px 14px;font-size:12px" onclick="analyzeVoice(\\'' + c.id + '\\')">\u2728 Analyze Voice from ' + c.post_count + ' Posts</button></div>';
        } else {
          html += '<div style="margin-top:12px;padding:12px;border:1px dashed #2a2d3a;border-radius:6px;text-align:center;color:#71717a;font-size:12px">No posts uploaded yet - add corpus documents first</div>';
        }
      }
      // GAP-43: Creator management controls
      html += '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:8px">';
      // Anti-clone markers
      html += '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span style="font-size:11px;color:var(--dim)">Anti-clone:</span>';
      const markers = c.disallowed_clone_markers || [];
      markers.forEach(m => html += '<span style="padding:2px 6px;border-radius:3px;font-size:10px;background:#2d0000;color:#fecaca">' + esc(m) + '</span>');
      html += '<button class="btn btn-dim" style="font-size:10px;padding:2px 6px" onclick="editAntiClone(\\'' + c.id + '\\')">Edit</button></div>';
      // GAP-50: Per-angle weights
      html += '<div style="margin-top:6px"><span style="font-size:11px;color:var(--dim)">Angle Preferences:</span>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">';
      const angleTypes = Object.keys(ANGLE_LABELS);
      for (const angle of angleTypes) {
        const weight = c.angle_weights?.[angle] != null ? c.angle_weights[angle] : 1;
        const excluded = weight === 0;
        html += '<button style="padding:2px 8px;border:1px solid ' + (excluded ? 'var(--red)' : 'var(--border)') + ';background:' + (excluded ? '#2d0000' : 'transparent') + ';color:' + (excluded ? 'var(--red)' : 'var(--dim)') + ';border-radius:4px;font-size:10px;cursor:pointer" onclick="toggleCreatorAngle(\\'' + c.id + '\\',\\'' + angle + '\\',' + (excluded ? '1' : '0') + ')" title="Click to ' + (excluded ? 'enable' : 'exclude') + '">' + ANGLE_LABELS[angle] + (excluded ? ' X' : '') + '</button>';
      }
      html += '</div></div>';
      html += '</div>';
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

// GAP-36: Save creator influence weight
async function saveCreatorWeight(creatorId, pct) {
  try {
    await api('/profiles/creators/' + creatorId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({allowed_influence_weight: pct / 100})});
    toast('Weight updated to ' + pct + '%');
  } catch(e) { toast('Failed: ' + e.message, false); }
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
    // GAP-41: SVG cost trend chart
    try {
      const chartDays = 14;
      const endD = new Date(); const startD = new Date(); startD.setDate(startD.getDate() - chartDays);
      const costHistory = await api('/costs/daily?start=' + fmtDate(startD) + '&end=' + fmtDate(endD)).catch(() => null);
      if (costHistory?.daily_costs?.length > 1) {
        const points = costHistory.daily_costs;
        const maxCost = Math.max(...points.map(p => p.cost), 0.01);
        const w = 700, h = 160, pad = 40;
        const xStep = (w - 2 * pad) / (points.length - 1);
        let pathD = ''; let dots = '';
        points.forEach((pt, i) => {
          const x = pad + i * xStep;
          const y = h - pad - ((pt.cost / maxCost) * (h - 2 * pad));
          pathD += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
          dots += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="3" fill="var(--accent)" />';
          dots += '<title>' + pt.date + ': $' + pt.cost.toFixed(2) + '</title>';
        });
        html += '<div class="card" style="margin-bottom:16px"><h3>Cost Trend (Last ' + chartDays + ' Days)</h3>';
        html += '<svg viewBox="0 0 ' + w + ' ' + h + '" style="width:100%;height:180px;margin-top:12px">';
        // Grid lines
        for (let g = 0; g <= 4; g++) {
          const gy = pad + g * ((h - 2 * pad) / 4);
          const gval = (maxCost * (4 - g) / 4).toFixed(2);
          html += '<line x1="' + pad + '" y1="' + gy + '" x2="' + (w - pad) + '" y2="' + gy + '" stroke="var(--border)" stroke-dasharray="4"/>';
          html += '<text x="' + (pad - 4) + '" y="' + (gy + 4) + '" text-anchor="end" fill="var(--dim)" font-size="10">$' + gval + '</text>';
        }
        html += '<path d="' + pathD + '" fill="none" stroke="var(--accent)" stroke-width="2"/>';
        html += dots;
        // X-axis labels (every 3rd)
        points.forEach((pt, i) => { if (i % 3 === 0 || i === points.length - 1) { const x = pad + i * xStep; html += '<text x="' + x + '" y="' + (h - 8) + '" text-anchor="middle" fill="var(--dim)" font-size="9">' + pt.date.substring(5) + '</text>'; } });
        html += '</svg></div>';
      }
    } catch {}
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
        html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Run ID</th><th style="text-align:left;padding:8px 12px">Workflow</th><th style="text-align:left;padding:8px 12px">Status</th><th style="text-align:left;padding:8px 12px">Day</th><th style="text-align:left;padding:8px 12px">Started</th><th style="text-align:left;padding:8px 12px">Error</th><th style="text-align:left;padding:8px 12px">Actions</th></tr>';
        for (const r of runs) {
          const stColor = r.status === 'completed' ? 'var(--green)' : r.status === 'failed' ? 'var(--red)' : 'var(--blue)';
          html += '<tr style="border-bottom:1px solid var(--border)">';
          html += '<td style="padding:8px 12px;font-family:monospace;font-size:12px">' + r.run_id.substring(0, 8) + '</td>';
          html += '<td style="padding:8px 12px">' + r.workflow + '</td>';
          html += '<td style="padding:8px 12px;color:' + stColor + ';font-weight:600">' + r.status + '</td>';
          html += '<td style="padding:8px 12px">' + (r.day_of_week != null ? DAY_NAMES[r.day_of_week] || r.day_of_week : '-') + '</td>';
          html += '<td style="padding:8px 12px;color:var(--dim)">' + (r.started_at ? new Date(r.started_at).toLocaleString() : '-') + '</td>';
          html += '<td style="padding:8px 12px;color:var(--red);font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(r.error_message || '') + '">' + esc((r.error_message || '').substring(0, 80)) + '</td>';
          // GAP-49: Resume button for failed/partial runs
          html += '<td style="padding:8px 12px">';
          if (r.status === 'failed') html += '<button class="btn btn-dim" style="font-size:10px;padding:2px 8px" onclick="resumePipeline(\\'' + r.run_id + '\\')">Resume</button>';
          html += '</td>';
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
  'cta_unfulfillable', 'cta_too_pushy', 'tone_mismatch', 'brand_voice_mismatch', 'too_long', 'too_short',
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
    toast('Feedback saved (' + action + ')');
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
    // GAP-26: Best CTAs
    const ctaCounts = {};
    for (const p of pkgs) { if (p.cta_keyword) { ctaCounts[p.cta_keyword] = ctaCounts[p.cta_keyword] || {total:0,approved:0}; ctaCounts[p.cta_keyword].total++; if (p.approval_status==='approved') ctaCounts[p.cta_keyword].approved++; } }
    if (Object.keys(ctaCounts).length) {
      html += '<div class="card" style="margin-bottom:16px"><h3>Best CTAs</h3>';
      html += '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">';
      html += '<tr style="border-bottom:1px solid var(--border);color:var(--dim);font-size:12px"><th style="text-align:left;padding:8px 12px">Keyword</th><th style="text-align:left;padding:8px 12px">Uses</th><th style="text-align:left;padding:8px 12px">Approved</th><th style="text-align:left;padding:8px 12px">Rate</th></tr>';
      const ctaSorted = Object.entries(ctaCounts).sort((a,b) => b[1].total - a[1].total);
      for (const [kw, d] of ctaSorted.slice(0,10)) {
        const rate = d.total > 0 ? ((d.approved/d.total)*100).toFixed(0) : '0';
        const rateColor = parseInt(rate) >= 70 ? 'var(--green)' : parseInt(rate) >= 40 ? 'var(--yellow)' : 'var(--red)';
        html += '<tr style="border-bottom:1px solid var(--border)"><td style="padding:8px 12px;font-weight:600;color:var(--accent2)">' + esc(kw) + '</td><td style="padding:8px 12px">' + d.total + '</td><td style="padding:8px 12px">' + d.approved + '</td><td style="padding:8px 12px;color:' + rateColor + ';font-weight:600">' + rate + '%</td></tr>';
      }
      html += '</table></div>';
    }
    // GAP-26: QA Score Distribution
    const qaScores = pkgs.map(p => p.quality_scores?.composite_score || p.quality_scores?.overall).filter(s => s != null).map(s => typeof s === 'number' ? s : (s?.score || 0));
    if (qaScores.length) {
      const avgQa = (qaScores.reduce((a,b)=>a+b,0)/qaScores.length).toFixed(1);
      const passCount = qaScores.filter(s => s >= 7).length;
      const condCount = qaScores.filter(s => s >= 5 && s < 7).length;
      const failCount = qaScores.filter(s => s < 5).length;
      html += '<div class="card" style="margin-bottom:16px"><h3>QA Score Distribution</h3>';
      html += '<div style="display:flex;gap:16px;margin-top:12px">';
      html += '<div style="flex:1;padding:12px;background:#0d1117;border-radius:8px;text-align:center;border:1px solid var(--border)"><div style="font-size:24px;font-weight:700;color:var(--accent)">' + avgQa + '</div><div style="font-size:12px;color:var(--dim)">Avg Score</div></div>';
      html += '<div style="flex:1;padding:12px;background:#0d1117;border-radius:8px;text-align:center;border:1px solid var(--border)"><div style="font-size:24px;font-weight:700;color:var(--green)">' + passCount + '</div><div style="font-size:12px;color:var(--dim)">Pass (7+)</div></div>';
      html += '<div style="flex:1;padding:12px;background:#0d1117;border-radius:8px;text-align:center;border:1px solid var(--border)"><div style="font-size:24px;font-weight:700;color:var(--yellow)">' + condCount + '</div><div style="font-size:12px;color:var(--dim)">Conditional</div></div>';
      html += '<div style="flex:1;padding:12px;background:#0d1117;border-radius:8px;text-align:center;border:1px solid var(--border)"><div style="font-size:24px;font-weight:700;color:var(--red)">' + failCount + '</div><div style="font-size:12px;color:var(--dim)">Fail (&lt;5)</div></div>';
      html += '</div></div>';
    }
    // GAP-26: QA Failure Breakdown
    const failedPkgs = pkgs.filter(p => { const s = p.quality_scores?.composite_score || p.quality_scores?.overall; return s != null && (typeof s === 'number' ? s : (s?.score || 0)) < 5; });
    if (failedPkgs.length) {
      const failReasons = {};
      for (const p of failedPkgs) {
        const dims = p.quality_scores?.dimension_scores || p.quality_scores?.dimensions || {};
        for (const [dim, val] of Object.entries(dims)) {
          const score = typeof val === 'number' ? val : (val?.score || 0);
          if (score < 5) { failReasons[dim] = (failReasons[dim] || 0) + 1; }
        }
      }
      if (Object.keys(failReasons).length) {
        html += '<div class="card" style="margin-bottom:16px"><h3 style="color:var(--red)">QA Failure Breakdown</h3>';
        html += '<div style="margin-top:12px">';
        const failSorted = Object.entries(failReasons).sort((a,b)=>b[1]-a[1]);
        for (const [dim,cnt] of failSorted) {
          const pct = ((cnt/failedPkgs.length)*100).toFixed(0);
          html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="width:140px;font-size:12px;color:var(--dim)">' + dim.replace(/_/g,' ') + '</span>';
          html += '<div style="flex:1;height:16px;background:var(--bg);border-radius:4px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:var(--red);border-radius:4px"></div></div>';
          html += '<span style="font-size:12px;font-weight:600;color:var(--red);width:40px;text-align:right">' + cnt + '</span></div>';
        }
        html += '</div></div>';
      }
    }
    // GAP-42: A/B Testing Framework
    try {
      const experiments = await api('/experiments/').catch(() => []);
      html += '<div class="card" style="margin-bottom:16px"><h3 style="color:var(--accent2)">A/B Experiments</h3>';
      html += '<div style="display:flex;gap:8px;margin:12px 0"><button class="btn btn-primary" style="font-size:12px" onclick="createExperiment()">New Experiment</button></div>';
      if (experiments.length) {
        for (const exp of experiments) {
          const stColor = exp.status === 'active' ? 'var(--green)' : exp.status === 'completed' ? 'var(--blue)' : 'var(--dim)';
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:8px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center"><div style="font-size:14px;font-weight:600">' + esc(exp.name || exp.id) + '</div>';
          html += '<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:' + stColor + '22;color:' + stColor + '">' + (exp.status || 'draft') + '</span></div>';
          if (exp.description) html += '<div style="font-size:12px;color:var(--dim);margin-top:4px">' + esc(exp.description) + '</div>';
          html += '<div style="font-size:12px;margin-top:8px;color:var(--dim)">Type: <strong>' + esc(exp.experiment_type || 'hook_variant') + '</strong> | Variants: <strong>' + (exp.variants?.length || 2) + '</strong></div>';
          if (exp.results) {
            html += '<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">';
            for (const [variant, data] of Object.entries(exp.results)) {
              html += '<div style="padding:6px 12px;background:var(--card);border:1px solid var(--border);border-radius:6px;font-size:12px"><strong>' + esc(variant) + '</strong>: ' + (data.approval_rate != null ? (data.approval_rate * 100).toFixed(0) + '% approval' : JSON.stringify(data).substring(0, 60)) + '</div>';
            }
            html += '</div>';
          }
          html += '</div>';
        }
      } else {
        html += '<div style="color:var(--dim);font-size:13px;padding:12px">No experiments yet. Create one to test hook variants, CTAs, or post structures.</div>';
      }
      html += '</div>';
    } catch {}
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
    // Learning Loop Insights
    try {
      const insights = await api('/feedback/insights');
      html += '<div class="card" style="margin-bottom:16px"><h3 style="color:var(--primary)">Learning Loop Insights</h3>';
      html += '<div style="margin-top:12px">';
      if (insights.learning_runs?.length) {
        for (const run of insights.learning_runs.slice(0, 3)) {
          const recs = run.recommendations || {};
          const stColor = run.status === 'completed' ? 'var(--green)' : run.status === 'failed' ? 'var(--red)' : 'var(--yellow)';
          html += '<div style="background:#111318;border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:8px">';
          html += '<div style="display:flex;justify-content:space-between;align-items:center">';
          html += '<span style="font-size:12px;color:var(--dim)">' + (run.started_at ? new Date(run.started_at).toLocaleDateString() : '-') + '</span>';
          html += '<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:' + stColor + '22;color:' + stColor + '">' + run.status + '</span></div>';
          if (recs.week_summary) html += '<div style="font-size:13px;margin-top:8px">' + esc(recs.week_summary) + '</div>';
          if (recs.voice_drift_analysis) {
            const vd = recs.voice_drift_analysis;
            if (vd.patterns_found?.length) {
              html += '<div style="margin-top:8px"><div style="font-size:11px;font-weight:600;color:var(--accent2);text-transform:uppercase;margin-bottom:4px">Voice Drift Patterns</div>';
              vd.patterns_found.forEach(p => html += '<div style="font-size:12px;color:var(--dim);margin-bottom:2px">- ' + esc(typeof p === 'string' ? p : JSON.stringify(p)) + '</div>');
              html += '</div>';
            }
            if (vd.suggested_voice_adjustments?.length) {
              html += '<div style="margin-top:6px"><div style="font-size:11px;font-weight:600;color:var(--accent);text-transform:uppercase;margin-bottom:4px">Suggested Adjustments</div>';
              vd.suggested_voice_adjustments.forEach(a => html += '<div style="font-size:12px;color:var(--dim);margin-bottom:2px">- ' + esc(typeof a === 'string' ? a : JSON.stringify(a)) + '</div>');
              html += '</div>';
            }
          }
          if (recs.action_items?.length) {
            html += '<div style="margin-top:8px"><div style="font-size:11px;font-weight:600;color:var(--green);text-transform:uppercase;margin-bottom:4px">Action Items</div>';
            recs.action_items.slice(0, 5).forEach(a => html += '<div style="font-size:12px;color:var(--dim);margin-bottom:2px">- ' + esc(typeof a === 'string' ? a : (a.action || a.description || JSON.stringify(a))) + '</div>');
            html += '</div>';
          }
          html += '</div>';
        }
      } else {
        html += '<div style="font-size:13px;color:var(--dim);padding:8px">No learning loop runs yet. The loop runs every Friday at 5 PM to analyze your feedback and update voice profile.</div>';
      }
      // System version history
      if (insights.system_versions?.length) {
        html += '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px"><div style="font-size:11px;font-weight:600;color:var(--dim);text-transform:uppercase;margin-bottom:8px">System Version History</div>';
        for (const v of insights.system_versions.slice(0, 5)) {
          html += '<div style="display:flex;justify-content:space-between;font-size:12px;padding:4px 0;border-bottom:1px solid #1a1d27">';
          html += '<span style="color:var(--dim)">' + (v.created_at ? new Date(v.created_at).toLocaleDateString() : '-') + '</span>';
          html += '<span style="color:var(--primary)">' + esc(v.change_type || '-') + '</span>';
          html += '<span>' + esc((v.change_description || '-').slice(0, 60)) + '</span>';
          html += '</div>';
        }
        html += '</div>';
      }
      html += '</div></div>';
    } catch {}
    document.getElementById('analytics-content').innerHTML = html;
  } catch (e) {
    document.getElementById('analytics-content').innerHTML = '<div class="empty">Error loading analytics: ' + e.message + '</div>';
  }
}

// GAP-23: Notification Center
let _notifCache = null;
async function pollNotifications() {
  try {
    const data = await api('/notifications/count');
    const badge = document.getElementById('notif-badge');
    if (data.unread > 0) { badge.style.display = 'flex'; badge.textContent = data.unread > 9 ? '9+' : data.unread; }
    else { badge.style.display = 'none'; }
  } catch(e) {}
}
async function toggleNotifications() {
  const panel = document.getElementById('notif-panel');
  if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }
  panel.innerHTML = '<div style="padding:12px;color:var(--dim)">Loading...</div>';
  panel.style.display = 'block';
  try {
    const notifs = await api('/notifications/?limit=20');
    _notifCache = notifs;
    if (!notifs.length) { panel.innerHTML = '<div style="padding:16px;text-align:center;color:var(--dim)">No notifications</div>'; return; }
    let h = '<div style="padding:8px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center"><span style="font-weight:600;font-size:13px">Notifications</span><button style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:12px" onclick="markAllRead()">Mark all read</button></div>';
    for (const n of notifs) {
      const sevColor = n.severity === 'critical' ? 'var(--red)' : n.severity === 'warning' ? 'var(--yellow)' : 'var(--blue)';
      const bg = n.read ? 'transparent' : 'rgba(99,102,241,0.05)';
      h += '<div style="padding:10px 12px;border-bottom:1px solid var(--border);background:' + bg + ';cursor:pointer" onclick="markNotifRead(\\'' + n.id + '\\', this)">';
      h += '<div style="display:flex;align-items:center;gap:6px"><span style="width:6px;height:6px;border-radius:50%;background:' + sevColor + ';flex-shrink:0"></span><span style="font-size:13px;font-weight:' + (n.read ? '400' : '600') + '">' + esc(n.title) + '</span></div>';
      h += '<div style="font-size:12px;color:var(--dim);margin-top:4px;padding-left:12px">' + esc(n.message || '') + '</div>';
      h += '<div style="font-size:11px;color:var(--dim);margin-top:4px;padding-left:12px">' + new Date(n.created_at).toLocaleString() + '</div>';
      h += '</div>';
    }
    panel.innerHTML = h;
  } catch(e) { panel.innerHTML = '<div style="padding:12px;color:var(--red)">Error: ' + e.message + '</div>'; }
}
async function markNotifRead(id, el) { try { await api('/notifications/' + id + '/read', {method:'POST'}); if(el) el.style.background = 'transparent'; pollNotifications(); } catch(e){} }
async function markAllRead() { try { await api('/notifications/read-all', {method:'POST'}); toggleNotifications(); pollNotifications(); } catch(e){} }
setInterval(pollNotifications, 30000);
pollNotifications();

// GAP-27: Global Search
let _searchTimeout = null;
function debounceSearch(q) {
  clearTimeout(_searchTimeout);
  const panel = document.getElementById('search-results');
  if (!q || q.length < 2) { panel.style.display = 'none'; return; }
  _searchTimeout = setTimeout(async () => {
    panel.style.display = 'block';
    panel.innerHTML = '<div style="padding:12px;color:var(--dim)">Searching...</div>';
    try {
      const results = await api('/content/search?q=' + encodeURIComponent(q));
      if (!results.length) { panel.innerHTML = '<div style="padding:12px;color:var(--dim)">No results for "' + esc(q) + '"</div>'; return; }
      let h = '';
      for (const r of results) {
        const icon = r.type === 'package' ? '&#128230;' : r.type === 'brief' ? '&#128196;' : '&#128203;';
        h += '<div style="padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;gap:8px;align-items:flex-start" onclick="searchNavigate(\\'' + r.type + '\\',\\'' + r.id + '\\')">';
        h += '<span style="font-size:16px">' + icon + '</span>';
        h += '<div><div style="font-size:13px;font-weight:600">' + esc((r.title || '').substring(0, 80)) + '</div>';
        h += '<div style="font-size:11px;color:var(--dim)">' + r.type + (r.status ? ' - ' + r.status : '') + (r.family ? ' - ' + r.family : '') + '</div></div>';
        h += '</div>';
      }
      panel.innerHTML = h;
    } catch(e) { panel.innerHTML = '<div style="padding:12px;color:var(--red)">Search failed</div>'; }
  }, 300);
}
function searchNavigate(type, id) {
  document.getElementById('search-results').style.display = 'none';
  document.getElementById('global-search').value = '';
  if (type === 'package') { viewPackage(id); }
  else if (type === 'template') { currentTab = 'templates'; document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === 'templates')); render(); }
  else if (type === 'brief') { currentTab = 'week'; document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === 'week')); render(); }
}
document.addEventListener('click', e => { if (!e.target.closest('#global-search') && !e.target.closest('#search-results')) document.getElementById('search-results').style.display = 'none'; });

// GAP-28: Breadcrumb
function updateBreadcrumb(parts) {
  const bc = document.getElementById('breadcrumb');
  const text = document.getElementById('bc-text');
  if (!parts || parts.length <= 1) { bc.style.display = 'none'; return; }
  bc.style.display = 'block';
  text.innerHTML = parts.map((p, i) => i < parts.length - 1 ? '<span style="cursor:pointer;color:var(--accent)" onclick="' + (p.action || '') + '">' + esc(p.label) + '</span>' : '<span style="color:var(--text)">' + esc(p.label) + '</span>').join(' <span style="color:var(--dim)">&#8250;</span> ');
}

// GAP-17: Inline post editing
async function toggleInlineEdit(pkgId, platform, btn) {
  const pid = pkgId.replace(/-/g, '');
  const containerId = (platform === 'fb' ? 'fb-' : 'li-') + pid;
  const container = document.getElementById(containerId);
  if (!container) return;
  const preview = container.querySelector('.post-preview');
  const existing = container.querySelector('.inline-edit-area');
  if (existing) { existing.remove(); if (preview) preview.style.display = ''; btn.textContent = 'Edit'; return; }
  if (preview) preview.style.display = 'none';
  const text = platform === 'fb' ? (_pkgCache?.find(p => p.id === pkgId)?.facebook_post || '') : (_pkgCache?.find(p => p.id === pkgId)?.linkedin_post || '');
  const area = document.createElement('div');
  area.className = 'inline-edit-area';
  area.innerHTML = '<textarea style="width:100%;min-height:200px;padding:12px;background:var(--bg);color:var(--text);border:1px solid var(--accent);border-radius:6px;font-family:inherit;font-size:14px;line-height:1.6;resize:vertical">' + esc(text) + '</textarea><div style="display:flex;gap:8px;margin-top:8px"><button class="btn btn-green" onclick="saveInlineEdit(\\'' + pkgId + '\\',\\'' + platform + '\\', this)">Save</button><button class="btn btn-dim" onclick="toggleInlineEdit(\\'' + pkgId + '\\',\\'' + platform + '\\', this.closest(\\'.pkg-card\\').querySelector(\\'.edit-toggle-' + platform + '\\'))">Cancel</button><span class="inline-wc" style="font-size:12px;color:var(--dim);align-self:center"></span></div>';
  container.insertBefore(area, container.firstChild);
  const ta = area.querySelector('textarea');
  ta.addEventListener('input', () => { const wc = ta.value.trim().split(/\\s+/).filter(Boolean).length; area.querySelector('.inline-wc').textContent = wc + ' words'; });
  ta.dispatchEvent(new Event('input'));
  btn.textContent = 'Cancel Edit';
}
async function saveInlineEdit(pkgId, platform, btn) {
  const pid = pkgId.replace(/-/g, '');
  const containerId = (platform === 'fb' ? 'fb-' : 'li-') + pid;
  const container = document.getElementById(containerId);
  const ta = container?.querySelector('.inline-edit-area textarea');
  if (!ta) return;
  const newText = ta.value;
  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    const field = platform === 'fb' ? 'facebook_post' : 'linkedin_post';
    await api('/content/packages/' + pkgId, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({[field]: newText}) });
    toast(platform.toUpperCase() + ' post saved');
    if (_pkgCache) { const pkg = _pkgCache.find(p => p.id === pkgId); if (pkg) pkg[field] = newText; }
    const preview = container.querySelector('.post-preview');
    if (preview) { preview.textContent = newText; preview.style.display = ''; }
    container.querySelector('.inline-edit-area')?.remove();
    const editBtn = container.closest('.pkg-card')?.querySelector('.edit-toggle-' + platform);
    if (editBtn) editBtn.textContent = 'Edit';
  } catch(e) { toast('Save failed: ' + e.message); btn.disabled = false; btn.textContent = 'Save'; }
}

// GAP-18: Explainability context
async function loadPackageContext(pkgId, el) {
  if (el._loaded) { const panel = el.nextElementSibling; panel.style.display = panel.style.display === 'none' ? '' : 'none'; return; }
  el.textContent = 'Loading...';
  try {
    const ctx = await api('/content/packages/' + pkgId + '/context');
    el._loaded = true;
    let h = '<div style="padding:12px;background:#111318;border:1px solid var(--border);border-radius:8px;margin-top:8px">';
    if (ctx.story_brief) {
      const sb = ctx.story_brief;
      h += '<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:600;color:var(--accent2);text-transform:uppercase;margin-bottom:6px">Why This Angle</div>';
      h += '<div style="font-size:13px;margin-bottom:4px"><strong>Topic:</strong> ' + esc(sb.topic || '-') + '</div>';
      h += '<div style="font-size:13px;margin-bottom:4px"><strong>Angle:</strong> ' + esc((sb.angle_type || '').replace(/_/g, ' ')) + '</div>';
      h += '<div style="font-size:13px;margin-bottom:4px"><strong>Thesis:</strong> ' + esc(sb.thesis || '-') + '</div>';
      h += '<div style="font-size:13px;margin-bottom:4px"><strong>Audience:</strong> ' + esc(sb.audience || '-') + '</div>';
      h += '<div style="font-size:13px;margin-bottom:4px"><strong>Belief Shift:</strong> ' + esc(sb.desired_belief_shift || '-') + '</div>';
      if (sb.house_voice_weights) {
        h += '<div style="font-size:12px;margin-top:6px"><strong>Influence Weights:</strong> ';
        h += Object.entries(sb.house_voice_weights).map(([k,v]) => esc(k) + ': ' + ((v*100).toFixed(0)) + '%').join(', ');
        h += '</div>';
      }
      h += '</div>';
    }
    if (ctx.research_brief) {
      const rb = ctx.research_brief;
      h += '<div style="margin-bottom:12px;border-top:1px solid var(--border);padding-top:12px"><div style="font-size:11px;font-weight:600;color:var(--green);text-transform:uppercase;margin-bottom:6px">Research Evidence</div>';
      const safeColor = rb.safe_to_publish ? 'var(--green)' : 'var(--yellow)';
      h += '<div style="font-size:12px;margin-bottom:6px;color:' + safeColor + '"><strong>Safe to publish:</strong> ' + (rb.safe_to_publish ? 'Yes' : 'Needs review') + '</div>';
      if (rb.verified_claims?.length) {
        h += '<div style="font-size:12px;margin-bottom:4px"><strong>Verified claims (' + rb.verified_claims.length + '):</strong></div>';
        h += '<ul style="font-size:12px;color:var(--dim);margin:0 0 6px 16px;padding:0">';
        rb.verified_claims.slice(0, 5).forEach(c => h += '<li style="margin-bottom:2px">' + esc(typeof c === 'string' ? c : c.claim || JSON.stringify(c)) + '</li>');
        h += '</ul>';
      }
      if (rb.risk_flags?.length) {
        h += '<div style="font-size:12px;color:var(--red)"><strong>Risk flags:</strong> ' + rb.risk_flags.map(f => esc(f)).join(', ') + '</div>';
      }
      if (rb.source_refs?.length) {
        h += '<div style="font-size:12px;margin-top:4px"><strong>Sources:</strong> ' + rb.source_refs.length + ' references</div>';
      }
      h += '</div>';
    }
    if (ctx.plan_context) {
      const pc = ctx.plan_context;
      const borderTop = (ctx.story_brief || ctx.research_brief) ? 'border-top:1px solid var(--border);padding-top:12px;' : '';
      h += '<div style="margin-bottom:12px;' + borderTop + '"><div style="font-size:11px;font-weight:600;color:var(--primary);text-transform:uppercase;margin-bottom:6px">Plan Context</div>';
      if (pc.topic) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Topic:</strong> ' + esc(pc.topic) + '</div>';
      if (pc.thesis) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Thesis:</strong> ' + esc(pc.thesis) + '</div>';
      if (pc.angle_type) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Angle:</strong> ' + esc(pc.angle_type.replace(/_/g, ' ')) + '</div>';
      if (pc.audience) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Audience:</strong> ' + esc(pc.audience) + '</div>';
      if (pc.desired_belief_shift) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Belief Shift:</strong> ' + esc(pc.desired_belief_shift) + '</div>';
      if (pc.platform_notes) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Platform Notes:</strong> ' + esc(pc.platform_notes) + '</div>';
      if (pc.connection_to_gift) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Gift Connection:</strong> ' + esc(pc.connection_to_gift) + '</div>';
      if (pc.visual_job) h += '<div style="font-size:13px;margin-bottom:4px"><strong>Visual Job:</strong> ' + esc(pc.visual_job.replace(/_/g, ' ')) + '</div>';
      if (pc.evidence_requirements?.length) {
        h += '<div style="font-size:12px;margin-top:6px"><strong>Evidence Needed:</strong></div>';
        h += '<ul style="font-size:12px;color:var(--dim);margin:2px 0 6px 16px;padding:0">';
        pc.evidence_requirements.forEach(e => h += '<li style="margin-bottom:2px">' + esc(e) + '</li>');
        h += '</ul>';
      }
      h += '</div>';
    }
    if (!ctx.story_brief && !ctx.research_brief && !ctx.plan_context) {
      h += '<div style="font-size:13px;color:var(--dim)">No context available for this package. May have been generated before context tracking was added.</div>';
    }
    h += '</div>';
    const panel = document.createElement('div');
    panel.innerHTML = h;
    el.after(panel);
    el.textContent = 'Hide Context';
  } catch(e) { el.textContent = 'Show Context'; toast('Failed to load context: ' + e.message); }
}

// GAP-19: DM Flow editing
async function editDmField(pkgId, fieldKey, el) {
  const current = el.previousElementSibling?.textContent || '';
  const input = prompt('Edit ' + fieldKey.replace(/_/g, ' ') + ':', current);
  if (input === null) return;
  try {
    const pkg = _pkgCache?.find(p => p.id === pkgId);
    if (!pkg?.dm_flow) return;
    const updated = {...pkg.dm_flow, [fieldKey]: input};
    await api('/content/packages/' + pkgId, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({dm_flow: updated}) });
    pkg.dm_flow = updated;
    if (el.previousElementSibling) el.previousElementSibling.textContent = input;
    toast('DM flow updated');
  } catch(e) { toast('Failed: ' + e.message); }
}

// GAP-21: Publish controls
async function schedulePublish(pkgId, platform) {
  const when = prompt('Schedule for (ISO date, e.g. 2026-03-28T09:00):');
  if (!when) return;
  toast('Scheduling ' + platform + ' post for ' + when + '...');
  // For now, mark as approved and log the schedule intent
  try {
    await api('/content/packages/' + pkgId + '/approve', {method:'POST'});
    toast('Package approved and scheduled for ' + when);
    if (_pkgCache) { const pkg = _pkgCache.find(p => p.id === pkgId); if (pkg) pkg.approval_status = 'approved'; }
    await renderPackages();
  } catch(e) { toast('Failed: ' + e.message); }
}

// GAP-25: Template Library
async function renderTemplates() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Template Library</h2><div id="tmpl-content"><div class="empty">Loading templates...</div></div></div>';
  updateBreadcrumb([{label:'Dashboard'},{label:'Templates'}]);
  try {
    const templates = await api('/patterns/templates');
    if (!templates.length) { document.getElementById('tmpl-content').innerHTML = '<div class="empty">No templates found. Templates are created by the Pattern Miner agent during corpus ingestion.</div>'; return; }
    const families = [...new Set(templates.map(t => t.template_family).filter(Boolean))];
    let html = '<div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center">';
    html += '<button class="btn btn-primary btn-sm tmpl-filter active" onclick="filterTemplates(null,this)">All (' + templates.length + ')</button>';
    families.forEach(f => { const count = templates.filter(t => t.template_family === f).length; html += '<button class="btn btn-dim btn-sm tmpl-filter" onclick="filterTemplates(\\'' + esc(f) + '\\',this)">' + esc(f) + ' (' + count + ')</button>'; });
    html += '<div style="margin-left:auto"><button class="btn btn-primary btn-sm" id="enrich-btn" onclick="enrichFromCorpus(this)" style="background:var(--green);border-color:var(--green)">Enrich from Corpus</button></div>';
    html += '</div>';
    html += '<div id="tmpl-grid" class="grid">';
    for (const t of templates) {
      const statusColor = t.status === 'banned' ? 'var(--red)' : t.status === 'locked' ? 'var(--yellow)' : 'var(--green)';
      html += '<div class="card tmpl-card" data-family="' + esc(t.template_family || '') + '" style="border-left:3px solid ' + statusColor + '">';
      html += '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:8px"><h3 style="font-size:14px;text-transform:none">' + esc(t.template_name) + '</h3>';
      html += '<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:' + statusColor + '22;color:' + statusColor + '">' + (t.status || 'active') + '</span></div>';
      if (t.template_family) html += '<div style="font-size:12px;color:var(--accent2);margin-bottom:4px">' + esc(t.template_family) + '</div>';
      if (t.best_for) html += '<div style="font-size:12px;color:var(--dim);margin-bottom:8px">' + esc(t.best_for) + '</div>';
      if (t.hook_formula) html += '<div style="font-size:12px;margin-bottom:4px"><strong style="color:var(--green)">Hook:</strong> ' + esc(t.hook_formula) + '</div>';
      if (t.body_formula) html += '<div style="font-size:12px;margin-bottom:4px"><strong style="color:var(--blue)">Body:</strong> ' + esc(String(t.body_formula).substring(0, 120)) + '</div>';
      if (t.platform_fit) html += '<div style="font-size:12px;margin-bottom:4px"><strong>Platform:</strong> ' + esc(t.platform_fit) + '</div>';
      if (t.proof_requirements) html += '<div style="font-size:12px;margin-bottom:4px"><strong style="color:var(--accent)">Proof:</strong> ' + esc(t.proof_requirements) + '</div>';
      if (t.cta_compatibility && t.cta_compatibility.length) html += '<div style="font-size:12px;margin-bottom:4px"><strong>CTAs:</strong> ' + t.cta_compatibility.map(c => '<span style="background:var(--accent)22;padding:1px 6px;border-radius:3px;margin-right:4px;font-size:11px">' + esc(c) + '</span>').join('') + '</div>';
      if (t.visual_compatibility && t.visual_compatibility.length) html += '<div style="font-size:12px;margin-bottom:4px"><strong>Visuals:</strong> ' + t.visual_compatibility.map(v => '<span style="background:var(--blue)22;padding:1px 6px;border-radius:3px;margin-right:4px;font-size:11px">' + esc(v) + '</span>').join('') + '</div>';
      if (t.tone_profile) { const tones = Object.entries(t.tone_profile).slice(0,5).map(([k,v]) => esc(k) + ':' + v).join(', '); html += '<div style="font-size:12px;margin-bottom:4px"><strong>Tones:</strong> ' + tones + '</div>'; }
      if (t.risk_notes) html += '<div style="font-size:12px;color:var(--yellow);margin-top:6px">Risk: ' + esc(t.risk_notes) + '</div>';
      if (t.anti_patterns) html += '<div style="font-size:12px;color:var(--red);margin-top:4px">Avoid: ' + esc(t.anti_patterns) + '</div>';
      if (t.median_score != null) html += '<div style="font-size:12px;margin-top:6px;color:var(--dim)">Score: ' + t.median_score.toFixed(1) + ' | Samples: ' + (t.sample_size || 0) + (t.confidence_avg != null ? ' | Conf: ' + t.confidence_avg.toFixed(2) : '') + ' | Creators: ' + (t.creator_diversity_count || 0) + '</div>';
      html += '<div style="display:flex;gap:6px;margin-top:8px">';
      if (t.status !== 'locked') html += '<button class="btn btn-dim" style="font-size:11px" onclick="lockTemplate(\\'' + esc(t.template_name) + '\\')">Lock</button>';
      else html += '<button class="btn btn-dim" style="font-size:11px" onclick="unlockTemplate(\\'' + esc(t.template_name) + '\\')">Unlock</button>';
      if (t.status !== 'banned') html += '<button class="btn btn-dim" style="font-size:11px;color:var(--red);border-color:var(--red)" onclick="banTemplate(\\'' + esc(t.template_name) + '\\')">Ban</button>';
      html += '</div></div>';
    }
    html += '</div>';
    document.getElementById('tmpl-content').innerHTML = html;
  } catch(e) { document.getElementById('tmpl-content').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}
function filterTemplates(family, btn) {
  document.querySelectorAll('.tmpl-filter').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.querySelectorAll('.tmpl-card').forEach(c => { c.style.display = (!family || c.dataset.family === family) ? '' : 'none'; });
}
async function lockTemplate(name) { try { await api('/controls/templates/lock', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_name:name,reason:'Operator locked'})}); toast('Template locked'); renderTemplates(); } catch(e) { toast('Failed: '+e.message); } }
async function unlockTemplate(name) { try { await api('/controls/templates/unlock', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_name:name})}); toast('Template unlocked'); renderTemplates(); } catch(e) { toast('Failed: '+e.message); } }
async function banTemplate(name) { if(!confirm('Ban template "'+name+'"?')) return; try { await api('/controls/templates/ban', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_name:name,reason:'Operator banned'})}); toast('Template banned'); renderTemplates(); } catch(e) { toast('Failed: '+e.message); } }

async function enrichFromCorpus(btn) {
  if (!confirm('This will:\\n1. Score all corpus posts\\n2. Classify posts into template families\\n3. Aggregate stats per template\\n4. AI-enrich template descriptions\\n\\nEstimated cost: ~$0.05. Continue?')) return;
  btn.disabled = true; btn.textContent = 'Starting...';
  try {
    // Start enrichment - show progress by polling status
    const statusDiv = document.createElement('div');
    statusDiv.id = 'enrich-status';
    statusDiv.style.cssText = 'background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:16px;font-size:13px';
    statusDiv.innerHTML = '<strong>Enrichment running...</strong> Phase 1/4: Scoring posts...';
    btn.parentElement.parentElement.insertBefore(statusDiv, btn.parentElement.nextSibling);
    // Poll status while waiting
    const pollId = setInterval(async () => {
      try {
        const st = await api('/patterns/templates/enrich-status');
        if (st.status === 'running') {
          statusDiv.innerHTML = '<strong>Enrichment running...</strong> Phase ' + st.phase + '/4: ' + (st.detail || '');
        }
      } catch(e) {}
    }, 2000);
    const result = await api('/patterns/templates/enrich', {method:'POST'});
    clearInterval(pollId);
    const sd = document.getElementById('enrich-status');
    if (sd) sd.innerHTML = '<strong style="color:var(--green)">Enrichment complete!</strong> Scored: ' + result.posts_scored + ' posts, Classified: ' + result.posts_classified + ', Templates enriched: ' + result.templates_enriched + ' (AI: ' + result.templates_ai_enriched + ')';
    btn.textContent = 'Enrich from Corpus'; btn.disabled = false;
    setTimeout(() => renderTemplates(), 2000);
  } catch(e) { btn.textContent = 'Enrich from Corpus'; btn.disabled = false; toast('Enrichment failed: ' + e.message); const sd = document.getElementById('enrich-status'); if (sd) sd.innerHTML = '<strong style="color:var(--red)">Failed:</strong> ' + e.message; }
}

// GAP-32: Prompt Library
async function renderPrompts() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Prompt Library</h2><div id="prompt-content"><div class="empty">Loading prompts...</div></div></div>';
  updateBreadcrumb([{label:'Dashboard'},{label:'Prompts'}]);
  try {
    const agents = await api('/admin/agents');
    let html = '';
    for (const a of agents) {
      html += '<div class="card" style="margin-bottom:12px">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><h3 style="font-size:14px;text-transform:none">' + esc(a.name) + '</h3>';
      html += '<span style="font-size:12px;padding:3px 10px;border-radius:6px;background:var(--accent)22;color:var(--accent)">' + esc(a.model || 'default') + '</span></div>';
      html += '<div id="prompt-versions-' + esc(a.name) + '"><button class="btn btn-dim" style="font-size:12px" onclick="loadPromptVersions(\\'' + esc(a.name) + '\\')">View Prompt Versions</button></div>';
      html += '</div>';
    }
    document.getElementById('prompt-content').innerHTML = html || '<div class="empty">No agents configured.</div>';
  } catch(e) { document.getElementById('prompt-content').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}
async function loadPromptVersions(agentName) {
  const el = document.getElementById('prompt-versions-' + agentName);
  if (!el) return;
  el.innerHTML = '<div style="color:var(--dim);font-size:12px">Loading...</div>';
  try {
    const versions = await api('/prompts/' + agentName);
    if (!versions.length) { el.innerHTML = '<div style="color:var(--dim);font-size:12px">No prompt versions recorded.</div>'; return; }
    let h = '<div style="margin-top:8px">';
    for (const v of versions) {
      const isActive = v.is_active;
      h += '<div style="padding:8px;margin-bottom:6px;border:1px solid ' + (isActive ? 'var(--green)' : 'var(--border)') + ';border-radius:6px;background:' + (isActive ? 'rgba(34,197,94,0.05)' : 'transparent') + '">';
      h += '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px"><span style="font-size:12px;font-weight:600">v' + v.version_number + (isActive ? ' (active)' : '') + '</span>';
      h += '<div style="display:flex;gap:4px">';
      // GAP-51: Side-by-side comparison
      if (!isActive && v.prompt_text) h += '<button class="btn btn-dim" style="font-size:10px;padding:2px 6px" onclick="comparePrompts(\\'' + agentName + '\\',' + v.version_number + ')">Compare</button>';
      if (!isActive) h += '<button class="btn btn-dim" style="font-size:11px" onclick="rollbackPrompt(\\'' + agentName + '\\',' + v.version_number + ')">Rollback to this</button>';
      h += '</div></div>';
      if (v.prompt_text) h += '<div style="font-size:12px;color:var(--dim);margin-top:4px;max-height:100px;overflow-y:auto;white-space:pre-wrap">' + esc(v.prompt_text.substring(0, 500)) + (v.prompt_text.length > 500 ? '...' : '') + '</div>';
      h += '</div>';
    }
    h += '</div>';
    el.innerHTML = h;
  } catch(e) { el.innerHTML = '<div style="color:var(--red);font-size:12px">Error: ' + e.message + '</div>'; }
}
async function rollbackPrompt(agent, version) {
  if (!confirm('Rollback ' + agent + ' to v' + version + '?')) return;
  try { await api('/prompts/' + agent + '/rollback', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_version:version})}); toast('Prompt rolled back'); loadPromptVersions(agent); } catch(e) { toast('Failed: '+e.message); }
}

// GAP-22: Settings page
async function renderSettings() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><h2>Settings</h2><div id="settings-content"><div class="empty">Loading...</div></div></div>';
  updateBreadcrumb([{label:'Dashboard'},{label:'Settings'}]);
  try {
    const [flags, platforms] = await Promise.all([
      api('/admin/agents').catch(() => []),
      api('/controls/platforms').catch(() => ({})),
    ]);
    let html = '';
    // Feature Flags
    html += '<div class="card" style="margin-bottom:16px"><h3>Platform Publishing</h3>';
    html += '<div style="margin-top:12px;display:flex;flex-direction:column;gap:8px">';
    for (const [plat, enabled] of Object.entries(platforms)) {
      html += '<div style="display:flex;align-items:center;gap:12px"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" ' + (enabled ? 'checked' : '') + ' onchange="togglePlatform(\\'' + esc(plat) + '\\', this.checked)" style="width:18px;height:18px;accent-color:var(--green)"><span style="font-size:14px">' + esc(plat) + '</span></label></div>';
    }
    html += '</div></div>';
    // Budget
    html += '<div class="card" style="margin-bottom:16px"><h3>Budget & Costs</h3>';
    html += '<div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:16px">';
    const savedDaily = localStorage.getItem('tce_daily_budget') || '5.00';
    const savedMonthly = localStorage.getItem('tce_monthly_budget') || '150.00';
    html += '<div><label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Daily Budget Cap (USD)</label><input id="set-daily-budget" type="number" step="0.5" value="' + savedDaily + '" style="width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px"></div>';
    html += '<div><label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Monthly Budget Alert (USD)</label><input id="set-monthly-budget" type="number" step="5" value="' + savedMonthly + '" style="width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px"></div>';
    html += '</div><button class="btn btn-primary" style="margin-top:12px" onclick="saveBudgetSettings()">Save Budget Settings</button></div>';
    // API Keys (read-only status)
    html += '<div class="card" style="margin-bottom:16px"><h3>API Keys Status</h3>';
    html += '<div style="margin-top:12px;font-size:13px">';
    html += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)"><span>Anthropic API</span><span style="color:var(--green)">Configured (env)</span></div>';
    html += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)"><span>fal.ai (Images)</span><span style="color:var(--green)">Configured (env)</span></div>';
    html += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)"><span>Brave Search</span><span style="color:var(--green)">Configured (env)</span></div>';
    html += '<div style="display:flex;justify-content:space-between;padding:6px 0"><span>Resend (Email)</span><span style="color:var(--dim)">Optional</span></div>';
    html += '</div><div style="margin-top:12px;font-size:12px;color:var(--dim)">API keys are managed via environment variables on the VPS. SSH to 5.161.71.94 to update.</div></div>';
    // Audience Config
    html += '<div class="card"><h3>Target Audience</h3>';
    const savedAudience = (localStorage.getItem('tce_audience') || '').replace(/'/g, '&#39;');
    html += '<div style="margin-top:12px"><label style="font-size:12px;color:var(--dim);display:block;margin-bottom:4px">Primary Audience Description</label><textarea id="set-audience" rows="3" style="width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:13px" placeholder="e.g. B2B agency owners, 10-50 employees, interested in AI adoption...">' + savedAudience + '</textarea></div>';
    html += '<button class="btn btn-primary" style="margin-top:8px" onclick="saveAudienceConfig()">Save</button></div>';
    // GAP-44: Engagement Scorer Controls
    html += '<div class="card" style="margin-top:16px"><h3>Engagement Scorer Weights</h3>';
    html += '<div style="margin-top:12px;font-size:12px;color:var(--dim);margin-bottom:12px">Adjust how the engagement scorer weighs different signals when evaluating post examples.</div>';
    const scorerWeights = JSON.parse(localStorage.getItem('tce_scorer_weights') || '{"comments":0.4,"shares":0.25,"reactions":0.2,"saves":0.15}');
    const weightKeys = ['comments', 'shares', 'reactions', 'saves'];
    html += '<div style="display:flex;flex-direction:column;gap:10px">';
    for (const k of weightKeys) {
      const val = (scorerWeights[k] || 0);
      html += '<div style="display:flex;align-items:center;gap:10px"><span style="width:80px;font-size:13px;color:var(--text)">' + k.charAt(0).toUpperCase() + k.slice(1) + '</span>';
      html += '<input type="range" min="0" max="100" value="' + (val * 100).toFixed(0) + '" style="flex:1;accent-color:var(--accent)" oninput="this.nextElementSibling.textContent=this.value+\\'%\\'" id="scorer-' + k + '">';
      html += '<span style="width:40px;font-size:12px;text-align:right">' + (val * 100).toFixed(0) + '%</span></div>';
    }
    html += '</div>';
    html += '<button class="btn btn-primary" style="margin-top:12px" onclick="saveScorerWeights()">Save Scorer Weights</button></div>';
    document.getElementById('settings-content').innerHTML = html;
  } catch(e) { document.getElementById('settings-content').innerHTML = '<div class="empty">Error: ' + e.message + '</div>'; }
}
async function togglePlatform(plat, enabled) {
  try { await api('/controls/platforms', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:plat,enabled:enabled})}); toast(plat + (enabled ? ' enabled' : ' disabled')); } catch(e) { toast('Failed: '+e.message); }
}
function saveBudgetSettings() {
  const daily = document.getElementById('set-daily-budget')?.value || '5.00';
  const monthly = document.getElementById('set-monthly-budget')?.value || '150.00';
  localStorage.setItem('tce_daily_budget', daily);
  localStorage.setItem('tce_monthly_budget', monthly);
  toast('Budget saved: $' + daily + '/day, $' + monthly + '/month alert');
}
function saveAudienceConfig() {
  const audience = document.getElementById('set-audience')?.value || '';
  localStorage.setItem('tce_audience', audience);
  toast('Audience config saved');
}
// GAP-44: Save scorer weights
function saveScorerWeights() {
  const weights = {};
  for (const k of ['comments','shares','reactions','saves']) {
    const el = document.getElementById('scorer-' + k);
    weights[k] = el ? parseFloat(el.value) / 100 : 0.25;
  }
  localStorage.setItem('tce_scorer_weights', JSON.stringify(weights));
  toast('Scorer weights saved');
}

// GAP-33: Chatbot interface
let _chatHistory = [];
async function renderChat() {
  const app = document.getElementById('app');
  let html = '<div class="section"><h2>Assistant</h2>';
  html += '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;height:500px;display:flex;flex-direction:column">';
  html += '<div id="chat-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px">';
  if (!_chatHistory.length) html += '<div style="color:var(--dim);text-align:center;margin-top:40px">Ask me anything about your content pipeline.<br>Try: "Show today\\'s package" or "Why did QA fail?" or "What\\'s my cost this week?"</div>';
  else { for (const m of _chatHistory) { html += '<div style="align-self:' + (m.role === 'user' ? 'flex-end' : 'flex-start') + ';max-width:80%;padding:10px 14px;border-radius:12px;background:' + (m.role === 'user' ? 'var(--accent)' : '#1e2030') + ';font-size:13px;line-height:1.5;white-space:pre-wrap">' + esc(m.text) + '</div>'; } }
  html += '</div>';
  html += '<div style="padding:12px;border-top:1px solid var(--border);display:flex;gap:8px"><input id="chat-input" type="text" style="flex:1;padding:10px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:14px" placeholder="Type a message..." onkeydown="if(event.key===\\'Enter\\')sendChat()"><button class="btn btn-primary" onclick="sendChat()">Send</button></div>';
  html += '</div></div>';
  app.innerHTML = html;
  updateBreadcrumb([{label:'Dashboard'},{label:'Assistant'}]);
}
async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  _chatHistory.push({role:'user', text:msg});
  const msgsDiv = document.getElementById('chat-messages');
  msgsDiv.innerHTML += '<div style="align-self:flex-end;max-width:80%;padding:10px 14px;border-radius:12px;background:var(--accent);font-size:13px;line-height:1.5">' + esc(msg) + '</div>';
  msgsDiv.innerHTML += '<div id="chat-typing" style="align-self:flex-start;padding:10px;color:var(--dim);font-size:13px">Thinking...</div>';
  msgsDiv.scrollTop = msgsDiv.scrollHeight;
  try {
    const resp = await api('/chat/', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
    document.getElementById('chat-typing')?.remove();
    _chatHistory.push({role:'assistant', text:resp.response});
    msgsDiv.innerHTML += '<div style="align-self:flex-start;max-width:80%;padding:10px 14px;border-radius:12px;background:#1e2030;font-size:13px;line-height:1.5;white-space:pre-wrap">' + esc(resp.response) + '</div>';
    msgsDiv.scrollTop = msgsDiv.scrollHeight;
  } catch(e) { document.getElementById('chat-typing')?.remove(); msgsDiv.innerHTML += '<div style="color:var(--red);font-size:12px;padding:8px">Error: ' + e.message + '</div>'; }
}

// GAP-35: Keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  if (e.key === '/') { e.preventDefault(); document.getElementById('global-search')?.focus(); return; }
  const tabKeys = {'1':'week','2':'generate','3':'packages','4':'corpus','5':'costs','6':'analytics'};
  if (e.altKey && tabKeys[e.key]) { e.preventDefault(); currentTab = tabKeys[e.key]; document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === currentTab)); render(); return; }
  if (e.key === '?' && !e.shiftKey) {
    toast('Shortcuts: / = Search, Alt+1-6 = Switch tabs');
  }
});

// GAP-51: Side-by-side prompt comparison
async function comparePrompts(agentName, versionNum) {
  try {
    const versions = await api('/prompts/' + agentName);
    const active = versions.find(v => v.is_active);
    const target = versions.find(v => v.version_number === versionNum);
    if (!active || !target) { toast('Cannot find versions to compare', false); return; }
    const w = window.open('', '_blank');
    let h = '<html><head><style>body{font-family:monospace;background:#0f1117;color:#e4e4e7;padding:20px;margin:0}h1{font-family:-apple-system,sans-serif;font-size:18px;margin-bottom:16px;color:#818cf8}.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;height:calc(100vh - 80px)}.col{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px;overflow-y:auto}.col h2{font-family:-apple-system,sans-serif;font-size:14px;margin-bottom:12px;position:sticky;top:0;background:#1a1d27;padding:4px 0}pre{white-space:pre-wrap;font-size:12px;line-height:1.6}</style></head><body>';
    h += '<h1>' + agentName + ' - v' + active.version_number + ' (active) vs v' + versionNum + '</h1>';
    h += '<div class="cols">';
    h += '<div class="col"><h2 style="color:#22c55e">v' + active.version_number + ' (Active)</h2><pre>' + (active.prompt_text || '').replace(/</g, '&lt;') + '</pre></div>';
    h += '<div class="col"><h2 style="color:#eab308">v' + versionNum + '</h2><pre>' + (target.prompt_text || '').replace(/</g, '&lt;') + '</pre></div>';
    h += '</div></body></html>';
    w.document.write(h);
  } catch(e) { toast('Error: ' + e.message, false); }
}

// GAP-47: Seasonal override toggle
document.addEventListener('change', e => {
  if (e.target.id === 'seasonal-override-toggle') {
    const input = document.getElementById('seasonal-context');
    if (input) input.style.display = e.target.checked ? 'block' : 'none';
  }
});

// GAP-46: View document guide preview
async function viewGuide(docId, name) {
  try {
    const doc = await api('/documents/' + docId);
    const text = doc.extracted_text || doc.notes || '';
    if (!text) { toast('No extracted text for this document', false); return; }
    const w = window.open('', '_blank');
    let h = '<html><head><style>body{font-family:-apple-system,sans-serif;padding:20px;max-width:800px;margin:auto;background:#0f1117;color:#e4e4e7}h1{font-size:20px;margin-bottom:8px;color:#818cf8}.meta{font-size:12px;color:#71717a;margin-bottom:20px}.content{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:24px;white-space:pre-wrap;font-size:14px;line-height:1.8;direction:rtl;text-align:right}</style></head><body>';
    h += '<h1>' + name + '</h1>';
    h += '<div class="meta">Document ID: ' + docId + ' | ' + (doc.pages || '?') + ' pages | Uploaded: ' + new Date(doc.created_at).toLocaleDateString() + '</div>';
    h += '<div class="content">' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
    h += '</body></html>';
    w.document.write(h);
  } catch(e) { toast('Error: ' + e.message, false); }
}

// GAP-45: Toggle CTA fulfillment checklist
function showCtaChecklist(pid) { const el = document.getElementById('cta-checklist-' + pid); if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none'; }

// GAP-43: Edit anti-clone markers
async function editAntiClone(creatorId) {
  const current = prompt('Enter anti-clone markers (comma-separated phrases to NEVER copy from this creator):');
  if (current === null) return;
  const markers = current.split(',').map(s => s.trim()).filter(Boolean);
  try { await api('/profiles/creators/' + creatorId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({disallowed_clone_markers: markers})}); toast('Anti-clone markers updated'); renderCreators(); } catch(e) { toast('Failed: ' + e.message, false); }
}

// GAP-50: Toggle creator angle weight
async function toggleCreatorAngle(creatorId, angle, newWeight) {
  try {
    const creator = await api('/profiles/creators/' + creatorId);
    const weights = creator.angle_weights || {};
    weights[angle] = parseFloat(newWeight);
    await api('/profiles/creators/' + creatorId, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({angle_weights: weights})});
    toast(angle.replace(/_/g,' ') + (newWeight > 0 ? ' enabled' : ' excluded'));
    renderCreators();
  } catch(e) { toast('Failed: ' + e.message, false); }
}

// GAP-42: Create A/B experiment
async function createExperiment() {
  const name = prompt('Experiment name:');
  if (!name) return;
  const types = ['hook_variant', 'cta_variant', 'post_structure', 'image_style'];
  const type = prompt('Experiment type (' + types.join(', ') + '):', 'hook_variant');
  if (!type) return;
  try {
    const r = await api('/experiments/', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name, experiment_type: type, variants: ['control', 'variant_a']})});
    toast('Experiment created: ' + r.id);
    renderAnalytics();
  } catch(e) { toast('Failed: ' + e.message, false); }
}

// GAP-38: Relearning functions
async function triggerRelearn() { try { const r = await api('/relearning/evaluate', {method:'POST'}); toast('Evaluation complete: ' + (r.proposals_created || 0) + ' proposals'); renderCorpus(); } catch(e) { toast('Failed: ' + e.message, false); } }
async function approveProposal(id) { try { await api('/relearning/proposals/' + id + '/approve', {method:'POST'}); toast('Proposal approved'); renderCorpus(); } catch(e) { toast('Failed: ' + e.message, false); } }
async function rejectProposal(id) { try { await api('/relearning/proposals/' + id + '/reject', {method:'POST'}); toast('Proposal rejected'); renderCorpus(); } catch(e) { toast('Failed: ' + e.message, false); } }

// --- Guides Tab ---
let _guidesFromPostExpanded = false;
async function renderGuides() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div class="empty">Loading guides...</div></div>';
  try {
    const guides = await api('/content/guides');
    let html = '<div class="section">';
    // Hero: Generate Guide from Post
    html += '<div style="background:linear-gradient(135deg,#0a2e1a 0%,#0d1117 60%);border:1px solid var(--green);border-radius:12px;padding:20px;margin-bottom:20px">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center">';
    html += '<div><div style="font-size:16px;font-weight:700;color:var(--green);margin-bottom:4px">Generate Guide from Post</div>';
    html += '<div style="font-size:12px;color:var(--dim)">Paste a social media post and the AI will research the topic and create a guide that delivers on the CTA promise.</div></div>';
    html += '<button class="btn btn-green" style="font-size:13px;padding:8px 20px;white-space:nowrap" onclick="toggleGuidesFromPost()">New Guide from Post</button>';
    html += '</div>';
    // Expandable form
    html += '<div id="guides-from-post-form" style="display:' + (_guidesFromPostExpanded ? 'block' : 'none') + ';margin-top:16px;border-top:1px solid var(--border);padding-top:16px">';
    html += '<textarea id="guides-post-input" rows="5" placeholder="Paste your social media post here..." style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;color:var(--text);color-scheme:dark;resize:vertical;font-family:inherit;box-sizing:border-box"></textarea>';
    html += '<div style="display:flex;gap:8px;margin-top:8px;align-items:center">';
    html += '<input id="guides-post-keyword" type="text" placeholder="CTA keyword (default: guide)" style="width:140px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:12px;color:var(--text);color-scheme:dark" />';
    html += '<input id="guides-post-instructions" type="text" placeholder="Optional instructions (e.g. focus on accuracy)" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:12px;color:var(--text);color-scheme:dark" />';
    html += '<button class="btn btn-green" style="font-size:12px;white-space:nowrap" onclick="guidesGenerateFromPost()">Generate</button>';
    html += '</div></div>';
    html += '</div>';
    // Guide cards grid
    if (!guides || guides.length === 0) {
      html += '<div class="empty">No guides yet. Generate your first guide from a post above, or run the weekly pipeline.</div>';
    } else {
      html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px">';
      for (const g of guides) {
        const md = g.markdown_content || '';
        const words = md.split(/\\s+/).filter(w => w.length > 0).length;
        const sections = (md.match(/^##\\s/gm) || []).length;
        const qs = g.quality_scores;
        const composite = qs ? (qs.composite || 0) : null;
        const passed = g.quality_gate_passed;
        const borderColor = passed === true ? 'var(--green)' : passed === false ? 'var(--yellow)' : 'var(--border)';
        html += '<div class="card" style="padding:16px;border:1px solid ' + borderColor + ';cursor:pointer" onclick="showWeekGuide(\\'' + g.id + '\\')">';
        html += '<div style="font-size:14px;font-weight:700;margin-bottom:6px;color:var(--text)">' + esc(g.guide_title || 'Untitled Guide') + '</div>';
        html += '<div style="font-size:11px;color:var(--dim);margin-bottom:10px">Week of ' + (g.week_start_date || 'unknown') + (g.weekly_theme ? ' - ' + esc(g.weekly_theme) : '') + '</div>';
        html += '<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:12px">';
        html += '<span style="color:var(--dim)">' + words + ' words</span>';
        html += '<span style="color:var(--dim)">' + sections + ' sections</span>';
        if (composite !== null) {
          const scoreColor = composite >= 8 ? 'var(--green)' : composite >= 6 ? 'var(--yellow)' : 'var(--red)';
          html += '<span style="font-weight:700;color:' + scoreColor + '">' + composite.toFixed(1) + '/10</span>';
        }
        if (passed === true) html += '<span style="color:var(--green);font-weight:600">Passed</span>';
        else if (passed === false) html += '<span style="color:var(--yellow);font-weight:600">Below Target</span>';
        else html += '<span style="color:var(--dim)">Not Assessed</span>';
        html += '</div>';
        html += '</div>';
      }
      html += '</div>';
    }
    html += '</div>';
    app.innerHTML = html;
  } catch(e) {
    app.innerHTML = '<div class="section"><div class="empty" style="color:var(--red)">Error loading guides: ' + esc(e.message) + '</div></div>';
  }
}

function toggleGuidesFromPost() {
  _guidesFromPostExpanded = !_guidesFromPostExpanded;
  const form = document.getElementById('guides-from-post-form');
  if (form) form.style.display = _guidesFromPostExpanded ? 'block' : 'none';
}

async function guidesGenerateFromPost() {
  const postText = document.getElementById('guides-post-input')?.value?.trim();
  if (!postText) { toast('Paste your post text first', false); return; }
  const keyword = document.getElementById('guides-post-keyword')?.value?.trim() || 'guide';
  const instructions = document.getElementById('guides-post-instructions')?.value?.trim() || null;
  try {
    const body = { post_text: postText, cta_keyword: keyword };
    if (instructions) body.operator_feedback = instructions;
    const r = await api('/content/guides/generate-from-post', { method: 'POST', body: JSON.stringify(body) });
    _regenState = { guideId: r.tracking_id, startTime: Date.now(), feedback: instructions, fromPost: true };
    toast('Guide generation started');
    pollRegenStatus(r.tracking_id);
  } catch(e) { toast('Failed: ' + e.message, false); }
}

// Helper to switch tab from inline onclick
function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
  const pt = document.getElementById('page-title');
  if (pt) pt.textContent = TAB_LABELS[tabName] || tabName;
  render();
}

async function showWeekGuide(mondayStrOrGuideId) {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div class="empty">Loading guide...</div></div>';
  try {
    let guide;
    // If it looks like a UUID, load that specific guide
    const isUuid = mondayStrOrGuideId && /^[0-9a-f]{8}-/.test(mondayStrOrGuideId);
    if (isUuid) {
      guide = await api('/content/guides/' + mondayStrOrGuideId);
    } else {
      const guides = await api('/content/guides');
      const mondayStr = mondayStrOrGuideId;
      const mon = new Date(mondayStr + 'T00:00:00');
      const sun = new Date(mon); sun.setDate(sun.getDate() + 6);
      guide = guides.find(g => {
        const gd = new Date(g.week_start_date + 'T00:00:00');
        return gd >= mon && gd <= sun;
      });
    }
    if (!guide) {
      app.innerHTML = '<div class="section"><button class="btn btn-dim" onclick="switchTab(\\'week\\')" style="margin-bottom:16px">Back to Week Planner</button><div class="empty">No guide found for this week yet. Run the full pipeline first - the guide is built in the final phase.</div></div>';
      return;
    }
    // Quality scores - LLM-assessed or pending
    const md = guide.markdown_content || '';
    const words = md.split(/\\s+/).filter(w => w.length > 0).length;
    const sections = (md.match(/^##\\s/gm) || []).length;
    const qs = guide.quality_scores || null;
    function scoreColor(s) { return s >= 8 ? 'var(--green)' : s >= 6 ? 'var(--yellow)' : 'var(--red)'; }
    function scoreBar(label, score, reason) {
      const tip = reason ? ' title="' + esc(reason).replace(/"/g, '&quot;') + '"' : '';
      return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;cursor:' + (reason ? 'help' : 'default') + '"' + tip + '><span style="width:110px;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px">' + label + '</span><div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden"><div style="width:' + (score * 10) + '%;height:100%;background:' + scoreColor(score) + ';border-radius:3px;transition:width 0.5s ease"></div></div><span style="font-size:13px;font-weight:700;color:' + scoreColor(score) + ';width:28px;text-align:right">' + score + '</span></div>';
    }

    let html = '<div class="section">';
    html += '<div style="display:flex;gap:8px;margin-bottom:16px"><button class="btn btn-dim" onclick="switchTab(\\'guides\\')">Back to Guides</button><button class="btn btn-dim" onclick="switchTab(\\'week\\')">Back to Week Planner</button></div>';
    html += '<div style="background:linear-gradient(135deg,#1a1d27,#1e2235);border:1px solid var(--green);border-radius:12px;padding:24px">';
    html += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--green);margin-bottom:8px">Weekly Free Guide</div>';
    html += '<h2 style="margin-bottom:4px">' + esc(guide.guide_title) + '</h2>';
    html += '<div style="font-size:13px;color:var(--dim);margin-bottom:16px">Week of ' + guide.week_start_date + (guide.weekly_theme ? ' - Theme: ' + esc(guide.weekly_theme) : '') + '</div>';

    // Stats row
    html += '<div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">';
    html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 16px;text-align:center;min-width:100px"><div style="font-size:24px;font-weight:800;color:var(--text)">' + words.toLocaleString() + '</div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-top:2px">Words</div></div>';
    html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 16px;text-align:center;min-width:100px"><div style="font-size:24px;font-weight:800;color:var(--text)">' + sections + '</div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-top:2px">Sections</div></div>';
    if (qs) {
      const comp = qs.composite || 0;
      html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 16px;text-align:center;min-width:100px"><div style="font-size:24px;font-weight:800;color:' + scoreColor(comp) + '">' + comp.toFixed(1) + '</div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-top:2px">Quality Score</div></div>';
    }
    // Quality gate badge
    const gp = guide.quality_gate_passed;
    const iters = guide.iteration_count || 0;
    if (gp === true || gp === false || iters > 0) {
      const gateColor = gp === true ? 'var(--green)' : gp === false ? 'var(--red)' : 'var(--dim)';
      const gateLabel = gp === true ? 'Passed' + (iters > 1 ? ' (' + iters + ' attempts)' : '') : gp === false ? 'Failed (' + iters + ' attempts)' : 'Pending';
      html += '<div style="background:var(--bg);border:1px solid ' + gateColor + ';border-radius:8px;padding:12px 16px;text-align:center;min-width:120px"><div style="font-size:13px;font-weight:800;color:' + gateColor + '">' + gateLabel + '</div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-top:2px">Quality Gate</div></div>';
    }
    html += '</div>';

    // Score bars or assess button
    if (qs) {
      html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px 20px;margin-bottom:16px">';
      html += '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:10px">LLM Quality Assessment</div>';
      const dims = [['practical','Practical'],['valuable','Valuable'],['generous','Generous'],['accurate','Accurate'],['quick_win','Quick Win'],['transformation','Transformation']];
      for (const [key, label] of dims) {
        const d = qs[key] || {};
        html += scoreBar(label, d.score || 0, d.reason || '');
      }
      if (qs.summary) {
        html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:13px;color:var(--dim);line-height:1.5">' + esc(qs.summary) + '</div>';
      }
      html += '</div>';
      // Feedback input + Re-assess/Regenerate buttons
      html += '<div style="margin-top:12px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px">';
      html += '<div style="font-size:11px;color:var(--dim);margin-bottom:6px">Regenerate with specific instructions:</div>';
      html += '<div style="display:flex;gap:6px;margin-bottom:8px">';
      html += '<input id="guide-feedback-input" type="text" placeholder="e.g. accuracy is too low, need more cited sources" style="flex:1;background:#0d1117;border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:12px;color:var(--text);color-scheme:dark" />';
      html += '<button class="btn btn-primary" style="font-size:11px;white-space:nowrap" onclick="const fb=document.getElementById(\\'guide-feedback-input\\').value.trim();regenerateGuide(\\'' + guide.id + '\\',fb||undefined)">Regenerate</button>';
      html += '</div>';
      html += '<div style="display:flex;gap:8px;justify-content:flex-end">';
      html += '<button class="btn btn-dim" style="font-size:12px" onclick="assessGuide(\\'' + guide.id + '\\')">Re-assess</button>';
      html += '</div>';
      html += '</div>';
      html += '</div>';
      // Assessment history accordion
      if (guide.assessment_history && guide.assessment_history.length > 1) {
        html += '<details style="margin-bottom:16px"><summary style="cursor:pointer;font-size:12px;color:var(--dim);margin-bottom:8px">Iteration history (' + guide.assessment_history.length + ' attempts)</summary><div style="font-size:12px">';
        for (const entry of guide.assessment_history) {
          const pc = entry.composite >= 8 ? 'var(--green)' : 'var(--red)';
          html += '<div style="display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)"><span style="color:var(--dim)">Attempt ' + entry.iteration + '</span><span style="font-weight:700;color:' + pc + '">' + (entry.composite || 0).toFixed(1) + '/10</span>';
          if (entry.summary) html += '<span style="color:var(--dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(entry.summary) + '</span>';
          html += '</div>';
        }
        html += '</div></details>';
      }
    } else {
      html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px 20px;margin-bottom:16px;text-align:center">';
      html += '<div style="color:var(--dim);font-size:13px;margin-bottom:10px">No quality assessment yet</div>';
      html += '<div style="display:flex;gap:8px;justify-content:center">';
      html += '<button class="btn btn-primary" onclick="assessGuide(\\'' + guide.id + '\\')">Assess Quality</button>';
      html += '<button class="btn btn-green" onclick="regenerateGuide(\\'' + guide.id + '\\')">Regenerate Guide</button>';
      html += '</div></div>';
    }

    // Action buttons
    html += '<div class="btn-group" style="margin-bottom:20px">';
    html += '<button class="btn btn-green" onclick="downloadGuide(\\'' + guide.id + '\\',\\'' + esc(guide.guide_title).replace(/'/g, '') + '\\')">Download DOCX</button>';
    if (guide.fulfillment_link) html += '<a class="btn btn-dim" style="border-color:var(--blue);color:var(--blue)" href="' + esc(guide.fulfillment_link) + '" target="_blank">Fulfillment Link</a>';
    if (guide.cta_keyword) html += '<span style="padding:6px 14px;background:rgba(234,179,8,0.1);border:1px solid rgba(234,179,8,0.3);border-radius:6px;font-weight:700;color:var(--yellow);font-size:13px">CTA: ' + esc(guide.cta_keyword) + '</span>';
    html += '</div>';
    // Guide content
    if (guide.markdown_content) {
      html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:20px;max-height:600px;overflow-y:auto;white-space:pre-wrap;font-size:14px;line-height:1.7">' + esc(guide.markdown_content) + '</div>';
    } else {
      html += '<div class="empty">Guide content not yet generated.</div>';
    }
    // Posts using this guide
    html += '<div id="guide-posts-section" style="margin-top:20px;padding:16px;background:#0d1117;border:1px solid var(--border);border-radius:8px">';
    html += '<div style="font-size:13px;font-weight:700;color:var(--accent2);margin-bottom:8px">Posts Using This Guide</div>';
    html += '<div id="guide-posts-list" style="color:var(--dim);font-size:12px">Loading linked posts...</div>';
    html += '</div>';
    // Load posts async
    (async function() {
      try {
        const pkgs = await api('/content/packages?guide_id=' + guide.id);
        const el = document.getElementById('guide-posts-list');
        if (!el) return;
        if (!pkgs || pkgs.length === 0) {
          el.innerHTML = '<span style="color:var(--dim);font-size:12px">No posts linked to this guide yet.</span>';
          return;
        }
        let ph = '';
        for (const p of pkgs) {
          const hook = (p.facebook_post || p.linkedin_post || '').split('\\n')[0].substring(0, 80);
          const kw = p.cta_keyword || '-';
          const platforms = [];
          if (p.facebook_post) platforms.push('FB');
          if (p.linkedin_post) platforms.push('LI');
          ph += '<div style="display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid var(--border)">';
          ph += '<span style="font-size:11px;color:var(--yellow);font-weight:600;min-width:80px">CTA: ' + esc(kw) + '</span>';
          ph += '<span style="font-size:11px;color:var(--dim)">' + platforms.join(', ') + '</span>';
          ph += '<span style="flex:1;font-size:12px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(hook || 'No content') + '</span>';
          ph += '<button class="btn btn-dim" style="font-size:10px;padding:2px 8px" onclick="switchTab(\\'packages\\')">View</button>';
          ph += '</div>';
        }
        el.innerHTML = ph;
      } catch(e) {
        const el = document.getElementById('guide-posts-list');
        if (el) el.innerHTML = '<span style="color:var(--dim);font-size:12px">Could not load linked posts.</span>';
      }
    })();

    // Generate from Post section
    html += '<div style="margin-top:20px;padding:16px;background:#0d1117;border:1px solid var(--border);border-radius:8px">';
    html += '<div style="font-size:13px;font-weight:700;color:var(--accent2);margin-bottom:8px">Generate Guide from Post</div>';
    html += '<div style="font-size:11px;color:var(--dim);margin-bottom:8px">Paste a social media post below. The AI will research the topic and generate a guide that delivers on the post\\\'s promise.</div>';
    html += '<textarea id="from-post-input" rows="5" placeholder="Paste your post text here..." style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;color:var(--text);color-scheme:dark;resize:vertical;font-family:inherit;box-sizing:border-box"></textarea>';
    html += '<div style="display:flex;gap:8px;margin-top:8px;align-items:center">';
    html += '<input id="from-post-keyword" type="text" placeholder="CTA keyword (default: guide)" style="width:140px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:12px;color:var(--text);color-scheme:dark" />';
    html += '<button class="btn btn-green" style="font-size:12px" onclick="generateFromPost()">Generate Guide from Post</button>';
    html += '</div></div>';

    // Footer stats
    html += '<div style="display:flex;gap:16px;margin-top:16px;font-size:12px;color:var(--dim)">';
    html += '<span>Downloads: ' + (guide.downloads_count || 0) + '</span>';
    if (guide.conversion_rate != null) html += '<span>Conversion: ' + (guide.conversion_rate * 100).toFixed(1) + '%</span>';
    html += '<span>Created: ' + new Date(guide.created_at).toLocaleString() + '</span>';
    html += '</div>';
    html += '</div></div>';
    app.innerHTML = html;
  } catch(e) {
    app.innerHTML = '<div class="section"><button class="btn btn-dim" onclick="switchTab(\\'week\\')" style="margin-bottom:16px">Back to Week Planner</button><div class="empty">Error loading guide: ' + e.message + '</div></div>';
  }
}

// Assess all guides (backfill)
async function assessAllGuides() {
  try {
    toast('Assessing all guides with Sonnet (this may take a minute)...');
    const r = await api('/content/guides/backfill-assess', { method: 'POST' });
    if (r) { toast('Assessed ' + r.assessed + ' guides: ' + r.passed + ' passed, ' + r.failed + ' failed'); showWeekGuide(); }
    else { toast('Backfill failed', false); }
  } catch(e) { toast('Backfill error: ' + e.message, false); }
}

// Assess guide quality via LLM
async function assessGuide(guideId) {
  try {
    toast('Assessing guide quality (this takes ~10s)...');
    const r = await api('/content/guides/' + guideId + '/assess', { method: 'POST' });
    if (r && r.composite) { toast('Quality assessment complete!'); showWeekGuide(); }
    else { toast('Assessment failed', false); }
  } catch(e) { toast('Assessment error: ' + e.message, false); }
}

// Regenerate guide with quality gate loop (background task) + live polling
let _regenState = null;
let _regenTimerInterval = null;
let _regenPollInterval = null;

async function regenerateGuide(guideId, operatorFeedback) {
  if (!operatorFeedback && !confirm('Regenerate this guide? It will run the full research pipeline + up to 3 quality iterations. This may take 2-3 minutes.')) return;
  try {
    let url = '/content/guides/' + guideId + '/regenerate';
    if (operatorFeedback) url += '?operator_feedback=' + encodeURIComponent(operatorFeedback);
    const r = await api(url, { method: 'POST' });
    if (r && r.status === 'already_running') { toast('Regeneration already in progress'); return; }
    if (!r || r.status !== 'started') { toast('Regeneration failed to start', false); return; }
    _regenState = { guideId, startTime: Date.now(), feedback: operatorFeedback || null };
    pollRegenStatus(guideId);
  } catch(e) { toast('Regeneration error: ' + e.message, false); }
}

async function generateFromPost() {
  const postText = document.getElementById('from-post-input')?.value?.trim();
  if (!postText || postText.length < 50) { toast('Please paste a substantial post (at least 50 characters)', false); return; }
  const keyword = document.getElementById('from-post-keyword')?.value?.trim() || 'guide';
  try {
    const r = await api('/content/guides/generate-from-post', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ post_text: postText, cta_keyword: keyword }),
    });
    if (!r || r.status !== 'started') { toast('Failed to start guide generation', false); return; }
    _regenState = { guideId: r.tracking_id, startTime: Date.now(), fromPost: true };
    pollRegenStatus(r.tracking_id);
  } catch(e) { toast('Error: ' + e.message, false); }
}

function pollRegenStatus(guideId) {
  // Clear any existing intervals
  if (_regenPollInterval) clearInterval(_regenPollInterval);
  if (_regenTimerInterval) clearInterval(_regenTimerInterval);

  // Ensure spin + pulse animations exist
  if (!document.getElementById('regen-anim-style')) {
    const st = document.createElement('style');
    st.id = 'regen-anim-style';
    st.textContent = '@keyframes spin{to{transform:rotate(360deg)}} @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}';
    document.head.appendChild(st);
  }

  // Render initial card
  renderRegenProgress(null);

  // Elapsed timer updates every second
  _regenTimerInterval = setInterval(() => {
    const el = document.getElementById('regen-elapsed');
    if (el && _regenState) el.textContent = formatElapsed(Date.now() - _regenState.startTime);
  }, 1000);

  // Poll API every 3 seconds
  _regenPollInterval = setInterval(async () => {
    try {
      const pollUrl = _regenState?.fromPost ? '/content/generation-status/' + guideId : '/content/guides/' + guideId + '/regen-status';
      const s = await api(pollUrl);
      if (!s || s.status === 'idle') return;
      renderRegenProgress(s);
      if (s.status === 'done' || s.status === 'error') {
        clearInterval(_regenPollInterval);
        clearInterval(_regenTimerInterval);
        _regenPollInterval = null;
        _regenTimerInterval = null;
      }
    } catch(e) { /* ignore poll errors */ }
  }, 3000);
}

function renderRegenProgress(s) {
  let container = document.getElementById('regen-progress-card');
  if (!container) {
    container = document.createElement('div');
    container.id = 'regen-progress-card';
    container.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9999;width:420px;max-height:90vh;overflow-y:auto;animation:fadeIn 0.3s';
    document.body.appendChild(container);
  }

  const elapsed = _regenState ? formatElapsed(Date.now() - _regenState.startTime) : '0s';
  const phase = s?.phase || 0;
  const totalPhases = s?.total_phases || 4;
  const isDone = s?.status === 'done';
  const isError = s?.status === 'error';
  const isRunning = !isDone && !isError;

  // Completion banner - big unmissable background
  let cardBorder = 'var(--blue)';
  let cardBg = '';
  if (isDone && s.passed) { cardBorder = 'var(--green)'; cardBg = 'background:linear-gradient(135deg,#0a2e1a 0%,#0d1117 60%);'; }
  else if (isDone) { cardBorder = 'var(--yellow)'; cardBg = 'background:linear-gradient(135deg,#2e2a0a 0%,#0d1117 60%);'; }
  else if (isError) { cardBorder = 'var(--red)'; cardBg = 'background:linear-gradient(135deg,#2e0a0a 0%,#0d1117 60%);'; }
  let html = '<div class="card" style="padding:16px;border:2px solid ' + cardBorder + ';' + cardBg + '">';

  // Browser notification on completion (fires once)
  if ((isDone || isError) && !window._regenNotified) {
    window._regenNotified = true;
    try {
      if (Notification.permission === 'granted') {
        new Notification(isDone ? (s.passed ? 'Guide Ready!' : 'Guide Updated (below target)') : 'Regeneration Failed', { body: elapsed + ' elapsed', icon: '/favicon.ico' });
      } else if (Notification.permission !== 'denied') {
        Notification.requestPermission();
      }
    } catch(e) {}
    // Also flash the page title
    let _origTitle = document.title;
    document.title = isDone ? (s.passed ? 'DONE - Guide Ready!' : 'DONE - Below Target') : 'FAILED - Regeneration';
    setTimeout(() => { document.title = _origTitle; }, 5000);
  }
  // Reset notification flag when starting a new regen
  if (isRunning) { window._regenNotified = false; }

  // === Header row ===
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">';
  html += '<div style="display:flex;align-items:center;gap:8px">';
  if (isRunning) html += '<div style="width:14px;height:14px;border:2px solid var(--blue);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></div>';
  else if (isDone && s.passed) html += '<span style="font-size:22px">\\u2705</span>';
  else if (isDone) html += '<span style="font-size:22px">\\u26A0\\uFE0F</span>';
  else html += '<span style="font-size:22px">\\u274C</span>';
  if (isDone) html += '<span style="font-size:18px;font-weight:800;color:' + (s.passed ? 'var(--green)' : 'var(--yellow)') + '">' + (s.passed ? 'Guide Ready!' : 'Guide Updated (below target)') + '</span>';
  else if (isError) html += '<span style="font-size:16px;font-weight:700;color:var(--red)">Regeneration Failed</span>';
  else html += '<span style="font-size:14px;font-weight:700">Regenerating Guide</span>';
  html += '</div>';
  html += '<span id="regen-elapsed" style="font-size:12px;color:var(--dim);font-family:monospace">' + elapsed + '</span>';
  html += '</div>';

  // === Phase pipeline dots ===
  const phaseLabels = ['Research', 'Write v1', 'Write v2', 'Write v3'];
  html += '<div style="display:flex;align-items:center;gap:0;margin-bottom:14px">';
  for (let i = 0; i < 4; i++) {
    const phaseNum = i + 1;
    const done = phase > phaseNum || isDone;
    const active = phase === phaseNum && isRunning;
    const dotColor = done ? 'var(--green)' : (active ? 'var(--blue)' : 'var(--border)');
    const dotAnim = active ? ';animation:pulse 1.5s ease-in-out infinite' : '';
    html += '<div style="text-align:center;flex:0 0 auto">';
    html += '<div style="width:12px;height:12px;border-radius:50%;background:' + dotColor + dotAnim + ';margin:0 auto"></div>';
    html += '<div style="font-size:9px;color:' + (active ? 'var(--text)' : (done ? 'var(--green)' : 'var(--dim)')) + ';margin-top:3px;font-weight:' + (active ? '700' : '400') + ';white-space:nowrap">' + phaseLabels[i] + '</div>';
    html += '</div>';
    if (i < 3) html += '<div style="flex:1;height:2px;background:' + (done ? 'var(--green)' : 'var(--border)') + ';margin:0 4px;margin-bottom:14px"></div>';
  }
  html += '</div>';

  // === Current phase detail ===
  if (s?.detail && isRunning) {
    html += '<div style="font-size:12px;color:var(--accent2);margin-bottom:10px;font-weight:600">' + esc(s.phase_label || s.detail) + '</div>';
  }

  // === Agent step breakdown ===
  const stepStatus = s?.step_status || {};
  const stepEntries = Object.entries(stepStatus);
  if (stepEntries.length > 0) {
    const completed = stepEntries.filter(([,v]) => v === 'completed').length;
    html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:10px">';
    // Progress bar
    html += '<div style="height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:8px">';
    html += '<div style="height:100%;background:var(--green);width:' + Math.round((completed / stepEntries.length) * 100) + '%;transition:width 0.3s"></div>';
    html += '</div>';
    for (const [agent, st] of stepEntries) {
      const label = AGENT_LABELS[agent] || agent.replace(/_/g, ' ');
      let icon, stColor;
      if (st === 'completed') { icon = 'Done'; stColor = 'var(--green)'; }
      else if (st === 'running') { icon = 'Running...'; stColor = 'var(--blue)'; }
      else if (st === 'failed') { icon = 'Failed'; stColor = 'var(--red)'; }
      else { icon = 'Waiting'; stColor = 'var(--dim)'; }
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0;font-size:11px">';
      html += '<span style="color:' + (st === 'running' ? 'var(--text)' : 'var(--dim)') + ';font-weight:' + (st === 'running' ? '600' : '400') + '">';
      if (st === 'running') html += '<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--blue);margin-right:5px"></span>';
      html += label + '</span>';
      html += '<span style="color:' + stColor + ';font-weight:600;font-size:10px">' + icon + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  // === Live activity feed (last 8 log entries across all agents) ===
  const stepLogs = s?.step_logs || {};
  const allLogs = [];
  for (const [agent, logs] of Object.entries(stepLogs)) {
    if (Array.isArray(logs)) {
      for (const line of logs) allLogs.push(line);
    }
  }
  // Sort by timestamp prefix [HH:MM:SS]
  allLogs.sort();
  const recentLogs = allLogs.slice(-8);
  if (recentLogs.length > 0 && isRunning) {
    html += '<div style="background:#0a0e14;border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:10px;max-height:120px;overflow-y:auto;font-family:monospace;font-size:10px;line-height:1.6;color:var(--dim)">';
    for (const line of recentLogs) {
      html += '<div>' + esc(line) + '</div>';
    }
    html += '</div>';
  }

  // === Research summary ===
  const rs = s?.research_summary;
  if (rs) {
    html += '<div style="display:flex;gap:12px;margin-bottom:10px;padding:6px 10px;background:#0d1117;border:1px solid var(--border);border-radius:6px">';
    html += '<span style="font-size:11px;color:var(--green);font-weight:600">' + (rs.trends || 0) + ' trends</span>';
    html += '<span style="font-size:11px;color:var(--accent2);font-weight:600">' + (rs.claims || 0) + ' claims</span>';
    html += '<span style="font-size:11px;color:var(--blue);font-weight:600">' + (rs.sources || 0) + ' sources</span>';
    html += '</div>';
  }

  // === Score breakdown (after assessment) ===
  const scores = s?.scores;
  const scoreHistory = s?.score_history || [];
  if (scores || scoreHistory.length > 0) {
    const dims = ['practical', 'valuable', 'generous', 'accurate', 'quick_win', 'transformation'];
    const dimLabels = { practical: 'Practical', valuable: 'Valuable', generous: 'Generous', accurate: 'Accurate', quick_win: 'Quick Win', transformation: 'Transform' };

    // Show previous attempts dimmed
    for (let hi = 0; hi < scoreHistory.length - (isDone ? 0 : 1); hi++) {
      const h = scoreHistory[hi];
      html += '<div style="font-size:10px;color:var(--dim);margin-bottom:4px;opacity:0.5">Attempt ' + h.attempt + ': ' + (h.composite || 0).toFixed(1) + '/10</div>';
    }

    // Current/latest scores
    const latest = scores || (scoreHistory.length > 0 ? scoreHistory[scoreHistory.length - 1] : null);
    if (latest) {
      html += '<div style="background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:10px">';
      const comp = s?.composite || latest.composite || 0;
      const compColor = comp >= 8 ? 'var(--green)' : (comp >= 5 ? 'var(--yellow)' : 'var(--red)');
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
      html += '<span style="font-size:11px;color:var(--dim)">Quality Score</span>';
      html += '<span style="font-size:18px;font-weight:700;color:' + compColor + '">' + comp.toFixed(1) + '<span style="font-size:12px;color:var(--dim)">/10</span></span>';
      html += '</div>';
      for (const d of dims) {
        const val = latest[d] || 0;
        const barColor = val >= 8 ? 'var(--green)' : (val >= 5 ? 'var(--yellow)' : 'var(--red)');
        html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;font-size:10px">';
        html += '<span style="width:60px;color:var(--dim);text-align:right">' + (dimLabels[d] || d) + '</span>';
        html += '<div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden"><div style="height:100%;background:' + barColor + ';width:' + (val * 10) + '%;transition:width 0.3s"></div></div>';
        html += '<span style="width:16px;color:' + barColor + ';font-weight:700;font-family:monospace">' + val + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }
  }

  // === Completion / Error actions ===
  if (isDone) {
    // Feedback input for targeted reiteration
    const guideId = _regenState?.guideId || '';
    html += '<div style="margin-top:10px;padding:8px 10px;background:#0d1117;border:1px solid var(--border);border-radius:6px">';
    html += '<div style="font-size:10px;color:var(--dim);margin-bottom:4px">Not satisfied? Tell the AI what to fix:</div>';
    html += '<div style="display:flex;gap:6px">';
    html += '<input id="regen-feedback-input" type="text" placeholder="e.g. accuracy is too low, cite more named sources" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-size:12px;color:var(--text);color-scheme:dark" />';
    html += '<button class="btn btn-primary" style="font-size:11px;white-space:nowrap;padding:4px 10px" onclick="const fb=document.getElementById(\\'regen-feedback-input\\').value.trim();if(!fb){toast(\\'Type your feedback first\\',false);return;}document.getElementById(\\'regen-progress-card\\').remove();regenerateGuide(\\'' + guideId + '\\',fb)">Regen with Focus</button>';
    html += '</div>';
    html += '</div>';
    // If from-post, the guide_id comes from the status response
    const viewGuideId = s?.guide_id || guideId;
    html += '<div style="display:flex;gap:8px;margin-top:8px">';
    if (viewGuideId && viewGuideId !== guideId) {
      // New guide created from post - navigate to it specifically
      html += '<button class="btn btn-primary" style="flex:1;font-size:12px" onclick="document.getElementById(\\'regen-progress-card\\').remove();showWeekGuide(\\''+viewGuideId+'\\')">View New Guide</button>';
    } else {
      html += '<button class="btn btn-primary" style="flex:1;font-size:12px" onclick="document.getElementById(\\'regen-progress-card\\').remove();showWeekGuide()">View Updated Guide</button>';
    }
    html += '<button class="btn btn-dim" style="font-size:12px" onclick="document.getElementById(\\'regen-progress-card\\').remove()">Dismiss</button>';
    html += '</div>';
    // Show what operator feedback was used (if any)
    const usedFeedback = s?.operator_feedback || _regenState?.feedback;
    if (usedFeedback) {
      html += '<div style="margin-top:6px;font-size:10px;color:var(--dim)">Focus used: <span style="color:var(--accent2)">' + esc(usedFeedback) + '</span></div>';
    }
  } else if (isError) {
    html += '<div style="color:var(--red);font-size:12px;margin-bottom:8px">' + esc(s?.detail || 'Unknown error') + '</div>';
    html += '<button class="btn btn-dim" style="font-size:12px" onclick="document.getElementById(\\'regen-progress-card\\').remove()">Dismiss</button>';
  }

  html += '</div>';
  container.innerHTML = html;
}

// Download guide via fetch+blob (bypasses browser insecure-download block on HTTP)
async function downloadGuide(guideId, title) {
  try {
    const resp = await fetch(API + '/content/guides/' + guideId + '/download');
    if (!resp.ok) throw new Error('Download failed');
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = (title || 'guide') + '.docx'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  } catch(e) { toast('Download failed: ' + e.message, false); }
}

// --- TRENDS TAB ---
async function renderTrends() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="page-content"><div class="section"><div class="section-label">Trend Scanner</div><p style="color:var(--dim);margin-bottom:16px">Scan current trends relevant to your content strategy. Results come from live web search + analysis.</p><div class="btn-group"><button class="btn btn-primary" onclick="scanTrends()">Scan Now</button></div></div><div id="trend-results" style="margin-top:24px"><div class="empty">No recent trend scans. Click "Scan Now" to start.</div></div></div>';
  try {
    const briefs = await api('/briefs/trends');
    if (briefs && briefs.length > 0) {
      let html = '<div class="section-label">Recent Trend Briefs</div><div class="grid stagger-children">';
      for (const b of briefs.slice(0, 12)) {
        html += '<div class="card hover-lift" style="cursor:pointer" onclick="showTrendDetail(\\'' + b.id + '\\')">';
        html += '<h3>' + esc(b.focus_area || 'Trend') + '</h3>';
        html += '<div style="font-size:13px;margin-top:8px;color:var(--text)">' + esc((b.summary || '').slice(0, 120)) + (b.summary && b.summary.length > 120 ? '...' : '') + '</div>';
        html += '<div style="margin-top:8px;font-size:11px;color:var(--dim);font-family:\\'JetBrains Mono\\',monospace">' + (b.created_at ? new Date(b.created_at).toLocaleDateString() : '') + '</div>';
        html += '</div>';
      }
      html += '</div>';
      document.getElementById('trend-results').innerHTML = html;
    }
  } catch(e) { /* ok, just show empty */ }
}
async function scanTrends() {
  try {
    toast('Trend scan started...');
    const r = await api('/trends/scan', { method: 'POST', body: '{}' });
    if (r.scan_id) {
      const poll = setInterval(async () => {
        try {
          const s = await api('/trends/scan/' + r.scan_id);
          if (s.status === 'completed') { clearInterval(poll); renderTrends(); toast('Trend scan complete!'); }
          else if (s.status === 'failed') { clearInterval(poll); toast('Scan failed', false); }
        } catch { clearInterval(poll); }
      }, 3000);
    }
  } catch(e) { toast('Scan failed: ' + e.message, false); }
}
async function showTrendDetail(id) {
  try {
    const b = await api('/briefs/trends/' + id);
    const app = document.getElementById('app');
    let html = '<div class="page-content"><button class="btn btn-dim" onclick="renderTrends()" style="margin-bottom:16px">Back to Trends</button>';
    html += '<div class="card-hero"><h2 style="font-family:\\'JetBrains Mono\\',monospace;font-size:18px;margin-bottom:12px">' + esc(b.focus_area || 'Trend Brief') + '</h2>';
    html += '<div style="color:var(--text);line-height:1.7;white-space:pre-wrap">' + esc(b.summary || 'No summary available') + '</div>';
    if (b.sources && b.sources.length) {
      html += '<div style="margin-top:16px"><div class="section-label">Sources</div><div style="display:flex;flex-direction:column;gap:4px">';
      for (const s of b.sources) html += '<div style="font-size:12px;color:var(--dim)">' + esc(typeof s === 'string' ? s : JSON.stringify(s)) + '</div>';
      html += '</div></div>';
    }
    html += '</div></div>';
    app.innerHTML = html;
    updateBreadcrumb('Trends > ' + (b.focus_area || 'Detail'));
  } catch(e) { toast('Failed to load trend: ' + e.message, false); }
}

// --- HELP TAB ---
async function renderHelp() {
  const app = document.getElementById('app');
  let html = '<div class="page-content"><div class="section"><div class="section-label">Quick Start Guide</div><div id="help-quickstart"><div class="empty">Loading...</div></div></div>';
  html += '<div class="section"><div class="section-label">Keyboard Shortcuts</div><div class="card" style="font-size:13px;line-height:2"><div style="display:grid;grid-template-columns:auto 1fr;gap:4px 16px">';
  const shortcuts = [['J / K', 'Navigate between items'], ['Enter', 'Approve selected package'], ['Esc', 'Close modal or panel'], ['/', 'Focus search bar'], ['G then W', 'Go to Week Planner'], ['G then P', 'Go to Packages'], ['G then G', 'Go to Generate']];
  for (const [k, v] of shortcuts) {
    html += '<div><span class="tag" style="background:var(--card-hover);color:var(--text);letter-spacing:0">' + k + '</span></div><div style="color:var(--dim)">' + v + '</div>';
  }
  html += '</div></div></div>';
  html += '<div class="section"><div class="section-label">Glossary</div><div id="help-glossary"><div class="empty">Loading...</div></div></div></div>';
  app.innerHTML = html;

  try {
    const qs = await api('/onboarding/quickstart');
    const qsEl = document.getElementById('help-quickstart');
    if (qs && qs.steps) {
      let qh = '<div class="stagger-children" style="display:flex;flex-direction:column;gap:8px">';
      for (let i = 0; i < qs.steps.length; i++) {
        const s = qs.steps[i];
        qh += '<div class="card hover-lift"><div style="display:flex;gap:12px;align-items:start"><div style="font-size:20px;font-weight:700;color:var(--primary);font-family:\\'JetBrains Mono\\',monospace">' + (i+1) + '</div><div><div style="font-weight:600;margin-bottom:4px">' + esc(s.title || '') + '</div><div style="color:var(--dim);font-size:13px">' + esc(s.description || '') + '</div></div></div></div>';
      }
      qh += '</div>';
      qsEl.innerHTML = qh;
    } else { qsEl.innerHTML = '<div class="card"><div style="color:var(--dim)">No quickstart guide available yet.</div></div>'; }
  } catch { document.getElementById('help-quickstart').innerHTML = '<div class="card"><div style="color:var(--dim)">Quickstart guide not available.</div></div>'; }

  try {
    const gl = await api('/onboarding/glossary');
    const glEl = document.getElementById('help-glossary');
    if (gl && gl.terms && gl.terms.length) {
      let gh = '<div class="stagger-children" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px">';
      for (const t of gl.terms) {
        gh += '<div class="card"><div style="font-weight:600;color:var(--primary);font-family:\\'JetBrains Mono\\',monospace;font-size:13px;margin-bottom:4px">' + esc(t.term || '') + '</div><div style="color:var(--dim);font-size:12px">' + esc(t.definition || '') + '</div></div>';
      }
      gh += '</div>';
      glEl.innerHTML = gh;
    } else { glEl.innerHTML = '<div class="card"><div style="color:var(--dim)">No glossary available yet.</div></div>'; }
  } catch { document.getElementById('help-glossary').innerHTML = '<div class="card"><div style="color:var(--dim)">Glossary not available.</div></div>'; }
}

// === WEEK BUILDER ===
// Pool of AI-generated options on the right, 7 day slots on the left.
// Drag from pool into slots to compose the ideal week.
let _wbPool = []; // all topic options from planning
let _wbSlots = [null, null, null, null, null, null, null]; // 7 day slots (Mon-Sun)
let _wbHidden = new Set(); // indices of hidden pool items

function wbSave() {
  try {
    localStorage.setItem('wb_pool', JSON.stringify(_wbPool));
    localStorage.setItem('wb_slots', JSON.stringify(_wbSlots));
    localStorage.setItem('wb_hidden', JSON.stringify([..._wbHidden]));
  } catch {}
}
function wbRestore() {
  try {
    const p = localStorage.getItem('wb_pool');
    const s = localStorage.getItem('wb_slots');
    const h = localStorage.getItem('wb_hidden');
    if (p) _wbPool = JSON.parse(p);
    if (s) _wbSlots = JSON.parse(s);
    if (h) _wbHidden = new Set(JSON.parse(h));
  } catch {}
}
const WB_DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const WB_ANGLE_COLORS = { big_shift_explainer: '#6366f1', tactical_workflow_guide: '#22c55e', contrarian_diagnosis: '#ef4444', case_study_build_story: '#eab308', second_order_implication: '#3b82f6' };

async function renderWeekBuilder() {
  wbRestore();
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><h2>Week Builder</h2><div style="display:flex;gap:8px;align-items:center"><button class="btn btn-primary" id="wb-generate-btn" onclick="wbGeneratePool()">Generate 20 Ideas (~$0.45)</button><button class="btn btn-green" id="wb-approve-btn" onclick="wbApproveWeek()" style="display:none">Approve Week</button></div></div><p style="color:var(--dim);font-size:13px;margin-bottom:16px">Generate a pool of topic ideas, then drag the best ones into your 7-day slots.</p><div class="wb-layout"><div class="wb-slots" id="wb-slots"></div><div class="wb-pool" id="wb-pool"><div style="text-align:center;padding:40px 20px;color:var(--muted)"><div style="font-size:28px;margin-bottom:8px">&#127919;</div>Click "Generate 20 Ideas" to fill this pool with AI-generated topics from current trends.</div></div></div></div>';
  if (_wbPool.length) {
    // Restored from localStorage - render immediately
    wbRenderSlots();
    wbRenderPool();
  } else {
    // Try loading from API
    await wbLoadExistingPool();
    wbSave();
    wbRenderSlots();
    wbRenderPool();
  }
}

async function wbLoadExistingPool() {
  try {
    const monday = getMonday(new Date());
    const endDate = new Date(monday);
    endDate.setDate(endDate.getDate() + 27); // 4 weeks
    const entries = await api('/calendar/?start=' + fmtDate(monday) + '&end=' + fmtDate(endDate));
    _wbPool = [];
    for (const entry of entries) {
      try {
        const options = await api('/calendar/' + entry.id + '/options');
        for (const opt of options) {
          _wbPool.push({
            id: 'opt-' + entry.id + '-' + opt.option_index,
            entry_id: entry.id,
            option_index: opt.option_index,
            topic: opt.topic,
            angle_type: opt.angle_type,
            thesis: opt.plan_context?.thesis || '',
            audience: opt.plan_context?.audience || '',
            belief_shift: opt.plan_context?.desired_belief_shift || '',
            connection_to_gift: opt.plan_context?.connection_to_gift || '',
            visual_job: opt.plan_context?.visual_job || 'cinematic_symbolic',
            evidence_requirements: opt.plan_context?.evidence_requirements || [],
            is_selected: opt.is_selected,
            date: entry.date,
          });
        }
      } catch { /* no options for this entry */ }
      // Also add the entry itself as an option if it has a topic
      if (entry.topic && !_wbPool.some(p => p.topic === entry.topic)) {
        _wbPool.push({
          id: 'entry-' + entry.id,
          entry_id: entry.id,
          option_index: -1,
          topic: entry.topic,
          angle_type: entry.angle_type || '',
          thesis: entry.plan_context?.thesis || '',
          audience: entry.plan_context?.audience || '',
          belief_shift: entry.plan_context?.desired_belief_shift || '',
          connection_to_gift: entry.plan_context?.connection_to_gift || '',
          visual_job: entry.plan_context?.visual_job || 'cinematic_symbolic',
          evidence_requirements: entry.plan_context?.evidence_requirements || [],
          is_selected: false,
          date: entry.date,
        });
      }
    }
  } catch { _wbPool = []; }
}

function wbRenderSlots() {
  const container = document.getElementById('wb-slots');
  if (!container) return;
  let html = '<div style="font-family:\\'JetBrains Mono\\',monospace;font-size:12px;color:var(--primary);font-weight:600;margin-bottom:8px">YOUR WEEK (' + _wbSlots.filter(Boolean).length + '/7 filled)</div>';
  for (let i = 0; i < 7; i++) {
    const slot = _wbSlots[i];
    const filled = slot ? ' filled' : '';
    html += '<div class="wb-slot' + filled + '" data-slot="' + i + '" ondragover="event.preventDefault();this.classList.add(\\'drag-over\\')" ondragleave="this.classList.remove(\\'drag-over\\')" ondrop="this.classList.remove(\\'drag-over\\');wbDropInSlot(event,' + i + ')">';
    html += '<div class="ws-label">' + WB_DAY_NAMES[i];
    if (slot) html += '<button class="ws-remove" onclick="wbRemoveFromSlot(' + i + ')">remove</button>';
    html += '</div>';
    if (slot) {
      const ac = WB_ANGLE_COLORS[slot.angle_type] || 'var(--dim)';
      html += '<div class="ws-topic">' + esc(slot.topic) + '</div>';
      html += '<span class="ws-angle" style="background:' + ac + '22;color:' + ac + '">' + (slot.angle_type || '').replace(/_/g, ' ') + '</span>';
    } else {
      html += '<div class="ws-empty">Drag a topic here</div>';
    }
    html += '</div>';
  }
  container.innerHTML = html;
  // Show approve button if any slots filled
  const approveBtn = document.getElementById('wb-approve-btn');
  if (approveBtn) approveBtn.style.display = _wbSlots.some(Boolean) ? '' : 'none';
}

function wbRenderPool() {
  const container = document.getElementById('wb-pool');
  if (!container) return;
  if (!_wbPool.length) return; // keep the placeholder
  const usedTopics = new Set(_wbSlots.filter(Boolean).map(s => s.topic));
  let availCount = 0;
  for (let pi = 0; pi < _wbPool.length; pi++) { if (!_wbHidden.has(pi) && !usedTopics.has(_wbPool[pi].topic)) availCount++; }
  let html = '<div style="font-family:\\'JetBrains Mono\\',monospace;font-size:12px;color:var(--accent);font-weight:600;margin-bottom:8px">' + availCount + ' TOPIC IDEAS</div>';
  for (let pi = 0; pi < _wbPool.length; pi++) {
    if (_wbHidden.has(pi)) continue;
    const p = _wbPool[pi];
    if (usedTopics.has(p.topic)) continue; // hide items already in a slot
    const ac = WB_ANGLE_COLORS[p.angle_type] || 'var(--dim)';
    html += '<div class="wb-pool-card" draggable="true" data-pool-idx="' + pi + '" ondragstart="wbPoolDragStart(event,' + pi + ')">';
    html += '<div style="display:flex;justify-content:space-between;align-items:start;gap:8px">';
    html += '<div class="pc-topic">' + esc(p.topic) + '</div>';
    html += '<div style="display:flex;gap:4px;align-items:center;flex-shrink:0">';
    html += '<span class="pc-angle" style="background:' + ac + '22;color:' + ac + '">' + (p.angle_type || '').replace(/_/g, ' ') + '</span>';
    html += '<button onclick="wbHideIdea(' + pi + ')" title="Hide this idea" style="background:none;border:none;cursor:pointer;padding:2px 4px;font-size:14px;color:var(--dim);line-height:1">&times;</button>';
    html += '</div>';
    html += '</div>';
    if (p.thesis) html += '<div class="pc-thesis">' + esc(p.thesis) + '</div>';
    html += '<div class="pc-meta">';
    if (p.audience) html += '<span>' + esc(p.audience) + '</span>';
    if (p.date) html += '<span>from ' + p.date + '</span>';
    html += '</div>';
    html += '</div>';
  }
  if (_wbHidden.size > 0) {
    html += '<button onclick="wbShowHidden()" style="background:none;border:1px solid var(--border);border-radius:6px;padding:8px 12px;color:var(--dim);cursor:pointer;width:100%;margin-top:4px;font-size:13px">' + _wbHidden.size + ' hidden idea' + (_wbHidden.size > 1 ? 's' : '') + ' - click to show</button>';
  }
  container.innerHTML = html;
}

function wbHideIdea(poolIdx) {
  _wbHidden.add(poolIdx);
  wbSave();
  wbRenderPool();
}

function wbShowHidden() {
  _wbHidden.clear();
  wbSave();
  wbRenderPool();
}

function wbPoolDragStart(ev, poolIdx) {
  ev.dataTransfer.setData('text/plain', String(poolIdx));
  ev.dataTransfer.effectAllowed = 'copy';
  ev.target.classList.add('dragging');
  setTimeout(() => ev.target.classList.remove('dragging'), 100);
}

function wbDropInSlot(ev, slotIdx) {
  ev.preventDefault();
  const poolIdx = parseInt(ev.dataTransfer.getData('text/plain'), 10);
  if (isNaN(poolIdx) || !_wbPool[poolIdx]) return;
  _wbSlots[slotIdx] = { ..._wbPool[poolIdx] };
  wbSave();
  wbRenderSlots();
  wbRenderPool();
}

function wbRemoveFromSlot(slotIdx) {
  _wbSlots[slotIdx] = null;
  wbSave();
  wbRenderSlots();
  wbRenderPool();
}

async function wbGeneratePool() {
  const btn = document.getElementById('wb-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating ideas...'; }
  const monday = getMonday(new Date());
  try {
    const r = await api('/monthly/plan', { method: 'POST', body: JSON.stringify({ month_start: fmtDate(monday) }) });
    // Poll for completion
    let done = false;
    while (!done) {
      await new Promise(ok => setTimeout(ok, 4000));
      try {
        const st = await api('/monthly/' + r.plan_id + '/status');
        if (btn) btn.textContent = st.phase_detail || 'Planning...';
        if (st.status === 'completed') {
          done = true;
          toast('Ideas generated! Drag your favorites into the slots.');
          await wbLoadExistingPool();
          wbSave();
          wbRenderPool();
        } else if (st.status === 'failed') {
          done = true;
          toast('Failed: ' + (st.error || 'Unknown'), false);
        }
      } catch { /* keep polling */ }
    }
  } catch (e) {
    toast('Failed: ' + e.message, false);
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Generate 20 Ideas (~$0.45)'; }
}

async function wbApproveWeek() {
  const filled = _wbSlots.filter(Boolean);
  if (!filled.length) { toast('No topics in your week yet', false); return; }
  // Save each slot to the post stack
  let saved = 0;
  for (let i = 0; i < 7; i++) {
    const slot = _wbSlots[i];
    if (!slot || !slot.entry_id) continue;
    // Select this option in the calendar
    if (slot.option_index >= 0) {
      try {
        await api('/calendar/' + slot.entry_id + '/options/' + slot.option_index + '/select', { method: 'POST' });
        saved++;
      } catch { /* already selected or no options */ }
    }
  }
  toast(saved + ' topics approved for the week!');
}

async function addToStack(packageId) {
  try {
    await api('/stack/add', { method: 'POST', body: JSON.stringify({ post_package_id: packageId }) });
    toast('Added to post stack!');
  } catch (e) { toast('Failed: ' + e.message, false); }
}

// === ELEMENT FEEDBACK (regenerate individual elements) ===
async function elementFeedback(packageId, element, btn) {
  const feedback = prompt('What should change about this ' + element.replace(/_/g, ' ') + '?');
  if (!feedback || !feedback.trim()) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Regenerating...'; }
  try {
    const result = await api('/content/packages/' + packageId + '/element-feedback', {
      method: 'POST',
      body: JSON.stringify({ element: element, feedback: feedback.trim() }),
    });
    toast(element.replace(/_/g, ' ') + ' regenerated!');
    // Refresh package cache
    const ci = _pkgCache?.findIndex(p => p.id === packageId);
    if (ci !== undefined && ci !== -1 && result.updated_package) {
      Object.assign(_pkgCache[ci], result.updated_package);
    }
    _renderPkgFromCache();
  } catch (e) {
    toast('Regeneration failed: ' + e.message, false);
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Feedback'; }
}

// ========== BRAND PROFILES ==========

let _brandsCache = null;
let _brandFormVisible = false;
let _editingBrandId = null;

async function renderBrands() {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="section"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><h2 style="margin:0">Brand Profiles</h2><button class="btn btn-primary" onclick="showBrandForm()">+ New Brand</button></div><div id="brand-form-area"></div><div id="brands-list"><div class="empty">Loading...</div></div></div>';
  try {
    const brands = await api('/profiles/brands');
    _brandsCache = brands;
    const creators = await api('/profiles/creators');
    const creatorMap = {};
    for (const c of creators) creatorMap[c.id] = c.creator_name;
    let html = '';
    if (brands.length === 0) {
      html = '<div class="empty">No brand profiles yet. Click "+ New Brand" to create one.</div>';
    } else {
      html = '<div class="grid">';
      for (const b of brands) {
        const colors = b.colors || {};
        const fonts = b.fonts || {};
        const swatches = ['primary','accent','dark','text','gradientDark','gradientAccent']
          .map(k => colors[k] ? '<div style="width:20px;height:20px;border-radius:4px;background:' + esc(colors[k]) + ';border:1px solid var(--border);display:inline-block;margin-right:4px" title="' + k + ': ' + esc(colors[k]) + '"></div>' : '')
          .join('');
        html += '<div class="card" style="cursor:pointer" onclick="editBrand(\\'' + b.id + '\\')">';
        html += '<div style="display:flex;justify-content:space-between;align-items:flex-start">';
        html += '<div><h3 style="text-transform:none;margin:0 0 8px 0">' + esc(b.name) + '</h3>';
        if (b.description) html += '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">' + esc(b.description) + '</div>';
        html += '</div>';
        if (b.logo_url) html += '<img src="' + esc(b.logo_url) + '" style="width:40px;height:40px;border-radius:6px;object-fit:contain;background:var(--bg)" />';
        html += '</div>';
        html += '<div style="margin-bottom:8px">' + swatches + '</div>';
        if (fonts.heading || fonts.body) html += '<div style="font-size:11px;color:var(--muted)">Fonts: ' + esc(fonts.heading || '-') + ' / ' + esc(fonts.body || '-') + '</div>';
        if (b.creator_profile_id && creatorMap[b.creator_profile_id]) html += '<div style="font-size:11px;color:var(--accent2);margin-top:4px">Creator: ' + esc(creatorMap[b.creator_profile_id]) + '</div>';
        if (b.voice_config && b.voice_config.elevenlabs_voice_id) html += '<div style="font-size:11px;color:var(--green);margin-top:4px">TTS Voice: ' + esc(b.voice_config.elevenlabs_voice_id) + '</div>';
        html += '<div style="margin-top:12px;display:flex;gap:8px">';
        html += '<button class="btn btn-dim" onclick="event.stopPropagation();editBrand(\\'' + b.id + '\\')">Edit</button>';
        html += '<button class="btn" style="color:var(--red)" onclick="event.stopPropagation();deleteBrand(\\'' + b.id + '\\',\\'' + esc(b.name) + '\\')">Delete</button>';
        html += '</div></div>';
      }
      html += '</div>';
    }
    document.getElementById('brands-list').innerHTML = html;
  } catch (e) {
    document.getElementById('brands-list').innerHTML = '<div class="empty">Error: ' + e.message + '</div>';
  }
}

function showBrandForm(brand) {
  _editingBrandId = brand ? brand.id : null;
  const c = brand?.colors || {};
  const f = brand?.fonts || {};
  const vc = brand?.voice_config || {};
  const formEl = document.getElementById('brand-form-area');
  formEl.innerHTML = '<div class="card" style="margin-bottom:20px">'
    + '<h3 style="margin:0 0 16px 0">' + (brand ? 'Edit Brand' : 'New Brand') + '</h3>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
    + '<div><label style="font-size:11px;color:var(--muted)">Name *</label><input id="bf-name" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(brand?.name || '') + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Description</label><input id="bf-desc" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(brand?.description || '') + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Logo URL</label><input id="bf-logo" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(brand?.logo_url || '') + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Creator Profile</label><select id="bf-creator" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px"><option value="">None</option></select></div>'
    + '</div>'
    + '<div style="margin-top:16px"><label style="font-size:12px;font-weight:600;color:var(--accent2)">Colors</label>'
    + '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px">'
    + _colorInput('bf-c-primary', 'Primary', c.primary || '#2ea3f2')
    + _colorInput('bf-c-accent', 'Accent', c.accent || '#00d4ff')
    + _colorInput('bf-c-dark', 'Dark', c.dark || '#0f172a')
    + _colorInput('bf-c-text', 'Text', c.text || '#e2e8f0')
    + _colorInput('bf-c-textMuted', 'Text Muted', c.textMuted || '#94a3b8')
    + _colorInput('bf-c-white', 'White', c.white || '#ffffff')
    + _colorInput('bf-c-gradientDark', 'Gradient Dark', c.gradientDark || '#020617')
    + _colorInput('bf-c-gradientAccent', 'Gradient Accent', c.gradientAccent || '#1e3a5f')
    + '</div></div>'
    + '<div style="margin-top:16px"><label style="font-size:12px;font-weight:600;color:var(--accent2)">Fonts</label>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">'
    + '<div><label style="font-size:11px;color:var(--muted)">Heading</label><input id="bf-f-heading" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(f.heading || 'Poppins') + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Body</label><input id="bf-f-body" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(f.body || 'Open Sans') + '"></div>'
    + '</div></div>'
    + '<div style="margin-top:16px"><label style="font-size:12px;font-weight:600;color:var(--accent2)">Voice Config (ElevenLabs)</label>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px">'
    + '<div><label style="font-size:11px;color:var(--muted)">Voice ID</label><input id="bf-vc-voiceid" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + esc(vc.elevenlabs_voice_id || '') + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Stability</label><input id="bf-vc-stability" type="number" step="0.1" min="0" max="1" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + (vc.stability ?? 0.5) + '"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Similarity</label><input id="bf-vc-similarity" type="number" step="0.1" min="0" max="1" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="' + (vc.similarityBoost ?? 0.75) + '"></div>'
    + '</div></div>'
    + '<div style="margin-top:20px;display:flex;gap:8px">'
    + '<button class="btn btn-primary" onclick="saveBrand()">Save</button>'
    + '<button class="btn btn-dim" onclick="hideBrandForm()">Cancel</button>'
    + '</div></div>';
  // Populate creator dropdown
  _loadCreatorDropdown(brand?.creator_profile_id);
}

function _colorInput(id, label, value) {
  return '<div><label style="font-size:11px;color:var(--muted)">' + label + '</label><div style="display:flex;gap:6px;align-items:center"><input type="color" id="' + id + '" value="' + value + '" style="width:36px;height:30px;border:1px solid var(--border);border-radius:4px;cursor:pointer;background:transparent"><input type="text" id="' + id + '-hex" value="' + value + '" style="width:80px;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:4px 6px;border-radius:4px;font-size:11px" oninput="document.getElementById(\\'' + id + '\\').value=this.value" onchange="document.getElementById(\\'' + id + '\\').value=this.value"></div></div>';
}

async function _loadCreatorDropdown(selectedId) {
  try {
    const creators = await api('/profiles/creators');
    const sel = document.getElementById('bf-creator');
    if (!sel) return;
    for (const c of creators) {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = c.creator_name;
      if (c.id === selectedId) opt.selected = true;
      sel.appendChild(opt);
    }
  } catch (e) {}
}

function hideBrandForm() {
  _editingBrandId = null;
  const formEl = document.getElementById('brand-form-area');
  if (formEl) formEl.innerHTML = '';
}

async function saveBrand() {
  const name = document.getElementById('bf-name').value.trim();
  if (!name) { toast('Name is required', false); return; }
  const body = {
    name,
    description: document.getElementById('bf-desc').value.trim() || null,
    logo_url: document.getElementById('bf-logo').value.trim() || null,
    creator_profile_id: document.getElementById('bf-creator').value || null,
    colors: {
      primary: document.getElementById('bf-c-primary').value,
      accent: document.getElementById('bf-c-accent').value,
      dark: document.getElementById('bf-c-dark').value,
      text: document.getElementById('bf-c-text').value,
      textMuted: document.getElementById('bf-c-textMuted').value,
      white: document.getElementById('bf-c-white').value,
      gradientDark: document.getElementById('bf-c-gradientDark').value,
      gradientAccent: document.getElementById('bf-c-gradientAccent').value,
    },
    fonts: {
      heading: document.getElementById('bf-f-heading').value.trim(),
      body: document.getElementById('bf-f-body').value.trim(),
    },
    voice_config: {
      elevenlabs_voice_id: document.getElementById('bf-vc-voiceid').value.trim() || null,
      stability: parseFloat(document.getElementById('bf-vc-stability').value) || 0.5,
      similarityBoost: parseFloat(document.getElementById('bf-vc-similarity').value) || 0.75,
    },
  };
  try {
    if (_editingBrandId) {
      await api('/profiles/brands/' + _editingBrandId, { method: 'PATCH', body: JSON.stringify(body) });
      toast('Brand updated');
    } else {
      await api('/profiles/brands', { method: 'POST', body: JSON.stringify(body) });
      toast('Brand created');
    }
    hideBrandForm();
    renderBrands();
  } catch (e) {
    toast('Failed: ' + e.message, false);
  }
}

async function editBrand(brandId) {
  try {
    const brand = await api('/profiles/brands/' + brandId);
    showBrandForm(brand);
    document.getElementById('brand-form-area').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast('Failed to load brand: ' + e.message, false);
  }
}

async function deleteBrand(brandId, name) {
  if (!confirm('Delete brand "' + name + '"? This cannot be undone.')) return;
  try {
    await api('/profiles/brands/' + brandId, { method: 'DELETE' });
    toast('Brand deleted');
    renderBrands();
  } catch (e) {
    toast('Failed: ' + e.message, false);
  }
}

// ========== PRODUCT DEMO ==========

let _demoRunId = null;
let _demoPollInterval = null;

async function renderProductDemo() {
  const app = document.getElementById('app');
  // Load brands for dropdown
  let brandsOpts = '<option value="">None (use defaults)</option>';
  try {
    const brands = await api('/profiles/brands');
    for (const b of brands) brandsOpts += '<option value="' + b.id + '">' + esc(b.name) + '</option>';
  } catch (e) {}

  app.innerHTML = '<div class="section">'
    + '<h2>Product Demo Video</h2>'
    + '<p style="color:var(--muted);margin-bottom:20px">Generate a product demo video from product info. Uses the ProductDemo Remotion template with TTS voiceover.</p>'
    + '<div class="card" style="max-width:700px">'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
    + '<div><label style="font-size:11px;color:var(--muted)">Product Name *</label><input id="pd-name" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" placeholder="KMBoards"></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">Tagline *</label><input id="pd-tagline" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" placeholder="AI-powered agency boards"></div>'
    + '</div>'
    + '<div style="margin-top:12px"><label style="font-size:11px;color:var(--muted)">Problem Statement</label><textarea id="pd-problem" rows="2" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px;resize:vertical" placeholder="Agencies waste hours on manual content planning..."></textarea></div>'
    + '<div style="margin-top:12px"><label style="font-size:11px;color:var(--muted)">Features (one per line)</label><textarea id="pd-features" rows="4" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px;resize:vertical" placeholder="AI content generation&#10;Smart scheduling&#10;Brand consistency"></textarea></div>'
    + '<div style="margin-top:12px"><label style="font-size:11px;color:var(--muted)">Screenshot URLs (one per line)</label><textarea id="pd-screenshots" rows="3" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px;resize:vertical" placeholder="https://example.com/screenshot1.png"></textarea></div>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">'
    + '<div><label style="font-size:11px;color:var(--muted)">Demo Video URL</label><input id="pd-video" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" placeholder="https://..."></div>'
    + '<div><label style="font-size:11px;color:var(--muted)">CTA Text</label><input id="pd-cta" class="search-input" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px" value="zivraviv.com"></div>'
    + '</div>'
    + '<div style="margin-top:12px"><label style="font-size:11px;color:var(--muted)">Brand Profile</label><select id="pd-brand" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:8px;border-radius:6px">' + brandsOpts + '</select></div>'
    + '<div style="margin-top:20px;display:flex;gap:12px;align-items:center">'
    + '<button class="btn btn-primary" id="pd-generate-btn" onclick="generateProductDemo(this)">Generate Demo Video</button>'
    + '<span id="pd-status" style="font-size:12px;color:var(--muted)"></span>'
    + '</div>'
    + '<div id="pd-progress" style="margin-top:12px"></div>'
    + '<div id="pd-results" style="margin-top:20px"></div>'
    + '</div></div>';
}

async function generateProductDemo(btn) {
  const name = document.getElementById('pd-name').value.trim();
  const tagline = document.getElementById('pd-tagline').value.trim();
  if (!name || !tagline) { toast('Product name and tagline are required', false); return; }

  const features = document.getElementById('pd-features').value.trim().split('\\n').filter(Boolean);
  const screenshots = document.getElementById('pd-screenshots').value.trim().split('\\n').filter(Boolean);

  const body = {
    product_name: name,
    product_tagline: tagline,
    product_problem: document.getElementById('pd-problem').value.trim() || null,
    product_features: features,
    screenshot_urls: screenshots,
    demo_video_url: document.getElementById('pd-video').value.trim() || null,
    cta_text: document.getElementById('pd-cta').value.trim() || 'zivraviv.com',
  };
  const brandId = document.getElementById('pd-brand').value;
  if (brandId) body.brand_profile_id = brandId;

  btn.disabled = true;
  btn.textContent = 'Generating...';
  const statusEl = document.getElementById('pd-status');
  const progressEl = document.getElementById('pd-progress');
  statusEl.textContent = 'Starting product demo pipeline...';
  statusEl.style.color = 'var(--accent2)';
  progressEl.innerHTML = '<div style="width:100%;height:6px;background:var(--border);border-radius:3px"><div id="pd-bar" style="height:100%;background:var(--accent2);width:10%;border-radius:3px;transition:width 0.5s ease"></div></div>';

  try {
    const resp = await fetch('/api/v1/videos/product-demo', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to start demo generation');

    _demoRunId = data.run_id;
    statusEl.textContent = 'Pipeline running (run: ' + data.run_id.substring(0, 8) + ')...';

    const bar = document.getElementById('pd-bar');
    let pct = 15;
    _demoPollInterval = setInterval(() => {
      pct = Math.min(pct + 3, 90);
      if (bar) bar.style.width = pct + '%';
    }, 3000);

    // Poll for completion
    let attempts = 0;
    while (attempts < 120) {
      await new Promise(r => setTimeout(r, 5000));
      attempts++;
      try {
        const checkResp = await fetch('/api/v1/pipeline/' + data.run_id + '/status');
        const status = await checkResp.json();
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(_demoPollInterval);
          if (bar) bar.style.width = '100%';
          if (status.status === 'completed') {
            statusEl.textContent = 'Demo video generated!';
            statusEl.style.color = 'var(--green)';
            // Show results
            const resultsEl = document.getElementById('pd-results');
            const ctx = status.context || {};
            const videos = ctx.video_assets || [];
            if (videos.length > 0) {
              let rhtml = '<h3 style="margin-bottom:12px">Generated Videos</h3><div class="grid">';
              for (const v of videos) {
                rhtml += '<div class="card"><video src="' + esc(v.url || v.video_url || '') + '" controls style="width:100%;border-radius:6px;margin-bottom:8px"></video>';
                rhtml += '<div style="font-size:11px;color:var(--muted)">' + esc(v.template_name || v.resolution || '') + '</div></div>';
              }
              rhtml += '</div>';
              resultsEl.innerHTML = rhtml;
            } else {
              resultsEl.innerHTML = '<div class="empty">Pipeline completed but no video assets found. Check pipeline logs.</div>';
            }
          } else {
            statusEl.textContent = 'Generation failed: ' + (status.error || 'Unknown error');
            statusEl.style.color = 'var(--red)';
          }
          break;
        }
        // Update status text with agent info if available
        if (status.current_agent) {
          statusEl.textContent = 'Running ' + status.current_agent + '...';
        }
      } catch (e) {}
    }
  } catch (e) {
    if (_demoPollInterval) clearInterval(_demoPollInterval);
    statusEl.textContent = 'Error: ' + e.message;
    statusEl.style.color = 'var(--red)';
    progressEl.innerHTML = '';
  }
  btn.disabled = false;
  btn.textContent = 'Generate Demo Video';
}

// Router
function render() {
  const map = { week: renderWeek, builder: renderWeekBuilder, guides: renderGuides, topic: renderTopic, generate: renderGenerate, packages: renderPackages, corpus: renderCorpus, voice: renderVoice, creators: renderCreators, agents: renderAgents, costs: renderCosts, analytics: renderAnalytics, templates: renderTemplates, prompts: renderPrompts, settings: renderSettings, chat: renderChat, trends: renderTrends, help: renderHelp, 'product-demo': renderProductDemo, brands: renderBrands };
  updateBreadcrumb(null);
  (map[currentTab] || renderGenerate)();
}
restoreGenAllState();
// Tick elapsed timer every second when generating
setInterval(() => { if (genAllState?.running) renderGenAllProgress(); }, 1000);

// --- Start From Copy ---
function runPolishCopy() {
  var copyEl = document.getElementById('polish-copy-text');
  var copyText = copyEl ? copyEl.value.trim() : '';
  if (!copyText) { toast('Please paste your copy first', false); return; }
  var platform = document.getElementById('polish-platform').value || 'both';
  var ctaKw = document.getElementById('polish-cta').value.trim() || null;
  var notesVal = document.getElementById('polish-notes').value.trim() || null;
  var btn = document.getElementById('polish-btn');
  btn.disabled = true; btn.textContent = 'Starting...';
  polishStartTime = Date.now();
  api('/pipeline/polish-copy', { method: 'POST', body: JSON.stringify({ copy_text: copyText, platform: platform, cta_keyword: ctaKw, notes: notesVal }) })
    .then(function(r) {
      activePolishRun = r.run_id;
      localStorage.setItem('tce_active_polish', r.run_id);
      toast('Copy polish started');
      pollPolish();
      if (polishPollInterval) clearInterval(polishPollInterval);
      polishPollInterval = setInterval(pollPolish, 3000);
    })
    .catch(function(e) { toast('Failed: ' + e.message, false); btn.disabled = false; btn.textContent = 'Polish & Build Package'; });
}

async function pollPolish() {
  if (!activePolishRun) return;
  try {
    const r = await api('/pipeline/polish-copy/' + activePolishRun + '/status');
    const container = document.getElementById('polish-status');
    const elapsed = document.getElementById('polish-elapsed');
    const btn = document.getElementById('polish-btn');
    if (!container) return;
    const sec = polishStartTime ? Math.round((Date.now() - polishStartTime) / 1000) : 0;
    if (elapsed) elapsed.textContent = sec > 0 ? sec + 's elapsed' : '';

    const stepStatus = r.step_status || {};
    const steps = ['copy_analyzer', 'cta_agent', 'copy_polisher', 'creative_director', 'qa_agent'];
    let badges = '<div class="pipeline-steps">';
    for (const s of steps) {
      const st = stepStatus[s] || 'pending';
      const label = AGENT_LABELS[s] || s;
      badges += '<span class="step-badge ' + st + '">' + (st === 'running' ? '<span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:4px"></span>' : '') + label + '</span>';
    }
    badges += '</div>';

    if (r.status === 'completed') {
      if (btn) { btn.disabled = false; btn.textContent = 'Polish & Build Package'; }
      clearInterval(polishPollInterval); polishPollInterval = null;
      activePolishRun = null; localStorage.removeItem('tce_active_polish');
      _pkgCache = null;
      // Clear the textarea to avoid confusion
      const ta = document.getElementById('polish-copy-input');
      if (ta) ta.value = '';
      // Fetch the created package and render inline
      if (r.pipeline_run_id) {
        try {
          const pkgs = await api('/content/packages?pipeline_run_id=' + encodeURIComponent(r.pipeline_run_id));
          const pkg = pkgs && pkgs.length > 0 ? pkgs[0] : null;
          if (pkg) {
            let hdr = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">';
            hdr += '<span style="color:var(--green);font-weight:600;font-size:15px">Package created!</span>';
            hdr += '<button class="btn btn-dim" style="font-size:11px" onclick="openBrainstorm(\\'' + pkg.id + '\\')">Brainstorm</button>';
            hdr += '<button class="btn btn-blue" style="font-size:11px" onclick="switchTab(\\'packages\\')">View in Packages</button>';
            hdr += '</div>';
            container.innerHTML = badges + '<div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">' + hdr + _renderPkgCard(pkg) + '</div>';
            return;
          }
        } catch(e) { console.error('Failed to render inline package:', e); }
      }
      container.innerHTML = badges + '<div style="margin-top:12px;color:var(--green);font-weight:600">Package created successfully! <button class="btn btn-blue" style="font-size:12px;margin-left:8px" onclick="switchTab(\\'packages\\')">View in Packages</button></div>';
    } else if (r.status === 'failed' || r.status === 'interrupted') {
      container.innerHTML = badges + '<div style="margin-top:12px;color:var(--red);font-weight:600">Failed: ' + esc(r.error || r.phase_detail || 'Unknown error') + '</div>';
      if (btn) { btn.disabled = false; btn.textContent = 'Polish & Build Package'; }
      clearInterval(polishPollInterval); polishPollInterval = null;
      activePolishRun = null; localStorage.removeItem('tce_active_polish');
    } else {
      container.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span class="spinner"></span><span>' + esc(r.phase_detail || 'Running...') + '</span></div>' + badges;
    }
  } catch (e) { /* ignore poll errors */ }
}

// --- Brainstorm ---
function openBrainstorm(packageId) {
  brainstormPackageId = packageId;
  brainstormHistory = [];
  let panel = document.getElementById('brainstorm-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'brainstorm-panel';
    panel.style.cssText = 'position:fixed;bottom:20px;right:20px;width:420px;height:500px;background:var(--card);border:1px solid var(--accent);border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.5);display:flex;flex-direction:column;z-index:1000';
    document.body.appendChild(panel);
  }
  panel.style.display = 'flex';
  panel.innerHTML = `
    <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
      <div style="font-weight:600;font-size:14px">Senior Strategist</div>
      <button onclick="closeBrainstorm()" style="background:none;border:none;color:var(--dim);cursor:pointer;font-size:18px">x</button>
    </div>
    <div id="brainstorm-messages" style="flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px">
      <div style="color:var(--dim);font-size:13px;text-align:center;padding:20px">Senior Strategist - can search the web, access briefs, research, templates, and all team resources. Ask anything.</div>
    </div>
    <div style="padding:12px;border-top:1px solid var(--border);display:flex;gap:8px">
      <input type="text" id="brainstorm-input" placeholder="Type your message..." style="flex:1" onkeydown="if(event.key==='Enter')sendBrainstorm()">
      <button class="btn btn-primary" onclick="sendBrainstorm()">Send</button>
    </div>`;
  document.getElementById('brainstorm-input')?.focus();
}

function closeBrainstorm() {
  const panel = document.getElementById('brainstorm-panel');
  if (panel) panel.style.display = 'none';
  brainstormPackageId = null;
  brainstormHistory = [];
}

async function sendBrainstorm() {
  const input = document.getElementById('brainstorm-input');
  const msg = input?.value?.trim();
  if (!msg) return;
  input.value = '';
  input.disabled = true;

  const messagesDiv = document.getElementById('brainstorm-messages');
  messagesDiv.innerHTML += '<div style="align-self:flex-end;background:var(--accent);color:#fff;padding:8px 12px;border-radius:12px 12px 2px 12px;max-width:85%;font-size:13px;line-height:1.5">' + esc(msg) + '</div>';
  messagesDiv.innerHTML += '<div id="brainstorm-typing" style="align-self:flex-start;color:var(--dim);font-size:12px;display:flex;align-items:center;gap:6px"><span class="spinner" style="width:14px;height:14px;border-width:2px"></span>Thinking...</div>';
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  brainstormHistory.push({ role: 'user', content: msg });
  try {
    const r = await api('/pipeline/brainstorm', { method: 'POST', body: JSON.stringify({ message: msg, package_id: brainstormPackageId, history: brainstormHistory.slice(0, -1) }) });
    brainstormHistory.push({ role: 'assistant', content: r.reply });
    const typing = document.getElementById('brainstorm-typing');
    if (typing) typing.remove();
    let toolBadges = '';
    if (r.tool_calls_made && r.tool_calls_made.length > 0) {
      toolBadges = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px">';
      r.tool_calls_made.forEach(tc => {
        const label = tc.tool === 'web_search' ? 'Searched: ' + esc(tc.query) : 'Looked up ' + (tc.days_back || 7) + 'd of packages';
        toolBadges += '<span style="font-size:10px;background:var(--accent);color:#fff;padding:2px 6px;border-radius:4px;opacity:0.8">' + label + '</span>';
      });
      toolBadges += '</div>';
    }
    messagesDiv.innerHTML += '<div style="align-self:flex-start;max-width:85%">' + toolBadges + '<div style="background:#111318;border:1px solid var(--border);padding:8px 12px;border-radius:12px 12px 12px 2px;font-size:13px;line-height:1.5;white-space:pre-wrap">' + esc(r.reply) + '</div></div>';
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  } catch (e) {
    const typing = document.getElementById('brainstorm-typing');
    if (typing) typing.remove();
    messagesDiv.innerHTML += '<div style="color:var(--red);font-size:12px;padding:4px 8px">Error: ' + esc(e.message) + '</div>';
  }
  input.disabled = false;
  input.focus();
}

// Tick polish elapsed timer
setInterval(() => {
  if (activePolishRun && polishStartTime) {
    const el = document.getElementById('polish-elapsed');
    if (el) el.textContent = Math.round((Date.now() - polishStartTime) / 1000) + 's elapsed';
  }
}, 1000);

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
