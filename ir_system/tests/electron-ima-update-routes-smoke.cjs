// Isolated profile. Real downloader is replaced before authorizing any execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{signature}=require('../src/main/sync/subscriptions');
(async()=>{
 const root=path.resolve(__dirname,'..'),sdk='/Users/chen/Documents/ir_search',python=path.join(root,'.runtime/venv/bin/python');
 const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-routes-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString(),configuration=JSON.stringify([archive,python,sdk]);
 const rows=['API 已就绪库','客户端库一','客户端库二','待核验库一','待核验库二'].map((name,i)=>({collectionId:'fixture'+i,name,directoryAccess:'accessible',present:true}));
 s.catalog={sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:rows}]};
 s.settings.policies=rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:'incremental',firstDate:'2026-01-01'}));
 s.imaAccess={fixture0:{status:'api_sample_ok',code:'sample_read_ok',checkedAt:stamp,configuration,fingerprint:signature(rows[0])}};
 s.downloadEvidence=Object.fromEntries([1,2].map(i=>['ima:fixture'+i,{status:'client_downloaded',checkedAt:stamp,configuration,fingerprint:signature(rows[i])}]));store.save();
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:python,IR_SYSTEM_IR_SEARCH_PATH:sdk}});
 try{
  await app.evaluate(({app,dialog})=>{
   globalThis.__dialogs=[];globalThis.__accept=false;globalThis.__requests=[];
   dialog.showMessageBox=async(_w,o)=>{globalThis.__dialogs.push(o);return {response:globalThis.__accept?1:0};};
   const req=process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json');
   const {SyncManager}=req('./src/main/sync/manager'),launch=SyncManager.prototype.launch;
   // This fixture deliberately exercises machines without the native helper.
   SyncManager.prototype.imaClientAvailable=()=>false;
   SyncManager.prototype.launch=function(job,request){this.runner=(r)=>{globalThis.__requests.push(r);return {promise:Promise.resolve({status:'completed',counts:{}}),stop(){}};};return launch.call(this,job,request);};
  });
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();
  await page.locator('[data-source-update="ima"][data-kind="backfill"]').click();
  assert.equal(await page.locator('[data-update-route]').count(),5);
  assert.equal(await page.locator('[data-update-probe]').count(),2);
  assert.match(await page.locator('#ima-update-routes').innerText(),/1 \/ 5 个库已就绪/);
  assert.equal(await page.locator('[data-ready-only]').innerText(),'本次只更新已就绪的 1 个库');
  await page.locator('[data-update-probe="fixture3"]').click();
  await page.waitForFunction(()=>document.querySelector('#dialog-message')?.textContent.includes('已取消核验'));
  assert.match((await app.evaluate(()=>globalThis.__dialogs)).at(-1).detail,/待核验库一/);
  await page.locator('[data-ready-only]').click();
  await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  const confirmation=(await app.evaluate(()=>globalThis.__dialogs)).at(-1);
  assert.match(confirmation.detail,/共 1 个已选集合/);assert.match(confirmation.detail,/本次暂不更新以下 4 个已勾选库/);
  let state=await page.evaluate(()=>window.irSystem.syncGetState());assert.equal(state.jobs.length,0);
  await page.locator('[data-source-update="ima"][data-kind="incremental"]').click();
  await app.evaluate(()=>{globalThis.__accept=true;});
  await page.locator('[data-ready-only]').click();
  await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  const deadline=Date.now()+10000;do{state=await page.evaluate(()=>window.irSystem.syncGetState());if(state.jobs[0]?.status==='completed')break;await page.waitForTimeout(100);}while(Date.now()<deadline);
  assert.equal(state.jobs[0]?.status,'completed');assert.equal(state.jobs[0].collectionCount,1);
  assert.equal(state.settings.policies.filter(p=>p.mode==='incremental').length,5);
  const requests=await app.evaluate(()=>globalThis.__requests);assert.equal(requests.length,1);assert.deepEqual(requests[0].plan.collections.map(r=>r.collectionId),['fixture0']);
  assert.deepEqual(Object.keys(state.watermarks),['ima:fixture0']);assert.deepEqual(errors,[]);
  await page.locator('[data-source-update="ima"][data-kind="backfill"]').click();
  await page.locator('#source-dialog').screenshot({path:path.join(profile,'ima-update-routes.png')});
  console.log(JSON.stringify({status:'passed',packaged:!!executablePath,realDownloads:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
