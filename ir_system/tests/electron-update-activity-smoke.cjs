// Synthetic job transitions only, isolated application profile, no downloads.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {_electron:electron}=require('playwright-core');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.mkdtempSync(path.join(os.tmpdir(),'ir-update-activity-')),archive=path.join(profile,'archive');fs.mkdirSync(archive);
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_ARCHIVE_ROOT:archive,IR_SYSTEM_PYTHON:'__offline_no_python__'}});
 try{
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const baseline=await page.evaluate(()=>window.irSystem.syncGetState());
  await app.evaluate(({ipcMain},state)=>{globalThis.testActivityState=state;ipcMain.removeHandler('sync:state');ipcMain.handle('sync:state',()=>globalThis.testActivityState);},baseline);
  await page.locator('[data-module="data"]').first().click();
  const button=(provider,kind)=>page.locator(`[data-source-update="${provider}"][data-kind="${kind}"]`);
  const set=async(provider,kind,stage,status='running',code=null)=>{
   await app.evaluate((_,j)=>{globalThis.testActivityState.busy=j.status==='running';globalThis.testActivityState.replaceableProviders=j.status==='running'&&j.kind!=='scan'?[j.collections[0].provider]:[];globalThis.testActivityState.jobs=[j];},{id:'00000000-0000-4000-8000-000000000001',createdAt:new Date().toISOString(),collections:[{provider}],kind,stage,status,code,counts:{downloaded:12}});
  };
  await set('ima','backfill','downloading');await button('ima','backfill').filter({hasText:'下载中'}).waitFor();
  assert.equal(await button('ima','backfill').getAttribute('aria-busy'),'true');assert.equal(await button('ima','backfill').isDisabled(),false);
  assert.equal(await button('zsxq','backfill').isDisabled(),true);
  assert.equal(await page.locator('.dc-update-spinner').count(),1);assert.equal(await button('ima','incremental').getAttribute('aria-busy'),'false');
  assert.match(await page.locator('.dc-update-progress').innerText(),/已下载 12 份/);
  const opacity=await button('ima','backfill').evaluate(el=>getComputedStyle(el).opacity);assert.equal(opacity,'1');
  const output=path.join(root,'.local/update-activity-acceptance');fs.mkdirSync(output,{recursive:true});
  await page.locator('.dc-sources').screenshot({path:path.join(output,'history-downloading.png'),scale:'css'});
  await set('ima','backfill','scanning');await button('ima','backfill').filter({hasText:'扫描中'}).waitFor();
  await set('ima','backfill','parsing');await button('ima','backfill').filter({hasText:'解析中'}).waitFor();
  await set('zsxq','incremental','web_downloading');await button('zsxq','incremental').filter({hasText:'下载中'}).waitFor();
  assert.equal(await button('ima','backfill').getAttribute('aria-busy'),'false');assert.equal(await page.locator('.dc-update-spinner').count(),1);
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.dc-update-spinner').evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await set('zsxq','incremental','cooldown','running','rate_limit');await button('zsxq','incremental').filter({hasText:'等待处理'}).waitFor();assert.equal(await page.locator('.dc-update-spinner').count(),0);
  for(const status of ['budget_paused','needs_attention','failed','completed']){
   await set('zsxq','incremental','downloading',status);await page.waitForFunction(()=>document.querySelectorAll('.dc-update-running,.dc-update-waiting').length===0);
   assert.equal(await button('zsxq','incremental').getAttribute('aria-busy'),'false');
  }
  await set('ima','scan','scanning');await page.waitForTimeout(2800);assert.equal(await page.locator('.dc-update-spinner').count(),0);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',packaged:!!executablePath,sourceCalls:0,modelCalls:0,profile}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1);});
