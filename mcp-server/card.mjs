/**
 * Jennifer's character, repeated (T-13569, Ziv 17-Oct-2026).
 *
 * A long call drifts to a flat assistant voice. Every 10th tool result on a voice
 * call carries the short character text again, so it is fresh in the last turns.
 * The text is deploy/voice-seat/jennifer-core.txt, the same words the call brief
 * opens with. Counted per call in a small file named by the call id, so a
 * respawned server (the brain hit its cap) keeps counting. No call id, no count.
 * Never fails a tool: any problem returns the result untouched.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const EVERY = 10;
const CORE_FILE = join(dirname(fileURLToPath(import.meta.url)), '..', 'deploy', 'voice-seat', 'jennifer-core.txt');

export function coreText() {
  try {
    return readFileSync(CORE_FILE, 'utf8').trim();
  } catch {
    return '';
  }
}

function counterFile(env) {
  const id = String(env.TCE_VOICE_CALL_ID || env.KMBOT_VOICE_SESSION || '').trim();
  if (!id) return null;
  const dir = env.TCE_VOICE_STATE_DIR || join(tmpdir(), 'tce-voice-calls');
  return join(dir, `${id.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 120)}.count`);
}

/** Add one to this call's count and say what it is now; 0 when there is no call. */
export function bump(env = process.env) {
  const file = counterFile(env);
  if (!file) return 0;
  try {
    mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
    let n = 0;
    try { n = parseInt(readFileSync(file, 'utf8'), 10) || 0; } catch { /* first call */ }
    n += 1;
    writeFileSync(file, String(n), { mode: 0o600 });
    return n;
  } catch {
    return 0;
  }
}

/** The tool result, with the character text added on every EVERYth call. */
export function withCard(result, n, core = coreText()) {
  if (!n || n % EVERY !== 0 || !core || !result || typeof result !== 'object') return result;
  const note = `\n\n${core}`;
  const out = { ...result };
  if (Array.isArray(out.content) && out.content[0] && typeof out.content[0].text === 'string') {
    out.content = [{ ...out.content[0], text: out.content[0].text + note }, ...out.content.slice(1)];
  }
  if (out.structuredContent && typeof out.structuredContent.said === 'string') {
    out.structuredContent = { ...out.structuredContent, said: out.structuredContent.said + note };
  }
  return out;
}

/** Wrap a tool handler so its results carry the repeat. */
export function wrapHandler(handler, env = process.env) {
  return async (...args) => withCard(await handler(...args), bump(env));
}
