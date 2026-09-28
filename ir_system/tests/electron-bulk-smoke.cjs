// Offline UI acceptance: no source calls, no downloads, no paid model calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.mkdtempSync(path.join(os.tmpdir(),'ir-bulk-ui-')),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:'__offline_fixture__'}});
 try{
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const state=await page.evaluate(()=>window.irSystem.syncGetState());
  state.settings.policies=['ima','zsxq'].map(provider=>({provider,collectionId:'123',name:provider+' fixture',mode:'incremental',firstDate:'2026-01-01'}));
  await app.evaluate(({ipcMain},s)=>{
   globalThis.bulkState=s;globalThis.bulkCalls=[];globalThis.audioActivity=[];
   const handler=(name,fn)=>{ipcMain.removeHandler(name);ipcMain.handle(name,fn);};
   handler('sync:state',()=>globalThis.bulkState);
   handler('archive:request',()=>({status:'ok',activity:globalThis.audioActivity}));
   handler('sync:scan',(_,providers)=>{globalThis.bulkCalls.push({scan:providers});s.jobs.unshift({id:'scan-fixture',kind:'scan',providers,status:'completed',counts:{}});return {status:'completed',jobId:'scan-fixture'};});
   handler('sync:check-local',()=>{globalThis.bulkCalls.push({check:true});return {status:'ready'};});
   handler('sync:preflight-prompt',(_,id)=>id+' repair only');
   handler('sync:prompt',(_,id,kind,range)=>{globalThis.bulkCalls.push({prompt:id,kind,range});return {prompts:{nonAudio:id+' nonAudio',audio:id+' audio'}};});
   handler('sync:approve',(_,kind,resume,selection)=>{globalThis.bulkCalls.push({kind,selection});return {status:'authorized'};});
  },state);
  await page.locator('[data-module="data"]').first().click();
  assert.equal(await page.locator('.dc-heading').count(),0);
  assert.doesNotMatch(await page.locator('#dc-bulk-actions').innerText(),/一次确认|共用归档|不并发/);
  assert.equal(await page.locator('[data-bulk-source]').count(),13);
  assert.equal(await page.locator('#world-clocks time').count(),4);
  assert.equal(await page.locator('#connection-status').count(),0);
  for(const id of ['ima','zsxq'])await page.locator(`[data-bulk-source="${id}"]`).check();
  await page.locator('[data-bulk-action="verify"]').click();
  try{await page.locator('[data-bulk-repair]').waitFor({timeout:8000});}catch(e){console.log(await page.locator('#sync-message').innerText(),await app.evaluate(()=>globalThis.bulkCalls),errors);throw e;}await page.locator('[data-bulk-repair]').click();
  await page.waitForFunction(()=>document.querySelector('#bulk-repair-text')?.value.includes('zsxq repair'));
  assert.match(await page.locator('#bulk-repair-text').inputValue(),/ima repair/);
  await page.locator('[data-dialog-close]').click();
  await page.locator('[data-bulk-action="incremental"]').click();
  assert.match(await page.locator('#bulk-update').innerText(),/2 个已勾选/);
  await page.locator('#bulk-update button[type="submit"]').click();
  await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  const submitted=(await app.evaluate(()=>globalThis.bulkCalls)).find(c=>c.selection);
  assert.deepEqual(submitted.selection.providers,['ima','zsxq']);assert.equal(submitted.selection.start,submitted.selection.end);
  await page.locator('[data-bulk-action="llm"]').click();await page.locator('#llm-prompt-options button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#llm-prompt-nonAudio')?.value.includes('zsxq nonAudio'));
  assert.match(await page.locator('#llm-prompt-nonAudio').inputValue(),/ima nonAudio/);
  await page.locator('[data-prompt-tab="audio"]').click();assert.match(await page.locator('#llm-prompt-audio').inputValue(),/zsxq audio/);
  await page.locator('[data-dialog-close]').click();
  assert.equal(await page.locator('[data-source-llm="ima"]').getAttribute('aria-busy'),'false');
  await app.evaluate(()=>{globalThis.audioActivity=[{source:'ima',title:'fixture.mp3',completed_seconds:60,duration_seconds:120}];});
  await page.locator('[data-source-llm="ima"]').filter({hasText:'转写中'}).waitFor();
  assert.match(await page.locator('#dc-audio-activity').innerText(),/60 \/ 120 秒/);
  const output=path.join(root,'.local/bulk-ui.png');await page.screenshot({path:output});
  await app.evaluate(()=>{globalThis.audioActivity=[];});
  await page.waitForFunction(()=>document.querySelector('[data-source-llm="ima"]').getAttribute('aria-busy')==='false');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',packaged:!!executablePath,realDownloads:0,modelCalls:0,screenshot:output}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
