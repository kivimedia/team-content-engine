#!/usr/bin/env node
/**
 * Smoke test for the TCE terminal: every READ tool against the live engine,
 * plus the shape of the write tools without firing them.
 *
 *   TCE_BASIC_USER=ziv TCE_BASIC_PASS=... node smoke.mjs
 *
 * Writes are only exercised with --write, and even then only the harmless ones
 * (produce-now dedupes; nothing approves, rejects or changes a schedule).
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

import { DEFAULT_BASE, makeCaller, registerTools } from './tools.mjs';

const user = process.env.TCE_BASIC_USER;
const password = process.env.TCE_BASIC_PASS;
if (!user || !password) {
  console.error('smoke: set TCE_BASIC_USER and TCE_BASIC_PASS');
  process.exit(1);
}

const registered = new Map();
const server = new McpServer({ name: 'tce-smoke', version: '0' });
server.registerTool = (name, meta, handler) => registered.set(name, { meta, handler });

const { families, tools } = await registerTools(server, makeCaller(DEFAULT_BASE, user, password));
console.log(`base ${DEFAULT_BASE}`);
console.log(`families: ${families.join(', ')}`);
console.log(`tools (${tools.length}): ${tools.join(', ')}\n`);

let failures = 0;

for (const [name, entry] of registered) {
  const description = entry.meta.description || '';
  if (!description) {
    console.log(`FAIL ${name}: no description`);
    failures += 1;
  }
}

async function run(name, args = {}) {
  const entry = registered.get(name);
  if (!entry) {
    console.log(`FAIL ${name}: not registered`);
    failures += 1;
    return null;
  }
  const started = Date.now();
  try {
    const result = await entry.handler(args);
    const text = result?.content?.[0]?.text ?? '';
    const bad = /^Could not /.test(text);
    if (bad) failures += 1;
    console.log(`${bad ? 'FAIL' : 'ok  '} ${name} (${Date.now() - started}ms)`);
    console.log(
      text
        .split('\n')
        .slice(0, 6)
        .map((l) => `      ${l}`)
        .join('\n'),
    );
    console.log('');
    return result;
  } catch (error) {
    failures += 1;
    console.log(`FAIL ${name}: threw ${error.message}`);
    return null;
  }
}

await run('tce_briefing');
await run('tce_health');
await run('tce_runs', { limit: 4 });
await run('tce_ideas', {});
await run('tce_script', { title: 'Selling is the first step' });
await run('tce_evidence', { days: 7 });

const runs = registered.get('tce_runs');
const listing = await runs.handler({ limit: 1 });
const firstId = listing?.structuredContent?.data?.runs?.[0]?.id;
if (firstId) await run('tce_run', { run_id: String(firstId).slice(0, 8) });

// Errors must read as sentences, not stack traces.
await run('tce_run', { run_id: 'zzzzzzzz' });
await run('tce_script', { candidate_id: '00000000' });

if (process.argv.includes('--write')) {
  await run('tce_produce_now', { days: 7, packets: 3 });
}

console.log(failures ? `${failures} FAILURE(S)` : 'all tools answered');
process.exit(failures ? 1 : 0);
