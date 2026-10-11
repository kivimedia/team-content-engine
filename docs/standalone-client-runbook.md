# TCE client studio runbook

The client service starts `tce.standalone.app:app`. It does not mount the owner
application or any publishing route. It uses a separate database and private media
volume. Keep its public address behind HTTPS. The container listens on local port
8765 for a reverse proxy.

## Prepare a new environment

1. Copy `.env.standalone.example` to the ignored `.env.standalone`. Fill the
   database URL, an independent random 32-byte AES key encoded as base64, an
   HTTPS public origin, a verified sender address, and a Resend API key. Back up
   the encryption key separately. Losing it makes client provider keys unreadable.
2. Run `docker compose --env-file .env.standalone -f compose.standalone.yml up -d --build`.
   The one-shot migration container must finish successfully before the app starts.
   The database is fresh and has no owner data. Do not point this at the owner TCE
   database or file volume.
3. Read `GET /healthz` through the HTTPS proxy and check that `/app` loads its
   CSS and JavaScript. Confirm the proxy forwards HTTPS correctly and limits upload
   size to at least 500 MB.
4. Back up the database and media volume before inviting a client. Exercise a
   restore on an isolated copy. Test account denial, video playback and download
   from both a phone and desktop browser.

The app intentionally has no shared Anthropic or OpenAI credential. Each client
enters their own key in Settings. Web idea generation needs a client-owned Anthropic
API key. Claude Code terminal mode can use that client's own subscription without
passing subscription tokens through this web app. OpenAI GPT-Live 1 requires the
client's OpenAI API key. Failed verification stays visible; it never switches to an
owner-paid key.

## Invite and onboard a client

From the running app container, run:

`python -m tce.standalone.provision --email client@example.com --name "Client Studio" --slug client-studio --timezone America/New_York`

The command sends a one-use link to that email via Resend. It never prints the
link or a password. The link expires in seven days. Repeating the command for an
unverified account replaces its prior link. Run it only when that client invitation
has been authorized. After accepting it, the client sets a password and chooses
three source lanes with per-lane filters and comments. They can revise or restore
settings, pause sources, remove provider keys, and deactivate uploaded material.

For Ken's pilot, use a real Ken-owned email and agreed domain only after the
isolated DB, HTTPS, backup, sender and provider keys are verified. Do not import
global owner records by guesswork. Map owner records on a copy before any import.

## Terminal access

In Settings, create a token with the required scopes. The raw token appears once.
Store it in the client's terminal secret store. Revoke it from `DELETE /api/tokens/{id}`
when no longer needed. Every request uses `Authorization: Bearer $TCE_CLIENT_TOKEN`.
The token is bound to one account and one workspace. A forged `X-Workspace-Id`
header is rejected. The terminal can use these routes:

| Action | Method and path | Scope |
| --- | --- | --- |
| Read settings | `GET /api/config` | read |
| Read ideas | `GET /api/ideas` | read |
| Add an idea | `POST /api/ideas` | write |
| Read the week | `GET /api/week/YYYY-MM-DD` | read |
| Read recordings | `GET /api/recordings` | read |
| Download selected video | `GET /api/recordings/{id}/video?version=selected` | read |
| Read edit versions | `GET /api/recordings/{id}/renders` | read |
| Get selected export manifest | `GET /api/recordings/{id}/export-manifest` | export |
| Send video to verified self | `POST /api/recordings/{id}/send-to-self` | deliver |

`POST /api/recordings/{id}/send-to-self` requires a unique
`{"idempotency_key":"client-generated-unique-value"}` body. It always uses the
account's verified email and the currently selected edit unless a render ID is
given. Failed delivery does not change the video. Videos over 25 MB are sent as a
private app link, so the recipient signs in before downloading. The app has no
social publish or schedule route. Claude Code can take the downloaded file into
a separate publishing tool under that tool's own permissions.

The export manifest identifies the selected render and its SHA-256 checksum,
idea, source and recorded script version. Captions, transcript and suggested
post copy are marked unavailable until a client supplies or generates them;
the manifest never invents those assets.

For MCP, install `mcp-server` dependencies from its lockfile and register
`node mcp-server/client.mjs` as a stdio MCP command in Claude Code. Supply
`TCE_CLIENT_URL` and `TCE_CLIENT_TOKEN` through that client's process
environment or secret manager. Do not put the token in a command line or a
committed MCP configuration. This separate entry point exposes only
`list_week`, `list_ready_videos`, `get_export_manifest`, and
`request_self_delivery`. Never point a client at the legacy `index.mjs` MCP
server, which is for the owner runtime.

## Operations and rollback

Audit active tokens in Settings and revoke any unused token. Pause a source in
Settings to stop new collection; its prior idea and script versions remain.
Disable invitation command access and stop the standalone container to freeze
the pilot. Roll back the app image if necessary, keeping the DB and media volumes.
Never delete client material as a rollback shortcut. Rotate Resend and provider
keys in their own systems; client keys can then be replaced in Settings.

Before client launch, verify two independent client accounts cannot read or alter
each other's settings, sources, recordings, tokens or deliveries. Run an actual
Fathom, GitHub, research, voice, recording, video email and terminal export pass
using consented test data. Those provider and device checks require real accounts
and devices; mocked tests alone do not establish them.
