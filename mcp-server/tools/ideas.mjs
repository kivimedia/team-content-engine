/**
 * The week's ideas and the scripts made from them.
 *
 * An idea is proposed by the engine, approved by Ziv, and only then does it
 * enter the recording queue: approval is the editorial gate, so `tce_approve`
 * is a decision, not a formality, and the tool says who approved it.
 */
export const FAMILY = 'ideas';

const HOOK_LIMIT = 3;

export function register(server, call, { reply, failure, shortId }) {
  server.tool(
    'tce_ideas',
    'The ideas TCE proposed for a week, with their rank, status and whether a script exists. '
      + 'Read-only. Use it to decide what to approve; pass week as the Monday (YYYY-MM-DD).',
    {
      type: 'object',
      properties: {
        week: { type: 'string', description: 'Monday of the week, YYYY-MM-DD. Default: whatever the engine last selected.' },
        status: { type: 'string', description: 'Only ideas in this status: proposed, selected, recorded, rejected.' },
      },
    },
    async ({ week, status }) => {
      const path = week ? `/editorial/candidates?week=${encodeURIComponent(week)}` : '/editorial/candidates';
      const result = await call('GET', path);
      if (!result.ok) return failure(result, 'read the ideas');
      let rows = result.data.candidates || [];
      if (status) rows = rows.filter((r) => r.status === status);
      rows = rows.filter((r) => !/^SYNTHETIC/i.test(r.title || ''));
      rows.sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
      if (!rows.length) {
        return reply(
          week
            ? `No ideas for the week of ${week}${status ? ` with status ${status}` : ''}.`
            : 'No ideas yet. A weekly run or a targeted request produces them.',
          { candidates: [] },
        );
      }
      const lines = rows.slice(0, 20).map((r) => {
        const rank = r.rank ? `#${r.rank}` : '  ';
        const flag = r.status === 'selected' ? ' [in the recording queue]'
          : r.status === 'recorded' ? ' [recorded]'
          : r.status === 'rejected' ? ' [rejected]' : '';
        return `${rank} ${r.title}${flag}\n     ${(r.lesson || '').slice(0, 150)}\n     id ${shortId(r.id)}`;
      });
      return reply(
        `${rows.length} idea(s)${week ? ` for the week of ${week}` : ''}:\n${lines.join('\n')}`,
        { candidates: rows.map((r) => ({ id: r.id, rank: r.rank, status: r.status, title: r.title })) },
      );
    },
  );

  server.tool(
    'tce_script',
    'One recording script in full: the chosen opening and its alternatives, the walking points, '
      + 'the spoken phrases and the Google Doc. Read-only. Give it a candidate id or the title.',
    {
      type: 'object',
      properties: {
        candidate_id: { type: 'string', description: 'The idea\'s id (or its first 8 characters).' },
        title: { type: 'string', description: 'Part of the title, if you do not have the id.' },
      },
    },
    async ({ candidate_id, title }) => {
      const queue = await call('GET', '/production/recording-queue');
      if (!queue.ok) return failure(queue, 'read the recording queue');
      const ideas = queue.data.ideas || [];
      const needle = (candidate_id || '').toLowerCase();
      const found = ideas.find((i) => (needle && String(i.candidate_id).toLowerCase().startsWith(needle))
        || (title && (i.title || '').toLowerCase().includes(title.toLowerCase())));
      if (!found) {
        return reply(
          'That script is not in the recording queue. Only approved ideas are there; '
            + 'tce_ideas shows the proposed ones and tce_approve moves one in.',
          { found: false, queue: ideas.map((i) => ({ title: i.title, candidate_id: i.candidate_id })) },
        );
      }
      const hooks = (found.hook_options || []).slice(0, HOOK_LIMIT);
      const selected = hooks.find((h) => h.id === found.selected_hook_id) || hooks[0];
      const lines = [
        found.title,
        found.big_idea ? `\n${found.big_idea}` : '',
        selected ? `\nOpening in use: "${selected.text}"\n  viewer question: ${selected.question}` : '',
      ];
      hooks.filter((h) => h !== selected).forEach((h, n) => {
        lines.push(`Alternative ${n + 1} (id ${h.id}): "${h.text}"\n  viewer question: ${h.question}`);
      });
      lines.push('\nWalking points:');
      (found.bullets || []).forEach((b, n) => lines.push(`  ${n + 1}. ${b}`));
      lines.push(`\n${(found.script_phrases || []).length} spoken phrases, packet v${found.packet_version}.`);
      return reply(lines.filter(Boolean).join('\n'), {
        candidate_id: found.candidate_id,
        packet_id: found.packet_id,
        packet_version: found.packet_version,
        hook_options: found.hook_options,
        selected_hook_id: found.selected_hook_id,
        bullets: found.bullets,
        script_phrases: found.script_phrases,
      });
    },
  );

  server.tool(
    'tce_approve',
    'Approve an idea so it enters the recording queue, or reject it. This is Ziv\'s editorial '
      + 'judgement and it trains future selection, so say who is approving: pass approver "ziv" '
      + 'only when Ziv actually said so, otherwise "claude".',
    {
      type: 'object',
      properties: {
        candidate_id: { type: 'string', description: 'The idea\'s id (full uuid).' },
        decision: { type: 'string', enum: ['approve', 'reject'], description: 'approve puts it in the queue; reject removes it from selection.' },
        approver: { type: 'string', enum: ['ziv', 'claude'], description: 'Whose judgement this is. Default claude.' },
        note: { type: 'string', description: 'Why. Worth writing: it is what the engine learns from.' },
      },
      required: ['candidate_id', 'decision'],
    },
    async ({ candidate_id, decision, approver, note }) => {
      const who = approver === 'ziv' ? 'ziv' : 'claude-terminal';
      const body = {
        kind: decision === 'reject' ? 'gate_reject' : 'approve',
        note: note || (approver === 'ziv' ? null : 'Approved from the TCE terminal; Ziv has not judged this idea yet.'),
        created_by: who,
      };
      const result = await call('POST', `/editorial/candidates/${candidate_id}/feedback`, body);
      if (!result.ok) return failure(result, `${decision} that idea`);
      return reply(
        decision === 'approve'
          ? `Approved as ${who}. It is now in the recording queue at https://bot.kivimedia.co/tce/record`
          : `Rejected as ${who}. It will not be offered for recording.`,
        { candidate_id, decision, created_by: who },
      );
    },
  );

  server.tool(
    'tce_choose_opening',
    'Switch a script to one of its other openings. Creates a new immutable packet version; '
      + 'refused while a take set for that script already has clips.',
    {
      type: 'object',
      properties: {
        candidate_id: { type: 'string', description: 'The idea\'s id (full uuid).' },
        hook_id: { type: 'string', description: 'The opening to use, from tce_script (h1, h2, h3).' },
      },
      required: ['candidate_id', 'hook_id'],
    },
    async ({ candidate_id, hook_id }) => {
      const result = await call('POST', `/production/candidates/${candidate_id}/choose-hook`, { hook_id });
      if (!result.ok) return failure(result, 'change the opening');
      const packet = result.data.packet || result.data;
      return reply(
        `Opening changed. Packet is now v${packet.version ?? '?'}; the rest of the script is unchanged.`,
        { packet_id: packet.id, version: packet.version, selected_hook_id: packet.selected_hook_id },
      );
    },
  );
}
