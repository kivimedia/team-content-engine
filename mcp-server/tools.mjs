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
export const SERVER_VERSION = '1.1.0';

export const DEFAULT_BASE = process.env.TCE_API_BASE || 'https://bot.kivimedia.co/tce';

/**
 * The headers one identity sends. Two shapes:
 *   - basic auth (the PC, through nginx, which injects the private key), or
 *   - the private key itself as a bearer, for a process on the VPS that talks to
 *     the API on 127.0.0.1 directly (the voice agent's brain). X-Workspace-Id
 *     picks the workspace; without it the API uses its configured editor one.
 */
export function authHeaders({ user, password, key, workspaceId } = {}) {
  const headers = {};
  if (key) {
    headers.Authorization = `Bearer ${key}`;
    if (workspaceId) headers['X-Workspace-Id'] = workspaceId;
  } else {
    headers.Authorization = 'Basic ' + Buffer.from(`${user}:${password}`).toString('base64');
  }
  return headers;
}

/**
 * Which identity the environment gives this process, or why it gives none.
 * TCE_PRIVATE_KEY wins when set: it only exists on the box the API runs on.
 */
export function identityFromEnv(env = process.env) {
  if (env.TCE_PRIVATE_KEY) {
    return {
      ok: true,
      mode: 'bearer',
      auth: { key: env.TCE_PRIVATE_KEY, workspaceId: env.TCE_WORKSPACE_ID || '' },
    };
  }
  if (env.TCE_BASIC_USER && env.TCE_BASIC_PASS) {
    return { ok: true, mode: 'basic', auth: { user: env.TCE_BASIC_USER, password: env.TCE_BASIC_PASS } };
  }
  return { ok: false, mode: 'none', auth: {} };
}

/**
 * Build a `call(method, path, body)` bound to one identity.
 * makeCaller(base, user, password) is the PC shape and still works;
 * makeCaller(base, { key, workspaceId }) is the VPS shape.
 */
