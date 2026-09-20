/**
 * Making the engine produce something, and seeing what it is doing.
 *
 * Producing is safe to repeat: TCE deduplicates by the hour and by the scope,
 * so two asks in the same hour resume the same run rather than starting a
 * second one. Nothing here invokes a metered provider; every language model
 * call runs on the subscription worker.
 */
export const FAMILY = 'runs';

export function register(server, call, { reply, failure, shortId, runLine, RUN_WORDS }) {
  server.tool(
    'tce_produce_now',
    'Produce this week\'s scripts from the last seven days of meetings and code. Safe to repeat: '
      + 'the same hour returns the same run. Runs on the subscription worker, never a paid API.',
    {
      type: 'object',
      properties: {
        days: { type: 'number', description: 'How many days back to cover. Default 7.' },
        packets: { type: 'number', description: 'How many scripts to write. Default 3.' },
      },
    },
    async ({ days, packets }) => {
      const end = new Date();
      const start = new Date(end.getTime() - (days || 7) * 86400000);
      const body = {
        idempotency_key: `tce-terminal:${end.toISOString().slice(0, 13)}`,
        scope_kind: 'week',
        window_start: start.toISOString(),
        window_end: end.toISOString(),
        maximum_candidate_count: 6,
        target_packet_count: packets || 3,
        trigger_origin: 'produce_now',
        actor: 'tce-terminal',
      };
      const result = await call('POST', '/content-runs/produce-now', body);
      if (!result.ok) return failure(result, 'start a run');
      const run = result.data;
      return reply(
        `Run ${shortId(run.id)} is ${RUN_WORDS[run.state] || run.state}. `
          + `It covers ${(days || 7)} days and aims for ${packets || 3} scripts. `
          + 'Ask tce_run for progress; nothing is lost if you close the session.',
        { id: run.id, state: run.state, focused_path: run.focused_path },
      );
    },
  );

  server.tool(
    'tce_request',
    'Ask for a script from a particular meeting, in plain words - "make a script from the call '
      + 'with Dovid yesterday". If several meetings match you get a choice; answer it by calling '
      + 'again with source_id. If the day was never collected, TCE collects it once before saying no.',
    {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'The request, naming the person: "the Fathom with Dovid yesterday is sick. Make a script".' },
        source_id: { type: 'string', description: 'The chosen meeting, when answering a previous choice.' },
        key: { type: 'string', description: 'Idempotency key. Reuse the same one when answering a choice.' },
      },
      required: ['text'],
    },
    async ({ text, source_id, key }) => {
      const body = {
        text,
        idempotency_key: key || `tce-terminal:${text.slice(0, 40)}:${new Date().toISOString().slice(0, 13)}`,
        ...(source_id ? { source_id } : {}),
      };
      const result = await call('POST', '/content-runs/from-claude/request', body);
      if (!result.ok) return failure(result, 'resolve that request');
      const data = result.data;
      if (data.status === 'needs_source_choice') {
        const lines = (data.choices || []).map(
          (c) => `  - ${c.occurred_at?.slice(0, 16)} ${c.title} (${(c.participants || []).join(', ')})\n    source_id ${c.source_id}`,
        );
        return reply(
          `Several meetings match. Call tce_request again with the same key `
            + `("${body.idempotency_key}") and one of these source_ids:\n${lines.join('\n')}`,
          { status: 'needs_source_choice', key: body.idempotency_key, choices: data.choices },
        );
      }
      const source = data.source || {};
      return reply(
        `Run ${shortId(data.id)} started from "${source.title}" (${source.local_date})`
          + `${data.refreshed_that_date ? ', after collecting that day' : ''}. `
          + `It is ${RUN_WORDS[data.state] || data.state}.`,
        { id: data.id, state: data.state, source, focused_path: data.focused_path },
      );
    },
  );

  server.tool(
    'tce_runs',
    'Recent runs and what each is doing or waiting for. Read-only.',
    {
      type: 'object',
      properties: { limit: { type: 'number', description: 'How many. Default 8.' } },
    },
    async ({ limit }) => {
      const result = await call('GET', `/content-runs?limit=${limit || 8}`);
      if (!result.ok) return failure(result, 'read the runs');
      const rows = result.data.runs || [];
      if (!rows.length) return reply('No runs yet.', { runs: [] });
      return reply(
        rows.map((r) => runLine(r)).join('\n'),
        { runs: rows.map((r) => ({ id: r.id, state: r.state, stage: r.current_stage, label: r.week_label, detail: r.error_detail })) },
      );
    },
  );

  server.tool(
    'tce_run',
    'One run in detail: every step, what finished, what it is waiting for and why.',
    {
      type: 'object',
      properties: { run_id: { type: 'string', description: 'The run id (or its first 8 characters).' } },
      required: ['run_id'],
    },
    async ({ run_id }) => {
      let id = run_id;
      if (id.length < 36) {
        const list = await call('GET', '/content-runs?limit=20');
        if (!list.ok) return failure(list, 'find that run');
        const match = (list.data.runs || []).find((r) => String(r.id).startsWith(id));
        if (!match) return reply(`No recent run starts with ${id}.`, { found: false });
        id = match.id;
      }
      const result = await call('GET', `/content-runs/${id}`);
      if (!result.ok) return failure(result, 'read that run');
      const run = result.data;
      const steps = (run.stages || []).map((s) => {
        const mark = s.status === 'succeeded' ? 'done' : s.status;
        const why = s.error_detail ? ` - ${String(s.error_detail).slice(0, 140)}` : '';
        return `  ${s.stage}: ${mark}${why}`;
      });
      return reply(
        `${runLine(run)}\n${steps.join('\n')}\n`
          + `Open it: https://bot.kivimedia.co/tce${run.focused_path || ''}`,
        { id: run.id, state: run.state, stages: run.stages, focused_path: run.focused_path },
      );
    },
  );

  server.tool(
    'tce_resume_run',
    'Unstick a run that stopped or is parked: it retries the step it is on. Safe - finished '
      + 'steps and completed jobs are never redone.',
    {
      type: 'object',
      properties: { run_id: { type: 'string', description: 'The run id (full uuid).' } },
      required: ['run_id'],
    },
    async ({ run_id }) => {
      const result = await call('POST', `/content-runs/${run_id}/resume`);
      if (!result.ok) return failure(result, 'resume that run');
      return reply(`Run ${shortId(run_id)} is resuming. Ask tce_run in a minute.`, result.data);
    },
  );
}
