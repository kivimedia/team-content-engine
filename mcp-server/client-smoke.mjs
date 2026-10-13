#!/usr/bin/env node
/** Local protocol check for the client-only MCP entry point. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const token = randomBytes(32).toString('hex');
const http = createServer((request, response) => {
  assert.equal(request.headers.authorization, `Bearer ${token}`);
  if (request.url === '/api/recordings' && request.method === 'GET') {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end('[]');
  } else if (request.url === '/api/jobs/lease' && request.method === 'POST') {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end('{"job":null}');
  } else {
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end('{}');
  }
});
await new Promise(resolve => http.listen(0, '127.0.0.1', resolve));
const address = http.address();
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [fileURLToPath(new URL('./client.mjs', import.meta.url))],
  env: {
    ...process.env,
    TCE_CLIENT_URL: `http://127.0.0.1:${address.port}`,
    TCE_CLIENT_TOKEN: token,
  },
});
const client = new Client({ name: 'tce-client-smoke', version: '1.0.0' });
try {
  await client.connect(transport);
  const listed = await client.listTools();
  assert.deepEqual(listed.tools.map(tool => tool.name).sort(), [
    'complete_client_job', 'fail_client_job', 'get_export_manifest', 'lease_client_job',
    'list_ready_videos', 'list_week', 'request_self_delivery',
  ]);
  const videos = await client.callTool({ name: 'list_ready_videos', arguments: {} });
  assert.equal(videos.isError, undefined);
  assert.deepEqual(JSON.parse(videos.content[0].text), []);
  const lease = await client.callTool({ name: 'lease_client_job', arguments: {} });
  assert.deepEqual(JSON.parse(lease.content[0].text), { job: null });
  console.log('Client MCP exposes seven scoped tools, including workspace-bound worker jobs.');
} finally {
  await client.close();
  await new Promise(resolve => http.close(resolve));
}
