// 18-Nov-2026 (T-22864): the Book shows the book editor like KM BOT - catch-up, its list,
// past replies with the unseen ones marked new, and a new call that asks for them first.
// 20-Nov-2026: the rows below have the shape the live KM BOT history API really sends (read
// on the box: his turns carry from 'ziv' and origin 'you', never origin 'ziv'; a quick reply is
// 'ack' with no 'result'; a KM BOT notice is from 'system'). The first fixture used origin 'ziv',
// so the test passed while the live Book painted none of his own lines.
const fs=require('fs'),path=require('path'),os=require('os');
let chromium;try {({chromium}=require(process.env.TCE_PLAYWRIGHT_MODULE||'playwright'));} catch {({chromium}=require('/home/ziv/node_modules/playwright'));}
const out=process.env.TCE_SHOT_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'tce-book-agent-'));
(async()=>{
 const root=path.resolve(__dirname,'../../src/tce/api'),checks=[],errors=[];
 const check=(name,pass)=>checks.push({name,pass:Boolean(pass)});
 const browser=await chromium.launch({headless:true});
 const now=Date.now(),iso=(ms)=>new Date(ms).toISOString();
 const turns=[{run_id:'r1',at:iso(now-864e5),from:'ziv',transport:'api',origin:'you',message:'Can you tighten chapter 11?',ack:'On it.',result:'Tightened chapter 11, it is in review.'},
  {run_id:'r2',at:iso(now-36e5),from:'ziv',transport:'voice',origin:'you',message:'Is the bakery layout done?',ack:'Yes: the bakery chapter layout is ready for you, three beats, one question for you.',result:''},
  {run_id:'r3',at:iso(now-18e5),from:'system',transport:'routine',origin:'',message:'',result:'The "book editor write requests" routine switched itself off after failing 10 runs in a row.'}];
 const tasks=[{id:'T-1',title:'Chapter 12 layout waits for your approval',status:'blocked',assigned:'book-editor',blocked_why:'blocked_on: owner needs=decision - approve the layout'},
  {id:'T-2',title:'Writing chapter 13 from your outline',status:'open',assigned:'book-editor',blocked_why:null},
  {id:'T-3',title:'Someone else',status:'open',assigned:'dev'}];
 try{for(const width of [390,1440]){
  const ctx=await browser.newContext({viewport:{width,height:900}}),p=await ctx.newPage();
  p.on('pageerror',e=>errors.push(e.message));
  await p.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.hostname!=='book.invalid')return r.abort();
   if(u.pathname==='/voice-client.js')return r.fulfill({status:503,body:''});
   if(u.pathname==='/kmbot-api/history')return r.fulfill({json:{agent:'book-editor',view:'chat',turns}});
   if(u.pathname==='/kmbot-api/tasks')return r.fulfill({json:{tasks}});
   if(u.pathname.includes('/api/v1/')){
    if(r.request().method()!=='GET')return r.fulfill({status:403,json:{}});
    return r.fulfill({json:{chapters:[{n:11,title:'The eleventh',part:'Part two',status:'in_review',status_words:'In review',status_at:iso(now-864e5),readable:true,paragraphs:12},{n:12,title:'The twelfth',part:'Part two',status:'to_write',status_at:iso(now-36e5)}],narration:{on:false}}});
   }
   const f=path.join(root,/^\/book(?:\/|$)/.test(u.pathname)?'book.html':u.pathname.slice(1));
   return fs.existsSync(f)?r.fulfill({body:fs.readFileSync(f),contentType:f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':'text/html'}):r.fulfill({status:404,body:''});
  });
  // He last opened the Book two hours ago: the day-old exchange is seen, the two newer rows are not.
  await p.addInitScript(()=>{try{localStorage.setItem('tce-book-editor-seen',String(Date.now()-72e5));}catch{}});
  await p.goto('https://book.invalid/book');await p.locator('#agentCatchup').waitFor({state:'visible',timeout:4000}).catch(()=>{});
  const cu=await p.locator('#agentCatchup').innerText().catch(()=>'');
  check(width+' catch-up names last chapter and what waits, chapters to review included',/Last worked on/.test(cu)&&/2 things wait on you/.test(cu)&&/1 chapter to review/.test(cu));
  check(width+' catch-up says what the editor is on',/Writing chapter 13/.test(cu));
  const list=await p.locator('#agentList').innerText().catch(()=>'');
  check(width+' list splits waiting and working',/Waiting on you[\s\S]*Chapter 12 layout[\s\S]*working on[\s\S]*chapter 13/i.test(list));
  check(width+' list leaves other agents out',!/Someone else/.test(list));
  check(width+' card opens in KM BOT',await p.locator('#agentList a').first().getAttribute('href')==='/c/T-1');
  await p.screenshot({path:path.join(out,`list-${width}.png`)});
  await p.locator('#listTalk').click();await p.waitForTimeout(200);
  const log=await p.locator('#editorLog').innerText().catch(()=>'');
  check(width+' chat shows past exchanges',/Tightened chapter 11/.test(log));
  check(width+' his own lines paint as You',/You\s*Can you tighten chapter 11\?/.test(log)&&/You\s*Is the bakery layout done\?/.test(log));
  check(width+' a quick reply with no result still paints',/bakery chapter layout is ready/.test(log));
  check(width+' a KM BOT notice is not called the editor',/KM BOT( \(new\))?\s*The "book editor write requests"/.test(log));
  check(width+' unseen replies marked new',await p.locator('#editorLog .chat-line.fresh').count()===2);
  await p.evaluate(()=>{window.sent=[];window.KmVoice={start:({on})=>{window.callOn=on;setTimeout(()=>on('realtime',{}),0);return {send:t=>sent.push(t),stop(){},mute(){}};}};});
  await p.locator('#editorText').fill('Where are we?');await p.locator('#editorForm button[type=submit]').click();await p.waitForTimeout(200);
  const first=await p.evaluate(()=>window.sent[0]||'');
  check(width+' new call asks for the unseen replies first',/2 replies he has not seen/.test(first)&&/Ziv: Where are we\?/.test(first));
  check(width+' the first line carries what the unseen replies say',/bakery chapter layout is ready/.test(first)&&/switched itself off/.test(first));
  check(width+' the first line does not carry a reply he saw',!/Tightened chapter 11/.test(first));
  await p.evaluate(()=>{window.callOn('said',{text:'Where are we?'});window.callOn('turn_end',{text:'Two things first: the bakery layout is ready, and the routine switched itself off.'});});
  check(width+' the status line stops waiting once the reply is in',!/Waiting for the reply/.test(await p.locator('#editorState').innerText())&&/Two things first/.test(await p.locator('#editorLog').innerText()));
  await p.screenshot({path:path.join(out,`chat-${width}.png`)});
  const fontOk=await p.evaluate(()=>[...document.querySelectorAll('.agent-card,.agent-catchup p')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=15));
  check(width+' text at 15px or more',fontOk);
  await ctx.close();
 }} finally {await browser.close();}
 const failed=checks.filter(c=>!c.pass);
 console.log(JSON.stringify({checks,errors,shots:out},null,1));
 process.exit(failed.length||errors.length?1:0);
})();
