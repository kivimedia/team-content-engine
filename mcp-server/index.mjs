#!/usr/bin/env node
/**
 * tce-mcp - Terminal Mode for the Team Content Engine.
 *
 * A local (stdio) MCP server that wraps TCE's private API as tools, so the
 * engine can be asked about the week, the ideas, the scripts and the machinery
 * in plain English from any session, without SSH and without a runbook.
 *
 * Setup:
 *   1. npm install, in this folder.
 *   2. claude mcp add tce --scope user \
 *        --env "TCE_BASIC_USER=ziv" --env "TCE_BASIC_PASS=..." \
 *        -- node "E:/FromC/projects/Team Content Engine/mcp-server/index.mjs"
 *
 * 🚨 --scope user, NOT the default. A local-scoped connector only exists in
 * sessions whose working directory is inside one folder; everywhere else the
 * tools are simply missing while everything still looks installed.
 *
 * Env (the PC):
 *   TCE_BASIC_USER  the editor login (ziv)
 *   TCE_BASIC_PASS  that login's password
 *   TCE_API_BASE    override the route (default https://bot.kivimedia.co/tce)
 *
 * Env (the VPS, e.g. the voice agent's brain), used instead when set:
 *   TCE_PRIVATE_KEY   the API's private access key, sent as a bearer
 *   TCE_WORKSPACE_ID  the workspace (optional; the API's editor workspace otherwise)
 *   TCE_API_BASE      http://127.0.0.1:8200, the API itself, not the nginx route
 *   TCE_MCP_FAMILIES  optional comma list to load only some families (e.g. "voice")
 *
 * Both public TCE routes strip Authorization at nginx and inject the private
 * editor key themselves, so on the PC basic auth is the whole credential. The
 * private key is only ever used on the VPS itself, against 127.0.0.1, and it
 * comes from that box's environment, never from a file in this repo.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import {
  DEFAULT_BASE, identityFromEnv, makeCaller, registerTools, SERVER_NAME, SERVER_VERSION,
} from './tools.mjs';

const identity = identityFromEnv();

if (!identity.ok) {
  // Said now rather than at the first tool call: a missing login costs a whole
  // session of confusing 401s if it is only discovered in use.
  console.error(
    'tce-mcp: set TCE_BASIC_USER and TCE_BASIC_PASS (the TCE editor login), '
      + 'or on the VPS TCE_PRIVATE_KEY with TCE_API_BASE=http://127.0.0.1:8200. '
      + 'Re-add the connector with --env "TCE_BASIC_USER=ziv" --env "TCE_BASIC_PASS=...".',
  );
  process.exit(1);
}

const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });
const { families, tools } = await registerTools(server, makeCaller(DEFAULT_BASE, identity.auth));

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(
  `tce-mcp ${SERVER_VERSION}: connected (stdio) to ${DEFAULT_BASE} as ${identity.mode}. `
    + `Families: ${families.join(', ')}. ${tools.length} tools.`,
);
