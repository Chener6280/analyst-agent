// Synthetic subscription/job; real packaged local checks under Finder's PATH.
// Never scans sources or authorizes downloads; confirmation dialogs cancel.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store');
(async()=>{
 const appRoot=path.resolve(__dirname,'..'),sdk=process.env.IR_SYSTEM_TEST_SDK;
 if(!sdk)throw new Error('IR_SYSTEM_TEST_SDK required');
 const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-scan-recovery-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString(),old=new Date(Date.now()-60000).toISOString();
 const row={provider:'zsxq',collectionId:'123',name:'启动恢复验收星球（模拟）',mode:'incremental',firstDate:'2026-01-01'};
 s.settings.policies=[row];s.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:stamp,collections:[{collectionId:'123',name:row.name,present:true,membership:{active:true},permissions:{allow_download:true},skill_api:'accessible'}]}]};
 s.jobs=[{id:'00000000-0000-4000-8000-000000000001',kind:'sync',root:archive,status:'needs_attention',code:'zsxq_cli_failed',stage:'scanning',attempt:1,counts:{},createdAt:old,finishedAt:old,plan:{kind:'backfill',collections:[row]}}];store.save();
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[appRoot],env:{...process.env,PATH:'/usr/bin:/bin:/usr/sbin:/sbin',IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:path.join(appRoot,'.runtime/venv/bin/python'),IR_SYSTEM_IR_SEARCH_PATH:sdk}});
 try{
  await app.evaluate(({dialog})=>{globalThis.confirmations=[];dialog.showMessageBox=async(_w,o)=>{globalThis.confirmations.push(o.message);return {response:0};};});
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();
  const before=await page.evaluate(()=>window.irSystem.syncGetState());assert.notEqual(before.readiness.zsxq.tone,'ready');
  await page.locator('[data-source-readiness="zsxq"]').click();await page.locator('[data-readiness-provider="zsxq"][data-readiness-tone="ready"]').waitFor();
  const after=await page.evaluate(()=>window.irSystem.syncGetState());assert.equal(after.jobs.length,1);assert.equal(after.jobs[0].status,'needs_attention');assert.equal(after.jobs[0].recoveredBeforeDownload,true);assert.deepEqual(after.watermarks,{});
  const output=path.join(appRoot,'.local/cli-runtime-recovery-acceptance');fs.mkdirSync(output,{recursive:true});
  await page.locator('#source-dialog').screenshot({path:path.join(output,'recovered-ready-fixture.png'),scale:'css'});
  await page.locator('[data-dialog-close]').click();
  assert.match(await page.locator('#console-body').innerText(),/启动故障已恢复/);
  await page.locator('.dc-log-job').screenshot({path:path.join(output,'recovered-job-fixture.png'),scale:'css'});
  for(const kind of ['backfill','incremental']){
   await page.locator(`[data-source-update="zsxq"][data-kind="${kind}"]`).click();
   await page.getByRole('button',{name:'确认范围并继续',exact:true}).click();await page.locator('#source-dialog').waitFor({state:'hidden'});
  }
  assert.equal((await app.evaluate(()=>globalThis.confirmations)).length,2);
  assert.equal((await page.evaluate(()=>window.irSystem.syncGetState())).jobs.length,1);assert.deepEqual(fs.readdirSync(archive),[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',packaged:!!executablePath,modelCalls:0,sourceCalls:0,downloads:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
