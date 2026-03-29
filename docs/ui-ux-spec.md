# Team Content Engine - UI/UX Specification

> **Purpose of this document:** Describe every screen, feature, and interaction in the TCE dashboard so a designer can propose a visual redesign without needing to read any source code. No API paths, database columns, or implementation details are included.

---

## 1. Product Overview

**Team Content Engine (TCE)** is an AI-powered content production dashboard for a single operator (the content manager of a marketing agency). The operator uses TCE to:

1. **Plan** a week of social media content (Mon-Fri)
2. **Generate** daily content packages (posts, hooks, images, DM funnels) using AI agents
3. **Review, revise, and approve** each package before publishing
4. **Teach the system** their brand voice through feedback, corpus uploads, and direct edits
5. **Monitor costs and quality** across all AI-generated output
6. **Track trends** from the web and social channels to inform content topics
7. **Schedule publishing** to Facebook and LinkedIn with timed delivery

The tool is not customer-facing. It is an internal operator console - think "recording studio control room" rather than "social media app." The operator is the only user.

---

## 2. Global Layout

### 2.1 Header Bar (persistent, top of every page)

| Element | Position | Behavior |
|---------|----------|----------|
| **App Title** - "Team Content Engine" | Left | Static text, acts as home link |
| **Global Search** | Center | Text input. Typing filters across posts, topics, and templates. Results appear in a dropdown below the input (max 10 results, scrollable). Clicking a result navigates to the relevant tab. Pressing `/` focuses the search field from anywhere. |
| **Notifications Bell** | Right of search | Icon with a red badge showing unread count. Clicking opens a dropdown panel listing recent alerts (pipeline failures, completed runs, feedback reminders, competitor overlap warnings). Each notification is dismissible. |
| **Help Icon** ("?") | Right of bell | Opens the Onboarding / Help panel (see section 3.15). |
| **System Health Dot** | Far right | A small colored circle - green when all systems are healthy, red when something is down. Hovering shows a tooltip with status details (e.g. "Database: OK, Version: 1.2.3"). |

### 2.2 Main Navigation (horizontal tab bar, below header)

15 tabs in a single row:

1. Week Planner
2. Generate
3. Packages
4. Corpus
5. Voice Profile
6. Creators
7. Agents
8. Costs
9. Analytics
10. Templates
11. Prompts
12. Settings
13. Chat
14. Trends
15. Help / Onboarding

The active tab is visually highlighted. Tabs do not reload the page - switching is instant. Keyboard shortcuts `Alt+1` through `Alt+6` jump to the first six tabs.

### 2.3 Breadcrumb Navigation (secondary nav, below tab bar)

A contextual path that updates dynamically as the operator navigates into nested views. Examples:

- "Week Planner > Wednesday > Package"
- "Packages > FB Copy > Edit Mode"
- "Corpus > Monthly Report.docx > Examples"

Each segment is clickable, allowing the operator to jump back to any parent level. The breadcrumb is hidden when the operator is at a top-level tab with no nested context.

### 2.4 Toast Notifications (global)

Success and error messages appear as small cards in the bottom-right corner. They auto-dismiss after 3 seconds. Green for success, red for errors. They stack if multiple fire at once.

---

## 3. Page-by-Page Specification

---

### 3.1 Week Planner

**Purpose:** Plan and visualize an entire week of content at a glance. This is the operator's "home base" - the first thing they see.

#### 3.1.1 Week Navigation

- **Week title** at the top: "Week of Mon Jan 13 - Fri Jan 17"
- Three navigation buttons: **Prev Week**, **This Week**, **Next Week**
- A cost summary line: "Today: $0.42 | Last plan: $0.25 | Total planning: $1.80"

#### 3.1.2 Planning Controls

A card with inputs for configuring the weekly AI plan:

- **Weekly Theme** - Optional text field (placeholder: "e.g. Agency scaling without burnout"). Gives the AI a creative direction for the whole week.
- **Sensitive Period** checkbox - When checked, the AI avoids war metaphors, fear-based hooks, and trivializing language. A tooltip explains this.
- **Seasonal Override** checkbox - When checked, reveals a textarea for seasonal context (e.g. "Post-holiday focus, Q1 planning season").
- **Cost hint** - Small text: "~$0.25 per plan" with a tooltip explaining token costs.
- **"Plan This Week" button** (primary action) - Launches the AI planner. Disabled while planning is in progress.
- **"Generate from Plan" button** (secondary, green) - Generates content packages from the existing plan. Shows contextual text like "Generate 3 Remaining" if some days already have packages.

#### 3.1.3 Planning Progress (appears while planning)

An animated card that shows real-time progress:

- A spinner icon
- Progress text that updates through stages: "Starting..." then "Searching trends..." then "Strategist choosing topics..." then "Plan ready!"
- An elapsed timer counting up (e.g. "1m 23s")
- Three step indicators in a row: **Trend Research** then **Strategy** then **Saving Plan** - each changes color as it progresses (gray = pending, blue = active, green = done)

#### 3.1.4 Weekly Theme Summary (appears after plan is created)

A styled card with a gradient background showing:

- **Weekly Direction** - The AI's chosen theme for the week (text block)
- **Gift of the Week** - Title, subtitle, and section count for the weekly downloadable guide (green accent)
- **CTA Keyword** - The call-to-action keyword for the week, shown large and bold (yellow accent)
- **"Edit Plan" button** - Opens the Plan Review Panel (see 3.1.5)
- **"View Guide" button** - Opens the dedicated Weekly Guide overlay (see 3.1.7)

#### 3.1.5 Plan Review Panel (appears when editing the plan)

A rich inline form that replaces the summary card when editing. Contains:

**Global fields:**
- **Weekly Theme** - Editable text field
- **Gift Theme** - Editable text field for the weekly guide topic
- **CTA Keyword** - Editable text field

**Trend Brief section** (collapsible):
- Shows the current week's trend candidates discovered by the Trend Scout
- Each trend displays: topic name, relevance score badge (color-coded), source URLs (clickable), and suggested angle
- **"Use This Trend"** action on each trend - seeds a day's topic from this trend

