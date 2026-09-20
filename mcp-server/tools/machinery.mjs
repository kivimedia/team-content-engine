/**
 * The machinery behind the engine: the schedules, the workers, the evidence.
 *
 * These answer "why is nothing happening", which is the question that used to
 * need SSH and a runbook.
 */
export const FAMILY = 'machinery';

export function register(server, call, { reply, failure, ago }) {
  server.tool(
    'tce_health',
    'Is the engine actually working: the API, the schedules, the cron tick and the desktop '
      + 'workers. Read-only. Ask this when something seems stuck.',
    {},
    async () => {
      const [health, schedules] = await Promise.all([
        call('GET', '/health'),
        call('GET', '/content-runs/schedule'),
      ]);
      const lines = [];
      lines.push(
        health.ok
          ? `API: ${health.data.status}, database ${health.data.database}, version ${health.data.version}.`
          : `API: not answering (${health.status}).`,
      );
      if (!schedules.ok) {
        lines.push('Schedules: could not be read.');
        return reply(lines.join('\n'), { api: health.data, schedules: null });
      }
      const rows = schedules.data.schedules || [];
      const checked = rows[0]?.last_checked_at;
      lines.push(
        checked
          ? `Cron tick: last ran ${ago(checked)} (it runs every five minutes).`
          : 'Cron tick: has never run. The VPS crontab entry may be missing.',
      );
      for (const row of rows) {
        lines.push(
          `${row.name}: ${row.enabled ? 'on' : 'OFF'}, `
            + `${row.cadence === 'daily' ? 'daily' : 'weekly'} at ${row.local_time} ${row.timezone}, `
            + `stops after ${row.final_stage}`
            + (row.due_now ? `, due now (${row.due_now})` : ''),
        );
      }
      const worker = schedules.data.worker || {};
      lines.push(
        worker.online
          ? `Workers: ${worker.online_count} online.`
          : `Workers: none. ${worker.detail || ''}`,
      );
      if (worker.capacity && worker.capacity.state !== 'available') {
        lines.push(`Capacity: ${worker.capacity.state}, retry at ${worker.capacity.retry_at || 'unknown'}.`);
      }
      return reply(lines.join('\n'), { api: health.data, schedules: rows, worker });
    },
  );

  server.tool(
    'tce_schedule',
    'Change when the engine runs by itself: the daily evidence pass and the weekly content run. '
      + 'Times are Israel time. Use it to pause ("enabled": false) or move a schedule.',
    {
      type: 'object',
      properties: {
        name: { type: 'string', enum: ['daily-evidence', 'weekly-content'], description: 'Which schedule.' },
        enabled: { type: 'boolean', description: 'On or off.' },
        local_time: { type: 'string', description: 'HH:MM in Israel time, e.g. 07:30.' },
        weekday: { type: 'number', description: 'Weekly only: 0 is Monday.' },
      },
      required: ['name', 'enabled'],
    },
    async ({ name, enabled, local_time, weekday }) => {
      const current = await call('GET', '/content-runs/schedule');
      if (!current.ok) return failure(current, 'read the schedules');
      const row = (current.data.schedules || []).find((s) => s.name === name);
      if (!row) return reply(`There is no schedule called ${name}.`, { found: false });
      const body = {
        enabled,
        cadence: row.cadence,
        weekday: weekday ?? row.weekday,
        local_time: local_time || row.local_time,
        timezone: row.timezone,
        catchup_days: row.catchup_days,
        final_stage: row.final_stage,
        window_days: row.window_days,
      };
      const result = await call('PUT', `/content-runs/schedule/${name}`, body);
      if (!result.ok) return failure(result, `change ${name}`);
      const saved = result.data;
      return reply(
        `${name} is now ${saved.enabled ? 'on' : 'off'}, `
          + `${saved.cadence === 'daily' ? 'daily' : 'weekly'} at ${saved.local_time} ${saved.timezone}.`,
        saved,
      );
    },
  );

  server.tool(
    'tce_evidence',
    'What evidence TCE holds for a window: meetings and code it collected, and how much has '
      + 'been read into moments. Read-only. Use it when a week produces no ideas.',
    {
      type: 'object',
      properties: {
        days: { type: 'number', description: 'How many days back. Default 7.' },
      },
    },
    async ({ days }) => {
      const end = new Date();
      const start = new Date(end.getTime() - (days || 7) * 86400000);
      const qs = `window_start=${start.toISOString()}&window_end=${end.toISOString()}`;
      const result = await call('GET', `/evidence/coverage?${qs}`);
      if (!result.ok) return failure(result, 'read the evidence coverage');
      // Coverage is the latest ledger per source kind, not a tally: say what
      // each pass did and when, which is what "is this week covered" means.
      const coverage = result.data.coverage || {};
      const names = {
        fathom_meeting: 'Meetings (Fathom)',
        github_commit_group: 'Code (GitHub)',
        moment_extraction: 'Reading into moments',
      };
      const lines = [`Evidence for the last ${days || 7} days:`];
      for (const [kind, row] of Object.entries(coverage)) {
        const label = names[kind] || kind;
        if (!row) {
          lines.push(`  ${label}: never collected for this window.`);
          continue;
        }
        const counts = row.counts || {};
        const interesting = ['processed', 'unchanged', 'excluded', 'failed', 'unavailable', 'sources', 'moments_stored']
          .filter((k) => typeof counts[k] === 'number' && counts[k] > 0)
          .map((k) => `${counts[k]} ${k}`)
          .join(', ');
        lines.push(
          `  ${label}: ${row.status}${row.complete ? '' : ' (incomplete)'}, `
            + `${ago(row.finished_at || row.started_at)}`
            + (interesting ? ` - ${interesting}` : '')
            + (row.complete ? '' : `\n      ${String(row.current_activity || '').slice(0, 160)}`),
        );
      }
      return reply(lines.join('\n'), result.data);
    },
  );
}
