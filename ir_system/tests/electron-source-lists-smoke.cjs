const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {_electron:electron}=require('playwright-core');
const {SourceLists}=require('../adapters/source_lists/store');
(async()=>{
 const root=path.resolve(__dirname,'..'),profile=fs.mkdtempSync(path.join(os.tmpdir(),'ir-source-lists-ui-')),store=new SourceLists(profile);
 store.change('wechat',0,()=>[{name:'示例公众号',ghid:'gh_fixture'},{name:'<安全测试>'}]);
 const executablePath=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 const app=await electron.launch({...(executablePath?{executablePath}:{}),args:executablePath?[]:[root],env:{...process.env,IR_SYSTEM_USER_DATA_DIR:profile,IR_SYSTEM_PROVIDER:'ir_search',IR_SYSTEM_PYTHON:'__offline_fixture__'}});
 try{
  const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.locator('[data-module="data"]').first().click();
  await page.locator('[data-local-list="wechat"]').waitFor();
  assert.equal(await page.locator('[data-source-row]').count(),12);
  assert.match(await page.locator('.dc-count').innerText(),/12 SOURCES/);
  for(const id of ['wechat','bilibili','announcements','web','news','xiaoyuzhou','xiaoe']){
   assert.equal(await page.locator(`[data-source-update="${id}"]`).first().isDisabled(),true);
   await page.locator(`[data-local-list="${id}"]`).click();
   assert.match(await page.locator('#source-dialog').innerText(),id==='wechat'?/示例公众号/:/清单为空/);
   await page.locator('[data-dialog-close]').click();
  }
  await page.locator('[data-source-llm="wechat"]').click();
  await page.locator('[data-list-prompt]').click();
  assert.match(await page.locator('#source-dialog textarea').inputValue(),/--revision/);
  assert.match(await page.locator('#source-dialog textarea').inputValue(),/不执行下载/);
  await page.locator('[data-dialog-close]').click();
  await page.locator('[data-local-list="wechat"]').click();
  store.change('wechat',1,rows=>[...rows,{name:'终端新增示例'}]);
  await page.waitForFunction(()=>document.querySelector('[data-local-list-view]')?.textContent.includes('终端新增示例'));
  assert.match(await page.locator('[data-local-list="wechat"]').innerText(),/3/);
  await page.locator('[data-dialog-close]').click();
  await page.locator('[data-bulk-source="wechat"]').check();await page.locator('[data-bulk-source="web"]').check();
  await page.locator('[data-bulk-action="verify"]').click();await page.locator('[data-bulk-repair]').click();
  assert.match(await page.locator('#bulk-repair-text').inputValue(),/--source wechat/);
  assert.match(await page.locator('#bulk-repair-text').inputValue(),/--source web/);
  await page.locator('[data-dialog-close]').click();
  await page.locator('[data-bulk-action="llm"]').click();await page.locator('#llm-prompt-options button[type="submit"]').click();
  assert.match(await page.locator('#llm-prompt-nonAudio').inputValue(),/--source wechat/);
  await page.locator('[data-dialog-close]').click();
  const snapshot=path.join(profile,'sources.png');await page.screenshot({path:snapshot,fullPage:true});
  assert.equal((await page.evaluate(()=>window.irSystem.syncGetState())).jobs.length,0);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',profile,snapshot,sourceCalls:0,modelCalls:0,downloads:0}));
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
