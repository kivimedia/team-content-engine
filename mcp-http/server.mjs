#!/usr/bin/env node
/** Remote, workspace-bound MCP over HTTP. No publishing tools or shared token cache. */
import { createMcpExpressApp, requireBearerAuth } from '@modelcontextprotocol/express';
import { toNodeHandler } from '@modelcontextprotocol/node';
import { createMcpHandler, McpServer, OAuthError, OAuthErrorCode } from '@modelcontextprotocol/server';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as z from 'zod/v4';

const api = new URL(process.env.TCE_CLIENT_API_URL || 'http://app:8000');
if (!process.env.TCE_CLIENT_PUBLIC_URL) throw new Error('Set TCE_CLIENT_PUBLIC_URL');
const publicUrl = new URL(process.env.TCE_CLIENT_PUBLIC_URL);
const listenHost = process.env.TCE_MCP_BIND || '0.0.0.0';
const listenPort = Number(process.env.TCE_MCP_PORT || '3000');
if (!['app', '127.0.0.1', 'localhost'].includes(api.hostname)
  || api.protocol !== 'http:' || publicUrl.protocol !== 'https:'
  || publicUrl.username || publicUrl.password || publicUrl.search || publicUrl.hash
  || !Number.isInteger(listenPort) || listenPort < 1 || listenPort > 65535) {
  throw new Error('Set an internal client API, clean HTTPS public URL, and valid MCP port');
}

async function identity(token) {
  let response;
  try {
    response = await fetch(new URL('/auth/me', api), {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    throw new Error('Client identity service is unavailable');
  }
  if (response.status === 401 || response.status === 403) {
    throw new OAuthError(OAuthErrorCode.InvalidToken, 'Client grant is unavailable');
  }
  if (!response.ok) throw new Error('Client identity service is unavailable');
  const profile = await response.json();
  const expiresAt = Date.parse(profile.token_expires_at || '') / 1000;
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now() / 1000
    || !profile.workspace_id || !Array.isArray(profile.scopes)) {
    throw new OAuthError(OAuthErrorCode.InvalidToken, 'Client grant is unavailable');
  }
  return { token, clientId: profile.workspace_id, scopes: profile.scopes, expiresAt };
}

async function call(token, method, path, body) {
  const url = new URL(path, api);
  if (url.origin !== api.origin) throw new Error('Endpoint outside the client studio');
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

function register(server, token, name, description, inputSchema, execute) {
  server.registerTool(name, { description, inputSchema: z.object(inputSchema) }, async (args) => {
    try {
      const value = await execute(args);
      return { content: [{ type: 'text', text: JSON.stringify(value) }] };
    } catch (error) {
      return { isError: true, content: [{ type: 'text', text: error.message || 'Client request failed' }] };
    }
  });
}

export function buildServer({ authInfo }) {
  const server = new McpServer({ name: 'tce-client', version: '1.0.0' });
  const token = authInfo?.token;
  const scopes = new Set(authInfo?.scopes || []);
  if (!token) return server;
  if (scopes.has('read')) {
    register(server, token, 'list_week', 'Read this client workspace week and selected ideas.', {
      week_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    }, ({ week_start }) => call(token, 'GET', `/api/week/${week_start}`));
    register(server, token, 'list_ready_videos', 'List this client workspace recordings and selected edits.', {},
      () => call(token, 'GET', '/api/recordings'));
    register(server, token, 'get_export_manifest', 'Get the selected video version, checksum and private download path.', {
      recording_id: z.string().uuid(),
    }, ({ recording_id }) => call(token, 'GET', `/api/recordings/${recording_id}/export-manifest`));
  }
  if (scopes.has('deliver')) {
    register(server, token, 'request_self_delivery', 'Email the selected video to this signed-in client only. Reuse the same idempotency key on retries.', {
      recording_id: z.string().uuid(),
      idempotency_key: z.string().min(8).max(120),
    }, ({ recording_id, idempotency_key }) => call(token, 'POST', `/api/recordings/${recording_id}/send-to-self`, { idempotency_key }));
  }
  if (scopes.has('worker')) {
    register(server, token, 'lease_client_job', 'Claim a queued scouting or script job for this client workspace.', {},
      () => call(token, 'POST', '/api/jobs/lease'));
    register(server, token, 'complete_client_job', 'Return a result for a job you leased. Scouting expects JSON; scripting expects text.', {
      job_id: z.string().uuid(), lease_token: z.string().min(20), output: z.string().min(1).max(40000),
    }, ({ job_id, lease_token, output }) => call(token, 'POST', `/api/jobs/${job_id}/complete`, { lease_token, output }));
    register(server, token, 'fail_client_job', 'Mark a leased job as needing attention with a safe error code.', {
      job_id: z.string().uuid(), lease_token: z.string().min(20),
      error_code: z.string().regex(/^[a-z0-9_]{2,80}$/),
    }, ({ job_id, lease_token, error_code }) => call(token, 'POST', `/api/jobs/${job_id}/fail`, { lease_token, error_code }));
  }
  return server;
}

export function createHttpApp() {
  const verifier = { verifyAccessToken: identity };
  const auth = requireBearerAuth({ verifier });
  const handler = createMcpHandler(buildServer);
  const node = toNodeHandler(handler);
  const host = publicUrl.hostname;
  const app = createMcpExpressApp({
    host: listenHost,
    allowedHosts: [host, 'localhost', '127.0.0.1'],
    allowedOrigins: [host, 'localhost', '127.0.0.1'],
  });
  app.get('/healthz', (_req, res) => res.json({ status: 'ok' }));
  app.all('/mcp', auth, (req, res) => void node(req, res, req.body));
  return { app, handler };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const { app, handler } = createHttpApp();
  const server = app.listen(listenPort, listenHost, () => {
    console.error(`TCE client MCP listening on ${listenHost}:${listenPort}`);
  });
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, async () => {
      server.close();
      await handler.close();
      process.exit(0);
    });
  }
}
