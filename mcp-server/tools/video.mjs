/**
 * The editor's voice tools: talk to the editor (design of 30-Sep, section 4).
 *
 * He watches an edit in the notes sheet, pauses, holds a button and says what is
 * wrong. The sheet pins the paused second to TCE the moment he presses (the
 * second is the page's, never a model's) and saves his words on that note. These
 * tools are the call brain's side of it:
 *
 *   tce_video_moment         read the note: the second, his words, the words of the
 *                            video around it, his earlier notes, and his standing
 *                            rules for the editor on the first call
 *   tce_video_note           save a one-line reading of the note and get the line
 *                            to say back (or take the note back); never renders
 *   tce_video_notes          the notes of this sitting and where each stands
 *   tce_video_make           the read-back and its check code, then, on his yes,
 *                            one job reads every note and the video renders once
 *   tce_video_undo_version   the read-back, then, on his yes, the version from
 *                            before his notes comes back
 *
 * Save, then say back (not ask, then save): nothing renders until he says make it,
 * and that one irreversible step has its own read-back, check code and undo.
 *
 * Nothing here opens a sitting or pins a note: only his sheet does. A sitting is
 * found with a read that leaves its heartbeat alone (GET /recordings/{id}/talk).
 */
import { createHash } from 'node:crypto';

import { idText, trackJob } from './voice.mjs';

export const FAMILY = 'voice';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// A whole id, or its first 8 characters or more.
const SOME_ID = /^[0-9a-f]{8}[0-9a-f-]{0,28}$/;

const NOTE_STATE = {
  listening: 'his words are on their way',
  held: 'saved, waiting for make it',
  done: 'done',
  needs_you: 'needs him',
  rejected: 'taken back',
};

const sentence = (text) => String(text ?? '').replace(/\s+/g, ' ').trim().replace(/[.!?;,:]+$/, '');
const upperFirst = (text) => (text ? text[0].toUpperCase() + text.slice(1) : text);

