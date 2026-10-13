/* One focused step at a time. Every change is saved to an encrypted server draft. */
function renderOnboarding(){
  const draft=state.onboardingDraft||{step:0,config:structuredClone(state.config.config)};
  state.onboardingDraft=draft;
  const c=draft.config,step=Math.min(6,Math.max(0,draft.step));
  const names=['Your perspective','First idea source','Second idea source','Third idea source','Your voice and files','Your connections','Review your studio'];
  header('Set up your private studio',`Step ${step+1} of 7: ${names[step]}. Everything can be changed later in Settings.`);
  const panel=surface();panel.classList.add('onboarding-panel');
  panel.append(node('span',`Step ${step+1} of 7`,'eyebrow'),node('h2',names[step]));
  const status=node('p','Your progress is saved privately to your account.','progress');
  status.setAttribute('role','status');
  let timer,pending=Promise.resolve();
  function persist(){
    clearTimeout(timer);status.textContent='Saving your private setup';
    const snapshot=JSON.stringify(draft);
    pending=pending.catch(()=>{}).then(()=>api('/api/onboarding/draft',{method:'PUT',body:snapshot}))
      .then(()=>{status.textContent='Saved. You can resume after a reload or reboot.';})
      .catch(error=>{status.textContent=`Could not save: ${message(error)}. Stay on this step and try again.`;throw error;});
    return pending;
  }
  function schedule(){status.textContent='Changes waiting to save';clearTimeout(timer);timer=setTimeout(()=>{void persist().catch(()=>{});},650);}
  function bind(label,value,assign,type='text',hint=''){
    const f=field(label,value,type,hint);panel.append(f.wrap);
    f.input.addEventListener('input',()=>{assign(f.input.value);schedule();});
    f.input.addEventListener('change',()=>{assign(f.input.value);schedule();});
    return f;
  }
  if(step===0){
    panel.append(node('p','Start with your point of view. You can add the rest one step at a time.'));
    bind('Name shown in your studio',c.display_name,v=>c.display_name=v);
    bind('Who you speak to',c.audience,v=>c.audience=v,'textarea');
    bind('What you help them do',c.focus,v=>c.focus=v,'textarea');
    bind('Timezone',c.timezone,v=>c.timezone=v,'text','For example America/New_York.');
  }else if(step<=3){
    const i=step-1,lane=c.source_lanes[i];
    panel.append(node('p',`Choose one source of real ideas. Source ${i+1} can be a book, research, course, calls, commits, or news.`));
    bind('Source name',lane.name,v=>lane.name=v);
    const kind=bind('Source type',lane.kind,v=>lane.kind=v,'select');
    ['book','research','course','upload','fathom','commits','ai_news','custom'].forEach(type=>{const option=node('option',sourceName(type));option.value=type;kind.input.append(option);});kind.input.value=lane.kind;
    bind('What counts as a useful idea',lane.filter,v=>lane.filter=v,'textarea');
    bind('Instructions for this source',lane.comments,v=>lane.comments=v,'textarea','Tell TCE how to use this material.');
    bind('Connection or location',lane.locator||'',v=>lane.locator=v,'text','Optional for uploaded files.');
    const enabled=field('Use this source',null,'checkbox');enabled.input.checked=lane.enabled;enabled.input.style.width='auto';enabled.input.style.minHeight='auto';enabled.input.addEventListener('change',()=>{lane.enabled=enabled.input.checked;schedule();});panel.append(enabled.wrap);
    const files=state.materials.filter(m=>m.kind==='source'&&m.lane_index===i&&m.active);
    panel.append(node('p',files.length?`Attached: ${files.map(m=>m.name).join(', ')}`:'No file attached yet. You can add one now or later.','muted'));
    const file=field('Upload a book, course, or notes','','file');file.input.accept='.pdf,.docx,.txt,.md';panel.append(file.wrap);
    const instruction=field('What should TCE notice in this file','','textarea');panel.append(instruction.wrap);
    panel.append(button('Upload this file',async()=>{
      if(!file.input.files[0]){status.textContent='Choose a file first.';return;}
      const fd=new FormData();fd.append('file',file.input.files[0]);fd.append('kind','source');fd.append('lane_index',String(i));fd.append('notes',instruction.input.value);
      status.textContent='Uploading and checking every readable page';
      try{const item=await api('/api/materials',{method:'POST',body:fd});state.materials=state.materials.filter(m=>m.id!==item.id);state.materials.unshift(item);status.textContent=item.page_count?`Ready: ${item.readable_page_count} of ${item.page_count} pages contain readable text.`:'File ready for scouting.';}
      catch(error){status.textContent=message(error);}
    },'secondary'));
  }else if(step===4){
    panel.append(node('p','A few sentences in your own words help scripts sound like you. A writing or audio sample is optional.'));
    bind('How your voice sounds',c.voice_notes,v=>c.voice_notes=v,'textarea');
    bind('Claims or topics to avoid',c.avoid,v=>c.avoid=v,'textarea');
    const file=field('Voice example','','file');file.input.accept='.txt,.md,.m4a,.mp3,.wav';panel.append(file.wrap);
    panel.append(button('Upload voice example',async()=>{
      if(!file.input.files[0]){status.textContent='Choose a file first.';return;}
      const fd=new FormData();fd.append('file',file.input.files[0]);fd.append('kind','voice');status.textContent='Uploading your private voice example';
      try{const item=await api('/api/materials',{method:'POST',body:fd});state.materials=state.materials.filter(m=>m.id!==item.id);state.materials.unshift(item);status.textContent='Voice example saved. Audio transcription can be started later in Settings.';}
      catch(error){status.textContent=message(error);}
    },'secondary'));
  }else if(step===5){
    panel.append(node('p','Connections are optional now. You can add or remove them later in Settings. Provider keys are encrypted before storage and never shown again.'));
    const mode=field('Reasoning connection',c.brain_mode,'select');[['unconfigured','Set up later'],['claude_code','Claude Code in my terminal'],['anthropic_api','My Anthropic API key']].forEach(([v,label])=>{const o=node('option',label);o.value=v;mode.input.append(o);});mode.input.value=c.brain_mode;mode.input.addEventListener('change',()=>{c.brain_mode=mode.input.value;schedule();});panel.append(mode.wrap);
    for(const [kind,label] of [['anthropic_api','Anthropic API key'],['openai_live','OpenAI live voice key']]){
      const key=field(label,'','password');panel.append(key.wrap);
      panel.append(button(`Save ${label}`,async()=>{
        status.textContent=`Checking ${label} with its provider`;
        try{const result=await api(`/api/secrets/${kind}`,{method:'PUT',body:JSON.stringify({value:key.input.value})});state.secrets=state.secrets.filter(s=>s.kind!==kind);state.secrets.push(result);key.input.value='';status.textContent=result.verified?`${label} saved and verified.`:`${label} saved, but provider access was not verified.`;}
        catch(error){status.textContent=message(error);}
      },'secondary'));
    }
  }else{
    panel.append(node('p','Only your workspace can open this setup. Your draft, provider keys, ideas, and scripts use authenticated encryption at rest. Files and other records are isolated by workspace access controls.'));
    panel.append(node('p','When you ask TCE to generate ideas, scripts, or live conversation, the selected content is sent to the provider you connect. TCE does not publish for you.'));
    panel.append(node('p','Your three sources: '+c.source_lanes.map((l,i)=>`${i+1}. ${l.name} (${l.enabled?'on':'off'})`).join('; ')));
    panel.append(node('p','TCE does not publish for you. Settings lets you revise every choice.'));
  }
  panel.append(status);
  const actions=row();
  if(step>0)actions.append(button('Back',async()=>{try{await pending;draft.step=step-1;await persist();renderOnboarding();}catch{}},'quiet'));
  if(step<6)actions.append(button('Save and continue',async()=>{try{await pending;draft.step=step+1;await persist();renderOnboarding();}catch{}},'primary'));
  else actions.append(button('Finish setup',async()=>{
    try{await persist();status.textContent='Saving your studio and opening your ideas';const out=await api('/api/config',{method:'PUT',body:JSON.stringify({expected_revision:state.config.revision,config:c})});state.config={revision:out.revision,config:out.config,onboarded:true};state.onboardingDraft=null;$('workspace-name').textContent=c.display_name;show('today');toast('Your studio is ready');}
    catch(error){status.textContent=message(error);}
  },'primary'));
  panel.append(actions);
}
