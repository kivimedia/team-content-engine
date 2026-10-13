import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';

test('remote MCP gates tools by a fresh revocable client grant', async t => {
  let revoked = false;
  const upstream = [];
  const fakeApi = createServer((req, res) => {
    upstream.push({ path: req.url, bearer: req.headers.authorization });
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/auth/me') {
      if (revoked || !['Bearer read-token', 'Bearer worker-token'].includes(req.headers.authorization)) {
        res.writeHead(401).end(JSON.stringify({ detail: 'revoked' }));
        return;
      }
      res.end(JSON.stringify({
        workspace_id: req.headers.authorization === 'Bearer read-token' ? 'ken' : 'other',
        scopes: req.headers.authorization === 'Bearer read-token' ? ['read'] : ['worker'],
        token_expires_at: new Date(Date.now() + 3600000).toISOString(),
      }));
      return;
    }
    if (req.url === '/api/week/2026-10-12' && req.headers.authorization === 'Bearer read-token') {
      res.end(JSON.stringify({ week_start: '2026-10-12', ideas: [] }));
      return;
    }
    res.writeHead(403).end(JSON.stringify({ detail: 'scope denied' }));
  });
  await new Promise(resolve => fakeApi.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => fakeApi.close(resolve)));
  process.env.TCE_CLIENT_API_URL = `http://127.0.0.1:${fakeApi.address().port}`;
  process.env.TCE_CLIENT_PUBLIC_URL = 'https://tce-clients.example.test';
  process.env.TCE_MCP_BIND = '127.0.0.1';
  const { createHttpApp } = await import('./server.mjs');
  const { app, handler } = createHttpApp();
  const gateway = app.listen(0, '127.0.0.1');
  await new Promise(resolve => gateway.once('listening', resolve));
  t.after(async () => {
    await handler.close();
    await new Promise(resolve => gateway.close(resolve));
  });
  const endpoint = `http://127.0.0.1:${gateway.address().port}/mcp`;
  async function rpc(token, id, method, params, origin) {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(origin ? { Origin: origin } : {}),
      },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, ...(params ? { params } : {}) }),
    });
    return { status: response.status, body: await response.text(), challenge: response.headers.get('www-authenticate') };
  }
  function result(response) {
    const event = response.body.match(/^data: (.*)$/m);
    return JSON.parse(event ? event[1] : response.body);
  }
  assert.equal((await rpc(null, 1, 'tools/list')).status, 401);
  const read = await rpc('read-token', 2, 'tools/list');
  assert.equal(read.status, 200, read.body);
  const readTools = result(read).result.tools.map(tool => tool.name);
  assert.deepEqual(readTools.sort(), ['get_export_manifest', 'list_ready_videos', 'list_week']);
  const worker = await rpc('worker-token', 3, 'tools/list');
  assert.equal(worker.status, 200, worker.body);
  const workerTools = result(worker).result.tools.map(tool => tool.name);
  assert.deepEqual(workerTools.sort(), ['complete_client_job', 'fail_client_job', 'lease_client_job']);
  const week = await rpc('read-token', 4, 'tools/call', {
    name: 'list_week', arguments: { week_start: '2026-10-12' },
  });
  assert.equal(week.status, 200, week.body);
  assert.deepEqual(JSON.parse(result(week).result.content[0].text), {
    week_start: '2026-10-12', ideas: [],
  });
  assert.ok(upstream.some(call => call.path === '/api/week/2026-10-12' && call.bearer === 'Bearer read-token'));
  assert.equal((await rpc('read-token', 5, 'tools/list', null, 'https://attacker.example')).status, 403);
  revoked = true;
  const denied = await rpc('read-token', 6, 'tools/list');
  assert.equal(denied.status, 401);
  assert.match(denied.challenge || '', /invalid_token/);
});
