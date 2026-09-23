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
export const FAMILY = 'voice';

// What this call has done, newest last. One process is one call, so "undo the
// last thing I changed" means the last entry here, never someone else's edit.
const ledger = { writes: [], jobs: [] };

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

export function register(server, call, { reply, failure, shortId }) {
  /** One topic by id or words; a reply to return instead when it is not exactly one. */
  async function resolve(topic) {
    if (!topic) return { stop: reply('Which topic? Say part of its title.', { status: 'none' }) };
    const result = await call('GET', `/editorial/voice/topic?q=${encodeURIComponent(topic)}`);
    if (!result.ok) return { stop: failure(result, 'find that topic') };
    const d = result.data;
    if (d.status === 'found') return { topic: d.topic };
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

  function spokenError(result, what) {
    const detail = result.data?.detail;
    if (result.status === 409 && detail && typeof detail === 'object') {
      const now = detail.current;
      if (typeof now === 'string') {
        return reply(
          `${detail.message} It now says: "${now}". Read him the current text and ask again.`,
          { ok: false, code: detail.code, current: now },
        );
      }
      return reply(`${detail.message}`, { ok: false, code: detail.code, current: now ?? null });
    }
    if (detail && typeof detail === 'object' && detail.message) {
      return reply(`Could not ${what}: ${detail.message}`, { ok: false, code: detail.code, status: result.status });
    }
    return failure(result, what);
  }

  function remember(entry) {
    ledger.writes.push({ ...entry, at: new Date().toISOString(), undone: false });
  }

  function track(job) {
    ledger.jobs.push({ ...job, started: new Date().toISOString(), announced: false });
  }

  // ------------------------------------------------------------------ read

  server.tool(
    'tce_week',
    'This week at a glance: the recording list in order with each script\'s state, and the ideas '
      + 'still waiting for a decision. Read-only. Start here when he says "the week".',
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
      if (reserve.length) lines.push(`${reserve.length} more in reserve.`);
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
      + 'script lines and the numbered opening options). Give an id or a few words of the title. '
      + 'If the words match more than one, it lists them so you can ask which. The text is for you; '
      + 'read aloud only the part he asked about.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const lines = [`${t.title} (id ${t.short_id})`];
      const state = t.put_away ? 'Put away.'
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
      + 'new text comes back. Returns a change id; tce_undo takes it back.',
    {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Id, short id, or words from the title.' },
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
      const found = await resolve(topic);
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
      return reply(`Done. ${d.said.join(' ')}${warn} (change ${d.short_id}; undo takes it back.)`, d);
    },
  );

  server.tool(
    'tce_decide',
    'Decide a topic: this_week (approve it into this week\'s list), discuss, later, or away. '
      + 'For away, prefer tce_put_away, and confirm the title by name first.',
    {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Id, short id, or words from the title.' },
        decision: { type: 'string', description: 'this_week, discuss, later or away. "approve" means this_week.' },
        note: { type: 'string', description: 'Why, in his words, if he said.' },
      },
      required: ['topic', 'decision'],
    },
    async ({ topic, decision, note }) => {
      const wanted = DECISIONS[clean(decision)] || DECISIONS[decision];
      if (!wanted) return reply(`"${decision}" is not a decision. Use this_week, discuss, later or away.`, { ok: false });
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', `/editorial/topics/${t.candidate_id}/decide`, { decision: wanted, note, by: 'voice' });
      if (!result.ok) return spokenError(result, 'decide that topic');
      remember({ kind: 'decision', candidate_id: t.candidate_id, title: t.title, decision: wanted, previous: result.data.previous_decision });
      const said = {
        this_week: `"${t.title}" is in this week's list${result.data.placed ? `, place ${result.data.placed.rank}` : ''}.`,
        discuss: `"${t.title}" is marked to think about.`,
        later: `"${t.title}" is saved for later.`,
        away: `"${t.title}" is put away. It can be brought back.`,
      }[wanted];
      return reply(said, result.data);
    },
  );

  server.tool(
    'tce_put_away',
    'Put an idea away (it stops being offered). Restorable with tce_restore_idea. Say the title back '
      + 'to him and get a yes before calling this.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      if (t.put_away) return reply(`"${t.title}" is already put away.`, { candidate_id: t.candidate_id });
      const result = await call('POST', `/editorial/topics/${t.candidate_id}/decide`, { decision: 'away', by: 'voice' });
      if (!result.ok) return spokenError(result, 'put that idea away');
      remember({ kind: 'decision', candidate_id: t.candidate_id, title: t.title, decision: 'away', previous: result.data.previous_decision });
      return reply(`Put away: "${t.title}". It can be brought back.`, result.data);
    },
  );

  server.tool(
    'tce_restore_idea',
    'Bring a put-away idea back to where it was before it was put away.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const result = await call('POST', `/editorial/topics/${found.topic.candidate_id}/restore`, { by: 'voice' });
      if (!result.ok) return spokenError(result, 'bring that idea back');
      return reply(result.data.said, result.data);
    },
  );

  server.tool(
    'tce_choose_hook',
    'Use a different opening for a script: option is the number from tce_topic\'s opening options '
      + '(1, 2, 3). The script\'s opening line becomes that option. Undoable.',
    {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Id, short id, or words from the title.' },
        option: { type: 'string', description: 'The option number (1, 2, 3) or its id.' },
      },
      required: ['topic', 'option'],
    },
    async ({ topic, option }) => {
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', '/editorial/voice/change', {
        candidate_id: t.candidate_id,
        target: 'script',
        operations: [{ op: 'choose_hook', after: String(option) }],
        summary: `Opening ${option} for "${t.title}"`,
        by: 'voice',
      });
      if (!result.ok) return spokenError(result, 'change the opening');
      const d = result.data;
      remember({ kind: 'change', id: d.change_set_id, title: t.title, summary: `opening ${option}` });
      const line = d.changes.find((c) => c.field === 'script_phrases.0');
      return reply(
        `Done. The opening is now option ${option}${line ? `: "${line.after}"` : ''}. (change ${d.short_id})`,
        d,
      );
    },
  );

  server.tool(
    'tce_reorder_week',
    'Move a topic in this week\'s list: first, up, down, last, reserve, primary, remove, or a '
      + 'position number. Undoable.',
    {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Id, short id, or words from the title.' },
        move: { type: 'string', description: 'first, up, down, last, reserve, primary, remove, or a number like "2".' },
      },
      required: ['topic', 'move'],
    },
    async ({ topic, move }) => {
      const key = clean(move);
      const spec = MOVES[key] || (/^\d+$/.test(key) ? { action: 'rank', rank: Number(key) } : null);
      if (!spec) return reply(`"${move}" is not a move. Use first, up, down, last, reserve, remove or a number.`, { ok: false });
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', '/editorial/voice/change', {
        candidate_id: t.candidate_id,
        target: 'week',
        operations: [{ op: 'move_topic', after: { ...spec, candidate_id: t.candidate_id } }],
        summary: `Move "${t.title}" ${key}`,
        by: 'voice',
      });
      if (!result.ok) return spokenError(result, 'move that topic');
      const d = result.data;
      remember({ kind: 'change', id: d.change_set_id, title: t.title, summary: d.said.join(' ') });
      return reply(`Done. ${d.said.join(' ')} (change ${d.short_id})`, d);
    },
  );

  server.tool(
    'tce_undo',
    'Take back a change. With no id it takes back the last thing changed in THIS call. With an id '
      + '(the change id a tool returned) it takes back that one. Refuses, with the current text, if '
      + 'the same part was changed again since.',
    {
      type: 'object',
      properties: { change_id: { type: 'string', description: 'Optional. The change id (or its first 8 characters).' } },
    },
    async ({ change_id }) => {
      let entry;
      if (change_id) {
        entry = [...ledger.writes].reverse().find((w) => w.kind === 'change' && String(w.id).startsWith(change_id));
        if (!entry) {
          if (/^[0-9a-f-]{36}$/i.test(change_id)) {
            entry = { kind: 'change', id: change_id };
          } else {
            const recent = await call('GET', '/editorial/voice/activity?hours=24');
            const hit = recent.ok && (recent.data.items || []).find((i) => i.kind === 'change' && String(i.id).startsWith(change_id));
            if (!hit) return reply(`I have no change ${change_id} from the last day.`, { ok: false });
            entry = { kind: 'change', id: hit.id, title: hit.title };
          }
        }
      } else {
        entry = [...ledger.writes].reverse().find((w) => !w.undone);
        if (!entry) return reply('Nothing has been changed in this call, so there is nothing to undo.', { ok: false });
      }

      if (entry.kind === 'decision') {
        let result;
        if (entry.decision === 'away') {
          result = await call('POST', `/editorial/topics/${entry.candidate_id}/restore`, { by: 'voice' });
        } else if (entry.previous) {
          result = await call('POST', `/editorial/topics/${entry.candidate_id}/decide`, { decision: entry.previous, by: 'voice' });
        } else {
          return reply(`"${entry.title}" had no decision before, so there is nothing to go back to. Decide it again instead.`, { ok: false });
        }
        if (!result.ok) return spokenError(result, 'undo that decision');
        entry.undone = true;
        return reply(`Undone. "${entry.title}" is back where it was.`, result.data);
      }

      const result = await call('POST', `/editorial/change-sets/${entry.id}/undo`, { by: 'voice' });
      if (!result.ok) return spokenError(result, 'undo that change');
      entry.undone = true;
      return reply(result.data.said, result.data);
    },
  );

  // ------------------------------------------------------------------ jobs

  server.tool(
    'tce_write_script',
    'Start writing the script for a topic. Takes a few minutes on his PC worker; this returns at '
      + 'once. Tell him it has started; tce_jobs says when it is ready.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
      if (found.stop) return found.stop;
      const t = found.topic;
      const result = await call('POST', `/editorial/candidates/${t.candidate_id}/packet`);
      const already = result.status === 409 && /already being written/.test(String(result.data?.detail || ''));
      if (!result.ok && !already) return spokenError(result, 'start the script');
      track({ kind: 'script', title: t.title, candidate_id: t.candidate_id });
      return reply(
        already
          ? `The script for "${t.title}" is already being written. I will say when it is ready.`
          : `Started the script for "${t.title}". It takes a few minutes; I will say when it is ready.`,
        { started: !already, candidate_id: t.candidate_id },
      );
    },
  );

  server.tool(
    'tce_more_hooks',
    'Ask for more opening options for a topic\'s script. Returns at once; tce_jobs says when they '
      + 'are ready. The script itself does not change.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
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
      + 'tce_jobs reports it.',
    {
      type: 'object',
      properties: { topic: { type: 'string', description: 'Id, short id, or words from the title.' } },
      required: ['topic'],
    },
    async ({ topic }) => {
      const found = await resolve(topic);
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
      if (j.state === 'done') return { state: 'done', said: 'is ready' };
      if (j.state === 'failed') return { state: 'failed', said: `stopped: ${j.detail || j.current_activity || 'an error'}` };
      return { state: j.state || 'running', said: `is still going (${j.current_activity || 'working'})` };
    }
    if (job.kind === 'more_hooks') {
      const r = await call('GET', `/editorial/packets/${job.packet_id}/more-hooks-status`);
      if (!r.ok) return { state: 'unknown', said: 'could not be checked' };
      if (r.data.state === 'done') return { state: 'done', said: 'are ready' };
      if (r.data.state === 'failed') return { state: 'failed', said: `stopped: ${r.data.detail || 'an error'}` };
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
      if (!shown.length) return reply('Nothing new has finished yet.', { jobs: [] });
      const lines = shown.map((r) => {
        const base = `${JOB_WORDS[r.job.kind]} for "${r.job.title}" ${r.said}.`;
        return r.summary ? `${base} ${r.summary}` : base;
      });
      return reply(lines.join('\n'), {
        jobs: rows.map((r) => ({ kind: r.job.kind, title: r.job.title, candidate_id: r.job.candidate_id, state: r.state })),
      });
    },
  );
}