**Per-day fields** (5 day sections, Mon-Fri):
Each day has editable fields for:
- **Topic** - What the post is about
- **Thesis** - The core argument or insight
- **Audience** - Who this post targets
- **Belief Shift** - What the reader should think differently after reading
- **Gift Connection** - How this day's post ties to the weekly guide

Each field has an individual **"AI Feedback"** button that opens an inline popover for the AI to suggest improvements to that specific field.

**Bottom action buttons:**
- **"Approve & Generate All 5 Days"** (primary, green) - Locks the plan and triggers generation for all days
- **"Save Plan Only"** (secondary) - Saves edits without generating
- **"Dismiss"** (dim) - Closes the review panel without saving

#### 3.1.6 Day Cards Grid

Five cards arranged horizontally (Mon through Fri), forming the core calendar view.

**Each day card contains:**

- **Day name and date** - e.g. "Monday" / "Jan 15". Today's card shows "(TODAY)" next to the name.
- **Angle Type badge** - A colored pill showing the content angle for that day (e.g. "Big Shift Explainer", "Tactical Workflow", "Contrarian Diagnosis"). Each angle type has its own color. Hovering shows a description tooltip.
- **Topic text** - The planned topic for that day, or italic dimmed "No topic set" if unplanned.
- **Buffer post indicator** - Small yellow text if this day is a buffer/filler post.
- **Status badge** - One of: UNPLANNED (gray), PLANNED (blue), READY (green), APPROVED (green), GENERATING (blue with spinner), PUBLISHED (purple), SKIPPED (yellow), FAILED (red), SCHEDULED (teal).
- **Action buttons** (contextual):
  - If a package exists: green **"Package"** button (navigates to Packages tab) + dim **"Regenerate"** button
  - If planned but no package: primary **"Generate"** button
  - If unplanned: no buttons, just the status badge

**Drag-and-drop:** Day cards can be dragged and reordered. While dragging, the source card becomes semi-transparent with a dashed border. The drop target shows a green outline.

**Responsive behavior:**
- Desktop (>900px): 5 columns
- Tablet (600-900px): 3 columns
- Mobile (<600px): 1 column, stacked vertically

#### 3.1.7 Weekly Guide Overlay (opens from "View Guide" button)

A full-screen overlay showing the weekly guide contents:

- **Guide title** (large heading)
- **Rendered guide sections** - The full guide content displayed with formatted headings, paragraphs, and tables
- **"Download DOCX"** button (green, prominent)
- **Guide performance stats:**
  - Download count (large number)
  - Conversion rate (percentage)
- **"Close"** button or click-outside to dismiss the overlay

#### 3.1.8 Topic Queue (below the day cards grid)

A section for managing future content topics:

- **Title:** "Topic Queue"
- **Add topic input** - Text field + **"Add"** button to add a topic to the reserve queue
- **Queue list** - Draggable list of topics held in reserve. Each topic shows:
  - Topic text
  - Suggested angle (if any)
  - **"Promote to This Week"** button - Moves the topic into an unplanned day slot
  - **"Remove"** button (dim)
- **Buffer post management** - Topics flagged as buffer posts show a yellow "Buffer" badge. Buffer posts are lighter-weight filler content for weeks when the operator has less bandwidth.

---

### 3.2 Generate (Run Pipeline)

**Purpose:** Manually trigger AI content generation pipelines and watch their progress in real time.

#### 3.2.1 Pipeline Configuration

A card with:

- **Workflow dropdown** - Four options:
  - "Daily Content (full pipeline)" - Runs all agents for one day's content
  - "Weekly Planning" - Runs trend research + strategy only
  - "Corpus Ingestion" - Parses and scores uploaded documents
  - "Weekly Learning" - Analyzes past week's feedback and improves the system
- **Description text** - Updates dynamically based on the selected workflow
- **Day of Week dropdown** - Shows Mon-Fri, each labeled with that day's angle type (e.g. "Thu - Case Study Build")
- **"Run Pipeline" button** (primary) - Launches the pipeline. Disabled after clicking to prevent double-runs.
- **Verbose Mode toggle** - "Verbose mode (show what each agent is doing)"

#### 3.2.2 Pipeline Progress (appears after running)

- **Header** showing the run ID (truncated)
- **Model fallback indicator** - If any agent in this run used a fallback model instead of the intended one, a yellow warning banner appears: "Fallback model used for [agent name] - [primary model] was unavailable, used [fallback model]"
- **Step badges row** - One badge per agent in the pipeline. Each badge is color-coded: green = completed, blue = running, gray = pending, red = failed.
- **Agent detail sections** (verbose mode only):
  - Each agent gets a collapsible panel
  - Header shows: agent name, status, and a one-line summary of the latest activity
  - Expanded view shows a scrollable log with timestamped entries like:
    - "[14:23:01] Starting content generation..."
    - "[14:23:05] LLM responded with 2,400 tokens"
    - "[14:23:08] Done. Quality score: 7.2"
  - Log entries are color-coded by type (blue for start, green for completion, yellow for LLM calls, red for errors)

---

### 3.3 Packages

**Purpose:** Review, approve, or reject the AI-generated content packages. This is where the operator does quality control before publishing.

#### 3.3.1 Header Controls

- **Title:** "Content Packages"
- **"Backfill All Hooks"** button (dim) - Regenerates hooks for all packages that are missing them
- **"Show archived"** checkbox - Toggles visibility of archived packages

#### 3.3.2 Day Filter Tabs

A row of tab buttons for Mon through Fri. Clicking a day filters the list to only show packages for that day. These are generated from the current week's calendar.

#### 3.3.3 Package Cards

Each package is a card with multiple sections:

**Package header:**
- Title or ID
- Creation date
- Status badge: DRAFT (gray), APPROVED (green), REJECTED (red), SCHEDULED (teal)
- **Model fallback warning** - If this package was generated using a fallback model, a small yellow "Fallback" badge appears next to the status. Hovering shows which agent used which fallback model and why.

