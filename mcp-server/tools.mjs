/**
 * The Team Content Engine tool index.
 *
 * One file per family in ./tools, discovered at load time, so adding a family
 * means adding a file and nothing here changes.
 *
 * Everything goes through `call`, which is bound to one editor identity. TCE's
 * two public routes (bot.kivimedia.co/tce and the sslip host) both strip
 * `Authorization` at nginx and inject the private editor key themselves, so the
 * only credential this server holds is Ziv's basic-auth pair. Never build a
 * fetch of your own in a family file, and never put the key or the password in
 * a file: they come from the environment.
 */
import { readdirSync } from 'node:fs';

export const SERVER_NAME = 'tce';
export const SERVER_VERSION = '1.0.0';

export const DEFAULT_BASE = process.env.TCE_API_BASE || 'https://bot.kivimedia.co/tce';

/** Build a `call(method, path, body)` bound to one editor login. */
export function makeCaller(base, user, password) {
  const auth = 'Basic ' + Buffer.from(`${user}:${password}`).toString('base64');
  return async function call(method, path, body) {
    let response;
    try {
      response = await fetch(`${base}/api/v1${path}`, {
        method,
        headers: {
          Authorization: auth,
          'content-type': 'application/json',
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      /*
       * A network failure is not an answer about the engine. "Nothing is in the
       * queue" and "I could not reach TCE" send somebody in opposite directions.
       */
      return {
        ok: false,
        status: 0,
        data: {
          error: 'could not reach TCE',
          hint: `The request never got there: ${error.message}. Nothing was read and nothing was changed.`,
        },
      };
    }
    const raw = await response.text();
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = { error: 'TCE did not answer with JSON', body: raw.slice(0, 400) };
    }
    if (response.status === 401) {
      data = {
        error: 'TCE refused the editor login',
        hint: 'Check TCE_BASIC_USER and TCE_BASIC_PASS. The route needs basic auth; a bearer key alone is refused at nginx.',
      };
    }
    return { ok: response.ok, status: response.status, data };
  };
}

/** What every tool returns: text the assistant can read out, plus the raw data. */
export function reply(text, data) {
  return {
    content: [{ type: 'text', text }],
    structuredContent: data === undefined ? undefined : { data },
  };
}

/** A failed call, said plainly rather than as a stack trace. */
export function failure(result, what) {
  const detail = result.data?.detail || result.data?.error || `HTTP ${result.status}`;
  const hint = result.data?.hint ? `\n${result.data.hint}` : '';
  return reply(`Could not ${what}: ${detail}${hint}`, { ok: false, status: result.status });
}

export function shortId(value) {
  return String(value || '').slice(0, 8);
}

/** "3 minutes ago" for a UTC timestamp, so states read as fresh or stale. */
export function ago(iso) {
  if (!iso) return 'never';
  const then = Date.parse(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(then)) return String(iso);
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

/** What a run is doing, in the words a person would use. */
export const RUN_WORDS = {
  queued: 'queued, starts within five minutes',
  collecting: 'collecting evidence',
  extracting: 'reading the evidence',
  selecting: 'choosing ideas',
  ranking: 'ranking the finalists',
  drafting: 'writing the packets',
  exporting: 'writing the Google Docs',
  ready: 'ready',
  waiting_worker: 'waiting for the desktop worker',
  waiting_capacity: 'waiting for capacity',
  needs_source_choice: 'waiting for a source choice',
  failed: 'stopped with an error',
  cancelled: 'cancelled',
};

export function runLine(run) {
  const words = RUN_WORDS[run.state] || run.state;
  const label = run.week_label ? ` ${run.week_label}` : '';
  const why = run.error_detail ? ` - ${String(run.error_detail).slice(0, 160)}` : '';
  return `${shortId(run.id)}${label}: ${words}${why}`;
}

const here = import.meta.url;

/**
 * Load every family in ./tools and register its tools.
 * One bad family must not cost the caller the others.
 */
export async function registerTools(server, call) {
  const helpers = { reply, failure, shortId, ago, runLine, RUN_WORDS };
  const families = [];
  const tools = [];
  const registrar = {
    tool(name, description, schema, handler) {
      if (tools.includes(name)) {
        throw new Error(`two families claim the tool name ${name}`);
      }
      tools.push(name);
      server.registerTool(name, { description, inputSchema: schema }, handler);
    },
  };
  const dir = new URL('./tools/', here);
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.mjs')).sort()) {
    try {
      const family = await import(new URL(file, dir).href);
      if (!family || typeof family.register !== 'function' || !family.FAMILY) continue;
      family.register(registrar, call, helpers);
      families.push(family.FAMILY);
    } catch (error) {
      console.error(`tce-mcp: family ${file} failed to load: ${error.message}`);
    }
  }
  return { families, tools };
}