function clip(text, max) {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 3).trimEnd()}...` : t;
}

/*
 * The reading is what he wants, without the time: the read-back and the said-back
 * line put the time in front ("at 0:38: ..."), so a reading that starts with it
 * would be said twice ("At 0:38: At 0:38 you want ...").
 */
export function oneLine(understood) {
  return sentence(understood)
    .replace(/^at\s+\d+:\d{2}\s*[:,-]?\s*/i, '')
    .slice(0, 400)
    .trim();
}

/** The line he hears after a note is saved: names the time, says nothing changed yet. */
export function saidBack(where, understood) {
  return `${upperFirst(where)}: ${oneLine(understood)}. Saved; nothing changes until you say make it.`;
}

/** The check code of a going-back read-back: a yes only goes back to what he heard. */
export function undoCheck(sessionId, readBack) {
  return createHash('sha256').update(`${sessionId}\n${readBack}`).digest('hex').slice(0, 12);
}

function noteLine(n) {
  const what = sentence(n.understood) || (sentence(n.request) ? `he said "${sentence(n.request)}"` : 'no words yet');
  const result = n.result || {};
  const outcome = n.state === 'needs_you' && result.question ? `: ${sentence(result.question)}`
    : n.state === 'done' && result.reply ? `: ${clip(sentence(result.reply), 160)}` : '';
  return `${n.where}: ${what} (${NOTE_STATE[n.state] || n.state}${outcome})`;
}

export function register(server, call, { reply, failure }) {
  // Which sitting each note is in, learned from every read, so tce_video_note can
  // save by the note id alone.
  const sittingOf = new Map();
  // The rules go with the first moment of this process (a respawned brain starts
  // without them, and so does this process).
  let rulesGiven = false;

  const learn = (sitting) => {
    for (const n of sitting?.notes || []) sittingOf.set(n.id, sitting.session_id);
  };

  /** A refusal from TCE, said plainly, with what to do instead when TCE says it. */
  function refused(result, what, more = '') {
    const d = result.data?.detail;
    if (d && typeof d === 'object' && typeof d.message === 'string') {
      const msg = /[.!?]$/.test(d.message.trim()) ? d.message.trim() : `${d.message.trim()}.`;
      return reply(`${msg}${more ? ` ${more}` : ''}`, { ok: false, code: d.code, status: result.status });
    }
    return failure(result, what);
  }

  /** The video and its sittings, by the id his call opened with (or a short id). */
  async function findVideo(video) {
    // As his call's context names it ("video:<id>"), or the id alone.
    const id = idText(String(video ?? '').replace(/^\s*video\s*:\s*/i, ''));
    if (!SOME_ID.test(id)) {
      return { stop: reply(`A video is named by its id, not by words ("${String(video ?? '')}" is not an id). `
        + 'Use the id his call opened with (video:<id>), or find it with tce_recordings. Nothing was done.',
      { ok: false, code: 'id_required' }) };
    }
    let full = id;
    if (!UUID.test(id)) {
      const lib = await call('GET', '/production/library?filter=all');
      if (!lib.ok) return { stop: failure(lib, 'find that video') };
      const hits = (lib.data?.items || []).filter((v) => String(v.upload_id).startsWith(id));
      if (hits.length !== 1) {
        return { stop: reply(hits.length ? `More than one video starts with "${id}"; use its whole id. Nothing was done.`
          : `No recorded video has the id "${id}". Use the id his call opened with. Nothing was done.`,
        { ok: false, code: 'unknown_video' }) };
      }
      full = String(hits[0].upload_id);
    }
    const r = await call('GET', `/production/recordings/${full}/talk`);
    if (!r.ok) {
      if (r.status === 404) {
        return { stop: reply(`No recorded video has the id "${id}". Use the id his call opened with. Nothing was done.`,
          { ok: false, code: 'unknown_video' }) };
      }
      return { stop: failure(r, 'read the notes on that video') };
    }
    learn(r.data.live);
    learn(r.data.made);
    return { found: r.data };
  }

  /** The sitting he is giving notes in on this video, or what to say instead. */
  async function takingNotes(video) {
    const f = await findVideo(video);
    if (f.stop) return f;
    const v = f.found;
    const s = v.live;
    if (!s) {
      return { stop: reply(`No notes are open on "${v.title}" right now. He gives notes in the video's notes sheet `
        + 'in the Library: pause, hold the button, talk. Nothing was done.',
      { ok: false, code: 'no_sitting', video: v.upload_id }) };
    }
    if (s.state !== 'open') {
      const step = sentence(s.state === 'rendering' ? s.video_step || s.result?.status : s.result?.status);
      return { stop: reply(`His notes on "${v.title}" are being made into a new version right now`
        + `${step ? ` (${step})` : ''}. New notes can be given once it is done; tce_video_notes says where it stands.`,
      { ok: false, code: 'being_made', video: v.upload_id, session_id: s.session_id, state: s.state }) };
    }
    return { video: v, sitting: s };
  }

  /** A note id as the brain passed it (whole or short), matched in the sitting. */
  function noteIn(sitting, note) {
    const id = idText(note);
    if (!SOME_ID.test(id)) return { stop: 'id_required' };
    const hits = (sitting.notes || []).filter((n) => n.id.startsWith(id));
    if (hits.length === 1) return { note: hits[0] };
    return { stop: hits.length ? 'ambiguous' : 'unknown' };
  }

  const NOTE_ID = {
    type: 'string',
    description: 'The note id, as tce_video_moment or tce_video_notes gave it. Never words.',
  };
  const VIDEO_ID = {
    type: 'string',
    description: 'The video id his call opened with (video:<id>), or its short id. Never words.',
  };

  server.tool(
    'tce_video_moment',
    'START HERE for every note he gives on a video he is reviewing (his call opened on video:<id>). '
      + 'Reads one note: the second he paused at, his words, the words of the video around that second '
      + '(cut words and joins marked), what his phone or the edit did to a word, his earlier notes on this '
      + 'video, and, the first time, his standing rules for the editor. It waits a few seconds when his '
      + 'words are still being saved. Pass the note id when you know which note you are answering. Then '
      + 'save your reading with tce_video_note. It never changes anything.',
    {
      type: 'object',
      properties: { video: VIDEO_ID, note: { ...NOTE_ID, description: 'The note id, when you know which note. Leave out for the note he just gave.' } },
      required: ['video'],
    },
    async ({ video, note }) => {
      const open = await takingNotes(video);
      if (open.stop) return open.stop;
      const { video: v, sitting } = open;
      const query = [];
      if (note) {
        const n = noteIn(sitting, note);
        if (n.stop) {
          return reply(`No note in his notes on "${v.title}" has the id "${idText(note)}". Leave the note out to read the one `
            + 'he just gave, or list them with tce_video_notes. Nothing was done.', { ok: false, code: 'unknown_note' });
        }
        query.push(`note=${encodeURIComponent(n.note.id)}`);
      }
      if (!rulesGiven) query.push('rules=1');
      const r = await call('GET', `/production/talk/${sitting.session_id}/moment${query.length ? `?${query.join('&')}` : ''}`);
      if (!r.ok) {
        if (r.status === 404 && r.data?.detail?.code === 'no_moment') {
          return reply('No note is waiting in his notes on this video: he has not held the button yet, or every note '
            + 'already has your reading. Nothing was done.', { ok: false, code: 'no_note', video: v.upload_id });
        }
        return refused(r, 'read that moment');
      }
      const m = r.data;
      if (m.rules) rulesGiven = true;
      for (const w of m.waiting || []) sittingOf.set(w.id, m.session_id);
      if (m.note?.id) sittingOf.set(m.note.id, m.session_id);
      const at = m.note?.where || (m.at ? `at ${m.at.clock}` : 'at that moment');
      const lines = [`Note ${at} on "${v.title}"${m.note?.id ? ` (note id ${m.note.id})` : ''}.`];
      if (m.heard) lines.push(`He said: "${m.heard}".`);
      else if (m.note) lines.push('His words for this note are not saved yet: use what he said on the call.');
      if (m.at && m.at.in_edit === false) {
        lines.push('The version he has now cut this moment; the note sits where that cut is.');
      }
      if (m.transcript) {
        lines.push('The video around it (numbered words; ~~word~~ was cut; /cut Ns/ is a join; times are in the edit he watches):');
        lines.push(m.transcript);
      }
      for (const k of m.marks || []) lines.push(`Word ${k.index} "${k.text}": ${k.mark}`);
      const others = (m.waiting || []).filter((w) => w.id !== m.note?.id);
      if (others.length) {
        lines.push(`Also waiting for your reading: ${others.map((w) => `${w.where} (note id ${w.id})${w.heard ? `: "${w.heard}"` : ''}`).join('; ')}.`);
      }
      lines.push(m.note?.id
        ? `Save what he wants at this second in one line with tce_video_note (note ${m.note.id}), then say back the line it gives you. `
          + 'Do not ask him first: nothing changes until he says make it. If his words are unclear, say what you heard and ask him to hold and say it again.'
        : 'This is the video at that second; there is no note to save here.');
      if (m.rules) lines.push('His standing rules for the editor are in rules: follow them when you read a note.');
      const data = {
        video: m.video,
        session_id: m.session_id,
        note: m.note ? { id: m.note.id, where: m.note.where, heard: m.heard, understood: m.note.understood, state: m.note.state } : null,
        at: m.at,
        transcript: m.transcript,
        marks: m.marks,
        waiting: m.waiting,
        earlier: m.earlier,
      };
      if (m.rules) data.rules = m.rules;
      return reply(lines.join('\n'), data);
    },
  );

  server.tool(
    'tce_video_note',
    'Save your one-line reading of ONE note (what he wants changed at that second, without the time), '
      + 'or take the note back when he says "scratch that" (drop true). Saving again for the same note '
      + 'rewrites that note and never adds one. Nothing is cut or rendered: that happens only when he says '
      + 'make it (tce_video_make). It returns the line to say back to him, naming the time.',
    {
      type: 'object',
      properties: {
        note: NOTE_ID,
        understood: { type: 'string', description: 'What he wants, in one plain line, without the time. Not needed with drop.' },
        drop: { type: 'boolean', description: 'True to take the note back ("scratch that").' },
        video: VIDEO_ID,
      },
      required: ['note'],
    },
    async ({ note, understood, drop, video }) => {
      const id = idText(note);
      if (!SOME_ID.test(id)) {
        return reply(`A note is named by its id ("${String(note ?? '')}" is not one). Read it with tce_video_moment first. Nothing was saved.`,
          { ok: false, code: 'id_required' });
      }
      const reading = drop ? '' : oneLine(understood);
      if (!drop && !reading) {
        return reply('Say what he wants at that second in one line, as understood. Nothing was saved.', { ok: false, code: 'empty' });
      }
      let noteId = UUID.test(id) ? id : null;
      let sid = noteId ? sittingOf.get(noteId) : null;
      if (!sid) {
        if (!video) {
          return reply('Which video? Pass the video id his call opened with, or read the note with tce_video_moment first. '
            + 'Nothing was saved.', { ok: false, code: 'video_required' });
        }
        const f = await findVideo(video);
        if (f.stop) return f.stop;
        const s = f.found.live;
        const n = s ? noteIn(s, id) : { stop: 'unknown' };
        if (n.stop) {
          return reply(`No note in his notes on "${f.found.title}" has the id "${id}". Read it with tce_video_moment. `
            + 'Nothing was saved.', { ok: false, code: 'unknown_note' });
        }
        noteId = n.note.id;
        sid = s.session_id;
      }
      const r = await call('PATCH', `/production/talk/${sid}/notes/${noteId}`, drop ? { drop: true } : { understood: reading });
      if (!r.ok) {
        const code = r.data?.detail?.code;
        if (drop && code === 'not_waiting') {
          return reply('That note was already taken back. Nothing else changed.', { ok: true, dropped: true, note: noteId });
        }
        if (code === 'not_waiting') {
          return refused(r, 'save that note', 'Nothing was saved. If he still wants it, he holds the button and says it again.');
        }
        return refused(r, drop ? 'take that note back' : 'save that note', 'Nothing was saved.');
      }
      const n = r.data;
      sittingOf.set(n.id, sid);
      if (drop) {
        return reply(`Took back the note ${n.where}. Nothing changes until you say make it.`,
          { ok: true, dropped: true, note: n.id, where: n.where });
      }
      const line = saidBack(n.where, n.understood || reading);
      return reply(line, { ok: true, note: n.id, where: n.where, understood: n.understood, state: n.state, rendered: false });
    },
  );

  server.tool(
    'tce_video_notes',
    'The notes he gave on one video, oldest first: where each is, what it says, and where it stands '
      + '(his words on their way, saved and waiting for make it, or, once made, done or needing him). '
      + 'Also what is happening to them right now. It never changes anything.',
    { type: 'object', properties: { video: VIDEO_ID }, required: ['video'] },
    async ({ video }) => {
      const f = await findVideo(video);
      if (f.stop) return f.stop;
      const v = f.found;
      const s = v.live || v.made;
      if (!s) {
        return reply(`He has not given notes on "${v.title}" yet.`, { video: v.upload_id, notes: [] });
      }
      const kept = (s.notes || []).filter((n) => n.state !== 'rejected');
      const back = (s.notes || []).length - kept.length;
      const status = sentence(s.state === 'rendering' ? s.video_step || s.result?.status : s.result?.status);
      let head;
      if (s.state === 'open') {
        head = kept.length
          ? `${kept.length} note${kept.length === 1 ? '' : 's'} on "${v.title}"; nothing changes until he says make it.`
          : `His notes on "${v.title}" are open, with no note yet.`;
        if (status) head += ` Last word from the editor: ${status}.`;
      } else if (s.state === 'thinking' || s.state === 'rendering') {
        head = `His notes on "${v.title}" are being made into a new version right now${status ? ` (${status})` : ''}.`;
      } else {
        head = `His last notes on "${v.title}" were made: ${status || s.state}.`;
      }
      const lines = [head, ...kept.map(noteLine)];
      if (back) lines.push(`${back} note${back === 1 ? ' was' : 's were'} taken back.`);
      return reply(lines.join('\n'), {
        video: v.upload_id,
        session_id: s.session_id,
        state: s.state,
        notes: kept.map((n) => ({ id: n.id, where: n.where, heard: n.request || null, understood: n.understood, state: n.state, result: n.result })),
      });
    },
  );

  server.tool(
    'tce_video_make',
    'Make the new version of the video from his notes: one job reads every note, then the video renders '
      + 'once. Only when he says make it ("that\'s all, make it"). First call it with confirmed false: '
      + 'nothing is made, and it returns the read-back of every note and a check code. Read that back to '
      + 'him and ask for a clear yes. Only after his yes, call it again with confirmed true and the same '
      + 'check code. If the notes changed after the read-back, it refuses and gives you the new read-back. '
      + 'tce_jobs says when the new version is ready.',
    {
      type: 'object',
      properties: {
        video: VIDEO_ID,
        confirmed: { type: 'boolean', description: 'True only after he said yes to the read-back.' },
        check: { type: 'string', description: 'The check code the read-back returned.' },
      },
      required: ['video'],
    },
    async ({ video, confirmed, check }) => {
      const open = await takingNotes(video);
      if (open.stop) return open.stop;
      const { video: v, sitting } = open;
      const url = `/production/talk/${sitting.session_id}/submit`;
      if (!confirmed) {
        const r = await call('GET', url);
        if (!r.ok) return refused(r, 'read the notes back', 'Nothing was made.');
        const p = r.data;
        return reply(`Read this back to him about "${v.title}" and ask for a clear yes: "${p.read_back}" `
          + `Nothing is made until you call tce_video_make again with confirmed true and check ${p.check}.`,
        { ok: false, code: 'read_back', check: p.check, read_back: p.read_back, count: p.count, video: v.upload_id, made: false });
      }
      const code = String(check ?? '').trim();
      if (!code) {
        return reply('There is no check code: call tce_video_make with confirmed false, read it back to him, and use the '
          + 'check code it gives. Nothing was made.', { ok: false, code: 'check_required', made: false });
      }
      const r = await call('POST', url, { check: code, by: 'voice' });
      if (!r.ok) {
        const d = r.data?.detail;
        if (r.status === 409 && d && d.code === 'changed' && d.read_back) {
          return reply(`The notes changed since you read them back. Read him this and ask again: "${d.read_back}" `
            + `Nothing was made. On his yes use check ${d.check}.`,
          { ok: false, code: 'changed', check: d.check, read_back: d.read_back, made: false });
        }
        return refused(r, 'make the new version', 'Nothing was made.');
      }
      const s = r.data;
      const count = (s.result?.notes || []).length;
      trackJob({ kind: 'video_edit', title: v.title, video: v.upload_id, session_id: s.session_id, notes: count });
      return reply(`Making the new version of "${v.title}" from ${count} note${count === 1 ? '' : 's'} now: one job reads `
        + 'them on the subscription, then one render. tce_jobs will say when it is ready.',
      { ok: true, made: 'started', session_id: s.session_id, video: v.upload_id, state: s.state, notes: count });
    },
  );

  server.tool(
    'tce_video_undo_version',
    'Go back to the version of the video from before his last notes were made, when he asks for that. '
      + 'One re-render. First call it with confirmed false: nothing changes, and it says what would come '
      + 'back and a check code (or why it cannot be done now). Read that back and ask for a clear yes. Only '
      + 'after his yes, call it again with confirmed true and the same check code. tce_jobs says when it is back.',
    {
      type: 'object',
      properties: {
        video: VIDEO_ID,
        confirmed: { type: 'boolean', description: 'True only after he said yes to the read-back.' },
        check: { type: 'string', description: 'The check code the read-back returned.' },
      },
      required: ['video'],
    },
    async ({ video, confirmed, check }) => {
      const f = await findVideo(video);
      if (f.stop) return f.stop;
      const v = f.found;
      const s = v.made;
      if (!s) {
        return reply(`No version of "${v.title}" was made from his notes, so there is nothing to go back from. Nothing was changed.`,
          { ok: false, code: 'nothing', video: v.upload_id });
      }
      const url = `/production/talk/${s.session_id}/undo`;
      const p = await call('GET', url);
      if (!p.ok) return refused(p, 'read what going back would do', 'Nothing was changed.');
      if (!p.data.possible) {
        const why = sentence(p.data.reason) || 'It cannot be done now';
        return reply(`${why}.${/nothing was changed/i.test(why) ? '' : ' Nothing was changed.'}`,
          { ok: false, code: p.data.code, video: v.upload_id });
      }
      const readBack = String(p.data.read_back || '').trim();
      const code = undoCheck(s.session_id, readBack);
      if (!confirmed) {
        return reply(`Read this back to him about "${v.title}" and ask for a clear yes: "${readBack}" `
          + `Nothing changes until you call tce_video_undo_version again with confirmed true and check ${code}.`,
        { ok: false, code: 'read_back', check: code, read_back: readBack, video: v.upload_id, undone: false });
      }
      if (String(check ?? '').trim() !== code) {
        return reply(`That is not the read-back he heard (it changed, or no check code was given). Read him this about `
          + `"${v.title}" and ask again: "${readBack}" Nothing was changed. On his yes use check ${code}.`,
        { ok: false, code: 'changed', check: code, read_back: readBack, undone: false });
      }
      const r = await call('POST', url);
      if (!r.ok) return refused(r, 'go back to the earlier version', 'Nothing was changed.');
      trackJob({ kind: 'video_undo', title: v.title, video: v.upload_id, session_id: s.session_id });
      return reply(`Putting back the version of "${v.title}" from before his notes now: one re-render. `
        + 'tce_jobs will say when it is back.', { ok: true, undone: 'started', session_id: s.session_id, video: v.upload_id });
    },
  );
}