**Metadata row:**
- Day of week
- Topic
- Angle type
- Date

**Content tabs within each card** (horizontal tab bar inside the card):

1. **Facebook Post** - Shows the full post text in a preview box (dark background, white text, scrollable). Below the preview:
   - **"Copy"** button - Copies text to clipboard
   - **"Edit"** button - Toggles the post display into a live textarea for direct editing. While editing: word count updates in real time, a **"Save"** button commits the edit, a **"Cancel"** button reverts. This is for manual edits without AI involvement.
   - **"Feedback"** button - Opens an inline popover with a textarea for writing revision notes, plus "Cancel" and "Revise with AI" buttons. The AI rewrites the post based on the feedback.
   - **"AI Revise Post"** button - Same as Feedback but more prominent

2. **LinkedIn Post** - Same layout and controls as Facebook Post, with LinkedIn-specific content

3. **Hooks** - Shows 3-5 alternative hook (opening line) variants, numbered. Each hook has a **"Use this"** button to select it as the primary hook. A **"Regenerate Hooks"** button at the bottom creates fresh alternatives.

4. **QA Scores** - A grid showing quality scores across 12 dimensions (Engagement, Tone, Structure, Humanitarian Sensitivity, etc.). Each score is a large number with color coding: green for high scores, yellow for medium, red for low.
   - **Expandable rows** - Clicking a dimension row expands it to show the AI model's written justification for that specific score (e.g. "Score 8: Strong hook with curiosity gap, evidence-backed claim, clear value proposition").
   - **Operator override** - Each dimension has an **"Override"** button that opens a small form with a score input (1-10) and a mandatory reason textarea. Overrides are permanently logged and shown with a "Manual" badge.
   - **Humanitarian gate** - If the humanitarian sensitivity dimension scores below threshold, the entire package is flagged with a red banner: "Humanitarian sensitivity flag triggered." The operator can override this with a **"Override with Justification"** button that requires a written reason. This override is logged permanently and cannot be undone.

5. **Image Prompt** - Shows the AI-generated image prompt text with:
   - **"Copy Prompt"** button
   - **"Generate Images"** button - When generating, shows an animated progress bar with status text ("Sending to image generator...", percentage, time estimate)
   - **Generated images grid** - After generation, images appear in a grid. Each image has:
     - **Platform badge** - Small label showing which platform the image is optimized for (e.g. "fal.ai", "Midjourney")
     - **Hover overlay** with two buttons:
       - **"Download"** - Downloads the image file to the operator's computer
       - **"Copy URL"** - Copies the CDN URL to clipboard

6. **DM Flow** - Shows a sequence of direct message steps. Each step displays:
   - Step label, message text, delay/timing, and trigger condition
   - **Per-field edit controls** - Each field (message text, delay, trigger keyword) has a small pencil icon. Clicking it opens an inline edit input for that specific field. Changes save individually.
   - **"Copy All DM Messages"** button copies the entire flow as formatted text

7. **Context** - (accessible via **"Show Context"** button on the package card header)
   An expandable panel revealing why the AI made the choices it did:
   - **Influence weights table** - Shows which source creators influenced this package and by how much (percentage bars)
   - **Research evidence** - List of source URLs and claims that were verified before writing
   - **Thesis derivation** - How the AI arrived at the core argument
   - **Relevance scores** - How well this package matches the weekly plan and audience
   - Collapsible, click to close

**Package action buttons** (below the tabs):
- **"Approve"** (green) - Marks the package as approved for publishing
- **"Reject"** (red) - Marks as rejected
- **"Schedule"** (teal) - Opens a date/time picker dialog for scheduling future publication. After scheduling, the package shows a "SCHEDULED" status with the scheduled date/time displayed.
- **"Submit Revised Copy"** (blue) - Opens the Revised Copy form (see 3.3.6)
- **"Archive"** (dim) - Hides the package from the default view
- **"Reset to Draft"** - Reverts to draft status
- **"Export"** - Opens the raw package data in a new window

**Feedback form** (collapsible section at the bottom of each card):
- 17 tag checkboxes organized as:
  - **Negative tags** (13): hook too aggressive, hook too weak, thesis unclear, thesis off-brand, CTA unfulfillable, CTA too pushy, tone mismatch, too long, too short, factual error, formatting issue, image mismatch, DM flow weak
  - **Positive tags** (4): great hook, strong thesis, perfect tone, good images
- **Notes** textarea for free-form feedback
- **Action dropdown**: Approved / Revised / Rejected
- **"Submit Feedback"** button

#### 3.3.4 Weekly Guides Section

Below the packages list, a separate section titled "Weekly Guides" shows guide cards:

- **Guide title**
- **Week start date**, theme, CTA keyword
- **"Download DOCX"** button (green) - Downloads the formatted guide document
- **"Fulfillment Link"** button (blue) - External link if configured
- **"Archive"** button
- **Collapsible "View Guide Content"** - Expands to show the guide's markdown content in a scrollable preview

#### 3.3.5 Schedule Publish Dialog

When the operator clicks "Schedule" on a package:

- A modal overlay appears with:
  - **Date picker** - Calendar widget for selecting the publish date
  - **Time picker** - Hour and minute selection
  - **Platform checkboxes** - Which platforms to publish to (Facebook, LinkedIn)
  - **"Confirm Schedule"** button (primary)
  - **"Cancel"** button
- After scheduling, the package status changes to "SCHEDULED" with the date/time shown on the card

#### 3.3.6 Submit Revised Copy Form

When the operator clicks "Submit Revised Copy" on an approved package:

