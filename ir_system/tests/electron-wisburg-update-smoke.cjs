// Isolated profile, real settings validation, intercepted approval: no downloads.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SyncStore}=require('../src/main/sync/store');
const {CATEGORIES,makePlan}=require('../src/main/sync/policy');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.mkdtempSync(path.join(os.tmpdir(),'ir-wisburg-dropdown-')),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const store=new SyncStore(profile),unrelated={provider:'ima',collectionId:'fixture',name:'untouched',mode:'off',firstDate:'2026-01-01'};
 store.state.settings.policies=[unrelated,...CATEGORIES.map(collectionId=>({provider:'wisburg',collectionId,name:collectionId,mode:'incremental',firstDate:'2026-01-01'}))];store.save();
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:'__offline_fixture__'}});
 try{
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await app.evaluate(({ipcMain})=>{globalThis.wisburgApprovals=[];ipcMain.removeHandler('sync:approve');ipcMain.handle('sync:approve',(_,kind,resume,selection)=>{globalThis.wisburgApprovals.push({kind,selection});return {status:'cancelled'};});});
  const state=()=>page.evaluate(()=>window.irSystem.syncGetState());
  const close=()=>page.locator('[data-dialog-close]').click();
  const openSelection=async()=>{await page.locator('#source-rows [data-source-select="wisburg"]').click();await page.locator('#wisburg-selection').waitFor();};
  const save=async()=>{await page.locator('#wisburg-selection button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);};
  const reload=async()=>{await page.reload();await page.locator('[data-module="data"]').first().click();await page.locator('[data-source-select="wisburg"]').waitFor();};
  await page.locator('[data-module="data"]').first().click();
  assert.match(await page.locator('[data-source-select="wisburg"]').innerText(),/已选 9 个栏目/);
  const before=await state();
  await openSelection();assert.equal(await page.locator('[name="category"]:checked').count(),9);
  assert.equal(await page.locator('#wisburg-selection [name="start"], #wisburg-selection [name="end"]').count(),0);
  for(const label of ['投行研报','公司研究','资管报告','央行·政府·智库','财报电话会','投研资讯流','市场日报','智堡研究','Mikko 市场短评'])assert.ok((await page.locator('#wisburg-selection').innerText()).includes(label));
  await page.locator('[data-wisburg-select="none"]').click();await close();assert.deepEqual((await state()).settings,before.settings);
  await openSelection();await page.locator('[data-wisburg-select="none"]').click();
  for(const id of ['archive','article'])await page.locator('[name="category"][value="'+id+'"]').check();
  await save();let saved=await state();assert.deepEqual(saved.settings.policies.find(p=>p.provider==='ima'),unrelated);
  assert.equal((await app.evaluate(()=>globalThis.wisburgApprovals)).length,0);
  await reload();assert.match(await page.locator('[data-source-select="wisburg"]').innerText(),/已选 2 个栏目/);
  const revision=(await state()).revision;
  for(const kind of ['backfill','incremental']){
   await page.locator('[data-source-update="wisburg"][data-kind="'+kind+'"]').click();await page.locator('#source-update').waitFor();
   assert.equal(await page.locator('[name="category"]').count(),0);
   assert.match(await page.locator('#source-update').innerText(),/2 个已勾选子信源/);
   if(kind==='backfill'){await page.locator('#source-update [name="start"]').fill('260920');await page.locator('#source-update [name="end"]').fill('260926');}
   else assert.equal(await page.locator('#source-update [name="start"]').inputValue(),await page.evaluate(()=>IRDates.compact(IRDates.today())));
   await page.locator('#source-update button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#source-dialog').open);
  }
  let calls=await app.evaluate(()=>globalThis.wisburgApprovals);
  assert.equal(calls.length,2);assert.deepEqual(calls[0].selection.collectionIds,['archive','article']);assert.deepEqual(calls[1].selection.collectionIds,['archive','article']);
  assert.equal((await state()).revision,revision);
  assert.equal(makePlan((await state()).settings,{},'backfill',archive,'2026-09-27',calls[0].selection).collections.length,2);
  await openSelection();await page.locator('[data-wisburg-select="none"]').click();await save();
  await page.locator('[data-bulk-source="wisburg"]').check();await page.locator('[data-bulk-action="backfill"]').click();
  await page.locator('#source-dialog [data-source-select="wisburg"]').click();await page.locator('#wisburg-selection').waitFor();
  assert.equal(await page.locator('[name="category"]:checked').count(),0);
  await page.locator('[data-wisburg-select="all"]').click();await save();
  await page.locator('[data-bulk-action="incremental"]').click();assert.match(await page.locator('#bulk-update').innerText(),/9 个已勾选/);await close();
  await openSelection();await page.evaluate(async()=>{const s=await window.irSystem.syncGetState();await window.irSystem.syncSaveSettings(s.settings);});
  await page.locator('#wisburg-selection button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#dialog-message').textContent.includes('设置已发生变化'));await close();
  assert.equal((await app.evaluate(()=>globalThis.wisburgApprovals)).length,2);
  assert.equal((await state()).jobs.length,0);assert.deepEqual(errors,[]);
  await openSelection();const screenshot=path.join(profile,'wisburg-dropdown.png');await page.locator('#source-dialog').screenshot({path:screenshot});
  console.log(JSON.stringify({status:'passed',packaged:!!executablePath,sourceCalls:0,downloads:0,modelCalls:0,profile,screenshot}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
