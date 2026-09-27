const test=require('node:test'),assert=require('node:assert/strict');
const {makePlan,validateSelection}=require('../src/main/sync/policy');
const {runBatches}=require('../src/main/sync/batch-runner');
const {forButton}=require('../src/shared/update-activity');
const {readiness}=require('../src/main/sync/readiness');
test('verification shows actual native permission failure without claiming library denial',()=>{
 const stamp=new Date().toISOString(),state={settings:{policies:[{provider:'ima',collectionId:'kb',mode:'incremental'}]},jobs:[],catalog:{sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:[]}]}};
 const r=readiness(state,'ima',{localCheck:{status:'ready',checkedAt:stamp,ima:{status:'needs_attention',code:'ima_accessibility_required'}}});
 assert.equal(r.tone,'attention');assert.ok(r.issues.some(i=>i.code==='ima_accessibility_required'));
 assert.ok(!r.issues.some(i=>i.code==='entitlement_denied'));
});
test('explicit multi-source scope keeps dates and excludes unchecked/once sources',()=>{
 const settings={policies:['ima','zsxq','wisburg'].flatMap(provider=>['incremental','once','off','pending_selection'].map(mode=>({provider,collectionId:mode,name:mode,mode,firstDate:'2026-01-01'}))),budgets:{},overlapDays:3};
 for(const kind of ['incremental','backfill']){
  const p=makePlan(settings,{},kind,'/tmp','2026-09-27',{providers:['ima','zsxq'],start:'2026-09-20',end:'2026-09-27'});
  assert.equal(p.collections.length,2);assert.ok(p.collections.every(c=>c.mode==='incremental'&&c.start==='2026-09-20'&&c.end==='2026-09-27'));
 }
 for(const providers of [[],['ima','ima'],['alphapai'],'ima'])assert.throws(()=>validateSelection({providers},'incremental'));
 assert.throws(()=>validateSelection({providers:['ima'],provider:'zsxq'},'incremental'));
});
test('permission grant resumes same checkpoint without holding writer or prompting again',async()=>{
 const request={imaClientEnabled:true,jobDirectory:'/fixture'},calls=[],events=[];let checks=0,runs=0;
 const runner=r=>{calls.push(r);return {stop(){},promise:Promise.resolve(r.command==='ima-permission'?(++checks===2?{status:'completed'}:{status:'needs_attention',code:'ima_accessibility_required'}):++runs===1?{status:'needs_attention',code:'ima_accessibility_required',counts:{downloaded:2}}:{status:'completed',counts:{downloaded:3}})};};
 const result=await runBatches(runner,request,{},{},e=>events.push(e),{permissionPolls:3,permissionDelayMs:0}).promise;
 assert.equal(result.status,'completed');assert.equal(result.counts.downloaded,5);assert.equal(runs,2);assert.equal(checks,2);
 assert.equal(calls[0],calls.at(-1));assert.equal(events[0].stage,'waiting_accessibility');
});
test('permission wait has a bound and a working stop; never grants permission',async()=>{
 const runner=()=>({stop(){},promise:Promise.resolve({status:'needs_attention',code:'ima_accessibility_required'})});
 const result=await runBatches(runner,{imaClientEnabled:true},{},{},()=>{},{permissionPolls:2,permissionDelayMs:0}).promise;
 assert.equal(result.code,'ima_accessibility_required');
 const task=runBatches(runner,{imaClientEnabled:true},{},{},()=>{},{permissionPolls:2,permissionDelayMs:10000});
 await new Promise(setImmediate);task.stop();assert.equal((await task.promise).status,'stopped');
});
test('waiting for OS permission is visible as waiting rather than downloading',()=>{
 const a=forButton([{status:'running',kind:'incremental',stage:'waiting_accessibility',collections:[{provider:'ima'}]}],'ima','incremental');
 assert.equal(a.phase,'等待辅助功能授权');assert.equal(a.waiting,true);assert.equal(a.animate,false);
});
