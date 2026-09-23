# TCE Terminal Mode

The Team Content Engine as MCP tools, so the engine can be asked about the
week, the ideas, the scripts and the machinery in plain English from any
session - without SSH, a psql prompt or a runbook.

## Install (once, per machine)

```
cd mcp-server && npm install
claude mcp add tce --scope user \
  --env "TCE_BASIC_USER=ziv" --env "TCE_BASIC_PASS=<the editor password>" \
  -- node "E:/FromC/projects/Team Content Engine/mcp-server/index.mjs"
```

`--scope user`, not the default: a local-scoped connector exists only in
sessions started inside one folder, and everywhere else the commands still
appear while the tools are silently missing.

The password is the TCE editor login (memory: `tce-editor-creds.md`). Both TCE
routes strip `Authorization` at nginx and inject the private editor key
themselves, so basic auth is the entire credential this server needs, and the
private key never leaves the server's `.env`.

## Use

- `/tce:briefing` - where the engine stands.
- `/tce:run <anything>` - the router.

## Tools

| Tool | What it answers |
|---|---|
| `tce_briefing` | Everything at once: queue, runs, schedules, workers |
| `tce_ideas` | The week's ideas with rank and status |
| `tce_script` | One script in full, with its alternative openings |
| `tce_approve` | Put an idea in the recording queue, or reject it |
| `tce_choose_opening` | Switch a script to another opening |
| `tce_produce_now` | Produce this week's scripts (dedupes by hour) |
| `tce_request` | "Make a script from the call with X", with source choice |
| `tce_runs` / `tce_run` | What is running and what each step did |
| `tce_resume_run` | Unstick a parked or stopped run |
| `tce_health` | API, cron tick, schedules, workers |
| `tce_schedule` | Turn a schedule on or off, move its time |
| `tce_evidence` | What was collected for a window, and read |

## The voice agent (on the VPS)

The `voice` family is the hands of the Opus brain on a TCE voice call. It runs
on the VPS next to the API, so it skips nginx and sends the private key itself:

```
TCE_API_BASE=http://127.0.0.1:8200 \
TCE_PRIVATE_KEY=<TCE_PRIVATE_ACCESS_KEY from the server .env> \
TCE_WORKSPACE_ID=<TCE_EDITOR_DEFAULT_WORKSPACE_ID from the server .env> \
TCE_MCP_FAMILIES=voice \
node /home/ziv/team-content-engine/mcp-server/index.mjs
```

`TCE_PRIVATE_KEY` wins over basic auth when both are set. `TCE_WORKSPACE_ID` is
optional (the API falls back to its editor workspace). `TCE_MCP_FAMILIES=voice`
keeps the call's tool list to the 13 it needs.

| Tool | What it does |
|---|---|
| `tce_week` | This week's list with script states, and what needs a decision |
| `tce_topic` | One topic: brief, opening, numbered points, lines and opening options |
| `tce_edit` | Change "point 3", "the opening", a brief block - applied at once, undoable |
| `tce_decide` | this_week (approve) / discuss / later / away |
| `tce_put_away` / `tce_restore_idea` | Put an idea away, bring it back |
| `tce_choose_hook` | Use opening option N |
| `tce_reorder_week` | first / up / down / last / reserve / remove / position N |
| `tce_undo` | The last change in this call, or one by id |
| `tce_write_script` / `tce_more_hooks` / `tce_research` | Start a background job |
| `tce_jobs` | Which of those finished, so the call can say so |

Every write is recorded as `voice` and listed on Today under "Changes by voice".

## Check it

```
TCE_BASIC_USER=ziv TCE_BASIC_PASS=... npm run smoke
```

Every read tool runs against the live engine and prints the first lines of its
answer; `--write` also starts a (deduplicated) run. A tool that cannot reach
TCE says so rather than reporting an empty engine.

## Adding a tool

One file per family in `tools/`, exporting `FAMILY` and `register(server, call,
helpers)`. Never build a `fetch` of your own: `call` carries the identity, and
a family that throws on load is skipped rather than taking the others down.
