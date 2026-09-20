/**
 * The one call that answers "where does TCE stand".
 *
 * Everything else in this server is a follow-up to something this says. It
 * reads only: nothing here starts work or spends a job.
 */
export const FAMILY = 'briefing';

export function register(server, call, { reply, failure, shortId, ago, runLine }) {
  server.tool(
    'tce_briefing',
    'Where the Team Content Engine stands right now: scripts ready to record, runs in flight '
      + 'and what each is waiting for, the schedules, and whether the machinery is running. '
      + 'Read-only. Ask for this first when someone says "what is happening with TCE".',
    {},
    async () => {
      const [queue, runs, schedules] = await Promise.all([
        call('GET', '/production/recording-queue'),
        call('GET', '/content-runs?limit=8'),
        call('GET', '/content-runs/schedule'),
      ]);
      if (!queue.ok) return failure(queue, 'read the recording queue');
      if (!runs.ok) return failure(runs, 'read the content runs');

      const ideas = queue.data.ideas || [];
      const real = ideas.filter((i) => !/^SYNTHETIC/i.test(i.title || ''));
      const lines = [];

      lines.push(
        real.length
          ? `Ready to record (${real.length}):`
          : 'Nothing is ready to record. Ideas enter the queue only after you approve them.',
      );
      for (const idea of real) {
        const hooks = (idea.hook_options || []).length;
        const opening = hooks ? `, ${hooks} openings to choose from` : '';
        const session = idea.active_session_status ? `, session ${idea.active_session_status}` : '';
        lines.push(
          `  - ${idea.title} (${(idea.bullets || []).length} points, `
            + `${(idea.script_phrases || []).length} phrases${opening}${session})`,
        );
      }

      const active = (runs.data.runs || []).filter(
        (r) => !['ready', 'failed', 'cancelled'].includes(r.state),
      );
      const ready = (runs.data.runs || []).filter((r) => r.state === 'ready');
      const failed = (runs.data.runs || []).filter((r) => r.state === 'failed');
      lines.push('');
      lines.push(active.length ? `In flight (${active.length}):` : 'No run is in flight.');
      for (const run of active) lines.push(`  - ${runLine(run)}`);
      if (failed.length) {
        lines.push(`Stopped (${failed.length}):`);
        for (const run of failed) lines.push(`  - ${runLine(run)}`);
      }
      if (ready.length) {
        lines.push(`Finished recently: ${ready.map((r) => shortId(r.id)).join(', ')}`);
      }

      if (schedules.ok) {
        lines.push('');
        for (const row of schedules.data.schedules || []) {
          const last = row.recent_occurrences?.[0];
          const when = row.cadence === 'daily'
            ? `every day at ${row.local_time}`
            : `Mondays at ${row.local_time}`;
          lines.push(
            `${row.name}: ${row.enabled ? when : 'disabled'}`
              + (last ? `, last ${last.occurrence_key} (${last.state})` : ', no occurrence yet'),
          );
        }
        const worker = schedules.data.worker;
        if (worker) {
          lines.push(
            worker.online
              ? `Workers: ${worker.online_count} online.`
              : `Workers: none online. ${worker.detail}`,
          );
        }
        const checked = schedules.data.schedules?.[0]?.last_checked_at;
        if (checked) lines.push(`Cron last ticked ${ago(checked)}.`);
      }

      return reply(lines.join('\n'), {
        ready_to_record: real.map((i) => ({
          title: i.title,
          candidate_id: i.candidate_id,
          packet_id: i.packet_id,
          hooks: (i.hook_options || []).length,
        })),
        runs: (runs.data.runs || []).map((r) => ({
          id: r.id,
          state: r.state,
          stage: r.current_stage,
          label: r.week_label,
          detail: r.error_detail,
        })),
        schedules: schedules.ok ? schedules.data.schedules : undefined,
        worker: schedules.ok ? schedules.data.worker : undefined,
      });
    },
  );
}
