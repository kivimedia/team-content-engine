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
