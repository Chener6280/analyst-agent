const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{makePlan}=require('../src/main/sync/policy');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-headless-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString(),id='00000000-0000-4000-8000-000000000001';
 s.settings.policies=[{provider:'zsxq',collectionId:'123',name:'模拟网页星球',mode:'incremental',firstDate:'2026-01-01'}];
 s.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:stamp,collections:[{collectionId:'123',name:'模拟网页星球',present:true,membership:{active:true},permissions:{allow_download:true},skill_api:'not_enabled'}]}]};
 const selection={provider:'zsxq',start:'2026-09-20',end:'2026-09-26'};
 s.jobs=[{id,kind:'sync',root:archive,status:'interrupted',code:'headless_browser_failed',stage:'web_downloading',attempt:1,counts:{downloaded:2},createdAt:stamp,finishedAt:stamp,selection,plan:makePlan(s.settings,{},'backfill',archive,undefined,selection)}];store.save();
 const checkpoint=path.join(store.jobDirectory(id),'checkpoint.json');fs.mkdirSync(path.dirname(checkpoint),{recursive:true});fs.writeFileSync(checkpoint,'{"fixture":true}');
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:path.join(root,'.runtime/venv/bin/python'),IR_SYSTEM_IR_SEARCH_PATH:'/Users/chen/Documents/ir_search'}});
 try{
  await app.evaluate(({app,dialog})=>{
   globalThis.dialogs=[];globalThis.accept=false;globalThis.requests=[];
   dialog.showMessageBox=async(_w,o)=>{globalThis.dialogs.push(o);return {response:globalThis.accept?1:0};};
   const load=process.getBuiltinModule('module').createRequire(app.getAppPath()+'/package.json'),{SyncManager}=load('./src/main/sync/manager'),launch=SyncManager.prototype.launch;
   SyncManager.prototype.launch=function(job,request){this.runner=r=>{globalThis.requests.push(r);return {promise:Promise.resolve({status:'completed',counts:{}}),stop(){}};};return launch.call(this,job,request);};
  });
  const page=await app.firstWindow();await page.locator('[data-module="data"]').first().click();
  await page.locator('[data-sync-resume-visible]').click();
  await page.waitForFunction(()=>document.querySelector('#sync-message').textContent.includes('已取消'));
  let state=await page.evaluate(()=>window.irSystem.syncGetState());assert.equal(state.jobs[0].selection.browserMode,undefined);
  assert.match((await app.evaluate(()=>globalThis.dialogs)).at(-1).detail,/本次明确使用可见浏览器续传/);
  await app.evaluate(()=>{globalThis.accept=true;});await page.locator('[data-sync-resume-visible]').click();
  const deadline=Date.now()+10000;do{state=await page.evaluate(()=>window.irSystem.syncGetState());if(state.jobs[0].status==='completed')break;await page.waitForTimeout(100);}while(Date.now()<deadline);
  assert.equal(state.jobs[0].status,'completed');assert.equal(state.jobs[0].id,id);
  const req=(await app.evaluate(()=>globalThis.requests))[0];assert.equal(req.browserMode,'visible');assert.equal(req.plan.kind,'backfill');assert.equal(req.plan.collections[0].start,selection.start);assert.equal(req.jobDirectory,path.dirname(checkpoint));assert.equal(fs.readFileSync(checkpoint,'utf8'),'{"fixture":true}');
  await app.evaluate(()=>{globalThis.accept=false;});await page.locator('[data-source-update="zsxq"][data-kind="backfill"]').click();await page.getByRole('button',{name:'确认范围并继续',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  assert.match((await app.evaluate(()=>globalThis.dialogs)).at(-1).detail,/网页下载默认后台无头运行/);
  console.log(JSON.stringify({status:'passed',packaged:!!executablePath,realDownloads:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
