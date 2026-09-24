/**
 * The voice agent's hands.
 *
 * An Opus brain on a live call uses these while Ziv talks. Everything it gets
 * back is text it may read aloud, so every reply is short, plain and says what
 * happened, with the ids it needs kept in the data rather than spoken.
 *
 * The contract (Ziv, 23-Sep): the brain reads a change back to him, then calls
 * tce_edit, which applies it at once. That is safe only because every write is
 * attributed to "voice" and undoable by id, which is what tce_undo is for. The
 * long jobs (a script, more openings, research) never block a spoken turn: they
 * start and return, and tce_jobs says when each one is ready.
 */
import {
  mkdirSync, readdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

export const FAMILY = 'voice';

/*
 * What this call has done, newest last, so "undo the last thing I changed"
 * means the last entry of THIS call, never someone else's edit.
 *
 * One process is NOT one call: when the brain hits its cap mid-call, KM BOT's
 * voice seat starts a new brain and kills the old one, and this server is
 * respawned with it. Kept only in memory, the ledger came back empty and undo
 * said "nothing has been changed" about an edit from two minutes earlier. So
 * the ledger is a small file named by the call id, which survives a rotation.
 * No call id (the PC terminal) keeps it in memory, as before.
 */
const STALE_MS = 2 * 24 * 3600 * 1000;

/** The file this call's ledger lives in, or null to keep it in memory only. */
export function ledgerPath(env = process.env) {
  const id = String(env.TCE_VOICE_CALL_ID || env.KMBOT_VOICE_SESSION || '').trim();
  if (!id) return null;
  const dir = env.TCE_VOICE_STATE_DIR || join(tmpdir(), 'tce-voice-calls');
  return join(dir, `${id.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 120)}.json`);
}

function loadLedger(file) {
  const empty = { writes: [], jobs: [] };
  if (!file) return empty;
  try {
    mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
    // Calls from days ago are nobody's "last change" any more.
    for (const name of readdirSync(dirname(file))) {
      const old = join(dirname(file), name);
      if (name.endsWith('.json') && old !== file && Date.now() - statSync(old).mtimeMs > STALE_MS) unlinkSync(old);
    }
  } catch {
    // Housekeeping only; the read below says whether the ledger is usable.
  }
  try {
    const saved = JSON.parse(readFileSync(file, 'utf8'));
    return {
      writes: Array.isArray(saved.writes) ? saved.writes : [],
      jobs: Array.isArray(saved.jobs) ? saved.jobs : [],
    };
  } catch (error) {
    if (error.code !== 'ENOENT') console.error(`tce-mcp: voice ledger ${file} unreadable, starting empty: ${error.message}`);
    return empty;
  }
}

function saveLedger(file, ledger) {
  if (!file) return;
  try {
    const tmp = `${file}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(ledger), { mode: 0o600 });
    renameSync(tmp, file);
  } catch (error) {
    // stderr, never stdout: stdout is the MCP stream.
    console.error(`tce-mcp: could not save the voice ledger to ${file}: ${error.message}`);
  }
}

const BRIEF_ALIASES = {
  topic: 'topic',
  audience: 'audience',
  'who it is for': 'audience',
  'big idea': 'big_idea',
  idea: 'big_idea',
  'why now': 'why_now',
  'why this is yours': 'why_this_is_yours',
  'why it s yours': 'why_this_is_yours',
  angle: 'distinctive_perspective',
  perspective: 'distinctive_perspective',
  'your angle': 'distinctive_perspective',
  evidence: 'evidence',
  'claims to avoid': 'claims_to_avoid',
  takeaway: 'takeaway',
  cta: 'cta',
  'call to action': 'cta',
};

const SCRIPT_WORDS = {
  none: 'no script yet',
  ready: 'script ready',
  draft: 'script in draft',
  issues: 'script has issues to check',
};

const DECISIONS = {
  this_week: 'this_week',
  'this week': 'this_week',
  approve: 'this_week',
  approved: 'this_week',
  yes: 'this_week',
  discuss: 'discuss',
  think: 'discuss',
  later: 'later',
  'save for later': 'later',
  away: 'away',
  'put away': 'away',
};

// "X is already ..." for a decision that changed nothing.
const ALREADY = {
  this_week: 'in this week\'s list',
  discuss: 'marked to think about',
  later: 'saved for later',
  away: 'put away',
};

const MOVES = {
  first: { action: 'first' },
  top: { action: 'first' },
  up: { action: 'up' },
  down: { action: 'down' },
  last: { action: 'rank', rank: 99 },
  reserve: { action: 'slot', slot: 'reserve' },
  primary: { action: 'slot', slot: 'primary' },
  remove: { action: 'remove' },
  out: { action: 'remove' },
};

const clean = (value) => String(value ?? '').toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();

/** "point 3" -> {target: script, field: bullets.2}. Null when it is not a part we know. */
export function parsePart(part) {
  const p = clean(part);
  let m = p.match(/^(?:point|bullet|walking point)\s*(\d+)$/);
  if (m) return { target: 'script', field: `bullets.${Number(m[1]) - 1}`, label: `Point ${m[1]}` };
  m = p.match(/^(?:line|script line|phrase|sentence)\s*(\d+)$/);
  if (m) return { target: 'script', field: `script_phrases.${Number(m[1]) - 1}`, label: `Script line ${m[1]}` };
  if (/^(?:the )?(?:opening|opening line|hook|first line)$/.test(p)) {
    return { target: 'script', field: 'script_phrases.0', label: 'The opening line' };
  }
  if (/^(?:the )?facebook(?: post)?$/.test(p)) return { target: 'script', field: 'facebook_post', label: 'The Facebook post' };
  if (/^(?:the )?linkedin(?: post)?$/.test(p)) return { target: 'script', field: 'linkedin_post', label: 'The LinkedIn post' };
  const brief = BRIEF_ALIASES[p.replace(/^the /, '')] || (Object.values(BRIEF_ALIASES).includes(p.replace(/ /g, '_')) ? p.replace(/ /g, '_') : null);
  if (brief) return { target: 'brief', field: brief, label: brief.replace(/_/g, ' ') };
  return null;
}

/*
 * A write names its topic by id, never by words (23-Sep, round 3). Every write
 * applies at once, and word matching kept finding new ways to land on the wrong
 * title: "the first one", "הראשון", "זה שדיברנו עליו" each named a title that
 * happened to hold the word. So words go only to the read tools (tce_topic,
 * tce_week), which answer with the title and its id, or with candidates when
 * the words are not a clear winner; the brain reads the title back to him, and
 * the write takes the id. At worst a stray word makes a read offer candidates.
 */
export const FIND_FIRST = 'Find the topic with tce_topic, read its title back to him, then pass its id.';
const TOPIC_ID = {
  type: 'string',
  description: 'The topic\'s id or short id, as tce_topic or tce_week gave it. Never words from the title.',
};
// A whole id, or the short id (its first 8 characters) or more of it.
const ID_TEXT = /^[0-9a-f]{8}[0-9a-f-]{0,28}$/;

/** "id 1a2b3c4d", "(1a2b3c4d)" -> "1a2b3c4d": the id as the brain may pass it. */
export function idText(raw) {
  return String(raw ?? '').trim().toLowerCase()
    .replace(/^(?:short\s+)?id[\s:]+/, '')
    .replace(/^[\s()[\]"'.]+|[\s()[\]"'.]+$/g, '');
}

/*
 * Put away as he means it: withdrawn, and not still chosen for this week and on
 * its list. Choosing an idea does not move its status, so the engine can withdraw
 * one he chose (a re-run of the week's selection, a stale news idea, the Archive
 * button) while it stays on this week's list; that one can still be put away,
 * which takes it off the list. The decide route draws the same line.
 */
function isAway(t) {
  return Boolean(t.put_away) && !(t.in_this_week && t.decision === 'this_week');
}

export function register(server, call, { reply, failure, shortId }) {
  const ledgerFile = ledgerPath();
  const ledger = loadLedger(ledgerFile);
  const save = () => saveLedger(ledgerFile, ledger);

  /**
   * The one topic an id names, for a tool that writes; a reply to return instead
   * when it is not an id, or names no topic. Words are refused before any request.
   */
  async function byId(topic) {
    const id = idText(topic);
    if (!ID_TEXT.test(id)) {
      return {
        stop: reply(
          `A change names its topic by id, not by words ("${String(topic ?? '')}" is not an id). `
            + `${FIND_FIRST} Nothing was changed.`,
          { ok: false, code: 'id_required' },
        ),
      };
    }
    const result = await call('GET', `/editorial/voice/topic?id=${encodeURIComponent(id)}`);
    if (!result.ok) {
      const detail = result.data?.detail;
      if (detail && typeof detail === 'object' && detail.message) {
        const tail = detail.message.includes('tce_topic') ? '' : ` ${FIND_FIRST}`;
        return { stop: reply(`${detail.message}${tail}`, { ok: false, code: detail.code, status: result.status }) };
      }
      return { stop: failure(result, 'find that topic') };
    }
    if (result.data?.status !== 'found' || !result.data.topic) {
      return {
        stop: reply(`No topic has the id "${id}". ${FIND_FIRST} Nothing was changed.`, { ok: false, code: 'unknown_topic' }),
      };
    }
    return { topic: result.data.topic };
  }

  /**
   * One topic by id or words, for reading; a reply to return instead when it is
   * not exactly one. Candidates come back with their titles and ids, so the
   * brain can read them to him and ask which.
   */
  async function resolve(topic) {
    if (!topic) return { stop: reply('Which topic? Say part of its title.', { status: 'none' }) };
    const result = await call('GET', `/editorial/voice/topic?q=${encodeURIComponent(topic)}`);
    if (!result.ok) return { stop: failure(result, 'find that topic') };
    const d = result.data;
    if (d.status === 'found') return { topic: d.topic };
    if (d.status === 'ambiguous' && d.candidates.length === 1) {
      // A close match that is not a sure one: he says whether it is the one.
      const [c] = d.candidates;
      return {
        stop: reply(
          `The closest topic to "${topic}" is "${c.title}" (id ${c.short_id}), but not all of his words are in it. `
            + 'Ask him if that is the one, then use its id.',
          d,
        ),
      };
    }
    if (d.status === 'ambiguous') {
      const names = d.candidates.map((c, n) => `${n + 1}. ${c.title} (id ${c.short_id})`);
      return {
        stop: reply(
          `More than one topic matches "${topic}":\n${names.join('\n')}\nAsk him which one, then use its id.`,
          d,
        ),
      };
    }
    return { stop: reply(`No topic matches "${topic}". Ask him for other words from its title.`, d) };
  }

  /** A refusal said plainly; `more` is added to what he hears. */
  function spokenError(result, what, more = '') {
    const raw = result.data?.detail;
    // A sentence ends before the next one starts, or they run together aloud.
    const detail = raw && typeof raw === 'object' && typeof raw.message === 'string'
      && !/[.!?]["')]?$/.test(raw.message.trim())
      ? { ...raw, message: `${raw.message.trim()}.` }
      : raw;
    const tail = more ? ` ${more}` : '';
    if (result.status === 409 && detail && typeof detail === 'object') {
      const now = detail.current;
      if (typeof now === 'string') {
        return reply(
          `${detail.message} It now says: "${now}". Read him the current text and ask again.${tail}`,
          { ok: false, code: detail.code, current: now },
        );
      }
      // The opening options as they are now, numbered: what to read him instead.
      const options = Array.isArray(now) && now.every((o) => o && typeof o.text === 'string')
        ? ` The options now are: ${now.map((o, n) => `${o.n ?? n + 1}. "${o.text}"`).join(' ')}`
        : '';
      return reply(`${detail.message}${options}${tail}`, { ok: false, code: detail.code, current: now ?? null });
    }
    if (detail && typeof detail === 'object' && detail.message) {
      return reply(`Could not ${what}: ${detail.message}${tail}`, { ok: false, code: detail.code, status: result.status });
    }
    if (!tail) return failure(result, what);
    const failed = failure(result, what);
    return reply(`${failed.content[0].text}${tail}`, failed.structuredContent.data);
  }

  function remember(entry) {
    ledger.writes.push({ ...entry, at: new Date().toISOString(), undone: false });
    save();
  }

  /*
   * A decision write as the call's undo needs it: its own change id. What it
   * replaced and what it did to a week's list are kept on the server with that
   * id, so the undo takes back exactly this write and no other. A write that
   * changed nothing has no id and is not remembered: "approve it" twice, then
   * "undo", takes back the approval that did it.
   */
  function rememberDecision(t, decision, data) {
    if (!data?.change_id) return '';
    remember({
      kind: 'decision',
      id: data.change_id,
      candidate_id: t.candidate_id,
      title: t.title,
      decision,
      summary: `the decision on "${t.title}"`,
    });
    return ` (change ${shortId(data.change_id)})`;
  }

  function track(job) {
    ledger.jobs.push({ ...job, started: new Date().toISOString(), announced: false });
    save();
  }

  /*
   * Undo with nothing on record for this call. That can be a call with no
   * change yet, or a server that restarted without a call id. Either way,
   * "nothing has been changed" may be false, and undoing the newest voice
   * change blindly may undo an earlier call's. So name it and ask.
   */
  async function lastVoiceChange() {
    const recent = await call('GET', '/editorial/voice/activity?hours=1');
    if (!recent.ok) {
      const detail = recent.data?.error || recent.data?.detail || `HTTP ${recent.status}`;
      return reply(
        `I have no record of a change in this call, and I could not check the voice log (${detail}). `
          + 'Nothing was undone.',
        { ok: false, code: 'no_record', status: recent.status },
      );
    }
    const items = recent.data.items || [];
    // Edits and decisions alike: each has its own change id now.
    const last = items.find((i) => (i.kind === 'change' || i.kind === 'decision')
      && !i.is_undo && !i.undone && i.can_undo !== false);
    if (!last) {
      return reply('Nothing has been changed by voice in the last hour, so there is nothing to undo.', { ok: false, code: 'nothing' });
    }
    const what = (last.lines || []).join(' ') || last.summary || 'a change';
    const on = last.title && last.kind === 'change' ? ` on "${last.title}"` : '';
    const short = last.short_id || shortId(last.id);
    return reply(
      `I have no record of a change in this call, so nothing was undone yet. The last voice change I can see is: `
        + `${what}${on} (change ${short}). Is that the one? If he says yes, call tce_undo with change_id ${short}.`,
      {
        ok: false,
        code: 'confirm_needed',
        kind: last.kind,
        change_id: last.id,
        short_id: short,
        candidate_id: last.candidate_id ?? null,
        title: last.title ?? null,
      },
    );
  }

  // ------------------------------------------------------------------ read

  server.tool(
    'tce_week',
    'This week at a glance: the recording list in order with each script\'s state, and the ideas '
      + 'still waiting for a decision, each with its id. Read-only. Start here when he says "the week"; '
      + 'a change to one of them takes the id listed here.',
    { type: 'object', properties: {} },
    async () => {
      const today = await call('GET', '/editorial/today');
      if (!today.ok) return failure(today, 'read this week');
      const waiting = await call('GET', '/editorial/topics?filter=best&limit=8');
      const week = today.data.week || {};
      const primary = week.primary || [];
      const lines = [];
      if (primary.length) {
        lines.push(`This week has ${primary.length} topic${primary.length === 1 ? '' : 's'}:`);
        primary.forEach((t, n) => {
          lines.push(`${n + 1}. ${t.title} - ${SCRIPT_WORDS[t.script_state] || t.script_state} (id ${shortId(t.candidate_id)})`);
        });
      } else {
        lines.push('Nothing is in this week yet.');
      }
      const reserve = week.reserve || [];
      if (reserve.length) {
        lines.push(`${reserve.length} more in reserve:`);
        reserve.forEach((t) => lines.push(`- ${t.title} (id ${shortId(t.candidate_id)})`));
      }
      const topics = (waiting.ok ? waiting.data.topics : []) || [];
      const undecided = topics.filter((t) => !t.decision);
      const count = today.data.attention?.waiting ?? undecided.length;
      if (count) {
        lines.push(`${count} idea${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} a decision, best first:`);
        undecided.slice(0, 5).forEach((t) => lines.push(`- ${t.title} (id ${shortId(t.candidate_id)})`));
      } else {
        lines.push('No ideas are waiting for a decision.');
      }
      const reviews = today.data.attention?.pending_reviews || 0;
      if (reviews) lines.push(`${reviews} proposed change${reviews === 1 ? ' is' : 's are'} waiting for a yes or no.`);
      if (today.data.next_action?.label) lines.push(`Next: ${today.data.next_action.label}. ${today.data.next_action.detail || ''}`.trim());
      return reply(lines.join('\n'), {
        week: primary.map((t) => ({ candidate_id: t.candidate_id, title: t.title, rank: t.rank, script_state: t.script_state, packet_id: t.packet_id })),
        reserve: reserve.map((t) => ({ candidate_id: t.candidate_id, title: t.title })),
        needs_decision: undecided.map((t) => ({ candidate_id: t.candidate_id, title: t.title })),
        attention: today.data.attention,
      });
    },
  );

  server.tool(
    'tce_topic',
    'One topic in full: its brief, and its script (the opening, the numbered points, the numbered '
      + 'script lines and the numbered opening options). Give an id or a few words of the title: this '
      + 'is where words go. If the words are not a clear match it lists the candidates, each with its '
      + 'title and id, so you can ask which. Read the title back to him before any change; the tools '
      + 'that change something take the id this returns, never words. The text is for you; read '
      + 'aloud only the part he asked about.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      // Reading: the only close title may be read back; he hears which one it is.
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const lines = [`${t.title} (id ${t.short_id})`];
      const state = isAway(t) ? 'Put away.'
        : t.in_this_week ? 'In this week.'
        : t.decision ? `Decision: ${t.decision.replace('_', ' ')}.` : 'Not decided yet.';
      lines.push(state);
      const b = t.brief.values || {};
      if (b.big_idea) lines.push(`Big idea: ${b.big_idea}`);
      if (b.takeaway) lines.push(`Takeaway: ${b.takeaway}`);
      const s = t.script;
      if (!s) {
        lines.push('No script yet. tce_write_script starts one.');
      } else {
        lines.push(`Script version ${s.version} (${s.status}).`);
        if (s.opening) lines.push(`Opening: "${s.opening}"`);
        if (s.points.length) {
          lines.push('Points:');
          s.points.forEach((p, n) => lines.push(`  ${n + 1}. ${p}`));
        }
        if (s.hooks.length) {
          lines.push('Opening options:');
          s.hooks.forEach((h) => lines.push(`  ${h.n}. ${h.text}${h.chosen ? ' (in use)' : ''}`));
        }
        if (s.script_phrases.length) {
          lines.push('Script lines:');
          s.script_phrases.forEach((p, n) => lines.push(`  ${n + 1}. ${p}`));
        }
      }
      if (t.research?.state === 'done' && t.research.summary) lines.push(t.research.summary);
      return reply(lines.join('\n'), t);
    },
  );

  // ------------------------------------------------------------------ write

  server.tool(
    'tce_edit',
    'Change one part of a script or brief, and apply it at once. Read the new wording back to him '
      + 'FIRST; call this only after he agreed. part is what he calls it: "point 3", "line 5", '
      + '"the opening", "facebook post", or a brief block ("big idea", "takeaway", "your angle", '
      + '"why now", "audience", "call to action", "claims to avoid", "evidence"). Pass expect with '
      + 'the text you read him as the current one: if it changed since, nothing is written and the '
      + `new text comes back. Returns a change id; tce_undo takes it back. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: {
        topic: TOPIC_ID,
        part: { type: 'string', description: 'Which part: "point 3", "line 2", "the opening", "takeaway"...' },
        text: { type: 'string', description: 'The new wording, exactly as agreed.' },
        expect: { type: 'string', description: 'The current wording you read him, to catch a change made meanwhile.' },
      },
      required: ['topic', 'part', 'text'],
    },
    async ({ topic, part, text, expect }) => {
      const where = parsePart(part);
      if (!where) {
        return reply(
          `I do not know which part "${part}" is. I can change: point N, line N, the opening, `
            + 'the Facebook or LinkedIn post, or a brief block (big idea, takeaway, your angle, why now, '
            + 'audience, call to action, claims to avoid, evidence).',
          { ok: false, code: 'unknown_part' },
        );
      }
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const op = { op: 'set_field', field: where.field, after: text };
      if (expect) op.expect = expect;
      const result = await call('POST', '/editorial/voice/change', {
        candidate_id: t.candidate_id,
        target: where.target,
        operations: [op],
        summary: `${where.label} of "${t.title}"`,
        by: 'voice',
      });
      if (!result.ok) return spokenError(result, `change ${where.label.toLowerCase()}`);
      const d = result.data;
      remember({ kind: 'change', id: d.change_set_id, title: t.title, summary: d.said.join(' ') });
      const warn = d.warnings?.length ? ` Note: ${d.warnings.join('; ')}.` : '';
      return reply(`Done on "${t.title}": ${d.said.join(' ')}${warn} (change ${d.short_id}; undo takes it back.)`, d);
    },
  );

  server.tool(
    'tce_decide',
    'Decide a topic: this_week (approve it into this week\'s list), discuss, later, or away. '
      + `For away, prefer tce_put_away. Returns a change id; tce_undo takes it back. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: {
        topic: TOPIC_ID,
        decision: { type: 'string', description: 'this_week, discuss, later or away. "approve" means this_week.' },
        note: { type: 'string', description: 'Why, in his words, if he said.' },
      },
      required: ['topic', 'decision'],
    },
    async ({ topic, decision, note }) => {
      const wanted = DECISIONS[clean(decision)] || DECISIONS[decision];
      if (!wanted) return reply(`"${decision}" is not a decision. Use this_week, discuss, later or away.`, { ok: false });
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', `/editorial/topics/${t.candidate_id}/decide`, { decision: wanted, note, by: 'voice' });
      if (!result.ok) return spokenError(result, 'decide that topic');
      const d = result.data;
      const sameOnWeek = d.changed === false && !d.added_to_week && !d.removed_from_week;
      if (sameOnWeek && !d.brought_back) {
        return reply(
          `"${t.title}" is already ${ALREADY[wanted] || wanted}. Nothing was changed, so there is nothing new to undo.`,
          d,
        );
      }
      const change = rememberDecision(t, wanted, d);
      if (sameOnWeek) {
        // The engine had withdrawn it; the decision stays, and bringing it back
        // is the change (undo withdraws it again).
        return reply(`"${t.title}" is back from the withdrawn ideas, still ${ALREADY[wanted] || wanted}.${change}`, d);
      }
      const said = {
        this_week: `"${t.title}" is in this week's list${result.data.placed ? `, place ${result.data.placed.rank}` : ''}.`,
        discuss: `"${t.title}" is marked to think about.`,
        later: `"${t.title}" is saved for later.`,
        away: `"${t.title}" is put away. It can be brought back.`,
      }[wanted];
      const back = d.brought_back ? ' It is back from the withdrawn ideas.' : '';
      return reply(`${said}${back}${change}`, d);
    },
  );

  server.tool(
    'tce_put_away',
    'Put an idea away (it stops being offered). Restorable with tce_restore_idea. Say the title back '
      + `to him and get a yes before calling this. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: { topic: TOPIC_ID },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      if (isAway(t)) return reply(`"${t.title}" is already put away.`, { candidate_id: t.candidate_id });
      const result = await call('POST', `/editorial/topics/${t.candidate_id}/decide`, { decision: 'away', by: 'voice' });
      if (!result.ok) return spokenError(result, 'put that idea away');
      const change = rememberDecision(t, 'away', result.data);
      return reply(`Put away: "${t.title}". It can be brought back.${change}`, result.data);
    },
  );

  server.tool(
    'tce_restore_idea',
    'Bring a put-away idea back to where it was before it was put away. tce_topic finds put-away '
      + `ideas too. Undoable. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: { topic: TOPIC_ID },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', `/editorial/topics/${t.candidate_id}/restore`, { by: 'voice' });
      if (!result.ok) return spokenError(result, 'bring that idea back');
      const change = rememberDecision(t, result.data.decision ?? 'undecided', result.data);
      return reply(`${result.data.said}${change}`, result.data);
    },
  );

  server.tool(
    'tce_choose_hook',
    'Use a different opening for a script: option is the number from tce_topic\'s opening options '
      + '(1, 2, 3), and expect is the text of that opening exactly as you read it to him. The '
      + 'script\'s opening line becomes that option. If the options changed since you read them '
      + '(a new script, more openings), nothing is written and the options as they are now come '
      + `back to read him instead. Undoable. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: {
        topic: TOPIC_ID,
        option: { type: 'string', description: 'The option number (1, 2, 3) or its id.' },
        expect: { type: 'string', description: 'The text of the opening he chose, as you read it to him.' },
      },
      required: ['topic', 'option', 'expect'],
    },
    async ({ topic, option, expect }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', '/editorial/voice/change', {
        candidate_id: t.candidate_id,
        target: 'script',
        operations: [{ op: 'choose_hook', after: String(option), expect: expect ?? null }],
        summary: `Opening ${option} for "${t.title}"`,
        by: 'voice',
      });
      if (!result.ok) return spokenError(result, 'change the opening');
      const d = result.data;
      remember({ kind: 'change', id: d.change_set_id, title: t.title, summary: `opening ${option}` });
      const line = d.changes.find((c) => c.field === 'script_phrases.0');
      return reply(
        `Done. The opening of "${t.title}" is now option ${option}${line ? `: "${line.after}"` : ''}. (change ${d.short_id})`,
        d,
      );
    },
  );

  server.tool(
    'tce_reorder_week',
    'Move a topic in this week\'s list: first, up, down, last, reserve, primary, remove, or a '
      + `position number. Undoable. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: {
        topic: TOPIC_ID,
        move: { type: 'string', description: 'first, up, down, last, reserve, primary, remove, or a number like "2".' },
      },
      required: ['topic', 'move'],
    },
    async ({ topic, move }) => {
      const key = clean(move);
      let spec = MOVES[key] || (/^\d+$/.test(key) ? { action: 'rank', rank: Number(key) } : null);
      if (!spec) return reply(`"${move}" is not a move. Use first, up, down, last, reserve, remove or a number.`, { ok: false });
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      /*
       * The lineup clamps a place past the end, but the change is read back
       * (and listed under "Changes by voice") with the number as asked: "last"
       * came out as "moved to place 99". So send the place it will really get.
       */
      let lastPlace = null;
      if (spec.action === 'rank') {
        const today = await call('GET', '/editorial/today');
        const week = (today.ok && today.data.week) || {};
        const where = [['primary', 'in the week'], ['reserve', 'in reserve']]
          .map(([slot, words]) => ({ list: week[slot] || [], words }))
          .find(({ list }) => list.some((i) => i.candidate_id === t.candidate_id));
        if (where) {
          const size = where.list.length;
          const rank = Math.max(1, Math.min(size, key === 'last' ? size : spec.rank));
          spec = { action: 'rank', rank };
          if (key === 'last' || Number(key) > size) lastPlace = `the last place ${where.words} (place ${rank})`;
        } else if (key === 'last') {
          lastPlace = 'the last place in the week';
        }
      }
      const result = await call('POST', '/editorial/voice/change', {
        candidate_id: t.candidate_id,
        target: 'week',
        operations: [{ op: 'move_topic', after: { ...spec, candidate_id: t.candidate_id } }],
        summary: `Move "${t.title}" ${key}`,
        by: 'voice',
      });
      if (!result.ok) return spokenError(result, 'move that topic');
      const d = result.data;
      const said = lastPlace ? `${t.title} moved to ${lastPlace}.` : d.said.join(' ');
      remember({ kind: 'change', id: d.change_set_id, title: t.title, summary: said });
      return reply(`Done. ${said} (change ${d.short_id})`, d);
    },
  );

  server.tool(
    'tce_undo',
    'Take back a change. With no id it takes back the last thing changed in THIS call that can '
      + 'still be taken back. With an id (the change id a tool returned: an edit, a decision, a new '
      + 'script) it takes back exactly that one. Refuses, with the current text, if the same part was '
      + 'changed again since; the next undo without an id then goes to the change before it. When '
      + 'an undo of a new script says the script moved on and offers a version, restore_version '
      + '(with that change id) puts that version back.',
    {
      type: 'object',
      properties: {
        change_id: { type: 'string', description: 'Optional. The change id (or its first 8 characters).' },
        restore_version: {
          type: 'integer',
          description: 'Only when an undo offered it: the script version to put back, with change_id.',
        },
      },
    },
    async ({ change_id, restore_version }) => {
      let entry;
      if (change_id) {
        // Any change of this call by its id: an edit, a decision, a rewrite.
        entry = [...ledger.writes].reverse().find((w) => w.id && String(w.id).startsWith(change_id));
        if (!entry) {
          // One from earlier today, an edit or a decision, by its id in the voice log.
          const recent = await call('GET', '/editorial/voice/activity?hours=24');
          const hit = recent.ok && (recent.data.items || []).find((i) => String(i.id).startsWith(change_id));
          if (hit && hit.kind === 'decision') {
            entry = {
              kind: 'decision', id: hit.id, candidate_id: hit.candidate_id, title: hit.title,
            };
          } else if (hit) {
            entry = { kind: 'change', id: hit.id, title: hit.title };
          } else if (/^[0-9a-f-]{36}$/i.test(change_id)) {
            entry = { kind: 'change', id: change_id };
          } else {
            return reply(`I have no change ${change_id} from the last day.`, { ok: false });
          }
        }
      } else {
        if (restore_version !== undefined && restore_version !== null) {
          return reply('restore_version goes with the change id whose undo offered it. Nothing was changed.', { ok: false });
        }
        if (!ledger.writes.length) return lastVoiceChange();
        // A change whose undo was refused for good is passed over, so "undo"
        // again means the change before it rather than the same refusal.
        entry = [...ledger.writes].reverse().find((w) => !w.undone && !w.refused);
        if (!entry) {
          const refused = ledger.writes.filter((w) => w.refused && !w.undone);
          if (!refused.length) return reply('Nothing has been changed in this call, so there is nothing to undo.', { ok: false });
          const names = refused.map((w) => `${w.summary || w.title || 'a change'}${w.id ? ` (change ${shortId(w.id)})` : ''}`);
          return reply(
            `Everything else changed in this call is undone. These could not be undone when asked: ${names.join('; ')}. `
              + 'If he asks again, use the change id.',
            { ok: false, code: 'only_refused', refused: refused.map((w) => w.id ?? null) },
          );
        }
      }

      if (restore_version !== undefined && restore_version !== null) {
        // A version an undo offered after saying the script moved on: put back as
        // a change of this call, attributed and undoable like any other.
        const version = Number(restore_version);
        if (!entry.candidate_id || !Number.isInteger(version)) {
          return reply('That change is not on a script, so there is no version to put back. Nothing was changed.', { ok: false });
        }
        const result = await call('POST', `/editorial/candidates/${entry.candidate_id}/script/restore`, { version, by: 'voice' });
        if (!result.ok) return spokenError(result, `put back script version ${version}`);
        const d = result.data;
        entry.undone = true;
        entry.refused = false;
        if (d.change_set_id) {
          remember({ kind: 'change', id: d.change_set_id, title: entry.title, summary: d.said });
        } else {
          save();
        }
        return reply(d.said, d);
      }

      /*
       * A refusal is an answer. One that holds for good (it was changed again, it
       * was never saved) marks the entry, so the next plain undo moves on; one
       * that is only "not yet" (still being written, a take being recorded)
       * leaves it next in line. Either way it stays reachable by its id.
       */
      const NOT_YET = new Set(['still_writing', 'recording']);
      const refusedWith = (result, what) => {
        const detail = result.data?.detail;
        const code = detail?.code;
        if (result.status >= 400 && result.status < 500 && !NOT_YET.has(code)) {
          entry.refused = true;
          save();
          const id = entry.id ? ` by its id (change ${shortId(entry.id)})` : '';
          let more = `The next undo goes to the change before this one; this one can still be undone later${id}.`;
          if (code === 'replaced_since' && Number.isInteger(detail.previous_version)) {
            more = `To put a version back, call tce_undo with change_id ${shortId(entry.id)} and `
              + `restore_version ${detail.previous_version} (the one just before the current script)`
              + (Number.isInteger(detail.asked_version) && detail.asked_version !== detail.previous_version
                ? ` or restore_version ${detail.asked_version} (the one he had when he asked).`
                : '.')
              + ' The next undo without an id goes to the change before this one.';
          }
          return spokenError(result, what, more);
        }
        if (NOT_YET.has(code)) {
          // Skipping it would quietly undo an older change he did not mean.
          return spokenError(result, what, 'It stays the next thing undo takes back once that is finished; '
            + 'to take back an earlier change now, use that change\'s id.');
        }
        return spokenError(result, what);
      };
      const done = (result, said) => {
        entry.undone = true;
        entry.refused = false;
        save();
        return reply(said, result.data);
      };

      if (entry.kind === 'decision') {
        // The server holds what this write replaced and what it did to a week's
        // list, under its change id: the undo takes back exactly this write, from
        // whichever week's list it touched, in one transaction.
        const result = await call('POST', `/editorial/topics/${entry.candidate_id}/undo-decision`, {
          change_id: entry.id,
          by: 'voice',
        });
        if (!result.ok) return refusedWith(result, 'undo that decision');
        const d = result.data || {};
        if (d.already) return done(result, d.said);
        return done(result, d.said ? `Undone. ${d.said}` : `Undone. "${entry.title}" is back where it was.`);
      }

      if (entry.kind === 'script') {
        // A rewrite he agreed to. What comes back is the script it replaced when
        // it was saved, edits made meanwhile included. That undo is not a new
        // step of this call: a second "undo" goes further back, it does not bring
        // the rewrite back.
        const result = entry.id
          ? await call('POST', `/editorial/candidates/${entry.candidate_id}/script/undo-rewrite`, {
            rewrite_id: entry.id, replaced_version: entry.replaced_version ?? null, by: 'voice',
          })
          : await call('POST', `/editorial/candidates/${entry.candidate_id}/script/restore`, { version: entry.replaced_version, by: 'voice' });
        if (!result.ok) return refusedWith(result, 'put the earlier script back');
        return done(result, result.data.said);
      }

      const result = await call('POST', `/editorial/change-sets/${entry.id}/undo`, { by: 'voice' });
      if (!result.ok) return refusedWith(result, 'undo that change');
      return done(result, result.data.said);
    },
  );

  // ------------------------------------------------------------------ jobs

  server.tool(
    'tce_write_script',
    'Start writing the script for a topic. Takes a few minutes on his PC worker; this returns at '
      + 'once. Tell him it has started; tce_jobs says when it is ready. If the topic already has a '
      + 'script (tce_topic says "Script version N"), writing a new one replaces the current script '
      + 'when it finishes, together with any edits made to it meanwhile. So this refuses and reads '
      + 'that back unless replace is true: tell him ("X already has a script, version N; a new one '
      + 'replaces it") and call again with replace true only after he says yes. While it is being '
      + 'written the script itself cannot be changed. tce_undo (or its change id) puts back the '
      + `script it replaced once the new one is ready. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: {
        topic: TOPIC_ID,
        replace: {
          type: 'boolean',
          description: 'Only after he agreed to replace the script the topic already has.',
        },
      },
      required: ['topic'],
    },
    async ({ topic, replace }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const hasScript = (version, status) => reply(
        `"${t.title}" already has a script (version ${version}, ${status}). A new one replaces it `
          + 'when it is written, together with any edits made to it meanwhile. Nothing was started. '
          + 'Ask him if he wants it rewritten; if he says yes, call tce_write_script again with replace true.',
        { ok: false, code: 'has_script', version, candidate_id: t.candidate_id },
      );
      if (t.script && !replace) return hasScript(t.script.version, t.script.status);
      const result = await call('POST', `/editorial/candidates/${t.candidate_id}/packet`, {
        replace: Boolean(replace),
        by: 'voice',
      });
      const detail = result.data?.detail;
      if (result.status === 409 && detail?.code === 'has_script') return hasScript(detail.version, detail.status);
      const already = result.status === 409 && /already being written/.test(String(detail || ''));
      if (!result.ok && !already) return spokenError(result, 'start the script');
      const replaces = already ? null : result.data?.replaces_version ?? null;
      const rewriteId = already ? null : result.data?.rewrite_id ?? null;
      track({
        kind: 'script', title: t.title, candidate_id: t.candidate_id, replaces_version: replaces,
      });
      if (Number.isInteger(replaces)) {
        // Undoable like any other change of this call, by the rewrite's id: the
        // server records it when the new script is saved, under that id.
        remember({
          kind: 'script',
          id: rewriteId,
          title: t.title,
          candidate_id: t.candidate_id,
          replaced_version: replaces,
          summary: `the new script for "${t.title}"`,
        });
      }
      const when = Number.isInteger(replaces) ? ` When it is ready it replaces version ${replaces}.` : '';
      const change = rewriteId ? ` (change ${shortId(rewriteId)}: once it is ready, undo puts back the script it replaced.)` : '';
      return reply(
        already
          ? `The script for "${t.title}" is already being written. I will say when it is ready.`
          : `Started ${replaces ? 'a new script' : 'the script'} for "${t.title}". It takes a few minutes; I will say when it is ready.${when}${change}`,
        {
          started: !already, candidate_id: t.candidate_id, replaces_version: replaces, change_id: rewriteId,
        },
      );
    },
  );

  server.tool(
    'tce_more_hooks',
    'Ask for more opening options for a topic\'s script. Returns at once; tce_jobs says when they '
      + 'are ready. The script itself does not change. Refused while a new script for the topic is '
      + `being written or waits to be finished. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: { topic: TOPIC_ID },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      if (!t.script) return reply(`"${t.title}" has no script yet, so there are no openings to add to.`, { ok: false });
      const result = await call('POST', `/editorial/packets/${t.script.packet_id}/more-hooks`);
      if (!result.ok) return spokenError(result, 'ask for more openings');
      track({ kind: 'more_hooks', title: t.title, candidate_id: t.candidate_id, packet_id: t.script.packet_id });
      return reply(`Asked for more openings for "${t.title}". I will say when they are ready.`, result.data);
    },
  );

  server.tool(
    'tce_research',
    'Research one idea in the background: what TCE already holds from his calls and commits, plus a '
      + 'web search when one is set up (the result says plainly when it is not). Returns at once; '
      + `tce_jobs reports it. ${FIND_FIRST}`,
    {
      type: 'object',
      properties: { topic: TOPIC_ID },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await byId(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', `/editorial/candidates/${t.candidate_id}/research`, { by: 'voice' });
      if (!result.ok) return spokenError(result, 'start the research');
      track({ kind: 'research', title: t.title, candidate_id: t.candidate_id, research_id: result.data.research_id });
      return reply(
        result.data.already_running
          ? `Research on "${t.title}" is already running. I will say when it is ready.`
          : `Started research on "${t.title}". I will say when it is ready.`,
        result.data,
      );
    },
  );

  const JOB_WORDS = { script: 'The script', more_hooks: 'More openings', research: 'Research' };
  const FINISHED = new Set(['done', 'ready', 'failed', 'interrupted']);

  async function jobState(job) {
    if (job.kind === 'script') {
      const r = await call('GET', `/editorial/candidates/${job.candidate_id}/packet-status`);
      if (!r.ok) return { state: 'unknown', said: 'could not be checked' };
      const j = r.data.job || {};
      // The version it really replaced is the one current when it was saved.
      if (j.state === 'done') return { state: 'done', said: 'is ready', replaced: j.result?.replaced_version ?? null };
      if (j.state === 'failed') return { state: 'failed', said: `stopped: ${j.detail || j.current_activity || 'an error'}` };
      // Written but never saved, or left queued by a restart: it waits for
      // someone to ask again, so "still going" would be waited on forever.
      if (j.state === 'interrupted') {
        return { state: 'interrupted', said: 'stopped before it was saved. Ask for it again (tce_write_script) and it picks up where it left off' };
      }
      return { state: j.state || 'running', said: `is still going (${j.current_activity || 'working'})` };
    }
    if (job.kind === 'more_hooks') {
      const r = await call('GET', `/editorial/packets/${job.packet_id}/more-hooks-status`);
      if (!r.ok) return { state: 'unknown', said: 'could not be checked' };
      if (r.data.state === 'done') return { state: 'done', said: 'are ready' };
      if (r.data.state === 'failed') return { state: 'failed', said: `stopped: ${r.data.detail || 'an error'}` };
      // The API keeps this job in memory only: after it restarts, a job we
      // started reads "idle, nothing asked for yet" and will never finish.
      if (r.data.state === 'idle') {
        return { state: 'interrupted', said: 'stopped when the server restarted. Ask for more openings again (tce_more_hooks)' };
      }
      return { state: r.data.state || 'running', said: `are still being written (${r.data.current_activity || 'working'})` };
    }
    const r = await call('GET', `/editorial/research/${job.research_id}`);
    if (!r.ok) return { state: 'unknown', said: 'could not be checked' };
    if (r.data.state === 'done') return { state: 'done', said: 'is ready', summary: r.data.summary };
    if (r.data.state === 'failed') return { state: 'failed', said: r.data.summary || 'stopped with an error' };
    return { state: 'running', said: 'is still going' };
  }

  server.tool(
    'tce_jobs',
    'What happened to the scripts, openings and research started in this call. Finished ones come '
      + 'first, so you can tell him "the new script for X is ready". Set new_only to hear only what '
      + 'finished since you last asked.',
    {
      type: 'object',
      properties: { new_only: { type: 'boolean', description: 'Only jobs that finished since the last check.' } },
    },
    async ({ new_only }) => {
      if (!ledger.jobs.length) return reply('Nothing was started in this call.', { jobs: [] });
      const rows = [];
      for (const job of ledger.jobs) {
        const s = await jobState(job);
        rows.push({ job, ...s });
      }
      const finished = rows.filter((r) => FINISHED.has(r.state));
      const running = rows.filter((r) => !FINISHED.has(r.state));
      const fresh = finished.filter((r) => !r.job.announced);
      const shown = new_only ? fresh : [...finished, ...running];
      fresh.forEach((r) => { r.job.announced = true; });
      if (fresh.length) save();
      const jobs = rows.map((r) => ({ kind: r.job.kind, title: r.job.title, candidate_id: r.job.candidate_id, state: r.state }));
      if (!shown.length) return reply('Nothing new has finished yet.', { jobs });
      const lines = shown.map((r) => {
        const base = `${JOB_WORDS[r.job.kind]} for "${r.job.title}" ${r.said}.`;
        const version = Number.isInteger(r.replaced) ? r.replaced : r.job.replaces_version;
        const replaced = r.state === 'done' && Number.isInteger(r.job.replaces_version) && Number.isInteger(version)
          ? ` It replaced version ${version}; tce_undo puts that one back.`
          : '';
        return r.summary ? `${base}${replaced} ${r.summary}` : `${base}${replaced}`;
      });
      return reply(lines.join('\n'), { jobs });
    },
  );
}
