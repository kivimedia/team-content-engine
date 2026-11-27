const fs=require('fs'),path=require('path');
let chromium;try {({chromium}=require(process.env.TCE_PLAYWRIGHT_MODULE||'playwright'));} catch {({chromium}=require('/home/ziv/node_modules/playwright'));}
const os=require('os'),out=process.env.TCE_SHOT_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'tce-book-ux-')); 
(async()=>{
 const root=path.resolve(__dirname,'../../src/tce/api'),checks=[],errors=[];
 const browser=await chromium.launch({channel:process.env.TCE_BROWSER_CHANNEL||undefined,headless:true,args:['--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP * 0.0.0.0']});
 const check=(name,pass)=>checks.push({name,pass});
 try{for(const width of [1440,390]){
  let phase='ready', shelf=[];
  const ctx=await browser.newContext({viewport:{width,height:900}}),p=await ctx.newPage();
  p.on('pageerror',e=>errors.push(e.message));
  await p.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.hostname!=='book.invalid')return r.abort();
   if(u.pathname==='/voice-client.js')return r.fulfill({status:503,body:''});
   if(u.pathname.includes('/api/v1/')){
    if(r.request().method()!=='GET')return r.fulfill({status:403,json:{detail:'Fixture forbids writes'}});
    const c={n:1,title:'A chapter to review',part:'Part two',version:phase==='ready-v2'?2:1,status:'in_review',status_words:'In review',paragraphs:['First paragraph.','Second paragraph.','Third paragraph.'],previous:null,next:null,narration:{on:false}};
    if(['layout','approved_unwritten'].includes(phase))Object.assign(c,{phased:true,readable:false,phase,phase_words:'Layout review',layout_status:phase==='layout'?'draft':'approved',layout:{big_idea:'The lesson for this chapter',covers:['A concrete story'],question:'What should the reader try?'},paragraphs:[]});
    const number=u.pathname.match(/\/chapters\/(\d+)$/);
    const detail=number && shelf.find(ch=>ch.n===Number(number[1]));
    return r.fulfill({json:number?(detail?{...c,...detail,paragraphs:detail.readable?c.paragraphs:[]}:c):{chapters:shelf,narration:{on:false}}});
   }
   const f=path.join(root,/^\/book(?:\/|$)/.test(u.pathname)?'book.html':u.pathname.slice(1));
   return fs.existsSync(f)?r.fulfill({body:fs.readFileSync(f),contentType:f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':'text/html'}):r.fulfill({status:404,body:''});
  });
  await p.goto('https://book.invalid/book/1');await p.waitForTimeout(400);await p.locator('#paragraphs p').first().waitFor({timeout:3000});
  await p.locator('#nextPara').click();await p.reload();await p.locator('#paragraphs p').first().waitFor();
  check(width+' saved reading position',await p.locator('#paragraphs p.now').getAttribute('data-i')==='1');
  check(width+' version always visible',(await p.locator('#chapterPart').innerText()).includes('version 1'));
  check(width+' approval shares player dock',await p.locator('#player #approveButton').count()===1);
  await p.locator('#bookMic').click();await p.locator('#editorType').click();await p.locator('#editorText').fill('Please clarify this paragraph.');
  await p.locator('#editorForm button[type=submit]').click();await p.waitForTimeout(250);
   check(width+' failed editor connection retains comment',await p.locator('#editorText').inputValue()==='Please clarify this paragraph.');
   await p.evaluate(()=>{window.fixtureSent=[];window.KmVoice={start:({on})=>{window.fixtureCall=on;setTimeout(()=>on('realtime',{}),0);return {send:text=>fixtureSent.push(text),stop:()=>on('closed',{})};}};});
   await p.locator('#editorForm button[type=submit]').click();await p.waitForTimeout(100);
   await p.evaluate(()=>fixtureCall('error',{text:'Fixture transport failure'}));
   check(width+' transport failure retains draft',await p.locator('#editorText').inputValue()==='Please clarify this paragraph.');
   await p.locator('#editorForm button[type=submit]').click();
   check(width+' retry carries paragraph context',await p.evaluate(()=>fixtureSent.length===2&&fixtureSent.every(t=>t.startsWith('[Where I am in the Book]'))));
   await p.evaluate(()=>fixtureCall('said',{text:fixtureSent.at(-1)}));
   check(width+' acknowledged comment clears draft',await p.locator('#editorText').inputValue()==='');
  check(width+' no horizontal overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await p.screenshot({path:path.join(out,'book-'+(process.argv[2]||'after')+'-'+width+'.png'),fullPage:true});
  phase='ready-v2';await p.reload();await p.locator('#paragraphs p').first().waitFor();
  check(width+' new version starts at its own reading position',await p.locator('#paragraphs p.now').getAttribute('data-i')==='0');
  phase='layout';await p.reload();await p.locator('#layoutPlan').waitFor();
  check(width+' layout must be approved before reading',await p.locator('#layoutApprove').isVisible()&&!await p.locator('#player').isVisible()&&!await p.locator('#writeButton').isVisible());
  await p.locator('#planNoteText').fill('Keep my layout note on failure');await p.locator('#planNoteForm [type=submit]').click();await p.waitForTimeout(100);
  check(width+' failed layout note stays in its field',await p.locator('#planNoteText').inputValue()==='Keep my layout note on failure');
  phase='approved_unwritten';await p.reload();await p.locator('#layoutPlan').waitFor();
  check(width+' approved layout offers writing before chapter review',await p.locator('#writeButton').isVisible()&&!await p.locator('#approveButton').isVisible()&&!await p.locator('#player').isVisible());
  phase='ready';
  const episode=(n,phase,extra={})=>({n,title:'Episode title '+n,group:'new',phased:true,phase,phase_words:phase,layout_status:'proposed',status:'draft',readable:false,minutes:0,...extra});
  shelf=[
   episode(12,'layout',{layout_status:'to_plan'}),
   episode(13,'approved_unwritten',{layout_status:'approved',write_requested_at:'2026-11-17'}),
   episode(14,'on_hold'),episode(15,'approved',{status:'approved',readable:true}),
   episode(16,'ready',{readable:true,minutes:3})
  ];
  await p.goto('https://book.invalid/book');
  const next=p.locator('#reviewNext');
  await next.waitFor({timeout:2500});
  check(width+' written episode first',await next.innerText()==='Review chapter' && await next.getAttribute('href')==='/book/16');
  check(width+' full list and narration details start folded',!await p.locator('#chapterList').isVisible()&&!await p.locator('#narrationNote').isVisible());
  await next.click();await p.waitForURL('**/book/16');await p.locator('#player').waitFor();
  check(width+' review link opens that episode',await p.locator('#chapterTitle').innerText()==='Episode 16: Episode title 16');
  await p.locator('#nextPara').click();
  await p.locator('#bookBack').click();await next.waitFor();
  check(width+' unfinished chapter offers continuation',await next.innerText()==='Continue reading' && await next.getAttribute('href')==='/book/16');
  shelf.pop();await p.goto('https://book.invalid/book');await next.waitFor();
  check(width+' skips pending and unprepared layouts',await next.innerText()==='Review layout' && await next.getAttribute('href')==='/book/14');
  await p.locator('#chapterDirectory summary').click();
  check(width+' directory preserves layout order',JSON.stringify(await p.locator('#chapterList [data-chapter]').evaluateAll(bs=>bs.map(b=>Number(b.dataset.chapter))))===JSON.stringify([12,13,14,15]));
  shelf=shelf.filter(ch=>ch.n!==14);await p.reload();await p.locator('#chapterDirectory summary').waitFor();
  check(width+' empty review queue keeps writing and approval under author control',!await next.isVisible() && await p.locator('#reviewTitle').innerText()==='Nothing to review right now');
  shelf[1].write_requested_at=null;await p.reload();await next.waitFor();
  check(width+' approved unrequested layout opens for a writing decision',await next.innerText()==='Open approved layout' && await next.getAttribute('href')==='/book/13');
  check(width+' book landing fits viewport',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await p.screenshot({path:path.join(out,'book-home-'+(process.argv[2]||'after')+'-'+width+'.png')});
  const original={n:3,title:'An earlier chapter',group:'written',version:1,phased:false,readable:true,paragraphs:3,status:'in_review',status_words:'In review'};
  shelf.unshift(original);
  await p.reload();await next.waitFor();
  check(width+' Part One is available without displacing new work',await next.getAttribute('href')==='/book/13');
  await p.locator('#writtenFold summary').click();
  await p.locator('#writtenList [data-chapter="3"]').click();await p.locator('#player').waitFor();
  await p.locator('#bookBack').click();await next.waitFor();
  check(width+' first paragraph can be resumed',await next.innerText()==='Continue reading' && await next.getAttribute('href')==='/book/3');
  await p.goto('https://book.invalid/book/3');await p.locator('#player').waitFor();
  await p.locator('#nextPara').click();await p.locator('#bookBack').click();await next.waitFor();
  check(width+' choosing an unfinished Part One chapter takes precedence',await next.innerText()==='Continue reading' && await next.getAttribute('href')==='/book/3');
  original.version=2;await p.reload();await next.waitFor();
  check(width+' rewritten Part One returns focus to new work',await next.getAttribute('href')==='/book/13');
  await p.goto('https://book.invalid/book/3');await p.locator('#player').waitFor();
  await p.evaluate(()=>Object.defineProperty(window.speechSynthesis,'speak',{value:utterance=>queueMicrotask(()=>utterance.onend())}));
  await p.locator('#playButton').click();
  await p.waitForFunction(()=>document.getElementById('bookState').textContent==='End of the chapter');
  await p.locator('#bookBack').click();await next.waitFor();
  check(width+' finishing narration returns focus to new work',await next.getAttribute('href')==='/book/13');
  await ctx.close();
 }}finally{await browser.close();}
 check('No JavaScript errors',errors.length===0);
 const result={checks,errors,passed:checks.filter(x=>x.pass).length,failed:checks.filter(x=>!x.pass).length};
 fs.writeFileSync(path.join(out,'book-'+(process.argv[2]||'after')+'.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));if(result.failed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
