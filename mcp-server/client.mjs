#!/usr/bin/env node
/** Workspace-bound client MCP. No owner auth and no publishing tools. */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const base = process.env.TCE_CLIENT_URL?.replace(/\/$/, '');
const token = process.env.TCE_CLIENT_TOKEN;
let origin;
try {
  origin = new URL(base);
} catch {
  console.error('Set TCE_CLIENT_URL to the client studio HTTPS origin.');
  process.exit(1);
}
if (!token || (origin.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(origin.hostname)) || origin.search || origin.hash) {
  console.error('Set a clean HTTPS TCE_CLIENT_URL and a scoped TCE_CLIENT_TOKEN.');
  process.exit(1);
}

async function call(method, path, body) {
  const url = new URL(path, base + '/');
  if (url.origin !== origin.origin) throw new Error('Endpoint outside the client studio');
  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(90000),
  });
  if (!response.ok) throw new Error(`Client studio returned HTTP ${response.status}`);
  return response.json();
}
function reply(value) { return { content: [{ type: 'text', text: JSON.stringify(value) }] }; }
function failure(error) { return { isError: true, content: [{ type: 'text', text: error.message || 'Client studio request failed' }] }; }
function register(server, name, description, inputSchema, execute) {
  server.registerTool(name, { description, inputSchema }, async (args) => {
    try { return reply(await execute(args)); } catch (error) { return failure(error); }
  });
}

const server = new McpServer({ name: 'tce-client', version: '1.0.0' });
register(server, 'list_week', 'Read this client workspace week and selected ideas.', {
  week_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
}, ({ week_start }) => call('GET', `/api/week/${week_start}`));
register(server, 'list_ready_videos', 'List this client workspace recordings and selected edits.', {},
  () => call('GET', '/api/recordings'));
register(server, 'get_export_manifest', 'Get the selected video version, checksum, evidence and private download path.', {
  recording_id: z.string().uuid(),
}, ({ recording_id }) => call('GET', `/api/recordings/${recording_id}/export-manifest`));
register(server, 'request_self_delivery', 'Email the selected video to this signed-in client only. Reuse the same idempotency key on retries.', {
  recording_id: z.string().uuid(),
  idempotency_key: z.string().min(8).max(120),
}, ({ recording_id, idempotency_key }) => call('POST', `/api/recordings/${recording_id}/send-to-self`, { idempotency_key }));
register(server, 'lease_client_job', 'Claim one queued scouting or script job for this client workspace. Use your own Claude Code session to answer its prompt.', {},
  () => call('POST', '/api/jobs/lease'));
register(server, 'complete_client_job', 'Return the finished result for a job you leased. Scouting expects a JSON array; scripting expects plain script text.', {
  job_id: z.string().uuid(),
  lease_token: z.string().min(20),
  output: z.string().min(1).max(40000),
}, ({ job_id, lease_token, output }) => call('POST', `/api/jobs/${job_id}/complete`, { lease_token, output }));
register(server, 'fail_client_job', 'Mark a leased job as needing attention, without including private content in the error code.', {
  job_id: z.string().uuid(),
  lease_token: z.string().min(20),
  error_code: z.string().regex(/^[a-z0-9_]{2,80}$/),
}, ({ job_id, lease_token, error_code }) => call('POST', `/api/jobs/${job_id}/fail`, { lease_token, error_code }));

await server.connect(new StdioServerTransport());
console.error('tce-client MCP connected to a single client studio.');
