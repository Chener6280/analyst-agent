// Isolated profile; real local health check and UI, no subscription/source calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{signature}=require('../src/main/sync/subscriptions');
(async()=>{
 const appRoot=path.resolve(__dirname,'..');
 const python=process.env.IR_SYSTEM_TEST_PYTHON||path.join(appRoot,'.runtime/venv/bin/python');
 const sdk=process.env.IR_SYSTEM_TEST_SDK;
 if(!sdk||!fs.existsSync(python))throw new Error('Set IR_SYSTEM_TEST_SDK and provide the local test Python runtime');
 const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-issue-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString();
 const rows=Array.from({length:4},(_,i)=>({collectionId:'fixture_'+i,name:i?'待处理测试库 '+i:'可更新测试库',directoryAccess:'accessible',present:true,accessCode:null}));
 s.catalog={sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:rows}]};
 s.settings.policies=rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:'incremental',firstDate:'2026-01-01'}));
 s.imaAccess=Object.fromEntries(rows.map((r,i)=>[r.collectionId,{status:i?'sample_denied':'api_sample_ok',code:i?'entitlement_denied':'sample_read_ok',checkedAt:stamp,fingerprint:signature(r),configuration:JSON.stringify([archive,python,sdk])}]));s.jobs=rows.slice(1).map((r,i)=>({id:'unfinished-'+i,kind:'sync',status:'needs_attention',createdAt:stamp,counts:{},root:archive,plan:{collections:[s.settings.policies[i+1]]}}));store.save();
 const output=path.join(appRoot,'.local/source-center-v10-acceptance');fs.mkdirSync(output,{recursive:true});
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[appRoot],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:python,IR_SYSTEM_IR_SEARCH_PATH:sdk}});
 try{
  await app.evaluate(({dialog})=>{globalThis.__dialogs=[];dialog.showMessageBox=async(_w,o)=>{globalThis.__dialogs.push(o);return {response:0};};});
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();await page.locator('[data-source-readiness="ima"]').click();
  await page.locator('[data-attention-code="unresolved_job"]').first().waitFor();
  await page.evaluate(()=>window.irSystem.syncCheckLocal());
  await page.locator('[data-attention-code="unresolved_job"] input:not(:disabled)').first().waitFor();
  await page.waitForTimeout(100);
  assert.equal(await page.locator('[data-attention-code="unresolved_job"] input:checked').count(),3);
  const current=await page.evaluate(()=>window.irSystem.syncGetState());
  assert.equal(current.readiness.ima.issues.length,3,JSON.stringify(current.readiness.ima.issues));
  await page.locator('#source-dialog').screenshot({path:path.join(output,'before.png'),scale:'css'});
  for(let i=1;i<=3;i++){
    await page.locator('[data-attention-code="unresolved_job"] input').first().click();
    await page.getByRole('checkbox',{name:'恢复 待处理测试库 '+i,exact:true}).waitFor();
  }
  await page.locator('[data-readiness-tone="ready"]').waitFor();
  assert.equal(await page.locator('.dc-excluded-item input:not(:checked)').count(),3);
  assert.match(await page.locator('.dc-callout').innerText(),/环境已就绪/);
  assert.match(await page.locator('.dc-callout').innerText(),/已排除 3 个/);
  await page.locator('#source-dialog').screenshot({path:path.join(output,'excluded-green.png'),scale:'css'});
  await page.locator('[data-dialog-close]').click();
  await page.locator('[data-source-row="ima"] [data-source-select]').click();assert.equal(await page.locator('#source-draft-rows .dc-choice-state').first().innerText(),'✓');
  assert.equal((await page.locator('#source-draft-rows .dc-choice-state').allTextContents()).filter(s=>s==='×').length,3);
  await page.locator('[data-dialog-close]').click();
  for(const kind of ['backfill','incremental']){
   await page.locator(`[data-source-update="ima"][data-kind="${kind}"]`).click();
   await page.getByRole('button',{name:'确认范围并继续',exact:true}).click();await page.locator('#source-dialog').waitFor({state:'hidden'});
   const d=(await app.evaluate(()=>globalThis.__dialogs)).at(-1);assert.match(d.detail,/共 1 个已选集合/);assert.match(d.detail,/可更新测试库/);assert.doesNotMatch(d.detail,/待处理测试库/);
  }
  await page.locator('[data-source-readiness="ima"]').click();await page.locator('[data-readiness-tone="ready"]').waitFor();await page.waitForTimeout(100);
  await page.getByRole('checkbox',{name:'恢复 待处理测试库 2',exact:true}).click();
  await page.locator('[data-attention-code="unresolved_job"]').waitFor();
  assert.equal((await page.evaluate(()=>window.irSystem.syncGetState())).readiness.ima.tone,'attention');
  const final=await page.evaluate(()=>window.irSystem.syncGetState());assert.equal(final.jobs.length,3);assert.deepEqual(final.watermarks,{});assert.equal(final.settings.policies.filter(p=>p.mode==='off').length,2);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',packaged:!!executablePath,sourceCalls:0,modelCalls:0,scopeExclusionVerified:true,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
