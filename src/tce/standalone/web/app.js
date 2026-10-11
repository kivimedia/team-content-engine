const state = {me:null, config:null, ideas:[], recordings:[], materials:[], secrets:[], view:'today', ideaId:null, weekStart:null, blob:null, media:null, stream:null, live:null};
const view = document.getElementById('view');
// A preview reads the saved lane so clients can inspect inputs before scouting.
const sourcePreviewObserver = new MutationObserver(() => {
  if (state.view !== 'settings') return;
  view.querySelectorAll('.lane-form').forEach((box, index) => {
    if (box.dataset.previewReady) return;
    box.dataset.previewReady = 'true';
    const result = document.createElement('div');
    result.className = 'source-preview';
    const preview = document.createElement('button');
    preview.type = 'button';
    preview.className = 'secondary';
    preview.textContent = 'Preview saved source';
    preview.addEventListener('click', async () => {
      preview.disabled = true;
      preview.textContent = 'Checking this source';
      result.textContent = 'Reading this source and checking its connection';
      try {
        const data = await api(`/api/sources/${index}/preview`, {method:'POST'});
        result.replaceChildren();
        result.append(node('strong', `${data.items_found} items available from ${data.name}`));
        if (data.research_note) result.append(node('p', data.research_note));
        if (data.filter) result.append(node('p', `Filter: ${data.filter}`));
        for (const item of data.items) {
          const entry = node('div', null, 'source-preview-item');
          entry.append(node('strong', item.title), node('p', item.excerpt));
          if (item.url) {
            const link = node('a', 'Open source');
            link.href = item.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            entry.append(link);
          }
          result.append(entry);
        }
      } catch (error) {
        result.textContent = message(error);
      } finally {
        preview.disabled = false;
        preview.textContent = 'Preview saved source';
      }
    });
    box.append(preview, result);
  });
});
sourcePreviewObserver.observe(view, {childList:true, subtree:true});
const visualReviewObserver = new MutationObserver(() => {
  if (state.view !== 'library') return;
  const log = view.querySelector('.chat-log');
  if (!log || log.parentElement.dataset.reviewReady) return;
  const panel = log.parentElement;
  panel.dataset.reviewReady = 'true';
  const recording = state.recordings.find(r => r.id === view.querySelector('select')?.value);
  if (!recording) return;
  const result = node('p', recording.qc?.visual_review?.summary ||
    'Jennifer can inspect three still frames. Audio and the full motion are not reviewed.');
  const action = button('Inspect selected video frames', async () => {
    try {
      const review = await act(action, 'Inspecting three video frames', () =>
        api(`/api/recordings/${recording.id}/visual-review`, {method:'POST'}));
      recording.qc = {...(recording.qc || {}), visual_review:review};
      result.textContent = review.summary;
      toast('Visual review saved for Jennifer');
    } catch {}
  }, 'secondary');
  panel.insertBefore(action, log);
  panel.insertBefore(result, log);
  const exportResult = node('div', null, 'stack-tight');
  const prepared = recording.qc?.export;
  if (prepared?.transcript_excerpt) exportResult.append(node('p',
    `Transcript ready: ${prepared.transcript_excerpt}`));
  const prepare = button('Prepare captions and post copy', async () => {
    try {
      const data = await act(prepare, 'Transcribing selected video', () =>
        api(`/api/recordings/${recording.id}/prepare-export`, {method:'POST'}));
      exportResult.replaceChildren(node('p', `Transcript: ${data.transcript}`));
      const captions = node('a', 'Download timed captions', 'secondary');
      captions.href = URL.createObjectURL(new Blob([data.captions], {type:'text/plain'}));
      captions.download = 'captions.srt';
      exportResult.append(captions);
      if (data.suggested_post_copy) {
        exportResult.append(node('p', `Suggested post copy: ${data.suggested_post_copy}`));
        exportResult.append(button('Copy post copy', async () => {
          await navigator.clipboard.writeText(data.suggested_post_copy);
          toast('Post copy copied');
        }, 'quiet'));
      }
      toast('Export package is ready for your terminal');
    } catch {}
  }, 'secondary');
  panel.insertBefore(prepare, log);
  panel.insertBefore(exportResult, log);
});
visualReviewObserver.observe(view, {childList:true, subtree:true});
const workerGrantObserver = new MutationObserver(() => {
  if (state.view !== 'settings') return;
  const heading = [...view.querySelectorAll('h2')].find(item => item.textContent === 'Terminal mode');
  const panel = heading?.parentElement;
  if (!panel || panel.dataset.workerReady) return;
  panel.dataset.workerReady = 'true';
  panel.append(node('p', 'Claude Code can scout and draft through its own signed-in terminal. Give its TCE MCP adapter a worker-only token. Disconnect it by revoking the token.'));
  const create = button('Create Claude Code worker token', async () => {
    try {
      const grant = await api('/api/tokens', {method:'POST', body:JSON.stringify({label:'Claude Code worker', scopes:['worker'], days:30})});
      const secret = node('textarea');
      secret.readOnly = true;
      secret.value = grant.token;
      panel.append(node('p', 'Copy this worker token now. It appears only once.', 'note'), secret);
      toast('Worker token created');
    } catch (error) { toast(message(error)); }
  }, 'secondary');
  panel.append(create);
  api('/api/tokens').then(tokens => {
    if (state.view !== 'settings') return;
    for (const token of tokens) {
      const line = node('div', null, 'button-row');
      line.append(node('span', `${token.label}: ${token.scopes.join(', ')}`));
      line.append(button('Revoke', async () => {
        try { await api(`/api/tokens/${token.id}`, {method:'DELETE'}); line.remove(); toast('Terminal grant revoked'); }
        catch (error) { toast(message(error)); }
      }, 'quiet'));
      panel.append(line);
    }
  }).catch(() => {});
});
workerGrantObserver.observe(view, {childList:true, subtree:true});
const routineStatusObserver = new MutationObserver(() => {
  if (state.view !== 'settings') return;
  const heading = [...view.querySelectorAll('h2')].find(item => item.textContent === 'Weekly scouting routine');
  if (!heading || heading.dataset.statusReady) return;
  heading.dataset.statusReady = 'true';
  const statusBox = node('div', null, 'stack-tight');
  heading.after(statusBox);
  api('/api/routine').then(runs => {
    if (!runs.length) { statusBox.append(node('p', 'No scheduled scouting run yet.')); return; }
    for (const run of runs.slice(0, 3)) {
      statusBox.append(node('p', `${run.date}: ${run.status}${run.error_code ? ` (${run.error_code})` : ''}. ${run.phase || ''}`));
    }
    if (runs[0]?.status === 'failed') statusBox.append(button('Open ideas to scout now', () => show('ideas'), 'quiet'));
  }).catch(() => {});
});
routineStatusObserver.observe(view, {childList:true, subtree:true});

