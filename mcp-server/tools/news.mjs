/**
 * The third lane from the terminal: "News that excites Ziv".
 *
 * Three questions he actually asks. Is this announcement worth anything to me?
 * What does TCE think my world is? Are the feeds alive, or is it just quiet?
 * None of these starts a weekly run; tce_news_check queues at most ONE appraisal,
 * and only when the announcement matched something of his.
 */
export const FAMILY = 'news';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function register(server, call, { reply, failure, shortId }) {
  server.tool(
    'tce_news_check',
    'Ask whether one announcement is worth anything to Ziv. Give the URL of the announcement itself '
      + '(a release note, a changelog, a pricing page) - not a news site\'s write-up of it, which is '
      + 'refused. Says at once what it matched in his work, or why it matched nothing. If it matched, '
      + 'one appraisal runs and this tool waits briefly for the verdict.',
    {
      type: 'object',
      properties: {
        url: { type: 'string', description: 'The announcement itself.' },
        wait_seconds: { type: 'number', description: 'How long to wait for the verdict. Default 60.' },
      },
      required: ['url'],
    },
    async ({ url, wait_seconds }) => {
      const started = await call('POST', '/news/check', { url });
      if (!started.ok) return failure(started, 'check the announcement');
      const first = started.data;

      if (first.status !== 'matched') {
        const said = {
          unverified: first.why,
          unreachable: first.why,
          no_match: `Nothing of yours is touched by this, so it goes no further. ${first.why}`
            + (first.checked ? ` (checked ${first.checked}).` : '.'),
        }[first.status] || first.why;
        return reply(said, first);
      }

      const lines = [`It matched: ${first.why}.`, 'Appraising it now...'];
      const deadline = Date.now() + 1000 * Math.max(5, Math.min(wait_seconds ?? 60, 300));
      let latest = null;
      while (Date.now() < deadline) {
        const status = await call('GET', `/news/items/${first.item_id}`);
        if (status.ok && status.data.appraisal) {
          latest = status.data;
          break;
        }
        await sleep(4000);
      }

      if (!latest) {
        lines.push(
          `No verdict yet (the appraisal waits for the subscription worker). `
            + `Item ${shortId(first.item_id)}; it will be on the Timely tab or in the next weekly set.`,
        );
        return reply(lines.join('\n'), first);
      }

      const a = latest.appraisal;
      lines.pop();
      lines.push(`Verdict: ${a.verdict}. ${a.reason || ''}`.trim());
      if (a.verdict === 'publish') {
        if (a.format) lines.push(`Shape: ${a.format.replace(/_/g, ' ')}.`);
        if (a.expires_at) lines.push(`Worth saying until ${new Date(a.expires_at).toDateString()}.`);
        if (a.do_differently?.length) lines.push(`What an owner should do: ${a.do_differently[0]}`);
      }
      lines.push(a.next);
      return reply(lines.join('\n'), latest);
    },
  );

  server.tool(
    'tce_news',
    'What the news lane believes and is doing: whether it is on, how many anchors it matches '
      + 'against, the watchlist, and any feed that is down. Read-only.',
    { type: 'object', properties: {} },
    async () => {
      const result = await call('GET', '/news/overview');
      if (!result.ok) return failure(result, 'read the news lane');
      const d = result.data;
      const kinds = Object.entries(d.anchors || {})
        .map(([kind, list]) => `${list.length} ${kind.replace('_', ' ')}`)
        .join(', ');
      const lines = [
        d.lane_on ? 'The news lane is ON.' : 'The news lane is OFF: nothing is fetched or matched on schedule.',
        `Matching against ${d.anchor_count} anchors${kinds ? ` (${kinds})` : ''}.`,
        `${(d.standing_facts || []).length} standing facts.`,
      ];
      if (d.feed_alarms?.length) lines.push('Feeds needing attention:', ...d.feed_alarms.map((l) => `  ${l}`));
      if (d.watchlist?.length) {
        lines.push(`Watching ${d.watchlist.length} item(s) that do not connect yet:`);
        for (const w of d.watchlist.slice(0, 8)) lines.push(`  - ${w.title}`);
      } else {
        lines.push('Nothing on the watchlist.');
      }
      return reply(lines.join('\n'), d);
    },
  );

  server.tool(
    'tce_news_feeds',
    'Every news feed with its last result. Tells a quiet feed from a dead one. Read-only.',
    { type: 'object', properties: {} },
    async () => {
      const result = await call('GET', '/news/overview');
      if (!result.ok) return failure(result, 'read the feeds');
      const feeds = result.data.feeds || [];
      if (!feeds.length) return reply('No feeds registered yet.', { feeds: [] });
      const lines = feeds.map((f) => {
        const state = f.down ? `DOWN, ${f.consecutive_failures} failures in a row (${f.error || 'no reason'})`
          : f.status || 'not fetched yet';
        return `${f.down ? '!!' : '  '} [${f.tier}] ${f.name}: ${state}`;
      });
      const down = feeds.filter((f) => f.down).length;
      return reply(
        `${feeds.length} feeds, ${down ? `${down} DOWN` : 'none down'}:\n${lines.join('\n')}`,
        { feeds },
      );
    },
  );
}