- A form panel expands below the package card:
  - **Facebook revised text** - Large textarea pre-filled with the approved FB post. The operator edits it to match what they actually published.
  - **Word count** (FB) - Live counter below the textarea
  - **LinkedIn revised text** - Large textarea pre-filled with the approved LI post
  - **Word count** (LI) - Live counter below the textarea
  - **"Preview Changes"** button - Opens a side-by-side word-level diff panel:
    - Left column: "Original" (the AI-generated text)
    - Right column: "Your version" (the operator's edits)
    - Color-coded diff: green highlighted = added words, red strikethrough = removed words, gray = unchanged
  - **"Submit Revised Copy"** button (primary) - Saves the revision to the learning pipeline. This teaches the AI the operator's actual voice.
  - **"Cancel"** button

---

### 3.4 Corpus

**Purpose:** Upload reference documents (swipe files, past content) that the AI learns from. Review extracted examples and manage the learning loop.

#### 3.4.1 File Upload Zone

A large clickable area: "+ Click to upload DOCX or TXT file". Clicking opens a file picker (accepts .docx and .txt). Subtitle: "Auto-analyzes corpus (extracts examples, scores engagement, mines patterns)". Shows upload progress during transfer.

#### 3.4.2 Documents List

Each uploaded document shows:
- File icon and filename
- Metadata: file type, page count, upload date
- **Approval status badge**: Approved (green), Pending (yellow), Rejected (red)
- **"Approve"** button (green) - Marks the document as approved for use by the AI
- **"Reject"** button (red) - Opens a small dialog with a mandatory reason textarea, then marks the document as rejected (AI will not learn from it)
- **"View Examples"** button - Opens a new window showing all extracted examples from this document
- **"Preview"** button - Opens the extracted raw text
- **Filter by status** - Dropdown or toggle buttons to filter: All / Approved / Pending / Rejected

**Examples Viewer (opens in new window):**
A dark-themed, RTL-compatible page showing each extracted example as a card:
- Creator name
- Engagement metrics (reactions, comments, shares, saves) with color coding
- Hook type tag
- Full post text (scrollable)
- Highlighted hook and CTA text
- Tone tags (small badges) and topic tags (green badges)
- Engagement score (large blue number)
- **"Inspire Pipeline"** button - Uses this specific example as inspiration for a new content generation run
- Inspiration status indicator (shows if a pipeline is running from this example)

#### 3.4.3 Relearning Review Section

- **Summary cards** showing: Total feedback items, Approved proposals, Pending proposals (with counts as large numbers)
- **"Evaluate Now"** button - Triggers the AI to evaluate accumulated feedback and propose system improvements

**Before/After Comparison Panel:**
When proposals are generated, each one includes a side-by-side comparison:
- **Left column: "Before"** - The current state (template, voice setting, or generated example)
- **Right column: "After"** - The proposed change
- Changes are highlighted with diff coloring (green = added, red = removed)
- **Version history list** below each proposal - Timestamps of previous changes to this element, each clickable to see that version's state
- **"Rollback"** button per version - Reverts to that earlier version

**Pending proposals list** - Each proposal shown as a card with:
  - Description and type
  - Before/after diff (as described above)
  - Details (truncated with expand)
  - **"Approve"** (green) and **"Reject"** (red) buttons

#### 3.4.4 Low-Confidence Examples

If any extracted examples have questionable data quality:
- Yellow-bordered section titled "Low-Confidence Examples (N)"
- Warning text: "These posts have low engagement confidence or OCR quality. Review and update manually."
- List of flagged posts showing first 80 characters, confidence score, and a "Review" badge

---

### 3.5 Voice Profile

**Purpose:** Define and fine-tune the brand's writing voice. The AI uses these profiles to match the founder's tone, vocabulary, and style.

#### 3.5.1 Founder Voice Profile Cards

Each profile card contains:

- **Header:** "Profile from: [source document names]" + **"Edit Profile"** button
- **Tone Range Sliders** - Interactive sliders (0-10) for each tone axis (e.g. formal vs casual, serious vs playful). Moving a slider updates the value in real time and saves immediately.
- **Humor Type** - Bold text showing the detected humor style
- **Edit section** (hidden by default, toggles on click):
  - Textarea: "Values & Beliefs (one per line)"
  - Textarea: "Metaphor Families (one per line)"
  - Textarea: "Taboos - things to NEVER say (one per line)"
  - Textarea: "Recurring Themes (one per line)"
  - **"Save Changes"** button
- **Read-only display** (after saving):
  - **Core Values** - Tag badges (shows up to 8, with "+N more" overflow)
  - **Metaphor Families** - Tag badges
  - **Taboos** - Red tag badges (up to 6, "+N more")
  - **Signature Phrases** - Purple tag badges (up to 10, "+N more")
- **Timestamp** - Small dim text showing when the profile was created

#### 3.5.2 Founder Source Material Upload

A dedicated section for ingesting the founder's personal writing that forms the voice foundation layer. This is distinct from the creator corpus - it represents the founder's authentic voice from long-form content.

- **Upload area** - "Upload founder source material (books, transcripts, interviews)"
- **Accepted formats** - PDF (books), TXT (transcripts), DOCX (written content)
- **Uploaded materials list** - Each item shows:
  - Filename and type badge (Book, Transcript, Interview)
  - Upload date
  - Processing status: Pending, Analyzing, Complete
  - **"Remove"** button
- **Processing status** - While analyzing, shows: "Extracting voice patterns from [filename]..." with a progress indicator
- **Relationship note** - Small explanatory text: "This material anchors the AI's voice. Creator profiles add style influences on top of this foundation."

---

### 3.6 Creators

**Purpose:** Manage the creator profiles that influence the AI's content style. Each creator represents a voice the system has learned from, with adjustable influence weights.

#### 3.6.1 Creator Cards Grid (responsive, minimum card width 280px)

Each creator card shows:

- **Creator name** (large text)
- **Influence weight** (large blue percentage number, right-aligned)
- **Influence weight slider** (0-100%) - Dragging updates the percentage in real time and saves on release
- **Style notes** - Italic dim text (if available)
- **Top patterns** - Small blue tag badges
- **Voice axes chart** (if analyzed) - Horizontal bar chart showing each voice axis:
  - Axis name (e.g. "Formal", "Analytical") on the left
  - Colored bar showing the value
  - Numeric value on the right
- **Or "Analyze Voice from Posts" button** (if not yet analyzed) - Triggers voice analysis

**Management controls** (bottom of each card, in a bordered section):
- **Anti-clone markers** - Red badges showing phrases the AI should never copy verbatim from this creator. **"Edit"** button opens a prompt to modify the list.
- **Angle preferences** - One button per content angle type. Red background = excluded (this creator's style won't be used for that angle). Gray = included. Clicking toggles between included/excluded. Excluded angles show an "X" badge.

#### 3.6.2 Competitor Overlap Alerts

A section below the creator cards grid (or as a notification type):

- **Title:** "Source Creator Overlap Alerts"
- When a tracked source creator publishes content on the same topic as a scheduled or planned TCE package, an alert appears:
  - **Creator name** who posted
  - **Their topic** (brief summary)
  - **Conflicting TCE package** - Which day and topic overlaps
  - **Actions:**
    - **"Dismiss"** - Acknowledge and continue with the plan
    - **"Adjust Plan"** - Navigates to the Week Planner to modify the overlapping day
    - **"Flag Package"** - Marks the package as needing differentiation review
- These alerts also appear in the global Notifications bell dropdown

---

### 3.7 Agents

**Purpose:** Choose which AI model each agent uses. This is a cost-vs-quality control panel.

#### 3.7.1 Agent Model Selection

Instructional text at top: "Change which LLM model each agent uses. Changes take effect immediately (no restart needed)."

Each agent displayed as a row:
- **Agent name** (left, large)
- **Agent type** (small dim text below name)
- **Model selection buttons** (right side) - Three buttons per agent:
  - **Haiku** (green accent) - Cheapest, fastest. Tooltip shows pricing.
  - **Sonnet** (indigo accent) - Mid-tier. Tooltip shows pricing.
  - **Opus** (amber accent) - Most capable, most expensive. Tooltip shows pricing.
  - The active model has a filled/colored background. Inactive models are gray. Clicking switches the model instantly.

**Model cost reference card** at the bottom showing all three models with their per-token pricing for quick comparison.

---

### 3.8 Costs

**Purpose:** Monitor AI spending with budgets, trends, breakdowns, and optimization suggestions.

#### 3.8.1 Top Summary Cards (4-column grid)

1. **Today** - Large dollar amount with color coding (green = under budget, yellow = approaching limit, red = over budget). Shows budget cap, percentage used, and a progress bar.
2. **This Month** - Same layout as Today, with monthly figures.
3. **Avg Cost/Post** - Dollar amount per content package, plus the number of runs and the min-max range.
4. **Total Spent (30d)** - Dollar amount and total pipeline runs in the last 30 days.

#### 3.8.2 Cost Trend Chart

A line graph showing daily costs over the past 14 days:
- Y-axis: dollar amounts with grid lines
- X-axis: dates (labeled every 3rd day)
- Hovering over a data point shows the exact date and cost

#### 3.8.3 Agent Cost Breakdown Table

A table showing today's costs per agent:
- Columns: Agent name, Cost ($), Input Tokens, Output Tokens, Calls
- Bold total row at the bottom (green-highlighted)
- **Model fallback entries** - If any agent used a fallback model, the row shows a yellow "Fallback" indicator with the substituted model name

#### 3.8.4 Model Distribution Cards (last 30 days)

One card per AI model showing:
- Model name with colored dot
- Total cost (colored by model tier)
- Percentage of total spending
- Call count and token breakdown

#### 3.8.5 Cache & Batch Efficiency Metrics

- **Cache Hit Rate** - A percentage gauge or time-series mini-chart showing the proportion of prompts served from cache vs. fresh AI calls. Higher = more savings. Shows the dollar amount saved by caching.
- **Batch API Utilization** - Percentage of eligible calls sent as batch (cheaper, slightly delayed) vs. real-time. Shows estimated savings from batching.

#### 3.8.6 Optimization Recommendations

- **Savings banner** at top: "Potential savings: $X.XX" (green)
- List of recommendations, each showing:
  - **Type badge** - "Model Downgrade" (blue), "Cache Improvement" (green), or "Batch API" (purple)
  - **Recommendation text** explaining what to change
  - **Details** (agent name, current model, cache rate)
  - **Savings amount** (large green number)

#### 3.8.7 Recent Pipeline Runs Table

Columns: Run ID (truncated), Workflow type, Status (colored badge), Day, Start time, Error (if any), Actions.
- Status colors: green = completed, red = failed, blue = running
- **"Resume"** button for failed runs
- **Fallback flag** - Yellow indicator if fallback models were used during this run
- Shows last 10 runs

---

### 3.9 Analytics

**Purpose:** Measure content quality, track feedback patterns, and run experiments.

#### 3.9.1 Summary Cards (4-column grid)

1. **Packages** - Total count + approved/draft/rejected breakdown
2. **Pipeline Runs** - Total count + successful/failed breakdown
3. **Feedback Submitted** - Total operator reviews
4. **Learning Events** - Total data points fed back into the system

#### 3.9.2 Recent Packages Table

Columns: Date, Status (colored), CTA keyword, QA Score (large number or dash), Feedback status. Last 15 packages shown.

#### 3.9.3 Feedback Tag Distribution

Colored pills showing how often each feedback tag has been used. Positive tags in green, negative tags in yellow/orange. Gives a quick visual sense of recurring quality issues.

#### 3.9.4 Voice Learning Section

- **If the operator has submitted revised copies:** Shows summary cards (revised copies count, Facebook posts edited, LinkedIn posts edited) plus an explanation of how revisions improve future output.
- **If no revisions yet:** Empty state message: "No revised copies submitted yet. Use the 'Submit Revised Copy' button on approved packages to teach the system your voice."

#### 3.9.5 Best CTAs Table

Columns: Keyword, Uses, Approved count, Approval Rate (%).
- Rate color coded: green >=70%, yellow >=40%, red <40%
- Top 10 CTAs by usage

#### 3.9.6 QA Score Distribution

Summary cards: Average score, Pass count (7+, green), Conditional (5-7, yellow), Fail (<5, red).

**QA Failure Breakdown** (if failures exist): Horizontal bar chart showing which quality dimensions fail most often, with count on the right.

#### 3.9.7 A/B Experiments

- **"New Experiment"** button (primary)
- Experiment list showing: name, status badge (active/completed/draft), description, type (hook variant, CTA variant, post structure, image style), variants count, and per-variant results (approval rates)

#### 3.9.8 DM Fulfillment Log

A management interface for tracking DM delivery:

- **Filter controls:**
  - Status filter: All / Pending / Sent / Failed (toggle buttons)
  - CTA keyword filter: Dropdown of active CTA keywords
- **Fulfillment table:**
  - Columns: Date, CTA Keyword, Trigger, Status (colored badge), Recipient count, Actions
  - Status colors: green = sent, yellow = pending, red = failed
  - Expandable rows showing per-recipient delivery details
- **Actions per row:**
  - **"Retry"** button (for failed DMs) - Re-attempts delivery
  - **"Mark as Sent"** button (for pending DMs) - Manually confirms delivery
  - **"View Details"** button - Expands the full DM flow that was sent
- **Empty state:** "No DM fulfillment logs yet. DM flows are generated by the CTA Agent during pipeline runs."

---

### 3.10 Templates

**Purpose:** Browse and manage the library of content structure templates that the AI uses to generate posts.

#### 3.10.1 Filter Controls

- **"All (N)"** button (shows total count)
- One filter button per template family (with count)
- **"Enrich from Corpus"** button (green, right side) - Triggers AI enrichment of templates using corpus data

**Enrichment progress** (appears while running): "Enrichment running... Phase X/4: [detail]"

#### 3.10.2 Templates Grid (responsive, minimum card width 280px)

Each template card shows:
- **Template name** (header)
- **Status badge**: active (green), locked (yellow), banned (red)
- **Family** (accent colored text)
- **Best For** (dim text)
- **Hook Formula** (green label + formula text)
- **Body Formula** (blue label + truncated text)
- **Platform Fit** (if available)
- **Proof Requirements** (accent label + text)
- **CTA Compatibility** (small blue pills)
- **Visual Compatibility** (small blue pills)
- **Tone Profile** (key-value pairs, max 5 shown)
- **Risk Notes** (yellow text, if any)
- **Anti-Patterns** (red text, if any)
- **Median Score** with sample count, confidence level, and creator diversity
- **Action buttons:**
  - **"Lock" / "Unlock"** - Prevents or allows the AI from modifying this template
  - **"Ban"** (red) - Removes the template from active use

---

### 3.11 Prompts

**Purpose:** View and manage the AI prompts used by each agent. Supports version history, comparison, and rollback.

#### 3.11.1 Agent Cards

One card per agent showing:
- **Agent name** (large)
- **Current model** tag (right side)
- **"View Prompt Versions"** button - Toggles expansion of version history

#### 3.11.2 Prompt Versions (expanded view)

For each version:
- **Version label** (e.g. "v1 (active)" or "v2")
- **Status indicator** (active or inactive)
- **Prompt text preview** - First 500 characters in a monospace, scrollable box (max height ~100px)
- **"Compare"** button - Opens a new window with side-by-side diff (left = active version in green header, right = selected version in yellow header, both showing full prompt text in monospace)
- **"Rollback to this"** button - Reverts the agent to use this prompt version

---

### 3.12 Settings

**Purpose:** Configure global preferences, budgets, integrations, and system scheduling.

#### 3.12.1 Platform Publishing

Checkboxes to enable/disable publishing to each platform (Facebook, LinkedIn, etc.).

#### 3.12.2 Budget & Costs

Two number inputs in a 2-column layout:
- "Daily Budget Cap (USD)" (step: $0.50)
- "Monthly Budget Alert (USD)" (step: $5.00)
- **"Save Budget Settings"** button

#### 3.12.3 API Keys Status

Read-only list showing connection status for each external service:
- Anthropic API - "Configured" (green)
- Image Generator - "Configured" (green)
- Search API - "Configured" (green)
- Email Service - "Optional" (dim)
- Note: "API keys are managed via environment variables on the server."

#### 3.12.4 Target Audience

A textarea for describing the primary audience:
- Placeholder: "e.g. B2B agency owners, 10-50 employees, interested in AI adoption..."
- **"Save"** button

#### 3.12.5 Engagement Scorer Weights

Four sliders (0-100%) controlling how the quality scorer weighs different engagement signals:
- Comments weight
- Shares weight
- Reactions weight
- Saves weight
- **"Save Scorer Weights"** button

#### 3.12.6 Scheduler Management

Controls for the automated pipeline scheduler:

- **Scheduler status** - "Running" (green) or "Stopped" (red)
- **Start / Stop toggle** - Turns automated scheduling on or off
- **Next scheduled run** - Date and time of the next automatic pipeline run
- **Last run timestamp** - When the scheduler last triggered a pipeline
- **"Trigger Now"** button - Manually triggers an immediate pipeline run outside the schedule
- **Schedule configuration** - Displays the current schedule pattern (e.g. "Daily at 06:00 UTC, Mon-Fri")

#### 3.12.7 Humanitarian Sensitivity Policy

- **Current policy status** - "Active" (green) with the threshold score displayed
- **Override log** - A read-only table showing all past humanitarian gate overrides:
  - Date, package ID, operator name, override justification text
  - This log cannot be edited or deleted - it serves as a permanent audit trail
- **Policy note** - "When content triggers the humanitarian sensitivity gate, the operator must provide a written justification to override. All overrides are permanently logged."

---

### 3.13 Chat (AI Assistant)

**Purpose:** A conversational interface where the operator can ask questions about their content pipeline, costs, packages, or quality metrics.

#### 3.13.1 Messages Panel

A scrollable conversation view (minimum height ~500px):
- **User messages** - Right-aligned, indigo background, max width 80%
- **Assistant messages** - Left-aligned, dark background, max width 80%
- **Empty state:** "Ask me anything about your content pipeline. Try: 'Show today's package' or 'Why did QA fail?' or 'What's my cost this week?'"

#### 3.13.2 Input Area

- Text input field spanning most of the width
- **"Send"** button (blue)
- Enter key submits the message
- **Typing indicator:** "Thinking..." appears while waiting for a response

---

### 3.14 Trends

**Purpose:** View and manage trend candidates discovered by the Trend Scout agent. Trends feed into the weekly planning process as topic inspiration.

#### 3.14.1 Trend Scout Controls

- **"Run Trend Scout"** button (primary) - Manually triggers a trend discovery scan
- **Last scan timestamp** - "Last scanned: [date/time]"
- **Scan progress** (appears while running) - Spinner with live status: "Scanning web sources...", "Analyzing social signals...", "Scoring relevance..."

#### 3.14.2 Trend Candidates List

Each trend shown as a card:
- **Topic name** (large text)
- **Relevance score** - Color-coded badge (green = high relevance, yellow = medium, red = low)
- **Source URLs** - Clickable links to the original sources where this trend was discovered
- **Suggested angle** - Which content angle type fits this trend best (badge)
- **Discovery date** - When the trend was found
- **Actions:**
  - **"Use in Plan"** button (primary) - Seeds this trend as a topic in the Week Planner for an unplanned day
  - **"Dismiss"** button (dim) - Removes this trend from the active list
  - **"Save for Later"** button - Moves to the Topic Queue (see 3.1.8)

#### 3.14.3 Trend History

A collapsible section showing previously dismissed or used trends:
- Table: Date, Topic, Status (Used / Dismissed / Saved), Relevance Score
- **Empty state:** "No trend history yet. Run the Trend Scout to discover content opportunities."

---

### 3.15 Onboarding / Help

**Purpose:** Guide new operators through the system and provide reference material. Accessible from the "?" icon in the header or as a tab.

#### 3.15.1 Quickstart Guide

A step-by-step walkthrough for first-time use:
1. Upload your swipe corpus (link to Corpus tab)
2. Upload founder source material (link to Voice Profile tab)
3. Review your creator profiles (link to Creators tab)
4. Plan your first week (link to Week Planner)
5. Generate and review packages (link to Packages tab)

Each step shows a brief description, a status indicator (done/not done), and a direct link to the relevant tab.

#### 3.15.2 Glossary

An alphabetical list of system terms with plain-language definitions:
- **Angle Type** - The content approach for a given day (e.g. Big Shift Explainer, Tactical Workflow)
- **Buffer Post** - A lighter-weight filler post for lower-bandwidth weeks
- **CTA Keyword** - The call-to-action word readers use to request the weekly guide
- **Hook** - The opening line of a post designed to stop the scroll
- **Package** - A complete set of content for one day (posts, hooks, images, DM flow)
- etc.

#### 3.15.3 Troubleshooting

Common issues and resolutions:
- "Pipeline failed mid-run" - How to resume or retry
- "QA scores are too low" - How to adjust agent models or provide feedback
- "Budget alert triggered" - How to adjust budget caps
- etc.

#### 3.15.4 Agent Roles

A reference showing each AI agent's purpose:
- **Trend Scout** - Discovers trending topics from web and social signals
- **Story Strategist** - Plans the weekly content calendar
- **Platform Writer (FB)** - Writes Facebook-optimized posts
- **Platform Writer (LI)** - Writes LinkedIn-optimized posts
- **QA Agent** - Scores content across 12 quality dimensions
- etc.

---

## 4. Shared Components

### 4.1 AI Feedback Popover

Appears inline below a "Feedback" or "AI Revise" button. Contains:
- A label explaining what to do
- A textarea for writing revision instructions
- **"Cancel"** and **"Revise with AI"** buttons
- Auto-positions to stay within the viewport

### 4.2 Global Search Dropdown

- Appears below the search input in the header
- Maximum height scrollable, shows up to 10 results
- Results span posts, topics, and templates
- Clicking a result navigates to the relevant tab and item

### 4.3 Notifications Dropdown

- Appears below the bell icon
- Shows unread items with timestamps
- Notification types include: pipeline completions, pipeline failures, feedback reminders, competitor overlap alerts, budget warnings, humanitarian gate triggers
- Each item is dismissible
- Badge on the bell icon shows the unread count

### 4.4 Confirmation Dialogs

Standard browser confirmation dialogs for destructive actions (archiving, banning, rejecting, rollback).

### 4.5 New-Window Viewers

Several features open in a new browser tab:
- Corpus example viewer (dark theme, RTL-compatible)
- Prompt comparison (side-by-side layout)
- Package export (raw data view)

### 4.6 Word Diff Panel

Used in the Revised Copy form (3.3.6) and the Relearning Review (3.4.3):
- Side-by-side two-column layout
- Left: original text, Right: modified text
- Word-level diff highlighting: green background = added words, red strikethrough = removed words, gray = unchanged
- Scrollable, synced scroll between columns

### 4.7 Date/Time Picker

Used in Schedule Publish (3.3.5):
- Calendar grid for date selection
- Hour/minute dropdowns or spinners for time
- Timezone display (server timezone)

---

## 5. Data Entities (What the User Sees)

| Entity | What It Is | Where It Appears |
|--------|-----------|------------------|
| **Weekly Plan** | A Mon-Fri plan with topics, angles, a weekly theme, and a CTA keyword | Week Planner |
| **Day Brief** | One day's plan: topic, angle type, thesis, audience, belief shift, status | Week Planner day cards + Plan Review |
| **Content Package** | A complete set of outputs for one day: Facebook post, LinkedIn post, hooks, QA scores, image prompt, DM flow | Packages tab |
| **Hook Variant** | An alternative opening line for a post (3-5 generated per package) | Hooks tab within a package |
| **QA Score** | A numeric quality rating across 12 dimensions with written justifications | QA tab within a package, Analytics |
| **Weekly Guide** | A downloadable DOCX document - the "gift of the week" lead magnet | Packages tab (bottom section), Week Planner overlay |
| **Corpus Document** | An uploaded reference file (DOCX/TXT) the AI learns from, with approval status | Corpus tab |
| **Extracted Example** | A single post extracted from a corpus document with engagement metrics | Corpus example viewer |
| **Voice Profile** | The brand's writing voice: tone ranges, values, taboos, metaphor families | Voice Profile tab |
| **Founder Source Material** | Books, transcripts, interviews that form the voice foundation | Voice Profile tab |
| **Creator Profile** | A content creator whose style influences AI output, with adjustable weight | Creators tab |
| **Template** | A structural pattern for posts (hook formula, body formula, CTA compatibility) | Templates tab |
| **Pipeline Run** | A single execution of the AI pipeline, with step-by-step progress | Generate tab, Costs tab |
| **Feedback** | Operator-submitted quality tags and notes on a package | Package feedback form, Analytics |
| **Revised Copy** | The operator's actual published version of a post, used to teach voice | Packages tab (Submit Revised Copy) |
| **Learning Proposal** | A system-suggested improvement based on accumulated feedback, with before/after diff | Corpus > Relearning Review |
| **A/B Experiment** | A test comparing different content approaches (hooks, CTAs, structure, images) | Analytics tab |
| **DM Flow** | A multi-step direct message sequence triggered by a CTA | DM tab within a package |
| **DM Fulfillment Log** | Delivery tracking for sent DM flows (pending/sent/failed) | Analytics tab |
| **Trend Candidate** | A topic discovered by the Trend Scout with relevance score and sources | Trends tab, Plan Review |
| **Topic Queue Item** | A future topic held in reserve for upcoming weeks | Week Planner |
| **Package Context** | The AI's reasoning - influence weights, evidence, thesis derivation | Context panel within a package |
| **Humanitarian Override** | A permanent audit record when content sensitivity was manually overridden | QA tab, Settings |

---

## 6. States & Empty States

Every section handles these states:

| State | Visual Treatment |
|-------|-----------------|
| **Loading** | Spinner or skeleton placeholder with descriptive text ("Loading packages...", "Fetching costs...") |
| **Empty** | Friendly message explaining what's missing and how to fill it. Example: "No packages yet. Go to Week Planner to plan your week, then hit Generate." |
| **Error** | Red-tinted card or toast with error message. The action that failed can usually be retried. |
| **Success** | Green toast notification auto-dismissing after 3 seconds. |
| **In-progress** | Animated spinner, progress bar, or step indicators with elapsed time. Live-updating text describes what's happening right now (e.g. "Trend scout is researching...", "QA agent scoring post..."). |
| **Flagged** | Yellow or red banner with explanation text. Used for humanitarian sensitivity flags, model fallback warnings, low-confidence examples, and competitor overlap alerts. Requires operator attention before proceeding. |

---

## 7. Theme & Visual Design

### 7.1 Current Color Palette (Dark Theme)

| Token | Value | Usage |
|-------|-------|-------|
| Background | #0f1117 | Page background |
| Card | #1a1d27 | Card and panel backgrounds |
| Border | #2a2d3a | Dividers and card borders |
| Text | #e4e4e7 | Primary text |
| Dim | #9ca3af | Secondary/helper text |
| Accent (Indigo) | #6366f1 | Primary buttons, active states, links |
| Accent Light | #818cf8 | Hover states, secondary accent |
| Green | #22c55e | Success, approved, healthy |
| Red | #ef4444 | Error, rejected, failed |
| Yellow | #eab308 | Warning, pending, caution |
| Blue | #3b82f6 | Info, running, links |
| Teal | #14b8a6 | Scheduled status |

### 7.2 Responsive Breakpoints

| Breakpoint | Behavior |
|------------|----------|
| >900px | Full desktop layout. Week grid: 5 columns. Card grids: 3-4 columns. |
| 600-900px | Tablet layout. Week grid: 3 columns. Card grids: 2 columns. |
| <600px | Mobile layout. Everything stacks to 1 column. |

### 7.3 Typography

All text is rendered in the system font stack (no custom fonts currently loaded). Monospace is used for prompt text, run IDs, and log entries.

---

## 8. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus the global search field |
| `Alt+1` | Switch to Week Planner |
| `Alt+2` | Switch to Generate |
| `Alt+3` | Switch to Packages |
| `Alt+4` | Switch to Corpus |
| `Alt+5` | Switch to Costs |
| `Alt+6` | Switch to Analytics |
| `?` | Show keyboard shortcuts hint |

---

## 9. Key Interaction Patterns

1. **Plan then Generate then Review** - The core workflow is: plan the week (Week Planner) then generate packages (Generate or Week Planner buttons) then review and approve (Packages). The UI should make this three-step flow feel natural and sequential.

2. **Real-time progress everywhere** - Planning, generating, trend scanning, and enriching all show live-updating progress with elapsed timers and step-by-step status. The operator should never wonder "is it still working?"

3. **Inline AI revision** - On any post, the operator can give natural-language feedback and the AI rewrites the content instantly, without leaving the page.

4. **Direct editing** - Separately from AI revision, the operator can toggle any post into a live textarea and make manual edits with real-time word count.

5. **Teach-by-doing** - The system learns from the operator's approvals, rejections, edits, revised copies, and feedback tags. There's no separate "training" step - every interaction is a learning signal. The revised copy workflow with word-level diff is the most powerful teaching tool.

6. **Cost awareness** - Cost information is surfaced in multiple places (Week Planner, Costs tab, Generate tab hints, cache/batch metrics) so the operator always knows what they're spending.

7. **Drag-and-drop reordering** - Day cards in the Week Planner can be reordered by dragging, giving the operator control over the weekly sequence.

8. **Progressive disclosure** - Details are hidden behind expandable sections, "View" buttons, and tabs within cards. The default view shows just enough to make decisions; details are one click away.

9. **Explainability on demand** - Every package has a "Show Context" panel that reveals the AI's reasoning: which creators influenced it, what evidence was used, how the thesis was derived. The operator never has to wonder "why did the AI write this?"

10. **Trend-to-plan pipeline** - Trends discovered by the scout flow directly into planning. The operator can use a trend as a topic with one click, or save it to the topic queue for future weeks.

11. **Permanent audit trail** - Humanitarian overrides, QA score overrides, and model fallback events are all logged permanently and displayed in the UI. The system maintains full accountability.
