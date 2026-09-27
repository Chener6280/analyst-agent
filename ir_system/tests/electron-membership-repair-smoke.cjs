// Isolated fixture profile. Real approval/supersession UI, synthetic downloader.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{makePlan}=require('../src/main/sync/policy');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-membership-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString();
 s.settings.policies=['123','456'].map(collectionId=>({provider:'zsxq',collectionId,name:'模拟星球 '+collectionId,mode:'incremental',firstDate:'2026-01-01'}));
 s.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:stamp,collections:s.settings.policies.map(p=>({collectionId:p.collectionId,name:p.name,present:true,membership:{active:true},permissions:{allow_download:true},skill_api:'accessible'}))}]};
 const relative='zsxq_web/jobs/desktop-abc123/manifest.json',file=path.join(archive,relative);fs.mkdirSync(path.dirname(file),{recursive:true});
 fs.writeFileSync(file,JSON.stringify({stage:'discover_topics',error:{code:'membership_expired',diagnostic:{message:'The group membership is expired in the browser session'}},topics_processed_total:0,record_refs:[],job:{group_id:'123',group_name:'模拟星球 123',membership:{active:true}}}));
 const selection={provider:'zsxq',start:'2026-08-27',end:'2026-09-26'};
 s.jobs=[{id:'00000000-0000-4000-8000-000000000001',kind:'sync',root:archive,status:'needs_attention',code:'membership_expired',stage:'web_downloading',attempt:1,counts:{operations:1,downloaded:0},createdAt:stamp,finishedAt:stamp,selection,webManifests:[relative],plan:makePlan(s.settings,{},'backfill',archive,undefined,selection)}];store.save();
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:path.join(root,'.runtime/venv/bin/python'),IR_SYSTEM_IR_SEARCH_PATH:'/Users/chen/Documents/ir_search'}});
 try{
  await app.evaluate(({dialog})=>{globalThis.confirmations=[];dialog.showMessageBox=async(_w,o)=>{globalThis.confirmations.push(o);return {response:0};};});
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();
  await page.locator('[data-source-readiness="zsxq"]').click();
  await page.locator('[data-readiness-tone="ready"]').waitFor();
  assert.match(await page.locator('.dc-task-warnings').innerText(),/不影响环境颜色/);
  assert.equal(await page.locator('.dc-task-warnings input').count(),0);
  const output=path.join(root,'.local/membership-isolation-acceptance');fs.mkdirSync(output,{recursive:true});
  await page.locator('#source-dialog').screenshot({path:path.join(output,'ready-with-task-warning.png'),scale:'css'});
  await page.locator('[data-dialog-close]').click();
  assert.equal(await page.locator('[data-sync-resume]').count(),1);
  await page.locator('#global-start').fill('260920');await page.locator('#global-end').fill('260926');
  await page.locator('[data-source-update="zsxq"][data-kind="backfill"]').click();
  await page.getByRole('button',{name:'确认范围并继续',exact:true}).click();
  await page.waitForFunction(async()=>(await window.irSystem.syncGetState()).busy===false);
  const confirmation=(await app.evaluate(()=>globalThis.confirmations)).at(-1);
  assert.match(confirmation.message,/启动一次性历史回补/);assert.match(confirmation.detail,/将替代 1 个旧任务/);assert.match(confirmation.detail,/2026-09-20/);
  assert.match(confirmation.detail,/自动分批处理完整已选范围/);
  assert.match(confirmation.detail,/网页下载默认后台无头运行/);
  const after=await page.evaluate(()=>window.irSystem.syncGetState());
  assert.equal(after.jobs.length,1);assert.equal(after.jobs[0].status,'needs_attention');assert.deepEqual(after.watermarks,{});assert.equal(after.settings.policies.filter(p=>p.mode==='incremental').length,2);
  // Disable only the isolated test downloader. Production approvals and state
  // transitions remain real; no provider requests are made after confirmation.
  const simulateBatches=process.env.IR_SYSTEM_TEST_AUTO_BATCH==='1';
  await app.evaluate(({app,dialog},simulateBatches)=>{
    const load=process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json');
    const {SyncManager}=load('./src/main/sync/manager');
    const original=SyncManager.prototype.launch;
    SyncManager.prototype.launch=function(job,request){
      if(!simulateBatches){globalThis.startedRequest=request;job.status='budget_paused';job.stage='enumerating';job.code='synthetic_budget_pause';this.store.save();return;}
      globalThis.batchRequests=[];
      this.runner=(request,_provider,_runtime,event)=>{
        globalThis.batchRequests.push(request.jobDirectory);const done=globalThis.batchRequests.length===3;
        event({stage:'downloading',counts:{newRecords:1,downloaded:1}});
        return {stop(){},promise:Promise.resolve({status:done?'completed':'budget_paused',code:done?null:'operation_budget_exhausted',stage:done?'finished':'downloading',counts:{newRecords:1,downloaded:1,operations:60}})};
      };
      return original.call(this,job,request);
    };
    dialog.showMessageBox=async()=>({response:1});
  },simulateBatches);
  await page.locator('[data-source-update="zsxq"][data-kind="backfill"]').click();
  await page.getByRole('button',{name:'确认范围并继续',exact:true}).click();
  await page.waitForFunction(async()=>(await window.irSystem.syncGetState()).jobs.length===2);
  const replaced=await page.evaluate(()=>window.irSystem.syncGetState());
  assert.equal(replaced.jobs[1].status,'superseded');assert.equal(replaced.jobs[0].collections[0].start,'2026-09-20');
  if(simulateBatches){
    let finished;const deadline=Date.now()+15000;
    do{finished=await page.evaluate(()=>window.irSystem.syncGetState());if(finished.jobs[0].status==='completed')break;await page.waitForTimeout(100);}while(Date.now()<deadline);
    assert.equal(finished.jobs[0].status,'completed');
    assert.equal(finished.jobs[0].counts.downloaded,3);assert.equal(finished.jobs[0].batchNumber,3);
    assert.equal(finished.jobs[0].untilComplete,true);
    const requests=await app.evaluate(()=>globalThis.batchRequests);assert.equal(requests.length,3);assert.equal(new Set(requests).size,1);
  }else assert.deepEqual(replaced.watermarks,{});
  assert.ok(fs.existsSync(file));
  await page.waitForFunction(()=>document.querySelector('#console-body')?.textContent.includes('已被新任务替代'));
  await page.locator('#console-body').screenshot({path:path.join(output,'new-task-replaces-old.png'),scale:'css'});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',packaged:!!executablePath,simulateBatches,realDownloads:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
