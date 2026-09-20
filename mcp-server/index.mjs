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
 * Env:
 *   TCE_BASIC_USER  required, the editor login (ziv)
 *   TCE_BASIC_PASS  required, that login's password
 *   TCE_API_BASE    override the route (default https://bot.kivimedia.co/tce)
 *
 * Both TCE routes strip Authorization at nginx and inject the private editor
 * key themselves, so basic auth is the whole credential this server needs. The
 * private key never leaves the server's .env.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { DEFAULT_BASE, makeCaller, registerTools, SERVER_NAME, SERVER_VERSION } from './tools.mjs';

const user = process.env.TCE_BASIC_USER;
const password = process.env.TCE_BASIC_PASS;

if (!user || !password) {
  // Said now rather than at the first tool call: a missing login costs a whole
  // session of confusing 401s if it is only discovered in use.
  console.error(
    'tce-mcp: set TCE_BASIC_USER and TCE_BASIC_PASS (the TCE editor login). '
      + 'Re-add the connector with --env "TCE_BASIC_USER=ziv" --env "TCE_BASIC_PASS=...".',
  );
  process.exit(1);
}

const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });
const { families, tools } = await registerTools(server, makeCaller(DEFAULT_BASE, user, password));

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(
  `tce-mcp ${SERVER_VERSION}: connected (stdio) to ${DEFAULT_BASE}. `
    + `Families: ${families.join(', ')}. ${tools.length} tools.`,
);
