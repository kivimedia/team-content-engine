const fs=require('fs'),path=require('path');
let chromium;try {({chromium}=require(process.env.TCE_PLAYWRIGHT_MODULE||'playwright'));} catch {({chromium}=require('/home/ziv/node_modules/playwright'));}
const os=require('os'),out=process.env.TCE_SHOT_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'tce-book-ux-')); 
(async()=>{
 const root=path.resolve(__dirname,'../../src/tce/api'),checks=[],errors=[];
 const browser=await chromium.launch({channel:process.env.TCE_BROWSER_CHANNEL||undefined,headless:true,args:['--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP * 0.0.0.0']});
 const check=(name,pass)=>checks.push({name,pass});
 try{for(const width of [1440,390]){
  let phase='ready';
  const ctx=await browser.newContext({viewport:{width,height:900}}),p=await ctx.newPage();
  p.on('pageerror',e=>errors.push(e.message));
  await p.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.hostname!=='book.invalid')return r.abort();
   if(u.pathname==='/voice-client.js')return r.fulfill({status:503,body:''});
   if(u.pathname.includes('/api/v1/')){
    if(r.request().method()!=='GET')return r.fulfill({status:403,json:{detail:'Fixture forbids writes'}});
    const c={n:1,title:'A chapter to review',part:'Part two',version:phase==='ready-v2'?2:1,status:'in_review',status_words:'In review',paragraphs:['First paragraph.','Second paragraph.','Third paragraph.'],previous:null,next:null,narration:{on:false}};
    if(['layout','approved_unwritten'].includes(phase))Object.assign(c,{phased:true,readable:false,phase,phase_words:'Layout review',layout_status:phase==='layout'?'draft':'approved',layout:{big_idea:'The lesson for this chapter',covers:['A concrete story'],question:'What should the reader try?'},paragraphs:[]});
    return r.fulfill({json:u.pathname.endsWith('/chapters/1')?c:{chapters:[c],narration:{on:false}}});
   }
   const f=path.join(root,u.pathname.startsWith('/book/')?'book.html':u.pathname.slice(1));
   return fs.existsSync(f)?r.fulfill({body:fs.readFileSync(f),contentType:f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':'text/html'}):r.fulfill({status:404,body:''});
  });
  await p.goto('https://book.invalid/book/1');await p.waitForTimeout(400);await p.locator('#paragraphs p').first().waitFor({timeout:3000});
  await p.locator('#nextPara').click();await p.reload();await p.locator('#paragraphs p').first().waitFor();
  check(width+' saved reading position',await p.locator('#paragraphs p.now').getAttribute('data-i')==='1');
  check(width+' version always visible',(await p.locator('#chapterPart').innerText()).includes('version 1'));
  check(width+' approval shares player dock',await p.locator('#player #approveButton').count()===1);
  await p.locator('#talkButton').click();await p.locator('#editorText').fill('Please clarify this paragraph.');
  await p.locator('#editorForm button[type=submit]').click();await p.waitForTimeout(250);
  check(width+' failed editor connection retains comment',await p.locator('#editorText').inputValue()==='Please clarify this paragraph.');
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
  await ctx.close();
 }}finally{await browser.close();}
 check('No JavaScript errors',errors.length===0);
 const result={checks,errors,passed:checks.filter(x=>x.pass).length,failed:checks.filter(x=>!x.pass).length};
 fs.writeFileSync(path.join(out,'book-'+(process.argv[2]||'after')+'.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));if(result.failed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