export function makeCaller(base, userOrAuth, password) {
  const identity = typeof userOrAuth === 'object' && userOrAuth !== null
    ? userOrAuth
    : { user: userOrAuth, password };
  const auth = authHeaders(identity);
  const bearer = Boolean(identity.key);
  return async function call(method, path, body) {
    let response;
    try {
      response = await fetch(`${base}/api/v1${path}`, {
        method,
        headers: {
          ...auth,
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
      data = bearer
        ? {
          error: 'TCE refused the private key',
          hint: 'Check TCE_PRIVATE_KEY against the API private access key, and that TCE_API_BASE is the API itself (http://127.0.0.1:8200), not the nginx route.',
        }
        : {
          error: 'TCE refused the editor login',
          hint: 'Check TCE_BASIC_USER and TCE_BASIC_PASS. The route needs basic auth; a bearer key alone is refused at nginx.',
        };
    }
    return { ok: response.ok, status: response.status, data };
  };
}

/**
 * What every tool returns: text the assistant can read out, plus the raw data.
 *
 * `said` repeats the text inside structuredContent on purpose. Whenever
 * structuredContent is set, Claude Code hands the model JSON.stringify of it
 * alone and drops the text blocks, so without `said` the voice brain got
 * {"data":{"ok":false}} and never heard why, nor what to ask him next.
 */
export function reply(text, data) {
  return {
    content: [{ type: 'text', text }],
    structuredContent: data === undefined ? undefined : { said: text, data },
  };
}

/**
 * A short, speakable excerpt of an answer that was not JSON (an nginx error page,
 * a proxy's text): markup and entities out, anything shaped like a key or token
 * hidden, clipped. Enough to say why, never the page itself.
 */
export function excerpt(raw, limit = 160) {
  const text = String(raw ?? '')
    .replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&[a-z0-9#]+;/gi, ' ')
    .replace(/\b(bearer|basic|token|key|password|secret)\b\s*[:=]?\s*\S+/gi, '$1 [hidden]')
    .replace(/[A-Za-z0-9_\-+/=]{32,}/g, '[hidden]')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > limit ? `${text.slice(0, limit - 3).trimEnd()}...` : text;
}

/** A failed call, said plainly rather than as a stack trace. */
export function failure(result, what) {
  let detail = result.data?.detail || result.data?.error || `HTTP ${result.status}`;
  if (typeof detail !== 'string') detail = excerpt(JSON.stringify(detail));
  // Not JSON: say what came back, so "why" has an answer.
  const body = result.data?.body ? excerpt(result.data.body) : '';
  const came = body ? ` (HTTP ${result.status}: ${body})` : '';
  const hint = result.data?.hint ? `\n${result.data.hint}` : '';
  return reply(`Could not ${what}: ${detail}${came}${hint}`, { ok: false, status: result.status });
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
 * TCE_MCP_FAMILIES="voice" loads only those families. A voice call's brain does
 * better with the dozen tools it needs than with every tool the terminal has.
 */
export function familyFilter(env = process.env) {
  const raw = (env.TCE_MCP_FAMILIES || '').trim();
  return raw ? raw.split(',').map((f) => f.trim()).filter(Boolean) : null;
}

const isZod = (value) => Boolean(value) && typeof value === 'object' && ('_def' in value || '_zod' in value);

function zodField(prop, z) {
  const p = prop || {};
  if (Array.isArray(p.enum) && p.enum.length && p.enum.every((v) => typeof v === 'string')) return z.enum(p.enum);
  switch (p.type) {
    case 'string': return z.string();
    case 'number': return z.number();
    case 'integer': return z.number().int();
    case 'boolean': return z.boolean();
    case 'array': return z.array(p.items ? described(zodField(p.items, z), p.items) : z.any());
    case 'object': return p.properties ? z.object(inputShape(p, z)) : z.record(z.any());
    default: return z.any();
  }
}

const described = (field, prop) => (prop?.description ? field.describe(prop.description) : field);

/**
 * A family's JSON-Schema literal as the Zod raw shape the SDK takes.
 *
 * The families declare plain JSON Schema ({ type: 'object', properties }), and
 * the SDK (1.30, the locked version) accepts only Zod: it threw on every one,
 * so every family with an argument failed to load and a voice call started with
 * no tools at all. Converted here, in one place, so a family file stays plain.
 * A schema that is already Zod (or a raw shape of Zod) passes through.
 */
export function inputShape(schema, z) {
  if (schema == null) return {};
  if (isZod(schema)) return schema;
  const values = Object.values(schema);
  if (!values.length) return {};
  if (values.every(isZod)) return schema;
  if (schema.type !== 'object' && !schema.properties) {
    throw new Error('the input schema is neither JSON Schema for an object nor Zod');
  }
  const required = new Set(schema.required || []);
  const shape = {};
  for (const [key, prop] of Object.entries(schema.properties || {})) {
    const field = zodField(prop, z);
    shape[key] = described(required.has(key) ? field : field.optional(), prop);
  }
  return shape;
}

/**
 * Load every family in ./tools and register its tools.
 * One bad family must not cost the caller the others.
 */
export async function registerTools(server, call, only = familyFilter()) {
  // Imported here, not at the top, so the family tests can load this file
  // without node_modules; the server itself cannot run without them anyway.
  const { z } = await import('zod');
  const helpers = { reply, failure, shortId, ago, runLine, RUN_WORDS };
  const families = [];
  const tools = [];
  const registrar = {
    tool(name, description, schema, handler) {
      if (tools.includes(name)) {
        throw new Error(`two families claim the tool name ${name}`);
      }
      server.registerTool(name, { description, inputSchema: inputShape(schema, z) }, handler);
      // Counted only once the SDK took it, so the startup line is true.
      tools.push(name);
    },
  };
  const dir = new URL('./tools/', here);
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.mjs')).sort()) {
    try {
      const family = await import(new URL(file, dir).href);
      if (!family || typeof family.register !== 'function' || !family.FAMILY) continue;
      if (only && !only.includes(family.FAMILY)) continue;
      family.register(registrar, call, helpers);
      families.push(family.FAMILY);
    } catch (error) {
      console.error(`tce-mcp: family ${file} failed to load: ${error.message}`);
    }
  }
  return { families, tools };
}