function draftScope() { return `tce-take:${state.me.workspace_id}:${state.me.email}`; }
function draftDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('tce-client-takes', 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('metadata');
      request.result.createObjectStore('chunks');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function draftWrite(storeName, key, value) {
  const db = await draftDatabase();
  try {
    await new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite');
      transaction.objectStore(storeName).put(value, key);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
async function draftRead() {
  const db = await draftDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(['metadata', 'chunks'], 'readonly');
      const scope = draftScope();
      const range = IDBKeyRange.bound(`${scope}:`, `${scope}:\uffff`);
      let metadata, keys, chunks;
      transaction.objectStore('metadata').get(scope).onsuccess = event => metadata = event.target.result;
      transaction.objectStore('chunks').getAllKeys(range).onsuccess = event => keys = event.target.result;
      transaction.objectStore('chunks').getAll(range).onsuccess = event => chunks = event.target.result;
      transaction.oncomplete = () => {
        if (!metadata) return resolve(null);
        const matched = keys.map((key, index) => [key, chunks[index]])
          .filter(([key]) => String(key).startsWith(`${scope}:${metadata.id}:`))
          .sort(([a], [b]) => Number(a.split(':').at(-1)) - Number(b.split(':').at(-1)))
          .map(([, blob]) => blob);
        resolve(matched.length ? {metadata, blob:new Blob(matched, {type:metadata.mime})} : null);
      };
      transaction.onerror = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
async function draftClear() {
  const db = await draftDatabase();
  try {
    await new Promise((resolve, reject) => {
      const transaction = db.transaction(['metadata', 'chunks'], 'readwrite');
      const scope = draftScope();
      transaction.objectStore('metadata').delete(scope);
      const store = transaction.objectStore('chunks');
      const request = store.openCursor(IDBKeyRange.bound(`${scope}:`, `${scope}:\uffff`));
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        cursor.delete();
        cursor.continue();
      };
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
const $ = (id) => document.getElementById(id);

function node(tag, text='', className='') { const n=document.createElement(tag); if(text!==null)n.textContent=text; if(className)n.className=className; return n; }
function button(text, onClick, className='secondary') { const n=node('button',text,className); n.type='button'; n.addEventListener('click',onClick); return n; }
function field(label, value='', type='text', help='') { const wrap=node('label',null,'field'); wrap.append(node('span',label)); const input=node(type==='textarea'?'textarea':type==='select'?'select':'input'); if(type!=='textarea'&&type!=='select')input.type=type; input.value=value??''; wrap.append(input); if(help)wrap.append(node('span',help,'field-help')); return {wrap,input}; }
function message(error) { const d=error?.detail; return typeof d==='string'?d:typeof d?.message==='string'?d.message:error?.message||'That action did not finish.'; }
function cookie(name){return document.cookie.split('; ').find(x=>x.startsWith(name+'='))?.slice(name.length+1)||'';}
async function api(path, options={}) { const headers={...(options.headers||{})}; if(!(options.body instanceof FormData)&&options.body!==undefined)headers['Content-Type']='application/json'; if(!['GET','HEAD'].includes(options.method||'GET'))headers['X-TCE-CSRF']=cookie('tce_client_csrf'); const r=await fetch(path,{credentials:'same-origin',...options,headers}); if(!r.ok){let body={};try{body=await r.json()}catch{} const e=new Error(message(body));e.status=r.status;throw e;} return r.status===204?null:r.json(); }
function toast(text){const t=$('toast');t.textContent=text;t.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('show'),4500);}
function status(text){let p=$('action-progress');if(p)p.textContent=text;}
async function act(btn, first, fn){const old=btn?.textContent;if(btn){btn.disabled=true;btn.textContent=first;}const started=Date.now();status(first);const ticker=setInterval(()=>status(`${state.actionPhase||first}. ${Math.floor((Date.now()-started)/1000)} seconds elapsed.`),1000);try{const value=await fn();status('Done');return value;}catch(e){status(message(e));toast(message(e));throw e;}finally{clearInterval(ticker);state.actionPhase=null;if(btn){btn.disabled=false;btn.textContent=old;}}}
async function waitForWorker(jobId) {
  for (let check = 0; check < 12; check++) {
    await new Promise(resolve => setTimeout(resolve, 5000));
    const job = await api(`/api/jobs/${jobId}`);
    state.actionPhase = job.phase;
    if (job.status === 'done') return job.result;
    if (job.status === 'failed') throw new Error(`Claude Code job needs attention: ${job.error_code}`);
  }
  toast('Your Claude Code job is still queued. You can see it on this page later.');
  return null;
}

async function renderJobs(name) {
  if (!state.config?.onboarded) return;
  try {
    const jobs = await api('/api/jobs');
    if (state.view !== name || view.querySelector('.job-queue')) return;
    const visible = jobs.filter(job => job.status !== 'done').slice(0, 5);
    if (!visible.length) return;
    const panel = node('div', null, 'surface stack-tight job-queue');
    panel.append(node('h2', 'Claude Code jobs'));
    panel.append(node('p', 'Your client-owned Claude Code connection works on these jobs. Failed jobs stay here until you retry.'));
    for (const job of visible) {
      const item = node('div', null, 'stack-tight');
      item.append(node('strong', `${job.kind}: ${job.status}`), node('p', job.phase));
      if (job.status === 'failed') item.append(button('Retry this job', async () => {
        try { await api(`/api/jobs/${job.id}/retry`, {method:'POST'}); toast('Job queued again'); show(name); }
        catch (error) { toast(message(error)); }
      }, 'secondary'));
      panel.append(item);
    }
    panel.append(button('Refresh worker jobs', () => show(name), 'quiet'));
    view.append(panel);
  } catch {}
}

function header(title, description, action){view.replaceChildren();const h=node('div',null,'view-header');const text=node('div');text.append(node('h1',title),node('p',description));h.append(text);if(action)h.append(action);view.append(h);}
function section(title){const h=node('div',null,'section-head');h.append(node('h2',title));view.append(h);return h;}
function surface(){const s=node('div',null,'surface');view.append(s);return s;}
function row(){return node('div',null,'button-row');}
function formError(form,text){let e=form.querySelector('.error');if(!e){e=node('div',null,'error');form.prepend(e);}e.textContent=text;}
function sourceName(kind){return ({fathom:'Fathom calls',commits:'Git commits',ai_news:'AI news',book:'Book',research:'Research',course:'Course',upload:'Uploaded material',custom:'Custom source'})[kind]||kind;}
function ideaById(id){return state.ideas.find(x=>x.id===id);}
function weekMonday(){const zone=state.config?.config?.timezone||'UTC';const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const get=(t)=>parts.find(p=>p.type===t).value;const d=new Date(`${get('year')}-${get('month')}-${get('day')}T12:00:00Z`);const wd=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-wd);return d.toISOString().slice(0,10);}
function moveWeek(days){const d=new Date(state.weekStart+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);state.weekStart=d.toISOString().slice(0,10);renderWeek();}

async function load(){const [me,config,ideas,recordings,materials,secrets]=await Promise.all([api('/auth/me'),api('/api/config'),api('/api/ideas'),api('/api/recordings'),api('/api/materials'),api('/api/secrets')]);Object.assign(state,{me,config,ideas,recordings,materials,secrets});const linkedRecording=new URLSearchParams(location.search).get('recording');if(linkedRecording&&recordings.some(r=>r.id===linkedRecording)){state.recordingId=linkedRecording;state.view='library';}$('workspace-name').textContent=config.config.display_name;$('login-shell').hidden=true;$('studio').hidden=false;if(!config.onboarded)state.view='settings';show(state.view);}
function show(name){if(state.live){closeLive();}if(state.view==='record'&&name!=='record'&&state.media?.state==='recording'){state.media.stop();state.stream?.getTracks().forEach(t=>t.stop());}state.view=name;document.querySelectorAll('[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view===name));history.replaceState(null,'',`/app#${name}`);if(name==='today')renderToday();if(name==='ideas')renderIdeas();if(name==='week')renderWeek();if(name==='record')renderRecord();if(name==='library')renderLibrary();if(name==='settings')renderSettings();void renderJobs(name);view.focus({preventScroll:true});}
document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>show(n.dataset.view)));
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;const body=Object.fromEntries(new FormData(form));const b=form.querySelector('button');b.disabled=true;b.textContent='Checking your workspace';$('login-message').textContent='Checking your email, password and workspace';try{await api('/auth/login',{method:'POST',body:JSON.stringify(body)});await load();}catch(err){$('login-message').textContent=message(err);}finally{b.disabled=false;b.textContent='Sign in';}});
$('sign-out').addEventListener('click',async()=>{try{await api('/auth/logout',{method:'POST'});}catch{}location.replace('/app');});

function renderToday(){const c=state.config.config;header(`What will ${c.display_name} say next?`,'Start with real material. Leave with a video you can publish on your own terms.',button('Scout ideas',()=>runScout(),'primary'));if(!state.config.onboarded){const s=surface();s.append(node('h2','Finish your setup'),node('p','Choose your three sources and add your voice before scouting.'));s.append(button('Open onboarding',()=>show('settings'),'primary'));return;}const stats=node('div',null,'stat-row');[['Ideas',state.ideas.length],['For this week',state.ideas.filter(i=>i.status==='this_week').length],['Recordings',state.recordings.length]].forEach(([label,value])=>{const n=node('div',null,'stat');n.append(node('strong',String(value)),node('span',label));stats.append(n)});view.append(stats);section('Your three idea sources');const grid=node('div',null,'source-grid');c.source_lanes.forEach((lane,index)=>{const n=node('div',null,'source-strip'+(lane.enabled?'':' off'));n.append(node('span',`Source ${index+1}`,'eyebrow'),node('strong',lane.name||sourceName(lane.kind)),node('p',lane.enabled?lane.filter||'No filter added yet':'Paused'));grid.append(n)});view.append(grid);section('Your next move');const s=surface();s.append(node('h3',state.ideas.length?'Choose an idea to shape':'Start with your own work'));s.append(node('p',state.ideas.length?'Review your ideas, choose one for the week, and make a script.':'Add a book, course, call, commit source or research topic, then scout ideas.'));s.append(button(state.ideas.length?'Open ideas':'Open settings',()=>show(state.ideas.length?'ideas':'settings'),'secondary'));view.append(node('p','', 'progress'));view.lastChild.id='action-progress';}
async function runScout(){const b=[...view.querySelectorAll('button')].find(x=>x.textContent==='Scout ideas');await act(b,'Reading your sources',async()=>{status('Reading configured sources, applying filters, then asking your client-owned brain for grounded ideas');let r=await api('/api/scout',{method:'POST'});if(r.job_id){state.actionPhase='Waiting for your Claude Code worker';r=await waitForWorker(r.job_id);if(!r){show('ideas');return;}}state.ideas.unshift(...r.ideas);toast(`${r.ideas.length} ideas ready to review`);show('ideas');});}

function sourceLink(idea){if(!idea.source_url||!/^https:\/\//i.test(idea.source_url))return null;const a=node('a','Open source','source-link');a.href=idea.source_url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function ideaCard(idea){const card=node('article',null,'idea-card');card.append(node('span',idea.status.replace('_',' '),'eyebrow'),node('h3',idea.title),node('p',idea.angle));if(idea.evidence)card.append(node('p',idea.evidence,'evidence'));const link=sourceLink(idea);if(link)card.append(link);const actions=row();actions.append(button('Open idea',()=>{state.ideaId=idea.id;renderIdeas();}));if(idea.status!=='this_week')actions.append(button('Put on this week',async()=>{try{const week=state.weekStart||weekMonday();const changed=await api(`/api/ideas/${idea.id}`,{method:'PATCH',body:JSON.stringify({status:'this_week',week_start:week})});Object.assign(idea,changed);toast('Added to this week');renderIdeas();}catch(e){toast(message(e));}},'quiet'));card.append(actions);return card;}
function renderIdeas(){if(state.ideaId){renderIdeaDetail(state.ideaId);return;}header('Ideas','A working inbox from your chosen sources.',button('Scout ideas',()=>runScout(),'primary'));const grid=node('div',null,'idea-grid');state.ideas.filter(i=>i.status!=='away').forEach(i=>grid.append(ideaCard(i)));if(!grid.children.length){const n=surface();n.append(node('h2','No ideas yet'),node('p','Add source material in Settings, then scout your first ideas.'));}else view.append(grid);const progress=node('p','', 'progress');progress.id='action-progress';view.append(progress);}
async function renderIdeaDetail(id){const idea=ideaById(id);if(!idea){state.ideaId=null;renderIdeas();return;}header(idea.title,idea.angle,button('Back to ideas',()=>{state.ideaId=null;renderIdeas();},'quiet'));const summary=surface();summary.append(node('span',idea.status.replace('_',' '),'eyebrow'),node('h3','What supports it'),node('p',idea.evidence||'Add evidence before making a strong claim.'),node('h3','Why now'),node('p',idea.why_now||'No timing note yet.'));const controls=row();controls.append(button('Put on this week',async()=>{try{const changed=await api(`/api/ideas/${id}`,{method:'PATCH',body:JSON.stringify({status:'this_week',week_start:state.weekStart||weekMonday()})});Object.assign(idea,changed);toast('Added to this week');renderIdeaDetail(id);}catch(e){toast(message(e));}},'secondary'),button('Record this idea',()=>show('record'),'quiet'));summary.append(controls);section('Script');const s=surface();const text=node('textarea');text.placeholder='Your script appears here. You can edit and save a new version.';text.style.minHeight='280px';s.append(text);const actions=row();const generate=button('Draft a script',async()=>{try{let out=await act(generate,'Writing your script',async()=>{let result=await api(`/api/ideas/${id}/script`,{method:'POST'});if(result.job_id){state.actionPhase='Waiting for your Claude Code worker';result=await waitForWorker(result.job_id);}return result;});if(!out)return;text.value=out.script;toast(`Script version ${out.version} is ready`);}catch{}} ,'primary');const save=button('Save my edits',async()=>{try{const out=await act(save,'Saving version',()=>api(`/api/ideas/${id}/script`,{method:'PUT',body:JSON.stringify({script:text.value})}));toast(`Saved version ${out.version}`);}catch{}});actions.append(generate,save);s.append(actions);const versions=node('div',null,'stack-tight');s.append(versions);try{const history=await api(`/api/ideas/${id}/scripts`);if(history.length){text.value=history[0].script;const selector=node('select');history.forEach(item=>{const option=node('option',`Version ${item.version} (${item.origin})`);option.value=String(item.version);selector.append(option);});selector.addEventListener('change',()=>{text.value=history.find(x=>String(x.version)===selector.value).script;});versions.append(node('h3','Earlier versions'),selector);}}catch(e){toast(message(e));}const progress=node('p','', 'progress');progress.id='action-progress';view.append(progress);}

async function renderWeek(){state.weekStart ||= weekMonday();header('This week','Choose what to record and discuss the lineup before you start.');const controls=row();controls.append(button('Previous week',()=>moveWeek(-7),'quiet'),node('strong',state.weekStart),button('Next week',()=>moveWeek(7),'quiet'));view.append(controls);const spine=node('div',null,'week-spine');[['Ideas','Choose'],['Scripts','Shape'],['Record','Capture'],['Review','Refine'],['Video','Take it with you']].forEach(([a,b])=>{const n=node('div',null,'week-step');n.append(node('span',a),node('strong',b));spine.append(n)});view.append(spine);const list=node('div',null,'idea-grid');view.append(list);try{const week=await api(`/api/week/${state.weekStart}`);if(!week.ideas.length){const s=node('div',null,'surface');s.append(node('h3','Your week is open'),node('p','Pick ideas from the inbox to put them here.'));s.append(button('Choose ideas',()=>show('ideas')));list.append(s);}else week.ideas.forEach(i=>list.append(ideaCard(i)));}catch(e){list.append(node('p',message(e),'error'));}section('Talk to the week');const s=surface();s.append(node('p','Ask which idea deserves attention or how to sequence the week. Suggestions stay in the conversation until you choose to change a card.'));const log=node('div',null,'chat-log');s.append(log);const form=node('form',null,'stack-tight');const input=field('Your question','','textarea');form.append(input.wrap);const actions=row();const send=node('button','Send question','primary');send.type='submit';actions.append(send,button('Start voice conversation',()=>startLive('week',null,s),'secondary'));form.append(actions);s.append(form);form.addEventListener('submit',async e=>{e.preventDefault();const value=input.input.value.trim();if(!value)return;appendChat(log,'You',value,true);input.input.value='';try{const r=await act(send,'Thinking about the week',()=>api('/api/talk/week',{method:'POST',body:JSON.stringify({message:value})}));appendChat(log,'TCE',r.answer,false);}catch{}});s.append(node('p','', 'progress'));s.lastChild.id='action-progress';}
function appendChat(log,name,text,mine){const m=node('div',null,'chat-message'+(mine?' mine':''));m.append(node('strong',name+' '),node('span',text));log.append(m);log.scrollTop=log.scrollHeight;}

async function renderRecord(){header('Record','Use your phone or camera. Your original stays safe while you review edits.');const form=surface();const choose=field('Idea to record','','select');choose.input.replaceChildren();const blank=node('option','Choose an idea');blank.value='';choose.input.append(blank);state.ideas.filter(i=>i.status!=='away').forEach(i=>{const o=node('option',i.title);o.value=i.id;choose.input.append(o)});if(state.ideaId)choose.input.value=state.ideaId;form.append(choose.wrap);const video=node('video');video.className='video-preview';video.playsInline=true;video.controls=true;video.muted=true;form.append(video);const controls=row();let chunks=[];const start=button('Start camera',async()=>{try{state.stream=await navigator.mediaDevices.getUserMedia({audio:true,video:{facingMode:'user'}});video.srcObject=state.stream;video.muted=true;await video.play();start.disabled=true;record.disabled=false;status('Camera and microphone are ready. Start recording when you are ready.');}catch(e){toast('Camera permission is needed to record.');}},'secondary');const record=button('Start recording',async()=>{if(!choose.input.value){toast('Choose an idea before recording.');return;}const mime=['video/mp4','video/webm;codecs=vp8,opus','video/webm'].find(x=>MediaRecorder.isTypeSupported(x));if(!mime){toast('This browser cannot record a supported video format.');return;}chunks=[];const draftId=crypto.randomUUID();const draftKey=`${draftScope()}:${draftId}`;const draftWrites=[];const draftMeta={id:draftId,ideaId:choose.input.value,mime:mime.split(';')[0],complete:false};try{await draftClear();await draftWrite('metadata',draftScope(),draftMeta);}catch(error){toast('Local take recovery is unavailable. Upload this take before leaving.');}state.media=new MediaRecorder(state.stream,{mimeType:mime});state.media.ondataavailable=e=>{if(e.data.size){const index=chunks.push(e.data)-1;draftWrites.push(draftWrite('chunks',`${draftKey}:${index}`,e.data).catch(()=>{state.draftStorageError=true;}));}};state.media.onstop=async()=>{await Promise.allSettled(draftWrites);state.blob=new Blob(chunks,{type:mime.split(';')[0]});try{await draftWrite('metadata',draftScope(),{...draftMeta,complete:true});}catch{}video.srcObject=null;video.src=URL.createObjectURL(state.blob);video.muted=false;upload.disabled=false;status('Take saved on this device. Review it, then upload.');};state.media.start(1000);record.disabled=true;stop.disabled=false;status('Recording now. Your camera and microphone are active.');},'primary');record.disabled=true;const stop=button('Stop recording',()=>{state.media.stop();state.stream.getTracks().forEach(t=>t.stop());stop.disabled=true;start.disabled=false;},'danger');stop.disabled=true;const upload=button('Save take to workspace',async()=>{if(!choose.input.value){toast('Choose an idea first.');return;}const type=state.blob.type==='video/mp4'?'video/mp4':'video/webm';const ext=type==='video/mp4'?'mp4':'webm';const fd=new FormData();fd.append('file',state.blob,`take.${ext}`);try{const out=await act(upload,'Uploading video',()=>api(`/api/ideas/${choose.input.value}/recordings`,{method:'POST',body:fd}));state.recordings.unshift(out);await draftClear().catch(()=>{});state.blob=null;toast('Take saved. Jennifer can review it in Library.');show('library');}catch{}});upload.disabled=true;controls.append(start,record,stop,upload);form.append(controls);const recovery=node('div',null,'stack-tight');form.append(recovery);draftRead().then(saved=>{if(!saved||state.media?.state==='recording')return;state.blob=saved.blob;if(state.ideas.some(i=>i.id===saved.metadata.ideaId))choose.input.value=saved.metadata.ideaId;video.srcObject=null;video.src=URL.createObjectURL(saved.blob);video.muted=false;upload.disabled=!choose.input.value;status('Recovered a take from this device. Review it before uploading.');recovery.append(node('p',saved.metadata.complete?'A take from this device is ready to upload.':'A recording was interrupted. Review the recovered video before uploading.'));recovery.append(button('Discard this device draft',async()=>{await draftClear();state.blob=null;video.removeAttribute('src');video.load();upload.disabled=true;recovery.replaceChildren();},'quiet'));}).catch(()=>{});const progress=node('p','Choose an idea, then start your camera.','progress');progress.id='action-progress';form.append(progress);section('Already recorded');const list=node('div',null,'idea-grid');state.recordings.slice(0,4).forEach(r=>list.append(recordingCard(r)));view.append(list);}

function recordingCard(r){const card=node('article',null,'idea-card');const idea=ideaById(r.idea_id);card.append(node('span',r.status,'eyebrow'),node('h3',idea?.title||'Recording'),node('p',`${r.qc?.duration_s||'?'} seconds, ${r.qc?.width||'?'} by ${r.qc?.height||'?'} pixels`));const actions=row();actions.append(button('Open video',()=>{state.recordingId=r.id;show('library');}));card.append(actions);return card;}

async function renderLibrary(){header('Library','Private recordings and selected edits. Download or send the video to your own email.');if(!state.recordings.length){const s=surface();s.append(node('h2','No videos yet'),node('p','Record a take to start your library.'));s.append(button('Go to Record',()=>show('record'),'primary'));return;}const select=field('Choose a recording','','select');state.recordings.forEach(r=>{const o=node('option',ideaById(r.idea_id)?.title||r.id);o.value=r.id;select.input.append(o)});select.input.value=state.recordingId&&state.recordings.some(r=>r.id===state.recordingId)?state.recordingId:state.recordings[0].id;select.input.addEventListener('change',()=>{state.recordingId=select.input.value;renderLibrary();});view.append(select.wrap);const r=state.recordings.find(x=>x.id===select.input.value);const panel=surface();const video=node('video');video.src=`/api/recordings/${r.id}/video?version=selected`;video.controls=true;video.playsInline=true;video.className='video-preview';panel.append(video);panel.append(node('p',`Technical check: ${r.qc?.duration_s||'?'} seconds, ${r.qc?.width||'?'} by ${r.qc?.height||'?'} pixels. ${r.qc?.has_audio?'Audio present.':'No audio track found.'}`));const actions=row();const download=node('a','Download selected video','secondary');download.href=video.src;download.download='your-video';download.style.textDecoration='none';actions.append(download);const send=button('Email this video to me',async()=>{try{const key=crypto.randomUUID();const out=await act(send,'Sending to your verified email',()=>api(`/api/recordings/${r.id}/send-to-self`,{method:'POST',body:JSON.stringify({idempotency_key:key})}));toast(out.status==='sent'?'Video email sent':'Delivery failed. Download your video here.');}catch{}} ,'primary');actions.append(send);panel.append(actions);section('Talk to Jennifer');const jen=surface();jen.append(node('p','Discuss a cut or tell Jennifer what you want changed. She sees technical checks and your notes.'));const log=node('div',null,'chat-log');jen.append(log);const chat=node('form',null,'stack-tight');const question=field('Tell Jennifer','','textarea');chat.append(question.wrap);const cActions=row();const ask=node('button','Ask Jennifer','primary');ask.type='submit';cActions.append(ask,button('Talk live',()=>startLive('jennifer',r.id,jen)));chat.append(cActions);jen.append(chat);chat.addEventListener('submit',async e=>{e.preventDefault();const value=question.input.value.trim();if(!value)return;appendChat(log,'You',value,true);question.input.value='';try{const out=await act(ask,'Jennifer is reviewing your notes',()=>api(`/api/talk/jennifer?context_id=${r.id}`,{method:'POST',body:JSON.stringify({message:value})}));appendChat(log,'Jennifer',out.answer,false);}catch{}});section('Make a cut');const edit=surface();edit.append(node('p','Choose a start and end time. The original is never changed.'));const times=node('div',null,'form-row');const start=field('Start at second','0','number');const end=field('End at second',String(Math.floor(r.qc?.duration_s||0)),'number');start.input.min='0';end.input.min='0';start.input.step=end.input.step='0.1';times.append(start.wrap,end.wrap);edit.append(times);const note=field('Edit note','','textarea');edit.append(note.wrap);const trim=button('Make this cut',async()=>{try{const out=await act(trim,'Rendering your cut',()=>api(`/api/recordings/${r.id}/trim`,{method:'POST',body:JSON.stringify({start_s:Number(start.input.value),end_s:Number(end.input.value),note:note.input.value})}));Object.assign(r,out.recording);toast(`Cut version ${out.version} is ready`);renderLibrary();}catch{}} ,'secondary');const restore=button('Use original video',async()=>{try{const out=await api(`/api/recordings/${r.id}/original/select`,{method:'POST'});Object.assign(r,out);toast('Original selected');renderLibrary();}catch(e){toast(message(e));}},'quiet');const editActions=row();editActions.append(trim,restore);edit.append(editActions);const versions=node('div',null,'stack-tight');edit.append(versions);try{const history=await api(`/api/recordings/${r.id}/renders`);history.forEach(item=>{versions.append(button(`Use cut ${item.version}: ${item.start_s}s to ${item.end_s}s`,async()=>{try{const out=await api(`/api/recordings/${r.id}/renders/${item.id}/select`,{method:'POST'});Object.assign(r,out);renderLibrary();}catch(e){toast(message(e));}},'pill'));});}catch{}const progress=node('p','', 'progress');progress.id='action-progress';view.append(progress);}

async function startLive(mode,contextId,container){
  if(state.live)closeLive();
  const info=node('p','Requesting microphone access','progress');container.append(info);
  let pc,stream,dc,sessionId='';let latestSpeech='',history='';const handled=new Set();
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    pc=new RTCPeerConnection();stream.getTracks().forEach(t=>pc.addTrack(t,stream));
    const audio=node('audio');audio.autoplay=true;container.append(audio);
    pc.ontrack=e=>audio.srcObject=e.streams[0];
    dc=pc.createDataChannel('oai-events');
    dc.onmessage=async e=>{
      let event;try{event=JSON.parse(e.data);}catch{return;}
      if(event.type==='session.started')info.textContent='Voice connected. Speak naturally.';
      if(event.type==='session.input_transcript.delta')latestSpeech+=(event.delta||'');
      if(event.type==='session.closed'){info.textContent='Voice conversation ended.';closeLive();return;}
      if(event.type!=='session.delegation.created'||event.delegation?.target!=='client')return;
      const id=event.delegation.id;if(!id||handled.has(id))return;handled.add(id);
      await new Promise(resolve=>setTimeout(resolve,250));
      const speech=latestSpeech.slice(-5000).trim();latestSpeech='';
      info.textContent='Asking your client-owned brain about what you said';
      try{
        const result=speech?await api('/api/live/delegation',{method:'POST',body:JSON.stringify({session_id:sessionId,delegation_id:id,transcript:speech,history:history.slice(-8000)})}):{answer:'I did not catch that. Please say it again.'};
        history+=`User: ${speech}\nAssistant: ${result.answer}\n`;
        if(dc.readyState==='open')dc.send(JSON.stringify({type:'session.commentary.append',event_id:crypto.randomUUID(),delegation_id:id,content:result.answer.slice(0,1700)}));
        info.textContent='Voice connected. Speak naturally.';
      }catch(error){
        info.textContent=message(error);
        if(dc.readyState==='open')dc.send(JSON.stringify({type:'session.commentary.append',event_id:crypto.randomUUID(),delegation_id:id,content:'The client reasoning connection needs attention. You can still use the text controls.'}));
      }
    };
    state.live={pc,stream,dc};
    const offer=await pc.createOffer();await pc.setLocalDescription(offer);
    if(pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Network negotiation timed out')),10000);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});});
    info.textContent='Connecting to live voice';
    const out=await api('/api/live/session',{method:'POST',body:JSON.stringify({sdp:pc.localDescription.sdp,mode,context_id:contextId})});
    sessionId=out.session_id;await pc.setRemoteDescription({type:'answer',sdp:out.sdp});
    const stop=button('End voice conversation',()=>{info.textContent='Closing the voice session';if(dc.readyState==='open')dc.send(JSON.stringify({type:'session.close'}));setTimeout(()=>{if(state.live)closeLive();},15000);},'danger');container.append(stop);
  }catch(error){info.textContent=message(error);closeLive();}
}
function closeLive(){if(!state.live)return;state.live.stream?.getTracks().forEach(t=>t.stop());state.live.pc?.close();state.live=null;}

async function renderSettings(){header(state.config.onboarded?'Settings':'Set up your studio','Everything here can be changed later. Your previous settings stay in history.');const c=state.config.config;const layout=node('div',null,'settings-grid');view.append(layout);const main=node('form',null,'surface stack');layout.append(main);main.append(node('h2','Your perspective'));const name=field('Name shown in your studio',c.display_name);const zone=field('Timezone',c.timezone,'text','Use an IANA name such as America/New_York.');const audience=field('Who you speak to',c.audience,'textarea');const focus=field('What you help them do',c.focus,'textarea');const voice=field('How your voice sounds',c.voice_notes,'textarea','Add words you use, rhythm, and what feels unlike you.');const avoid=field('Claims or topics to avoid',c.avoid,'textarea');[name,zone,audience,focus,voice,avoid].forEach(x=>main.append(x.wrap));main.append(node('h2','Your three idea sources'));const lanes=[];c.source_lanes.forEach((lane,i)=>{const box=node('div',null,'lane-form stack-tight');box.append(node('h3',`Source ${i+1}`));const n=field('Name',lane.name);const k=field('Type',lane.kind,'select');['fathom','commits','ai_news','book','research','course','upload','custom'].forEach(type=>{const o=node('option',sourceName(type));o.value=type;k.input.append(o)});k.input.value=lane.kind;const l=field('Connection or location',lane.locator||'','text','For commits, enter owner/repo. For files, upload below.');const f=field('Filter: what should count',lane.filter,'textarea');const com=field('Comments for this source',lane.comments,'textarea');const on=field('Use this source',null,'checkbox');on.input.checked=lane.enabled;on.input.style.width='auto';on.input.style.minHeight='auto';[n,k,l,f,com,on].forEach(x=>box.append(x.wrap));main.append(box);lanes.push({n,k,l,f,com,on});});const routine=c.routine||{enabled:false,weekday:0,local_time:'09:00'};main.append(node('h2','Weekly scouting routine'),node('p','Choose when TCE checks your enabled sources. Claude Code mode queues a job for your signed-in worker.'));const weekly=field('Scout automatically each week',null,'checkbox');weekly.input.checked=routine.enabled;weekly.input.style.width='auto';weekly.input.style.minHeight='auto';main.append(weekly.wrap);const day=field('Scouting day','','select');['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].forEach((name,index)=>{const option=node('option',name);option.value=String(index);day.input.append(option)});day.input.value=String(routine.weekday);main.append(day.wrap);const time=field('Your local time',routine.local_time,'time','Uses the timezone above, including daylight saving changes.');main.append(time.wrap);main.append(node('h2','Reasoning connection'));const mode=field('How scripts and ideas are generated',c.brain_mode,'select');[['unconfigured','Choose a connection'],['anthropic_api','Client-owned Anthropic API key for web generation'],['claude_code','Claude Code in your terminal']].forEach(([value,label])=>{const o=node('option',label);o.value=value;mode.input.append(o)});mode.input.value=c.brain_mode;main.append(mode.wrap);const model=field('Claude API model',c.brain_model||'claude-sonnet-5','text','Used only with your own Anthropic API key.');main.append(model.wrap);const save=node('button','Save settings','primary');save.type='submit';main.append(save);main.append(node('p','', 'progress'));main.lastChild.id='action-progress';main.addEventListener('submit',async e=>{e.preventDefault();const config={display_name:name.input.value,timezone:zone.input.value,audience:audience.input.value,focus:focus.input.value,voice_notes:voice.input.value,avoid:avoid.input.value,brain_mode:mode.input.value,brain_model:model.input.value,routine:{enabled:weekly.input.checked,weekday:Number(day.input.value),local_time:time.input.value},source_lanes:lanes.map(x=>({name:x.n.input.value,kind:x.k.input.value,locator:x.l.input.value,filter:x.f.input.value,comments:x.com.input.value,enabled:x.on.input.checked}))};try{const out=await act(save,'Saving a new settings version',()=>api('/api/config',{method:'PUT',body:JSON.stringify({expected_revision:state.config.revision,config})}));state.config={revision:out.revision,config:out.config,onboarded:true};$('workspace-name').textContent=config.display_name;toast('Settings saved');renderSettings();}catch{}});
const side=node('div',null,'stack');layout.append(side);const connect=node('div',null,'surface stack-tight');connect.append(node('h2','Connections'),node('p','Keys stay encrypted and are never shown again. Remove any connection here.'));for(const [kind,label] of [['openai_live','OpenAI GPT-Live 1'],['anthropic_api','Anthropic API'],['fathom','Fathom'],['github','GitHub']]){const wrapper=node('div',null,'stack-tight');const existing=state.secrets.find(x=>x.kind===kind);wrapper.append(node('h3',label),node('p',existing?(existing.verified?'Connected':'Saved, verification needed')+` (${existing.fingerprint})`:'Not connected','muted'));const f=field(`Set ${label} key`,'','password');wrapper.append(f.wrap);const buttons=row();buttons.append(button('Save key',async()=>{try{const out=await api(`/api/secrets/${kind}`,{method:'PUT',body:JSON.stringify({value:f.input.value})});state.secrets=state.secrets.filter(x=>x.kind!==kind);state.secrets.push(out);toast(out.verified?'Key verified':'Key saved. Check provider access before use.');renderSettings();}catch(e){toast(message(e));}},'secondary'));if(existing)buttons.append(button('Remove',async()=>{try{await api(`/api/secrets/${kind}`,{method:'DELETE'});state.secrets=state.secrets.filter(x=>x.kind!==kind);toast('Connection removed');renderSettings();}catch(e){toast(message(e));}},'quiet'));wrapper.append(buttons);connect.append(wrapper);}side.append(connect);const materials=node('div',null,'surface stack-tight');materials.append(node('h2','Your material'),node('p','Upload a book chapter or course as a source. Upload writing or audio to show your voice.'));const uploadForm=node('form',null,'stack-tight');const kind=field('Material purpose','','select');[['source','Idea source'],['voice','Voice example']].forEach(([v,t])=>{const o=node('option',t);o.value=v;kind.input.append(o)});uploadForm.append(kind.wrap);const lane=field('Idea source number','0','select');[0,1,2].forEach(i=>{const o=node('option',`Source ${i+1}`);o.value=String(i);lane.input.append(o)});uploadForm.append(lane.wrap);kind.input.addEventListener('change',()=>lane.wrap.hidden=kind.input.value==='voice');const file=field('Choose a file','','file');file.input.accept='.txt,.md,.pdf,.docx,.m4a,.mp3,.wav';uploadForm.append(file.wrap);const note=field('What should TCE notice','','textarea');uploadForm.append(note.wrap);const upload=node('button','Upload material','secondary');upload.type='submit';uploadForm.append(upload);materials.append(uploadForm);uploadForm.addEventListener('submit',async e=>{e.preventDefault();if(!file.input.files[0])return;const fd=new FormData();fd.append('file',file.input.files[0]);fd.append('kind',kind.input.value);if(kind.input.value==='source')fd.append('lane_index',lane.input.value);fd.append('notes',note.input.value);try{const out=await act(upload,'Uploading private material',()=>api('/api/materials',{method:'POST',body:fd}));state.materials.unshift(out);toast('Material added');renderSettings();}catch{}});state.materials.forEach(item=>{const r=node('div',null,'stack-tight');r.append(node('strong',item.name),node('span',`${item.kind}${item.lane_index!==null?` for source ${item.lane_index+1}`:''}`,'muted'));r.append(button(item.active?'Pause':'Use again',async()=>{try{const out=await api(`/api/materials/${item.id}/active?active=${!item.active}`,{method:'POST'});Object.assign(item,out);renderSettings();}catch(e){toast(message(e));}},'pill'));if(item.kind==='voice'&&/\.(m4a|mp3|wav)$/i.test(item.name)){const transcribe=button(item.transcribed?'Transcribe again with my OpenAI key':'Transcribe with my OpenAI key',async()=>{try{const out=await act(transcribe,'Transcribing this voice sample',()=>api(`/api/materials/${item.id}/transcribe`,{method:'POST'}));Object.assign(item,out);toast('Voice words are ready for future scripts');renderSettings();}catch{}},'secondary');r.append(transcribe);if(item.transcribed)r.append(node('p',item.transcript_excerpt,'muted'));}materials.append(r)});side.append(materials);const terminal=node('div',null,'surface stack-tight');terminal.append(node('h2','Terminal mode'),node('p','Create a scoped token for Claude Code or your own terminal. TCE exposes only your workspace. It never publishes.'));const make=button('Create terminal token',async()=>{try{const out=await api('/api/tokens',{method:'POST',body:JSON.stringify({label:'My terminal',scopes:['read','write','record','export','deliver'],days:30})});const secret=node('textarea');secret.readOnly=true;secret.value=out.token;terminal.append(node('p','Copy this token now. It will not be shown again.','note'),secret);toast('Terminal token created');}catch(e){toast(message(e));}},'secondary');terminal.append(make);side.append(terminal);const history=node('div',null,'surface stack-tight');history.append(node('h2','Settings history'));side.append(history);try{const versions=await api('/api/config/history');versions.forEach(item=>{const r=row();r.append(node('span',`Version ${item.revision} (${item.reason})`));if(item.revision!==state.config.revision)r.append(button('Restore',async()=>{try{const out=await api('/api/config/restore',{method:'POST',body:JSON.stringify({expected_revision:state.config.revision,restore_revision:item.revision})});state.config={revision:out.revision,config:out.config,onboarded:true};toast('Earlier settings restored as a new version');renderSettings();}catch(e){toast(message(e));}},'quiet'));history.append(r);});}catch{} }

function inviteScreen(token){history.replaceState(null,'','/app');document.querySelector('.login-copy h1').textContent='Make this studio yours.';document.querySelector('.login-copy p').textContent='Set a password, then choose your sources and voice.';const form=$('login-form');form.replaceChildren(node('h2','Start your workspace'));const password=field('Create a password','','password','At least 16 characters.');password.input.minLength=16;password.input.required=true;password.input.autocomplete='new-password';const confirm=field('Confirm password','','password');confirm.input.required=true;confirm.input.autocomplete='new-password';const submit=node('button','Activate my workspace','primary');submit.type='submit';const note=node('p','','form-note');note.setAttribute('role','status');form.append(password.wrap,confirm.wrap,submit,note);form.addEventListener('submit',async e=>{e.preventDefault();if(password.input.value!==confirm.input.value){note.textContent='Passwords do not match.';return;}submit.disabled=true;submit.textContent='Activating your private workspace';note.textContent='Checking your one-time invitation and creating your account';try{await api('/auth/accept-invite',{method:'POST',body:JSON.stringify({token,password:password.input.value})});await load();}catch(error){note.textContent=message(error);}finally{submit.disabled=false;submit.textContent='Activate my workspace';}});}
(async()=>{const hash=location.hash.slice(1);if(hash.startsWith('invite=')){inviteScreen(hash.slice(7));return;}try{await load();if(['today','ideas','week','record','library','settings'].includes(hash)&&state.config.onboarded)show(hash);}catch{$('login-shell').hidden=false;$('studio').hidden=true;}})();
