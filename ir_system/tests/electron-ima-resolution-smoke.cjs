// Isolated application profile; dialogs cancel all network activity.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store'),{signature}=require('../src/main/sync/subscriptions');
(async()=>{
 const root=path.resolve(__dirname,'..'),sdk=process.env.IR_SYSTEM_TEST_SDK;
 const python=process.env.IR_SYSTEM_TEST_PYTHON||path.join(root,'.runtime/venv/bin/python');
 if(!sdk)throw new Error('IR_SYSTEM_TEST_SDK required');
 const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-resolution-ui-'))),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),s=store.state,stamp=new Date().toISOString(),configuration=JSON.stringify([archive,python,sdk]);
 const names=['有效通过库','断点续查库','接口拒绝库','本轮未检查库','已排除库'];
 const rows=names.map((name,i)=>({collectionId:'fixture'+i,name,directoryAccess:'accessible',accessCode:null,present:true}));
 s.catalog={sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:rows}]};
 s.settings.policies=rows.map((r,i)=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:i===4?'off':'incremental',firstDate:'2026-01-01'}));
 s.imaAccess=Object.fromEntries(rows.map((r,i)=>[r.collectionId,{status:i===0?'api_sample_ok':i===2?'sample_denied':'unverified',
  code:['sample_read_ok','sample_not_found_in_budget','entitlement_denied','not_tested','not_tested'][i],checkedAt:i===3?null:stamp,observedAt:stamp,configuration,fingerprint:signature(r),
  ...(i===2?{sampleRef:'ima://media/example',sampleTitle:'测试文件 <script>window.bad=1</script>.pdf',diagnostic:{phase:'sample_read',operation:'get_media_info',httpStatus:200,providerCode:210011,code:'entitlement_denied',observedAt:stamp}}:{})}]));
 s.imaProbeSearch={fixture1:{configuration,fingerprint:signature(rows[1]),checkpoint:{version:1,queue:[[null,'page4']],visited:['a'.repeat(64)],sample:null,pagesTotal:3,skippedTotal:20}}};
 s.downloadEvidence={
  'ima:fixture1':{status:'client_downloaded',checkedAt:stamp,configuration,fingerprint:signature(rows[1]),sampleTitle:'allowed.pdf',bytes:100,sha256:'a'.repeat(64)},
  'ima:fixture2':{status:'client_blocked',checkedAt:stamp,configuration,fingerprint:signature(rows[2]),sampleTitle:'restricted.pdf'}
 };store.save();
 const output=path.join(root,'.local/source-center-v10-acceptance');fs.mkdirSync(output,{recursive:true});
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:python,IR_SYSTEM_IR_SEARCH_PATH:sdk}});
 try{
  await app.evaluate(({dialog})=>{globalThis.__dialogs=[];dialog.showMessageBox=async(_w,o)=>{globalThis.__dialogs.push(o);return {response:0};};});
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();await page.locator('[data-source-readiness="ima"]').click();
  await page.evaluate(()=>window.irSystem.syncCheckLocal());
  await page.locator('[data-readiness-tone="ready"]').waitFor();assert.equal(await page.locator('[data-probe-ima]').count(),0);
  await page.locator('[data-dialog-close]').click();await page.locator('#source-rows [data-source-select="ima"]').click();
  assert.equal(await page.locator('.dc-capability-checks, [data-probe-ima]').count(),0);
  assert.doesNotMatch(await page.locator('#source-dialog').innerText(),/单库 API 样本核验与诊断/);
  assert.equal(await page.locator('.dc-download-available').count(),2);
  assert.match(await page.locator('.dc-download-unavailable').innerText(),/不可下载（已测样本）/);
  const row=name=>page.locator('#source-draft-rows tr').filter({hasText:name});
  assert.equal(await row('接口拒绝库').locator('.dc-choice-state').innerText(),'×');
  assert.match(await row('接口拒绝库').innerText(),/默认打叉/);
  assert.equal(await row('本轮未检查库').locator('.dc-choice-state').innerText(),'✓');
  // Unsaved selections survive viewing diagnostics and cancelling a network prompt.
  await row('断点续查库').locator('[data-value="off"]').click();
  await row('断点续查库').locator('details > summary').click();
  assert.match(await row('断点续查库').innerText(),/Computer Use/);
  await page.locator('#source-dialog').screenshot({path:path.join(output,'ima-download-methods.png'),scale:'css'});
  await page.locator('[data-ima-evidence="fixture1"]').click();
  assert.match(await page.locator('.dc-ima-evidence').innerText(),/累计查 3 页/);
  assert.equal(await page.locator('[data-probe-ima-library="fixture1"]:not([data-probe-restart])').innerText(),'继续找样本');
  await page.locator('[data-probe-ima-library="fixture1"]:not([data-probe-restart])').click();
  await page.waitForFunction(()=>document.querySelector('#dialog-message')?.textContent.includes('已取消'));
  let d=(await app.evaluate(()=>globalThis.__dialogs)).at(-1);
  assert.match(d.detail,/以下 1 个库/);assert.match(d.detail,/断点续查库/);assert.doesNotMatch(d.detail,/接口拒绝库/);
  await page.locator('[data-evidence-back]').click();
  assert.equal(await row('断点续查库').locator('.dc-choice-state').innerText(),'×');
  await row('本轮未检查库').locator('details > summary').click();await page.locator('[data-ima-evidence="fixture3"]').click();
  assert.match(await page.locator('.dc-ima-evidence').innerText(),/本轮未检查/);
  await page.locator('[data-evidence-back]').click();
  await row('接口拒绝库').locator('details > summary').click();await page.locator('[data-ima-evidence="fixture2"]').click();
  assert.match(await page.locator('.dc-ima-evidence').innerText(),/210011/);
  assert.match(await page.locator('.dc-ima-evidence').innerText(),/测试文件 <script>/);assert.equal(await page.evaluate(()=>window.bad),undefined);
  assert.match(await page.locator('.dc-ima-evidence').innerText(),/同一个样本/);
  await page.locator('#source-dialog').screenshot({path:path.join(output,'ima-sample-diagnostic.png'),scale:'css'});
  await page.locator('[data-probe-restart]').click();
  d=(await app.evaluate(()=>globalThis.__dialogs)).at(-1);assert.match(d.message,/从头/);assert.match(d.detail,/接口拒绝库/);assert.match(d.detail,/其他库不受影响/);
  await page.locator('[data-evidence-back]').click();assert.equal(await row('接口拒绝库').locator('.dc-choice-state').innerText(),'×');
  const state=await page.evaluate(()=>window.irSystem.syncGetState());assert.equal(state.jobs.length,0);assert.deepEqual(state.watermarks,{});
  assert.equal(state.imaAccess.fixture1.search.pagesTotal,3);assert.equal(state.imaAccess.fixture0.status,'api_sample_ok');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',packaged:!!executablePath,sourceCalls:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
