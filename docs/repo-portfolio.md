# Kivi Media Repo Portfolio - Case Study Material for Content

**Source of truth:** `https://github.com/kivimedia` (60+ active repos as of 2026-04-26).
**Purpose:** This is the catalog of builds Ziv Raviv has actually shipped. The strategist references this when picking topics so content can tie back to real, named, in-flight work - not generic AI commentary.

**Rule:** These repos are **proof material**, not products being sold. The offer is Super Coaching for Coaches ($4-5K/month). The repos demonstrate that the AI-agent methodology is real, working, and worth teaching. When a topic naturally connects to one of these builds, name it and tell the story. When it doesn't, don't force it.

---

## Flagship platforms (the AI agent thesis, in production)

- **kmboards** (kmboards.co): the central agency dashboard - 150+ named agents, multi-tenant, RLS-enforced. Built and rebuilt multiple times. The clearest "AI agent team for an agency" case study.
- **kmcrm** (crm.kivimedia.co): multi-brand CRM that replaced 17hats internally. Real migration off a paid SaaS.
- **DevCast**: voice-first senior engineer. Listens to your repos, gives daily briefings, dispatches coding agents from your phone. The "agent that knows your codebase" angle.
- **TCE** (Team Content Engine, this repo): the content factory itself - trend scout + weekly planner + post packagers + walking-video splitter. Self-referential proof.
- **kmshake**: cold email outreach platform with 12 scenario templates. Replaced an outsourced cold email agency.
- **inquiry-qualifier-pro / leadgate.pro**: lead qualification with Google Ads + Calendar OAuth. Currently in OAuth verification.

## Industry-specific agent teams (proof the methodology generalizes)

- **gobo-designer / progobo.com**: lighting designer React SPA inside a WP/WooCommerce plugin. Proves AI-built UI can ship inside legacy WordPress.
- **dj-hub / beat-boss-ui**: full-feature DJ event CRM. "Event Pro CRM" merging gigboard + kmcrm.
- **carolinaHQ**: balloon proposal platform. Trello migration story - moved an entire studio off Trello onto custom software.
- **KaraokeMadness** (karaokemadness.co): Crazy Lyrics pipeline, Lambda chain-compile. AI-driven karaoke video factory.
- **matan-magic-crm**: WhatsApp lead pipeline for an Israeli magician. Hebrew RTL, Plaud transcripts. Niche-specific automation.
- **whatsapp-coach-agent**: nutrition coach engagement monitor on VPS. Decodo IL proxy + Baileys. Real client running it.
- **cpbg-events**: WordPress plugin for synagogue event management, registration, payments. Religious-niche software.
- **choirmind**: Hebrew RTL system to practice learning lyrics. Side project that became client onboarding.
- **sewbabygift**: Etsy product photo enhancement dashboard. Mask-based inpainting (NEVER generative on products).
- **Inventory-Plus / qa-inventoryplus**: inventory management + Playwright E2E QA suite. The "I built tests for my own SaaS" angle.

## Skills + bridges (the "make Claude do anything" angle)

- **meta-app-submit-skill**: Claude skill that automates Meta App Review submissions. Public.
- **watch-video-skill** (CutSense): AI Video Understanding & Programmatic Editing Engine. Public.
- **schedule-youtube-short-skill**: schedule YouTube Shorts via API. Native server-side `publishAt`, no cron needed.
- **schedule-insta-post-skill**: Instagram scheduling via Meta Graph API.
- **schedule-linkedin-post-skill**: LinkedIn scheduler - thin client to kmboards' Camoufox session.
- **schedule-fb-page-post-skill**: Facebook Page scheduler.
- **gmail-send-skill**: Gmail with attachments via gws auth. Fills the gap in `gws gmail +send`. Public.
- **browser-history-skill**: read-only CLI for Chrome/Edge/Firefox history. Public. "Match Fathom call timestamps to the sites you were on."
- **feature-pointer**: takes a screenshot, draws a green arrow + callout on a UI element. Public.
- **vercel-deploy-watcher / railway-deploy-watcher**: monitor deployments after every push. Public.
- **repo-summary**: AI CLI summarizing GitHub activity across all repos. Public.
- **canon-memory-claude-rules**: 6 rules. No scaffolding. The "Claude already knows how to code" stance. Public.
- **deployhelper-scanner**: scan local dev folders for API keys, upload to vault. Public.
- **rename-my-window**: VS Code extension to rename editor window titles. Public.
- **orellius-browser-bridge**: multi-session fork supporting parallel Claude instances on different tabs. Public.

