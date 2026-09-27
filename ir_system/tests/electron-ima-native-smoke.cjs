// Isolated UI profile: verify button-to-worker routing, never download live data.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{signature}=require('../src/main/sync/subscriptions');
(async()=>{
 const root=path.resolve(__dirname,'..'),sdk='/Users/chen/Documents/ir_search',python=path.join(root,'.runtime/venv/bin/python');
 const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-native-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString(),configuration=JSON.stringify([archive,python,sdk]);
 const rows=['API 已就绪库','客户端库','执行时核验库'].map((name,i)=>({collectionId:'fixture'+i,name,present:true}));
 s.catalog={sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:rows}]};
 s.settings.policies=rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:'incremental',firstDate:'2026-01-01'}));
 s.imaAccess={fixture0:{status:'api_sample_ok',code:'sample_read_ok',checkedAt:stamp,configuration,fingerprint:signature(rows[0])}};
 s.downloadEvidence={'ima:fixture1':{status:'client_downloaded',checkedAt:stamp,configuration,fingerprint:signature(rows[1])}};store.save();
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:python,IR_SYSTEM_IR_SEARCH_PATH:sdk}});
 try{
  await app.evaluate(({app,dialog})=>{
   globalThis.__requests=[];globalThis.__dialogs=[];
   dialog.showMessageBox=async(_w,o)=>{globalThis.__dialogs.push(o);return {response:1};};
   const req=process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json');
   const {SyncManager}=req('./src/main/sync/manager'),launch=SyncManager.prototype.launch;
   SyncManager.prototype.launch=function(job,request){
    this.runner=r=>{globalThis.__requests.push(r);return {promise:Promise.resolve({status:'completed',counts:{}}),stop(){}};};
    return launch.call(this,job,request);
   };
  });
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();
  await page.locator('[data-source-update="ima"][data-kind="incremental"]').click();
  assert.match(await page.locator('#ima-update-routes').innerText(),/3 \/ 3 个库已就绪/);
  assert.match(await page.locator('#ima-update-routes').innerText(),/官方客户端/);
  await page.locator('#source-update button[type="submit"]').click();
  await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  const requests=await app.evaluate(()=>globalThis.__requests);
  assert.equal(requests.length,1);assert.equal(requests[0].imaClientEnabled,true);
  assert.deepEqual(requests[0].imaClientCollections,['fixture1','fixture2']);
  assert.equal(requests[0].plan.collections.length,3);
  assert.ok(requests[0].plan.collections.every(r=>r.start===r.end));
  assert.match((await app.evaluate(()=>globalThis.__dialogs)).at(-1).detail,/辅助功能/);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',packaged:!!executablePath,realDownloads:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