## Bridges (legacy CRM / external tool integrations)

- **SMPL_Bridge**: WPForms -> SMPL CRM bridge for In The Mix Events.
- **djeventplanner-bridge**: VPS bridge for DJEP Classic ASP CRM.
- **ppm-bridge**: Telegram bridge for PartyProManager (Playwright-backed).
- **zoho-bridge**: Zoho integration.
- **wp-gtw-integration**: WordPress plugin replacing Zapier for GoToWebinar. Public.

## Specialty AI pipelines

- **instaiq**: Instagram Profile Intelligence - multi-agent deep profile analysis.
- **tiktokiq**: TikTok analogue.
- **meeting-analyzer**: TRIBE v2 Zoom objection detection + follow-up.
- **courseiq**: multi-agent course capture, transcription, knowledge extraction.
- **script-engine**: Hebrew video script pipeline.
- **seo-machine-stagesplus**: 13-agent SEO content pipeline for Stages Plus (Orlando stage rental).
- **techseo-worker**: polls audits + crawls via Scrapling on VPS.
- **marizai**: AI Executive Assistant ("Virtual Maris").
- **agent-artist-studio**: AI art workflow.

## Side / portfolio (talking points only)

- **relaytext / relaytext-android**: desktop SMS scheduler + Android companion.
- **proposal-poppers**: proposal software.
- **testimonial-editor**: Electron desktop app, Yaron method, 3-phase workflow.
- **gigboard**, **harmony-hub**, **lavabowl**, **sendtoamram**, **ghost-hunter**, **glowandco**, **appspotlight**, **florist-delivery-calculator**, **lead-glow-ux**, **design-canvas-pro**, **gobo-design**, **signature-intelligence**, **gig-harmony-ui**, **export-hats**, **deployhelper-desktop-scanner**, **tentmeister-calculator**, **vibe-test-studio**, **gobotab-km**, **webapp-tester**: smaller / archived / single-purpose builds. Reference only when a topic explicitly fits.

---

## How the planner should use this

1. **Don't force a repo into every day.** A week of 5 days where every topic ties back to a Kivi build feels like a brag-feed. 1-2 days/week is the right cadence.
2. **Use repos as evidence, not as the topic.** Bad: "Today I'm announcing kmboards has new features." Good: "I rebuilt my agency's task system 4 times in 90 days. Here's what version 4 finally got right (and why versions 1-3 were wrong)." The story is the *learning*, the repo is the *proof*.
3. **Match repo to angle:**
   - **big_shift_explainer** (Mon): point to a repo as "I bet on this shift early - here's what it looks like in production"
   - **tactical_workflow_guide** (Tue): "Here's the exact workflow I used to build [repo] - copy this"
   - **contrarian_diagnosis** (Wed): "Most agencies are doing X. I built [repo] specifically to avoid that. Here's why."
   - **case_study_build_story** (Thu): the most natural fit - a repo IS a case study
   - **second_order_implication** (Fri): "I built [repo] for one client. Three months later it changed how I think about [bigger thing]."
4. **Reference current Claude/model versions when the story includes them.** "Sonnet 4.6 cut my agent costs 40% so I rebuilt [repo] on it" is way better than "I'm using a recent Anthropic model."
5. **Public repos are link-worthy.** When the topic discusses a public repo (`watch-video-skill`, `gmail-send-skill`, `repo-summary`, etc.), the post can include the GitHub URL as the CTA.
